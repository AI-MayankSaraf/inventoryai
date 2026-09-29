"""
The ledger's read and manual-write paths.

Every posting goes through `core.inventory.post_transaction`, which is the
one place that writes `inventory_transactions` and the matching
`stock_balances` row in a single statement pair. This module's job is the
part that engine deliberately does not do: decide the sign, allocate a
document number, validate the tenant's own rules, and record the audit row.

The ledger is append-only (BR-INV-03, enforced by a database trigger). A
mistake is corrected by posting an offsetting row that points back at what
it reverses -- never by editing or deleting the original.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core import audit, inventory as ledger, numbering
from app.core.db import set_tenant
from app.core.deps import assert_godown_in_scope
from app.core.errors import (
    ApiError,
    CODE_BUSINESS_RULE_VIOLATION,
    CODE_IMMUTABLE_LEDGER,
    CODE_NOT_FOUND,
    CODE_REMARKS_REQUIRED,
)
from app.core.security import AccessTokenClaims
from app.modules.inventory.schemas import TransactionCreate

# BR-INV-04: the sign belongs to the type, not to the caller. A client that
# could choose it could post a DAMAGE that *increases* stock.
_OUTWARD = {"DAMAGE", "SALES_ISSUE", "EXPIRY_WRITE_OFF"}

# Which business document a manual posting is attributed to. Everything
# posted through this endpoint is an adjustment by definition -- a GRN or a
# transfer writes its own rows with its own source_type -- except opening
# stock, which the schema gives its own `opening` source so a tenant's
# starting balances stay distinguishable from corrections made later.
_SOURCE_TYPE = "adjustment"
_SOURCE_BY_TYPE = {"OPENING_STOCK": "opening"}

_ROW_SELECT = """
    SELECT it.id, it.txn_number, it.txn_type, it.txn_date, it.product_variant_id,
           COALESCE(pv.sku, '') AS sku,
           TRIM(COALESCE(p.name, '') || ' ' || COALESCE(pv.variant_name, '')) AS product_name,
           it.godown_id, COALESCE(g.name, '') AS godown_name,
           it.batch_id, bt.batch_number,
           it.quantity, it.uom_id, COALESCE(u.code, '') AS uom_code,
           it.entered_quantity, it.entered_uom_id, it.conversion_factor, it.unit_cost,
           it.source_type, it.source_id, it.source_line_id,
           it.counterpart_txn_id, it.reverses_txn_id, it.reason_code, it.remarks,
           it.performed_by, COALESCE(usr.full_name, '') AS performed_by_name,
           it.posted_at
    FROM inventory_transactions it
    LEFT JOIN product_variants pv ON pv.id = it.product_variant_id AND pv.company_id = it.company_id
    LEFT JOIN products p ON p.id = pv.product_id AND p.company_id = pv.company_id
    LEFT JOIN godowns g ON g.id = it.godown_id AND g.company_id = it.company_id
    LEFT JOIN batches bt ON bt.id = it.batch_id AND bt.company_id = it.company_id
    LEFT JOIN uoms u ON u.id = it.uom_id
    LEFT JOIN users usr ON usr.id = it.performed_by
"""


async def _load(session: AsyncSession, *, company_id: UUID, txn_id: UUID) -> dict:
    row = (
        await session.execute(
            text(f"{_ROW_SELECT} WHERE it.id = :id AND it.company_id = :c"),
            {"id": txn_id, "c": company_id},
        )
    ).mappings().first()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Transaction not found")
    return dict(row)


async def list_transactions(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    txn_type: Optional[str] = None,
    godown_id: Optional[UUID] = None,
    product_variant_id: Optional[UUID] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    q: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    from app.core.deps import scoped_godown_filter

    where = ["it.company_id = :c"]
    params: dict = {"c": claims.company_id}

    scope_sql, scope_params = scoped_godown_filter(claims, "it.godown_id")
    if scope_sql:
        where.append(scope_sql)
        params.update(scope_params)

    if txn_type:
        where.append("it.txn_type = :txn_type")
        params["txn_type"] = txn_type
    if godown_id:
        where.append("it.godown_id = :godown_id")
        params["godown_id"] = godown_id
    if product_variant_id:
        where.append("it.product_variant_id = :variant_id")
        params["variant_id"] = product_variant_id
    if date_from:
        where.append("it.txn_date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        # Inclusive of the whole end day, not up to its midnight.
        where.append("it.txn_date < (CAST(:date_to AS date) + 1)")
        params["date_to"] = date_to
    if q:
        where.append("(it.txn_number ILIKE :q OR pv.sku ILIKE :q OR p.name ILIKE :q)")
        params["q"] = f"%{q}%"

    rows = (
        await session.execute(
            text(
                f"{_ROW_SELECT} WHERE {' AND '.join(where)} "
                "ORDER BY it.txn_date DESC, it.posted_at DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": limit, "offset": offset},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def variant_ledger(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    product_variant_id: UUID,
    godown_id: Optional[UUID] = None,
    limit: int = 200,
) -> list[dict]:
    """One variant's movements, oldest first, each carrying the running
    balance after it.

    The running balance is computed here rather than read from anywhere: no
    such column exists, and inventing one would be a second thing that can
    disagree with the ledger. Ordering is the whole meaning of the number,
    which is why only this endpoint returns it -- a filtered list would be
    showing a running total over an arbitrary subset.
    """
    rows = await list_transactions(
        session,
        claims=claims,
        product_variant_id=product_variant_id,
        godown_id=godown_id,
        limit=limit,
    )
    rows.reverse()  # list_transactions is newest-first; a ledger reads forward.

    running: dict[tuple, Decimal] = {}
    for row in rows:
        key = (row["product_variant_id"], row["godown_id"], row["batch_id"])
        running[key] = running.get(key, Decimal("0")) + Decimal(str(row["quantity"]))
        row["balance_after"] = running[key]
    return rows


async def create_transaction(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    body: TransactionCreate,
    request: Optional[Request] = None,
) -> dict:
    """A manual movement: damage, sales issue, write-off, or a correction."""
    assert_godown_in_scope(claims, body.godown_id)

    variant = (
        await session.execute(
            text(
                "SELECT pv.id, pv.sku, pv.uom_id AS base_uom_id, pv.is_active, pv.purchase_price, "
                "       p.name AS product_name, COALESCE(p.tracking_type, 'none') AS tracking_type "
                "FROM product_variants pv "
                "JOIN products p ON p.id = pv.product_id AND p.company_id = pv.company_id "
                "WHERE pv.id = :v AND pv.company_id = :c AND pv.deleted_at IS NULL"
            ),
            {"v": body.product_variant_id, "c": claims.company_id},
        )
    ).mappings().first()
    if variant is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Product variant not found")
    if not variant["is_active"]:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_BUSINESS_RULE_VIOLATION,
            "This variant is inactive; reactivate it before posting stock against it",
        )

    # A naive value (a date-only field) is Indian time, not UTC midnight.
    txn_date = clock.as_business_time(body.txn_date) if body.txn_date else datetime.now(timezone.utc)
    # BR-INV-10, first half: a movement cannot be dated in the future — by
    # the day in India. The second half (the period-close marker) needs the
    # tenant's settings and lives in the ledger module.
    if clock.is_future_day(txn_date):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_BUSINESS_RULE_VIOLATION,
            "A movement cannot be dated in the future",
        )
    await ledger.assert_period_open(session, company_id=claims.company_id, on=txn_date.date())

    # BR-INV-07 ahead of the engine's own check, so the caller gets the
    # documented code and a field-level message instead of a 500.
    if body.txn_type in ("DAMAGE", "STOCK_CORRECTION") and not (body.remarks and body.remarks.strip()):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_REMARKS_REQUIRED,
            f"{body.txn_type} needs remarks explaining what happened",
            errors=[{"field": "remarks", "message": "Required for this movement type"}],
        )
    reason_code = body.reason_code or ("correction" if body.txn_type == "STOCK_CORRECTION" else body.txn_type.lower())

    outward = body.txn_type in _OUTWARD or (body.txn_type == "STOCK_CORRECTION" and body.direction == "decrease")

    await ledger.assert_batch_ok(
        session,
        company_id=claims.company_id,
        product_variant_id=body.product_variant_id,
        tracking_type=variant["tracking_type"],
        batch_id=body.batch_id,
        outward=outward,
        override_expiry="inventory.override_expiry" in claims.permissions,
    )

    # BR-INV-08: store in the variant's base unit, and freeze the factor.
    factor = await ledger.resolve_conversion_factor(
        session,
        company_id=claims.company_id,
        product_variant_id=body.product_variant_id,
        base_uom_id=variant["base_uom_id"],
        line_uom_id=body.uom_id,
    )
    base_quantity = (Decimal(str(body.quantity)) * factor).quantize(Decimal("0.001"))
    signed = -base_quantity if outward else base_quantity

    allow_negative = bool(
        (
            await session.execute(
                text("SELECT allow_negative_stock FROM company_settings WHERE company_id = :c"),
                {"c": claims.company_id},
            )
        ).scalar_one_or_none()
    )

    txn_number = await numbering.allocate(
        session, company_id=claims.company_id, doc_type="adjustment", on=txn_date.date()
    )

    row = await ledger.post_transaction(
        session,
        company_id=claims.company_id,
        txn_type=body.txn_type,
        txn_number=txn_number,
        txn_date=txn_date,
        product_variant_id=body.product_variant_id,
        godown_id=body.godown_id,
        quantity=signed,
        uom_id=variant["base_uom_id"],
        performed_by=UUID(claims.user_id),
        allow_negative_stock=allow_negative,
        batch_id=body.batch_id,
        unit_cost=variant["purchase_price"],
        source_type=_SOURCE_BY_TYPE.get(body.txn_type, _SOURCE_TYPE),
        reason_code=reason_code,
        remarks=body.remarks,
        entered_quantity=body.quantity,
        entered_uom_id=body.uom_id,
        conversion_factor=factor,
    )

    await audit.record(
        session,
        entity_type="inventory_transaction",
        action="created",
        claims=claims,
        entity_id=row["id"],
        entity_label=txn_number,
        description=f"{body.txn_type} {signed} of {variant['sku']}",
        after={"txn_type": body.txn_type, "quantity": str(signed), "godown_id": str(body.godown_id)},
        request=request,
    )
    await session.commit()
    # The commit above ended the transaction the RLS tenant scope was set
    # on -- `set_tenant()` uses `set_config(..., is_local => true)`, which is
    # transaction-scoped by design (core/db.py). Reading back on the same
    # session without re-asserting it runs with no scope and fails RLS with
    # "invalid input syntax for type uuid: ''". Same trap `comparison_service`
    # hit last phase; it bites any service that commits then reads.
    await set_tenant(session, UUID(claims.company_id))
    return await _load(session, company_id=claims.company_id, txn_id=row["id"])


async def reverse_transaction(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    txn_id: UUID,
    reason: str,
    request: Optional[Request] = None,
) -> dict:
    """Post the offsetting row that cancels a movement out.

    Guarded against double-reversal by looking for an existing row that
    already points at this one -- without that check, clicking twice
    silently posts the correction twice and leaves the balance wrong in the
    opposite direction.
    """
    original = await _load(session, company_id=claims.company_id, txn_id=txn_id)
    assert_godown_in_scope(claims, original["godown_id"])

    existing = (
        await session.execute(
            text("SELECT id, txn_number FROM inventory_transactions WHERE company_id = :c AND reverses_txn_id = :t"),
            {"c": claims.company_id, "t": txn_id},
        )
    ).mappings().first()
    if existing:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_IMMUTABLE_LEDGER,
            f"This movement was already reversed by {existing['txn_number']}",
        )
    if original["reverses_txn_id"]:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_IMMUTABLE_LEDGER,
            "This row is itself a reversal; reverse the original movement instead",
        )

    # A reversal is always a STOCK_CORRECTION carrying the opposite sign:
    # posting it as the original type would claim a second DAMAGE happened.
    signed = -Decimal(str(original["quantity"]))
    now = datetime.now(timezone.utc)
    await ledger.assert_period_open(session, company_id=claims.company_id, on=now.date())

    allow_negative = bool(
        (
            await session.execute(
                text("SELECT allow_negative_stock FROM company_settings WHERE company_id = :c"),
                {"c": claims.company_id},
            )
        ).scalar_one_or_none()
    )
    txn_number = await numbering.allocate(session, company_id=claims.company_id, doc_type="adjustment", on=now.date())

    row = await ledger.post_transaction(
        session,
        company_id=claims.company_id,
        txn_type="STOCK_CORRECTION",
        txn_number=txn_number,
        txn_date=now,
        product_variant_id=original["product_variant_id"],
        godown_id=original["godown_id"],
        quantity=signed,
        uom_id=original["uom_id"],
        performed_by=UUID(claims.user_id),
        allow_negative_stock=allow_negative,
        batch_id=original["batch_id"],
        unit_cost=original["unit_cost"],
        source_type=_SOURCE_TYPE,
        reason_code="reversal",
        remarks=reason,
        reverses_txn_id=txn_id,
    )

    await audit.record(
        session,
        entity_type="inventory_transaction",
        action="reversed",
        claims=claims,
        entity_id=row["id"],
        entity_label=txn_number,
        description=f"Reversed {original['txn_number']}: {reason}",
        before={"txn_number": original["txn_number"], "quantity": str(original["quantity"])},
        after={"txn_number": txn_number, "quantity": str(signed)},
        request=request,
    )
    await session.commit()
    await set_tenant(session, UUID(claims.company_id))  # see create_transaction
    return await _load(session, company_id=claims.company_id, txn_id=row["id"])
