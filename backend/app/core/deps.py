"""
FastAPI dependencies for auth + RBAC, per 07_RBAC_MATRIX.md §6:

    1. Token claims — permissions and godown scope are baked into a
       15-minute access token.
    2. Endpoint dependency — declarative `require_permission(code)`.
    3. Row-level security — company_id isolation enforced by the database.
    4. Object-level checks — godown scope, approval limits, state-machine
       legality, checked inside the service layer (not modelled yet — no
       business endpoints exist yet for it to apply to).
    5. Audit — not wired yet (no write-path endpoints exist yet either).
    6. UI — out of scope for the backend.

This module gives every endpoint layers 1+2+3 together: `require_permission`
verifies the JWT and checks the permission code against its baked-in claims
(layer 1+2); `get_tenant_session` hands back a DB session already scoped to
the caller's tenant via `set_tenant()`, so every query made with it is also
filtered by RLS (layer 3) even if a handler has a bug. A platform-admin
token (company_id is None) is only valid against `require_platform_admin`
— per the RBAC matrix, Super Admin has *no* tenant-data permissions at all,
so a platform token simply carries no permission codes a tenant endpoint
would accept, and `get_tenant_session` refuses it outright rather than
relying on that alone.
"""

from __future__ import annotations

from typing import Callable
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import text

from app.core.db import get_platform_session, get_session, set_tenant
from app.core.errors import (
    CODE_COMPANY_SUSPENDED,
    CODE_GODOWN_OUT_OF_SCOPE,
    CODE_SESSION_REVOKED,
    ApiError,
)
from app.core.security import AccessTokenClaims, decode_access_token

_bearer_scheme = HTTPBearer(auto_error=True, description="Access token from POST /auth/login or /auth/refresh")


async def get_current_claims(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_platform_session),
) -> AccessTokenClaims:
    """Verify the token, then confirm the session behind it is still live.

    The signature check alone is not enough. An access token is a
    self-contained 15-minute JWT, so suspending a company, removing a user,
    changing a role or resetting a password would otherwise take effect only
    when the token expired — BR-AUTH-04 gives that 60 seconds, and BR-AUTH-11
    expects a permission change to bite immediately. `users.sessions_revoked_at`
    is the marker those actions bump; a token issued before it is dead.

    One indexed lookup per request. That is a deliberate trade against the
    original "never re-queries the database per request" note above: a
    revocation that takes 15 minutes is not a revocation.
    """
    try:
        claims = decode_access_token(credentials.credentials)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    await assert_session_live(session, claims)
    # Release the implicit transaction the check just opened: this session is
    # shared with whatever handler depends on it, and a handler that opens its
    # own `session.begin()` would otherwise find one already running.
    await session.rollback()
    return claims


async def assert_session_live(session: AsyncSession, claims: AccessTokenClaims) -> None:
    # The company checked is the one the token is *for*, not the user's home
    # one: after a switch (BR-AUTH-13) those differ, and it is the active
    # company whose suspension must end the session. `membership_status` is
    # NULL for the home company (no `company_users` row by design) and for
    # a membership that has been removed.
    row = (
        await session.execute(
            text(
                "SELECT u.status, u.deleted_at, u.sessions_revoked_at, u.company_id AS home_company_id, "
                "c.status AS company_status, cu.status AS membership_status "
                "FROM users u "
                "LEFT JOIN companies c ON c.id = COALESCE(CAST(:active AS uuid), u.company_id) "
                "LEFT JOIN company_users cu ON cu.user_id = u.id AND cu.company_id = CAST(:active AS uuid) "
                "WHERE u.id = :id"
            ),
            {"id": claims.user_id, "active": claims.company_id},
        )
    ).mappings().first()

    if row is None or row["deleted_at"] is not None or row["status"] != "active":
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED, CODE_SESSION_REVOKED, "This account is no longer active. Sign in again."
        )
    if (
        claims.company_id is not None
        and str(row["home_company_id"]) != str(claims.company_id)
        and row["membership_status"] != "active"
    ):
        # A switched-into company whose membership was removed or
        # suspended: the very next request stops working, rather than the
        # token running out its 15 minutes.
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            CODE_SESSION_REVOKED,
            "Your access to this company was removed. Sign in again.",
        )
    if row["company_status"] == "suspended":
        # BR-AUTH-04, the "existing tokens stop working" half.
        raise ApiError(
            status.HTTP_403_FORBIDDEN, CODE_COMPANY_SUSPENDED, "This company account is suspended. Contact support."
        )
    # Tokens carry a millisecond-resolution issue time (`iat_ms`) precisely
    # so this comparison is unambiguous: a role change and the user signing
    # back in commonly land in the same second.
    revoked_at = row["sessions_revoked_at"]
    if revoked_at is not None and claims.issued_at is not None and claims.issued_at <= revoked_at:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            CODE_SESSION_REVOKED,
            "Your access changed and this session ended. Sign in again.",
        )

    if claims.impersonation_id:
        # BR-AUTH-07: an impersonation token dies with its session, not just
        # with its own 30-minute clock.
        ended = (
            await session.execute(
                text("SELECT ended_at FROM impersonation_sessions WHERE id = :id"),
                {"id": claims.impersonation_id},
            )
        ).first()
        if ended is None or ended[0] is not None:
            raise ApiError(
                status.HTTP_401_UNAUTHORIZED, CODE_SESSION_REVOKED, "This impersonation session has ended."
            )


async def revoke_sessions(session: AsyncSession, *, user_id, reason: str = "") -> None:
    """Kill every live session for one user: refresh tokens revoked, and the
    marker bumped so access tokens already in the wild stop being accepted
    on their next request. `reason` is for the caller's audit row, not
    stored here."""
    await session.execute(
        text("UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = :u AND revoked_at IS NULL"),
        {"u": user_id},
    )
    await session.execute(
        text("UPDATE users SET sessions_revoked_at = now() WHERE id = :u"), {"u": user_id},
    )


def require_permission(code: str) -> Callable:
    """Declarative per-endpoint permission gate. Returns the verified claims
    so the handler can still read `company_id`/`godown_scope` for
    object-level checks — 403s before the handler body runs otherwise."""

    async def _dependency(claims: AccessTokenClaims = Depends(get_current_claims)) -> AccessTokenClaims:
        if code not in claims.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {code}",
            )
        return claims

    return _dependency


def require_any_permission(*codes: str) -> Callable:
    """Like `require_permission`, but any one of `codes` is enough. For reads
    another job depends on: receiving goods (`grn.create`) means reading the
    purchase order being received, without `po.view`'s menu or actions."""

    async def _dependency(claims: AccessTokenClaims = Depends(get_current_claims)) -> AccessTokenClaims:
        if not any(code in claims.permissions for code in codes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: one of {', '.join(codes)}",
            )
        return claims

    return _dependency


async def get_tenant_session(
    claims: AccessTokenClaims = Depends(get_current_claims),
    session: AsyncSession = Depends(get_session),
) -> AsyncSession:
    """A DB session already scoped to the caller's tenant. Uses the
    RLS-restricted `app_engine` session (`get_session`, not the BYPASSRLS
    platform one) — `set_tenant()` is what narrows it to one company, RLS
    is what actually enforces that narrowing at the database level."""
    if claims.company_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint requires a tenant context; platform-admin tokens have none",
        )
    await set_tenant(session, UUID(claims.company_id))
    return session


def user_may_touch_godown(claims: AccessTokenClaims, godown_id) -> bool:
    """BR-AUTH-12: "Godown-scoped users see and act on stock only in their
    assigned godowns." A user with `all` scope passes everything."""
    if claims.godown_scope.all_godowns:
        return True
    return str(godown_id) in set(claims.godown_scope.godown_ids)


def assert_godown_in_scope(claims: AccessTokenClaims, godown_id, *, override_permission: str = "") -> None:
    """Write-side guard. Raises `403 GODOWN_OUT_OF_SCOPE` (the code named by
    BR-AUTH-12 and BR-GRN-10) unless the godown is in the caller's scope, or
    they hold the override permission that rule allows —
    `grn.receive_other_godown` for receiving elsewhere,
    `inventory.transfer_any` for transfers crossing the boundary.

    Deliberately a plain function rather than a FastAPI dependency: the
    godown being written to is usually inside the request body or derived
    from another record (the PO's delivery godown, the GRN's receiving
    godown), which a dependency cannot see. Handlers call this once they
    know which godown they are actually touching.
    """
    if user_may_touch_godown(claims, godown_id):
        return
    if override_permission and override_permission in claims.permissions:
        return
    raise ApiError(
        status.HTTP_403_FORBIDDEN,
        CODE_GODOWN_OUT_OF_SCOPE,
        "This godown is outside your assigned scope",
    )


def scoped_godown_filter(claims: AccessTokenClaims, column: str = "godown_id") -> tuple[str, dict]:
    """Read-side filter. Returns a SQL fragment and its parameters, to be
    ANDed into a query so a scoped user only sees rows for their own
    godowns.

    `inventory.view_all` overrides, exactly as BR-AUTH-12 says ("
    `inventory.view_all` overrides for read") — a Purchase Manager or
    Accountant needs to see stock everywhere without being assigned to
    every godown.

    A scoped user with no godowns assigned matches nothing, which is the
    correct reading of 02_DATABASE_DESIGN.md's note that "absence of rows +
    `users.has_all_godowns=false` means no stock visibility".
    """
    if claims.godown_scope.all_godowns or "inventory.view_all" in claims.permissions:
        return "", {}
    if not claims.godown_scope.godown_ids:
        return "FALSE", {}
    return (
        f"{column} = ANY(CAST(:scoped_godown_ids AS uuid[]))",
        {"scoped_godown_ids": list(claims.godown_scope.godown_ids)},
    )


async def require_platform_admin(
    claims: AccessTokenClaims = Depends(get_current_claims),
) -> AccessTokenClaims:
    """For the small set of genuinely platform-level endpoints (none exist
    yet in this phase). Per the RBAC matrix, Super Admin has no tenant-data
    permissions at all — this is the only kind of check a Super Admin token
    should ever pass."""
    if not claims.is_platform_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform admin only")
    return claims


async def get_platform_db(
    _: AccessTokenClaims = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> AsyncSession:
    return session
