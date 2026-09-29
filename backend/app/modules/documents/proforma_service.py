"""
Proforma invoices -- `06_BUSINESS_RULES.md` §8.

BR-PF-01 is the rule that shapes everything else: **a proforma is not a tax
invoice.** It never grants input tax credit and never touches inventory. So
there is no confirm step here that posts anything, and no path from this
module into `core/inventory`. It is a request for money against an order,
and the only question worth asking of it is whether it matches what was
agreed.

That question is BR-PF-02/03, and it is why the PO's total and each line's
rate are *snapshotted* when the proforma is linked. Comparing against the
live PO later would quietly re-baseline every variance the moment someone
edited the order -- the snapshot is what makes "they billed more than we
agreed" still true tomorrow.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from fastapi import Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.db import set_tenant
from app.core.errors import (
    ApiError,
    CODE_BUSINESS_RULE_VIOLATION,
    CODE_DUPLICATE,
    CODE_INVALID_STATE_TRANSITION,
    CODE_NOT_FOUND,
    CODE_STALE_RECORD,
    CODE_VARIANCE_EXCEEDS_TOLERANCE,
)
from app.core.money import D, document_totals, is_inter_state, line_amounts, round2
from app.core.security import AccessTokenClaims
from app.modules.documents import variance_service
from app.modules.documents.schemas import ProformaCreate, ProformaUpdate

# BR-PF: the proforma state machine from §14.
_ALLOWED_TRANSITIONS = {
    "pending": {"under_review", "approved", "rejected", "cancelled"},
    "under_review": {"approved", "rejected", "cancelled"},
    "approved": {"paid", "cancelled"},
    "paid": {"completed"},
    "completed": set(),
    "rejected": set(),
    "cancelled": set(),
}

_EDITABLE = {"pending", "under_review"}


async def _load(session: AsyncSession, *, company_id: UUID, proforma_id: UUID) -> dict:
    header = (
        await session.execute(
            text(
                "SELECT pf.*, COALESCE(s.name, '') AS supplier_name, po.po_number "
                "FROM proforma_invoices pf "
                "LEFT JOIN suppliers s ON s.id = pf.supplier_id AND s.company_id = pf.company_id "
                "LEFT JOIN purchase_orders po ON po.id = pf.purchase_order_id AND po.company_id = pf.company_id "
                "WHERE pf.id = :id AND pf.company_id = :c"
            ),
            {"id": proforma_id, "c": company_id},
        )
    ).mappings().first()
    if header is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Proforma invoice not found")

    items = (
        await session.execute(
            text(
                "SELECT pi.*, COALESCE(pv.sku, '') AS sku, COALESCE(u.code, '') AS uom_code "
                "FROM proforma_invoice_items pi "
                "LEFT JOIN product_variants pv ON pv.id = pi.product_variant_id AND pv.company_id = pi.company_id "
                "LEFT JOIN uoms u ON u.id = pi.uom_id "
                "WHERE pi.proforma_id = :id AND pi.company_id = :c ORDER BY pi.line_no"
            ),
            {"id": proforma_id, "c": company_id},
        )
    ).mappings().all()

    variances = await variance_service.list_variances(
        session, company_id=company_id, compare_doc_id=proforma_id
    )

    out = dict(header)
    out["items"] = [dict(i) for i in items]
    out["item_count"] = len(items)
    out["variances"] = variances
    return out


async def list_proformas(
    session: AsyncSession,
    *,
    company_id: UUID,
    status_filter: Optional[str] = None,
    supplier_id: Optional[UUID] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    where = ["pf.company_id = :c"]
    params: dict = {"c": company_id}
    if status_filter:
        where.append("pf.status = :status_filter")
        params["status_filter"] = status_filter
    if supplier_id:
        where.append("pf.supplier_id = :supplier_id")
        params["supplier_id"] = supplier_id

    rows = (
        await session.execute(
            text(
                "SELECT pf.*, COALESCE(s.name, '') AS supplier_name, po.po_number, "
                "       (SELECT COUNT(*) FROM proforma_invoice_items pi "
                "         WHERE pi.proforma_id = pf.id AND pi.company_id = pf.company_id) AS item_count "
                "FROM proforma_invoices pf "
                "LEFT JOIN suppliers s ON s.id = pf.supplier_id AND s.company_id = pf.company_id "
                "LEFT JOIN purchase_orders po ON po.id = pf.purchase_order_id AND po.company_id = pf.company_id "
                f"WHERE {' AND '.join(where)} "
                "ORDER BY pf.proforma_date DESC, pf.proforma_number DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": limit, "offset": offset},
        )
    ).mappings().all()
    # Items and variances are deliberately not hydrated on the list -- that
    # is an N+1 fan-out over every proforma just to show a count, and the
    # count is a cheap subquery instead.
    return [{**dict(r), "items": [], "variances": []} for r in rows]


async def get_proforma(session: AsyncSession, *, company_id: UUID, proforma_id: UUID) -> dict:
    return await _load(session, company_id=company_id, proforma_id=proforma_id)


async def _po_snapshot(session: AsyncSession, *, company_id: UUID, po_id: UUID) -> tuple[Decimal, dict]:
    """The PO total and its per-line rates, frozen at link time (BR-PF-02)."""
    po = (
        await session.execute(
            text("SELECT id, total_amount, status FROM purchase_orders WHERE id = :id AND company_id = :c"),
            {"id": po_id, "c": company_id},
        )
    ).mappings().first()
    if po is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Purchase order not found")

    lines = (
        await session.execute(
            text(
                "SELECT id, product_variant_id, quantity, unit_price FROM purchase_order_items "
                "WHERE purchase_order_id = :id AND company_id = :c"
            ),
            {"id": po_id, "c": company_id},
        )
    ).mappings().all()
    by_line = {r["id"]: dict(r) for r in lines}
    return D(po["total_amount"]), by_line


async def _write_items(
    session: AsyncSession,
    *,
    company_id: UUID,
    proforma_id: UUID,
    items,
    po_lines: dict,
    inter_state: bool,
    freight: Decimal,
    other_charges: Decimal,
    rounding_mode: str,
):
    await session.execute(
        text("DELETE FROM proforma_invoice_items WHERE proforma_id = :id AND company_id = :c"),
        {"id": proforma_id, "c": company_id},
    )

    calcs, gross_lines = [], []
    for line_no, item in enumerate(items, start=1):
        amounts = line_amounts(
            quantity=D(item.quantity),
            unit_price=D(item.unit_price),
            discount_pct=Decimal("0"),
            gst_rate=D(item.gst_rate),
            cess_rate=D(item.cess_rate),
        )
        gross_lines.append(D(item.quantity) * D(item.unit_price))
        calcs.append(amounts)

        # BR-PF-02: the PO rate is copied onto the line, not looked up
        # later. `price_variance_pct` is then a fact about this document
        # rather than a live comparison that moves when the PO is edited.
        po_line = po_lines.get(item.purchase_order_item_id) if item.purchase_order_item_id else None
        po_price = D(po_line["unit_price"]) if po_line else None
        variance_pct = (
            round2((D(item.unit_price) - po_price) / po_price * 100) if po_price and po_price != 0 else None
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
                "INSERT INTO proforma_invoice_items "
                "(company_id, proforma_id, line_no, purchase_order_item_id, product_variant_id, description, "
                " hsn_code, quantity, uom_id, unit_price, gst_rate, cess_rate, line_net, line_tax, line_total, "
                " po_unit_price_snapshot, price_variance_pct) "
                "VALUES (:c, :pf, :line_no, :po_item, :variant, :description, :hsn, :qty, :uom, :price, "
                " :gst, :cess, :net, :tax, :total, :po_price, :variance_pct)"
            ),
            {
                "c": company_id,
                "pf": proforma_id,
                "line_no": line_no,
                "po_item": item.purchase_order_item_id,
                "variant": item.product_variant_id,
                "description": description or "Item",
                "hsn": item.hsn_code,
                "qty": D(item.quantity),
                "uom": item.uom_id,
                "price": D(item.unit_price),
                "gst": D(item.gst_rate),
                "cess": D(item.cess_rate),
                "net": amounts.line_net,
                "tax": amounts.line_tax,
                "total": amounts.line_total,
                "po_price": po_price,
                "variance_pct": variance_pct,
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


def _check_advance(total: Decimal, advance_percent, advance_amount) -> None:
    """BR-PF-04: the advance cannot exceed the proforma total."""
    if advance_amount is not None and D(advance_amount) > total:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_BUSINESS_RULE_VIOLATION,
            f"Advance of {advance_amount} is more than the proforma total of {total}",
            errors=[{"field": "advance_amount", "message": "Cannot exceed the total"}],
        )
    if advance_percent is not None and D(advance_percent) > 100:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_BUSINESS_RULE_VIOLATION,
            "Advance percentage cannot exceed 100%",
            errors=[{"field": "advance_percent", "message": "Cannot exceed 100"}],
        )


async def _record_po_variance(
    session: AsyncSession, *, company_id: UUID, proforma_id: UUID, po_id: UUID, po_total: Decimal, pf_total: Decimal
) -> None:
    """BR-PF-03 plus BR-PF-05, in one pass.

    Line-level price differences come from the snapshots already on the
    lines. The header-level check is against the PO total *less what other
    proformas already claim against it* -- BR-PF-05's "combined value is
    checked against the PO total", which a naive per-proforma comparison
    would miss entirely when a supplier splits one order across three
    proformas that are each individually under the total.
    """
    lines = (
        await session.execute(
            text(
                "SELECT id, product_variant_id, quantity, unit_price, po_unit_price_snapshot "
                "FROM proforma_invoice_items WHERE proforma_id = :id AND company_id = :c"
            ),
            {"id": proforma_id, "c": company_id},
        )
    ).mappings().all()

    findings = [
        variance_service.Finding(
            variance_type="price",
            base_value=D(line["po_unit_price_snapshot"]),
            compare_value=D(line["unit_price"]),
            product_variant_id=line["product_variant_id"],
            compare_line_id=line["id"],
        )
        for line in lines
        if line["po_unit_price_snapshot"] is not None
    ]

    others = (
        await session.execute(
            text(
                "SELECT COALESCE(SUM(total_amount), 0) FROM proforma_invoices "
                "WHERE company_id = :c AND purchase_order_id = :po AND id <> :self "
                "AND status NOT IN ('rejected', 'cancelled')"
            ),
            {"c": company_id, "po": po_id, "self": proforma_id},
        )
    ).scalar_one()
    combined = D(others) + pf_total
    findings.append(
        variance_service.Finding(variance_type="total", base_value=po_total, compare_value=combined)
    )

    await variance_service.record_variances(
        session,
        company_id=company_id,
        comparison_kind="proforma_vs_po",
        base_doc_type="purchase_order",
        base_doc_id=po_id,
        compare_doc_type="proforma_invoice",
        compare_doc_id=proforma_id,
        findings=findings,
    )
    # `proforma_invoices.variance_amount` is a GENERATED ALWAYS column
    # (`total_amount - po_total_snapshot`) — the schema already keeps this
    # document's own variance in step with its total, so there is nothing to
    # write here. The combined-value figure above is deliberately *not*
    # forced into it: that column means "this proforma vs the PO", and
    # overwriting it with a cross-document total would make the same field
    # mean two different things depending on how many proformas exist.


async def create_proforma(
    session: AsyncSession, *, claims: AccessTokenClaims, body: ProformaCreate, request: Optional[Request] = None
) -> dict:
    company_id = UUID(claims.company_id)

    clash = (
        await session.execute(
            text(
                "SELECT 1 FROM proforma_invoices WHERE company_id = :c AND supplier_id = :s "
                "AND lower(proforma_number) = lower(:n)"
            ),
            {"c": company_id, "s": body.supplier_id, "n": body.proforma_number},
        )
    ).first()
    if clash:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_DUPLICATE,
            "This supplier already has a proforma with that number",
            errors=[{"field": "proforma_number", "message": "Already recorded for this supplier"}],
        )

    supplier = (
        await session.execute(
            text("SELECT id, name, state_code, gstin FROM suppliers WHERE id = :id AND company_id = :c AND deleted_at IS NULL"),
            {"id": body.supplier_id, "c": company_id},
        )
    ).mappings().first()
    if supplier is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Supplier not found")

    po_total, po_lines = (Decimal("0"), {})
    place_of_supply = None
    if body.purchase_order_id:
        po_total, po_lines = await _po_snapshot(session, company_id=company_id, po_id=body.purchase_order_id)
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

    proforma_id = uuid4()
    proforma_date = body.proforma_date or date.today()

    # Header first with placeholder totals: the item rows carry a NOT NULL
    # FK back to it, so they cannot be inserted before it exists. Same
    # ordering the PO and GRN services settled on.
    await session.execute(
        text(
            "INSERT INTO proforma_invoices "
            "(id, company_id, proforma_number, supplier_id, purchase_order_id, proforma_date, valid_until, "
            " place_of_supply_state_code, is_inter_state, advance_percent, advance_amount, payment_instructions, "
            " bank_name, bank_account_no, bank_ifsc, bank_branch, supplier_gstin_snapshot, "
            " po_total_snapshot, status) "
            "VALUES (:id, :c, :number, :supplier, :po, :pf_date, :valid_until, :place, :inter, "
            " :adv_pct, :adv_amt, :pay_instr, :bank, :acct, :ifsc, :branch, :gstin, :po_total, 'pending')"
        ),
        {
            "id": proforma_id,
            "c": company_id,
            "number": body.proforma_number,
            "supplier": body.supplier_id,
            "po": body.purchase_order_id,
            "pf_date": proforma_date,
            "valid_until": body.valid_until,
            "place": place_of_supply,
            "inter": inter_state,
            "adv_pct": body.advance_percent,
            "adv_amt": body.advance_amount,
            "pay_instr": body.payment_instructions,
            "bank": body.bank_name,
            "acct": body.bank_account_no,
            "ifsc": body.bank_ifsc,
            "branch": body.bank_branch,
            "gstin": supplier["gstin"],
            "po_total": po_total if body.purchase_order_id else None,
        },
    )

    totals = await _write_items(
        session,
        company_id=company_id,
        proforma_id=proforma_id,
        items=body.items,
        po_lines=po_lines,
        inter_state=inter_state,
        freight=D(body.freight_amount),
        other_charges=D(body.other_charges),
        rounding_mode=rounding_mode,
    )
    _check_advance(totals.total_amount, body.advance_percent, body.advance_amount)

    await session.execute(
        text(
            "UPDATE proforma_invoices SET subtotal = :subtotal, discount_amount = :discount, "
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
            "id": proforma_id,
            "c": company_id,
        },
    )

    if body.purchase_order_id:
        await _record_po_variance(
            session,
            company_id=company_id,
            proforma_id=proforma_id,
            po_id=body.purchase_order_id,
            po_total=po_total,
            pf_total=totals.total_amount,
        )

    await audit.record(
        session,
        entity_type="proforma_invoice",
        action="created",
        claims=claims,
        entity_id=proforma_id,
        entity_label=body.proforma_number,
        description=f"{len(body.items)} line(s), total {totals.total_amount}",
        after={"total_amount": str(totals.total_amount), "supplier_id": str(body.supplier_id)},
        request=request,
    )
    await session.commit()
    await set_tenant(session, company_id)  # commit ends the RLS-scoped transaction
    return await _load(session, company_id=company_id, proforma_id=proforma_id)


async def update_proforma(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    proforma_id: UUID,
    body: ProformaUpdate,
    request: Optional[Request] = None,
) -> dict:
    company_id = UUID(claims.company_id)
    before = await _load(session, company_id=company_id, proforma_id=proforma_id)

    if before["status"] not in _EDITABLE:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_INVALID_STATE_TRANSITION,
            f"A proforma in status {before['status']} can no longer be edited",
        )
    if body.row_version != before["row_version"]:
        raise ApiError(
            status.HTTP_409_CONFLICT, CODE_STALE_RECORD, "This proforma was changed by someone else; reload and retry"
        )

    header_fields = body.model_dump(exclude_unset=True, exclude={"items", "row_version"})
    if header_fields:
        assignments = ", ".join(f"{k} = :{k}" for k in header_fields)
        await session.execute(
            text(
                f"UPDATE proforma_invoices SET {assignments}, row_version = row_version + 1 "
                "WHERE id = :id AND company_id = :c"
            ),
            {**header_fields, "id": proforma_id, "c": company_id},
        )
    else:
        await session.execute(
            text("UPDATE proforma_invoices SET row_version = row_version + 1 WHERE id = :id AND company_id = :c"),
            {"id": proforma_id, "c": company_id},
        )

    if body.items is not None:
        po_total, po_lines = (Decimal("0"), {})
        if before["purchase_order_id"]:
            po_total, po_lines = await _po_snapshot(
                session, company_id=company_id, po_id=before["purchase_order_id"]
            )
        rounding_mode = (
            await session.execute(
                text("SELECT COALESCE(rounding_mode, 'nearest') FROM company_settings WHERE company_id = :c"),
                {"c": company_id},
            )
        ).scalar_one_or_none() or "nearest"

        freight = D(body.freight_amount if body.freight_amount is not None else before["freight_amount"])
        other = D(body.other_charges if body.other_charges is not None else before["other_charges"])

        totals = await _write_items(
            session,
            company_id=company_id,
            proforma_id=proforma_id,
            items=body.items,
            po_lines=po_lines,
            inter_state=bool(before["is_inter_state"]),
            freight=freight,
            other_charges=other,
            rounding_mode=rounding_mode,
        )
        _check_advance(
            totals.total_amount,
            body.advance_percent if body.advance_percent is not None else before["advance_percent"],
            body.advance_amount if body.advance_amount is not None else before["advance_amount"],
        )
        await session.execute(
            text(
                "UPDATE proforma_invoices SET subtotal = :subtotal, discount_amount = :discount, "
                " taxable_value = :taxable, cgst_amount = :cgst, sgst_amount = :sgst, igst_amount = :igst, "
                " cess_amount = :cess, freight_amount = :freight, other_charges = :other, "
                " round_off = :round_off, total_amount = :total WHERE id = :id AND company_id = :c"
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
                "id": proforma_id,
                "c": company_id,
            },
        )
        if before["purchase_order_id"]:
            await _record_po_variance(
                session,
                company_id=company_id,
                proforma_id=proforma_id,
                po_id=before["purchase_order_id"],
                po_total=po_total,
                pf_total=totals.total_amount,
            )

    await audit.record(
        session,
        entity_type="proforma_invoice",
        action="updated",
        claims=claims,
        entity_id=proforma_id,
        entity_label=before["proforma_number"],
        request=request,
    )
    await session.commit()
    await set_tenant(session, company_id)
    return await _load(session, company_id=company_id, proforma_id=proforma_id)


async def set_status(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    proforma_id: UUID,
    new_status: str,
    note: Optional[str] = None,
    request: Optional[Request] = None,
) -> dict:
    company_id = UUID(claims.company_id)
    before = await _load(session, company_id=company_id, proforma_id=proforma_id)
    current = before["status"]

    if new_status not in _ALLOWED_TRANSITIONS.get(current, set()):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_INVALID_STATE_TRANSITION,
            f"A proforma cannot go from {current} to {new_status}",
        )

    if new_status == "approved":
        # BR-PF-03: an open variance beyond tolerance blocks approval
        # unless the approver holds the permission that exists for exactly
        # this. Note it checks *open* variances -- someone who has reviewed
        # and accepted the difference has already made the decision, and
        # should not be asked to hold a special permission to act on it.
        if await variance_service.exceeds_tolerance(session, company_id=company_id, compare_doc_id=proforma_id):
            if "proforma.approve_variance" not in claims.permissions:
                raise ApiError(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    CODE_VARIANCE_EXCEEDS_TOLERANCE,
                    "This proforma differs from the purchase order by more than the allowed tolerance; "
                    "approving it needs the variance-approval permission, or the variances resolved first",
                )

    sets = ["status = :status"]
    params: dict = {"status": new_status, "id": proforma_id, "c": company_id}
    if new_status == "approved":
        sets += ["approved_by = :who", "approved_at = now()"]
        params["who"] = UUID(claims.user_id)
    if new_status == "rejected" and note:
        sets.append("query_note = :note")
        params["note"] = note

    await session.execute(
        text(f"UPDATE proforma_invoices SET {', '.join(sets)} WHERE id = :id AND company_id = :c"), params
    )

    await audit.record(
        session,
        entity_type="proforma_invoice",
        action="approved" if new_status == "approved" else ("rejected" if new_status == "rejected" else "status_changed"),
        claims=claims,
        entity_id=proforma_id,
        entity_label=before["proforma_number"],
        description=note,
        before={"status": current},
        after={"status": new_status},
        request=request,
    )
    await session.commit()
    await set_tenant(session, company_id)
    return await _load(session, company_id=company_id, proforma_id=proforma_id)


async def raise_query(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    proforma_id: UUID,
    note: str,
    request: Optional[Request] = None,
) -> dict:
    """Record a question back to the supplier, and move the proforma to
    `under_review` so it stops looking like it is waiting on us."""
    company_id = UUID(claims.company_id)
    before = await _load(session, company_id=company_id, proforma_id=proforma_id)
    if before["status"] in ("paid", "completed", "cancelled", "rejected"):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_INVALID_STATE_TRANSITION,
            f"Cannot raise a query on a proforma in status {before['status']}",
        )

    await session.execute(
        text(
            "UPDATE proforma_invoices SET query_note = :note, query_raised_at = now(), "
            " status = CASE WHEN status = 'pending' THEN 'under_review' ELSE status END "
            "WHERE id = :id AND company_id = :c"
        ),
        {"note": note, "id": proforma_id, "c": company_id},
    )
    await audit.record(
        session,
        entity_type="proforma_invoice",
        action="status_changed",
        claims=claims,
        entity_id=proforma_id,
        entity_label=before["proforma_number"],
        description=f"Query raised: {note}",
        request=request,
    )
    await session.commit()
    await set_tenant(session, company_id)
    return await _load(session, company_id=company_id, proforma_id=proforma_id)


async def delete_proforma(
    session: AsyncSession, *, claims: AccessTokenClaims, proforma_id: UUID, request: Optional[Request] = None
) -> None:
    company_id = UUID(claims.company_id)
    before = await _load(session, company_id=company_id, proforma_id=proforma_id)
    if before["status"] != "pending":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_INVALID_STATE_TRANSITION,
            f"Only a pending proforma can be deleted (this one is {before['status']})",
        )
    await session.execute(
        text("DELETE FROM document_variances WHERE company_id = :c AND compare_doc_id = :id"),
        {"c": company_id, "id": proforma_id},
    )
    await session.execute(
        text("DELETE FROM proforma_invoice_items WHERE proforma_id = :id AND company_id = :c"),
        {"id": proforma_id, "c": company_id},
    )
    await session.execute(
        text("DELETE FROM proforma_invoices WHERE id = :id AND company_id = :c"),
        {"id": proforma_id, "c": company_id},
    )
    await audit.record(
        session,
        entity_type="proforma_invoice",
        action="deleted",
        claims=claims,
        entity_id=proforma_id,
        entity_label=before["proforma_number"],
        request=request,
    )
    await session.commit()
