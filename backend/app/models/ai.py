"""
AI pipeline tables — `08_AI_DATA_MODEL.md` §3.

Principle enforced by this schema, not by convention: AI never writes to a
business table (it writes here; a human approval promotes the result) and
AI never produces a stored financial value (totals are always recomputed
server-side from reviewed quantity x price x rate).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    ARRAY,
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # pragma: no cover - pgvector always installed in this project, but degrade gracefully
    Vector = None  # type: ignore[assignment]

from app.models.base import (
    AuditMixin,
    Base,
    Pct,
    Qty,
    Rate,
    TenantMixin,
    UUIDPkMixin,
    enum_check,
    plain_fk,
    tenant_fk,
    uq_company_id,
)


class AiProcessingJob(UUIDPkMixin, TenantMixin, AuditMixin, Base):
    """One row per pipeline run. Drives the progress bar and every
    cost/latency question."""

    __tablename__ = "ai_processing_jobs"

    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    job_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"), index=True)
    stage: Mapped[Optional[str]] = mapped_column(Text)
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    provider: Mapped[Optional[str]] = mapped_column(Text)
    model_id: Mapped[Optional[str]] = mapped_column(Text, index=True)
    model_tier: Mapped[Optional[str]] = mapped_column(Text)
    prompt_name: Mapped[Optional[str]] = mapped_column(Text)
    prompt_version: Mapped[Optional[str]] = mapped_column(Text, index=True)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 6))
    started_at: Mapped[Optional[datetime]] = mapped_column()
    finished_at: Mapped[Optional[datetime]] = mapped_column()
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    attempt: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))
    error_code: Mapped[Optional[str]] = mapped_column(Text)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    request_payload: Mapped[Optional[dict]] = mapped_column(JSONB)
    response_payload: Mapped[Optional[dict]] = mapped_column(JSONB)
    triggered_by: Mapped[Optional[uuid.UUID]] = plain_fk("users.id", ondelete="SET NULL")

    __table_args__ = (
        uq_company_id("ai_processing_jobs"),
        tenant_fk("ai_processing_jobs", "document_id", "documents", ondelete="CASCADE"),
        Index("ix_ai_jobs_queue", "company_id", "status", "created_at"),
        enum_check(
            "job_type", ["extraction", "classification", "schema_mapping", "sku_match", "embedding", "assistant"]
        ),
        enum_check("status", ["queued", "running", "succeeded", "failed", "cancelled", "dead_letter"]),
        enum_check("model_tier", ["small", "large"]),
    )


class AiExtractionResult(UUIDPkMixin, TenantMixin, Base):
    """The structured outcome of one extraction attempt on one document."""

    __tablename__ = "ai_extraction_results"

    document_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    schema_mapping_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    document_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    supplier_confidence: Mapped[Optional[float]] = mapped_column(Pct)
    overall_confidence: Mapped[Optional[float]] = mapped_column(Pct, index=True)
    page_count: Mapped[Optional[int]] = mapped_column(SmallInteger)
    line_count: Mapped[Optional[int]] = mapped_column(SmallInteger)
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSONB)
    validation_errors: Mapped[Optional[list]] = mapped_column(JSONB)
    pipeline_trace: Mapped[Optional[list]] = mapped_column(JSONB)
    review_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"), index=True)
    reviewed_by: Mapped[Optional[uuid.UUID]] = plain_fk("users.id", ondelete="SET NULL")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column()
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)
    promoted_to_type: Mapped[Optional[str]] = mapped_column(Text, index=True)
    promoted_to_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    superseded_by: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        uq_company_id("ai_extraction_results"),
        tenant_fk("ai_extraction_results", "document_id", "documents", ondelete="CASCADE"),
        tenant_fk("ai_extraction_results", "job_id", "ai_processing_jobs", ondelete="RESTRICT"),
        tenant_fk(
            "ai_extraction_results", "schema_mapping_id", "document_schema_mappings", ondelete="SET NULL"
        ),
        tenant_fk("ai_extraction_results", "supplier_id", "suppliers", ondelete="SET NULL"),
        tenant_fk("ai_extraction_results", "superseded_by", "ai_extraction_results", ondelete="SET NULL"),
        # One active result per document where superseded_by IS NULL.
        Index(
            "uq_ai_extraction_active",
            "document_id",
            unique=True,
            postgresql_where=text("superseded_by IS NULL"),
        ),
        enum_check("review_status", ["pending", "in_review", "approved", "rejected"]),
        enum_check("promoted_to_type", ["supplier_quotation", "proforma_invoice", "supplier_invoice"]),
    )


class AiExtractedField(UUIDPkMixin, TenantMixin, Base):
    """One row per header field on the review screen."""

    __tablename__ = "ai_extracted_fields"

    extraction_result_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    field_key: Mapped[str] = mapped_column(Text, nullable=False)
    field_label: Mapped[str] = mapped_column(Text, nullable=False)
    raw_value: Mapped[Optional[str]] = mapped_column(Text)
    normalised_value: Mapped[Optional[str]] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'string'"))
    confidence: Mapped[Optional[float]] = mapped_column(Pct)
    provenance: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'ai_extracted'"))
    source_page: Mapped[Optional[int]] = mapped_column(SmallInteger)
    source_bbox: Mapped[Optional[dict]] = mapped_column(JSONB)
    source_cell: Mapped[Optional[str]] = mapped_column(Text)
    corrected_value: Mapped[Optional[str]] = mapped_column(Text)
    corrected_by: Mapped[Optional[uuid.UUID]] = plain_fk("users.id", ondelete="SET NULL")
    corrected_at: Mapped[Optional[datetime]] = mapped_column()
    validation_error: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        uq_company_id("ai_extracted_fields"),
        tenant_fk("ai_extracted_fields", "extraction_result_id", "ai_extraction_results", ondelete="CASCADE"),
        UniqueConstraint("extraction_result_id", "field_key", name="uq_extracted_field"),
        enum_check("value_type", ["string", "number", "date", "currency", "gstin"]),
        enum_check(
            "provenance", ["ai_extracted", "ai_suggested", "needs_review", "user_approved", "calculated"]
        ),
    )


class AiExtractedLine(UUIDPkMixin, TenantMixin, Base):
    """One row per line item read from the document, before it becomes a
    quotation/invoice line."""

    __tablename__ = "ai_extracted_lines"

    extraction_result_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    normalised_description: Mapped[Optional[str]] = mapped_column(Text)
    supplier_sku: Mapped[Optional[str]] = mapped_column(Text)
    raw_quantity: Mapped[Optional[str]] = mapped_column(Text)
    quantity: Mapped[Optional[float]] = mapped_column(Qty)
    raw_uom: Mapped[Optional[str]] = mapped_column(Text)
    uom_id: Mapped[Optional[uuid.UUID]] = plain_fk("uoms.id")
    unit_price: Mapped[Optional[float]] = mapped_column(Rate)
    discount_pct: Mapped[Optional[float]] = mapped_column(Pct)
    gst_rate: Mapped[Optional[float]] = mapped_column(Pct)
    hsn_code: Mapped[Optional[str]] = mapped_column(Text)
    line_total_as_printed: Mapped[Optional[float]] = mapped_column(Numeric(18, 2))
    matched_variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    match_method: Mapped[Optional[str]] = mapped_column(Text)
    match_score: Mapped[Optional[float]] = mapped_column(Numeric(6, 4))
    confidence: Mapped[Optional[float]] = mapped_column(Pct)
    provenance: Mapped[str] = mapped_column(Text, nullable=False)
    suggestion_text: Mapped[Optional[str]] = mapped_column(Text)
    final_variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    final_decision: Mapped[Optional[str]] = mapped_column(Text)
    decided_by: Mapped[Optional[uuid.UUID]] = plain_fk("users.id", ondelete="SET NULL")
    decided_at: Mapped[Optional[datetime]] = mapped_column()
    alias_saved: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    validation_errors: Mapped[Optional[list]] = mapped_column(JSONB)

    __table_args__ = (
        uq_company_id("ai_extracted_lines"),
        tenant_fk("ai_extracted_lines", "extraction_result_id", "ai_extraction_results", ondelete="CASCADE"),
        tenant_fk("ai_extracted_lines", "matched_variant_id", "product_variants", ondelete="SET NULL"),
        tenant_fk("ai_extracted_lines", "final_variant_id", "product_variants", ondelete="SET NULL"),
        enum_check(
            "match_method",
            ["exact_sku", "supplier_alias", "barcode", "normalised_rule", "trigram", "embedding", "llm", "manual"],
        ),
        enum_check(
            "provenance", ["ai_extracted", "ai_suggested", "needs_review", "user_approved", "calculated"]
        ),
        enum_check("final_decision", ["accepted_ai", "changed", "new_product", "skipped"]),
    )


class AiMatchCandidate(UUIDPkMixin, TenantMixin, Base):
    """The ranked shortlist behind every line — the evidence for why a
    match was proposed."""

    __tablename__ = "ai_match_candidates"

    extracted_line_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    query_text: Mapped[Optional[str]] = mapped_column(Text)
    normalised_query: Mapped[Optional[str]] = mapped_column(Text)
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    rank: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    product_variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    match_method: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[Optional[float]] = mapped_column(Numeric(6, 4))
    confidence: Mapped[Optional[float]] = mapped_column(Pct)
    reasons: Mapped[Optional[list]] = mapped_column(JSONB)
    is_selected: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    model_id: Mapped[Optional[str]] = mapped_column(Text)
    prompt_version: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))

    __table_args__ = (
        uq_company_id("ai_match_candidates"),
        tenant_fk("ai_match_candidates", "extracted_line_id", "ai_extracted_lines", ondelete="CASCADE"),
        tenant_fk("ai_match_candidates", "supplier_id", "suppliers", ondelete="SET NULL"),
        tenant_fk("ai_match_candidates", "product_variant_id", "product_variants", ondelete="SET NULL"),
        Index("ix_ai_match_candidates_rank", "company_id", "extracted_line_id", "rank"),
        enum_check(
            "match_method",
            ["exact_sku", "supplier_alias", "barcode", "normalised_rule", "trigram", "embedding", "llm", "manual"],
        ),
    )


class AiReviewAction(UUIDPkMixin, TenantMixin, Base):
    """The supervision record — who overrode the AI, on what, when, and to
    what."""

    __tablename__ = "ai_review_actions"

    extraction_result_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    before_value: Mapped[Optional[dict]] = mapped_column(JSONB)
    after_value: Mapped[Optional[dict]] = mapped_column(JSONB)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    reviewer_id: Mapped[uuid.UUID] = plain_fk("users.id", nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))
    time_spent_ms: Mapped[Optional[int]] = mapped_column(Integer)

    __table_args__ = (
        uq_company_id("ai_review_actions"),
        tenant_fk("ai_review_actions", "extraction_result_id", "ai_extraction_results", ondelete="CASCADE"),
        enum_check("target_type", ["field", "line", "document", "mapping"]),
        enum_check(
            "action",
            [
                "accept",
                "edit",
                "match",
                "unmatch",
                "reject_line",
                "approve_document",
                "reject_document",
                "save_alias",
                "confirm_mapping",
            ],
        ),
    )


class CanonicalField(UUIDPkMixin, Base):
    """The controlled vocabulary that column mappings target — global, not
    tenant-scoped, deliberately decoupled from physical column names."""

    __tablename__ = "canonical_fields"

    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    field_group: Mapped[str] = mapped_column(Text, nullable=False)
    data_type: Mapped[str] = mapped_column(Text, nullable=False)
    applies_to_doc_types: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    is_required: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    synonyms: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    validation_regex: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        enum_check("field_group", ["header", "line"]),
        enum_check("data_type", ["string", "number", "date", "currency", "percent", "uom"]),
    )


class DocumentSchemaMapping(UUIDPkMixin, TenantMixin, Base):
    """"This supplier's quotation always looks like this." Learned once,
    reused forever, cached in Redis (Postgres remains authoritative)."""

    __tablename__ = "document_schema_mappings"

    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    document_type: Mapped[str] = mapped_column(Text, nullable=False)
    file_format: Mapped[str] = mapped_column(Text, nullable=False)
    mapping_name: Mapped[Optional[str]] = mapped_column(Text)
    column_signature: Mapped[str] = mapped_column(Text, nullable=False)
    header_row_index: Mapped[Optional[int]] = mapped_column(SmallInteger)
    data_start_row: Mapped[Optional[int]] = mapped_column(SmallInteger)
    sheet_name: Mapped[Optional[str]] = mapped_column(Text)
    sample_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'proposed'"), index=True)
    confidence: Mapped[Optional[float]] = mapped_column(Pct)
    confirmed_by: Mapped[Optional[uuid.UUID]] = plain_fk("users.id", ondelete="SET NULL")
    confirmed_at: Mapped[Optional[datetime]] = mapped_column()
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_used_at: Mapped[Optional[datetime]] = mapped_column()
    success_rate: Mapped[Optional[float]] = mapped_column(Pct)
    version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))

    __table_args__ = (
        uq_company_id("document_schema_mappings"),
        tenant_fk("document_schema_mappings", "supplier_id", "suppliers", ondelete="CASCADE"),
        tenant_fk("document_schema_mappings", "sample_document_id", "documents", ondelete="SET NULL"),
        UniqueConstraint(
            "company_id", "supplier_id", "document_type", "column_signature", "version", name="uq_schema_mapping"
        ),
        enum_check("file_format", ["xlsx", "csv", "pdf_table", "docx"]),
        enum_check("status", ["proposed", "confirmed", "deprecated"]),
    )


class DocumentSchemaMappingField(UUIDPkMixin, Base):
    __tablename__ = "document_schema_mapping_fields"

    mapping_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_schema_mappings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_column: Mapped[str] = mapped_column(Text, nullable=False)
    source_column_index: Mapped[Optional[int]] = mapped_column(SmallInteger)
    canonical_field_id: Mapped[uuid.UUID] = plain_fk("canonical_fields.id", nullable=False)
    transform: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'none'"))
    transform_arg: Mapped[Optional[str]] = mapped_column(Text)
    is_required: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    confidence: Mapped[Optional[float]] = mapped_column(Pct)
    confirmed_by: Mapped[Optional[uuid.UUID]] = plain_fk("users.id", ondelete="SET NULL")
    confirmed_at: Mapped[Optional[datetime]] = mapped_column()

    __table_args__ = (
        UniqueConstraint("mapping_id", "source_column", name="uq_mapping_field_column"),
        UniqueConstraint("mapping_id", "canonical_field_id", name="uq_mapping_field_canonical"),
        enum_check(
            "transform",
            [
                "none",
                "trim",
                "upper",
                "strip_currency",
                "parse_indian_number",
                "percent_to_decimal",
                "date_ddmmyyyy",
                "multiply",
            ],
        ),
    )


class VariantEmbedding(TenantMixin, Base):
    """1:1 with the variant — PK *is* `product_variant_id`. `company_id`
    filter applied before the ANN scan (§4, §12) — never shared between
    tenants."""

    __tablename__ = "variant_embeddings"

    product_variant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(768) if Vector is not None else JSONB
    )
    model_id: Mapped[Optional[str]] = mapped_column(Text)
    source_text: Mapped[Optional[str]] = mapped_column(Text)
    content_hash: Mapped[Optional[str]] = mapped_column(Text)
    generated_at: Mapped[Optional[datetime]] = mapped_column()

    __table_args__ = (
        tenant_fk("variant_embeddings", "product_variant_id", "product_variants", ondelete="CASCADE"),
        # Nearest-neighbour search by cosine distance (migration d4e9f2a6b8c1).
        Index(
            "ix_variant_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class AssistantQuery(UUIDPkMixin, TenantMixin, Base):
    """(OPTIONAL but recommended) Shows which questions users actually ask
    and proves the assistant never touched anything it should not have."""

    __tablename__ = "assistant_queries"

    user_id: Mapped[uuid.UUID] = plain_fk("users.id", nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    detected_intent: Mapped[Optional[str]] = mapped_column(Text)
    intent_confidence: Mapped[Optional[float]] = mapped_column(Pct)
    resolved_entities: Mapped[Optional[dict]] = mapped_column(JSONB)
    query_plan: Mapped[Optional[str]] = mapped_column(Text)
    answer_text: Mapped[Optional[str]] = mapped_column(Text)
    result_payload: Mapped[Optional[dict]] = mapped_column(JSONB)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    model_id: Mapped[Optional[str]] = mapped_column(Text)
    tokens: Mapped[Optional[int]] = mapped_column(Integer)
    cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 6))
    feedback: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))

    __table_args__ = (
        uq_company_id("assistant_queries"),
        enum_check("feedback", ["helpful", "not_helpful"]),
    )
