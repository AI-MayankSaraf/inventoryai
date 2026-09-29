from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class CompanyProfileOut(BaseModel):
    id: UUID
    name: str
    legal_name: Optional[str]
    gstin: Optional[str]
    pan: Optional[str]
    state_code: str
    state_name: str
    city: Optional[str]
    address_line1: Optional[str]
    address_line2: Optional[str]
    pincode: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    plan: str
    status: str
    onboarded_on: date


class CompanyProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=500)
    legal_name: Optional[str] = None
    gstin: Optional[str] = Field(default=None, max_length=15)
    pan: Optional[str] = Field(default=None, max_length=10)
    state_code: Optional[str] = Field(default=None, max_length=2)
    state_name: Optional[str] = None
    city: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    pincode: Optional[str] = Field(default=None, max_length=6)
    email: Optional[str] = None
    phone: Optional[str] = None


class CompanySettingsOut(BaseModel):
    company_id: UUID
    currency_code: str
    default_gst_rate: float
    rounding_mode: str
    financial_year_start_month: int
    default_godown_id: Optional[UUID]
    ai_auto_process: bool
    ai_review_confidence_threshold: float
    ai_suggest_while_typing: bool
    ai_never_autoapprove_financials: bool
    low_stock_threshold_mode: str
    alert_email_critical: bool
    alert_daily_low_stock_digest: bool
    alert_po_delay_notify: bool
    po_delay_grace_days: int
    allow_grn_excess_receipt: bool
    grn_excess_tolerance_pct: float
    require_po_approval_above: Optional[float]
    require_maker_checker: bool
    allow_negative_stock: bool
    allow_nonstandard_gst: bool
    inventory_locked_through: Optional[date]
    variance_price_tolerance_pct: float
    variance_amount_tolerance: float
    comparison_weights: dict


class CompanySettingsUpdate(BaseModel):
    """Every field optional — PATCH semantics. Bounds mirror the schema's
    own CHECK constraints so a bad value is a readable 422 rather than a
    database error."""

    currency_code: Optional[str] = Field(default=None, max_length=3)
    default_gst_rate: Optional[float] = Field(default=None, ge=0, le=28)
    rounding_mode: Optional[str] = Field(default=None, pattern="^(nearest|up|down)$")
    financial_year_start_month: Optional[int] = Field(default=None, ge=1, le=12)
    default_godown_id: Optional[UUID] = None
    ai_auto_process: Optional[bool] = None
    ai_review_confidence_threshold: Optional[float] = Field(default=None, ge=0, le=100)
    ai_suggest_while_typing: Optional[bool] = None
    # Deliberately settable, but note 06_BUSINESS_RULES.md treats
    # "never auto-approve financials" as the safe default — turning it off
    # is a decision the Owner makes knowingly, and it lands in the audit log.
    ai_never_autoapprove_financials: Optional[bool] = None
    low_stock_threshold_mode: Optional[str] = Field(default=None, pattern="^(reorder|manual|forecast)$")
    alert_email_critical: Optional[bool] = None
    alert_daily_low_stock_digest: Optional[bool] = None
    alert_po_delay_notify: Optional[bool] = None
    po_delay_grace_days: Optional[int] = Field(default=None, ge=0, le=365)
    allow_grn_excess_receipt: Optional[bool] = None
    grn_excess_tolerance_pct: Optional[float] = Field(default=None, ge=0, le=100)
    require_po_approval_above: Optional[float] = Field(default=None, ge=0)
    require_maker_checker: Optional[bool] = None
    allow_negative_stock: Optional[bool] = None
    allow_nonstandard_gst: Optional[bool] = None
    inventory_locked_through: Optional[date] = None
    variance_price_tolerance_pct: Optional[float] = Field(default=None, ge=0, le=100)
    variance_amount_tolerance: Optional[float] = Field(default=None, ge=0)


class DocumentSequenceOut(BaseModel):
    """One numbering series, as the allocator actually holds it.

    `next_number` is the live counter, not a setting — the Settings screen
    showed seeded mock values here before, so a user reading "next PO: 1"
    while the allocator sat at 89 had no way to know.
    """

    id: UUID
    doc_type: str
    financial_year: str
    prefix: str
    padding: int
    next_number: int


class GodownUsageOut(BaseModel):
    """What is standing behind a godown, for the Godowns screen.

    `in_use` is the deactivation guard: a godown holding stock, expecting a
    delivery, or scoping a user's access cannot be quietly switched off.
    """

    godown_id: UUID
    incharge_name: Optional[str] = None
    sku_count: int
    stock_value: float
    open_po_count: int
    scoped_user_count: int
    in_use: bool
    reason: Optional[str] = None


# ================================================= impersonation (BR-AUTH-07)

class ImpersonateRequest(BaseModel):
    user_id: UUID
    #: Written to `impersonation_sessions.reason` and to the audit trail —
    #: "because I could" is not an acceptable answer six months later.
    reason: str = Field(min_length=3, max_length=500)


class ImpersonationOut(BaseModel):
    id: UUID
    platform_user_id: UUID
    target_user_id: UUID
    target_user_name: str
    target_company_id: UUID
    target_company_name: str
    reason: Optional[str]
    ended_at: Optional[datetime]


class ImpersonationTokenOut(BaseModel):
    """No refresh token, by design: BR-AUTH-07 says an impersonation token
    cannot be refreshed, and the simplest way to guarantee that is to never
    issue anything that could be."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    impersonation: ImpersonationOut


# ======================================================= email / SMTP

class EmailSettingsOut(BaseModel):
    """The password is never returned — only whether one is stored."""

    company_id: UUID
    provider: str
    from_address: Optional[str]
    from_name: Optional[str]
    smtp_host: Optional[str]
    smtp_port: int
    smtp_username: Optional[str]
    smtp_use_tls: bool
    has_password: bool
    last_test_at: Optional[datetime]
    last_test_ok: Optional[bool]
    last_test_error: Optional[str]


class EmailSettingsUpdate(BaseModel):
    provider: str = Field(default="console", pattern="^(console|smtp)$")
    from_address: Optional[str] = Field(default=None, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    from_name: Optional[str] = Field(default=None, max_length=200)
    smtp_host: Optional[str] = Field(default=None, max_length=253)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: Optional[str] = Field(default=None, max_length=254)
    #: Omit to keep the stored password; send "" to clear it.
    smtp_password: Optional[str] = Field(default=None, max_length=500)
    smtp_use_tls: bool = True

    @model_validator(mode="after")
    def _smtp_needs_a_host(self) -> "EmailSettingsUpdate":
        if self.provider == "smtp" and not (self.smtp_host or "").strip():
            raise ValueError("smtp_host is required when the provider is smtp")
        if self.provider == "smtp" and not (self.from_address or "").strip():
            raise ValueError("from_address is required when the provider is smtp")
        return self


class EmailTestRequest(BaseModel):
    to_address: Optional[str] = Field(default=None, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailTestResult(BaseModel):
    sent: bool
    provider: str
    to_address: str
    error: Optional[str] = None


# ================================================ platform console

class PlatformKpisOut(BaseModel):
    """The four numbers at the top of the System Admin console."""

    companies: int
    active_companies: int
    suspended_companies: int
    users: int
    active_users_30d: int


class PlatformCompanyOut(BaseModel):
    """A tenant as the platform sees it.

    `owner_email` falls back to the pending Owner invitation, so a company
    onboarded a minute ago is not shown with a blank owner until someone
    accepts.
    """

    id: UUID
    name: str
    legal_name: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    state_code: str
    state_name: str
    city: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    plan: str
    status: str
    suspended_at: Optional[datetime] = None
    suspended_reason: Optional[str] = None
    onboarded_on: date
    user_count: int = 0
    sku_count: int = 0
    owner_name: str = ""
    owner_email: str = ""


class CompanyOnboardRequest(BaseModel):
    """Everything needed to stand up a tenant, and nothing more.

    There is deliberately no `owner_password`: the first Owner is *invited*,
    so the only person who ever knows that password is the Owner.
    """

    name: str = Field(min_length=2, max_length=500)
    legal_name: Optional[str] = Field(default=None, max_length=500)
    gstin: Optional[str] = Field(default=None, max_length=15)
    state_code: str = Field(min_length=2, max_length=2, pattern=r"^\d{2}$")
    state_name: str = Field(min_length=2, max_length=100)
    city: Optional[str] = Field(default=None, max_length=200)
    email: Optional[str] = Field(default=None, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: Optional[str] = Field(default=None, max_length=20)
    plan: str = Field(default="Trial", pattern="^(Trial|Starter|Growth|Enterprise)$")
    owner_email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    owner_full_name: str = Field(min_length=2, max_length=300)


class CompanyOnboardedOut(BaseModel):
    company: PlatformCompanyOut
    owner_email: str
    #: Development only, exactly like `/users/invite` — elsewhere the emailed
    #: link is the only way to get it.
    invitation_token: Optional[str] = None
    #: True when `owner_email` already had a login and was linked to the new
    #: company (BR-AUTH-13) instead of being sent an invitation.
    owner_linked: bool = False


class PlatformMemberAdd(BaseModel):
    """Give an existing login Owner access to this company (BR-AUTH-13)."""

    email: str = Field(min_length=3, max_length=320)


class PlatformMemberOut(BaseModel):
    user_id: UUID
    company_id: UUID
    email: str
    full_name: str
    home_company_id: Optional[UUID] = None
    home_company_name: str = ""
    role_code: str
    role_name: str
    status: str
    added_at: datetime
    last_login_at: Optional[datetime] = None


class CompanyAdminUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=500)
    legal_name: Optional[str] = Field(default=None, max_length=500)
    gstin: Optional[str] = Field(default=None, max_length=15)
    pan: Optional[str] = Field(default=None, max_length=10)
    state_code: Optional[str] = Field(default=None, min_length=2, max_length=2, pattern=r"^\d{2}$")
    state_name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    city: Optional[str] = Field(default=None, max_length=200)
    email: Optional[str] = Field(default=None, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: Optional[str] = Field(default=None, max_length=20)
    plan: Optional[str] = Field(default=None, pattern="^(Trial|Starter|Growth|Enterprise)$")


class CompanySuspendRequest(BaseModel):
    #: Shown to the tenant's users at the login screen and kept on the
    #: company row, so "why is my account locked" has an answer.
    reason: str = Field(min_length=3, max_length=500)


class PlatformUserStatusUpdate(BaseModel):
    """Activate/deactivate a tenant user from the console. Deliberately no
    role or godown-scope field here — see `console_service.update_user_status`
    for why those stay on the tenant-side endpoint."""

    status: str = Field(pattern="^(active|inactive)$")


class PlatformUserOut(BaseModel):
    id: UUID
    company_id: Optional[UUID] = None
    company_name: str = ""
    email: str
    full_name: str
    role_code: str
    role_name: str
    status: str
    last_login_at: Optional[datetime] = None


class PlatformActivityOut(BaseModel):
    id: UUID
    created_at: datetime
    company_id: Optional[UUID] = None
    company_name: str
    entity_type: str
    entity_id: Optional[UUID] = None
    entity_label: str = ""
    action: str
    description: Optional[str] = None
    actor_user_id: Optional[UUID] = None
    actor_name: str = ""
    actor_role: str = ""
    impersonated_by: Optional[UUID] = None


class PlatformInvitationOut(BaseModel):
    """A pending invitation on one company, for the console's Users tab."""

    id: UUID
    email: str
    full_name: str
    role_code: str
    role_name: str
    status: str
    invited_at: datetime
    expires_at: datetime
    last_sent_at: Optional[datetime] = None
    resend_count: int = 0
    is_expired: bool = False


class PlatformInvitationResendOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    expires_at: datetime
    #: Development only, exactly like `/users/invite` and onboarding — the
    #: stored token is a hash, so the link can only be shown at the moment a
    #: new one is issued, and elsewhere the emailed link is the only copy.
    invitation_token: Optional[str] = None


class PlatformOwnerInvite(BaseModel):
    """Invite an additional Owner to an existing company."""

    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    full_name: str = Field(min_length=2, max_length=300)


class PlatformUserCompanyOut(BaseModel):
    """One company a user can work in, with their role there."""

    company_id: UUID
    company_name: str
    role_code: str
    role_name: str
    #: The company status of the *link* (`company_users.status`); for the
    #: home company this is always "active".
    status: str = "active"
    is_home: bool = False


class PlatformDirectoryUserOut(BaseModel):
    """A row of the console's all-users directory."""

    id: UUID
    email: str
    full_name: str
    phone: Optional[str] = None
    status: str
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    #: Home company first, then every company they are linked to.
    companies: list[PlatformUserCompanyOut] = []


class PlatformUserProfileUpdate(BaseModel):
    """Profile fields a platform admin may correct. No email (it is the
    login identifier) and no role (see `update_user_status`)."""

    full_name: Optional[str] = Field(default=None, min_length=2, max_length=300)
    phone: Optional[str] = Field(default=None, max_length=30)

