"""
The platform console — every tenant on the installation, not one of them.

Everything here runs on the BYPASSRLS platform session, because that is the
point: a platform admin's token carries no `company_id` at all, so there is
no tenant to scope to. That makes the permission check the only thing
standing between this module and every company's data, so each endpoint
goes through `require_platform_admin` and nothing here ever reads a company
id from the request body as if it were authorisation.

Onboarding a company creates the same shape `app/db/seed.py` creates for the
demo tenant — company, settings, a default godown, one document-sequence row
per document type — and then *invites* the owner rather than setting a
password for them. A password chosen by whoever pressed the button is a
password the owner never picked.
"""

from __future__ import annotations

import json
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

from fastapi import Request, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, company_lists
from app.modules.platform import plans_service
from app.core import audit
from app.core.deps import revoke_sessions
from app.core.errors import CODE_DUPLICATE, CODE_FORBIDDEN, CODE_NOT_FOUND, CODE_VALIDATION, ApiError
from app.core.security import AccessTokenClaims, hash_refresh_token
from app.db.seed import DOC_PREFIXES, DOC_TYPES, _financial_year
from app.modules.notifications import email as email_service

INVITATION_TTL_DAYS = 7

_COMPANY_COLUMNS = (
    "c.id, c.name, c.legal_name, c.gstin, c.pan, c.state_code, c.state_name, c.city, "
    "c.email, c.phone, c.plan, c.status, c.suspended_at, c.suspended_reason, c.onboarded_on"
)

_COMPANY_ROW = f"""
    SELECT {_COMPANY_COLUMNS},
           (SELECT COUNT(*) FROM users u
             WHERE u.company_id = c.id AND u.deleted_at IS NULL) AS user_count,
           (SELECT COUNT(*) FROM product_variants pv
             WHERE pv.company_id = c.id AND pv.deleted_at IS NULL) AS sku_count,
           COALESCE((SELECT u.full_name FROM users u JOIN roles r ON r.id = u.role_id
                      WHERE u.company_id = c.id AND r.code = 'owner' AND u.deleted_at IS NULL
                      ORDER BY u.created_at LIMIT 1),
                    (SELECT u.full_name FROM company_users cu JOIN users u ON u.id = cu.user_id
                      JOIN roles r ON r.id = cu.role_id
                      WHERE cu.company_id = c.id AND r.code = 'owner' AND cu.status = 'active'
                        AND u.deleted_at IS NULL
                      ORDER BY cu.added_at LIMIT 1), '') AS owner_name,
           COALESCE((SELECT u.email FROM users u JOIN roles r ON r.id = u.role_id
                      WHERE u.company_id = c.id AND r.code = 'owner' AND u.deleted_at IS NULL
                      ORDER BY u.created_at LIMIT 1),
                    (SELECT u.email FROM company_users cu JOIN users u ON u.id = cu.user_id
                      JOIN roles r ON r.id = cu.role_id
                      WHERE cu.company_id = c.id AND r.code = 'owner' AND cu.status = 'active'
                        AND u.deleted_at IS NULL
                      ORDER BY cu.added_at LIMIT 1),
                    (SELECT i.email FROM invitations i JOIN roles r ON r.id = i.role_id
                      WHERE i.company_id = c.id AND r.code = 'owner' AND i.status = 'pending'
                      ORDER BY i.invited_at LIMIT 1), '') AS owner_email
    FROM companies c
"""


async def kpis(session: AsyncSession) -> dict:
    row = (
        await session.execute(
            text(
                "SELECT COUNT(*) AS companies, "
                "COUNT(*) FILTER (WHERE status = 'active') AS active_companies, "
                "COUNT(*) FILTER (WHERE status = 'suspended') AS suspended_companies, "
                "(SELECT COUNT(*) FROM users WHERE deleted_at IS NULL AND NOT is_platform_admin) AS users, "
                "(SELECT COUNT(*) FROM users WHERE deleted_at IS NULL AND NOT is_platform_admin "
                " AND last_login_at > now() - interval '30 days') AS active_users_30d "
                "FROM companies WHERE deleted_at IS NULL"
            )
        )
    ).mappings().one()
    return dict(row)


async def list_companies(
    session: AsyncSession,
    *,
    q: Optional[str] = None,
    status_filter: Optional[str] = None,
    plan: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    where = ["c.deleted_at IS NULL"]
    params: dict = {"limit": limit, "offset": offset}
    if q:
        where.append(
            "(c.name ILIKE :q OR c.gstin ILIKE :q OR c.city ILIKE :q OR c.state_name ILIKE :q)"
        )
        params["q"] = f"%{q.strip()}%"
    if status_filter:
        where.append("c.status = :status_filter")
        params["status_filter"] = status_filter
    if plan:
        where.append("c.plan = :plan")
        params["plan"] = plan

    rows = (
        await session.execute(
            text(f"{_COMPANY_ROW} WHERE {' AND '.join(where)} ORDER BY c.name LIMIT :limit OFFSET :offset"),
            params,
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def get_company(session: AsyncSession, company_id: UUID) -> dict:
    row = (
        await session.execute(
            text(f"{_COMPANY_ROW} WHERE c.id = :id AND c.deleted_at IS NULL"), {"id": company_id}
        )
    ).mappings().first()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Company not found")
    return dict(row)


async def onboard_company(
    session: AsyncSession, *, claims: AccessTokenClaims, body, request: Optional[Request] = None
) -> tuple[dict, Optional[UUID], Optional[str]]:
    """Create a tenant and invite its first Owner.

    Returns (company, outbound message id, raw invite token) — the caller
    sends the mail after committing, exactly as `/users/invite` does.
    """
    clash = (
        await session.execute(
            text("SELECT id FROM companies WHERE lower(name) = lower(:n) AND deleted_at IS NULL"),
            {"n": body.name.strip()},
        )
    ).scalar_one_or_none()
    if clash:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_DUPLICATE,
            "A company with that name already exists",
            errors=[{"field": "name", "message": "Already used by another company"}],
        )
    # BR-AUTH-13: an owner email that already has a login is the "one
    # person, a second company" case. Rather than refuse it, the new company
    # is linked to that login (a `company_users` row) — they switch into it
    # from the header, with no second account and no invitation mail.
    # Platform admins and inactive accounts are still refused.
    existing_owner = (
        await session.execute(
            text(
                "SELECT id, is_platform_admin, status FROM users "
                "WHERE lower(email) = lower(:e) AND deleted_at IS NULL"
            ),
            {"e": body.owner_email},
        )
    ).mappings().first()
    if existing_owner is not None and (existing_owner["is_platform_admin"] or existing_owner["status"] != "active"):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_DUPLICATE,
            "That email belongs to an account that cannot own a company",
            errors=[{"field": "owner_email", "message": "Belongs to a platform admin or an inactive account"}],
        )

    await plans_service.assert_assignable(session, body.plan)

    company_id = uuid4()
    try:
        await session.execute(
            text(
                "INSERT INTO companies (id, name, legal_name, gstin, state_code, state_name, city, "
                " email, phone, plan, status, onboarded_on) "
                "VALUES (:id, :name, :legal_name, :gstin, :state_code, :state_name, :city, "
                " :email, :phone, :plan, 'active', CURRENT_DATE)"
            ),
            {
                "id": company_id,
                "name": body.name.strip(),
                "legal_name": (body.legal_name or "").strip() or None,
                "gstin": (body.gstin or "").strip().upper() or None,
                "state_code": body.state_code,
                "state_name": body.state_name,
                "city": (body.city or "").strip() or None,
                "email": (body.email or "").strip() or None,
                "phone": (body.phone or "").strip() or None,
                "plan": body.plan,
            },
        )
    except IntegrityError as exc:
        if "uq_companies_gstin" in str(exc.orig):
            raise ApiError(
                status.HTTP_409_CONFLICT,
                CODE_DUPLICATE,
                "That GSTIN already belongs to another company",
                errors=[{"field": "gstin", "message": "Already registered"}],
            )
        raise

    # The default godown carries the company's own state code: every PO
    # delivered there needs it to decide CGST+SGST vs IGST, and a null one
    # 422s at approval time with no obvious cause (same reasoning as
    # `seed_demo_company`).
    godown_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO godowns (id, company_id, name, code, is_default, city, state_code) "
            "VALUES (:id, :c, 'Main Warehouse', 'MAIN', true, :city, :state_code)"
        ),
        {"id": godown_id, "c": company_id, "city": (body.city or "").strip() or None, "state_code": body.state_code},
    )
    await session.execute(
        text("INSERT INTO company_settings (company_id, default_godown_id) VALUES (:c, :g)"),
        {"c": company_id, "g": godown_id},
    )
    await company_lists.seed_defaults(session, company_id)

    fy = _financial_year()
    for doc_type in DOC_TYPES:
        await session.execute(
            text(
                "INSERT INTO document_sequences (company_id, doc_type, financial_year, prefix) "
                "VALUES (:c, :doc_type, :fy, :prefix)"
            ),
            {"c": company_id, "doc_type": doc_type, "fy": fy, "prefix": f"{DOC_PREFIXES[doc_type]}{fy}-"},
        )

    owner_role_id = (
        await session.execute(text("SELECT id FROM roles WHERE company_id IS NULL AND code = 'owner'"))
    ).scalar_one()

    if existing_owner is not None:
        await session.execute(
            text(
                "INSERT INTO company_users (user_id, company_id, role_id, added_by) "
                "VALUES (:u, :c, :r, :by)"
            ),
            {"u": existing_owner["id"], "c": company_id, "r": owner_role_id, "by": claims.user_id},
        )
        await audit.record(
            session,
            entity_type="company",
            action="created",
            entity_id=company_id,
            entity_label=body.name.strip(),
            company_id=company_id,
            actor_user_id=UUID(claims.user_id),
            actor_role="super_admin",
            description=(
                f"Onboarded on the {body.plan} plan; existing login {body.owner_email} "
                "linked as Owner (multi-company)"
            ),
            request=request,
        )
        return await get_company(session, company_id), None, None

    _, message_id, raw_token, _ = await _issue_owner_invitation(
        session,
        claims=claims,
        company_id=company_id,
        company_name=body.name.strip(),
        email=body.owner_email,
        full_name=body.owner_full_name,
        owner_role_id=owner_role_id,
    )

    await audit.record(
        session,
        entity_type="company",
        action="created",
        entity_id=company_id,
        entity_label=body.name.strip(),
        company_id=company_id,
        actor_user_id=UUID(claims.user_id),
        actor_role="super_admin",
        description=f"Onboarded on the {body.plan} plan; {body.owner_email} invited as Owner",
        request=request,
    )
    return await get_company(session, company_id), message_id, raw_token


async def _issue_owner_invitation(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    company_id: UUID,
    company_name: str,
    email: str,
    full_name: str,
    owner_role_id: Optional[UUID] = None,
) -> tuple[UUID, UUID, str, datetime]:
    """Insert an Owner invitation and record its email, in the caller's
    transaction. Shared by onboarding and "Invite owner". Returns
    (invitation id, outbound message id, raw token, expiry); the caller
    sends the mail after committing."""
    if owner_role_id is None:
        owner_role_id = (
            await session.execute(text("SELECT id FROM roles WHERE company_id IS NULL AND code = 'owner'"))
        ).scalar_one()
    raw_token = secrets.token_urlsafe(32)
    invitation_id = uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(days=INVITATION_TTL_DAYS)
    await session.execute(
        text(
            "INSERT INTO invitations (id, company_id, email, full_name, role_id, godown_scope, "
            " token_hash, invited_by, expires_at, last_sent_at) "
            "VALUES (:id, :c, :email, :full_name, :role_id, 'all', :token_hash, :invited_by, "
            " :expires_at, now())"
        ),
        {
            "id": invitation_id,
            "c": company_id,
            "email": email,
            "full_name": full_name,
            "role_id": owner_role_id,
            "token_hash": hash_refresh_token(raw_token),
            "invited_by": claims.user_id,
            "expires_at": expires_at,
        },
    )

    spec = email_service.invitation_email(
        full_name=full_name,
        company_name=company_name,
        invited_by="The InventoryAI team",
        token=raw_token,
    )
    spec.to = email
    message_id = await email_service.record_outbound(
        session,
        company_id=company_id,
        message_type="invitation",
        to_address=email,
        subject=spec.subject,
        body_preview=spec.body,
        related_type="invitation",
        related_id=invitation_id,
        sent_by=claims.user_id,
    )
    return invitation_id, message_id, raw_token, expires_at


async def invite_owner(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    company_id: UUID,
    email: str,
    full_name: str,
    request: Optional[Request] = None,
) -> tuple[dict, UUID, str]:
    """Invite an additional Owner to an existing company — the console's
    answer to BR-AUTH-10: replace an Owner by adding the new one first.

    Someone who already has a login is pointed at Linked owners instead:
    a second account for the same email is not possible, and linking is
    how an existing login gets into another company."""
    company = await get_company(session, company_id)
    email = email.strip()
    full_name = full_name.strip()
    existing = (
        await session.execute(
            text("SELECT company_id FROM users WHERE lower(email) = lower(:e) AND deleted_at IS NULL"),
            {"e": email},
        )
    ).mappings().first()
    if existing is not None:
        same_company = str(existing["company_id"]) == str(company_id)
        message = (
            "That person is already a user of this company"
            if same_company
            else "That email already has a login — add them under Linked owners instead"
        )
        raise ApiError(
            status.HTTP_409_CONFLICT, CODE_DUPLICATE, message, errors=[{"field": "email", "message": message}]
        )

    try:
        invitation_id, message_id, raw_token, expires_at = await _issue_owner_invitation(
            session,
            claims=claims,
            company_id=company_id,
            company_name=company["name"],
            email=email,
            full_name=full_name,
        )
    except IntegrityError:
        message = "There is already a pending invitation for this email — resend it instead"
        raise ApiError(
            status.HTTP_409_CONFLICT, CODE_DUPLICATE, message, errors=[{"field": "email", "message": message}]
        )

    await audit.record(
        session,
        entity_type="invitation",
        action="invited",
        entity_id=invitation_id,
        entity_label=email,
        company_id=company_id,
        actor_user_id=UUID(claims.user_id),
        actor_role="super_admin",
        description="Invited as Owner from the platform console",
        request=request,
    )
    return (
        {"id": invitation_id, "email": email, "full_name": full_name, "expires_at": expires_at},
        message_id,
        raw_token,
    )


async def update_company(
    session: AsyncSession, *, claims: AccessTokenClaims, company_id: UUID, values: dict, request: Optional[Request] = None
) -> dict:
    before = await get_company(session, company_id)
    fields = {k: v for k, v in values.items() if k in (
        "name", "legal_name", "gstin", "pan", "state_code", "state_name", "city", "email", "phone", "plan"
    )}
    if not fields:
        return before
    if "name" in fields and not (fields["name"] or "").strip():
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_VALIDATION, "A company needs a name")
    if "plan" in fields:
        await plans_service.assert_assignable(session, fields["plan"], current=before["plan"])

    assignments = ", ".join(f"{k} = :{k}" for k in fields)
    try:
        await session.execute(
            text(f"UPDATE companies SET {assignments} WHERE id = :id"), {**fields, "id": company_id}
        )
    except IntegrityError:
        raise ApiError(status.HTTP_409_CONFLICT, CODE_DUPLICATE, "Those details clash with another company")

    after = await get_company(session, company_id)
    await audit.record(
        session,
        entity_type="company",
        action="updated",
        entity_id=company_id,
        entity_label=after["name"],
        company_id=company_id,
        actor_user_id=UUID(claims.user_id),
        actor_role="super_admin",
        before=before,
        after=after,
        request=request,
    )
    return after


async def set_status(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    company_id: UUID,
    suspend: bool,
    reason: Optional[str] = None,
    request: Optional[Request] = None,
) -> dict:
    """Suspend or reactivate a tenant.

    BR-AUTH-04's other half lives in `deps.assert_session_live`: suspending
    a company does not have to reach into anyone's session, because every
    request re-checks the company's status. Tokens stop working on the next
    call rather than when they expire.
    """
    before = await get_company(session, company_id)
    if suspend and before["status"] == "suspended":
        return before
    if not suspend and before["status"] == "active":
        return before

    await session.execute(
        text(
            "UPDATE companies SET status = :status, suspended_at = :at, suspended_reason = :reason "
            "WHERE id = :id"
        ),
        {
            "status": "suspended" if suspend else "active",
            "at": datetime.now(timezone.utc) if suspend else None,
            "reason": (reason or "").strip() or None if suspend else None,
            "id": company_id,
        },
    )
    after = await get_company(session, company_id)
    await audit.record(
        session,
        entity_type="company",
        action="suspended" if suspend else "reactivated",
        entity_id=company_id,
        entity_label=after["name"],
        company_id=company_id,
        actor_user_id=UUID(claims.user_id),
        actor_role="super_admin",
        description=(reason or "").strip() or None,
        before=before,
        after=after,
        request=request,
    )
    return after


async def list_users(
    session: AsyncSession,
    *,
    q: Optional[str] = None,
    company_id: Optional[UUID] = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    """Every user on the platform, for the impersonation picker and support.

    Platform admins are excluded: they cannot be impersonated (the endpoint
    refuses it), so listing them here would only offer a button that fails.
    """
    where = ["u.deleted_at IS NULL", "NOT u.is_platform_admin"]
    params: dict = {"limit": limit, "offset": offset}
    if q:
        where.append("(u.full_name ILIKE :q OR u.email ILIKE :q)")
        params["q"] = f"%{q.strip()}%"
    if company_id:
        where.append("u.company_id = :company_id")
        params["company_id"] = company_id

    rows = (
        await session.execute(
            text(
                "SELECT u.id, u.company_id, COALESCE(c.name, '') AS company_name, u.email, u.full_name, "
                "r.code AS role_code, r.name AS role_name, u.status, u.last_login_at "
                "FROM users u JOIN roles r ON r.id = u.role_id "
                "LEFT JOIN companies c ON c.id = u.company_id "
                f"WHERE {' AND '.join(where)} ORDER BY c.name, u.full_name LIMIT :limit OFFSET :offset"
            ),
            params,
        )
    ).mappings().all()
    return [dict(r) for r in rows]


_DIRECTORY_SQL = """
    SELECT u.id, u.email, u.full_name, u.phone, u.status, u.last_login_at, u.created_at,
           u.company_id AS home_company_id, COALESCE(hc.name, '') AS home_company_name,
           r.code AS home_role_code, r.name AS home_role_name,
           COALESCE((
               SELECT json_agg(json_build_object(
                          'company_id', cu.company_id, 'company_name', lc.name,
                          'role_code', lr.code, 'role_name', lr.name, 'status', cu.status)
                      ORDER BY lc.name)
               FROM company_users cu
               JOIN companies lc ON lc.id = cu.company_id
               JOIN roles lr ON lr.id = cu.role_id
               WHERE cu.user_id = u.id
           ), '[]'::json) AS linked
    FROM users u
    JOIN roles r ON r.id = u.role_id
    LEFT JOIN companies hc ON hc.id = u.company_id
"""


async def list_directory(
    session: AsyncSession,
    *,
    q: Optional[str] = None,
    company_id: Optional[UUID] = None,
    status_filter: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
) -> list[dict]:
    """Every tenant user on the platform, with *all* the companies they can
    work in — their home company plus any they are linked to (BR-AUTH-13).

    The company filter matches either, so filtering by a company shows its
    linked Owners too, not just its own users. Platform admins are left out,
    same as `list_users`: nothing on this screen applies to them.
    """
    where = ["u.deleted_at IS NULL", "NOT u.is_platform_admin"]
    params: dict = {"limit": limit, "offset": offset}
    if q and q.strip():
        where.append("(u.full_name ILIKE :q OR u.email ILIKE :q)")
        params["q"] = f"%{q.strip()}%"
    if company_id:
        where.append(
            "(u.company_id = :company_id OR EXISTS (SELECT 1 FROM company_users x "
            "WHERE x.user_id = u.id AND x.company_id = :company_id))"
        )
        params["company_id"] = company_id
    if status_filter:
        where.append("u.status = :status")
        params["status"] = status_filter

    rows = (
        await session.execute(
            text(
                _DIRECTORY_SQL
                + f" WHERE {' AND '.join(where)} ORDER BY u.full_name, u.email LIMIT :limit OFFSET :offset"
            ),
            params,
        )
    ).mappings().all()
    return [_directory_row(r) for r in rows]


def _directory_row(r) -> dict:
    linked = r["linked"]
    if isinstance(linked, str):  # asyncpg hands `json` back as text
        linked = json.loads(linked)
    companies = []
    if r["home_company_id"] is not None:
        companies.append(
            {
                "company_id": r["home_company_id"],
                "company_name": r["home_company_name"],
                "role_code": r["home_role_code"],
                "role_name": r["home_role_name"],
                "status": "active",
                "is_home": True,
            }
        )
    companies.extend({**c, "is_home": False} for c in (linked or []))
    return {
        "id": r["id"],
        "email": r["email"],
        "full_name": r["full_name"],
        "phone": r["phone"],
        "status": r["status"],
        "last_login_at": r["last_login_at"],
        "created_at": r["created_at"],
        "companies": companies,
    }


async def get_directory_user(session: AsyncSession, user_id: UUID) -> dict:
    row = (
        await session.execute(
            text(_DIRECTORY_SQL + " WHERE u.id = :id AND u.deleted_at IS NULL"), {"id": user_id}
        )
    ).mappings().first()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "User not found")
    return _directory_row(row)


async def update_user_profile(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    user_id: UUID,
    full_name: Optional[str],
    phone: Optional[str],
    request: Optional[Request] = None,
) -> dict:
    """Correct a tenant user's name or phone from the console.

    Email is not editable here: it is the login, and changing it without
    the person confirming the new address would hand their account to
    whoever owns that address. Role stays on the tenant side for the
    BR-AUTH-09 reason given on `update_user_status`.
    """
    before = await get_platform_user(session, user_id)
    if before["is_platform_admin"]:
        raise ApiError(status.HTTP_403_FORBIDDEN, CODE_FORBIDDEN, "Platform admins are not managed from this screen")

    values: dict = {}
    if full_name is not None:
        if len(full_name.strip()) < 2:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_VALIDATION, "Name is too short",
                errors=[{"field": "full_name", "message": "Enter at least 2 characters"}],
            )
        values["full_name"] = full_name.strip()
    if phone is not None:
        values["phone"] = phone.strip() or None

    old = (
        await session.execute(text("SELECT full_name, phone FROM users WHERE id = :id"), {"id": user_id})
    ).mappings().first()
    changed = {k: v for k, v in values.items() if old[k] != v}
    if changed:
        assignments = ", ".join(f"{k} = :{k}" for k in changed)
        await session.execute(text(f"UPDATE users SET {assignments} WHERE id = :id"), {**changed, "id": user_id})
        await audit.record(
            session,
            entity_type="user",
            action="updated",
            entity_id=user_id,
            entity_label=before["email"],
            company_id=before["company_id"],
            actor_user_id=UUID(claims.user_id),
            actor_role="super_admin",
            description="Profile updated from the platform console",
            before={k: old[k] for k in changed},
            after=changed,
            request=request,
        )
    return await get_directory_user(session, user_id)


_PLATFORM_USER_ROW = """
    SELECT u.id, u.company_id, COALESCE(c.name, '') AS company_name, u.email, u.full_name,
           r.code AS role_code, r.name AS role_name, u.status, u.last_login_at,
           u.is_platform_admin
    FROM users u JOIN roles r ON r.id = u.role_id
    LEFT JOIN companies c ON c.id = u.company_id
    WHERE u.id = :id AND u.deleted_at IS NULL
"""


async def get_platform_user(session: AsyncSession, user_id: UUID) -> dict:
    row = (await session.execute(text(_PLATFORM_USER_ROW), {"id": user_id})).mappings().first()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "User not found")
    return dict(row)


async def update_user_status(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    user_id: UUID,
    new_status: str,
    request: Optional[Request] = None,
) -> dict:
    """Activate/deactivate a tenant user from the console.

    Deliberately narrower than the tenant-side `PATCH /users/{id}`: no role
    or godown-scope editing here. Role changes stay bound to BR-AUTH-09's
    escalation check, which compares a new role's permissions against the
    *caller's own* — a platform admin holds no tenant permissions to compare
    against, so there is no safe way to run that check from here. Status
    grants nothing, so it is safe on its own.
    """
    # Local import: mirrors `onboard_company`'s import of
    # `_deliver_queued_email` from the same module, avoiding a module-level
    # circular import between `auth` and `platform`.
    from app.modules.auth.users_router import _assert_not_last_owner, _assert_not_sole_owner_elsewhere

    before = await get_platform_user(session, user_id)
    if before["is_platform_admin"]:
        raise ApiError(status.HTTP_403_FORBIDDEN, CODE_FORBIDDEN, "Platform admins are not managed from this screen")
    if before["company_id"] is None:
        raise ApiError(status.HTTP_400_BAD_REQUEST, CODE_VALIDATION, "This user has no company")
    if before["status"] == new_status:
        return before

    if new_status != "active":
        # BR-AUTH-10: the last active Owner cannot be deactivated, from here
        # any more than from the tenant's own Users screen.
        await _assert_not_last_owner(
            session, user_id=user_id, company_id=str(before["company_id"]), action="deactivated"
        )
        await _assert_not_sole_owner_elsewhere(user_id=user_id, action="deactivated", name_companies=True)

    await session.execute(text("UPDATE users SET status = :s WHERE id = :id"), {"s": new_status, "id": user_id})
    if new_status != "active":
        # Same reasoning as the tenant-side endpoint (BR-AUTH-11's sibling
        # case): a deactivated user's live access token should not keep
        # working until it naturally expires.
        await revoke_sessions(session, user_id=user_id)

    after = await get_platform_user(session, user_id)
    await audit.record(
        session,
        entity_type="user",
        action="updated",
        entity_id=user_id,
        entity_label=before["email"],
        company_id=before["company_id"],
        actor_user_id=UUID(claims.user_id),
        actor_role="super_admin",
        description=f"Status changed to {new_status} from the platform console",
        before={"status": before["status"]},
        after={"status": new_status},
        request=request,
    )
    return after


# ================================================== linked owners (BR-AUTH-13)
#
# Giving an existing login access to another company. Console-only on
# purpose: a tenant admin adding "someone@othercompany" to their own
# company would be reaching into another tenant's user base, and would
# also turn the invite form into a way to find out which emails have
# accounts. A platform admin is the one party that already sees both sides.
#
# Owner only for now — the feature is "one owner, several businesses".
# `company_users.role_id` is a real column, so widening this later is a
# change here, not a schema change.

_MEMBER_ROW = """
    SELECT cu.user_id, cu.company_id, u.email, u.full_name,
           u.company_id AS home_company_id, COALESCE(hc.name, '') AS home_company_name,
           r.code AS role_code, r.name AS role_name, cu.status, cu.added_at, u.last_login_at
    FROM company_users cu
    JOIN users u ON u.id = cu.user_id
    JOIN roles r ON r.id = cu.role_id
    LEFT JOIN companies hc ON hc.id = u.company_id
    WHERE u.deleted_at IS NULL
"""


async def list_invitations(session: AsyncSession, company_id: UUID) -> list[dict]:
    """Invitations still waiting to be accepted at one company.

    A company onboarded a minute ago has no users yet — only its Owner's
    invitation — so without this the console has nothing to show for it and
    no way to get the link out again.
    """
    await get_company(session, company_id)  # 404 for an unknown company
    rows = (
        await session.execute(
            text(
                "SELECT i.id, i.email, i.full_name, r.code AS role_code, r.name AS role_name, "
                "i.status, i.invited_at, i.expires_at, i.last_sent_at, i.resend_count, "
                "(i.expires_at < now()) AS is_expired "
                "FROM invitations i JOIN roles r ON r.id = i.role_id "
                "WHERE i.company_id = :c AND i.status = 'pending' "
                "ORDER BY i.invited_at DESC"
            ),
            {"c": company_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def resend_invitation(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    company_id: UUID,
    invitation_id: UUID,
    request: Optional[Request] = None,
) -> tuple[dict, UUID, str]:
    """Issue a fresh link for a pending invitation and queue its email.

    Same rule as the tenant-side resend: a *new* token replaces the old one,
    so an earlier email cannot stay live. Returns (row, outbound message id,
    raw token); the caller sends the mail after committing.
    """
    company = await get_company(session, company_id)
    row = (
        await session.execute(
            text(
                "SELECT id, email, full_name, status FROM invitations "
                "WHERE id = :id AND company_id = :c FOR UPDATE"
            ),
            {"id": invitation_id, "c": company_id},
        )
    ).mappings().first()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Invitation not found")
    if row["status"] != "pending":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_DUPLICATE,
            f"This invitation is {row['status']} and cannot be resent",
        )

    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=INVITATION_TTL_DAYS)
    await session.execute(
        text(
            "UPDATE invitations SET token_hash = :h, expires_at = :e, "
            "resend_count = resend_count + 1, last_sent_at = now() WHERE id = :id"
        ),
        {"h": hash_refresh_token(raw_token), "e": expires_at, "id": invitation_id},
    )

    spec = email_service.invitation_email(
        full_name=row["full_name"],
        company_name=company["name"],
        invited_by="The InventoryAI team",
        token=raw_token,
    )
    spec.to = row["email"]
    message_id = await email_service.record_outbound(
        session,
        company_id=company_id,
        message_type="invitation",
        to_address=row["email"],
        subject=spec.subject,
        body_preview=spec.body,
        related_type="invitation",
        related_id=invitation_id,
        sent_by=claims.user_id,
    )
    await audit.record(
        session,
        entity_type="invitation",
        action="invitation_resent",
        entity_id=invitation_id,
        entity_label=row["email"],
        company_id=company_id,
        actor_user_id=UUID(claims.user_id),
        actor_role="super_admin",
        description="Invitation link re-issued from the platform console",
        request=request,
    )
    return (
        {"id": invitation_id, "email": row["email"], "full_name": row["full_name"], "expires_at": expires_at},
        message_id,
        raw_token,
    )


async def list_members(session: AsyncSession, company_id: UUID) -> list[dict]:
    await get_company(session, company_id)  # 404 for an unknown company
    rows = (
        await session.execute(
            text(_MEMBER_ROW + " AND cu.company_id = :c ORDER BY cu.added_at"), {"c": company_id}
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def add_member(
    session: AsyncSession, *, claims: AccessTokenClaims, company_id: UUID, email: str,
    request: Optional[Request] = None,
) -> dict:
    company = await get_company(session, company_id)
    user = (
        await session.execute(
            text(
                "SELECT id, email, company_id, is_platform_admin, status FROM users "
                "WHERE lower(email) = lower(:e) AND deleted_at IS NULL"
            ),
            {"e": email.strip()},
        )
    ).mappings().first()
    if user is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "No account uses that email",
            errors=[{"field": "email", "message": "No account uses that email"}],
        )
    if user["is_platform_admin"] or user["status"] != "active":
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_VALIDATION,
            "Only an active company user can be given access to another company",
            errors=[{"field": "email", "message": "Platform admin or inactive account"}],
        )
    if str(user["company_id"]) == str(company_id):
        raise ApiError(
            status.HTTP_409_CONFLICT, CODE_DUPLICATE, "That person already belongs to this company",
            errors=[{"field": "email", "message": "Already a user of this company"}],
        )

    owner_role_id = (
        await session.execute(text("SELECT id FROM roles WHERE company_id IS NULL AND code = 'owner'"))
    ).scalar_one()
    try:
        await session.execute(
            text(
                "INSERT INTO company_users (user_id, company_id, role_id, added_by) "
                "VALUES (:u, :c, :r, :by)"
            ),
            {"u": user["id"], "c": company_id, "r": owner_role_id, "by": claims.user_id},
        )
    except IntegrityError:
        raise ApiError(
            status.HTTP_409_CONFLICT, CODE_DUPLICATE, "That person already has access to this company",
            errors=[{"field": "email", "message": "Already linked"}],
        )

    await audit.record(
        session, entity_type="user", action="updated", entity_id=user["id"], entity_label=user["email"],
        company_id=company_id, actor_user_id=UUID(claims.user_id), actor_role="super_admin",
        description=f"Given Owner access to {company['name']} (multi-company login)", request=request,
    )
    row = (
        await session.execute(
            text(_MEMBER_ROW + " AND cu.company_id = :c AND cu.user_id = :u"), {"c": company_id, "u": user["id"]}
        )
    ).mappings().first()
    return dict(row)


async def remove_member(
    session: AsyncSession, *, claims: AccessTokenClaims, company_id: UUID, user_id: UUID,
    request: Optional[Request] = None,
) -> None:
    """Deleting the row is enough to end their access: `assert_session_live`
    checks the membership on every request, so a token they are holding for
    this company stops working on its next call, and `/auth/refresh` will
    not mint another. Their home company is untouched."""
    from app.modules.auth.users_router import _assert_not_last_owner

    company = await get_company(session, company_id)
    # Linked Owners count toward BR-AUTH-10, so unlinking the only one
    # would leave the company without an Owner, same as deactivating one.
    await _assert_not_last_owner(session, user_id=user_id, company_id=str(company_id), action="removed")
    row = (
        await session.execute(
            text("DELETE FROM company_users WHERE company_id = :c AND user_id = :u RETURNING user_id"),
            {"c": company_id, "u": user_id},
        )
    ).first()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "That person has no linked access here")

    email = (
        await session.execute(text("SELECT email FROM users WHERE id = :u"), {"u": user_id})
    ).scalar_one_or_none()
    await audit.record(
        session, entity_type="user", action="removed", entity_id=user_id, entity_label=email,
        company_id=company_id, actor_user_id=UUID(claims.user_id), actor_role="super_admin",
        description=f"Access to {company['name']} removed (multi-company login)", request=request,
    )


async def activity(session: AsyncSession, *, limit: int = 100, company_id: Optional[UUID] = None) -> list[dict]:
    where = []
    params: dict = {"limit": limit}
    if company_id:
        where.append("a.company_id = :company_id")
        params["company_id"] = company_id
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    rows = (
        await session.execute(
            text(
                "SELECT a.id, a.created_at, a.company_id, COALESCE(c.name, 'Platform') AS company_name, "
                "a.entity_type, a.entity_id, COALESCE(a.entity_label, '') AS entity_label, a.action, "
                "a.description, a.actor_user_id, COALESCE(a.actor_name, u.full_name, '') AS actor_name, "
                "COALESCE(a.actor_role, '') AS actor_role, a.impersonated_by "
                "FROM audit_logs a "
                "LEFT JOIN companies c ON c.id = a.company_id "
                "LEFT JOIN users u ON u.id = a.actor_user_id "
                f"{clause} ORDER BY a.created_at DESC LIMIT :limit"
            ),
            params,
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def today() -> date:
    return clock.today()
