"""
Tenancy and identity — `02_DATABASE_DESIGN.md` §3.

companies -> company_settings (1:1) -> document_sequences
         -> roles -> permissions (M:N via role_permissions)
         -> users -> user_godown_access -> godowns (godowns itself is in
            master.py; user_godown_access is declared here because it is
            conceptually part of access control)
         -> invitations, refresh_tokens, impersonation_sessions
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.elements import conv

from app.models.base import (
    AuditMixin,
    Base,
    Money,
    Pct,
    SoftDeleteMixin,
    TenantMixin,
    UUIDPkMixin,
    enum_check,
    plain_fk,
    tenant_fk,
    uq_company_id,
)

ZERO_UUID = text("'00000000-0000-0000-0000-000000000000'::uuid")


class Company(UUIDPkMixin, AuditMixin, SoftDeleteMixin, Base):
    """A tenant. Owns every other row in the system. `deleted_at` exists only
    because §3's own footnote defines `uq_companies_gstin` as partial on
    `deleted_at IS NULL`; a company is otherwise deactivated via `status`,
    never actually deleted."""

    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    legal_name: Mapped[Optional[str]] = mapped_column(Text)
    gstin: Mapped[Optional[str]] = mapped_column(Text)
    pan: Mapped[Optional[str]] = mapped_column(Text)
    state_code: Mapped[str] = mapped_column(Text, nullable=False)
    state_name: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[Optional[str]] = mapped_column(Text)
    address_line1: Mapped[Optional[str]] = mapped_column(Text)
    address_line2: Mapped[Optional[str]] = mapped_column(Text)
    pincode: Mapped[Optional[str]] = mapped_column(Text)
    email: Mapped[Optional[str]] = mapped_column(Text)
    phone: Mapped[Optional[str]] = mapped_column(Text)
    logo_document_id: Mapped[Optional[uuid.UUID]] = plain_fk("documents.id", ondelete="SET NULL")
    plan: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'Trial'"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    suspended_at: Mapped[Optional[datetime]] = mapped_column()
    suspended_reason: Mapped[Optional[str]] = mapped_column(Text)
    onboarded_on: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())

    __table_args__ = (
        Index(
            "uq_companies_gstin",
            "gstin",
            unique=True,
            postgresql_where=text("gstin IS NOT NULL AND deleted_at IS NULL"),
        ),
        enum_check("plan", ["Trial", "Starter", "Growth", "Enterprise"]),
        enum_check("status", ["active", "suspended"]),
    )


class CompanySettings(Base):
    """1:1 configuration for a tenant — every field on `/settings`. PK *is*
    `company_id`; there is no separate surrogate id (§3)."""

    __tablename__ = "company_settings"

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), primary_key=True
    )
    currency_code: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'INR'"))
    default_gst_rate: Mapped[float] = mapped_column(Pct, nullable=False, server_default=text("18.00"))
    rounding_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'nearest'"))
    financial_year_start_month: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("4"))
    default_godown_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True))
    ai_auto_process: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    ai_review_confidence_threshold: Mapped[float] = mapped_column(Pct, nullable=False, server_default=text("90.00"))
    ai_suggest_while_typing: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    ai_never_autoapprove_financials: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    low_stock_threshold_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'reorder'"))
    alert_email_critical: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    alert_daily_low_stock_digest: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    alert_po_delay_notify: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    po_delay_grace_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    allow_grn_excess_receipt: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    grn_excess_tolerance_pct: Mapped[float] = mapped_column(Pct, nullable=False, server_default=text("0.00"))
    require_po_approval_above: Mapped[Optional[float]] = mapped_column(Money)
    require_maker_checker: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    allow_negative_stock: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    allow_nonstandard_gst: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    inventory_locked_through: Mapped[Optional[date]] = mapped_column(Date)
    variance_price_tolerance_pct: Mapped[float] = mapped_column(Pct, nullable=False, server_default=text("0.00"))
    variance_amount_tolerance: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0.00"))
    comparison_weights: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        # `:` escaped as `\:` — sqlalchemy.text() otherwise parses `"cost":`
        # as a bind-parameter marker, per BR-CMP-01's default weights.
        server_default=text(
            "'{\"cost\"\\:0.5,\"delivery\"\\:0.2,\"on_time\"\\:0.15,\"quality\"\\:0.1,\"warranty\"\\:0.05}'::jsonb"
        ),
    )

    __table_args__ = (
        CheckConstraint("financial_year_start_month BETWEEN 1 AND 12", name="financial_year_start_month_range"),
    )


class DocumentSequence(UUIDPkMixin, TenantMixin, AuditMixin, Base):
    """Safe, per-tenant, per-document-type, per-financial-year numbering.
    Replaces client-side `max+1`. Allocation is `SELECT ... FOR UPDATE`
    inside the same transaction as the insert — service-layer concern, not
    modelled here."""

    __tablename__ = "document_sequences"

    doc_type: Mapped[str] = mapped_column(Text, nullable=False)
    financial_year: Mapped[str] = mapped_column(Text, nullable=False)
    prefix: Mapped[str] = mapped_column(Text, nullable=False)
    padding: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("5"))
    next_number: Mapped[int] = mapped_column(nullable=False, server_default=text("1"))

    __table_args__ = (
        uq_company_id("document_sequences"),
        UniqueConstraint("company_id", "doc_type", "financial_year", name="uq_docseq"),
        enum_check(
            "doc_type",
            ["rfq", "po", "grn", "proforma", "invoice", "transfer", "return", "adjustment"],
        ),
    )


class Role(UUIDPkMixin, Base):
    """`company_id IS NULL` = a built-in system role shared by every tenant.
    Not `TenantMixin` — company_id here must be nullable."""

    __tablename__ = "roles"

    company_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))

    __table_args__ = (
        # uq_roles_code = (COALESCE(company_id, 0000...), code) — lets a
        # tenant define a custom role without colliding with system codes.
        Index(
            "uq_roles_code",
            func.coalesce(company_id, text("'00000000-0000-0000-0000-000000000000'::uuid")),
            code,
            unique=True,
        ),
        enum_check(
            "code",
            [
                "super_admin",
                "owner",
                "purchase_manager",
                "godown_manager",
                "accountant",
                "staff",
                "viewer",
            ],
        ),
    )


class Permission(UUIDPkMixin, Base):
    """`po.approve`, `grn.confirm`, `inventory.adjust`, ... Full list in
    `07_RBAC_MATRIX.md` — seeded by the application, not enumerated here."""

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    module: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)


class RolePermission(Base):
    """Composite PK, no surrogate key (§3)."""

    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )


class User(UUIDPkMixin, AuditMixin, SoftDeleteMixin, Base):
    """`company_id IS NULL` => platform (Super) admin. Not `TenantMixin` —
    company_id here must be nullable."""

    __tablename__ = "users"

    company_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    password_hash: Mapped[Optional[str]] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    phone: Mapped[Optional[str]] = mapped_column(Text)
    role_id: Mapped[uuid.UUID] = plain_fk("roles.id", nullable=False)
    avatar_document_id: Mapped[Optional[uuid.UUID]] = plain_fk("documents.id", ondelete="SET NULL")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'invited'"), index=True)
    is_platform_admin: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    has_all_godowns: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    last_login_at: Mapped[Optional[datetime]] = mapped_column()
    last_active_at: Mapped[Optional[datetime]] = mapped_column(index=True)
    failed_login_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    locked_until: Mapped[Optional[datetime]] = mapped_column()
    password_changed_at: Mapped[Optional[datetime]] = mapped_column()
    #: Every token issued before this is refused: "sign out everywhere"
    #: after a password change or reset.
    sessions_revoked_at: Mapped[Optional[datetime]] = mapped_column()

    __table_args__ = (
        Index("uq_users_email", func.lower(email), unique=True),
        CheckConstraint("is_platform_admin = (company_id IS NULL)", name="is_platform_admin_matches_company"),
        enum_check("status", ["invited", "active", "inactive", "suspended"]),
    )


class UserGodownAccess(Base):
    """Implements `Member.godown` ("All godowns" vs a named godown). Absence
    of rows + `users.has_all_godowns=false` means no stock visibility."""

    __tablename__ = "user_godown_access"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    godown_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("godowns.id", ondelete="CASCADE"), primary_key=True
    )
    can_receive: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    can_adjust: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))


class Invitation(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "invitations"

    email: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    role_id: Mapped[uuid.UUID] = plain_fk("roles.id", nullable=False)
    godown_scope: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'all'"))
    godown_ids: Mapped[Optional[list[uuid.UUID]]] = mapped_column(ARRAY(PGUUID(as_uuid=True)))
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    invited_by: Mapped[uuid.UUID] = plain_fk("users.id", nullable=False)
    invited_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    resend_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    last_sent_at: Mapped[Optional[datetime]] = mapped_column()
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"), index=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column()
    accepted_user_id: Mapped[Optional[uuid.UUID]] = plain_fk("users.id", ondelete="SET NULL")

    __table_args__ = (
        uq_company_id("invitations"),
        # One pending invite per email per company (§3 footnote).
        Index(
            "uq_invitations_pending_email",
            "company_id",
            "email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        enum_check("godown_scope", ["all", "specific"]),
        enum_check("status", ["pending", "accepted", "revoked", "expired"]),
    )


class RefreshToken(UUIDPkMixin, Base):
    """(RECOMMENDED) Supports "Keep me signed in" and forced logout on role
    change/suspension."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = plain_fk("users.id", ondelete="CASCADE", nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    issued_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column()
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    impersonated_by: Mapped[Optional[uuid.UUID]] = plain_fk("users.id", ondelete="SET NULL")
    #: The company this session is acting in (BR-AUTH-13); null for a
    #: platform admin.
    company_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True
    )


class CompanyUser(Base):
    """BR-AUTH-13: a login can belong to several companies, with a role in
    each. The user's home company is still `users.company_id`; rows here
    are the other companies they were added to."""

    __tablename__ = "company_users"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    added_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    added_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'suspended')",
            name=conv("ck_company_users_ck_company_users_status_valid"),
        ),
    )


class PasswordResetToken(UUIDPkMixin, Base):
    """One-time reset link. Only the hash is stored; the token itself exists
    only in the email."""

    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    requested_ip: Mapped[Optional[str]] = mapped_column(INET)
    requested_user_agent: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (Index("uq_password_reset_token_hash", "token_hash", unique=True),)


class CompanyEmailSettings(Base):
    """How a company's outgoing mail is sent: `console` (logged only) or its
    own SMTP server. The password is stored encrypted."""

    __tablename__ = "company_email_settings"

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'console'"))
    from_address: Mapped[Optional[str]] = mapped_column(Text)
    from_name: Mapped[Optional[str]] = mapped_column(Text)
    smtp_host: Mapped[Optional[str]] = mapped_column(Text)
    smtp_port: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("587"))
    smtp_username: Mapped[Optional[str]] = mapped_column(Text)
    smtp_password_encrypted: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    smtp_use_tls: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    last_test_at: Mapped[Optional[datetime]] = mapped_column()
    last_test_ok: Mapped[Optional[bool]] = mapped_column()
    last_test_error: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "smtp_port > 0 AND smtp_port <= 65535",
            name=conv("ck_company_email_settings_ck_company_email_settings_port_valid"),
        ),
        CheckConstraint(
            "provider IN ('console', 'smtp')",
            name=conv("ck_company_email_settings_ck_company_email_settings_pro_a5e8"),
        ),
    )


class ImpersonationSession(UUIDPkMixin, Base):
    """(RECOMMENDED) The UI lets a Super Admin *become* a tenant user. That
    must be provable after the fact."""

    __tablename__ = "impersonation_sessions"

    platform_user_id: Mapped[uuid.UUID] = plain_fk("users.id", nullable=False)
    target_user_id: Mapped[uuid.UUID] = plain_fk("users.id", nullable=False)
    target_company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    ended_at: Mapped[Optional[datetime]] = mapped_column()
    reason: Mapped[Optional[str]] = mapped_column(Text)
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    actions_count: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
