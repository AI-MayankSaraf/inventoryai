"""
The inventory ledger — 02_DATABASE_DESIGN.md §5, "the critical section",
and 06_BUSINESS_RULES.md §4.

    BR-INV-01: "Stock quantity can never be written directly... every
    change posts an inventory_transaction."

Every module that moves stock (GRN confirm today; transfers, sales issue,
adjustments and returns later) calls `post_transaction()` rather than
touching `stock_balances` itself. That single choke point is what makes
BR-INV-02 ("stock_balances.quantity must equal SUM(inventory_transactions)
for the same key") true by construction instead of by nightly repair job.

Design mirrors `core/numbering.py`: takes the caller's own session and
therefore runs inside the caller's transaction. A GRN confirmation posts one
row per accepted line and updates the GRN/PO status in the *same* commit —
BR-GRN-07's "postings, balance updates, PO line updates... all commit
together or not at all" — so this module never calls `session.commit()`
itself.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.errors import (
    CODE_BATCH_EXPIRED,
    CODE_BATCH_REQUIRED,
    CODE_INSUFFICIENT_STOCK,
    CODE_NO_UOM_CONVERSION,
    CODE_PERIOD_CLOSED,
    ApiError,
)
from fastapi import status

# BR-INV-04: sign is derived from txn_type by the server; a caller passing
# the wrong sign for a type is a bug, not a business decision, so this
# raises rather than silently flipping it.
_INWARD_TYPES = {"OPENING_STOCK", "GOODS_RECEIPT", "TRANSFER_IN", "SALES_RETURN"}
_OUTWARD_TYPES = {"TRANSFER_OUT", "SALES_ISSUE", "DAMAGE", "PURCHASE_RETURN", "EXPIRY_WRITE_OFF"}
# STOCK_CORRECTION may carry either sign (schema's own CHECK allows it).


class LedgerError(RuntimeError):
    pass


async def resolve_conversion_factor(
    session: AsyncSession,
    *,
    company_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    base_uom_id: uuid.UUID,
    line_uom_id: uuid.UUID,
) -> Decimal:
    """BR-INV-08: "quantities are stored in the variant's base UoM. Any
    other UoM requires an active conversion for that variant; the factor
    used is frozen on the transaction." Frozen means resolved once, at the
    point a line is created — callers store the returned factor on the line
    row rather than re-resolving it at confirm time, so a conversion edited
    later never rewrites history.
    """
    if line_uom_id == base_uom_id:
        return Decimal("1")

    factor = (
        await session.execute(
            text(
                "SELECT factor FROM product_uom_conversions "
                "WHERE company_id = :c AND product_variant_id = :v "
                "AND from_uom_id = :from_uom AND to_uom_id = :to_uom"
            ),
            {"c": company_id, "v": product_variant_id, "from_uom": line_uom_id, "to_uom": base_uom_id},
        )
    ).scalar_one_or_none()
    if factor is None:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_NO_UOM_CONVERSION,
            "This unit has no active conversion to the item's base unit for this variant",
        )
    return Decimal(str(factor))


async def assert_period_open(session: AsyncSession, *, company_id: uuid.UUID, on: date) -> None:
    """BR-INV-10: a movement dated on or before the period-close marker is
    refused. `on` may be in the future check separately (callers reject a
    future date themselves — that half of the rule is a plain field
    validation, this half needs the tenant's settings row)."""
    locked_through = (
        await session.execute(
            text("SELECT inventory_locked_through FROM company_settings WHERE company_id = :c"),
            {"c": company_id},
        )
    ).scalar_one_or_none()
    if locked_through is not None and on <= locked_through:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_PERIOD_CLOSED,
            f"This period is closed through {locked_through.isoformat()}; postings on or before that date are refused",
        )


async def assert_batch_ok(
    session: AsyncSession,
    *,
    company_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    tracking_type: str,
    batch_id: Optional[uuid.UUID],
    outward: bool,
    override_expiry: bool = False,
) -> None:
    """BR-INV-09 / BR-GRN-11: batch-tracked variants require a batch on
    every movement; an outward movement additionally refuses an expired
    batch unless the caller holds `inventory.override_expiry`."""
    if tracking_type != "batch":
        return
    if batch_id is None:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_BATCH_REQUIRED, "This item is batch-tracked; a batch is required"
        )
    if not outward:
        return
    expires_on = (
        await session.execute(
            text("SELECT expires_on FROM batches WHERE company_id = :c AND id = :b"),
            {"c": company_id, "b": batch_id},
        )
    ).scalar_one_or_none()
    if expires_on is not None and expires_on < clock.today() and not override_expiry:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_BATCH_EXPIRED,
            f"Batch expired on {expires_on.isoformat()}",
        )


async def post_transaction(
    session: AsyncSession,
    *,
    company_id: uuid.UUID,
    txn_type: str,
    txn_number: str,
    txn_date: datetime,
    product_variant_id: uuid.UUID,
    godown_id: uuid.UUID,
    quantity: Decimal,
    uom_id: uuid.UUID,
    performed_by: uuid.UUID,
    allow_negative_stock: bool = False,
    batch_id: Optional[uuid.UUID] = None,
    unit_cost: Optional[Decimal] = None,
    source_type: Optional[str] = None,
    source_id: Optional[uuid.UUID] = None,
    source_line_id: Optional[uuid.UUID] = None,
    reason_code: Optional[str] = None,
    remarks: Optional[str] = None,
    counterpart_txn_id: Optional[uuid.UUID] = None,
    reverses_txn_id: Optional[uuid.UUID] = None,
    entered_quantity: Optional[Decimal] = None,
    entered_uom_id: Optional[uuid.UUID] = None,
    conversion_factor: Optional[Decimal] = None,
    txn_id: Optional[uuid.UUID] = None,
) -> dict:
    """Post one signed movement: an immutable `inventory_transactions` row
    plus the matching `stock_balances` upsert, both inside the caller's
    transaction (BR-GRN-07).

    Does not commit. Does not allocate `txn_number` — callers pass the
    owning document's own number (a GRN posts many lines under one
    `grn_number`; §5.2's own footnote is why `txn_number` alone isn't
    unique on this table).

    `txn_id` lets a caller decide the row's id before inserting it. Only
    transfers need this, and they genuinely need it: BR-INV-06 requires the
    OUT and IN rows to point at each other through `counterpart_txn_id`,
    the table is append-only (the `trg_inventory_transactions_immutable`
    trigger refuses *every* UPDATE, not just one to a quantity), so neither
    pointer can be back-filled after the fact. Knowing both ids up front is
    the only way to write that pair. Everyone else omits it and lets the
    column default generate one.
    """
    if quantity == 0:
        raise LedgerError("quantity must be non-zero")
    if txn_type in _INWARD_TYPES and quantity <= 0:
        raise LedgerError(f"{txn_type} requires a positive quantity")
    if txn_type in _OUTWARD_TYPES and quantity >= 0:
        raise LedgerError(f"{txn_type} requires a negative quantity")

    if txn_type in ("DAMAGE", "STOCK_CORRECTION"):
        # BR-INV-07: both require a real reason, not a UI-only field the
        # prototype "collects and discards".
        if not remarks or not reason_code:
            raise LedgerError(f"{txn_type} requires both remarks and a reason_code")

    # BR-INV-05: lock the balance row first so two concurrent postings
    # against the same (variant, godown, batch) serialise instead of both
    # reading a stale "there's enough" answer.
    balance_key = {
        "c": company_id,
        "v": product_variant_id,
        "g": godown_id,
        "b": batch_id,
    }
    current = (
        await session.execute(
            text(
                "SELECT quantity FROM stock_balances "
                "WHERE company_id = :c AND product_variant_id = :v AND godown_id = :g "
                "AND COALESCE(batch_id, '00000000-0000-0000-0000-000000000000'::uuid) "
                "= COALESCE(CAST(:b AS uuid), '00000000-0000-0000-0000-000000000000'::uuid) "
                "FOR UPDATE"
            ),
            balance_key,
        )
    ).scalar_one_or_none()
    current = Decimal(str(current)) if current is not None else Decimal("0")
    new_balance = current + quantity

    if new_balance < 0 and not allow_negative_stock:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_INSUFFICIENT_STOCK,
            f"Only {current} available; this movement would take it to {new_balance}",
        )

    row = (
        await session.execute(
            text(
                "INSERT INTO inventory_transactions "
                "(id, company_id, txn_number, txn_type, txn_date, product_variant_id, godown_id, batch_id, "
                " quantity, uom_id, entered_quantity, entered_uom_id, conversion_factor, unit_cost, "
                " source_type, source_id, source_line_id, counterpart_txn_id, reverses_txn_id, "
                " reason_code, remarks, performed_by) "
                "VALUES (:id, :company_id, :txn_number, :txn_type, :txn_date, :product_variant_id, :godown_id, :batch_id, "
                " :quantity, :uom_id, :entered_quantity, :entered_uom_id, :conversion_factor, :unit_cost, "
                " :source_type, :source_id, :source_line_id, :counterpart_txn_id, :reverses_txn_id, "
                " :reason_code, :remarks, :performed_by) "
                "RETURNING *"
            ),
            {
                "id": txn_id or uuid.uuid4(),
                "company_id": company_id,
                "txn_number": txn_number,
                "txn_type": txn_type,
                "txn_date": txn_date,
                "product_variant_id": product_variant_id,
                "godown_id": godown_id,
                "batch_id": batch_id,
                "quantity": quantity,
                "uom_id": uom_id,
                "entered_quantity": entered_quantity,
                "entered_uom_id": entered_uom_id,
                "conversion_factor": conversion_factor,
                "unit_cost": unit_cost,
                "source_type": source_type,
                "source_id": source_id,
                "source_line_id": source_line_id,
                "counterpart_txn_id": counterpart_txn_id,
                "reverses_txn_id": reverses_txn_id,
                "reason_code": reason_code,
                "remarks": remarks,
                "performed_by": performed_by,
            },
        )
    ).mappings().first()

    # avg_cost: a simple weighted average on inward movements only: outward
    # movements and corrections do not change the tenant's cost basis.
    # BR-INV-12 keeps valuation on `purchase_price` for Phase 1 and only
    # asks that `unit_cost` be captured on every inward transaction "so
    # weighted-average costing can be enabled later without backfilling" —
    # maintaining `avg_cost` here is exactly that forward-compatibility
    # step, not a switch to WAC-based valuation.
    if txn_type in _INWARD_TYPES and unit_cost is not None:
        await session.execute(
            text(
                "INSERT INTO stock_balances (company_id, product_variant_id, godown_id, batch_id, quantity, avg_cost, last_txn_at) "
                "VALUES (:c, :v, :g, :b, :qty, :cost, now()) "
                "ON CONFLICT (company_id, product_variant_id, godown_id, "
                "COALESCE(batch_id, '00000000-0000-0000-0000-000000000000'::uuid)) "
                "DO UPDATE SET "
                " avg_cost = CASE WHEN stock_balances.quantity + EXCLUDED.quantity > 0 "
                "   THEN ((stock_balances.quantity * COALESCE(stock_balances.avg_cost, 0)) + (EXCLUDED.quantity * EXCLUDED.avg_cost)) "
                "        / (stock_balances.quantity + EXCLUDED.quantity) "
                "   ELSE stock_balances.avg_cost END, "
                " quantity = stock_balances.quantity + EXCLUDED.quantity, "
                " last_txn_at = now()"
            ),
            {**balance_key, "qty": quantity, "cost": unit_cost},
        )
    else:
        await session.execute(
            text(
                "INSERT INTO stock_balances (company_id, product_variant_id, godown_id, batch_id, quantity, last_txn_at) "
                "VALUES (:c, :v, :g, :b, :qty, now()) "
                "ON CONFLICT (company_id, product_variant_id, godown_id, "
                "COALESCE(batch_id, '00000000-0000-0000-0000-000000000000'::uuid)) "
                "DO UPDATE SET quantity = stock_balances.quantity + EXCLUDED.quantity, last_txn_at = now()"
            ),
            {**balance_key, "qty": quantity},
        )

    return dict(row)
