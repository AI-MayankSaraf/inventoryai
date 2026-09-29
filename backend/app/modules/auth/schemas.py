from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    # Plain str, not pydantic's EmailStr: EmailStr's underlying
    # email-validator library rejects reserved/special-use TLDs (.test,
    # .invalid, .example, .localhost) by default, which would reject this
    # project's own seeded demo accounts (owner@acme-demo.test). The lookup
    # itself (`lower(email) = lower(:email)`, service.py) is already the
    # real validation — a non-existent or malformed address just fails to
    # match any user and returns the same generic 401 as a wrong password.
    email: str = Field(min_length=3, max_length=320)
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class GodownScopeOut(BaseModel):
    all: bool
    godown_ids: list[str]


class MeOut(BaseModel):
    """The profile fields a JWT doesn't carry — the frontend fetches this
    once right after login (and again on session bootstrap) to render full
    name, company name and role display name. Permissions stay out of this
    response deliberately: the frontend already has them from the access
    token's own claims."""

    id: UUID
    company_id: Optional[UUID]
    company_name: Optional[str]
    email: str
    full_name: str
    phone: Optional[str]
    role_id: UUID
    role_code: str
    role_name: str
    status: str
    is_platform_admin: bool
    godown_scope: GodownScopeOut
    last_login_at: Optional[datetime]
    #: BR-AUTH-13. `company_id` above is the *active* company (the one the
    #: token is for); this is where the user's own record lives. They
    #: differ only after switching into another company.
    home_company_id: Optional[UUID] = None


class CompanyMembershipOut(BaseModel):
    """One entry in the company switcher (`GET /auth/me/companies`)."""

    company_id: UUID
    company_name: str
    company_status: str
    role_code: str
    role_name: str
    is_home: bool
    is_current: bool


class SwitchCompanyRequest(BaseModel):
    company_id: UUID
    #: The refresh token being replaced. Optional so a client that lost it
    #: can still switch; when present it is revoked, since it is bound to
    #: the company being left.
    refresh_token: Optional[str] = None


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class UpdateMeRequest(BaseModel):
    """Self-service profile edit. Only the fields a person owns about
    themselves — email, role, status and godown scope stay with whoever
    holds `user.manage` (BR-AUTH-09)."""

    full_name: Optional[str] = Field(default=None, min_length=1, max_length=300)
    phone: Optional[str] = Field(default=None, max_length=20, pattern=r"^[0-9+\-() ]*$")


class AcceptedResponse(BaseModel):
    """Deliberately says nothing about whether an account exists."""

    status: str = "accepted"
    detail: str = "If that email belongs to an account, a reset link is on its way."
