"""
The System Admin console's API — every tenant on the installation.

All of it runs on `get_platform_session` (BYPASSRLS) behind
`require_platform_admin`, which is the only thing standing between these
handlers and every company's data. Two rules follow from that and are worth
stating out loud:

* No handler here reads a company id from the body as if it were
  authorisation. The id says *which* tenant to act on; the token says
  whether the caller may act at all.
* An impersonating token is a tenant token — `require_platform_admin`
  refuses it — so a support session cannot walk back up into the console.

Suspension is deliberately not a session-killing operation: `set_status`
flips the company row, and `deps.assert_session_live` re-checks that row on
every request, so a suspended tenant's live tokens stop working on their
next call (BR-AUTH-04) without anything here enumerating sessions.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_platform_session
from app.core.deps import require_platform_admin
from app.core.errors import CODE_FORBIDDEN, ApiError
from app.core.security import AccessTokenClaims
from app.modules.platform import console_service
from app.modules.platform.schemas import (
    CompanyAdminUpdate,
    CompanyOnboardRequest,
    CompanyOnboardedOut,
    CompanySuspendRequest,
    PlatformActivityOut,
    PlatformCompanyOut,
    PlatformDirectoryUserOut,
    PlatformInvitationOut,
    PlatformInvitationResendOut,
    PlatformKpisOut,
    PlatformMemberAdd,
    PlatformMemberOut,
    PlatformOwnerInvite,
    PlatformUserOut,
    PlatformUserProfileUpdate,
    PlatformUserStatusUpdate,
)

router = APIRouter(prefix="/platform", tags=["platform-console"])


def _not_impersonating(claims: AccessTokenClaims) -> None:
    if claims.impersonated_by:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            CODE_FORBIDDEN,
            "The platform console is not available inside an impersonation session",
        )


@router.get("/kpis", response_model=PlatformKpisOut)
async def platform_kpis(
    claims: AccessTokenClaims = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> dict:
    _not_impersonating(claims)
    return await console_service.kpis(session)


@router.get("/companies", response_model=list[PlatformCompanyOut])
async def list_companies(
    q: Optional[str] = Query(default=None, max_length=200),
    status_filter: Optional[str] = Query(default=None, alias="status", pattern="^(active|suspended)$"),
    plan: Optional[str] = Query(default=None, pattern="^(Trial|Starter|Growth|Enterprise)$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    claims: AccessTokenClaims = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> list[dict]:
    _not_impersonating(claims)
    return await console_service.list_companies(
        session, q=q, status_filter=status_filter, plan=plan, limit=limit, offset=offset
    )


@router.post("/companies", response_model=CompanyOnboardedOut, status_code=status.HTTP_201_CREATED)
async def onboard_company(
    body: CompanyOnboardRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> dict:
    _not_impersonating(claims)
    company, message_id, raw_token = await console_service.onboard_company(
        session, claims=claims, body=body, request=request
    )
    await session.commit()

    # After the commit, never inside it — an SMTP handshake has no business
    # holding a transaction open (same note as users_router).
    if message_id is not None:
        from app.modules.auth.users_router import _deliver_queued_email

        await _deliver_queued_email(message_id)

    return {
        "company": company,
        "owner_email": body.owner_email,
        "invitation_token": raw_token if get_settings().is_development else None,
        # No invitation is only ever the linked-existing-login path.
        "owner_linked": raw_token is None,
    }


@router.get("/companies/{company_id}", response_model=PlatformCompanyOut)
async def get_company(
    company_id: UUID,
    claims: AccessTokenClaims = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> dict:
    _not_impersonating(claims)
    return await console_service.get_company(session, company_id)


@router.patch("/companies/{company_id}", response_model=PlatformCompanyOut)
async def update_company(
    company_id: UUID,
    body: CompanyAdminUpdate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> dict:
    _not_impersonating(claims)
    company = await console_service.update_company(
        session,
        claims=claims,
        company_id=company_id,
        values=body.model_dump(exclude_unset=True),
        request=request,
    )
    await session.commit()
    return company


@router.post("/companies/{company_id}/suspend", response_model=PlatformCompanyOut)
async def suspend_company(
    company_id: UUID,
    body: CompanySuspendRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> dict:
    _not_impersonating(claims)
    company = await console_service.set_status(
        session, claims=claims, company_id=company_id, suspend=True, reason=body.reason, request=request
    )
    await session.commit()
    return company


@router.post("/companies/{company_id}/reactivate", response_model=PlatformCompanyOut)
async def reactivate_company(
    company_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> dict:
    _not_impersonating(claims)
    company = await console_service.set_status(
        session, claims=claims, company_id=company_id, suspend=False, request=request
    )
    await session.commit()
    return company


@router.get("/users", response_model=list[PlatformUserOut])
async def list_platform_users(
    q: Optional[str] = Query(default=None, max_length=200),
    company_id: Optional[UUID] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    claims: AccessTokenClaims = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> list[dict]:
    _not_impersonating(claims)
    return await console_service.list_users(session, q=q, company_id=company_id, limit=limit, offset=offset)


@router.get("/user-directory", response_model=list[PlatformDirectoryUserOut])
async def user_directory(
    q: Optional[str] = Query(default=None, max_length=200),
    company_id: Optional[UUID] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status", pattern="^(active|inactive|invited)$"),
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    claims: AccessTokenClaims = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> list[dict]:
    """All tenant users, each with every company they can work in. The
    company filter matches home *or* linked companies."""
    _not_impersonating(claims)
    return await console_service.list_directory(
        session, q=q, company_id=company_id, status_filter=status_filter, limit=limit, offset=offset
    )


@router.patch("/users/{user_id}/profile", response_model=PlatformDirectoryUserOut)
async def update_platform_user_profile(
    user_id: UUID,
    body: PlatformUserProfileUpdate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> dict:
    """Name and phone only — see `console_service.update_user_profile`."""
    _not_impersonating(claims)
    result = await console_service.update_user_profile(
        session, claims=claims, user_id=user_id, full_name=body.full_name, phone=body.phone, request=request
    )
    await session.commit()
    return result


@router.patch("/users/{user_id}", response_model=PlatformUserOut)
async def update_platform_user_status(
    user_id: UUID,
    body: PlatformUserStatusUpdate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> dict:
    """Activate/deactivate a tenant user from the console — see
    `console_service.update_user_status` for why this stops at status and
    does not also take on role or godown-scope editing."""
    _not_impersonating(claims)
    result = await console_service.update_user_status(
        session, claims=claims, user_id=user_id, new_status=body.status, request=request
    )
    await session.commit()
    return result


# ============================================= pending invitations (per company)

@router.get("/companies/{company_id}/invitations", response_model=list[PlatformInvitationOut])
async def list_company_invitations(
    company_id: UUID,
    claims: AccessTokenClaims = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> list[dict]:
    _not_impersonating(claims)
    return await console_service.list_invitations(session, company_id)


@router.post(
    "/companies/{company_id}/invitations",
    response_model=PlatformInvitationResendOut,
    status_code=status.HTTP_201_CREATED,
)
async def invite_company_owner(
    company_id: UUID,
    body: PlatformOwnerInvite,
    request: Request,
    claims: AccessTokenClaims = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> dict:
    """Invite another Owner to an existing company (so the current one can
    be replaced without ever leaving the company Owner-less)."""
    _not_impersonating(claims)
    result, message_id, raw_token = await console_service.invite_owner(
        session, claims=claims, company_id=company_id, email=body.email, full_name=body.full_name, request=request
    )
    await session.commit()

    from app.modules.auth.users_router import _deliver_queued_email

    await _deliver_queued_email(message_id)

    return {**result, "invitation_token": raw_token if get_settings().is_development else None}


@router.post(
    "/companies/{company_id}/invitations/{invitation_id}/resend",
    response_model=PlatformInvitationResendOut,
)
async def resend_company_invitation(
    company_id: UUID,
    invitation_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> dict:
    """Re-issue a pending invitation's link and email it again. The old link
    stops working; in development the new one is also returned."""
    _not_impersonating(claims)
    result, message_id, raw_token = await console_service.resend_invitation(
        session, claims=claims, company_id=company_id, invitation_id=invitation_id, request=request
    )
    await session.commit()

    # After the commit, never inside it (same note as onboarding).
    from app.modules.auth.users_router import _deliver_queued_email

    await _deliver_queued_email(message_id)

    return {**result, "invitation_token": raw_token if get_settings().is_development else None}


# ===================================================== linked owners (BR-AUTH-13)

@router.get("/companies/{company_id}/members", response_model=list[PlatformMemberOut])
async def list_company_members(
    company_id: UUID,
    claims: AccessTokenClaims = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> list[dict]:
    """People whose login lives in another company but who can switch into
    this one. The company's own users are `/platform/users?company_id=`."""
    _not_impersonating(claims)
    return await console_service.list_members(session, company_id)


@router.post(
    "/companies/{company_id}/members", response_model=PlatformMemberOut, status_code=status.HTTP_201_CREATED
)
async def add_company_member(
    company_id: UUID,
    body: PlatformMemberAdd,
    request: Request,
    claims: AccessTokenClaims = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> dict:
    _not_impersonating(claims)
    result = await console_service.add_member(
        session, claims=claims, company_id=company_id, email=body.email, request=request
    )
    await session.commit()
    return result


@router.delete("/companies/{company_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_company_member(
    company_id: UUID,
    user_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> None:
    _not_impersonating(claims)
    await console_service.remove_member(
        session, claims=claims, company_id=company_id, user_id=user_id, request=request
    )
    await session.commit()


@router.get("/activity", response_model=list[PlatformActivityOut])
async def platform_activity(
    company_id: Optional[UUID] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    claims: AccessTokenClaims = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> list[dict]:
    _not_impersonating(claims)
    return await console_service.activity(session, limit=limit, company_id=company_id)
