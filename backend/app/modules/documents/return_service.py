"""
Purchase returns -- goods going back to the supplier.

This is the one document in this module that moves stock, and it moves it
the only way anything in this system moves stock: by posting through
`core/inventory.post_transaction` (BR-INV-01). A confirmed return writes one
`PURCHASE_RETURN` row per line and stamps the resulting transaction id back
onto the line, so the paper document and the ledger entry point at each
other.

Draft returns move nothing. That split matters: a return is often raised
while the goods are still being argued about, and stock should not leave the
books until someone confirms it actually went back.

The quantity guard is the substantive rule here -- you cannot return more of
a line than the GRN accepted. Without it a typo silently drives stock
negative (or, with `allow_negative_stock` on, quietly wrong), and the
supplier gets a debit note for goods they never delivered.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from fastapi import Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, inventory as ledger, numbering
from app.core.db import set_tenant
from app.core.deps import assert_godown_in_scope, scoped_godown_filter
from app.core.errors import (
    ApiError,
    CODE_BUSINESS_RULE_VIOLATION,
    CODE_INVALID_STATE_TRANSITION,
    CODE_NOT_FOUND,
    CODE_RETURN_EXCEEDS_RECEIPT,
)
from app.core.money import D, round2
from app.core.security import AccessTokenClaims
from app.modules.documents.schemas import ReturnCreate, ReturnUpdate

# §14: RETURN: draft -> sent -> accepted -> credited, with cancelled.
# Stock leaves at `sent` — the moment the goods physically go back — not at
# `credited`, which is the supplier's accounting catching up later.
_ALLOWED_TRANSITIONS = {
    "draft": {"sent", "cancelled"},
    "sent": {"accepted", "cancelled"},
    "accepted": {"credited"},
    "credited": set(),
    "cancelled": set(),
}


async def _load(session: AsyncSession, *, company_id: UUID, return_id: UUID) -> dict:
    header = (
        await session.execute(
            text(
                "SELECT pr.*, COALESCE(s.name, '') AS supplier_name, COALESCE(g.name, '') AS godown_name, "
                "       gr.grn_number "
                "FROM purchase_returns pr "
                "LEFT JOIN suppliers s ON s.id = pr.supplier_id AND s.company_id = pr.company_id "
                "LEFT JOIN godowns g ON g.id = pr.godown_id AND g.company_id = pr.company_id "
                "LEFT JOIN goods_receipts gr ON gr.id = pr.goods_receipt_id AND gr.company_id = pr.company_id "
                "WHERE pr.id = :id AND pr.company_id = :c"
            ),
            {"id": return_id, "c": company_id},
        )
    ).mappings().first()
    if header is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Purchase return not found")

    items = (
        await session.execute(
            text(
                "SELECT ri.*, COALESCE(pv.sku, '') AS sku, "
                "       TRIM(COALESCE(p.name, '') || ' ' || COALESCE(pv.variant_name, '')) AS product_name "
                "FROM purchase_return_items ri "
                "LEFT JOIN product_variants pv ON pv.id = ri.product_variant_id AND pv.company_id = ri.company_id "
                "LEFT JOIN products p ON p.id = pv.product_id AND p.company_id = pv.company_id "
                "WHERE ri.return_id = :id AND ri.company_id = :c ORDER BY ri.id"
            ),
            {"id": return_id, "c": company_id},
        )
    ).mappings().all()

    out = dict(header)
    out["items"] = [dict(i) for i in items]
    out["item_count"] = len(items)
    # Derived, not stored: a line carrying a transaction id is proof the
    # posting happened, which a separate boolean column could contradict.
    out["stock_posted"] = any(i["inventory_transaction_id"] for i in items)
    return out


async def list_returns(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    status_filter: Optional[str] = None,
    supplier_id: Optional[UUID] = None,
    goods_receipt_id: Optional[UUID] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    where = ["pr.company_id = :c"]
    params: dict = {"c": claims.company_id}

    scope_sql, scope_params = scoped_godown_filter(claims, "pr.godown_id")
    if scope_sql:
        where.append(scope_sql)
        params.update(scope_params)
    if status_filter:
        where.append("pr.status = :status_filter")
        params["status_filter"] = status_filter
    if supplier_id:
        where.append("pr.supplier_id = :supplier_id")
        params["supplier_id"] = supplier_id
    if goods_receipt_id:
        where.append("pr.goods_receipt_id = :goods_receipt_id")
        params["goods_receipt_id"] = goods_receipt_id

    rows = (
        await session.execute(
            text(
                "SELECT pr.*, COALESCE(s.name, '') AS supplier_name, COALESCE(g.name, '') AS godown_name, "
                "       gr.grn_number, "
                "       (SELECT COUNT(*) FROM purchase_return_items ri "
                "         WHERE ri.return_id = pr.id AND ri.company_id = pr.company_id) AS item_count, "
                "       EXISTS (SELECT 1 FROM purchase_return_items ri2 "
                "         WHERE ri2.return_id = pr.id AND ri2.company_id = pr.company_id "
                "           AND ri2.inventory_transaction_id IS NOT NULL) AS stock_posted "
                "FROM purchase_returns pr "
                "LEFT JOIN suppliers s ON s.id = pr.supplier_id AND s.company_id = pr.company_id "
                "LEFT JOIN godowns g ON g.id = pr.godown_id AND g.company_id = pr.company_id "
                "LEFT JOIN goods_receipts gr ON gr.id = pr.goods_receipt_id AND gr.company_id = pr.company_id "
                f"WHERE {' AND '.join(where)} "
                "ORDER BY pr.return_date DESC, pr.return_number DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": limit, "offset": offset},
        )
    ).mappings().all()
    return [{**dict(r), "items": []} for r in rows]


async def get_return(session: AsyncSession, *, company_id: UUID, return_id: UUID) -> dict:
    return await _load(session, company_id=company_id, return_id=return_id)


async def _assert_within_receipt(session: AsyncSession, *, company_id: UUID, items, return_id: Optional[UUID]) -> None:
    """You cannot send back more than arrived.

    Counts what other returns already claim against the same GRN line, so
    three separate returns of 40% each are caught on the third rather than
    each passing its own isolated check.
    """
    for item in items:
        if not item.goods_receipt_item_id:
            continue
        accepted = (
            await session.execute(
                text(
                    "SELECT accepted_quantity FROM goods_receipt_items WHERE id = :id AND company_id = :c"
                ),
                {"id": item.goods_receipt_item_id, "c": company_id},
            )
        ).scalar_one_or_none()
        if accepted is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Goods receipt line not found")

        params = {"grn_item": item.goods_receipt_item_id, "c": company_id}
        exclude = ""
        if return_id:
            exclude = "AND ri.return_id <> :self "
            params["self"] = return_id
        already = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(ri.quantity), 0) FROM purchase_return_items ri "
                    "JOIN purchase_returns pr ON pr.id = ri.return_id AND pr.company_id = ri.company_id "
                    f"WHERE ri.goods_receipt_item_id = :grn_item AND ri.company_id = :c {exclude}"
                    "AND pr.status <> 'cancelled'"
                ),
                params,
            )
        ).scalar_one()

        if D(already) + D(item.quantity) > D(accepted):
            remaining = round2(D(accepted) - D(already))
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                CODE_RETURN_EXCEEDS_RECEIPT,
                f"Only {remaining} of this line remains returnable; {accepted} was accepted "
                f"and {already} has already been returned",
                errors=[{"field": "quantity", "message": f"At most {remaining}"}],
            )


async def _write_items(session: AsyncSession, *, company_id: UUID, return_id: UUID, items) -> Decimal:
    await session.execute(
        text("DELETE FROM purchase_return_items WHERE return_id = :id AND company_id = :c"),
        {"id": return_id, "c": company_id},
    )
    total = Decimal("0")
    for item in items:
        line_total = round2(D(item.quantity) * D(item.unit_price) * (1 + D(item.gst_rate) / Decimal(100)))
        total += line_total
        await session.execute(
            text(
                "INSERT INTO purchase_return_items "
                "(company_id, return_id, goods_receipt_item_id, product_variant_id, batch_id, quantity, "
                " unit_price, gst_rate, line_total) "
                "VALUES (:c, :ret, :grn_item, :variant, :batch, :qty, :price, :gst, :total)"
            ),
            {
                "c": company_id,
                "ret": return_id,
                "grn_item": item.goods_receipt_item_id,
                "variant": item.product_variant_id,
                "batch": item.batch_id,
                "qty": D(item.quantity),
                "price": D(item.unit_price),
                "gst": D(item.gst_rate),
                "total": line_total,
            },
        )
    return round2(total)


async def create_return(
    session: AsyncSession, *, claims: AccessTokenClaims, body: ReturnCreate, request: Optional[Request] = None
) -> dict:
    company_id = UUID(claims.company_id)
    assert_godown_in_scope(claims, body.godown_id)

    supplier = (
        await session.execute(
            text("SELECT id, name FROM suppliers WHERE id = :id AND company_id = :c AND deleted_at IS NULL"),
            {"id": body.supplier_id, "c": company_id},
        )
    ).mappings().first()
    if supplier is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Supplier not found")

    return_date = body.return_date or date.today()
    if return_date > date.today():
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_BUSINESS_RULE_VIOLATION,
            "A return cannot be dated in the future",
        )

    await _assert_within_receipt(session, company_id=company_id, items=body.items, return_id=None)

    return_id = uuid4()
    return_number = await numbering.allocate(
        session, company_id=company_id, doc_type="return", on=return_date
    )
    await session.execute(
        text(
            "INSERT INTO purchase_returns "
            "(id, company_id, return_number, return_date, supplier_id, goods_receipt_id, purchase_order_id, "
            " godown_id, reason, status, debit_note_number, eway_bill_number, total_amount) "
            "VALUES (:id, :c, :number, :ret_date, :supplier, :grn, :po, :godown, :reason, 'draft', "
            " :debit_note, :eway, 0)"
        ),
        {
            "id": return_id,
            "c": company_id,
            "number": return_number,
            "ret_date": return_date,
            "supplier": body.supplier_id,
            "grn": body.goods_receipt_id,
            "po": body.purchase_order_id,
            "godown": body.godown_id,
            "reason": body.reason,
            "debit_note": body.debit_note_number,
            "eway": body.eway_bill_number,
        },
    )

    total = await _write_items(session, company_id=company_id, return_id=return_id, items=body.items)
    await session.execute(
        text("UPDATE purchase_returns SET total_amount = :t WHERE id = :id AND company_id = :c"),
        {"t": total, "id": return_id, "c": company_id},
    )

    await audit.record(
        session,
        entity_type="purchase_return",
        action="created",
        claims=claims,
        entity_id=return_id,
        entity_label=return_number,
        description=f"{len(body.items)} line(s) to {supplier['name']}: {body.reason}",
        after={"total_amount": str(total), "supplier_id": str(body.supplier_id)},
        request=request,
    )
    await session.commit()
    await set_tenant(session, company_id)
    return await _load(session, company_id=company_id, return_id=return_id)


async def update_return(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    return_id: UUID,
    body: ReturnUpdate,
    request: Optional[Request] = None,
) -> dict:
    company_id = UUID(claims.company_id)
    before = await _load(session, company_id=company_id, return_id=return_id)
    if before["status"] != "draft":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_INVALID_STATE_TRANSITION,
            f"Only a draft return can be edited (this one is {before['status']})",
        )
    assert_godown_in_scope(claims, before["godown_id"])

    header_fields = body.model_dump(exclude_unset=True, exclude={"items"})
    if header_fields:
        assignments = ", ".join(f"{k} = :{k}" for k in header_fields)
        await session.execute(
            text(f"UPDATE purchase_returns SET {assignments} WHERE id = :id AND company_id = :c"),
            {**header_fields, "id": return_id, "c": company_id},
        )

    if body.items is not None:
        await _assert_within_receipt(session, company_id=company_id, items=body.items, return_id=return_id)
        total = await _write_items(session, company_id=company_id, return_id=return_id, items=body.items)
        await session.execute(
            text("UPDATE purchase_returns SET total_amount = :t WHERE id = :id AND company_id = :c"),
            {"t": total, "id": return_id, "c": company_id},
        )

    await audit.record(
        session,
        entity_type="purchase_return",
        action="updated",
        claims=claims,
        entity_id=return_id,
        entity_label=before["return_number"],
        request=request,
    )
    await session.commit()
    await set_tenant(session, company_id)
    return await _load(session, company_id=company_id, return_id=return_id)


async def confirm_return(
    session: AsyncSession, *, claims: AccessTokenClaims, return_id: UUID, request: Optional[Request] = None
) -> dict:
    """Send the goods back: post one `PURCHASE_RETURN` row per line.

    Idempotent. A line that already carries an `inventory_transaction_id`
    has already left the books, and posting it twice would take the stock
    out twice -- the same guard the GRN confirm path settled on.
    """
    company_id = UUID(claims.company_id)
    before = await _load(session, company_id=company_id, return_id=return_id)

    if before["status"] not in ("draft", "sent"):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_INVALID_STATE_TRANSITION,
            f"A return in status {before['status']} cannot be confirmed",
        )
    assert_godown_in_scope(claims, before["godown_id"])

    if before["stock_posted"]:
        # Already posted; move the status along without touching stock.
        if before["status"] == "draft":
            await session.execute(
                text("UPDATE purchase_returns SET status = 'sent' WHERE id = :id AND company_id = :c"),
                {"id": return_id, "c": company_id},
            )
            await session.commit()
            await set_tenant(session, company_id)
        return await _load(session, company_id=company_id, return_id=return_id)

    return_date = before["return_date"]
    await ledger.assert_period_open(session, company_id=company_id, on=return_date)
    txn_datetime = datetime.combine(return_date, time(12, 0), tzinfo=timezone.utc)

    allow_negative = bool(
        (
            await session.execute(
                text("SELECT allow_negative_stock FROM company_settings WHERE company_id = :c"),
                {"c": company_id},
            )
        ).scalar_one_or_none()
    )

    for line in before["items"]:
        variant = (
            await session.execute(
                text(
                    "SELECT pv.uom_id AS base_uom_id, pv.purchase_price, "
                    "       COALESCE(p.tracking_type, 'none') AS tracking_type "
                    "FROM product_variants pv JOIN products p ON p.id = pv.product_id AND p.company_id = pv.company_id "
                    "WHERE pv.id = :v AND pv.company_id = :c"
                ),
                {"v": line["product_variant_id"], "c": company_id},
            )
        ).mappings().first()
        if variant is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Product variant not found")

        # Goods leaving for a return are an outward movement, so an expired
        # batch is checked the same way it is for any other outward move.
        await ledger.assert_batch_ok(
            session,
            company_id=company_id,
            product_variant_id=line["product_variant_id"],
            tracking_type=variant["tracking_type"],
            batch_id=line["batch_id"],
            outward=True,
            override_expiry="inventory.override_expiry" in claims.permissions,
        )

        txn = await ledger.post_transaction(
            session,
            company_id=company_id,
            txn_type="PURCHASE_RETURN",
            txn_number=before["return_number"],
            txn_date=txn_datetime,
            product_variant_id=line["product_variant_id"],
            godown_id=before["godown_id"],
            quantity=-D(line["quantity"]),
            uom_id=variant["base_uom_id"],
            performed_by=UUID(claims.user_id),
            allow_negative_stock=allow_negative,
            batch_id=line["batch_id"],
            unit_cost=D(line["unit_price"]),
            source_type="purchase_return",
            source_id=return_id,
            source_line_id=line["id"],
            remarks=before["reason"],
        )
        await session.execute(
            text(
                "UPDATE purchase_return_items SET inventory_transaction_id = :txn "
                "WHERE id = :id AND company_id = :c"
            ),
            {"txn": txn["id"], "id": line["id"], "c": company_id},
        )

    await session.execute(
        text("UPDATE purchase_returns SET status = 'sent' WHERE id = :id AND company_id = :c"),
        {"id": return_id, "c": company_id},
    )
    await audit.record(
        session,
        entity_type="purchase_return",
        action="confirmed",
        claims=claims,
        entity_id=return_id,
        entity_label=before["return_number"],
        description=f"{len(before['items'])} line(s) posted out of {before['godown_name']}",
        before={"status": before["status"]},
        after={"status": "sent"},
        request=request,
    )
    await session.commit()
    await set_tenant(session, company_id)
    return await _load(session, company_id=company_id, return_id=return_id)


async def set_status(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    return_id: UUID,
    new_status: str,
    note: Optional[str] = None,
    request: Optional[Request] = None,
) -> dict:
    company_id = UUID(claims.company_id)
    before = await _load(session, company_id=company_id, return_id=return_id)
    current = before["status"]

    if new_status not in _ALLOWED_TRANSITIONS.get(current, set()):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_INVALID_STATE_TRANSITION,
            f"A return cannot go from {current} to {new_status}",
        )

    # `sent` is where stock leaves, so route it through confirm rather than
    # letting a plain status change move goods without posting anything.
    if new_status == "sent":
        return await confirm_return(session, claims=claims, return_id=return_id, request=request)

    if new_status == "cancelled" and before["stock_posted"]:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_BUSINESS_RULE_VIOLATION,
            "This return has already moved stock; reverse those transactions instead of cancelling it",
        )

    await session.execute(
        text("UPDATE purchase_returns SET status = :status WHERE id = :id AND company_id = :c"),
        {"status": new_status, "id": return_id, "c": company_id},
    )
    await audit.record(
        session,
        entity_type="purchase_return",
        action="cancelled" if new_status == "cancelled" else "status_changed",
        claims=claims,
        entity_id=return_id,
        entity_label=before["return_number"],
        description=note,
        before={"status": current},
        after={"status": new_status},
        request=request,
    )
    await session.commit()
    await set_tenant(session, company_id)
    return await _load(session, company_id=company_id, return_id=return_id)
