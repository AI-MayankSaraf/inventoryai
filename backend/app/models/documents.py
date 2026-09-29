"""
Document storage — `02_DATABASE_DESIGN.md` §8 (documents, document_links).
AI tables live in `ai.py`; ops tables (alerts, audit, messaging) in `ops.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Index, SmallInteger, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    Pct,
    TenantMixin,
    UUIDPkMixin,
    enum_check,
    plain_fk,
    tenant_fk,
    uq_company_id,
)


class Document(UUIDPkMixin, TenantMixin, Base):
    """One row per uploaded file. Bytes live in S3; Postgres holds metadata,
    dedupe hash and processing state (§8)."""

    __tablename__ = "documents"

    original_filename: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    storage_bucket: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    file_extension: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256_hash: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[Optional[int]] = mapped_column(SmallInteger)
    document_type: Mapped[Optional[str]] = mapped_column(Text, index=True)
    document_type_confidence: Mapped[Optional[float]] = mapped_column(Pct)
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    supplier_confidence: Mapped[Optional[float]] = mapped_column(Pct)
    processing_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'uploaded'"), index=True)
    processing_stage: Mapped[Optional[str]] = mapped_column(Text)
    processing_progress: Mapped[Optional[int]] = mapped_column(SmallInteger)
    extraction_confidence: Mapped[Optional[float]] = mapped_column(Pct)
    items_found: Mapped[Optional[int]] = mapped_column(SmallInteger)
    error_code: Mapped[Optional[str]] = mapped_column(Text)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'upload'"))
    uploaded_by: Mapped[uuid.UUID] = plain_fk("users.id", nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"), index=True)
    retention_expires_at: Mapped[Optional[datetime]] = mapped_column(index=True)
    is_archived: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))

    __table_args__ = (
        uq_company_id("documents"),
        tenant_fk("documents", "supplier_id", "suppliers", ondelete="SET NULL"),
        # Per tenant, not global (§8 fn 1): two tenants uploading the same
        # manufacturer rate card is normal and must not collide.
        UniqueConstraint("company_id", "sha256_hash", name="uq_document_hash"),
        Index("ix_documents_queue", "company_id", "processing_status", "uploaded_at"),
        enum_check(
            "document_type",
            [
                "supplier_quotation",
                "proforma_invoice",
                "tax_invoice",
                "delivery_challan",
                "rate_list",
                "price_revision",
                "purchase_order",
                "other",
                "unrecognised",
            ],
        ),
        enum_check(
            "processing_status",
            [
                "uploaded",
                "queued",
                "processing",
                "extracted",
                "review_required",
                "approved",
                "rejected",
                "failed",
                "duplicate",
            ],
        ),
        enum_check("source", ["upload", "email", "api", "whatsapp"]),
    )


class DocumentLink(UUIDPkMixin, TenantMixin, Base):
    """A file may back several business records — polymorphic M:N (§8).
    Deliberately no DB-level FK on `linked_id`: the set of linkable record
    types grows with every module; validated in the service layer instead
    (documented trade-off, §8)."""

    __tablename__ = "document_links"

    document_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    linked_type: Mapped[str] = mapped_column(Text, nullable=False)
    linked_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    link_role: Mapped[str] = mapped_column(Text, nullable=False)
    linked_by: Mapped[uuid.UUID] = plain_fk("users.id", nullable=False)
    linked_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))

    __table_args__ = (
        uq_company_id("document_links"),
        tenant_fk("document_links", "document_id", "documents", ondelete="CASCADE"),
        UniqueConstraint("document_id", "linked_type", "linked_id", "link_role", name="uq_document_link"),
        Index("ix_document_links_target", "company_id", "linked_type", "linked_id"),
        enum_check(
            "linked_type",
            [
                "rfq",
                "supplier_quotation",
                "purchase_order",
                "proforma_invoice",
                "goods_receipt",
                "supplier_invoice",
                "purchase_return",
                "product",
                "supplier",
                "company",
            ],
        ),
        enum_check("link_role", ["source", "attachment", "signed_copy", "supporting", "logo"]),
    )
