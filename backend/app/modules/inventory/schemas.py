"""
Inventory request/response shapes.

Field names mirror `04_API_SPECIFICATION.md` §2.7 and §3.7-3.9.

Quantities and money are `float` **in these wire shapes only**, matching the
convention every other module's `*Out` schema already follows. All actual
arithmetic -- balances, signs, tax, the BR-INV-02 reconciliation -- happens
in `Decimal` inside the services and the database, which is what keeps a
balance from drifting by a rounding error.

This is not cosmetic. Pydantic serialises a `Decimal` field as a JSON
*string*, so a schema declaring `quantity: Decimal` sends `"-75.000"` to the
browser; the frontend then does `0 + "-75.000"` and gets string
concatenation instead of a sum. That is exactly how the first cut of this
module shipped a ledger whose "Balance After" column read 0 on every row.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

# BR-INV-11: stock status is derived on read, never stored.
StockState = Literal["in_stock", "low_stock", "out_of_stock"]

# The subset of ledger types a human may post by hand. Every other type
# (GOODS_RECEIPT, TRANSFER_IN/OUT...) is written by the document that causes
# it, never through this endpoint.
#
# `OPENING_STOCK` belongs here despite being inward: BR-INV-01 says opening
# stock "posts an inventory_transaction" like everything else, and names the
# prototype's editable `currentStock` field as the thing that must be
# replaced by exactly this posting. Without it, creating a product with an
# opening quantity has nowhere real to write.
ManualTxnType = Literal[
    "OPENING_STOCK", "DAMAGE", "SALES_ISSUE", "STOCK_CORRECTION", "EXPIRY_WRITE_OFF"
]


# ------------------------------------------------------------------ stock

class StockRowOut(BaseModel):
    id: str
    product_id: UUID
    product_variant_id: UUID
    sku: str
    product_name: str
    brand_name: str
    category_name: str
    godown_id: UUID
    godown_name: str
    quantity: float
    reserved_quantity: float
    available_quantity: float
    uom_code: str
    status: StockState
    # BR-INV-12: Phase 1 values stock at standard cost (`purchase_price`),
    # not at the weighted average the ledger already tracks in `avg_cost`.
    value: float


class InventoryKpisOut(BaseModel):
    total_skus: int
    inventory_value: float
    low_stock: int
    out_of_stock: int


class StockListOut(BaseModel):
    """§3.7 returns rows *and* the KPIs for the same filtered set, so a tile
    can never contradict the list under it."""

    items: list[StockRowOut]
    kpis: InventoryKpisOut
    total: int


class LowStockRowOut(BaseModel):
    id: str
    product_variant_id: UUID
    sku: str
    product_name: str
    brand_name: str
    godown_id: UUID
    godown_name: str
    current_stock: float
    reorder_point: float
    suggested_qty: float
    uom_code: str
    preferred_supplier_id: Optional[UUID] = None
    preferred_supplier_name: str = ""
    last_purchase_price: float = 0
    status: Literal["low_stock", "out_of_stock"]


class BatchOut(BaseModel):
    id: UUID
    product_variant_id: UUID
    batch_number: str
    supplier_batch_number: Optional[str] = None
    manufactured_on: Optional[date] = None
    expires_on: Optional[date] = None
    mrp: Optional[float] = None
    received_on: Optional[date] = None
    is_quarantined: bool = False
    quantity_on_hand: float = 0


class BalanceDriftOut(BaseModel):
    product_variant_id: UUID
    godown_id: UUID
    batch_id: Optional[UUID] = None
    balance_quantity: float
    ledger_quantity: float
    drift: float


class VerifyBalancesOut(BaseModel):
    """BR-INV-02 made checkable on demand rather than only by the nightly
    job: does every `stock_balances` row still equal the sum of its ledger?"""

    checked: int
    ok: bool
    drifts: list[BalanceDriftOut]


# ----------------------------------------------------------- transactions

class TransactionOut(BaseModel):
    id: UUID
    txn_number: str
    txn_type: str
    txn_date: datetime
    product_variant_id: UUID
    sku: str = ""
    product_name: str = ""
    godown_id: UUID
    godown_name: str = ""
    batch_id: Optional[UUID] = None
    batch_number: Optional[str] = None
    quantity: float
    uom_id: UUID
    uom_code: str = ""
    entered_quantity: Optional[float] = None
    entered_uom_id: Optional[UUID] = None
    conversion_factor: Optional[float] = None
    unit_cost: Optional[float] = None
    source_type: Optional[str] = None
    source_id: Optional[UUID] = None
    source_line_id: Optional[UUID] = None
    counterpart_txn_id: Optional[UUID] = None
    reverses_txn_id: Optional[UUID] = None
    reason_code: Optional[str] = None
    remarks: Optional[str] = None
    performed_by: UUID
    performed_by_name: str = ""
    posted_at: datetime
    # Running balance after this row, for the per-variant ledger view. Only
    # populated by the ledger endpoint, where the ordering makes it mean
    # something; a filtered list can't compute it honestly.
    balance_after: Optional[float] = None


class TransactionCreate(BaseModel):
    txn_type: ManualTxnType
    product_variant_id: UUID
    godown_id: UUID
    batch_id: Optional[UUID] = None
    # §3.8: "the client sends an unsigned magnitude; the server applies the
    # sign from txn_type". Enforced here rather than trusted.
    quantity: float = Field(gt=0)
    uom_id: UUID
    direction: Optional[Literal["increase", "decrease"]] = None
    txn_date: Optional[datetime] = None
    reason_code: Optional[str] = None
    remarks: Optional[str] = None
    reference: Optional[str] = None


class TransactionReverseRequest(BaseModel):
    reason: str = Field(min_length=1)


# -------------------------------------------------------------- transfers

class TransferItemIn(BaseModel):
    product_variant_id: UUID
    batch_id: Optional[UUID] = None
    quantity: float = Field(gt=0)
    uom_id: UUID


class TransferCreate(BaseModel):
    from_godown_id: UUID
    to_godown_id: UUID
    transfer_date: Optional[date] = None
    vehicle_number: Optional[str] = None
    lr_number: Optional[str] = None
    eway_bill_number: Optional[str] = None
    remarks: Optional[str] = None
    items: list[TransferItemIn] = Field(min_length=1)


class TransferItemOut(BaseModel):
    id: UUID
    product_variant_id: UUID
    sku: str = ""
    product_name: str = ""
    batch_id: Optional[UUID] = None
    quantity: float
    uom_id: UUID
    dispatched_qty: Optional[float] = None
    received_qty: Optional[float] = None


class TransferOut(BaseModel):
    id: UUID
    transfer_number: str
    transfer_date: date
    from_godown_id: UUID
    from_godown_name: str = ""
    to_godown_id: UUID
    to_godown_name: str = ""
    status: str
    dispatched_by: Optional[UUID] = None
    received_by: Optional[UUID] = None
    vehicle_number: Optional[str] = None
    lr_number: Optional[str] = None
    eway_bill_number: Optional[str] = None
    remarks: Optional[str] = None
    items: list[TransferItemOut] = Field(default_factory=list)
    transactions: list[TransactionOut] = Field(default_factory=list)
