"""
Supplier Portal endpoints.

* `/supplier-portal/*` — used by the supplier. Authenticated with a portal
  token (`type=supplier_access`), never a staff token.
* `/catalog/suppliers/{supplier_id}/portal-access` — used by the company,
  to grant, re-send and revoke access. Ordinary staff auth + permissions.

Both run on the platform (BYPASSRLS) session because portal accounts are
platform-level rows, looked up before any tenant is known; every query in
`service.py` therefore filters by company explicitly.
"""

from __future__ import annotations

from datetime import date as Date, datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_platform_session
from app.core.deps import require_permission
from app.core.errors import CODE_UNAUTHENTICATED, ApiError
from app.core.security import AccessTokenClaims
from app.modules.auth.users_router import _deliver_queued_email
from app.modules.supplier_portal import service

router = APIRouter(tags=["supplier-portal"])
_bearer = HTTPBearer(auto_error=False)


# ----------------------------------------------------------------- schemas


class PortalLoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class PortalCompanyOut(BaseModel):
    access_id: UUID
    company_id: UUID
    company_name: str
    city: str
    state_name: str
    supplier_id: UUID
    supplier_name: str


class PortalPrincipalOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    companies: list[PortalCompanyOut]


class PortalTokenOut(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    principal: PortalPrincipalOut


class PortalSetPasswordIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class PortalRfqOut(BaseModel):
    id: UUID
    number: str
    subject: str
    date: Date
    expected: Optional[Date] = None
    status: str
    invitation_status: str
    line_count: int


class PortalQuotationOut(BaseModel):
    id: UUID
    number: str
    rfq_number: str
    date: Optional[Date] = None
    valid_until: Optional[Date] = None
    status: str
    total_amount: float


class PortalPoOut(BaseModel):
    id: UUID
    number: str
    date: Date
    expected: Optional[Date] = None
    status: str
    total_amount: float
    line_count: int


class PortalActivityOut(BaseModel):
    rfqs: list[PortalRfqOut]
    quotations: list[PortalQuotationOut]
    purchase_orders: list[PortalPoOut]


class AccessGrantIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    full_name: str = Field(default="", max_length=300)


class AccessOut(BaseModel):
    id: UUID
    account_id: UUID
    email: str
    full_name: str
    status: str
    account_status: str
    granted_at: datetime
    last_login_at: Optional[datetime] = None


# ---------------------------------------------------------- supplier side


async def portal_account(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    session: AsyncSession = Depends(get_platform_session),
) -> dict:
    if credentials is None:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, CODE_UNAUTHENTICATED, "Sign in to the Supplier Portal")
    return await service.current_account(session, credentials.credentials)


@router.post("/supplier-portal/login", response_model=PortalTokenOut)
async def portal_login(body: PortalLoginIn, request: Request, session: AsyncSession = Depends(get_platform_session)):
    return await service.login(session, email=body.email, password=body.password, request=request)


@router.post("/supplier-portal/set-password", status_code=status.HTTP_204_NO_CONTENT)
async def portal_set_password(body: PortalSetPasswordIn, session: AsyncSession = Depends(get_platform_session)):
    await service.set_password(session, token=body.token, password=body.password)


@router.get("/supplier-portal/me", response_model=PortalPrincipalOut)
async def portal_me(account: dict = Depends(portal_account), session: AsyncSession = Depends(get_platform_session)):
    return await service.principal(session, account)


@router.get("/supplier-portal/access/{access_id}/activity", response_model=PortalActivityOut)
async def portal_activity(
    access_id: UUID,
    account: dict = Depends(portal_account),
    session: AsyncSession = Depends(get_platform_session),
):
    return await service.activity(session, account=account, access_id=access_id)


# ----------------------------------------------------------- company side


@router.get("/catalog/suppliers/{supplier_id}/portal-access", response_model=list[AccessOut])
async def list_portal_access(
    supplier_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("supplier.view")),
    session: AsyncSession = Depends(get_platform_session),
):
    return await service.list_access(session, company_id=claims.company_id, supplier_id=supplier_id)


@router.post("/catalog/suppliers/{supplier_id}/portal-access", response_model=AccessOut, status_code=status.HTTP_201_CREATED)
async def grant_portal_access(
    supplier_id: UUID,
    body: AccessGrantIn,
    request: Request,
    background: BackgroundTasks,
    claims: AccessTokenClaims = Depends(require_permission("supplier.update")),
    session: AsyncSession = Depends(get_platform_session),
):
    grant, message_id = await service.grant_access(
        session, claims=claims, supplier_id=supplier_id, email=body.email, full_name=body.full_name, request=request
    )
    if message_id:
        background.add_task(_deliver_queued_email, message_id)
    return grant


@router.post("/catalog/suppliers/{supplier_id}/portal-access/{access_id}/resend", status_code=status.HTTP_202_ACCEPTED)
async def resend_portal_link(
    supplier_id: UUID,
    access_id: UUID,
    background: BackgroundTasks,
    claims: AccessTokenClaims = Depends(require_permission("supplier.update")),
    session: AsyncSession = Depends(get_platform_session),
):
    message_id = await service.resend_link(session, claims=claims, supplier_id=supplier_id, access_id=access_id)
    background.add_task(_deliver_queued_email, message_id)
    return {"status": "sent"}


@router.delete("/catalog/suppliers/{supplier_id}/portal-access/{access_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_portal_access(
    supplier_id: UUID,
    access_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("supplier.update")),
    session: AsyncSession = Depends(get_platform_session),
):
    await service.revoke_access(session, claims=claims, supplier_id=supplier_id, access_id=access_id, request=request)
