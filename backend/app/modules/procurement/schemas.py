"""
Request/response models for the RFQ -> PO -> GRN procurement loop.

Same convention as `catalog/schemas.py`: three shapes per resource
(`*Create`/`*Update`/`*Out`) written out explicitly. Money/quantity fields
are typed `float` here — the wire format everything else in this API uses —
while every computation behind them runs in `Decimal` (`core/money.py`,
`core/inventory.py`); the boundary between the two is the service layer,
never these schemas.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.core import clock
from app.modules.documents.schemas import VarianceOut as DocVarianceOut

# ==================================================================== RFQ


class RfqItemIn(BaseModel):
    product_variant_id: Optional[UUID] = None
    description: Optional[str] = None
    quantity: float = Field(gt=0)
    uom_id: UUID
    expected_price: float = Field(default=0, ge=0)
    target_delivery_date: Optional[date] = None
    remarks: Optional[str] = None

    @model_validator(mode="after")
    def _variant_or_description(self) -> "RfqItemIn":
        # BR-RFQ-02: "either a product_variant_id or a non-empty
        # description (free-text sourcing is legitimate)."
        if not self.product_variant_id and not (self.description and self.description.strip()):
            raise ValueError("Each item needs either product_variant_id or a description")
        return self


class RfqItemOut(RfqItemIn):
    id: UUID
    line_no: int


class RfqCreate(BaseModel):
    rfq_date: Optional[date] = None
    expected_delivery_date: Optional[date] = None
    subject: Optional[str] = None
    delivery_godown_id: Optional[UUID] = None
    notes: Optional[str] = None
    items: list[RfqItemIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _dates(self) -> "RfqCreate":
        # BR-RFQ-05
        if self.rfq_date and self.expected_delivery_date and self.expected_delivery_date < self.rfq_date:
            raise ValueError("expected_delivery_date must be on or after rfq_date")
        return self


class RfqUpdate(BaseModel):
    expected_delivery_date: Optional[date] = None
    subject: Optional[str] = None
    delivery_godown_id: Optional[UUID] = None
    notes: Optional[str] = None
    items: Optional[list[RfqItemIn]] = None


class RfqSupplierOut(BaseModel):
    id: UUID
    supplier_id: UUID
    status: str
    sent_at: Optional[datetime]
    responded_at: Optional[datetime]


class RfqOut(BaseModel):
    id: UUID
    rfq_number: str
    rfq_date: date
    expected_delivery_date: Optional[date]
    subject: Optional[str]
    delivery_godown_id: Optional[UUID]
    notes: Optional[str]
    status: str
    sent_at: Optional[datetime]
    closed_at: Optional[datetime]
    estimated_value: float
    created_from: Optional[str]
    row_version: int
    # Set only when created_from == 'imported' (BR-RFQ-09).
    external_source_name: Optional[str] = None
    external_reference_number: Optional[str] = None
    source_file_name: Optional[str] = None
    items: list[RfqItemOut] = Field(default_factory=list)
    suppliers: list[RfqSupplierOut] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RfqSendRequest(BaseModel):
    supplier_ids: list[UUID] = Field(min_length=1)


class RfqCancelRequest(BaseModel):
    reason: Optional[str] = None


# ============================================================= RFQ import

class RfqImportPreviewRow(BaseModel):
    source_row: int
    description: str
    quantity: float
    uom_id: UUID
    uom_code: str
    expected_price: float
    remarks: Optional[str] = None


class RfqImportColumnOut(BaseModel):
    """One RFQ field and which column of the file feeds it."""

    field: str
    label: str
    required: bool
    column_index: Optional[int] = None
    header: Optional[str] = None
    #: 0-100. How sure the detection was; 100 for saved or manual mappings.
    confidence: int = 0
    #: exact | contains | similar (heading synonyms), values (read from what
    #: the column holds), ai (heading meaning, via embeddings), llm
    #: (language model, checked against the values), saved | manual — or
    #: null when unmapped.
    match: Optional[str] = None
    #: Why, for values/ai/llm matches — shown next to the suggestion.
    reason: Optional[str] = None


class RfqImportPreviewOut(BaseModel):
    """What `rfq_import.parse` found, before anything is written — the
    "preview and validate before import" step. `errors` non-empty means the
    import endpoint will refuse the same file with the same overrides for
    the same reasons; `warnings` are things it will import anyway.

    `headers`, `sample_rows` and `columns` drive the mapping step: the
    screen shows which column feeds each field and lets a person change it,
    then previews again with `column_map`/`header_row`/`sheet_index`."""

    rows: list[RfqImportPreviewRow]
    errors: list[str]
    warnings: list[str] = []
    row_count: int
    sheet_names: list[str] = []
    sheet_index: int = 0
    #: 1-based row the column headings were read from.
    header_row: Optional[int] = None
    headers: list[str] = []
    sample_rows: list[list[str]] = []
    columns: list[RfqImportColumnOut] = []
    missing_required: list[str] = []
    #: auto | saved | manual
    layout_source: str = "auto"
    column_map: dict[str, int] = {}


# ===================================================================== PO


class PoItemIn(BaseModel):
    product_variant_id: UUID
    description: Optional[str] = None
    hsn_code: Optional[str] = None
    quantity: float = Field(gt=0)
    uom_id: UUID
    unit_price: float = Field(ge=0)
    discount_pct: float = Field(default=0, ge=0, le=100)
    gst_rate: float = Field(ge=0, le=28)
    cess_rate: float = Field(default=0, ge=0)
    expected_delivery_date: Optional[date] = None
    rfq_item_id: Optional[UUID] = None
    quotation_item_id: Optional[UUID] = None


class PoItemOut(BaseModel):
    id: UUID
    line_no: int
    product_variant_id: UUID
    quotation_item_id: Optional[UUID] = None
    rfq_item_id: Optional[UUID] = None
    description: Optional[str]
    hsn_code: Optional[str]
    quantity: float
    uom_id: UUID
    conversion_factor: float
    unit_price: float
    discount_pct: float
    discount_amount: float
    gst_rate: float
    cess_rate: float
    line_net: float
    line_tax: float
    line_total: float
    received_quantity: float
    returned_quantity: float
    invoiced_quantity: float
    pending_quantity: float
    line_status: str
    expected_delivery_date: Optional[date]


class PoCreate(BaseModel):
    supplier_id: UUID
    delivery_godown_id: UUID
    po_date: Optional[date] = None
    expected_delivery_date: Optional[date] = None
    payment_terms: Optional[str] = None
    delivery_terms: Optional[str] = None
    rfq_id: Optional[UUID] = None
    freight_amount: float = Field(default=0, ge=0)
    other_charges: float = Field(default=0, ge=0)
    notes: Optional[str] = None
    items: list[PoItemIn] = Field(default_factory=list)


class PoUpdate(BaseModel):
    expected_delivery_date: Optional[date] = None
    payment_terms: Optional[str] = None
    delivery_terms: Optional[str] = None
    delivery_godown_id: Optional[UUID] = None
    freight_amount: Optional[float] = Field(default=None, ge=0)
    other_charges: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = None
    items: Optional[list[PoItemIn]] = None
    row_version: int  # optimistic-lock token; required on every edit


class PoOut(BaseModel):
    id: UUID
    po_number: str
    supplier_id: UUID
    rfq_id: Optional[UUID]
    quotation_id: Optional[UUID]
    comparison_id: Optional[UUID] = None
    po_date: date
    expected_delivery_date: Optional[date]
    delivery_godown_id: UUID
    payment_terms: Optional[str]
    delivery_terms: Optional[str]
    place_of_supply_state_code: str
    is_inter_state: bool
    currency_code: str
    subtotal: float
    discount_amount: float
    taxable_value: float
    cgst_amount: float
    sgst_amount: float
    igst_amount: float
    cess_amount: float
    freight_amount: float
    other_charges: float
    round_off: float
    total_amount: float
    status: str
    approved_by: Optional[UUID]
    approved_at: Optional[datetime]
    sent_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    cancelled_by: Optional[UUID] = None
    cancelled_by_name: Optional[str] = None
    cancellation_reason: Optional[str]
    notes: Optional[str] = None
    received_pct: float
    fully_received_at: Optional[datetime]
    row_version: int
    created_at: datetime
    updated_at: datetime
    items: list[PoItemOut] = Field(default_factory=list)


class PoCancelRequest(BaseModel):
    reason: str = Field(min_length=1)


class PoCloseRequest(BaseModel):
    reason: Optional[str] = None


# ==================================================================== GRN

_ISSUE_TYPES = "^(none|short|excess|damaged|expired|wrong_product|wrong_variant|wrong_model|wrong_brand)$"


class GrnItemIn(BaseModel):
    purchase_order_item_id: Optional[UUID] = None
    product_variant_id: UUID
    batch_number: Optional[str] = None
    manufactured_on: Optional[date] = None
    expires_on: Optional[date] = None
    mrp: Optional[float] = Field(default=None, ge=0)
    received_quantity: float = Field(ge=0)
    accepted_quantity: float = Field(ge=0)
    uom_id: UUID
    unit_price: Optional[float] = Field(default=None, ge=0)
    issue_type: str = Field(default="none", pattern=_ISSUE_TYPES)
    expected_variant_id: Optional[UUID] = None
    rejection_reason: Optional[str] = None
    remarks: Optional[str] = None

    @model_validator(mode="after")
    def _accepted_within_received(self) -> "GrnItemIn":
        # BR-GRN-01 (also DB-enforced; checked here for a clean 422)
        if self.accepted_quantity > self.received_quantity:
            raise ValueError("accepted_quantity cannot exceed received_quantity")
        return self


class GrnItemOut(BaseModel):
    id: UUID
    line_no: int
    purchase_order_item_id: Optional[UUID]
    product_variant_id: UUID
    batch_id: Optional[UUID]
    ordered_quantity: Optional[float]
    previously_received_quantity: Optional[float]
    received_quantity: float
    accepted_quantity: float
    rejected_quantity: float
    uom_id: UUID
    conversion_factor: float
    unit_price: Optional[float]
    issue_type: str
    expected_variant_id: Optional[UUID]
    rejection_reason: Optional[str]
    remarks: Optional[str]
    inventory_transaction_id: Optional[UUID] = None
    batch_number: Optional[str] = None
    manufactured_on: Optional[date] = None
    expires_on: Optional[date] = None
    #: What actually reached the ledger for this line — null until the
    #: receipt is confirmed, and the figure the detail screen shows as
    #: "posted" rather than re-displaying `accepted_quantity`.
    posted_quantity: Optional[float] = None


class GrnCreate(BaseModel):
    supplier_id: UUID
    purchase_order_id: Optional[UUID] = None
    godown_id: UUID
    grn_date: Optional[date] = None
    vehicle_number: Optional[str] = None
    transporter_name: Optional[str] = None
    lr_number: Optional[str] = None
    eway_bill_number: Optional[str] = None
    gate_entry_number: Optional[str] = None
    supplier_challan_number: Optional[str] = None
    supplier_challan_date: Optional[date] = None
    remarks: Optional[str] = None
    items: list[GrnItemIn] = Field(min_length=1)

    @model_validator(mode="after")
    def _date_not_future(self) -> "GrnCreate":
        # BR-GRN-13
        if self.grn_date and clock.is_future_day(self.grn_date):
            raise ValueError("grn_date cannot be in the future")
        return self


class GrnOut(BaseModel):
    id: UUID
    grn_number: str
    grn_date: date
    supplier_id: UUID
    purchase_order_id: Optional[UUID]
    godown_id: UUID
    received_by: UUID
    vehicle_number: Optional[str]
    transporter_name: Optional[str]
    lr_number: Optional[str]
    eway_bill_number: Optional[str]
    gate_entry_number: Optional[str]
    supplier_challan_number: Optional[str]
    supplier_challan_date: Optional[date]
    status: str
    confirmed_by: Optional[UUID]
    confirmed_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    cancelled_by: Optional[UUID] = None
    cancelled_by_name: Optional[str] = None
    cancellation_reason: Optional[str] = None
    has_discrepancy: Optional[bool]
    remarks: Optional[str]
    row_version: int
    created_at: datetime
    updated_at: datetime
    items: list[GrnItemOut] = Field(default_factory=list)
    reversal: Optional["GrnReversalOut"] = None


class GrnReversalOut(BaseModel):
    """Set once `POST .../reverse` has run against this receipt. A reversal
    is not a second GRN (BR-GRN-08 posts offsetting rows against this one),
    so this is read back from the audit trail."""

    reversed_at: datetime
    reversed_by: Optional[UUID] = None
    reversed_by_name: str = ""
    reason: Optional[str] = None


class GrnUpdate(BaseModel):
    """Edit a draft receipt. Supplier and linked PO are fixed at creation."""

    grn_date: Optional[date] = None
    godown_id: Optional[UUID] = None
    vehicle_number: Optional[str] = None
    transporter_name: Optional[str] = None
    lr_number: Optional[str] = None
    eway_bill_number: Optional[str] = None
    gate_entry_number: Optional[str] = None
    supplier_challan_number: Optional[str] = None
    supplier_challan_date: Optional[date] = None
    remarks: Optional[str] = None
    items: list[GrnItemIn] = Field(min_length=1)
    row_version: int  # optimistic-lock token; required on every edit

    @model_validator(mode="after")
    def _date_not_future(self) -> "GrnUpdate":
        if self.grn_date and clock.is_future_day(self.grn_date):
            raise ValueError("grn_date cannot be in the future")
        return self


class GrnPostingOut(BaseModel):
    """One ledger row this receipt produced."""

    inventory_transaction_id: UUID
    goods_receipt_item_id: Optional[UUID]
    txn_number: str
    txn_type: str
    txn_date: datetime
    posted_at: datetime
    product_variant_id: UUID
    sku: str
    godown_id: UUID
    godown_name: str
    quantity: float
    uom_id: UUID
    balance_now: Optional[float] = None
    #: Set on the offsetting rows a reversal posts.
    reverses_txn_id: Optional[UUID] = None


class GrnConfirmOut(BaseModel):
    """What confirming actually did — 04_API_SPECIFICATION.md §3.18."""

    goods_receipt: GrnOut
    inventory_postings: list[GrnPostingOut] = Field(default_factory=list)
    purchase_order: Optional["GrnConfirmPoOut"] = None
    #: `documents.schemas.VarianceOut` rows — the same shape the payables
    #: screens already read, so one mapper serves both.
    variances: list[DocVarianceOut] = Field(default_factory=list)
    alerts_raised: list[UUID] = Field(default_factory=list)


class GrnConfirmPoOut(BaseModel):
    id: UUID
    po_number: str
    received_pct: float
    status: str


class GrnReverseLine(BaseModel):
    goods_receipt_item_id: UUID
    quantity: float = Field(gt=0)


class GrnCancelRequest(BaseModel):
    """Why a draft receipt was cancelled. Optional so older clients that
    post no body keep working."""

    reason: Optional[str] = None


class GrnReverseRequest(BaseModel):
    reason: str = Field(min_length=1)
    lines: Optional[list[GrnReverseLine]] = None


# ============================================================== Quotations


class QuotationItemIn(BaseModel):
    rfq_item_id: Optional[UUID] = None
    product_variant_id: Optional[UUID] = None
    raw_description: Optional[str] = None
    supplier_sku: Optional[str] = None
    quantity: float = Field(gt=0)
    uom_id: UUID
    unit_price: float = Field(ge=0)
    discount_pct: float = Field(default=0, ge=0, le=100)
    gst_rate: float = Field(ge=0, le=28)
    cess_rate: float = Field(default=0, ge=0)
    is_available: bool = True
    availability_note: Optional[str] = None
    lead_time_days: Optional[int] = None

    @model_validator(mode="after")
    def _variant_or_description(self) -> "QuotationItemIn":
        # Same shape as BR-RFQ-02 — a line needs something to identify what
        # is being quoted, matched SKU or not.
        if not self.product_variant_id and not (self.raw_description and self.raw_description.strip()):
            raise ValueError("Each item needs either product_variant_id or raw_description")
        return self


class QuotationItemOut(BaseModel):
    id: UUID
    line_no: int
    rfq_item_id: Optional[UUID]
    product_variant_id: Optional[UUID]
    raw_description: Optional[str]
    supplier_sku: Optional[str]
    quantity: float
    uom_id: UUID
    unit_price: float
    discount_pct: float
    gst_rate: float
    cess_rate: float
    line_net: float
    line_tax: float
    line_total: float
    is_available: bool
    availability_note: Optional[str]
    lead_time_days: Optional[int]
    provenance: str


class QuotationCreate(BaseModel):
    supplier_id: UUID
    rfq_id: Optional[UUID] = None
    quotation_number: str = Field(min_length=1)
    quotation_date: Optional[date] = None
    valid_until: Optional[date] = None
    payment_terms: Optional[str] = None
    delivery_terms: Optional[str] = None
    delivery_period_days: Optional[int] = None
    warranty_terms: Optional[str] = None
    freight_terms: Optional[str] = None
    freight_amount: float = Field(default=0, ge=0)
    other_charges: float = Field(default=0, ge=0)
    items: list[QuotationItemIn] = Field(min_length=1)


class QuotationUpdate(BaseModel):
    quotation_number: Optional[str] = None
    quotation_date: Optional[date] = None
    valid_until: Optional[date] = None
    payment_terms: Optional[str] = None
    delivery_terms: Optional[str] = None
    delivery_period_days: Optional[int] = None
    warranty_terms: Optional[str] = None
    freight_terms: Optional[str] = None
    freight_amount: Optional[float] = Field(default=None, ge=0)
    other_charges: Optional[float] = Field(default=None, ge=0)
    items: Optional[list[QuotationItemIn]] = None


class QuotationOut(BaseModel):
    id: UUID
    quotation_number: str
    supplier_id: UUID
    rfq_id: Optional[UUID]
    quotation_date: date
    valid_until: Optional[date]
    currency_code: str
    subtotal: float
    discount_amount: float
    taxable_value: float
    tax_amount: float
    freight_amount: float
    other_charges: float
    round_off: float
    total_amount: float
    payment_terms: Optional[str]
    delivery_terms: Optional[str]
    delivery_period_days: Optional[int]
    warranty_terms: Optional[str]
    freight_terms: Optional[str]
    source: str
    status: str
    approved_by: Optional[UUID]
    approved_at: Optional[datetime]
    rejected_reason: Optional[str]
    row_version: int
    items: list[QuotationItemOut] = Field(default_factory=list)
    is_expired: bool = False
    # `list_quotations` deliberately doesn't hydrate `items` (would be an
    # N+1 fan-out over every quotation on the list screen) but list rows
    # still need to show an item count — this is a cheap COUNT(*) instead.
    item_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class QuotationRejectRequest(BaseModel):
    reason: str = Field(min_length=1)


# ============================================================== Comparison


class ComparisonBuildRequest(BaseModel):
    rfq_id: UUID
    name: Optional[str] = None
    quotation_ids: Optional[list[UUID]] = None  # explicit subset; default is "all approved for this RFQ"


class ComparisonCellOut(BaseModel):
    supplier_id: UUID
    quotation_id: UUID
    quotation_item_id: UUID
    unit_price: float
    landed_unit_cost: float
    line_total: float
    gst_rate: float
    is_available: bool
    availability_note: Optional[str]
    is_lowest: bool


class ComparisonRowOut(BaseModel):
    line_id: UUID
    rfq_item_id: UUID
    product_variant_id: Optional[UUID]
    quantity: float
    cells: list[ComparisonCellOut] = Field(default_factory=list)
    recommended_quotation_item_id: Optional[UUID]
    recommended_supplier_id: Optional[UUID]
    recommendation_reason: Optional[str]
    recommendation_score: Optional[float]
    price_spread_pct: Optional[float]
    selected_quotation_item_id: Optional[UUID]
    selected_supplier_id: Optional[UUID]
    override_reason: Optional[str]


class ComparisonSupplierOut(BaseModel):
    supplier_id: UUID
    name: str
    quotation_id: UUID
    quotation_number: str
    valid_until: Optional[date]
    is_expired: bool
    total_amount: float
    missing_lines: int


class ComparisonOut(BaseModel):
    id: UUID
    rfq_id: UUID
    name: Optional[str]
    strategy: str
    status: str
    single_supplier_best_total: Optional[float]
    split_total: Optional[float]
    projected_savings: Optional[float]
    notes: Optional[str]
    suppliers: list[ComparisonSupplierOut] = Field(default_factory=list)
    rows: list[ComparisonRowOut] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ComparisonOverrideRequest(BaseModel):
    quotation_item_id: UUID
    reason: Optional[str] = None


class ComparisonConvertSelection(BaseModel):
    rfq_item_id: UUID
    quotation_item_id: UUID


class ComparisonConvertRequest(BaseModel):
    delivery_godown_id: UUID
    expected_delivery_date: Optional[date] = None
    payment_terms: Optional[str] = None
    delivery_terms: Optional[str] = None
    allow_expired: bool = False
    selections: Optional[list[ComparisonConvertSelection]] = None  # default: every row's current selection


class ComparisonConvertResponse(BaseModel):
    purchase_orders: list[PoOut]
    comparison_status: str
