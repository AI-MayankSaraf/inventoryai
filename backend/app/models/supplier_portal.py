"""
Supplier Portal identity — migration `f3c6a8e2b4d7`.

A supplier's contact signs in here, never as a tenant `users` row: they are
not a member of any company, hold no tenant permission, and one login covers
every company that has granted them access.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin


class SupplierPortalAccount(UUIDPkMixin, Base):
    __tablename__ = "supplier_portal_accounts"

    email: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'invited'"))
    failed_login_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    locked_until: Mapped[Optional[datetime]] = mapped_column()
    last_login_at: Mapped[Optional[datetime]] = mapped_column()
    password_changed_at: Mapped[Optional[datetime]] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    __table_args__ = (
        Index("uq_supplier_portal_accounts_email", func.lower(email), unique=True),
        CheckConstraint("status IN ('invited', 'active', 'disabled')", name="status_valid"),
    )


class SupplierPortalAccess(UUIDPkMixin, Base):
    """One company letting one account act as one of its supplier records."""

    __tablename__ = "supplier_portal_access"

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("supplier_portal_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    granted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    granted_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    revoked_at: Mapped[Optional[datetime]] = mapped_column()

    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "supplier_id"],
            ["suppliers.company_id", "suppliers.id"],
            name="fk_supplier_portal_access_supplier_id_suppliers",
            ondelete="CASCADE",
        ),
        UniqueConstraint("company_id", "account_id", "supplier_id", name="uq_supplier_portal_access_grant"),
        CheckConstraint("status IN ('active', 'revoked')", name="status_valid"),
    )


class SupplierPortalToken(UUIDPkMixin, Base):
    """One-time set-password link. Only the hash is stored."""

    __tablename__ = "supplier_portal_tokens"

    account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("supplier_portal_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    __table_args__ = (Index("uq_supplier_portal_token_hash", "token_hash", unique=True),)
