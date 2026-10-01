"""
Inventory — `02_DATABASE_DESIGN.md` §5, "the critical section".

`inventory_transactions` is the only source of truth for stock (§5.1).
`stock_balances` is a materialised, transactionally-maintained cache of it
(§5.4) — never the other way around. Nothing else may hold a quantity.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DDL,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    Factor,
    Qty,
    Rate,
    TenantMixin,
    UUIDPkMixin,
    enum_check,
    plain_fk,
    self_tenant_fk,
    tenant_fk,
    uq_company_id,
)

TXN_TYPES = [
    "OPENING_STOCK",
    "GOODS_RECEIPT",
    "PURCHASE_RETURN",
    "TRANSFER_IN",
    "TRANSFER_OUT",
    "SALES_ISSUE",
    "SALES_RETURN",
    "DAMAGE",
    "EXPIRY_WRITE_OFF",
    "STOCK_CORRECTION",
]


class InventoryTransaction(UUIDPkMixin, TenantMixin, Base):
    """Append-only, signed-quantity stock ledger (§5.2). Immutability is
    enforced by a `BEFORE UPDATE OR DELETE` trigger (added below via a raw
    `event.listen` DDL hook, since the ORM itself cannot stop a raw SQL
    statement) — corrections are new rows with `reverses_txn_id` set."""

    __tablename__ = "inventory_transactions"

    txn_number: Mapped[str] = mapped_column(Text, nullable=False)
    txn_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    txn_date: Mapped[datetime] = mapped_column(nullable=False, index=True)
    product_variant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    godown_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    quantity: Mapped[float] = mapped_column(Qty, nullable=False)
    uom_id: Mapped[uuid.UUID] = plain_fk("uoms.id", nullable=False)
    entered_quantity: Mapped[Optional[float]] = mapped_column(Qty)
    entered_uom_id: Mapped[Optional[uuid.UUID]] = plain_fk("uoms.id")
    conversion_factor: Mapped[Optional[float]] = mapped_column(Factor)
    unit_cost: Mapped[Optional[float]] = mapped_column(Rate)
    source_type: Mapped[Optional[str]] = mapped_column(Text, index=True)
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    source_line_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True))
    counterpart_txn_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    reverses_txn_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    reason_code: Mapped[Optional[str]] = mapped_column(Text)
    remarks: Mapped[Optional[str]] = mapped_column(Text)
    performed_by: Mapped[uuid.UUID] = plain_fk("users.id", nullable=False)
    posted_at: Mapped[datetime] = mapped_column(nullable=False, index=True, server_default=text("now()"))

    __table_args__ = (
        uq_company_id("inventory_transactions"),
        tenant_fk("inventory_transactions", "product_variant_id", "product_variants", ondelete="RESTRICT"),
        tenant_fk("inventory_transactions", "godown_id", "godowns", ondelete="RESTRICT"),
        tenant_fk("inventory_transactions", "batch_id", "batches", ondelete="RESTRICT"),
        # Deferrable: a transfer inserts its OUT and IN rows, each pointing at
        # the other, in one transaction (migration a71c4e0d95b2).
        self_tenant_fk("inventory_transactions", "counterpart_txn_id", ondelete="RESTRICT", deferrable=True),
        self_tenant_fk("inventory_transactions", "reverses_txn_id", ondelete="RESTRICT"),
        # One reference legitimately covers many lines (a GRN posts one row
        # per accepted line), so the number alone is not unique (§5.2 fn 1).
        # Batch and source line are part of the key so two batches of one
        # product on one GRN or transfer can both post (f3c8a1d6b902).
        UniqueConstraint(
            "company_id", "txn_number", "product_variant_id", "godown_id", "txn_type", "batch_id", "source_line_id",
            name="uq_txn_number", postgresql_nulls_not_distinct=True,
        ),
        Index("ix_inventory_transactions_ledger", "company_id", "product_variant_id", "godown_id", "txn_date"),
        Index("ix_inventory_transactions_by_source", "company_id", "source_type", "source_id"),
        CheckConstraint("quantity <> 0", name="quantity_nonzero"),
        enum_check("txn_type", TXN_TYPES),
        enum_check(
            "source_type",
            ["goods_receipt", "purchase_return", "stock_transfer", "adjustment", "sales_issue", "opening"],
        ),
        CheckConstraint(
            "(txn_type IN ('OPENING_STOCK','GOODS_RECEIPT','TRANSFER_IN','SALES_RETURN') AND quantity > 0)"
            " OR (txn_type IN ('TRANSFER_OUT','SALES_ISSUE','DAMAGE','PURCHASE_RETURN','EXPIRY_WRITE_OFF') AND quantity < 0)"
            " OR (txn_type = 'STOCK_CORRECTION')",
            name="sign_matches_txn_type",
        ),
    )


# The ledger's immutability trigger — §5.2: "a BEFORE UPDATE OR DELETE
# trigger raises an exception. Corrections are new rows... This is what
# makes the ledger auditable." Declared as DDL attached to metadata so it is
# created by the same Alembic migration that creates the table, instead of
# being a business-logic concern living in application code.
_LEDGER_IMMUTABLE_FN = DDL(
    """
    CREATE OR REPLACE FUNCTION inventory_transactions_immutable() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'inventory_transactions is append-only: %% is not permitted (id=%%)', TG_OP, OLD.id;
    END;
    $$ LANGUAGE plpgsql;
    """
)
_LEDGER_IMMUTABLE_TRIGGER = DDL(
    """
    CREATE TRIGGER trg_inventory_transactions_immutable
    BEFORE UPDATE OR DELETE ON inventory_transactions
    FOR EACH ROW EXECUTE FUNCTION inventory_transactions_immutable();
    """
)
event.listen(InventoryTransaction.__table__, "after_create", _LEDGER_IMMUTABLE_FN)
event.listen(InventoryTransaction.__table__, "after_create", _LEDGER_IMMUTABLE_TRIGGER)


class StockBalance(UUIDPkMixin, TenantMixin, Base):
    """Materialised cache of the ledger (§5.4). `available_quantity` is a
    generated column; `quantity` is updated in the *same transaction* as the
    ledger insert via the `INSERT ... ON CONFLICT DO UPDATE` shown in §5.4 —
    that upsert lives in the inventory service layer (a later phase), not
    here."""

    __tablename__ = "stock_balances"

    product_variant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    godown_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    quantity: Mapped[float] = mapped_column(Qty, nullable=False, server_default=text("0"), index=True)
    reserved_quantity: Mapped[float] = mapped_column(Qty, nullable=False, server_default=text("0"))
    available_quantity: Mapped[float] = mapped_column(
        Qty, Computed("quantity - reserved_quantity", persisted=True)
    )
    avg_cost: Mapped[Optional[float]] = mapped_column(Rate)
    last_txn_at: Mapped[Optional[datetime]] = mapped_column()
    last_recalculated_at: Mapped[Optional[datetime]] = mapped_column()

    __table_args__ = (
        uq_company_id("stock_balances"),
        tenant_fk("stock_balances", "product_variant_id", "product_variants", ondelete="RESTRICT"),
        tenant_fk("stock_balances", "godown_id", "godowns", ondelete="RESTRICT"),
        tenant_fk("stock_balances", "batch_id", "batches", ondelete="RESTRICT"),
        Index(
            "uq_stock_balance",
            "company_id",
            "product_variant_id",
            "godown_id",
            text("COALESCE(batch_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            unique=True,
        ),
        Index("ix_stock_balances_by_godown", "company_id", "godown_id"),
    )


class Batch(UUIDPkMixin, TenantMixin, Base):
    """(RECOMMENDED) Included in the first migration even though no UI
    exists yet — retrofitting `batch_id` into a populated ledger later means
    rewriting history (§5.5)."""

    __tablename__ = "batches"

    product_variant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    batch_number: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_batch_number: Mapped[Optional[str]] = mapped_column(Text)
    manufactured_on: Mapped[Optional[date]] = mapped_column(Date)
    expires_on: Mapped[Optional[date]] = mapped_column(Date, index=True)
    mrp: Mapped[Optional[float]] = mapped_column(Rate)
    received_on: Mapped[Optional[date]] = mapped_column(Date)
    goods_receipt_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True))
    is_quarantined: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))

    __table_args__ = (
        uq_company_id("batches"),
        tenant_fk("batches", "product_variant_id", "product_variants", ondelete="RESTRICT"),
        UniqueConstraint("company_id", "product_variant_id", "batch_number", name="uq_batch_number"),
        Index(
            "ix_batches_expiry",
            "company_id",
            "expires_on",
            postgresql_where=text("expires_on IS NOT NULL"),
        ),
    )


class StockTransfer(UUIDPkMixin, TenantMixin, Base):
    """(RECOMMENDED) A header record makes the movement a first-class
    document that can be approved, printed as a delivery challan (a legal
    requirement for inter-state stock movement in India) and tracked in
    transit (§5.6)."""

    __tablename__ = "stock_transfers"

    transfer_number: Mapped[str] = mapped_column(Text, nullable=False)
    transfer_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=text("CURRENT_DATE"))
    from_godown_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    to_godown_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"), index=True)
    dispatched_by: Mapped[Optional[uuid.UUID]] = plain_fk("users.id")
    received_by: Mapped[Optional[uuid.UUID]] = plain_fk("users.id")
    vehicle_number: Mapped[Optional[str]] = mapped_column(Text)
    lr_number: Mapped[Optional[str]] = mapped_column(Text)
    eway_bill_number: Mapped[Optional[str]] = mapped_column(Text)
    remarks: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        uq_company_id("stock_transfers"),
        tenant_fk("stock_transfers", "from_godown_id", "godowns", ondelete="RESTRICT"),
        tenant_fk("stock_transfers", "to_godown_id", "godowns", ondelete="RESTRICT"),
        UniqueConstraint("company_id", "transfer_number", name="uq_transfer_number"),
        CheckConstraint("from_godown_id <> to_godown_id", name="from_ne_to_godown"),
        enum_check("status", ["draft", "in_transit", "received", "cancelled"]),
    )


class StockTransferItem(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "stock_transfer_items"

    transfer_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    product_variant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    quantity: Mapped[float] = mapped_column(Qty, nullable=False)
    uom_id: Mapped[uuid.UUID] = plain_fk("uoms.id", nullable=False)
    dispatched_qty: Mapped[Optional[float]] = mapped_column(Qty)
    received_qty: Mapped[Optional[float]] = mapped_column(Qty)

    __table_args__ = (
        uq_company_id("stock_transfer_items"),
        tenant_fk("stock_transfer_items", "transfer_id", "stock_transfers", ondelete="CASCADE"),
        tenant_fk("stock_transfer_items", "product_variant_id", "product_variants", ondelete="RESTRICT"),
        tenant_fk("stock_transfer_items", "batch_id", "batches", ondelete="RESTRICT"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )


class InventoryReservation(UUIDPkMixin, TenantMixin, Base):
    """(FUTURE) `reserved` is displayed everywhere but nothing in Phase 1
    can create it — ship with `reserved_quantity` permanently 0 (§5.7).
    Table declared for completeness of the schema inventory; not populated
    or read by anything in this phase."""

    __tablename__ = "inventory_reservations"

    product_variant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    godown_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    quantity: Mapped[float] = mapped_column(Qty, nullable=False)
    reserved_for_type: Mapped[str] = mapped_column(Text, nullable=False)
    reserved_for_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column()
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))

    __table_args__ = (
        uq_company_id("inventory_reservations"),
        tenant_fk("inventory_reservations", "product_variant_id", "product_variants", ondelete="RESTRICT"),
        tenant_fk("inventory_reservations", "godown_id", "godowns", ondelete="RESTRICT"),
        tenant_fk("inventory_reservations", "batch_id", "batches", ondelete="RESTRICT"),
    )


class VariantGodownPolicy(UUIDPkMixin, TenantMixin, Base):
    """(OPTIONAL) Per-godown reorder points — §5.8. Until adopted, low-stock
    is evaluated per godown against the SKU's single global reorder point,
    which is what the mock data does."""

    __tablename__ = "variant_godown_policies"

    product_variant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    godown_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    reorder_point: Mapped[float] = mapped_column(Qty, nullable=False, server_default=text("0"))
    reorder_qty: Mapped[float] = mapped_column(Qty, nullable=False, server_default=text("0"))
    max_stock: Mapped[Optional[float]] = mapped_column(Qty)
    is_stocked: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))

    __table_args__ = (
        uq_company_id("variant_godown_policies"),
        tenant_fk("variant_godown_policies", "product_variant_id", "product_variants", ondelete="CASCADE"),
        tenant_fk("variant_godown_policies", "godown_id", "godowns", ondelete="CASCADE"),
        UniqueConstraint("product_variant_id", "godown_id", name="uq_variant_godown_policy"),
    )
