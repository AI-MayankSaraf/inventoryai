"""
Password reset and change — 04_API_SPECIFICATION.md §2.1, BR-AUTH-02.

Three rules shape this module:

1. **`/auth/forgot-password` never says whether an account exists.** It
   answers 202 for every well-formed address. Anything else turns the
   endpoint into a free account-enumeration oracle, which matters more here
   than the small convenience of "no account with that email".
2. **Only the hash of a reset token is stored**, exactly as refresh tokens
   are. The link that goes out in the email is the only copy.
3. **A completed reset ends every other session.** Resetting a password is
   what you do when you think someone else has it, so leaving their refresh
   tokens alive would defeat the point (`deps.revoke_sessions`, which also
   bumps `users.sessions_revoked_at` so access tokens already issued stop
   being accepted).

Tokens live one hour, are single-use, and a new request invalidates any
earlier unused one for that user — a mailbox with three links in it should
not have three working keys.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import get_settings
from app.core.deps import revoke_sessions
from app.core.errors import CODE_INVALID_CREDENTIALS, CODE_INVALID_RESET_TOKEN, ApiError
from app.core.security import (
    generate_reset_token,
    hash_password,
    hash_reset_token,
    validate_password_strength,
    verify_password,
)
from app.modules.notifications import email as email_service

logger = logging.getLogger("app.auth.password")

RESET_TTL_MINUTES = 60


async def request_reset(
    session: AsyncSession, *, email: str, request: Optional[Request] = None
) -> Optional[tuple[UUID, UUID, str]]:
    """Issue a reset token for `email` if it belongs to an account that can
    actually sign in. Returns (message_id, user_id, raw_token) so the caller
    can send the mail after committing, or None when there is nothing to do
    — the caller answers 202 either way.
    """
    row = (
        await session.execute(
            text(
                "SELECT u.id, u.company_id, u.email, u.full_name, u.status, c.status AS company_status, "
                "COALESCE(c.name, '') AS company_name "
                "FROM users u LEFT JOIN companies c ON c.id = u.company_id "
                "WHERE lower(u.email) = lower(:email) AND u.deleted_at IS NULL"
            ),
            {"email": email},
        )
    ).mappings().first()

    if row is None or row["status"] != "active" or row["company_status"] == "suspended":
        # Recorded so a burst of probes is visible in the audit trail even
        # though the response is identical either way.
        await audit.record(
            session,
            entity_type="user",
            action="password_reset",
            entity_label=email,
            description="Reset requested for an address with no usable account",
            request=request,
        )
        return None

    # One live link per mailbox.
    await session.execute(
        text("UPDATE password_reset_tokens SET used_at = now() WHERE user_id = :u AND used_at IS NULL"),
        {"u": row["id"]},
    )

    raw, token_hash = generate_reset_token()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=RESET_TTL_MINUTES)
    await session.execute(
        text(
            "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at, requested_ip, requested_user_agent) "
            "VALUES (:u, :hash, :expires, CAST(:ip AS inet), :ua)"
        ),
        {
            "u": row["id"],
            "hash": token_hash,
            "expires": expires_at,
            "ip": request.client.host if request and request.client else None,
            "ua": request.headers.get("user-agent") if request else None,
        },
    )

    spec = email_service.password_reset_email(
        full_name=row["full_name"] or row["email"],
        company_name=row["company_name"] or "your company",
        token=raw,
        ttl_minutes=RESET_TTL_MINUTES,
    )
    spec.to = row["email"]
    message_id = await email_service.record_outbound(
        session,
        company_id=row["company_id"],
        message_type="password_reset",
        to_address=row["email"],
        subject=spec.subject,
        body_preview=spec.body,
        sent_by=row["id"],
    )

    await audit.record(
        session,
        entity_type="user",
        action="password_reset",
        entity_id=row["id"],
        entity_label=row["email"],
        company_id=row["company_id"],
        actor_user_id=row["id"],
        description="Reset link requested",
        request=request,
    )
    return message_id, row["id"], raw


async def complete_reset(
    session: AsyncSession, *, raw_token: str, new_password: str, request: Optional[Request] = None
) -> UUID:
    """Consume a reset token and set the new password. Raises
    `422 INVALID_RESET_TOKEN` for anything not currently usable — unknown,
    already used, or expired all give the same answer, since telling them
    apart only helps someone guessing."""
    validate_password_strength(new_password)

    row = (
        await session.execute(
            text(
                "SELECT t.id, t.user_id, t.used_at, t.expires_at, u.email, u.company_id, u.status, u.deleted_at "
                "FROM password_reset_tokens t JOIN users u ON u.id = t.user_id "
                "WHERE t.token_hash = :hash"
            ),
            {"hash": hash_reset_token(raw_token)},
        )
    ).mappings().first()

    now = datetime.now(timezone.utc)
    if (
        row is None
        or row["used_at"] is not None
        or row["expires_at"] <= now
        or row["deleted_at"] is not None
        or row["status"] != "active"
    ):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_INVALID_RESET_TOKEN,
            "This reset link is no longer valid. Request a new one.",
        )

    await session.execute(
        text(
            "UPDATE users SET password_hash = :pw, password_changed_at = now(), "
            "failed_login_count = 0, locked_until = NULL WHERE id = :u"
        ),
        {"pw": hash_password(new_password), "u": row["user_id"]},
    )
    await session.execute(
        text("UPDATE password_reset_tokens SET used_at = now() WHERE id = :id"), {"id": row["id"]}
    )
    # A reset is a "someone else may have my password" action: end every
    # session, not just the ones on this device.
    await revoke_sessions(session, user_id=row["user_id"])

    await audit.record(
        session,
        entity_type="user",
        action="password_reset",
        entity_id=row["user_id"],
        entity_label=row["email"],
        company_id=row["company_id"],
        actor_user_id=row["user_id"],
        description="Password reset completed; all sessions ended",
        request=request,
    )
    return row["user_id"]


async def change_password(
    session: AsyncSession,
    *,
    user_id: str,
    current_password: str,
    new_password: str,
    request: Optional[Request] = None,
) -> None:
    """Change your own password. The current one is required — an unlocked
    laptop should not be enough to lock the owner out of their account."""
    row = (
        await session.execute(
            text("SELECT id, email, company_id, password_hash FROM users WHERE id = :id AND deleted_at IS NULL"),
            {"id": user_id},
        )
    ).mappings().first()
    if row is None or not row["password_hash"] or not verify_password(current_password, row["password_hash"]):
        raise ApiError(status.HTTP_401_UNAUTHORIZED, CODE_INVALID_CREDENTIALS, "Your current password is incorrect")

    validate_password_strength(new_password)
    if verify_password(new_password, row["password_hash"]):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_INVALID_RESET_TOKEN,
            "The new password must be different from the current one",
        )

    await session.execute(
        text("UPDATE users SET password_hash = :pw, password_changed_at = now() WHERE id = :u"),
        {"pw": hash_password(new_password), "u": row["id"]},
    )
    await revoke_sessions(session, user_id=row["id"])

    await audit.record(
        session,
        entity_type="user",
        action="password_changed",
        entity_id=row["id"],
        entity_label=row["email"],
        company_id=row["company_id"],
        actor_user_id=row["id"],
        description="Password changed; other sessions ended",
        request=request,
    )


def settings_app_base_url() -> str:
    return get_settings().app_base_url.rstrip("/")
