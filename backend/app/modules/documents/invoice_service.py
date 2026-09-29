"""
Supplier invoices and the 3-way match.

The match is the point of this module. An invoice on its own is a claim;
what makes it trustworthy is agreeing with two other documents written at
different times by different people:

* **invoice vs PO**  -- are we being charged the price we agreed?
* **invoice vs GRN** -- are we being charged for what actually arrived?

Either one alone is easy to satisfy and easy to abuse. Together they catch
the two common problems: a price that crept up after the order, and a
quantity billed that never came off the truck.

`match_status` is therefore derived, never set by hand: run the match and
it tells you what it found. The invoice is `matched` only when both
comparisons come back clean.
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
from app.core.db import set_tenant
from app.core.errors import (
    ApiError,
    CODE_BUSINESS_RULE_VIOLATION,
    CODE_DUPLICATE,
    CODE_INVALID_STATE_TRANSITION,
    CODE_INVOICE_DISPUTED,
    CODE_NOT_FOUND,
    CODE_STALE_RECORD,
    CODE_VARIANCE_EXCEEDS_TOLERANCE,
)
from app.core.money import D, document_totals, is_inter_state, line_amounts, round2
from app.core.security import AccessTokenClaims
from app.modules.documents import variance_service
from app.modules.documents.schemas import InvoiceCreate, InvoiceUpdate

# §14: INVOICE: draft -> under_review -> approved, with disputed and
# cancelled branches. `disputed` is deliberately reversible -- a dispute
# that is settled should be able to go back for approval rather than
# forcing a cancel-and-re-enter.
_ALLOWED_TRANSITIONS = {
    "draft": {"under_review", "cancelled"},
    "under_review": {"approved", "disputed", "cancelled"},
    "approved": {"disputed"},
    "disputed": {"under_review", "cancelled"},
    "cancelled": set(),
}

_EDITABLE = {"draft", "under_review"}


async def _load(session: AsyncSession, *, company_id: UUID, invoice_id: UUID) -> dict:
    header = (
        await session.execute(
            text(
                "SELECT si.*, COALESCE(s.name, '') AS supplier_name, po.po_number, gr.grn_number "
                "FROM supplier_invoices si "
                "LEFT JOIN suppliers s ON s.id = si.supplier_id AND s.company_id = si.company_id "
                "LEFT JOIN purchase_orders po ON po.id = si.purchase_order_id AND po.company_id = si.company_id "
                "LEFT JOIN goods_receipts gr ON gr.id = si.goods_receipt_id AND gr.company_id = si.company_id "
                "WHERE si.id = :id AND si.company_id = :c"
            ),
            {"id": invoice_id, "c": company_id},
        )
    ).mappings().first()
    if header is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Supplier invoice not found")

    items = (
        await session.execute(
            text(
                "SELECT ii.*, COALESCE(pv.sku, '') AS sku, COALESCE(u.code, '') AS uom_code "
                "FROM supplier_invoice_items ii "
                "LEFT JOIN product_variants pv ON pv.id = ii.product_variant_id AND pv.company_id = ii.company_id "
                "LEFT JOIN uoms u ON u.id = ii.uom_id "
                "WHERE ii.invoice_id = :id AND ii.company_id = :c ORDER BY ii.line_no"
            ),
            {"id": invoice_id, "c": company_id},
        )
    ).mappings().all()

    out = dict(header)
    out["items"] = [dict(i) for i in items]
    out["item_count"] = len(items)
    out["variances"] = await variance_service.list_variances(
        session, company_id=company_id, compare_doc_id=invoice_id
    )
    return out


async def list_invoices(
    session: AsyncSession,
    *,
    company_id: UUID,
    status_filter: Optional[str] = None,
    match_status: Optional[str] = None,
    payment_status: Optional[str] = None,
    supplier_id: Optional[UUID] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    where = ["si.company_id = :c"]
    params: dict = {"c": company_id}
    for column, value in (
        ("status", status_filter),
        ("match_status", match_status),
        ("payment_status", payment_status),
        ("supplier_id", supplier_id),
    ):
        if value:
            where.append(f"si.{column} = :{column}")
            params[column] = value

    rows = (
        await session.execute(
            text(
                "SELECT si.*, COALESCE(s.name, '') AS supplier_name, po.po_number, gr.grn_number, "
                "       (SELECT COUNT(*) FROM supplier_invoice_items ii "
                "         WHERE ii.invoice_id = si.id AND ii.company_id = si.company_id) AS item_count "
                "FROM supplier_invoices si "
                "LEFT JOIN suppliers s ON s.id = si.supplier_id AND s.company_id = si.company_id "
                "LEFT JOIN purchase_orders po ON po.id = si.purchase_order_id AND po.company_id = si.company_id "
                "LEFT JOIN goods_receipts gr ON gr.id = si.goods_receipt_id AND gr.company_id = si.company_id "
                f"WHERE {' AND '.join(where)} "
                "ORDER BY si.invoice_date DESC, si.invoice_number DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": limit, "offset": offset},
        )
    ).mappings().all()
    return [{**dict(r), "items": [], "variances": []} for r in rows]


async def get_invoice(session: AsyncSession, *, company_id: UUID, invoice_id: UUID) -> dict:
    return await _load(session, company_id=company_id, invoice_id=invoice_id)


async def _write_items(
    session: AsyncSession,
    *,
    company_id: UUID,
    invoice_id: UUID,
    items,
    inter_state: bool,
    freight: Decimal,
    other_charges: Decimal,
    rounding_mode: str,
):
    await session.execute(
        text("DELETE FROM supplier_invoice_items WHERE invoice_id = :id AND company_id = :c"),
        {"id": invoice_id, "c": company_id},
    )

    calcs, gross_lines = [], []
    for line_no, item in enumerate(items, start=1):
        amounts = line_amounts(
            quantity=D(item.quantity),
            unit_price=D(item.unit_price),
            discount_pct=D(item.discount_pct),
            gst_rate=D(item.gst_rate),
            cess_rate=D(item.cess_rate),
        )
        gross_lines.append(D(item.quantity) * D(item.unit_price))
        calcs.append(amounts)

        # Snapshots for the match: the PO rate this line was billed
        # against, and how far the billed quantity is from what the GRN
        # accepted. Both frozen on the row so the match's own evidence
        # cannot drift when the PO or GRN changes afterwards.
        po_price = None
        qty_variance = None
        if item.purchase_order_item_id:
            po_price = (
                await session.execute(
                    text(
                        "SELECT unit_price FROM purchase_order_items WHERE id = :id AND company_id = :c"
                    ),
                    {"id": item.purchase_order_item_id, "c": company_id},
                )
            ).scalar_one_or_none()
        if item.goods_receipt_item_id:
            accepted = (
                await session.execute(
                    text(
                        "SELECT accepted_quantity FROM goods_receipt_items WHERE id = :id AND company_id = :c"
                    ),
                    {"id": item.goods_receipt_item_id, "c": company_id},
                )
            ).scalar_one_or_none()
            if accepted is not None:
                qty_variance = round2(D(item.quantity) - D(accepted))

        variance_pct = (
            round2((D(item.unit_price) - D(po_price)) / D(po_price) * 100)
            if po_price is not None and D(po_price) != 0
            else None
        )

        description = item.description
        if not description and item.product_variant_id:
            description = (
                await session.execute(
                    text(
                        "SELECT TRIM(COALESCE(p.name, '') || ' ' || COALESCE(pv.variant_name, '')) "
                        "FROM product_variants pv JOIN products p ON p.id = pv.product_id "
                        "WHERE pv.id = :v AND pv.company_id = :c"
                    ),
                    {"v": item.product_variant_id, "c": company_id},
                )
            ).scalar_one_or_none()

        await session.execute(
            text(
                "INSERT INTO supplier_invoice_items "
                "(company_id, invoice_id, line_no, purchase_order_item_id, goods_receipt_item_id, "
                " product_variant_id, description, hsn_code, quantity, uom_id, unit_price, discount_pct, "
                " gst_rate, cess_rate, line_net, line_tax, line_total, po_unit_price_snapshot, "
                " price_variance_pct, qty_variance) "
                "VALUES (:c, :inv, :line_no, :po_item, :grn_item, :variant, :description, :hsn, :qty, :uom, "
                " :price, :disc, :gst, :cess, :net, :tax, :total, :po_price, :variance_pct, :qty_variance)"
            ),
            {
                "c": company_id,
                "inv": invoice_id,
                "line_no": line_no,
                "po_item": item.purchase_order_item_id,
                "grn_item": item.goods_receipt_item_id,
                "variant": item.product_variant_id,
                "description": description or "Item",
                "hsn": item.hsn_code,
                "qty": D(item.quantity),
                "uom": item.uom_id,
                "price": D(item.unit_price),
                "disc": D(item.discount_pct),
                "gst": D(item.gst_rate),
                "cess": D(item.cess_rate),
                "net": amounts.line_net,
                "tax": amounts.line_tax,
                "total": amounts.line_total,
                "po_price": po_price,
                "variance_pct": variance_pct,
                "qty_variance": qty_variance,
            },
        )

    return document_totals(
        lines=calcs,
        gross_lines=gross_lines,
        is_inter_state=inter_state,
        freight_amount=freight,
        other_charges=other_charges,
        rounding_mode=rounding_mode,
    )


async def create_invoice(
    session: AsyncSession, *, claims: AccessTokenClaims, body: InvoiceCreate, request: Optional[Request] = None
) -> dict:
    company_id = UUID(claims.company_id)

    clash = (
        await session.execute(
            text(
                "SELECT 1 FROM supplier_invoices WHERE company_id = :c AND supplier_id = :s "
                "AND lower(invoice_number) = lower(:n)"
            ),
            {"c": company_id, "s": body.supplier_id, "n": body.invoice_number},
        )
    ).first()
    if clash:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_DUPLICATE,
            "This supplier already has an invoice with that number",
            errors=[{"field": "invoice_number", "message": "Already recorded for this supplier"}],
        )

    supplier = (
        await session.execute(
            text(
                "SELECT id, name, state_code, gstin FROM suppliers "
                "WHERE id = :id AND company_id = :c AND deleted_at IS NULL"
            ),
            {"id": body.supplier_id, "c": company_id},
        )
    ).mappings().first()
    if supplier is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Supplier not found")

    if clock.is_future_day(body.invoice_date):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_BUSINESS_RULE_VIOLATION,
            "An invoice cannot be dated in the future",
        )

    # Place of supply follows the receiving godown, same as the PO — it is
    # what decides CGST+SGST against IGST.
    place_of_supply = None
    if body.goods_receipt_id:
        place_of_supply = (
            await session.execute(
                text(
                    "SELECT g.state_code FROM goods_receipts gr "
                    "JOIN godowns g ON g.id = gr.godown_id AND g.company_id = gr.company_id "
                    "WHERE gr.id = :id AND gr.company_id = :c"
                ),
                {"id": body.goods_receipt_id, "c": company_id},
            )
        ).scalar_one_or_none()
    elif body.purchase_order_id:
        place_of_supply = (
            await session.execute(
                text(
                    "SELECT g.state_code FROM purchase_orders po "
                    "JOIN godowns g ON g.id = po.delivery_godown_id AND g.company_id = po.company_id "
                    "WHERE po.id = :id AND po.company_id = :c"
                ),
                {"id": body.purchase_order_id, "c": company_id},
            )
        ).scalar_one_or_none()

    inter_state = is_inter_state(supplier["state_code"], place_of_supply) if place_of_supply else False
    rounding_mode = (
        await session.execute(
            text("SELECT COALESCE(rounding_mode, 'nearest') FROM company_settings WHERE company_id = :c"),
            {"c": company_id},
        )
    ).scalar_one_or_none() or "nearest"

    invoice_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO supplier_invoices "
            "(id, company_id, invoice_number, invoice_date, supplier_id, purchase_order_id, goods_receipt_id, "
            " supplier_gstin, place_of_supply_state_code, is_inter_state, invoice_type, tds_amount, due_date, "
            " eway_bill_number, irn, status, match_status, payment_status) "
            # `tax_invoice` is the schema's vocabulary for an ordinary GST
            # purchase invoice (the CHECK allows tax_invoice, bill_of_supply,
            # debit_note, credit_note). Debit and credit notes are the same
            # table with a different type, which is how a purchase return's
            # debit note will land here later without a new table.
            "VALUES (:id, :c, :number, :inv_date, :supplier, :po, :grn, :gstin, :place, :inter, 'tax_invoice', "
            " :tds, :due, :eway, :irn, 'draft', 'unmatched', 'unpaid')"
        ),
        {
            "id": invoice_id,
            "c": company_id,
            "number": body.invoice_number,
            "inv_date": body.invoice_date,
            "supplier": body.supplier_id,
            "po": body.purchase_order_id,
            "grn": body.goods_receipt_id,
            "gstin": body.supplier_gstin or supplier["gstin"],
            "place": place_of_supply,
            "inter": inter_state,
            "tds": D(body.tds_amount),
            "due": body.due_date,
            "eway": body.eway_bill_number,
            "irn": body.irn,
        },
    )

    totals = await _write_items(
        session,
        company_id=company_id,
        invoice_id=invoice_id,
        items=body.items,
        inter_state=inter_state,
        freight=D(body.freight_amount),
        other_charges=D(body.other_charges),
        rounding_mode=rounding_mode,
    )
    await _save_totals(session, company_id=company_id, invoice_id=invoice_id, totals=totals)

    await audit.record(
        session,
        entity_type="supplier_invoice",
        action="created",
        claims=claims,
        entity_id=invoice_id,
        entity_label=body.invoice_number,
        description=f"{len(body.items)} line(s), total {totals.total_amount}",
        after={"total_amount": str(totals.total_amount), "supplier_id": str(body.supplier_id)},
        request=request,
    )
    await session.commit()
    await set_tenant(session, company_id)
    return await _load(session, company_id=company_id, invoice_id=invoice_id)


async def _save_totals(session: AsyncSession, *, company_id: UUID, invoice_id: UUID, totals) -> None:
    await session.execute(
        text(
            "UPDATE supplier_invoices SET subtotal = :subtotal, discount_amount = :discount, "
            " taxable_value = :taxable, cgst_amount = :cgst, sgst_amount = :sgst, igst_amount = :igst, "
            " cess_amount = :cess, freight_amount = :freight, other_charges = :other, round_off = :round_off, "
            " total_amount = :total WHERE id = :id AND company_id = :c"
        ),
        {
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
            "id": invoice_id,
            "c": company_id,
        },
    )


async def update_invoice(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    invoice_id: UUID,
    body: InvoiceUpdate,
    request: Optional[Request] = None,
) -> dict:
    company_id = UUID(claims.company_id)
    before = await _load(session, company_id=company_id, invoice_id=invoice_id)

    if before["status"] not in _EDITABLE:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_INVALID_STATE_TRANSITION,
            f"An invoice in status {before['status']} can no longer be edited",
        )
    if body.row_version != before["row_version"]:
        raise ApiError(
            status.HTTP_409_CONFLICT, CODE_STALE_RECORD, "This invoice was changed by someone else; reload and retry"
        )

    header_fields = body.model_dump(exclude_unset=True, exclude={"items", "row_version"})
    if header_fields:
        assignments = ", ".join(f"{k} = :{k}" for k in header_fields)
        await session.execute(
            text(
                f"UPDATE supplier_invoices SET {assignments}, row_version = row_version + 1 "
                "WHERE id = :id AND company_id = :c"
            ),
            {**header_fields, "id": invoice_id, "c": company_id},
        )
    else:
        await session.execute(
            text("UPDATE supplier_invoices SET row_version = row_version + 1 WHERE id = :id AND company_id = :c"),
            {"id": invoice_id, "c": company_id},
        )

    if body.items is not None:
        rounding_mode = (
            await session.execute(
                text("SELECT COALESCE(rounding_mode, 'nearest') FROM company_settings WHERE company_id = :c"),
                {"c": company_id},
            )
        ).scalar_one_or_none() or "nearest"
        totals = await _write_items(
            session,
            company_id=company_id,
            invoice_id=invoice_id,
            items=body.items,
            inter_state=bool(before["is_inter_state"]),
            freight=D(body.freight_amount if body.freight_amount is not None else before["freight_amount"]),
            other_charges=D(body.other_charges if body.other_charges is not None else before["other_charges"]),
            rounding_mode=rounding_mode,
        )
        await _save_totals(session, company_id=company_id, invoice_id=invoice_id, totals=totals)
        # The lines changed, so any previous match verdict is stale. Saying
        # "unmatched" is honest; leaving "matched" on an edited invoice
        # would be a lie the approval step then trusts.
        await session.execute(
            text("UPDATE supplier_invoices SET match_status = 'unmatched' WHERE id = :id AND company_id = :c"),
            {"id": invoice_id, "c": company_id},
        )

    await audit.record(
        session,
        entity_type="supplier_invoice",
        action="updated",
        claims=claims,
        entity_id=invoice_id,
        entity_label=before["invoice_number"],
        request=request,
    )
    await session.commit()
    await set_tenant(session, company_id)
    return await _load(session, company_id=company_id, invoice_id=invoice_id)


async def run_match(
    session: AsyncSession, *, claims: AccessTokenClaims, invoice_id: UUID, request: Optional[Request] = None
) -> dict:
    """The 3-way match. Re-runnable: each run replaces its own open findings."""
    company_id = UUID(claims.company_id)
    invoice = await _load(session, company_id=company_id, invoice_id=invoice_id)

    po_id = invoice["purchase_order_id"]
    grn_id = invoice["goods_receipt_id"]
    if not po_id and not grn_id:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_BUSINESS_RULE_VIOLATION,
            "This invoice is not linked to a purchase order or a goods receipt, so there is nothing to match it against",
        )

    po_findings: list[variance_service.Finding] = []
    grn_findings: list[variance_service.Finding] = []

    for line in invoice["items"]:
        if line["po_unit_price_snapshot"] is not None:
            po_findings.append(
                variance_service.Finding(
                    variance_type="price",
                    base_value=D(line["po_unit_price_snapshot"]),
                    compare_value=D(line["unit_price"]),
                    product_variant_id=line["product_variant_id"],
                    base_line_id=line["purchase_order_item_id"],
                    compare_line_id=line["id"],
                )
            )
        if line["qty_variance"] is not None and D(line["qty_variance"]) != 0:
            received = D(line["quantity"]) - D(line["qty_variance"])
            grn_findings.append(
                variance_service.Finding(
                    variance_type="quantity",
                    base_value=received,
                    compare_value=D(line["quantity"]),
                    product_variant_id=line["product_variant_id"],
                    base_line_id=line["goods_receipt_item_id"],
                    compare_line_id=line["id"],
                )
            )

    # Header check: what these lines *should* have cost at the agreed rates,
    # against what is being charged for them.
    #
    # Deliberately NOT the PO's own total. An invoice for a partial delivery
    # legitimately bills less than the whole order -- comparing it to the
    # full PO total flags every honest partial invoice as a variance, which
    # is how the first cut of this match reported a perfectly correct
    # invoice as `variance` with -1180. Under-delivery is already told
    # truthfully by the quantity comparison against the GRN; this line is
    # only about price.
    priced_lines = [ln for ln in invoice["items"] if ln["po_unit_price_snapshot"] is not None]
    if po_id and priced_lines and len(priced_lines) == len(invoice["items"]):
        expected_net = round2(
            sum((D(ln["po_unit_price_snapshot"]) * D(ln["quantity"]) for ln in priced_lines), Decimal("0"))
        )
        billed_net = round2(sum((D(ln["line_net"]) for ln in invoice["items"]), Decimal("0")))
        po_findings.append(
            variance_service.Finding(
                variance_type="total", base_value=expected_net, compare_value=billed_net
            )
        )

    written = []
    if po_id:
        written += await variance_service.record_variances(
            session,
            company_id=company_id,
            comparison_kind="invoice_vs_po",
            base_doc_type="purchase_order",
            base_doc_id=po_id,
            compare_doc_type="supplier_invoice",
            compare_doc_id=invoice_id,
            findings=po_findings,
        )
    if grn_id:
        written += await variance_service.record_variances(
            session,
            company_id=company_id,
            comparison_kind="invoice_vs_grn",
            base_doc_type="goods_receipt",
            base_doc_id=grn_id,
            compare_doc_type="supplier_invoice",
            compare_doc_id=invoice_id,
            findings=grn_findings,
        )

    # `matched` means both available comparisons came back clean. An
    # invoice linked only to a PO can still be `matched` -- against what it
    # has -- and `matched_against_grn` says plainly that the second leg was
    # not checked, rather than implying a verification that never happened.
    match_status = "variance" if written else "matched"
    variance_amount = round2(sum((D(w["difference"]) for w in written if w["variance_type"] == "total"), Decimal("0")))

    await session.execute(
        text(
            "UPDATE supplier_invoices SET match_status = :ms, variance_amount = :va "
            "WHERE id = :id AND company_id = :c"
        ),
        {"ms": match_status, "va": variance_amount, "id": invoice_id, "c": company_id},
    )

    await audit.record(
        session,
        entity_type="supplier_invoice",
        action="status_changed",
        claims=claims,
        entity_id=invoice_id,
        entity_label=invoice["invoice_number"],
        description=f"3-way match: {match_status} ({len(written)} variance(s))",
        after={"match_status": match_status},
        request=request,
    )
    await session.commit()
    await set_tenant(session, company_id)

    return {
        "invoice_id": invoice_id,
        "match_status": match_status,
        "matched_against_po": bool(po_id),
        "matched_against_grn": bool(grn_id),
        "variance_amount": variance_amount,
        "variances": await variance_service.list_variances(
            session, company_id=company_id, compare_doc_id=invoice_id
        ),
    }


async def set_status(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    invoice_id: UUID,
    new_status: str,
    note: Optional[str] = None,
    request: Optional[Request] = None,
) -> dict:
    company_id = UUID(claims.company_id)
    before = await _load(session, company_id=company_id, invoice_id=invoice_id)
    current = before["status"]

    if new_status not in _ALLOWED_TRANSITIONS.get(current, set()):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_INVALID_STATE_TRANSITION,
            f"An invoice cannot go from {current} to {new_status}",
        )

    if new_status == "approved":
        # Approving an invoice releases money, so it gets the stricter of
        # the two gates: it must have been matched at all, and any open
        # beyond-tolerance variance blocks it.
        if before["match_status"] == "unmatched":
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                CODE_BUSINESS_RULE_VIOLATION,
                "Run the 3-way match before approving this invoice for payment",
            )
        if await variance_service.exceeds_tolerance(session, company_id=company_id, compare_doc_id=invoice_id):
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                CODE_VARIANCE_EXCEEDS_TOLERANCE,
                "This invoice has unresolved variances beyond tolerance; resolve them before approving for payment",
            )

    sets = ["status = :status"]
    params: dict = {"status": new_status, "id": invoice_id, "c": company_id}
    if new_status == "approved":
        sets += ["approved_by = :who", "approved_at = now()"]
        params["who"] = UUID(claims.user_id)

    await session.execute(
        text(f"UPDATE supplier_invoices SET {', '.join(sets)} WHERE id = :id AND company_id = :c"), params
    )
    await audit.record(
        session,
        entity_type="supplier_invoice",
        action="approved" if new_status == "approved" else "status_changed",
        claims=claims,
        entity_id=invoice_id,
        entity_label=before["invoice_number"],
        description=note,
        before={"status": current},
        after={"status": new_status},
        request=request,
    )
    await session.commit()
    await set_tenant(session, company_id)
    return await _load(session, company_id=company_id, invoice_id=invoice_id)


async def record_payment(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    invoice_id: UUID,
    amount: Decimal,
    request: Optional[Request] = None,
) -> dict:
    company_id = UUID(claims.company_id)
    before = await _load(session, company_id=company_id, invoice_id=invoice_id)

    if before["status"] == "disputed":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_INVOICE_DISPUTED,
            "This invoice is disputed; settle the dispute before recording a payment against it",
        )
    if before["status"] != "approved":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_INVALID_STATE_TRANSITION,
            f"Only an approved invoice can be paid (this one is {before['status']})",
        )

    already = D(before["amount_paid"] or 0)
    total = D(before["total_amount"])
    new_paid = round2(already + D(amount))
    if new_paid > total:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_BUSINESS_RULE_VIOLATION,
            f"That would pay {new_paid} against an invoice of {total}",
            errors=[{"field": "amount", "message": f"At most {round2(total - already)} remains"}],
        )

    payment_status = "paid" if new_paid >= total else "partially_paid"
    await session.execute(
        text(
            "UPDATE supplier_invoices SET amount_paid = :paid, payment_status = :ps "
            "WHERE id = :id AND company_id = :c"
        ),
        {"paid": new_paid, "ps": payment_status, "id": invoice_id, "c": company_id},
    )
    await audit.record(
        session,
        entity_type="supplier_invoice",
        action="status_changed",
        claims=claims,
        entity_id=invoice_id,
        entity_label=before["invoice_number"],
        description=f"Payment of {amount} recorded ({payment_status})",
        before={"amount_paid": str(already)},
        after={"amount_paid": str(new_paid), "payment_status": payment_status},
        request=request,
    )
    await session.commit()
    await set_tenant(session, company_id)
    return await _load(session, company_id=company_id, invoice_id=invoice_id)
