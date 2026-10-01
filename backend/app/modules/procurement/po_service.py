"""
Purchase order service — 06_BUSINESS_RULES.md §7 (BR-PO-01..10), §10 (money)
and the PO arm of §14's state machine:

    draft -> pending_approval -> approved -> sent -> acknowledged
                                    -> partially_received -> received -> closed
         -> cancelled (only before any receipt)

`acknowledged` (a supplier confirming receipt of the PO through a future
portal integration) is declared in the schema's enum but nothing in this
phase transitions into it — GRNs confirm directly against `sent`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from fastapi import Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core import audit
from app.core.deps import assert_godown_in_scope
from app.core.errors import (
    CODE_APPROVAL_LIMIT_EXCEEDED,
    CODE_BUSINESS_RULE_VIOLATION,
    CODE_INVALID_STATE_TRANSITION,
    CODE_NOT_FOUND,
    CODE_NO_ITEMS,
    CODE_PO_HAS_RECEIPTS,
    CODE_STALE_RECORD,
    CODE_VALIDATION,
    ApiError,
)
from app.core.inventory import resolve_conversion_factor
from app.core.money import D, document_totals, is_inter_state, line_amounts
from app.core.numbering import allocate
from app.core.security import AccessTokenClaims
from app.modules.procurement.schemas import PoCancelRequest, PoCloseRequest, PoCreate, PoUpdate

_OPEN_LINE_STATUSES = ("open", "partially_received")


async def _load(session: AsyncSession, *, company_id: str, po_id: UUID) -> dict:
    header = (
        await session.execute(
            text(
                "SELECT id, po_number, supplier_id, rfq_id, quotation_id, comparison_id, po_date, "
                "expected_delivery_date, delivery_godown_id, payment_terms, delivery_terms, "
                "place_of_supply_state_code, is_inter_state, currency_code, subtotal, discount_amount, "
                "taxable_value, cgst_amount, sgst_amount, igst_amount, cess_amount, freight_amount, "
                "other_charges, round_off, total_amount, status, approved_by, approved_at, sent_at, "
                "cancelled_at, cancelled_by, cancellation_reason, notes, received_pct, fully_received_at, row_version, "
                "created_at, updated_at, "
                "(SELECT u.full_name FROM users u WHERE u.id = purchase_orders.cancelled_by) AS cancelled_by_name "
                "FROM purchase_orders WHERE id = :id AND company_id = :c"
            ),
            {"id": po_id, "c": company_id},
        )
    ).mappings().first()
    if header is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Purchase order not found")

    items = (
        await session.execute(
            text(
                "SELECT id, line_no, product_variant_id, quotation_item_id, rfq_item_id, description, hsn_code, "
                "quantity, uom_id, conversion_factor, unit_price, discount_pct, discount_amount, gst_rate, "
                "cess_rate, line_net, line_tax, line_total, received_quantity, returned_quantity, "
                "invoiced_quantity, pending_quantity, line_status, expected_delivery_date "
                "FROM purchase_order_items WHERE purchase_order_id = :id AND company_id = :c ORDER BY line_no"
            ),
            {"id": po_id, "c": company_id},
        )
    ).mappings().all()

    out = dict(header)
    out["items"] = [dict(r) for r in items]
    return out


async def list_pos(
    session: AsyncSession, *, company_id: str, limit: int = 100, offset: int = 0, status_filter: Optional[str] = None,
    supplier_id: Optional[UUID] = None,
) -> list[dict]:
    where = ["company_id = :c"]
    params: dict = {"c": company_id, "limit": limit, "offset": offset}
    if status_filter:
        where.append("status = :status")
        params["status"] = status_filter
    if supplier_id:
        where.append("supplier_id = :supplier_id")
        params["supplier_id"] = supplier_id
    rows = (
        await session.execute(
            text(
                "SELECT id, po_number, supplier_id, rfq_id, quotation_id, comparison_id, po_date, "
                "expected_delivery_date, delivery_godown_id, payment_terms, delivery_terms, "
                "place_of_supply_state_code, is_inter_state, currency_code, subtotal, discount_amount, "
                "taxable_value, cgst_amount, sgst_amount, igst_amount, cess_amount, freight_amount, "
                "other_charges, round_off, total_amount, status, approved_by, approved_at, sent_at, "
                "cancelled_at, cancelled_by, cancellation_reason, notes, received_pct, fully_received_at, row_version, "
                "created_at, updated_at, "
                "(SELECT u.full_name FROM users u WHERE u.id = purchase_orders.cancelled_by) AS cancelled_by_name, "
                # The list leaves the lines out; the count is all it shows of them.
                "(SELECT COUNT(*) FROM purchase_order_items i WHERE i.purchase_order_id = purchase_orders.id "
                "AND i.company_id = purchase_orders.company_id) AS item_count "
                f"FROM purchase_orders WHERE {' AND '.join(where)} "
                "ORDER BY po_date DESC, po_number DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
    ).mappings().all()
    return [{**dict(r), "items": []} for r in rows]


async def get_po(session: AsyncSession, *, company_id: str, po_id: UUID) -> dict:
    return await _load(session, company_id=company_id, po_id=po_id)


async def _auto_fill_from_rfq(session: AsyncSession, *, company_id: str, rfq_id: UUID) -> list[dict]:
    """BR-PO-08: only fills lines when the PO has none; the caller is what
    enforces "none" by only calling this when `body.items` was empty."""
    rows = (
        await session.execute(
            text(
                "SELECT ri.id AS rfq_item_id, ri.product_variant_id, ri.quantity, ri.uom_id, ri.expected_price, "
                "v.uom_id AS base_uom_id, v.gst_rate AS variant_gst_rate, v.purchase_price, "
                "p.gst_rate AS product_gst_rate, p.cess_rate "
                "FROM rfq_items ri "
                "JOIN product_variants v ON v.id = ri.product_variant_id AND v.company_id = ri.company_id "
                "JOIN products p ON p.id = v.product_id AND p.company_id = v.company_id "
                "WHERE ri.rfq_id = :rfq_id AND ri.company_id = :c AND ri.product_variant_id IS NOT NULL "
                "ORDER BY ri.line_no"
            ),
            {"rfq_id": rfq_id, "c": company_id},
        )
    ).mappings().all()
    return [
        {
            "product_variant_id": r["product_variant_id"],
            "description": None,
            "hsn_code": None,
            "quantity": float(r["quantity"]),
            "uom_id": r["uom_id"] or r["base_uom_id"],
            "unit_price": float(r["expected_price"]) if r["expected_price"] else float(r["purchase_price"]),
            "discount_pct": 0,
            "gst_rate": float(r["variant_gst_rate"] if r["variant_gst_rate"] is not None else r["product_gst_rate"]),
            "cess_rate": float(r["cess_rate"] or 0),
            "expected_delivery_date": None,
            "rfq_item_id": r["rfq_item_id"],
            "quotation_item_id": None,
        }
        for r in rows
    ]


async def _insert_items(
    session: AsyncSession, *, company_id: str, po_id: UUID, items: list, rounding_mode: str, freight, other_charges,
    is_inter_state: bool,
):
    """Computes and writes every line, then the header totals — BR-TAX-01..10.
    Returns the computed `DocumentTotals` fields as a dict."""
    gross_lines: list[Decimal] = []
    line_calcs = []
    for line_no, item in enumerate(items, start=1):
        variant = (
            await session.execute(
                text("SELECT uom_id FROM product_variants WHERE id = :id AND company_id = :c"),
                {"id": item["product_variant_id"] if isinstance(item, dict) else item.product_variant_id, "c": company_id},
            )
        ).mappings().first()
        if variant is None:
            raise ApiError(status.HTTP_400_BAD_REQUEST, CODE_VALIDATION, "One of the selected products does not exist")

        d = item if isinstance(item, dict) else item.model_dump()
        conversion_factor = await resolve_conversion_factor(
            session,
            company_id=UUID(company_id),
            product_variant_id=d["product_variant_id"],
            base_uom_id=variant["uom_id"],
            line_uom_id=d["uom_id"],
        )
        amounts = line_amounts(
            quantity=D(d["quantity"]),
            unit_price=D(d["unit_price"]),
            discount_pct=D(d["discount_pct"]),
            gst_rate=D(d["gst_rate"]),
            cess_rate=D(d["cess_rate"]),
        )
        gross_lines.append(D(d["quantity"]) * D(d["unit_price"]))
        line_calcs.append((d, amounts, conversion_factor))

        discount_amount = (D(d["quantity"]) * D(d["unit_price"]) * D(d["discount_pct"]) / Decimal(100)).quantize(Decimal("0.01"))
        await session.execute(
            text(
                "INSERT INTO purchase_order_items "
                "(company_id, purchase_order_id, line_no, product_variant_id, quotation_item_id, rfq_item_id, "
                " description, hsn_code, quantity, uom_id, conversion_factor, unit_price, discount_pct, "
                " discount_amount, gst_rate, cess_rate, line_net, line_tax, line_total, expected_delivery_date) "
                "VALUES (:c, :po_id, :line_no, :variant, :quotation_item_id, :rfq_item_id, :description, :hsn, "
                " :quantity, :uom, :factor, :unit_price, :discount_pct, :discount_amount, :gst_rate, :cess_rate, "
                " :line_net, :line_tax, :line_total, :expected_date)"
            ),
            {
                "c": company_id,
                "po_id": po_id,
                "line_no": line_no,
                "variant": d["product_variant_id"],
                "quotation_item_id": d.get("quotation_item_id"),
                "rfq_item_id": d.get("rfq_item_id"),
                "description": d.get("description"),
                "hsn": d.get("hsn_code"),
                "quantity": d["quantity"],
                "uom": d["uom_id"],
                "factor": conversion_factor,
                "unit_price": d["unit_price"],
                "discount_pct": d["discount_pct"],
                "discount_amount": discount_amount,
                "gst_rate": d["gst_rate"],
                "cess_rate": d["cess_rate"],
                "line_net": amounts.line_net,
                "line_tax": amounts.line_tax,
                "line_total": amounts.line_total,
                "expected_date": d.get("expected_delivery_date"),
            },
        )

    return document_totals(
        lines=[a for _, a, _ in line_calcs],
        gross_lines=gross_lines,
        is_inter_state=is_inter_state,
        freight_amount=D(freight),
        other_charges=D(other_charges),
        rounding_mode=rounding_mode,
    )


async def create_po(
    session: AsyncSession, *, claims: AccessTokenClaims, body: PoCreate, request: Optional[Request] = None
) -> dict:
    supplier = (
        await session.execute(
            text("SELECT id, name, state_code, status, gst_treatment FROM suppliers WHERE id = :id AND company_id = :c AND deleted_at IS NULL"),
            {"id": body.supplier_id, "c": claims.company_id},
        )
    ).mappings().first()
    if supplier is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Supplier not found")

    # BR-AUTH-12: a scoped user may not direct stock to a godown outside
    # their scope. This was missed when the PO path was first built — the
    # GRN path had it from the start, so a scoped user could not *receive*
    # elsewhere but could still order goods delivered there, which is the
    # same boundary crossed one document earlier.
    assert_godown_in_scope(claims, body.delivery_godown_id)

    godown = (
        await session.execute(
            text("SELECT id, state_code FROM godowns WHERE id = :id AND company_id = :c AND deleted_at IS NULL"),
            {"id": body.delivery_godown_id, "c": claims.company_id},
        )
    ).mappings().first()
    if godown is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Delivery godown not found")
    if not godown["state_code"]:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_BUSINESS_RULE_VIOLATION, "Delivery godown has no state code set"
        )

    items = body.items
    if not items and body.rfq_id:
        # BR-PO-08
        rfq = (
            await session.execute(
                text("SELECT id FROM rfqs WHERE id = :id AND company_id = :c"), {"id": body.rfq_id, "c": claims.company_id}
            )
        ).mappings().first()
        if rfq is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "RFQ not found")
        items = await _auto_fill_from_rfq(session, company_id=claims.company_id, rfq_id=body.rfq_id)

    if not items:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_NO_ITEMS, "A purchase order needs at least one item")

    settings = (
        await session.execute(
            text("SELECT rounding_mode FROM company_settings WHERE company_id = :c"), {"c": claims.company_id}
        )
    ).mappings().first()
    rounding_mode = (settings or {}).get("rounding_mode", "nearest")

    po_id = uuid4()
    po_date = body.po_date or clock.today()
    po_number = await allocate(session, company_id=UUID(claims.company_id), doc_type="po", on=po_date)
    inter_state = is_inter_state(supplier["state_code"], godown["state_code"])

    # Header first, with placeholder totals: purchase_order_items carries a
    # NOT NULL FK to purchase_orders, so the parent row has to exist before
    # _insert_items() can write any line against it. Totals are corrected
    # below once the lines (and their conversion factors) are known.
    await session.execute(
        text(
            "INSERT INTO purchase_orders "
            "(id, company_id, po_number, supplier_id, rfq_id, po_date, expected_delivery_date, delivery_godown_id, "
            " payment_terms, delivery_terms, place_of_supply_state_code, is_inter_state, notes) "
            "VALUES (:id, :c, :number, :supplier, :rfq_id, :po_date, :expected, :godown, :payment_terms, "
            " :delivery_terms, :state, :inter_state, :notes)"
        ),
        {
            "id": po_id,
            "c": claims.company_id,
            "number": po_number,
            "supplier": body.supplier_id,
            "rfq_id": body.rfq_id,
            "po_date": po_date,
            "expected": body.expected_delivery_date,
            "godown": body.delivery_godown_id,
            "payment_terms": body.payment_terms,
            "delivery_terms": body.delivery_terms,
            "state": godown["state_code"],
            "inter_state": inter_state,
            "notes": body.notes,
        },
    )

    totals = await _insert_items(
        session,
        company_id=claims.company_id,
        po_id=po_id,
        items=items,
        rounding_mode=rounding_mode,
        freight=body.freight_amount,
        other_charges=body.other_charges,
        is_inter_state=inter_state,
    )

    await session.execute(
        text(
            "UPDATE purchase_orders SET subtotal = :subtotal, discount_amount = :discount, taxable_value = :taxable, "
            "cgst_amount = :cgst, sgst_amount = :sgst, igst_amount = :igst, cess_amount = :cess, "
            "freight_amount = :freight, other_charges = :other, round_off = :round_off, total_amount = :total "
            "WHERE id = :id"
        ),
        {
            "id": po_id,
            "subtotal": totals.subtotal,
            "discount": totals.discount_amount,
            "taxable": totals.taxable_value,
            "cgst": totals.cgst_amount,
            "sgst": totals.sgst_amount,
            "igst": totals.igst_amount,
            "cess": totals.cess_amount,
            "freight": totals.freight_amount,
            "other": totals.other_charges,
            "round_off": totals.round_off,
            "total": totals.total_amount,
        },
    )

    result = await _load(session, company_id=claims.company_id, po_id=po_id)
    await audit.record(
        session,
        entity_type="purchase_order",
        action="created",
        claims=claims,
        entity_id=po_id,
        entity_label=po_number,
        after=result,
        request=request,
    )
    await session.commit()
    return result


async def update_po(
    session: AsyncSession, *, claims: AccessTokenClaims, po_id: UUID, body: PoUpdate, request: Optional[Request] = None
) -> dict:
    before = await _load(session, company_id=claims.company_id, po_id=po_id)
    if before["status"] != "draft":
        # BR-PO-04
        raise ApiError(
            status.HTTP_409_CONFLICT, CODE_INVALID_STATE_TRANSITION, f"Only draft POs are editable (current status: {before['status']})"
        )
    if body.row_version != before["row_version"]:
        raise ApiError(status.HTTP_409_CONFLICT, CODE_STALE_RECORD, "This purchase order was changed by someone else; reload and retry")

    # Same BR-AUTH-12 guard as create: editing a draft is another way to
    # point a delivery at a godown outside the caller's scope.
    if body.delivery_godown_id is not None:
        assert_godown_in_scope(claims, body.delivery_godown_id)

    header_fields = body.model_dump(exclude_unset=True, exclude={"items", "row_version"})
    if header_fields:
        assignments = ", ".join(f"{k} = :{k}" for k in header_fields)
        await session.execute(
            text(f"UPDATE purchase_orders SET {assignments}, row_version = row_version + 1 WHERE id = :id AND company_id = :c"),
            {**header_fields, "id": po_id, "c": claims.company_id},
        )
    else:
        await session.execute(
            text("UPDATE purchase_orders SET row_version = row_version + 1 WHERE id = :id"), {"id": po_id}
        )

    if body.items is not None:
        if not body.items:
            raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_NO_ITEMS, "A purchase order needs at least one item")
        await session.execute(
            text("DELETE FROM purchase_order_items WHERE purchase_order_id = :id AND company_id = :c"),
            {"id": po_id, "c": claims.company_id},
        )
        current = (
            await session.execute(
                text(
                    "SELECT supplier_id, delivery_godown_id, freight_amount, other_charges FROM purchase_orders WHERE id = :id"
                ),
                {"id": po_id},
            )
        ).mappings().first()
        supplier = (
            await session.execute(text("SELECT state_code FROM suppliers WHERE id = :id"), {"id": current["supplier_id"]})
        ).mappings().first()
        godown = (
            await session.execute(text("SELECT state_code FROM godowns WHERE id = :id"), {"id": current["delivery_godown_id"]})
        ).mappings().first()
        settings = (
            await session.execute(text("SELECT rounding_mode FROM company_settings WHERE company_id = :c"), {"c": claims.company_id})
        ).mappings().first()
        rounding_mode = (settings or {}).get("rounding_mode", "nearest")
        freight = body.freight_amount if body.freight_amount is not None else current["freight_amount"]
        other = body.other_charges if body.other_charges is not None else current["other_charges"]
        inter_state = is_inter_state(supplier["state_code"], godown["state_code"])

        totals = await _insert_items(
            session, company_id=claims.company_id, po_id=po_id, items=body.items, rounding_mode=rounding_mode,
            freight=freight, other_charges=other, is_inter_state=inter_state,
        )
        await session.execute(
            text(
                "UPDATE purchase_orders SET is_inter_state = :inter_state, subtotal = :subtotal, discount_amount = :discount, "
                "taxable_value = :taxable, cgst_amount = :cgst, sgst_amount = :sgst, igst_amount = :igst, "
                "cess_amount = :cess, freight_amount = :freight, other_charges = :other, round_off = :round_off, "
                "total_amount = :total WHERE id = :id"
            ),
            {
                "inter_state": inter_state,
                "subtotal": totals.subtotal,
                "discount": totals.discount_amount,
                "taxable": totals.taxable_value,
                "cgst": totals.cgst_amount,
                "sgst": totals.sgst_amount,
                "igst": totals.igst_amount,
                "cess": totals.cess_amount,
                "freight": totals.freight_amount,
                "other": totals.other_charges,
                "round_off": totals.round_off,
                "total": totals.total_amount,
                "id": po_id,
            },
        )
    elif body.freight_amount is not None or body.other_charges is not None or body.delivery_godown_id is not None:
        # Items unchanged: subtotal/discount/taxable_value/cess don't move.
        # Only the freight/other addenda and (if the godown changed) the
        # intra- vs inter-state tax split do.
        current = (
            await session.execute(
                text(
                    "SELECT supplier_id, delivery_godown_id, taxable_value, cgst_amount, sgst_amount, igst_amount, "
                    "cess_amount, freight_amount, other_charges FROM purchase_orders WHERE id = :id"
                ),
                {"id": po_id},
            )
        ).mappings().first()
        supplier = (
            await session.execute(text("SELECT state_code FROM suppliers WHERE id = :id"), {"id": current["supplier_id"]})
        ).mappings().first()
        godown = (
            await session.execute(text("SELECT state_code FROM godowns WHERE id = :id"), {"id": current["delivery_godown_id"]})
        ).mappings().first()
        settings = (
            await session.execute(text("SELECT rounding_mode FROM company_settings WHERE company_id = :c"), {"c": claims.company_id})
        ).mappings().first()
        rounding_mode = (settings or {}).get("rounding_mode", "nearest")

        inter_state = is_inter_state(supplier["state_code"], godown["state_code"] if godown else None)
        tax_total = D(current["cgst_amount"]) + D(current["sgst_amount"]) + D(current["igst_amount"])
        if inter_state:
            cgst, sgst, igst = Decimal("0"), Decimal("0"), tax_total
        else:
            half = (tax_total / Decimal(2)).quantize(Decimal("0.01"))
            cgst, sgst, igst = tax_total - half, half, Decimal("0")

        taxable_value = D(current["taxable_value"])
        cess_amount = D(current["cess_amount"])
        freight = D(current["freight_amount"])
        other = D(current["other_charges"])
        total_before_round = taxable_value + tax_total + cess_amount + freight + other
        from app.core.money import round_total

        total_amount = round_total(total_before_round, rounding_mode)
        round_off = (total_amount - total_before_round).quantize(Decimal("0.01"))

        await session.execute(
            text(
                "UPDATE purchase_orders SET is_inter_state = :inter_state, cgst_amount = :cgst, sgst_amount = :sgst, "
                "igst_amount = :igst, round_off = :round_off, total_amount = :total WHERE id = :id"
            ),
            {"inter_state": inter_state, "cgst": cgst, "sgst": sgst, "igst": igst, "round_off": round_off, "total": total_amount, "id": po_id},
        )

    after = await _load(session, company_id=claims.company_id, po_id=po_id)
    await audit.record(
        session, entity_type="purchase_order", action="updated", claims=claims, entity_id=po_id,
        entity_label=after["po_number"], before=before, after=after, request=request,
    )
    await session.commit()
    return after


def _assert_approval_ready(po: dict) -> None:
    """BR-PO-02."""
    if not po["items"]:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_NO_ITEMS, "A purchase order needs at least one item")
    for item in po["items"]:
        if float(item["quantity"]) <= 0 or float(item["unit_price"]) < 0:
            raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_BUSINESS_RULE_VIOLATION, "Every line needs quantity > 0 and unit_price >= 0")
    if not po["delivery_godown_id"] or not po["expected_delivery_date"] or not (po["total_amount"] and float(po["total_amount"]) > 0):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_BUSINESS_RULE_VIOLATION,
            "A delivery godown, an expected delivery date and a total greater than zero are required",
        )


async def submit_po(
    session: AsyncSession, *, claims: AccessTokenClaims, po_id: UUID, request: Optional[Request] = None
) -> dict:
    before = await _load(session, company_id=claims.company_id, po_id=po_id)
    if before["status"] != "draft":
        raise ApiError(status.HTTP_409_CONFLICT, CODE_INVALID_STATE_TRANSITION, f"Only draft POs can be submitted (current status: {before['status']})")

    supplier = (
        await session.execute(text("SELECT status FROM suppliers WHERE id = :id"), {"id": before["supplier_id"]})
    ).mappings().first()
    if not supplier or supplier["status"] != "active":
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_BUSINESS_RULE_VIOLATION, "Supplier must be active")

    _assert_approval_ready(before)

    await session.execute(
        text("UPDATE purchase_orders SET status = 'pending_approval', row_version = row_version + 1 WHERE id = :id"),
        {"id": po_id},
    )
    after = await _load(session, company_id=claims.company_id, po_id=po_id)
    await audit.record(
        session, entity_type="purchase_order", action="submitted", claims=claims, entity_id=po_id,
        entity_label=after["po_number"], before=before, after=after, request=request,
    )
    await session.commit()
    return after


async def approve_po(
    session: AsyncSession, *, claims: AccessTokenClaims, po_id: UUID, request: Optional[Request] = None
) -> dict:
    before = await _load(session, company_id=claims.company_id, po_id=po_id)
    if before["status"] != "pending_approval":
        raise ApiError(status.HTTP_409_CONFLICT, CODE_INVALID_STATE_TRANSITION, f"Only POs pending approval can be approved (current status: {before['status']})")

    settings = (
        await session.execute(
            text("SELECT require_po_approval_above, require_maker_checker FROM company_settings WHERE company_id = :c"),
            {"c": claims.company_id},
        )
    ).mappings().first() or {}
    threshold = settings.get("require_po_approval_above")
    if threshold is not None and float(before["total_amount"]) > float(threshold) and "po.approve_high_value" not in claims.permissions:
        # BR-PO-03
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            CODE_APPROVAL_LIMIT_EXCEEDED,
            f"This PO's total ({before['total_amount']}) exceeds your approval limit of {threshold}",
        )

    if settings.get("require_maker_checker"):
        creator_id = await audit.get_actor(session, entity_type="purchase_order", entity_id=po_id, action="created")
        if creator_id is not None and str(creator_id) == claims.user_id:
            raise ApiError(
                status.HTTP_403_FORBIDDEN,
                CODE_APPROVAL_LIMIT_EXCEEDED,
                "Maker-checker is enabled; the PO's creator cannot also approve it",
            )

    await session.execute(
        text(
            "UPDATE purchase_orders SET status = 'approved', approved_by = :approver, approved_at = now(), "
            "row_version = row_version + 1 WHERE id = :id"
        ),
        {"approver": claims.user_id, "id": po_id},
    )
    after = await _load(session, company_id=claims.company_id, po_id=po_id)
    await audit.record(
        session, entity_type="purchase_order", action="approved", claims=claims, entity_id=po_id,
        entity_label=after["po_number"], before=before, after=after, request=request,
    )
    await session.commit()
    return after


async def send_po(
    session: AsyncSession, *, claims: AccessTokenClaims, po_id: UUID, request: Optional[Request] = None
) -> dict:
    before = await _load(session, company_id=claims.company_id, po_id=po_id)
    if before["status"] != "approved":
        raise ApiError(status.HTTP_409_CONFLICT, CODE_INVALID_STATE_TRANSITION, f"Only approved POs can be sent (current status: {before['status']})")

    supplier = (
        await session.execute(text("SELECT email FROM suppliers WHERE id = :id"), {"id": before["supplier_id"]})
    ).mappings().first()

    await session.execute(
        text(
            "UPDATE purchase_orders SET status = 'sent', sent_at = now(), sent_to_email = :email, "
            "row_version = row_version + 1 WHERE id = :id"
        ),
        {"email": supplier["email"] if supplier else None, "id": po_id},
    )
    after = await _load(session, company_id=claims.company_id, po_id=po_id)
    await audit.record(
        session, entity_type="purchase_order", action="sent", claims=claims, entity_id=po_id,
        entity_label=after["po_number"], before=before, after=after, request=request,
    )
    await session.commit()
    return after


async def cancel_po(
    session: AsyncSession, *, claims: AccessTokenClaims, po_id: UUID, body: PoCancelRequest, request: Optional[Request] = None
) -> dict:
    before = await _load(session, company_id=claims.company_id, po_id=po_id)
    if before["status"] in ("cancelled", "closed"):
        raise ApiError(status.HTTP_409_CONFLICT, CODE_INVALID_STATE_TRANSITION, f"PO already {before['status']}")
    if before["status"] in ("partially_received", "received") or float(before["received_pct"] or 0) > 0:
        # BR-PO-07
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_PO_HAS_RECEIPTS, "This PO has confirmed receipts; short-close it instead of cancelling")

    await session.execute(
        text(
            "UPDATE purchase_orders SET status = 'cancelled', cancelled_at = now(), cancelled_by = :who, "
            "cancellation_reason = :reason, row_version = row_version + 1 WHERE id = :id"
        ),
        {"who": claims.user_id, "reason": body.reason, "id": po_id},
    )
    after = await _load(session, company_id=claims.company_id, po_id=po_id)
    await audit.record(
        session, entity_type="purchase_order", action="cancelled", claims=claims, entity_id=po_id,
        entity_label=after["po_number"], description=body.reason, before=before, after=after, request=request,
    )
    await session.commit()
    return after


async def close_po(
    session: AsyncSession, *, claims: AccessTokenClaims, po_id: UUID, body: PoCloseRequest, request: Optional[Request] = None
) -> dict:
    before = await _load(session, company_id=claims.company_id, po_id=po_id)
    if before["status"] not in ("approved", "sent", "acknowledged", "partially_received", "received"):
        raise ApiError(status.HTTP_409_CONFLICT, CODE_INVALID_STATE_TRANSITION, f"Cannot close a PO in status {before['status']}")

    await session.execute(
        text(
            "UPDATE purchase_order_items SET line_status = 'short_closed' "
            "WHERE purchase_order_id = :id AND line_status IN ('open', 'partially_received')"
        ),
        {"id": po_id},
    )
    await session.execute(
        text("UPDATE purchase_orders SET status = 'closed', row_version = row_version + 1 WHERE id = :id"), {"id": po_id}
    )
    after = await _load(session, company_id=claims.company_id, po_id=po_id)
    await audit.record(
        session, entity_type="purchase_order", action="closed", claims=claims, entity_id=po_id,
        entity_label=after["po_number"], description=body.reason, before=before, after=after, request=request,
    )
    await session.commit()
    return after


async def delete_po(
    session: AsyncSession, *, claims: AccessTokenClaims, po_id: UUID, request: Optional[Request] = None
) -> None:
    before = await _load(session, company_id=claims.company_id, po_id=po_id)
    if before["status"] != "draft":
        # BR-PO-10
        raise ApiError(status.HTTP_409_CONFLICT, CODE_INVALID_STATE_TRANSITION, f"Only draft POs can be deleted (current status: {before['status']}); cancel it instead")
    await session.execute(text("DELETE FROM purchase_orders WHERE id = :id AND company_id = :c"), {"id": po_id, "c": claims.company_id})
    await audit.record(
        session, entity_type="purchase_order", action="deleted", claims=claims, entity_id=po_id,
        entity_label=before["po_number"], before=before, request=request,
    )
    await session.commit()


async def recompute_receipt_state(session: AsyncSession, *, company_id: str, po_id: UUID) -> None:
    """BR-PO-05: PO status and `received_pct` are derived from its lines,
    never set by hand. Called after a GRN confirms or reverses receipts
    against this PO."""
    agg = (
        await session.execute(
            text(
                "SELECT COALESCE(SUM(quantity), 0) AS ordered, COALESCE(SUM(received_quantity), 0) AS received, "
                "COUNT(*) FILTER (WHERE line_status = 'received') AS received_lines, "
                "COUNT(*) FILTER (WHERE line_status IN ('short_closed', 'cancelled')) AS closed_lines, "
                "COUNT(*) AS total_lines "
                "FROM purchase_order_items WHERE purchase_order_id = :id AND company_id = :c"
            ),
            {"id": po_id, "c": company_id},
        )
    ).mappings().first()
    if not agg or agg["total_lines"] == 0:
        return

    ordered = Decimal(str(agg["ordered"]))
    received = Decimal(str(agg["received"]))
    received_pct = (received / ordered * Decimal(100)) if ordered > 0 else Decimal("0")

    current = (
        await session.execute(text("SELECT status FROM purchase_orders WHERE id = :id"), {"id": po_id})
    ).mappings().first()
    if current is None or current["status"] not in ("approved", "sent", "acknowledged", "partially_received", "received"):
        # Don't resurrect a cancelled/closed/draft PO's status from a
        # reversal recompute; received_pct on a closed PO is historical.
        await session.execute(
            text("UPDATE purchase_orders SET received_pct = :pct WHERE id = :id"), {"pct": received_pct, "id": po_id}
        )
        return

    fully_received = agg["received_lines"] + agg["closed_lines"] == agg["total_lines"] and agg["received_lines"] > 0
    if fully_received:
        await session.execute(
            text(
                "UPDATE purchase_orders SET status = 'received', received_pct = :pct, fully_received_at = now() "
                "WHERE id = :id"
            ),
            {"pct": received_pct, "id": po_id},
        )
    elif received > 0:
        await session.execute(
            text("UPDATE purchase_orders SET status = 'partially_received', received_pct = :pct WHERE id = :id"),
            {"pct": received_pct, "id": po_id},
        )
    else:
        await session.execute(
            text("UPDATE purchase_orders SET received_pct = :pct WHERE id = :id"), {"pct": received_pct, "id": po_id}
        )
