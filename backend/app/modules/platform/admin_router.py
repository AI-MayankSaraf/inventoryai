"""
Platform-admin endpoints that exist independently of the (still unbuilt)
System Admin console: impersonation, per BR-AUTH-07.

    "Only a platform admin may impersonate. Impersonation tokens expire in
    30 minutes, cannot be refreshed, cannot themselves impersonate, and
    stamp `impersonated_by` on every audit row."

Each clause is enforced somewhere specific:

* *only a platform admin* — `require_platform_admin`, plus a second check
  that the caller is not already impersonating.
* *30 minutes* — `create_access_token(ttl_minutes=30)`.
* *cannot be refreshed* — no refresh token is issued at all, so there is
  nothing to present to `/auth/refresh`.
* *cannot themselves impersonate* — a token carrying `impersonated_by` is
  refused here.
* *stamp `impersonated_by`* — `audit.record` reads it off the token claims,
  so no handler can forget it.

Stopping is also revocable from the platform side: `impersonation_sessions`
carries `ended_at`, and `deps.assert_session_live` refuses any token whose
session has ended — so "stop" takes effect on the very next request rather
than when the 30 minutes run out.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.db import get_platform_session
from app.core.deps import get_current_claims, require_platform_admin
from app.core.errors import CODE_FORBIDDEN, CODE_NOT_FOUND, ApiError
from app.core.security import AccessTokenClaims, GodownScope, create_access_token
from app.modules.platform.schemas import ImpersonateRequest, ImpersonationOut, ImpersonationTokenOut

router = APIRouter(prefix="/platform", tags=["platform"])

IMPERSONATION_TTL_MINUTES = 30


@router.post("/impersonate", response_model=ImpersonationTokenOut)
async def start_impersonation(
    body: ImpersonateRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> dict:
    if claims.impersonated_by:
        raise ApiError(status.HTTP_403_FORBIDDEN, CODE_FORBIDDEN, "An impersonation session cannot impersonate")

    target = (
        await session.execute(
            text(
                "SELECT u.id, u.company_id, u.email, u.full_name, u.role_id, u.status, u.has_all_godowns, "
                "u.is_platform_admin, r.code AS role_code, COALESCE(c.name, '') AS company_name, "
                "c.status AS company_status "
                "FROM users u JOIN roles r ON r.id = u.role_id "
                "LEFT JOIN companies c ON c.id = u.company_id "
                "WHERE u.id = :id AND u.deleted_at IS NULL"
            ),
            {"id": body.user_id},
        )
    ).mappings().first()

    if target is None or target["status"] != "active":
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "User not found")
    if target["is_platform_admin"]:
        # Impersonating another platform admin buys nothing and loses the
        # audit trail's distinction between the two of them.
        raise ApiError(status.HTTP_403_FORBIDDEN, CODE_FORBIDDEN, "A platform admin cannot be impersonated")
    if target["company_id"] is None:
        raise ApiError(status.HTTP_403_FORBIDDEN, CODE_FORBIDDEN, "This user has no company to impersonate into")
    if target["company_status"] == "suspended":
        raise ApiError(status.HTTP_403_FORBIDDEN, CODE_FORBIDDEN, "This company is suspended")

    permissions = sorted(
        r[0]
        for r in (
            await session.execute(
                text(
                    "SELECT p.code FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id "
                    "WHERE rp.role_id = :role_id"
                ),
                {"role_id": target["role_id"]},
            )
        ).all()
    )
    if target["has_all_godowns"]:
        scope = GodownScope(all_godowns=True, godown_ids=[])
    else:
        godowns = (
            await session.execute(
                text("SELECT godown_id FROM user_godown_access WHERE user_id = :u"), {"u": target["id"]}
            )
        ).all()
        scope = GodownScope(all_godowns=False, godown_ids=[str(g[0]) for g in godowns])

    session_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO impersonation_sessions (id, platform_user_id, target_user_id, target_company_id, "
            "reason, ip_address) VALUES (:id, :platform_user, :target, :company, :reason, CAST(:ip AS inet))"
        ),
        {
            "id": session_id,
            "platform_user": claims.user_id,
            "target": target["id"],
            "company": target["company_id"],
            "reason": body.reason.strip(),
            "ip": request.client.host if request.client else None,
        },
    )

    token = create_access_token(
        user_id=target["id"],
        company_id=target["company_id"],
        role_code=target["role_code"],
        is_platform_admin=False,
        permissions=permissions,
        godown_scope=scope,
        impersonated_by=UUID(claims.user_id),
        impersonation_id=session_id,
        ttl_minutes=IMPERSONATION_TTL_MINUTES,
    )

    await audit.record(
        session,
        entity_type="user",
        action="impersonated",
        entity_id=target["id"],
        entity_label=target["email"],
        company_id=target["company_id"],
        actor_user_id=UUID(claims.user_id),
        actor_role="super_admin",
        description=f"Impersonation started: {body.reason.strip()}",
        request=request,
    )
    await session.commit()

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": IMPERSONATION_TTL_MINUTES * 60,
        "impersonation": {
            "id": session_id,
            "platform_user_id": claims.user_id,
            "target_user_id": target["id"],
            "target_user_name": target["full_name"],
            "target_company_id": target["company_id"],
            "target_company_name": target["company_name"],
            "reason": body.reason.strip(),
            "ended_at": None,
        },
    }


@router.post("/impersonate/stop", response_model=ImpersonationOut)
async def stop_impersonation(
    request: Request,
    claims: AccessTokenClaims = Depends(get_current_claims),
    session: AsyncSession = Depends(get_platform_session),
) -> dict:
    """Called with the *impersonation* token. The platform admin's own token
    was never invalidated, so the client simply goes back to using it."""
    if not claims.impersonation_id:
        raise ApiError(status.HTTP_403_FORBIDDEN, CODE_FORBIDDEN, "This is not an impersonation session")

    row = (
        await session.execute(
            text(
                "UPDATE impersonation_sessions SET ended_at = now() "
                "WHERE id = :id AND ended_at IS NULL "
                "RETURNING id, platform_user_id, target_user_id, target_company_id, reason, ended_at"
            ),
            {"id": claims.impersonation_id},
        )
    ).mappings().first()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "This impersonation session has already ended")

    target = (
        await session.execute(
            text(
                "SELECT u.full_name, u.email, COALESCE(c.name, '') AS company_name FROM users u "
                "LEFT JOIN companies c ON c.id = u.company_id WHERE u.id = :id"
            ),
            {"id": row["target_user_id"]},
        )
    ).mappings().first() or {}

    await audit.record(
        session,
        entity_type="user",
        action="impersonated",
        entity_id=row["target_user_id"],
        entity_label=target.get("email", ""),
        company_id=row["target_company_id"],
        actor_user_id=row["platform_user_id"],
        actor_role="super_admin",
        description="Impersonation ended",
        request=request,
    )
    await session.commit()

    return {
        "id": row["id"],
        "platform_user_id": row["platform_user_id"],
        "target_user_id": row["target_user_id"],
        "target_user_name": target.get("full_name", ""),
        "target_company_id": row["target_company_id"],
        "target_company_name": target.get("company_name", ""),
        "reason": row["reason"],
        "ended_at": row["ended_at"],
    }
