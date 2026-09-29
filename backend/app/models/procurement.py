"""
Procurement workflow — `02_DATABASE_DESIGN.md` §6.

rfqs -> rfq_items / rfq_suppliers -> supplier_quotations -> quotation_items
     -> quotation_comparisons -> purchase_orders -> purchase_order_items
         -> proforma_invoices, goods_receipts, supplier_invoices
     -> purchase_returns, document_variances

Every arrow in §6.1's chain-of-custody diagram is a real FK here; the
prototype's string-number links (`linkedRfq`, `poNumber`) become FKs, and
the human-readable number stays as a display column.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Computed,
    Date,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    Factor,
    Money,
    Pct,
    Qty,
    Rate,
    RowVersionMixin,
    Score,
    TenantMixin,
    UUIDPkMixin,
    VariancePct,
    enum_check,
    plain_fk,
    tenant_fk,
    uq_company_id,
)

# ============================================================== 6.2-6.7 RFQ


class Rfq(UUIDPkMixin, TenantMixin, RowVersionMixin, Base):
    __tablename__ = "rfqs"

    rfq_number: Mapped[str] = mapped_column(Text, nullable=False)
    rfq_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=text("CURRENT_DATE"), index=True)
    expected_delivery_date: Mapped[Optional[date]] = mapped_column(Date)
    subject: Mapped[Optional[str]] = mapped_column(Text, index=True)
    delivery_godown_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"), index=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column()
    closed_at: Mapped[Optional[datetime]] = mapped_column()
    estimated_value: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    created_from: Mapped[Optional[str]] = mapped_column(Text)
    # RFQ import (migration a3f6c92e0d17): where an imported RFQ came from,
    # the buyer's own number, and the uploaded file's name.
    external_source_name: Mapped[Optional[str]] = mapped_column(Text)
    external_reference_number: Mapped[Optional[str]] = mapped_column(Text)
    source_file_name: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        uq_company_id("rfqs"),
        tenant_fk("rfqs", "delivery_godown_id", "godowns", ondelete="RESTRICT"),
        UniqueConstraint("company_id", "rfq_number", name="uq_rfq_number"),
        Index("ix_rfqs_status_date", "company_id", "status", "rfq_date"),
        enum_check(
            "status", ["draft", "sent", "partially_quoted", "quoted", "under_review", "closed", "cancelled"]
        ),
        enum_check("created_from", ["manual", "low_stock", "imported"]),
    )


class RfqItem(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "rfq_items"

    rfq_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    product_variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[float] = mapped_column(Qty, nullable=False)
    uom_id: Mapped[uuid.UUID] = plain_fk("uoms.id", nullable=False)
    expected_price: Mapped[float] = mapped_column(Rate, nullable=False, server_default=text("0"))
    target_delivery_date: Mapped[Optional[date]] = mapped_column(Date)
    remarks: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        uq_company_id("rfq_items"),
        tenant_fk("rfq_items", "rfq_id", "rfqs", ondelete="CASCADE"),
        tenant_fk("rfq_items", "product_variant_id", "product_variants", ondelete="RESTRICT"),
        UniqueConstraint("rfq_id", "line_no", name="uq_rfq_item_line"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )


class RfqSupplier(UUIDPkMixin, TenantMixin, Base):
    """M:N between an RFQ and the suppliers it was sent to, plus per-supplier
    dispatch state (§6.4)."""

    __tablename__ = "rfq_suppliers"

    rfq_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    supplier_contact_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column()
    sent_channel: Mapped[Optional[str]] = mapped_column(Text)
    outbound_message_id: Mapped[Optional[uuid.UUID]] = plain_fk("outbound_messages.id", ondelete="SET NULL")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    responded_at: Mapped[Optional[datetime]] = mapped_column()
    decline_reason: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        uq_company_id("rfq_suppliers"),
        tenant_fk("rfq_suppliers", "rfq_id", "rfqs", ondelete="CASCADE"),
        tenant_fk("rfq_suppliers", "supplier_id", "suppliers", ondelete="RESTRICT"),
        tenant_fk("rfq_suppliers", "supplier_contact_id", "supplier_contacts", ondelete="SET NULL"),
        UniqueConstraint("rfq_id", "supplier_id", name="uq_rfq_supplier"),
        enum_check("sent_channel", ["email", "whatsapp", "manual", "portal"]),
        enum_check("status", ["pending", "sent", "failed", "viewed", "quoted", "declined"]),
    )


class SupplierQuotation(UUIDPkMixin, TenantMixin, RowVersionMixin, Base):
    __tablename__ = "supplier_quotations"

    quotation_number: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    rfq_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    quotation_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    valid_until: Mapped[Optional[date]] = mapped_column(Date, index=True)
    currency_code: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'INR'"))
    subtotal: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    discount_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    taxable_value: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    tax_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    freight_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    other_charges: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    round_off: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    total_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    payment_terms: Mapped[Optional[str]] = mapped_column(Text)
    delivery_terms: Mapped[Optional[str]] = mapped_column(Text)
    delivery_period_days: Mapped[Optional[int]] = mapped_column(SmallInteger)
    warranty_terms: Mapped[Optional[str]] = mapped_column(Text)
    freight_terms: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"), index=True)
    document_id: Mapped[Optional[uuid.UUID]] = plain_fk("documents.id", ondelete="SET NULL")
    ai_extraction_result_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True))
    extraction_confidence: Mapped[Optional[float]] = mapped_column(Pct)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"), index=True)
    approved_by: Mapped[Optional[uuid.UUID]] = plain_fk("users.id", ondelete="SET NULL")
    approved_at: Mapped[Optional[datetime]] = mapped_column()
    rejected_reason: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        uq_company_id("supplier_quotations"),
        tenant_fk("supplier_quotations", "supplier_id", "suppliers", ondelete="RESTRICT"),
        tenant_fk("supplier_quotations", "rfq_id", "rfqs", ondelete="RESTRICT"),
        tenant_fk("supplier_quotations", "ai_extraction_result_id", "ai_extraction_results", ondelete="SET NULL"),
        Index(
            "uq_quotation",
            "company_id",
            "supplier_id",
            func.upper(quotation_number),
            unique=True,
        ),
        enum_check(
            "status",
            ["draft", "under_review", "approved", "rejected", "expired", "superseded", "converted"],
        ),
        enum_check("source", ["ai_extracted", "manual", "email", "portal"]),
    )


class SupplierQuotationItem(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "supplier_quotation_items"

    quotation_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    rfq_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    product_variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    raw_description: Mapped[Optional[str]] = mapped_column(Text)
    supplier_sku: Mapped[Optional[str]] = mapped_column(Text)
    quantity: Mapped[float] = mapped_column(Qty, nullable=False)
    uom_id: Mapped[uuid.UUID] = plain_fk("uoms.id", nullable=False)
    unit_price: Mapped[float] = mapped_column(Rate, nullable=False)
    discount_pct: Mapped[float] = mapped_column(Pct, nullable=False, server_default=text("0"))
    gst_rate: Mapped[float] = mapped_column(Pct, nullable=False)
    cess_rate: Mapped[float] = mapped_column(Pct, nullable=False, server_default=text("0"))
    line_net: Mapped[float] = mapped_column(Money, nullable=False)
    line_tax: Mapped[float] = mapped_column(Money, nullable=False)
    line_total: Mapped[float] = mapped_column(Money, nullable=False)
    is_available: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    availability_note: Mapped[Optional[str]] = mapped_column(Text)
    lead_time_days: Mapped[Optional[int]] = mapped_column(SmallInteger)
    match_confidence: Mapped[Optional[float]] = mapped_column(Pct)
    match_method: Mapped[Optional[str]] = mapped_column(Text)
    provenance: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'ai_extracted'"))

    __table_args__ = (
        uq_company_id("supplier_quotation_items"),
        tenant_fk("supplier_quotation_items", "quotation_id", "supplier_quotations", ondelete="CASCADE"),
        tenant_fk("supplier_quotation_items", "rfq_item_id", "rfq_items", ondelete="SET NULL"),
        tenant_fk("supplier_quotation_items", "product_variant_id", "product_variants", ondelete="RESTRICT"),
        UniqueConstraint("quotation_id", "line_no", name="uq_quotation_item_line"),
        enum_check(
            "provenance", ["ai_extracted", "ai_suggested", "needs_review", "user_approved", "calculated"]
        ),
    )


class QuotationComparison(UUIDPkMixin, TenantMixin, Base):
    """(RECOMMENDED) The sourcing decision — today lost in `sessionStorage`
    (§6.7)."""

    __tablename__ = "quotation_comparisons"

    rfq_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(Text)
    compared_supplier_ids: Mapped[Optional[list[uuid.UUID]]] = mapped_column(ARRAY(PGUUID(as_uuid=True)))
    strategy: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'lowest_price'"))
    single_supplier_best_total: Mapped[Optional[float]] = mapped_column(Money)
    split_total: Mapped[Optional[float]] = mapped_column(Money)
    projected_savings: Mapped[Optional[float]] = mapped_column(Money)
    decided_by: Mapped[Optional[uuid.UUID]] = plain_fk("users.id", ondelete="SET NULL")
    decided_at: Mapped[Optional[datetime]] = mapped_column()
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        uq_company_id("quotation_comparisons"),
        tenant_fk("quotation_comparisons", "rfq_id", "rfqs", ondelete="CASCADE"),
        enum_check("strategy", ["lowest_price", "split_optimal", "manual"]),
        enum_check("status", ["draft", "decided", "converted", "discarded"]),
    )


class QuotationComparisonLine(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "quotation_comparison_lines"

    comparison_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    rfq_item_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    product_variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    quantity: Mapped[float] = mapped_column(Qty, nullable=False)
    selected_quotation_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    selected_supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    recommended_quotation_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    recommendation_reason: Mapped[Optional[str]] = mapped_column(Text)
    recommendation_score: Mapped[Optional[float]] = mapped_column(Score)
    price_spread_pct: Mapped[Optional[float]] = mapped_column(Pct)
    override_reason: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        uq_company_id("quotation_comparison_lines"),
        tenant_fk("quotation_comparison_lines", "comparison_id", "quotation_comparisons", ondelete="CASCADE"),
        tenant_fk("quotation_comparison_lines", "rfq_item_id", "rfq_items", ondelete="RESTRICT"),
        tenant_fk("quotation_comparison_lines", "product_variant_id", "product_variants", ondelete="RESTRICT"),
        tenant_fk(
            "quotation_comparison_lines", "selected_quotation_item_id", "supplier_quotation_items", ondelete="SET NULL"
        ),
        tenant_fk("quotation_comparison_lines", "selected_supplier_id", "suppliers", ondelete="SET NULL"),
        tenant_fk(
            "quotation_comparison_lines",
            "recommended_quotation_item_id",
            "supplier_quotation_items",
            ondelete="SET NULL",
        ),
    )


# =========================================================== 6.8-6.9 PO


class PurchaseOrder(UUIDPkMixin, TenantMixin, RowVersionMixin, Base):
    __tablename__ = "purchase_orders"

    po_number: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    rfq_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    quotation_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    comparison_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    po_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=text("CURRENT_DATE"), index=True)
    expected_delivery_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    delivery_godown_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    delivery_address_override: Mapped[Optional[str]] = mapped_column(Text)
    payment_terms: Mapped[Optional[str]] = mapped_column(Text)
    delivery_terms: Mapped[Optional[str]] = mapped_column(Text)
    place_of_supply_state_code: Mapped[str] = mapped_column(Text, nullable=False)
    is_inter_state: Mapped[bool] = mapped_column(nullable=False)
    currency_code: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'INR'"))
    subtotal: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    discount_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    taxable_value: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    cgst_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    sgst_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    igst_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    cess_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    freight_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    other_charges: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    round_off: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    total_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"), index=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"), index=True)
    approved_by: Mapped[Optional[uuid.UUID]] = plain_fk("users.id", ondelete="SET NULL")
    approved_at: Mapped[Optional[datetime]] = mapped_column()
    sent_at: Mapped[Optional[datetime]] = mapped_column()
    sent_to_email: Mapped[Optional[str]] = mapped_column(Text)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column()
    cancelled_by: Mapped[Optional[uuid.UUID]] = plain_fk("users.id", ondelete="SET NULL")
    cancellation_reason: Mapped[Optional[str]] = mapped_column(Text)
    received_pct: Mapped[float] = mapped_column(Pct, nullable=False, server_default=text("0"))
    fully_received_at: Mapped[Optional[datetime]] = mapped_column()

    __table_args__ = (
        uq_company_id("purchase_orders"),
        tenant_fk("purchase_orders", "supplier_id", "suppliers", ondelete="RESTRICT"),
        tenant_fk("purchase_orders", "rfq_id", "rfqs", ondelete="RESTRICT"),
        tenant_fk("purchase_orders", "quotation_id", "supplier_quotations", ondelete="RESTRICT"),
        tenant_fk("purchase_orders", "comparison_id", "quotation_comparisons", ondelete="RESTRICT"),
        tenant_fk("purchase_orders", "delivery_godown_id", "godowns", ondelete="RESTRICT"),
        UniqueConstraint("company_id", "po_number", name="uq_po_number"),
        Index("ix_purchase_orders_status_date", "company_id", "status", "po_date"),
        Index("ix_purchase_orders_supplier_date", "company_id", "supplier_id", "po_date"),
        CheckConstraint(
            "NOT (is_inter_state AND (cgst_amount > 0 OR sgst_amount > 0))", name="interstate_excludes_cgst_sgst"
        ),
        CheckConstraint("NOT (NOT is_inter_state AND igst_amount > 0)", name="intrastate_excludes_igst"),
        enum_check(
            "status",
            [
                "draft",
                "pending_approval",
                "approved",
                "sent",
                "acknowledged",
                "partially_received",
                "received",
                "closed",
                "cancelled",
            ],
        ),
        enum_check("payment_terms", ["Advance", "15 Days", "30 Days", "45 Days", "Cash on Delivery"]),
        enum_check("delivery_terms", ["FOR", "Ex-Works", "Door Delivery", "To Pay"]),
    )


class PurchaseOrderItem(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "purchase_order_items"

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    product_variant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    quotation_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    rfq_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    hsn_code: Mapped[Optional[str]] = mapped_column(Text)
    quantity: Mapped[float] = mapped_column(Qty, nullable=False)
    uom_id: Mapped[uuid.UUID] = plain_fk("uoms.id", nullable=False)
    conversion_factor: Mapped[float] = mapped_column(Factor, nullable=False, server_default=text("1"))
    unit_price: Mapped[float] = mapped_column(Rate, nullable=False)
    discount_pct: Mapped[float] = mapped_column(Pct, nullable=False, server_default=text("0"))
    discount_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    gst_rate: Mapped[float] = mapped_column(Pct, nullable=False)
    cess_rate: Mapped[float] = mapped_column(Pct, nullable=False, server_default=text("0"))
    line_net: Mapped[float] = mapped_column(Money, nullable=False)
    line_tax: Mapped[float] = mapped_column(Money, nullable=False)
    line_total: Mapped[float] = mapped_column(Money, nullable=False)
    received_quantity: Mapped[float] = mapped_column(Qty, nullable=False, server_default=text("0"))
    returned_quantity: Mapped[float] = mapped_column(Qty, nullable=False, server_default=text("0"))
    invoiced_quantity: Mapped[float] = mapped_column(Qty, nullable=False, server_default=text("0"))
    pending_quantity: Mapped[float] = mapped_column(Qty, Computed("quantity - received_quantity", persisted=True))
    line_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"), index=True)
    expected_delivery_date: Mapped[Optional[date]] = mapped_column(Date)

    __table_args__ = (
        uq_company_id("purchase_order_items"),
        tenant_fk("purchase_order_items", "purchase_order_id", "purchase_orders", ondelete="CASCADE"),
        tenant_fk("purchase_order_items", "product_variant_id", "product_variants", ondelete="RESTRICT"),
        tenant_fk("purchase_order_items", "quotation_item_id", "supplier_quotation_items", ondelete="SET NULL"),
        tenant_fk("purchase_order_items", "rfq_item_id", "rfq_items", ondelete="SET NULL"),
        UniqueConstraint("purchase_order_id", "line_no", name="uq_po_item_line"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("discount_pct BETWEEN 0 AND 100", name="discount_pct_range"),
        enum_check(
            "line_status", ["open", "partially_received", "received", "short_closed", "cancelled"]
        ),
    )


# ============================================================ 6.10 Proforma


class ProformaInvoice(UUIDPkMixin, TenantMixin, RowVersionMixin, Base):
    """Not a statutory tax invoice — an advance-payment request (§6.10)."""

    __tablename__ = "proforma_invoices"

    proforma_number: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    purchase_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    proforma_date: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[Optional[date]] = mapped_column(Date)
    place_of_supply_state_code: Mapped[Optional[str]] = mapped_column(Text)
    is_inter_state: Mapped[Optional[bool]] = mapped_column()
    subtotal: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    discount_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    taxable_value: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    cgst_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    sgst_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    igst_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    cess_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    freight_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    other_charges: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    round_off: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    total_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    po_total_snapshot: Mapped[Optional[float]] = mapped_column(Money)
    variance_amount: Mapped[Optional[float]] = mapped_column(
        Money, Computed("total_amount - po_total_snapshot", persisted=True)
    )
    advance_percent: Mapped[Optional[float]] = mapped_column(Pct)
    advance_amount: Mapped[Optional[float]] = mapped_column(Money)
    payment_instructions: Mapped[Optional[str]] = mapped_column(Text)
    bank_name: Mapped[Optional[str]] = mapped_column(Text)
    bank_account_no: Mapped[Optional[str]] = mapped_column(Text)
    bank_ifsc: Mapped[Optional[str]] = mapped_column(Text)
    bank_branch: Mapped[Optional[str]] = mapped_column(Text)
    supplier_gstin_snapshot: Mapped[Optional[str]] = mapped_column(Text)
    supplier_address_snapshot: Mapped[Optional[str]] = mapped_column(Text)
    document_id: Mapped[Optional[uuid.UUID]] = plain_fk("documents.id", ondelete="SET NULL")
    ai_extraction_result_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"), index=True)
    approved_by: Mapped[Optional[uuid.UUID]] = plain_fk("users.id", ondelete="SET NULL")
    approved_at: Mapped[Optional[datetime]] = mapped_column()
    query_raised_at: Mapped[Optional[datetime]] = mapped_column()
    query_note: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        uq_company_id("proforma_invoices"),
        tenant_fk("proforma_invoices", "supplier_id", "suppliers", ondelete="RESTRICT"),
        tenant_fk("proforma_invoices", "purchase_order_id", "purchase_orders", ondelete="RESTRICT"),
        tenant_fk("proforma_invoices", "ai_extraction_result_id", "ai_extraction_results", ondelete="SET NULL"),
        Index(
            "uq_proforma_number",
            "company_id",
            "supplier_id",
            func.upper(proforma_number),
            unique=True,
        ),
        enum_check(
            "status", ["pending", "under_review", "approved", "rejected", "paid", "completed", "cancelled"]
        ),
    )


class ProformaInvoiceItem(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "proforma_invoice_items"

    proforma_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    purchase_order_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    product_variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    hsn_code: Mapped[Optional[str]] = mapped_column(Text)
    quantity: Mapped[float] = mapped_column(Qty, nullable=False)
    uom_id: Mapped[uuid.UUID] = plain_fk("uoms.id", nullable=False)
    unit_price: Mapped[float] = mapped_column(Rate, nullable=False)
    gst_rate: Mapped[float] = mapped_column(Pct, nullable=False)
    cess_rate: Mapped[float] = mapped_column(Pct, nullable=False, server_default=text("0"))
    line_net: Mapped[float] = mapped_column(Money, nullable=False)
    line_tax: Mapped[float] = mapped_column(Money, nullable=False)
    line_total: Mapped[float] = mapped_column(Money, nullable=False)
    po_unit_price_snapshot: Mapped[Optional[float]] = mapped_column(Rate)
    price_variance_pct: Mapped[Optional[float]] = mapped_column(Pct)

    __table_args__ = (
        uq_company_id("proforma_invoice_items"),
        tenant_fk("proforma_invoice_items", "proforma_id", "proforma_invoices", ondelete="CASCADE"),
        tenant_fk("proforma_invoice_items", "purchase_order_item_id", "purchase_order_items", ondelete="SET NULL"),
        tenant_fk("proforma_invoice_items", "product_variant_id", "product_variants", ondelete="RESTRICT"),
        UniqueConstraint("proforma_id", "line_no", name="uq_proforma_item_line"),
    )


# ======================================================= 6.11-6.12 GRN


class GoodsReceipt(UUIDPkMixin, TenantMixin, RowVersionMixin, Base):
    __tablename__ = "goods_receipts"

    grn_number: Mapped[str] = mapped_column(Text, nullable=False)
    grn_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=text("CURRENT_DATE"))
    supplier_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    purchase_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    godown_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    received_by: Mapped[uuid.UUID] = plain_fk("users.id", nullable=False)
    vehicle_number: Mapped[Optional[str]] = mapped_column(Text)
    transporter_name: Mapped[Optional[str]] = mapped_column(Text)
    lr_number: Mapped[Optional[str]] = mapped_column(Text)
    eway_bill_number: Mapped[Optional[str]] = mapped_column(Text)
    gate_entry_number: Mapped[Optional[str]] = mapped_column(Text)
    gate_entry_at: Mapped[Optional[datetime]] = mapped_column()
    supplier_challan_number: Mapped[Optional[str]] = mapped_column(Text)
    supplier_challan_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"), index=True)
    confirmed_by: Mapped[Optional[uuid.UUID]] = plain_fk("users.id", ondelete="SET NULL")
    confirmed_at: Mapped[Optional[datetime]] = mapped_column()
    cancelled_at: Mapped[Optional[datetime]] = mapped_column()
    cancelled_by: Mapped[Optional[uuid.UUID]] = plain_fk("users.id", ondelete="SET NULL")
    cancellation_reason: Mapped[Optional[str]] = mapped_column(Text)
    has_discrepancy: Mapped[Optional[bool]] = mapped_column(server_default=text("false"))
    remarks: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        uq_company_id("goods_receipts"),
        tenant_fk("goods_receipts", "supplier_id", "suppliers", ondelete="RESTRICT"),
        tenant_fk("goods_receipts", "purchase_order_id", "purchase_orders", ondelete="RESTRICT"),
        tenant_fk("goods_receipts", "godown_id", "godowns", ondelete="RESTRICT"),
        UniqueConstraint("company_id", "grn_number", name="uq_grn_number"),
        Index("ix_goods_receipts_by_godown_date", "company_id", "godown_id", "grn_date"),
        enum_check(
            "status", ["draft", "confirmed", "partially_received", "received", "cancelled"]
        ),
    )


class GoodsReceiptItem(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "goods_receipt_items"

    goods_receipt_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    purchase_order_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    product_variant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    ordered_quantity: Mapped[Optional[float]] = mapped_column(Qty)
    previously_received_quantity: Mapped[Optional[float]] = mapped_column(Qty)
    received_quantity: Mapped[float] = mapped_column(Qty, nullable=False)
    accepted_quantity: Mapped[float] = mapped_column(Qty, nullable=False)
    rejected_quantity: Mapped[float] = mapped_column(
        Qty, Computed("received_quantity - accepted_quantity", persisted=True)
    )
    uom_id: Mapped[uuid.UUID] = plain_fk("uoms.id", nullable=False)
    conversion_factor: Mapped[float] = mapped_column(Factor, nullable=False, server_default=text("1"))
    unit_price: Mapped[Optional[float]] = mapped_column(Rate)
    issue_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'none'"))
    expected_variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)
    remarks: Mapped[Optional[str]] = mapped_column(Text)
    inventory_transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        uq_company_id("goods_receipt_items"),
        tenant_fk("goods_receipt_items", "goods_receipt_id", "goods_receipts", ondelete="CASCADE"),
        tenant_fk("goods_receipt_items", "purchase_order_item_id", "purchase_order_items", ondelete="RESTRICT"),
        tenant_fk("goods_receipt_items", "product_variant_id", "product_variants", ondelete="RESTRICT"),
        tenant_fk("goods_receipt_items", "batch_id", "batches", ondelete="RESTRICT"),
        tenant_fk("goods_receipt_items", "expected_variant_id", "product_variants", ondelete="RESTRICT"),
        tenant_fk("goods_receipt_items", "inventory_transaction_id", "inventory_transactions", ondelete="SET NULL"),
        UniqueConstraint("goods_receipt_id", "line_no", name="uq_grn_item_line"),
        CheckConstraint("received_quantity >= 0", name="received_quantity_nonneg"),
        CheckConstraint(
            "accepted_quantity >= 0 AND accepted_quantity <= received_quantity", name="accepted_within_received"
        ),
        enum_check(
            "issue_type",
            [
                "none",
                "short",
                "excess",
                "damaged",
                "expired",
                "wrong_product",
                "wrong_variant",
                "wrong_model",
                "wrong_brand",
            ],
        ),
    )


# ============================================================ 6.13 Invoice


class SupplierInvoice(UUIDPkMixin, TenantMixin, RowVersionMixin, Base):
    """No UI exists yet; the workflow requires it — §6.13."""

    __tablename__ = "supplier_invoices"

    invoice_number: Mapped[str] = mapped_column(Text, nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    purchase_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    goods_receipt_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    supplier_gstin: Mapped[Optional[str]] = mapped_column(Text)
    buyer_gstin: Mapped[Optional[str]] = mapped_column(Text)
    place_of_supply_state_code: Mapped[Optional[str]] = mapped_column(Text)
    is_inter_state: Mapped[Optional[bool]] = mapped_column()
    invoice_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'tax_invoice'"))
    subtotal: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    discount_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    taxable_value: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    freight_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    other_charges: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    round_off: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    total_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    cgst_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    sgst_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    igst_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    cess_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    tds_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    eway_bill_number: Mapped[Optional[str]] = mapped_column(Text)
    irn: Mapped[Optional[str]] = mapped_column(Text)
    ack_number: Mapped[Optional[str]] = mapped_column(Text)
    ack_date: Mapped[Optional[date]] = mapped_column(Date)
    due_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    amount_paid: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    payment_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'unpaid'"))
    match_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'unmatched'"))
    variance_amount: Mapped[Optional[float]] = mapped_column(Money)
    document_id: Mapped[Optional[uuid.UUID]] = plain_fk("documents.id", ondelete="SET NULL")
    ai_extraction_result_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"), index=True)
    approved_by: Mapped[Optional[uuid.UUID]] = plain_fk("users.id", ondelete="SET NULL")
    approved_at: Mapped[Optional[datetime]] = mapped_column()

    __table_args__ = (
        uq_company_id("supplier_invoices"),
        tenant_fk("supplier_invoices", "supplier_id", "suppliers", ondelete="RESTRICT"),
        tenant_fk("supplier_invoices", "purchase_order_id", "purchase_orders", ondelete="RESTRICT"),
        tenant_fk("supplier_invoices", "goods_receipt_id", "goods_receipts", ondelete="RESTRICT"),
        tenant_fk("supplier_invoices", "ai_extraction_result_id", "ai_extraction_results", ondelete="SET NULL"),
        Index(
            "uq_supplier_invoice",
            "company_id",
            "supplier_id",
            func.upper(invoice_number),
            "invoice_date",
            unique=True,
        ),
        enum_check("invoice_type", ["tax_invoice", "bill_of_supply", "debit_note", "credit_note"]),
        enum_check("status", ["draft", "under_review", "approved", "disputed", "cancelled"]),
        enum_check("match_status", ["unmatched", "matched", "variance"]),
        enum_check("payment_status", ["unpaid", "partially_paid", "paid"]),
    )


class SupplierInvoiceItem(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "supplier_invoice_items"

    invoice_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    purchase_order_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    goods_receipt_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    product_variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    hsn_code: Mapped[Optional[str]] = mapped_column(Text)
    quantity: Mapped[float] = mapped_column(Qty, nullable=False)
    uom_id: Mapped[uuid.UUID] = plain_fk("uoms.id", nullable=False)
    unit_price: Mapped[float] = mapped_column(Rate, nullable=False)
    discount_pct: Mapped[float] = mapped_column(Pct, nullable=False, server_default=text("0"))
    gst_rate: Mapped[float] = mapped_column(Pct, nullable=False)
    cess_rate: Mapped[float] = mapped_column(Pct, nullable=False, server_default=text("0"))
    line_net: Mapped[float] = mapped_column(Money, nullable=False)
    line_tax: Mapped[float] = mapped_column(Money, nullable=False)
    line_total: Mapped[float] = mapped_column(Money, nullable=False)
    po_unit_price_snapshot: Mapped[Optional[float]] = mapped_column(Rate)
    price_variance_pct: Mapped[Optional[float]] = mapped_column(Pct)
    qty_variance: Mapped[Optional[float]] = mapped_column(Qty)

    __table_args__ = (
        uq_company_id("supplier_invoice_items"),
        tenant_fk("supplier_invoice_items", "invoice_id", "supplier_invoices", ondelete="CASCADE"),
        tenant_fk("supplier_invoice_items", "purchase_order_item_id", "purchase_order_items", ondelete="RESTRICT"),
        tenant_fk("supplier_invoice_items", "goods_receipt_item_id", "goods_receipt_items", ondelete="RESTRICT"),
        tenant_fk("supplier_invoice_items", "product_variant_id", "product_variants", ondelete="RESTRICT"),
        UniqueConstraint("invoice_id", "line_no", name="uq_invoice_item_line"),
    )


# ==================================================== 6.14 Purchase returns


class PurchaseReturn(UUIDPkMixin, TenantMixin, Base):
    """(RECOMMENDED) Only goods that were accepted into stock and later
    returned post `PURCHASE_RETURN` transactions; goods rejected at the gate
    never entered stock and post nothing (§6.14)."""

    __tablename__ = "purchase_returns"

    return_number: Mapped[str] = mapped_column(Text, nullable=False)
    return_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=text("CURRENT_DATE"))
    supplier_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    goods_receipt_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    purchase_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    godown_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"), index=True)
    debit_note_number: Mapped[Optional[str]] = mapped_column(Text)
    total_amount: Mapped[float] = mapped_column(Money, nullable=False, server_default=text("0"))
    eway_bill_number: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        uq_company_id("purchase_returns"),
        tenant_fk("purchase_returns", "supplier_id", "suppliers", ondelete="RESTRICT"),
        tenant_fk("purchase_returns", "goods_receipt_id", "goods_receipts", ondelete="RESTRICT"),
        tenant_fk("purchase_returns", "purchase_order_id", "purchase_orders", ondelete="RESTRICT"),
        tenant_fk("purchase_returns", "godown_id", "godowns", ondelete="RESTRICT"),
        UniqueConstraint("company_id", "return_number", name="uq_return_number"),
        enum_check("status", ["draft", "sent", "accepted", "credited", "cancelled"]),
    )


class PurchaseReturnItem(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "purchase_return_items"

    return_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    goods_receipt_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    product_variant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    quantity: Mapped[float] = mapped_column(Qty, nullable=False)
    unit_price: Mapped[float] = mapped_column(Rate, nullable=False)
    gst_rate: Mapped[float] = mapped_column(Pct, nullable=False, server_default=text("0"))
    line_total: Mapped[float] = mapped_column(Money, nullable=False)
    inventory_transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        uq_company_id("purchase_return_items"),
        tenant_fk("purchase_return_items", "return_id", "purchase_returns", ondelete="CASCADE"),
        tenant_fk("purchase_return_items", "goods_receipt_item_id", "goods_receipt_items", ondelete="RESTRICT"),
        tenant_fk("purchase_return_items", "product_variant_id", "product_variants", ondelete="RESTRICT"),
        tenant_fk("purchase_return_items", "batch_id", "batches", ondelete="RESTRICT"),
        tenant_fk(
            "purchase_return_items", "inventory_transaction_id", "inventory_transactions", ondelete="SET NULL"
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )


# ==================================================== 6.15 Document variances


class DocumentVariance(UUIDPkMixin, TenantMixin, Base):
    """(RECOMMENDED) One table behind four mismatch screens and four alert
    types (§6.15). Detected server-side at confirm time, never by the
    browser."""

    __tablename__ = "document_variances"

    variance_type: Mapped[str] = mapped_column(Text, nullable=False)
    comparison_kind: Mapped[str] = mapped_column(Text, nullable=False)
    base_doc_type: Mapped[str] = mapped_column(Text, nullable=False)
    base_doc_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    base_line_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    compare_doc_type: Mapped[str] = mapped_column(Text, nullable=False)
    compare_doc_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    compare_line_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    product_variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    base_value: Mapped[Optional[float]] = mapped_column(Rate)
    compare_value: Mapped[Optional[float]] = mapped_column(Rate)
    difference: Mapped[Optional[float]] = mapped_column(Rate)
    difference_pct: Mapped[Optional[float]] = mapped_column(VariancePct)
    severity: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"), index=True)
    resolved_by: Mapped[Optional[uuid.UUID]] = plain_fk("users.id", ondelete="SET NULL")
    resolved_at: Mapped[Optional[datetime]] = mapped_column()
    resolution_note: Mapped[Optional[str]] = mapped_column(Text)
    alert_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        uq_company_id("document_variances"),
        tenant_fk("document_variances", "product_variant_id", "product_variants", ondelete="SET NULL"),
        tenant_fk("document_variances", "alert_id", "alerts", ondelete="SET NULL", use_alter=True),
        enum_check("variance_type", ["price", "quantity", "tax", "total", "product", "delivery_date"]),
        enum_check(
            "comparison_kind", ["proforma_vs_po", "grn_vs_po", "invoice_vs_po", "invoice_vs_grn"]
        ),
        enum_check("severity", ["info", "warning", "critical"]),
        enum_check("status", ["open", "accepted", "disputed", "resolved"]),
    )
