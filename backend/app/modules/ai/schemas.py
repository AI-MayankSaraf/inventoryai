"""Wire shapes for the AI document pipeline."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ------------------------------------------------------------- documents

class DocumentOut(BaseModel):
    id: UUID
    original_filename: str
    mime_type: str
    file_extension: str
    file_size_bytes: int
    sha256_hash: str
    page_count: Optional[int] = None
    document_type: Optional[str] = None
    document_type_confidence: Optional[float] = None
    supplier_id: Optional[UUID] = None
    supplier_name: str = ""
    supplier_confidence: Optional[float] = None
    processing_status: str
    processing_stage: Optional[str] = None
    processing_progress: Optional[int] = None
    extraction_confidence: Optional[float] = None
    items_found: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    source: str
    uploaded_by: UUID
    uploaded_by_name: str = ""
    uploaded_at: datetime
    extraction_result_id: Optional[UUID] = None


class UploadResultOut(BaseModel):
    document: DocumentOut
    job_id: Optional[UUID] = None
    #: Set when the same bytes were already uploaded by this tenant
    #: (BR-DOC-02) — the file is *not* processed a second time.
    duplicate_of: Optional[DocumentOut] = None


class DownloadLinkOut(BaseModel):
    url: str
    expires_at: datetime


class SourceDocumentOut(BaseModel):
    id: UUID
    original_filename: str
    mime_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    document_type: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    link_role: str
    linked_at: Optional[datetime] = None


class AttachmentOut(BaseModel):
    link_id: UUID
    document_id: UUID
    original_filename: str
    mime_type: str
    file_extension: str
    file_size_bytes: int
    document_type: Optional[str] = None
    uploaded_at: datetime
    uploaded_by_name: str
    link_role: str
    is_image: bool
    #: Signed, expires in minutes (BR-DOC-03) — re-list for a fresh one.
    url: str
    url_expires_at: datetime


class JobStatusOut(BaseModel):
    document_id: UUID
    job_id: Optional[UUID] = None
    processing_status: str
    processing_stage: Optional[str] = None
    processing_progress: int = 0
    extraction_confidence: Optional[float] = None
    items_found: Optional[int] = None
    extraction_result_id: Optional[UUID] = None
    duration_ms: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


# ------------------------------------------------------------ extraction

class ExtractedFieldOut(BaseModel):
    id: UUID
    field_key: str
    field_label: str
    raw_value: Optional[str] = None
    normalised_value: Optional[str] = None
    corrected_value: Optional[str] = None
    value_type: str
    confidence: Optional[float] = None
    provenance: str
    source_cell: Optional[str] = None
    corrected_by: Optional[UUID] = None
    corrected_at: Optional[datetime] = None
    validation_error: Optional[str] = None


class MatchCandidateOut(BaseModel):
    id: Optional[UUID] = None
    product_variant_id: Optional[UUID] = None
    sku: str = ""
    product_name: str = ""
    rank: int = 0
    match_method: str
    score: Optional[float] = None
    confidence: Optional[float] = None
    reasons: list[str] = Field(default_factory=list)
    is_selected: bool = False


class ExtractedLineOut(BaseModel):
    id: UUID
    line_no: int
    raw_description: str
    normalised_description: Optional[str] = None
    supplier_sku: Optional[str] = None
    raw_quantity: Optional[str] = None
    quantity: Optional[float] = None
    raw_uom: Optional[str] = None
    unit_price: Optional[float] = None
    discount_pct: Optional[float] = None
    gst_rate: Optional[float] = None
    hsn_code: Optional[str] = None
    #: What the document printed. Kept as a cross-check and never stored on
    #: the promoted document (BR-AI-02).
    line_total_as_printed: Optional[float] = None
    matched_variant_id: Optional[UUID] = None
    matched_sku: str = ""
    matched_product_name: str = ""
    match_method: Optional[str] = None
    match_score: Optional[float] = None
    confidence: Optional[float] = None
    provenance: str
    suggestion_text: Optional[str] = None
    final_variant_id: Optional[UUID] = None
    final_decision: Optional[str] = None
    alias_saved: bool = False
    validation_errors: list[dict] = Field(default_factory=list)
    candidates: list[MatchCandidateOut] = Field(default_factory=list)


class TraceStepOut(BaseModel):
    stage: str
    detail: str
    at_ms: Optional[int] = None


class ProviderStatusOut(BaseModel):
    kind: str
    configured: bool
    provider: str
    model_id: Optional[str] = None
    note: str


class ExtractionOut(BaseModel):
    """Everything the review screen needs in one call.

    `totals` are computed here from the *reviewed* quantities and prices —
    they are a preview of what approval will produce, not a value read off
    the document.
    """

    id: UUID
    document: DocumentOut
    job: Optional[JobStatusOut] = None
    document_type: str
    #: The learned layout this was read with, so the review screen can link
    #: to it — "read using the Reliance rate-sheet mapping".
    schema_mapping_id: Optional[UUID] = None
    supplier_id: Optional[UUID] = None
    supplier_name: str = ""
    supplier_confidence: Optional[float] = None
    overall_confidence: Optional[float] = None
    review_status: str
    rejection_reason: Optional[str] = None
    promoted_to_type: Optional[str] = None
    promoted_to_id: Optional[UUID] = None
    fields: list[ExtractedFieldOut] = Field(default_factory=list)
    lines: list[ExtractedLineOut] = Field(default_factory=list)
    totals: dict[str, float] = Field(default_factory=dict)
    unresolved_count: int = 0
    fields_needing_review: int = 0
    can_approve: bool = False
    blocking_reason: Optional[str] = None
    pipeline_trace: list[TraceStepOut] = Field(default_factory=list)
    validation_errors: list[dict] = Field(default_factory=list)
    providers: list[ProviderStatusOut] = Field(default_factory=list)


# --------------------------------------------------------------- review

class FieldCorrection(BaseModel):
    value: str = Field(min_length=1, max_length=500)


class LineUpdate(BaseModel):
    quantity: Optional[float] = Field(default=None, gt=0)
    unit_price: Optional[float] = Field(default=None, ge=0)
    discount_pct: Optional[float] = Field(default=None, ge=0, le=100)
    gst_rate: Optional[float] = Field(default=None, ge=0, le=28)
    hsn_code: Optional[str] = Field(default=None, max_length=20)
    raw_uom: Optional[str] = Field(default=None, max_length=50)


class ConfirmMatchRequest(BaseModel):
    product_variant_id: UUID
    #: BR-AI-06. Default on: the whole point of confirming is that the next
    #: document from this supplier resolves the same code for free.
    save_alias: bool = True


class SkipLineRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class SuggestionsOut(BaseModel):
    line_id: UUID
    rung_reached: str
    auto_matched: bool
    #: Ladder rungs not attempted because no provider is configured.
    skipped_rungs: list[str] = Field(default_factory=list)
    candidates: list[MatchCandidateOut] = Field(default_factory=list)


class ApproveRequest(BaseModel):
    rfq_id: Optional[UUID] = None


class ApprovalOut(BaseModel):
    extraction_result_id: UUID
    promoted_to_type: str
    promoted_to_id: UUID
    line_count: int


class RejectRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class RejectionOut(BaseModel):
    extraction_result_id: UUID
    review_status: str


# -------------------------------------------------------- schema mapping

class CanonicalFieldOut(BaseModel):
    id: UUID
    code: str
    label: str
    field_group: str
    data_type: str
    is_required: bool
    synonyms: list[str] = Field(default_factory=list)
    description: Optional[str] = None


class MappingFieldOut(BaseModel):
    id: UUID
    source_column: str
    source_column_index: Optional[int] = None
    canonical_field_id: UUID
    canonical_code: str
    canonical_label: str
    transform: str
    is_required: bool
    confidence: Optional[float] = None
    confirmed_by: Optional[UUID] = None
    confirmed_at: Optional[datetime] = None


class SchemaMappingOut(BaseModel):
    id: UUID
    supplier_id: Optional[UUID] = None
    supplier_name: str = ""
    document_type: str
    file_format: str
    mapping_name: Optional[str] = None
    column_signature: str
    header_row_index: Optional[int] = None
    data_start_row: Optional[int] = None
    sheet_name: Optional[str] = None
    sample_document_id: Optional[UUID] = None
    status: str
    confidence: Optional[float] = None
    usage_count: int = 0
    last_used_at: Optional[datetime] = None
    success_rate: Optional[float] = None
    version: int = 1
    confirmed_by: Optional[UUID] = None
    confirmed_at: Optional[datetime] = None
    fields: list[MappingFieldOut] = Field(default_factory=list)
    #: Columns in the sample file that no canonical field is mapped to.
    unmapped_columns: list[str] = Field(default_factory=list)


class MappingFieldUpdate(BaseModel):
    canonical_field_id: Optional[UUID] = None
    transform: Optional[str] = Field(
        default=None,
        pattern="^(none|trim|upper|strip_currency|parse_indian_number|percent_to_decimal|date_ddmmyyyy|multiply)$",
    )
    transform_arg: Optional[str] = Field(default=None, max_length=50)


class MappingColumnAdd(BaseModel):
    source_column: str = Field(min_length=1, max_length=200)
    source_column_index: Optional[int] = None
    canonical_field_id: UUID


# ------------------------------------------------------------ assistant

class AssistantRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)


class AssistantAnswerOut(BaseModel):
    intent: str
    source: str
    answer: str
    table: Optional[dict[str, Any]] = None
    breakdown: Optional[list[dict[str, str]]] = None
    link: Optional[dict[str, str]] = None


class EmbeddingStatusOut(BaseModel):
    """How much of the catalogue can be matched by meaning (rung 6)."""

    configured: bool
    provider: str
    model: Optional[str] = None
    dimensions: int
    total_products: int
    embedded: int
    pending: int
    last_generated_at: Optional[datetime] = None
    rebuilding: bool = False
    rebuild_embedded: int = 0
    last_error: Optional[str] = None


class AssistantSuggestionOut(BaseModel):
    intent: str
    question: str
