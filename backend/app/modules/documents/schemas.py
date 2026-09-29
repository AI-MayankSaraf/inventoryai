"""
Proforma, supplier invoice, purchase return and variance wire shapes.

Money and quantities are `float` in these `*Out` models, matching every
other module. All arithmetic happens in `Decimal` inside the services --
Pydantic serialises a `Decimal` field as a JSON *string*, which silently
breaks arithmetic on the frontend (see the note in the inventory module's
schemas, where that cost a debugging session).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

ProformaStatus = Literal["pending", "under_review", "approved", "rejected", "paid", "completed", "cancelled"]
InvoiceStatus = Literal["draft", "under_review", "approved", "disputed", "cancelled"]
MatchStatus = Literal["unmatched", "matched", "variance"]
PaymentStatus = Literal["unpaid", "partially_paid", "paid"]
ReturnStatus = Literal["draft", "sent", "accepted", "credited", "cancelled"]
VarianceStatus = Literal["open", "accepted", "disputed", "resolved"]


# ------------------------------------------------------------- variances

class VarianceOut(BaseModel):
    id: UUID
    variance_type: str
    comparison_kind: str
    base_doc_type: str
    base_doc_id: UUID
    base_line_id: Optional[UUID] = None
    compare_doc_type: str
    compare_doc_id: UUID
    compare_line_id: Optional[UUID] = None
    product_variant_id: Optional[UUID] = None
    sku: str = ""
    product_name: str = ""
    base_value: float
    compare_value: float
    difference: float
    difference_pct: float
    severity: str
    status: VarianceStatus
    resolved_by: Optional[UUID] = None
    resolved_at: Optional[datetime] = None
    resolution_note: Optional[str] = None


class VarianceResolveRequest(BaseModel):
    status: Literal["accepted", "disputed", "resolved"]
    # Required, not optional: "accepted" with no reason is the audit gap
    # this table exists to close (BR-PF-03).
    note: str = Field(min_length=1)


# -------------------------------------------------------------- proforma

class ProformaItemIn(BaseModel):
    purchase_order_item_id: Optional[UUID] = None
    product_variant_id: Optional[UUID] = None
    description: Optional[str] = None
    hsn_code: Optional[str] = None
    quantity: float = Field(gt=0)
    uom_id: UUID
    unit_price: float = Field(ge=0)
    gst_rate: float = Field(default=18, ge=0, le=28)
    cess_rate: float = Field(default=0, ge=0)


class ProformaItemOut(BaseModel):
    id: UUID
    line_no: int
    purchase_order_item_id: Optional[UUID] = None
    product_variant_id: Optional[UUID] = None
    sku: str = ""
    description: str = ""
    hsn_code: Optional[str] = None
    quantity: float
    uom_id: UUID
    uom_code: str = ""
    unit_price: float
    gst_rate: float
    cess_rate: float
    line_net: float
    line_tax: float
    line_total: float
    po_unit_price_snapshot: Optional[float] = None
    price_variance_pct: Optional[float] = None


class ProformaCreate(BaseModel):
    supplier_id: UUID
    purchase_order_id: Optional[UUID] = None
    proforma_number: str = Field(min_length=1, max_length=100)
    proforma_date: Optional[date] = None
    valid_until: Optional[date] = None
    advance_percent: Optional[float] = Field(default=None, ge=0, le=100)
    advance_amount: Optional[float] = Field(default=None, ge=0)
    payment_instructions: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account_no: Optional[str] = None
    bank_ifsc: Optional[str] = None
    bank_branch: Optional[str] = None
    freight_amount: float = Field(default=0, ge=0)
    other_charges: float = Field(default=0, ge=0)
    items: list[ProformaItemIn] = Field(min_length=1)

    @model_validator(mode="after")
    def _dates_in_order(self) -> "ProformaCreate":
        if self.proforma_date and self.valid_until and self.valid_until < self.proforma_date:
            raise ValueError("valid_until cannot be before the proforma date")
        return self


class ProformaUpdate(BaseModel):
    proforma_date: Optional[date] = None
    valid_until: Optional[date] = None
    advance_percent: Optional[float] = Field(default=None, ge=0, le=100)
    advance_amount: Optional[float] = Field(default=None, ge=0)
    payment_instructions: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account_no: Optional[str] = None
    bank_ifsc: Optional[str] = None
    bank_branch: Optional[str] = None
    freight_amount: Optional[float] = Field(default=None, ge=0)
    other_charges: Optional[float] = Field(default=None, ge=0)
    items: Optional[list[ProformaItemIn]] = None
    row_version: int


class ProformaRejectRequest(BaseModel):
    reason: str = Field(min_length=1)


class ProformaQueryRequest(BaseModel):
    note: str = Field(min_length=1)


class ProformaStatusRequest(BaseModel):
    """The transitions without a dedicated verb. Each document type gets its
    own request model rather than sharing one: a shared `status` Literal
    silently rejects the states it wasn't written for, which is exactly how
    the invoice `/status` endpoint shipped unusable the first time."""

    status: Literal["under_review", "paid", "completed", "cancelled"]
    note: Optional[str] = None


class ProformaOut(BaseModel):
    id: UUID
    proforma_number: str
    supplier_id: UUID
    supplier_name: str = ""
    purchase_order_id: Optional[UUID] = None
    po_number: Optional[str] = None
    proforma_date: date
    valid_until: Optional[date] = None
    is_inter_state: bool = False
    subtotal: float = 0
    discount_amount: float = 0
    taxable_value: float = 0
    cgst_amount: float = 0
    sgst_amount: float = 0
    igst_amount: float = 0
    cess_amount: float = 0
    freight_amount: float = 0
    other_charges: float = 0
    round_off: float = 0
    total_amount: float = 0
    po_total_snapshot: Optional[float] = None
    variance_amount: Optional[float] = None
    advance_percent: Optional[float] = None
    advance_amount: Optional[float] = None
    payment_instructions: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account_no: Optional[str] = None
    bank_ifsc: Optional[str] = None
    bank_branch: Optional[str] = None
    status: ProformaStatus
    approved_by: Optional[UUID] = None
    approved_at: Optional[datetime] = None
    query_raised_at: Optional[datetime] = None
    query_note: Optional[str] = None
    row_version: int = 1
    items: list[ProformaItemOut] = Field(default_factory=list)
    item_count: int = 0
    variances: list[VarianceOut] = Field(default_factory=list)


# ------------------------------------------------------- supplier invoice

class InvoiceItemIn(BaseModel):
    purchase_order_item_id: Optional[UUID] = None
    goods_receipt_item_id: Optional[UUID] = None
    product_variant_id: Optional[UUID] = None
    description: Optional[str] = None
    hsn_code: Optional[str] = None
    quantity: float = Field(gt=0)
    uom_id: UUID
    unit_price: float = Field(ge=0)
    discount_pct: float = Field(default=0, ge=0, le=100)
    gst_rate: float = Field(default=18, ge=0, le=28)
    cess_rate: float = Field(default=0, ge=0)


class InvoiceItemOut(BaseModel):
    id: UUID
    line_no: int
    purchase_order_item_id: Optional[UUID] = None
    goods_receipt_item_id: Optional[UUID] = None
    product_variant_id: Optional[UUID] = None
    sku: str = ""
    description: str = ""
    hsn_code: Optional[str] = None
    quantity: float
    uom_id: UUID
    uom_code: str = ""
    unit_price: float
    discount_pct: float
    gst_rate: float
    cess_rate: float
    line_net: float
    line_tax: float
    line_total: float
    po_unit_price_snapshot: Optional[float] = None
    price_variance_pct: Optional[float] = None
    qty_variance: Optional[float] = None


class InvoiceCreate(BaseModel):
    supplier_id: UUID
    invoice_number: str = Field(min_length=1, max_length=100)
    invoice_date: date
    purchase_order_id: Optional[UUID] = None
    goods_receipt_id: Optional[UUID] = None
    supplier_gstin: Optional[str] = None
    due_date: Optional[date] = None
    eway_bill_number: Optional[str] = None
    irn: Optional[str] = None
    freight_amount: float = Field(default=0, ge=0)
    other_charges: float = Field(default=0, ge=0)
    tds_amount: float = Field(default=0, ge=0)
    items: list[InvoiceItemIn] = Field(min_length=1)


class InvoiceUpdate(BaseModel):
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    eway_bill_number: Optional[str] = None
    irn: Optional[str] = None
    freight_amount: Optional[float] = Field(default=None, ge=0)
    other_charges: Optional[float] = Field(default=None, ge=0)
    tds_amount: Optional[float] = Field(default=None, ge=0)
    items: Optional[list[InvoiceItemIn]] = None
    row_version: int


class InvoiceDisputeRequest(BaseModel):
    reason: str = Field(min_length=1)


class InvoicePaymentRequest(BaseModel):
    amount: float = Field(gt=0)


class InvoiceStatusRequest(BaseModel):
    status: Literal["under_review", "cancelled"]
    note: Optional[str] = None


class InvoiceOut(BaseModel):
    id: UUID
    invoice_number: str
    invoice_date: date
    supplier_id: UUID
    supplier_name: str = ""
    purchase_order_id: Optional[UUID] = None
    po_number: Optional[str] = None
    goods_receipt_id: Optional[UUID] = None
    grn_number: Optional[str] = None
    supplier_gstin: Optional[str] = None
    is_inter_state: bool = False
    subtotal: float = 0
    discount_amount: float = 0
    taxable_value: float = 0
    cgst_amount: float = 0
    sgst_amount: float = 0
    igst_amount: float = 0
    cess_amount: float = 0
    freight_amount: float = 0
    other_charges: float = 0
    round_off: float = 0
    total_amount: float = 0
    tds_amount: float = 0
    due_date: Optional[date] = None
    amount_paid: float = 0
    eway_bill_number: Optional[str] = None
    irn: Optional[str] = None
    payment_status: PaymentStatus = "unpaid"
    match_status: MatchStatus = "unmatched"
    variance_amount: Optional[float] = None
    status: InvoiceStatus
    approved_by: Optional[UUID] = None
    approved_at: Optional[datetime] = None
    row_version: int = 1
    items: list[InvoiceItemOut] = Field(default_factory=list)
    item_count: int = 0
    variances: list[VarianceOut] = Field(default_factory=list)


class ThreeWayMatchOut(BaseModel):
    """What `/match` reports back: the verdict plus every difference behind
    it, so a buyer can see *why* an invoice was flagged rather than being
    told only that it was."""

    invoice_id: UUID
    match_status: MatchStatus
    matched_against_po: bool
    matched_against_grn: bool
    variance_amount: float
    variances: list[VarianceOut] = Field(default_factory=list)


# -------------------------------------------------------- purchase return

class ReturnItemIn(BaseModel):
    goods_receipt_item_id: Optional[UUID] = None
    product_variant_id: UUID
    batch_id: Optional[UUID] = None
    quantity: float = Field(gt=0)
    unit_price: float = Field(ge=0)
    gst_rate: float = Field(default=18, ge=0, le=28)


class ReturnItemOut(BaseModel):
    id: UUID
    goods_receipt_item_id: Optional[UUID] = None
    product_variant_id: UUID
    sku: str = ""
    product_name: str = ""
    batch_id: Optional[UUID] = None
    quantity: float
    unit_price: float
    gst_rate: float
    line_total: float
    inventory_transaction_id: Optional[UUID] = None


class ReturnCreate(BaseModel):
    supplier_id: UUID
    godown_id: UUID
    goods_receipt_id: Optional[UUID] = None
    purchase_order_id: Optional[UUID] = None
    return_date: Optional[date] = None
    reason: str = Field(min_length=1)
    debit_note_number: Optional[str] = None
    eway_bill_number: Optional[str] = None
    items: list[ReturnItemIn] = Field(min_length=1)


class ReturnUpdate(BaseModel):
    return_date: Optional[date] = None
    reason: Optional[str] = None
    debit_note_number: Optional[str] = None
    eway_bill_number: Optional[str] = None
    items: Optional[list[ReturnItemIn]] = None


class ReturnStatusRequest(BaseModel):
    status: Literal["sent", "accepted", "credited", "cancelled"]
    note: Optional[str] = None


class ReturnOut(BaseModel):
    id: UUID
    return_number: str
    return_date: date
    supplier_id: UUID
    supplier_name: str = ""
    goods_receipt_id: Optional[UUID] = None
    grn_number: Optional[str] = None
    purchase_order_id: Optional[UUID] = None
    godown_id: UUID
    godown_name: str = ""
    reason: str
    status: ReturnStatus
    debit_note_number: Optional[str] = None
    eway_bill_number: Optional[str] = None
    total_amount: float = 0
    items: list[ReturnItemOut] = Field(default_factory=list)
    item_count: int = 0
    # True once the confirm step has posted PURCHASE_RETURN rows to the
    # ledger. Derived from the lines' own transaction ids rather than stored
    # separately, so it cannot drift from what actually happened.
    stock_posted: bool = False
