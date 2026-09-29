"""
Godown-to-godown stock transfers.

BR-INV-06: "a transfer writes exactly two rows in one transaction
(`TRANSFER_OUT` -q, `TRANSFER_IN` +q) with `counterpart_txn_id` set both
ways, and `from_godown != to_godown`."

The pairing is the point. A transfer posted as two independent movements
can half-fail and leave stock that exists in neither godown, or in both --
so both legs and the transfer header are written inside one transaction and
commit together. `counterpart_txn_id` is then set on each row pointing at
the other, which is what makes a transfer reconstructable from the ledger
alone rather than only from the `stock_transfers` table.

Phase 1 posts both legs immediately (status `received`). The two-step
in-transit mode the spec describes -- dispatch now, receive later -- needs
a company setting that does not exist yet, so it is deliberately not
implemented rather than half-implemented.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from fastapi import Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core import audit, inventory as ledger, numbering
from app.core.db import set_tenant
from app.core.deps import assert_godown_in_scope, scoped_godown_filter
from app.core.errors import (
    ApiError,
    CODE_BUSINESS_RULE_VIOLATION,
    CODE_NOT_FOUND,
    CODE_SAME_GODOWN,
)
from app.core.security import AccessTokenClaims
from app.modules.inventory import txn_service
from app.modules.inventory.schemas import TransferCreate


async def _load(session: AsyncSession, *, company_id: UUID, transfer_id: UUID) -> dict:
    header = (
        await session.execute(
            text(
                "SELECT st.id, st.transfer_number, st.transfer_date, st.from_godown_id, st.to_godown_id, "
                "       COALESCE(fg.name, '') AS from_godown_name, COALESCE(tg.name, '') AS to_godown_name, "
                "       st.status, st.dispatched_by, st.received_by, st.vehicle_number, st.lr_number, "
                "       st.eway_bill_number, st.remarks "
                "FROM stock_transfers st "
                "LEFT JOIN godowns fg ON fg.id = st.from_godown_id AND fg.company_id = st.company_id "
                "LEFT JOIN godowns tg ON tg.id = st.to_godown_id AND tg.company_id = st.company_id "
                "WHERE st.id = :id AND st.company_id = :c"
            ),
            {"id": transfer_id, "c": company_id},
        )
    ).mappings().first()
    if header is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Transfer not found")

    items = (
        await session.execute(
            text(
                "SELECT sti.id, sti.product_variant_id, COALESCE(pv.sku, '') AS sku, "
                "       TRIM(COALESCE(p.name, '') || ' ' || COALESCE(pv.variant_name, '')) AS product_name, "
                "       sti.batch_id, sti.quantity, sti.uom_id, sti.dispatched_qty, sti.received_qty "
                "FROM stock_transfer_items sti "
                "LEFT JOIN product_variants pv ON pv.id = sti.product_variant_id AND pv.company_id = sti.company_id "
                "LEFT JOIN products p ON p.id = pv.product_id AND p.company_id = pv.company_id "
                "WHERE sti.transfer_id = :id AND sti.company_id = :c ORDER BY sti.id"
            ),
            {"id": transfer_id, "c": company_id},
        )
    ).mappings().all()

    # The ledger rows this transfer produced, found through source_id rather
    # than stored on the transfer: the ledger is the record of what moved.
    txns = (
        await session.execute(
            text(
                f"{txn_service._ROW_SELECT} "
                "WHERE it.company_id = :c AND it.source_type = 'stock_transfer' AND it.source_id = :id "
                "ORDER BY it.quantity"
            ),
            {"c": company_id, "id": transfer_id},
        )
    ).mappings().all()

    out = dict(header)
    out["items"] = [dict(i) for i in items]
    out["transactions"] = [dict(t) for t in txns]
    return out


async def list_transfers(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    godown_id: Optional[UUID] = None,
    status_filter: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    where = ["st.company_id = :c"]
    params: dict = {"c": claims.company_id}

    # A scoped user sees a transfer if *either* end is in their scope --
    # stock arriving from a godown they can't see is still their business.
    from_sql, from_params = scoped_godown_filter(claims, "st.from_godown_id")
    to_sql, to_params = scoped_godown_filter(claims, "st.to_godown_id")
    if from_sql:
        where.append(f"(({from_sql}) OR ({to_sql}))")
        params.update(from_params)
        params.update(to_params)

    if godown_id:
        where.append("(st.from_godown_id = :godown_id OR st.to_godown_id = :godown_id)")
        params["godown_id"] = godown_id
    if status_filter:
        where.append("st.status = :status_filter")
        params["status_filter"] = status_filter

    rows = (
        await session.execute(
            text(
                "SELECT st.id, st.transfer_number, st.transfer_date, st.from_godown_id, st.to_godown_id, "
                "       COALESCE(fg.name, '') AS from_godown_name, COALESCE(tg.name, '') AS to_godown_name, "
                "       st.status, st.dispatched_by, st.received_by, st.vehicle_number, st.lr_number, "
                "       st.eway_bill_number, st.remarks "
                "FROM stock_transfers st "
                "LEFT JOIN godowns fg ON fg.id = st.from_godown_id AND fg.company_id = st.company_id "
                "LEFT JOIN godowns tg ON tg.id = st.to_godown_id AND tg.company_id = st.company_id "
                f"WHERE {' AND '.join(where)} "
                "ORDER BY st.transfer_date DESC, st.transfer_number DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": limit, "offset": offset},
        )
    ).mappings().all()
    return [{**dict(r), "items": [], "transactions": []} for r in rows]


async def get_transfer(session: AsyncSession, *, claims: AccessTokenClaims, transfer_id: UUID) -> dict:
    return await _load(session, company_id=claims.company_id, transfer_id=transfer_id)


async def create_transfer(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    body: TransferCreate,
    request: Optional[Request] = None,
) -> dict:
    if body.from_godown_id == body.to_godown_id:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_SAME_GODOWN,
            "A transfer needs two different godowns",
        )

    # Both ends must be in scope. `inventory.transfer_any` is the documented
    # override for a transfer that crosses the boundary (BR-AUTH-12).
    assert_godown_in_scope(claims, body.from_godown_id, override_permission="inventory.transfer_any")
    assert_godown_in_scope(claims, body.to_godown_id, override_permission="inventory.transfer_any")

    for godown_id in (body.from_godown_id, body.to_godown_id):
        exists = (
            await session.execute(
                text("SELECT 1 FROM godowns WHERE id = :g AND company_id = :c AND deleted_at IS NULL"),
                {"g": godown_id, "c": claims.company_id},
            )
        ).scalar_one_or_none()
        if not exists:
            raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Godown not found")

    transfer_date = body.transfer_date or clock.today()
    if clock.is_future_day(transfer_date):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_BUSINESS_RULE_VIOLATION,
            "A transfer cannot be dated in the future",
        )
    await ledger.assert_period_open(session, company_id=claims.company_id, on=transfer_date)

    txn_datetime = datetime.combine(transfer_date, time(12, 0), tzinfo=timezone.utc)
    allow_negative = bool(
        (
            await session.execute(
                text("SELECT allow_negative_stock FROM company_settings WHERE company_id = :c"),
                {"c": claims.company_id},
            )
        ).scalar_one_or_none()
    )

    # BR-INV-06's cross-pointers mean each ledger row references one that is
    # written after it. Migration a71c4e0d95b2 made that FK deferrable
    # precisely for this; deferring it here moves the check to COMMIT, by
    # which point both rows exist. Nothing else in the codebase defers, so
    # every other posting path still gets immediate checking.
    await session.execute(
        text("SET CONSTRAINTS fk_inventory_transactions_counterpart_txn_id_inventory_ded32bea DEFERRED")
    )

    transfer_number = await numbering.allocate(
        session, company_id=claims.company_id, doc_type="transfer", on=transfer_date
    )
    header = (
        await session.execute(
            text(
                "INSERT INTO stock_transfers "
                "(company_id, transfer_number, transfer_date, from_godown_id, to_godown_id, status, "
                " dispatched_by, received_by, vehicle_number, lr_number, eway_bill_number, remarks) "
                "VALUES (:c, :number, :transfer_date, :from_g, :to_g, 'received', "
                " :who, :who, :vehicle, :lr, :eway, :remarks) RETURNING id"
            ),
            {
                "c": claims.company_id,
                "number": transfer_number,
                "transfer_date": transfer_date,
                "from_g": body.from_godown_id,
                "to_g": body.to_godown_id,
                "who": UUID(claims.user_id),
                "vehicle": body.vehicle_number,
                "lr": body.lr_number,
                "eway": body.eway_bill_number,
                "remarks": body.remarks,
            },
        )
    ).mappings().first()
    transfer_id = header["id"]

    for item in body.items:
        variant = (
            await session.execute(
                text(
                    "SELECT pv.id, pv.sku, pv.uom_id AS base_uom_id, pv.purchase_price, "
                    "       COALESCE(p.tracking_type, 'none') AS tracking_type "
                    "FROM product_variants pv "
                    "JOIN products p ON p.id = pv.product_id AND p.company_id = pv.company_id "
                    "WHERE pv.id = :v AND pv.company_id = :c AND pv.deleted_at IS NULL"
                ),
                {"v": item.product_variant_id, "c": claims.company_id},
            )
        ).mappings().first()
        if variant is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Product variant not found")

        # The outward leg is the one that can fail on insufficient stock, so
        # the batch check runs with outward=True: an expired batch may not
        # leave a godown even to go to another one.
        await ledger.assert_batch_ok(
            session,
            company_id=claims.company_id,
            product_variant_id=item.product_variant_id,
            tracking_type=variant["tracking_type"],
            batch_id=item.batch_id,
            outward=True,
            override_expiry="inventory.override_expiry" in claims.permissions,
        )

        factor = await ledger.resolve_conversion_factor(
            session,
            company_id=claims.company_id,
            product_variant_id=item.product_variant_id,
            base_uom_id=variant["base_uom_id"],
            line_uom_id=item.uom_id,
        )
        base_quantity = (Decimal(str(item.quantity)) * factor).quantize(Decimal("0.001"))

        await session.execute(
            text(
                "INSERT INTO stock_transfer_items "
                "(company_id, transfer_id, product_variant_id, batch_id, quantity, uom_id, dispatched_qty, received_qty) "
                "VALUES (:c, :t, :v, :b, :qty, :uom, :qty, :qty)"
            ),
            {
                "c": claims.company_id,
                "t": transfer_id,
                "v": item.product_variant_id,
                "b": item.batch_id,
                "qty": base_quantity,
                "uom": variant["base_uom_id"],
            },
        )

        common = {
            "company_id": claims.company_id,
            "txn_number": transfer_number,
            "txn_date": txn_datetime,
            "product_variant_id": item.product_variant_id,
            "uom_id": variant["base_uom_id"],
            "performed_by": UUID(claims.user_id),
            "allow_negative_stock": allow_negative,
            "batch_id": item.batch_id,
            "unit_cost": variant["purchase_price"],
            "source_type": "stock_transfer",
            "source_id": transfer_id,
            "entered_quantity": item.quantity,
            "entered_uom_id": item.uom_id,
            "conversion_factor": factor,
        }

        # Both ids are decided here, before either row is written, because
        # the pair has to point at each other and the table refuses every
        # UPDATE (BR-INV-03's trigger). There is no back-fill available.
        out_id, in_id = uuid4(), uuid4()

        # Outward first: if the source godown hasn't got the stock, nothing
        # should have been written at all, and this is where that is found.
        await ledger.post_transaction(
            session,
            txn_type="TRANSFER_OUT",
            godown_id=body.from_godown_id,
            quantity=-base_quantity,
            txn_id=out_id,
            counterpart_txn_id=in_id,
            **common,
        )
        await ledger.post_transaction(
            session,
            txn_type="TRANSFER_IN",
            godown_id=body.to_godown_id,
            quantity=base_quantity,
            txn_id=in_id,
            counterpart_txn_id=out_id,
            **common,
        )

    await audit.record(
        session,
        entity_type="stock_transfer",
        action="created",
        claims=claims,
        entity_id=transfer_id,
        entity_label=transfer_number,
        description=f"{len(body.items)} item(s) transferred",
        after={
            "from_godown_id": str(body.from_godown_id),
            "to_godown_id": str(body.to_godown_id),
            "items": len(body.items),
        },
        request=request,
    )
    await session.commit()
    # Re-assert the tenant scope the commit just dropped -- see the note in
    # `txn_service.create_transaction`.
    await set_tenant(session, UUID(claims.company_id))
    return await _load(session, company_id=claims.company_id, transfer_id=transfer_id)
