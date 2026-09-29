"""
Supplier Portal — what a supplier's contact can do and see.

Two sides:

* **The company** (a tenant user with `supplier.update`) grants a contact
  access to one of its supplier records. The first grant creates the portal
  account and emails a one-time set-password link; later grants from other
  companies attach to the same account.
* **The supplier** signs in with that account and sees, per granted
  (company, supplier) pair, the RFQs sent to them, their quotations and the
  purchase orders placed with them. Read-only.

Isolation is the whole point, so it is enforced in one place:
`_activity()` only ever filters by the `company_id` *and* `supplier_id` of
an access row that belongs to the signed-in account and is still active.
Nothing in a portal request takes a company or supplier id from the client
on trust.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import Request, status
from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import get_settings
from app.core.errors import (
    CODE_INVALID_CREDENTIALS,
    CODE_INVALID_RESET_TOKEN,
    CODE_NOT_FOUND,
    CODE_RATE_LIMITED,
    CODE_UNAUTHENTICATED,
    CODE_VALIDATION,
    ApiError,
)
from app.core.security import JWT_ALGORITHM, hash_password, validate_password_strength, verify_password
from app.modules.notifications import email as email_service

TOKEN_TYPE = "supplier_access"
ACCESS_TTL_HOURS = 8
LINK_TTL_DAYS = 7

#: A supplier sees a PO once it has been sent to them — not while the buyer
#: is still drafting or approving it.
VISIBLE_PO_STATUSES = ("sent", "acknowledged", "partially_received", "received", "closed")


# ------------------------------------------------------------------ tokens


def create_token(account_id: UUID) -> tuple[str, int]:
    """A JWT with its own `type`. Every tenant endpoint decodes with
    `decode_access_token`, which refuses anything but `type=access`, so a
    portal token can never reach tenant data even though it shares the key."""
    now = datetime.now(timezone.utc)
    ttl = ACCESS_TTL_HOURS * 3600
    payload = {
        "sub": str(account_id),
        "type": TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "iat_ms": int(now.timestamp() * 1000),
        "exp": int(now.timestamp()) + ttl,
    }
    return jwt.encode(payload, get_settings().jwt_secret, algorithm=JWT_ALGORITHM), ttl


def decode_token(token: str) -> tuple[str, datetime]:
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, CODE_UNAUTHENTICATED, "Sign in again")
    if payload.get("type") != TOKEN_TYPE:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, CODE_UNAUTHENTICATED, "Sign in again")
    issued = datetime.fromtimestamp(payload.get("iat_ms", payload["iat"] * 1000) / 1000, tz=timezone.utc)
    return payload["sub"], issued


def _new_link_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


# ------------------------------------------------------------------ account


async def current_account(session: AsyncSession, token: str) -> dict:
    """The signed-in account, checked against the database on every request
    so disabling it, or resetting its password, takes effect at once."""
    account_id, issued = decode_token(token)
    row = (
        await session.execute(
            text(
                "SELECT id, email, full_name, status, password_changed_at FROM supplier_portal_accounts "
                "WHERE id = :id"
            ),
            {"id": account_id},
        )
    ).mappings().first()
    if row is None or row["status"] != "active":
        raise ApiError(status.HTTP_401_UNAUTHORIZED, CODE_UNAUTHENTICATED, "Sign in again")
    changed = row["password_changed_at"]
    if changed is not None and issued < changed - timedelta(seconds=1):
        raise ApiError(status.HTTP_401_UNAUTHORIZED, CODE_UNAUTHENTICATED, "Sign in again")
    return dict(row)


async def principal(session: AsyncSession, account: dict) -> dict:
    """The account plus every (company, supplier) it may act for."""
    rows = (
        await session.execute(
            text(
                "SELECT a.id AS access_id, c.id AS company_id, c.name AS company_name, "
                "       COALESCE(c.city, '') AS city, COALESCE(c.state_name, '') AS state_name, "
                "       s.id AS supplier_id, s.name AS supplier_name "
                "  FROM supplier_portal_access a "
                "  JOIN companies c ON c.id = a.company_id "
                "  JOIN suppliers s ON s.id = a.supplier_id AND s.company_id = a.company_id "
                " WHERE a.account_id = :acc AND a.status = 'active' "
                "   AND c.status = 'active' AND c.deleted_at IS NULL AND s.deleted_at IS NULL "
                " ORDER BY c.name, s.name"
            ),
            {"acc": account["id"]},
        )
    ).mappings().all()
    return {
        "id": account["id"],
        "email": account["email"],
        "full_name": account["full_name"],
        "companies": [dict(r) for r in rows],
    }


async def login(session: AsyncSession, *, email: str, password: str, request: Optional[Request]) -> dict:
    settings = get_settings()
    row = (
        await session.execute(
            text(
                "SELECT id, email, full_name, status, password_hash, locked_until FROM supplier_portal_accounts "
                "WHERE lower(email) = lower(:e)"
            ),
            {"e": email.strip()},
        )
    ).mappings().first()
    now = datetime.now(timezone.utc)
    if row and row["locked_until"] and row["locked_until"] > now:
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            CODE_RATE_LIMITED,
            "Too many failed attempts. Try again later.",
            headers={"Retry-After": str(max(1, int((row["locked_until"] - now).total_seconds())))},
        )
    ok = bool(
        row and row["status"] == "active" and row["password_hash"] and verify_password(password, row["password_hash"])
    )
    if not ok:
        if row:
            await session.execute(
                text(
                    "UPDATE supplier_portal_accounts SET failed_login_count = failed_login_count + 1, "
                    " locked_until = CASE WHEN failed_login_count + 1 >= :max "
                    "   THEN now() + make_interval(mins => :mins) ELSE locked_until END WHERE id = :id"
                ),
                {"id": row["id"], "max": settings.login_max_failed_attempts, "mins": settings.login_lockout_minutes},
            )
            await session.commit()
        raise ApiError(status.HTTP_401_UNAUTHORIZED, CODE_INVALID_CREDENTIALS, "That email and password don't match a supplier account.")

    await session.execute(
        text(
            "UPDATE supplier_portal_accounts SET failed_login_count = 0, locked_until = NULL, "
            "last_login_at = now() WHERE id = :id"
        ),
        {"id": row["id"]},
    )
    await session.commit()
    token, ttl = create_token(row["id"])
    account = {"id": row["id"], "email": row["email"], "full_name": row["full_name"]}
    return {"access_token": token, "token_type": "bearer", "expires_in": ttl, "principal": await principal(session, account)}


async def set_password(session: AsyncSession, *, token: str, password: str) -> dict:
    """Redeem an emailed link: first sign-in for a new account, or a reset."""
    validate_password_strength(password)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = (
        await session.execute(
            text(
                "SELECT t.id, t.account_id, t.expires_at, t.used_at, a.email, a.full_name, a.status "
                "FROM supplier_portal_tokens t JOIN supplier_portal_accounts a ON a.id = t.account_id "
                "WHERE t.token_hash = :h"
            ),
            {"h": token_hash},
        )
    ).mappings().first()
    if row is None or row["used_at"] is not None or row["expires_at"] < datetime.now(timezone.utc) or row["status"] == "disabled":
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            CODE_INVALID_RESET_TOKEN,
            "This link has expired or was already used. Ask the company to send a new one.",
        )
    await session.execute(text("UPDATE supplier_portal_tokens SET used_at = now() WHERE id = :id"), {"id": row["id"]})
    await session.execute(
        text(
            "UPDATE supplier_portal_accounts SET password_hash = :pw, status = 'active', "
            "password_changed_at = now(), failed_login_count = 0, locked_until = NULL WHERE id = :id"
        ),
        {"pw": hash_password(password), "id": row["account_id"]},
    )
    await session.commit()
    return {"email": row["email"]}


# ----------------------------------------------------------------- activity


async def activity(session: AsyncSession, *, account: dict, access_id: UUID) -> dict:
    grant = (
        await session.execute(
            text(
                "SELECT a.company_id, a.supplier_id FROM supplier_portal_access a "
                "JOIN companies c ON c.id = a.company_id "
                "WHERE a.id = :id AND a.account_id = :acc AND a.status = 'active' AND c.status = 'active'"
            ),
            {"id": access_id, "acc": account["id"]},
        )
    ).mappings().first()
    if grant is None:
        # Same answer whether it doesn't exist or isn't theirs.
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Not found")
    c, s = grant["company_id"], grant["supplier_id"]
    rfqs = (
        await session.execute(
            text(
                "SELECT r.id, r.rfq_number AS number, COALESCE(r.subject, '') AS subject, r.rfq_date AS date, "
                "       r.expected_delivery_date AS expected, rs.status AS invitation_status, r.status, "
                "       (SELECT count(*) FROM rfq_items i WHERE i.rfq_id = r.id AND i.company_id = r.company_id) AS line_count "
                "  FROM rfq_suppliers rs JOIN rfqs r ON r.id = rs.rfq_id AND r.company_id = rs.company_id "
                " WHERE rs.company_id = :c AND rs.supplier_id = :s AND r.status <> 'draft' "
                " ORDER BY r.rfq_date DESC, r.rfq_number DESC LIMIT 100"
            ),
            {"c": c, "s": s},
        )
    ).mappings().all()
    quotations = (
        await session.execute(
            text(
                "SELECT q.id, q.quotation_number AS number, COALESCE(r.rfq_number, '') AS rfq_number, "
                "       q.quotation_date AS date, q.valid_until, q.status, q.total_amount "
                "  FROM supplier_quotations q LEFT JOIN rfqs r ON r.id = q.rfq_id AND r.company_id = q.company_id "
                " WHERE q.company_id = :c AND q.supplier_id = :s "
                " ORDER BY q.quotation_date DESC NULLS LAST, q.quotation_number DESC LIMIT 100"
            ),
            {"c": c, "s": s},
        )
    ).mappings().all()
    pos = (
        await session.execute(
            text(
                "SELECT p.id, p.po_number AS number, p.po_date AS date, p.expected_delivery_date AS expected, "
                "       p.status, p.total_amount, "
                "       (SELECT count(*) FROM purchase_order_items i WHERE i.purchase_order_id = p.id "
                "          AND i.company_id = p.company_id) AS line_count "
                "  FROM purchase_orders p "
                " WHERE p.company_id = :c AND p.supplier_id = :s AND p.status = ANY(:visible) "
                " ORDER BY p.po_date DESC, p.po_number DESC LIMIT 100"
            ),
            {"c": c, "s": s, "visible": list(VISIBLE_PO_STATUSES)},
        )
    ).mappings().all()
    return {"rfqs": [dict(r) for r in rfqs], "quotations": [dict(r) for r in quotations], "purchase_orders": [dict(r) for r in pos]}


# ------------------------------------------------ company side: grant access


async def list_access(session: AsyncSession, *, company_id: str, supplier_id: UUID) -> list[dict]:
    rows = (
        await session.execute(
            text(
                "SELECT a.id, acc.id AS account_id, acc.email, acc.full_name, a.status, acc.status AS account_status, "
                "       a.granted_at, acc.last_login_at "
                "  FROM supplier_portal_access a JOIN supplier_portal_accounts acc ON acc.id = a.account_id "
                " WHERE a.company_id = :c AND a.supplier_id = :s "
                " ORDER BY a.status, acc.full_name"
            ),
            {"c": company_id, "s": supplier_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def _supplier(session: AsyncSession, company_id: str, supplier_id: UUID) -> dict:
    row = (
        await session.execute(
            text(
                "SELECT s.id, s.name, c.name AS company_name FROM suppliers s JOIN companies c ON c.id = s.company_id "
                "WHERE s.id = :s AND s.company_id = :c AND s.deleted_at IS NULL"
            ),
            {"s": supplier_id, "c": company_id},
        )
    ).mappings().first()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Supplier not found")
    return dict(row)


async def _queue_link(session: AsyncSession, *, company_id: str, account: dict, supplier: dict, sent_by: str, new_account: bool):
    raw, token_hash = _new_link_token()
    await session.execute(
        text("UPDATE supplier_portal_tokens SET used_at = now() WHERE account_id = :a AND used_at IS NULL"),
        {"a": account["id"]},
    )
    await session.execute(
        text(
            "INSERT INTO supplier_portal_tokens (account_id, token_hash, expires_at) "
            "VALUES (:a, :h, now() + make_interval(days => :d))"
        ),
        {"a": account["id"], "h": token_hash, "d": LINK_TTL_DAYS},
    )
    link = f"{get_settings().app_base_url.rstrip('/')}/supplier-portal/set-password?token={raw}"
    body = (
        f"Hello {account['full_name']},\n\n"
        f"{supplier['company_name']} has given you access to its Supplier Portal as {supplier['name']}.\n\n"
        f"{'Set your password' if new_account else 'Set a new password'} here (valid {LINK_TTL_DAYS} days, once):\n{link}"
    )
    return await email_service.record_outbound(
        session,
        company_id=company_id,
        message_type="supplier_portal_invite",
        to_address=account["email"],
        subject=f"Supplier Portal access — {supplier['company_name']}",
        body_preview=body,
        related_type="supplier",
        related_id=supplier["id"],
        sent_by=sent_by,
    )


async def grant_access(
    session: AsyncSession, *, claims, supplier_id: UUID, email: str, full_name: str, request: Optional[Request]
) -> tuple[dict, Optional[UUID]]:
    """Give a contact portal access to this supplier record. Returns the
    grant and, when an email needs sending, its queued message id."""
    email = email.strip().lower()
    if "@" not in email or len(email) < 5:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_VALIDATION, "Enter a valid email address")
    supplier = await _supplier(session, claims.company_id, supplier_id)

    account = (
        await session.execute(
            text("SELECT id, email, full_name, status FROM supplier_portal_accounts WHERE lower(email) = :e"),
            {"e": email},
        )
    ).mappings().first()
    new_account = account is None
    if new_account:
        account = (
            await session.execute(
                text(
                    "INSERT INTO supplier_portal_accounts (email, full_name) VALUES (:e, :n) "
                    "RETURNING id, email, full_name, status"
                ),
                {"e": email, "n": full_name.strip() or email},
            )
        ).mappings().one()
    account = dict(account)
    if account["status"] == "disabled":
        raise ApiError(status.HTTP_409_CONFLICT, CODE_VALIDATION, "This portal account has been disabled")

    access = (
        await session.execute(
            text(
                "INSERT INTO supplier_portal_access (company_id, account_id, supplier_id, granted_by) "
                "VALUES (:c, :a, :s, :by) "
                "ON CONFLICT (company_id, account_id, supplier_id) DO UPDATE SET status = 'active', "
                " revoked_at = NULL, granted_by = EXCLUDED.granted_by, granted_at = now() "
                "RETURNING id"
            ),
            {"c": claims.company_id, "a": account["id"], "s": supplier_id, "by": claims.user_id},
        )
    ).scalar_one()

    message_id = None
    if account["status"] == "invited":
        # They have never set a password: send (or re-send) the link.
        message_id = await _queue_link(
            session, company_id=claims.company_id, account=account, supplier=supplier,
            sent_by=claims.user_id, new_account=True,
        )
    await audit.record(
        session, entity_type="supplier_portal_access", action="invited", claims=claims, entity_id=access,
        entity_label=f"{email} → {supplier['name']}", description="Supplier Portal access granted", request=request,
    )
    await session.commit()
    rows = await list_access(session, company_id=claims.company_id, supplier_id=supplier_id)
    return next(r for r in rows if r["id"] == access), message_id


async def resend_link(session: AsyncSession, *, claims, supplier_id: UUID, access_id: UUID) -> UUID:
    """A fresh set-password link — also how a supplier who forgot their
    password gets back in."""
    supplier = await _supplier(session, claims.company_id, supplier_id)
    account = (
        await session.execute(
            text(
                "SELECT acc.id, acc.email, acc.full_name, acc.status FROM supplier_portal_access a "
                "JOIN supplier_portal_accounts acc ON acc.id = a.account_id "
                "WHERE a.id = :id AND a.company_id = :c AND a.supplier_id = :s AND a.status = 'active'"
            ),
            {"id": access_id, "c": claims.company_id, "s": supplier_id},
        )
    ).mappings().first()
    if account is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Access not found")
    message_id = await _queue_link(
        session, company_id=claims.company_id, account=dict(account), supplier=supplier,
        sent_by=claims.user_id, new_account=account["status"] == "invited",
    )
    await session.commit()
    return message_id


async def revoke_access(session: AsyncSession, *, claims, supplier_id: UUID, access_id: UUID, request: Optional[Request]) -> None:
    result = await session.execute(
        text(
            "UPDATE supplier_portal_access SET status = 'revoked', revoked_at = now() "
            "WHERE id = :id AND company_id = :c AND supplier_id = :s AND status = 'active' RETURNING id"
        ),
        {"id": access_id, "c": claims.company_id, "s": supplier_id},
    )
    if result.scalar_one_or_none() is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Access not found")
    await audit.record(
        session, entity_type="supplier_portal_access", action="removed", claims=claims, entity_id=access_id,
        description="Supplier Portal access revoked", request=request,
    )
    await session.commit()

