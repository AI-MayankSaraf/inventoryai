"""
Supplier quotation service — 06_BUSINESS_RULES.md §6 (BR-QT-01..05) and the
quotation arm of §14's state machine: `draft -> approved -> converted`,
`-> rejected` from draft.

Scope cut, matching this backend's AI pipeline gap: `source` is always
'manual' here. The schema's `under_review` status and `ai_extraction_result_id`
column exist for the AI-extraction-review flow (04_API_SPECIFICATION.md §3.21's
`/ai/extractions/{id}/approve`, which promotes an extraction into this same
table) but that pipeline isn't built yet, so a manual quotation goes straight
`draft -> approved` through the one approve action below rather than through
a separate review step. When AI extraction lands, it can reuse this same
table and approve action; nothing here forecloses that.

BR-QT-03 (a quotation past `valid_until` is `expired`) has no daily job to
flip the stored `status` column — Celery isn't wired in this backend yet —
so expiry is computed on read (`is_expired` in the response) and enforced
at the point it matters (comparison build/convert) rather than mutating
`status` out from under a job that doesn't exist.
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
from app.core.errors import (
    CODE_DUPLICATE,
    CODE_INVALID_STATE_TRANSITION,
    CODE_NOT_FOUND,
    CODE_UNRESOLVED_LINES,
    CODE_VALIDATION,
    ApiError,
)
from app.core.money import D, round2, round_total
from app.core.security import AccessTokenClaims
from app.modules.procurement.schemas import QuotationCreate, QuotationRejectRequest, QuotationUpdate

_EDITABLE_STATUSES = ("draft",)


async def _load(session: AsyncSession, *, company_id: str, quotation_id: UUID) -> dict:
    header = (
        await session.execute(
            text(
                "SELECT id, quotation_number, supplier_id, rfq_id, quotation_date, valid_until, currency_code, "
                "subtotal, discount_amount, taxable_value, tax_amount, freight_amount, other_charges, round_off, "
                "total_amount, payment_terms, delivery_terms, delivery_period_days, warranty_terms, freight_terms, "
                "source, status, approved_by, approved_at, rejected_reason, row_version, created_at, updated_at "
                "FROM supplier_quotations WHERE id = :id AND company_id = :c"
            ),
            {"id": quotation_id, "c": company_id},
        )
    ).mappings().first()
    if header is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Quotation not found")

    items = (
        await session.execute(
            text(
                "SELECT id, line_no, rfq_item_id, product_variant_id, raw_description, supplier_sku, quantity, "
                "uom_id, unit_price, discount_pct, gst_rate, cess_rate, line_net, line_tax, line_total, "
                "is_available, availability_note, lead_time_days, provenance "
                "FROM supplier_quotation_items WHERE quotation_id = :id AND company_id = :c ORDER BY line_no"
            ),
            {"id": quotation_id, "c": company_id},
        )
    ).mappings().all()

    out = dict(header)
    out["items"] = [dict(r) for r in items]
    out["item_count"] = len(items)
    out["is_expired"] = bool(out["valid_until"] and out["valid_until"] < clock.today())
    return out


async def list_quotations(
    session: AsyncSession,
    *,
    company_id: str,
    limit: int = 100,
    offset: int = 0,
    status_filter: Optional[str] = None,
    supplier_id: Optional[UUID] = None,
    rfq_id: Optional[UUID] = None,
) -> list[dict]:
    where = ["company_id = :c"]
    params: dict = {"c": company_id, "limit": limit, "offset": offset}
    if status_filter:
        where.append("status = :status")
        params["status"] = status_filter
    if supplier_id:
        where.append("supplier_id = :supplier_id")
        params["supplier_id"] = supplier_id
    if rfq_id:
        where.append("rfq_id = :rfq_id")
        params["rfq_id"] = rfq_id
    rows = (
        await session.execute(
            text(
                "SELECT id, quotation_number, supplier_id, rfq_id, quotation_date, valid_until, currency_code, "
                "subtotal, discount_amount, taxable_value, tax_amount, freight_amount, other_charges, round_off, "
                "total_amount, payment_terms, delivery_terms, delivery_period_days, warranty_terms, freight_terms, "
                "source, status, approved_by, approved_at, rejected_reason, row_version, created_at, updated_at, "
                "(SELECT COUNT(*) FROM supplier_quotation_items sqi "
                " WHERE sqi.quotation_id = supplier_quotations.id AND sqi.company_id = supplier_quotations.company_id"
                ") AS item_count "
                f"FROM supplier_quotations WHERE {' AND '.join(where)} "
                "ORDER BY quotation_date DESC, quotation_number DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
    ).mappings().all()
    return [
        {**dict(r), "items": [], "is_expired": bool(r["valid_until"] and r["valid_until"] < clock.today())}
        for r in rows
    ]


async def get_quotation(session: AsyncSession, *, company_id: str, quotation_id: UUID) -> dict:
    return await _load(session, company_id=company_id, quotation_id=quotation_id)


async def _totals_and_items(
    session: AsyncSession, *, company_id: str, quotation_id: UUID, items: list, freight, other_charges
) -> dict:
    """Quotation totals have no CGST/SGST/IGST split (there's no delivery
    godown yet to derive one from — that only exists once this becomes a
    PO) — just one combined `tax_amount`, so this doesn't reuse
    `core.money.document_totals`, only its per-line `line_amounts`."""
    from app.core.money import line_amounts

    subtotal = Decimal("0")
    taxable_value = Decimal("0")
    tax_amount = Decimal("0")

    for line_no, item in enumerate(items, start=1):
        d = item if isinstance(item, dict) else item.model_dump()
        if d.get("product_variant_id"):
            variant = (
                await session.execute(
                    text("SELECT id FROM product_variants WHERE id = :id AND company_id = :c"),
                    {"id": d["product_variant_id"], "c": company_id},
                )
            ).mappings().first()
            if variant is None:
                raise ApiError(status.HTTP_400_BAD_REQUEST, CODE_VALIDATION, "One of the selected products does not exist")

        amounts = line_amounts(
            quantity=D(d["quantity"]),
            unit_price=D(d["unit_price"]),
            discount_pct=D(d["discount_pct"]),
            gst_rate=D(d["gst_rate"]),
            cess_rate=D(d["cess_rate"]),
        )
        line_tax_combined = amounts.line_tax + amounts.line_cess
        line_total = amounts.line_net + line_tax_combined

        subtotal += D(d["quantity"]) * D(d["unit_price"])
        taxable_value += amounts.line_net
        tax_amount += line_tax_combined

        await session.execute(
            text(
                "INSERT INTO supplier_quotation_items "
                "(company_id, quotation_id, line_no, rfq_item_id, product_variant_id, raw_description, "
                " supplier_sku, quantity, uom_id, unit_price, discount_pct, gst_rate, cess_rate, line_net, "
                " line_tax, line_total, is_available, availability_note, lead_time_days, provenance) "
                "VALUES (:c, :qid, :line_no, :rfq_item_id, :variant, :raw_desc, :sku, :quantity, :uom, "
                " :unit_price, :discount_pct, :gst_rate, :cess_rate, :line_net, :line_tax, :line_total, "
                " :is_available, :availability_note, :lead_time, 'user_approved')"
            ),
            {
                "c": company_id,
                "qid": quotation_id,
                "line_no": line_no,
                "rfq_item_id": d.get("rfq_item_id"),
                "variant": d.get("product_variant_id"),
                "raw_desc": d.get("raw_description"),
                "sku": d.get("supplier_sku"),
                "quantity": d["quantity"],
                "uom": d["uom_id"],
                "unit_price": d["unit_price"],
                "discount_pct": d["discount_pct"],
                "gst_rate": d["gst_rate"],
                "cess_rate": d["cess_rate"],
                "line_net": amounts.line_net,
                "line_tax": line_tax_combined,
                "line_total": line_total,
                "is_available": d.get("is_available", True),
                "availability_note": d.get("availability_note"),
                "lead_time": d.get("lead_time_days"),
            },
        )

    subtotal = round2(subtotal)
    taxable_value = round2(taxable_value)
    tax_amount = round2(tax_amount)
    discount_amount = round2(subtotal - taxable_value)
    freight_amount = round2(D(freight))
    other_amount = round2(D(other_charges))
    total_before_round = taxable_value + tax_amount + freight_amount + other_amount
    total_amount = round_total(total_before_round, "nearest")
    round_off = round2(total_amount - total_before_round)

    return {
        "subtotal": subtotal,
        "discount_amount": discount_amount,
        "taxable_value": taxable_value,
        "tax_amount": tax_amount,
        "freight_amount": freight_amount,
        "other_charges": other_amount,
        "round_off": round_off,
        "total_amount": total_amount,
    }


async def _sync_rfq_status_on_quotation(session: AsyncSession, *, company_id: str, rfq_id: UUID, supplier_id: UUID) -> None:
    """BR-RFQ-06: derive the RFQ's status from its suppliers' response
    state, never set by hand. Left unimplemented in `rfq_service.py` on
    purpose (that phase never drove a quotation into existence); this is
    where it actually gets exercised for the first time.
    """
    await session.execute(
        text(
            "UPDATE rfq_suppliers SET status = 'quoted', responded_at = now() "
            "WHERE rfq_id = :rfq_id AND company_id = :c AND supplier_id = :supplier_id"
        ),
        {"rfq_id": rfq_id, "c": company_id, "supplier_id": supplier_id},
    )
    counts = (
        await session.execute(
            text(
                "SELECT COUNT(*) AS total, "
                "COUNT(*) FILTER (WHERE status IN ('quoted', 'declined')) AS resolved "
                "FROM rfq_suppliers WHERE rfq_id = :rfq_id AND company_id = :c"
            ),
            {"rfq_id": rfq_id, "c": company_id},
        )
    ).mappings().first()
    rfq = (
        await session.execute(text("SELECT status FROM rfqs WHERE id = :id AND company_id = :c"), {"id": rfq_id, "c": company_id})
    ).mappings().first()
    if rfq is None or rfq["status"] not in ("sent", "partially_quoted", "quoted"):
        return
    if counts["total"] and counts["resolved"] == counts["total"]:
        new_status = "quoted"
    else:
        new_status = "partially_quoted"
    if new_status != rfq["status"]:
        await session.execute(
            text("UPDATE rfqs SET status = :s, row_version = row_version + 1 WHERE id = :id"),
            {"s": new_status, "id": rfq_id},
        )


async def create_quotation(
    session: AsyncSession, *, claims: AccessTokenClaims, body: QuotationCreate, request: Optional[Request] = None
) -> dict:
    supplier = (
        await session.execute(
            text("SELECT id, name FROM suppliers WHERE id = :id AND company_id = :c AND deleted_at IS NULL"),
            {"id": body.supplier_id, "c": claims.company_id},
        )
    ).mappings().first()
    if supplier is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Supplier not found")

    if body.rfq_id:
        rfq = (
            await session.execute(
                text("SELECT id, status FROM rfqs WHERE id = :id AND company_id = :c"),
                {"id": body.rfq_id, "c": claims.company_id},
            )
        ).mappings().first()
        if rfq is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "RFQ not found")
        if rfq["status"] not in ("sent", "partially_quoted", "quoted"):
            raise ApiError(
                status.HTTP_409_CONFLICT,
                CODE_INVALID_STATE_TRANSITION,
                f"Cannot record a quotation against an RFQ in status {rfq['status']}",
            )

    # BR-QT-01: (supplier, quotation_number) unique per tenant. The DB has
    # this as a case-insensitive unique index (`uq_quotation`); checked here
    # first for a clean 409 rather than surfacing a raw IntegrityError.
    dup = (
        await session.execute(
            text(
                "SELECT id FROM supplier_quotations WHERE company_id = :c AND supplier_id = :supplier "
                "AND upper(quotation_number) = upper(:number)"
            ),
            {"c": claims.company_id, "supplier": body.supplier_id, "number": body.quotation_number},
        )
    ).mappings().first()
    if dup is not None:
        raise ApiError(
            status.HTTP_409_CONFLICT, CODE_DUPLICATE, f"A quotation numbered {body.quotation_number} already exists for this supplier"
        )

    quotation_id = uuid4()
    quotation_date = body.quotation_date or clock.today()

    # Header first (placeholder totals), then items: same ordering fix as
    # PO/GRN — items carry a NOT NULL FK to the header.
    await session.execute(
        text(
            "INSERT INTO supplier_quotations "
            "(id, company_id, quotation_number, supplier_id, rfq_id, quotation_date, valid_until, "
            " payment_terms, delivery_terms, delivery_period_days, warranty_terms, freight_terms, source) "
            "VALUES (:id, :c, :number, :supplier, :rfq_id, :qdate, :valid_until, :payment_terms, "
            " :delivery_terms, :delivery_days, :warranty, :freight_terms, 'manual')"
        ),
        {
            "id": quotation_id,
            "c": claims.company_id,
            "number": body.quotation_number,
            "supplier": body.supplier_id,
            "rfq_id": body.rfq_id,
            "qdate": quotation_date,
            "valid_until": body.valid_until,
            "payment_terms": body.payment_terms,
            "delivery_terms": body.delivery_terms,
            "delivery_days": body.delivery_period_days,
            "warranty": body.warranty_terms,
            "freight_terms": body.freight_terms,
        },
    )

    totals = await _totals_and_items(
        session,
        company_id=claims.company_id,
        quotation_id=quotation_id,
        items=body.items,
        freight=body.freight_amount,
        other_charges=body.other_charges,
    )
    await session.execute(
        text(
            "UPDATE supplier_quotations SET subtotal = :subtotal, discount_amount = :discount, "
            "taxable_value = :taxable, tax_amount = :tax, freight_amount = :freight, other_charges = :other, "
            "round_off = :round_off, total_amount = :total WHERE id = :id"
        ),
        {
            "id": quotation_id,
            "subtotal": totals["subtotal"],
            "discount": totals["discount_amount"],
            "taxable": totals["taxable_value"],
            "tax": totals["tax_amount"],
            "freight": totals["freight_amount"],
            "other": totals["other_charges"],
            "round_off": totals["round_off"],
            "total": totals["total_amount"],
        },
    )

    if body.rfq_id:
        await _sync_rfq_status_on_quotation(session, company_id=claims.company_id, rfq_id=body.rfq_id, supplier_id=body.supplier_id)

    result = await _load(session, company_id=claims.company_id, quotation_id=quotation_id)
    await audit.record(
        session, entity_type="supplier_quotation", action="created", claims=claims, entity_id=quotation_id,
        entity_label=result["quotation_number"], after=result, request=request,
    )
    await session.commit()
    return result


async def update_quotation(
    session: AsyncSession, *, claims: AccessTokenClaims, quotation_id: UUID, body: QuotationUpdate, request: Optional[Request] = None
) -> dict:
    before = await _load(session, company_id=claims.company_id, quotation_id=quotation_id)
    if before["status"] not in _EDITABLE_STATUSES:
        raise ApiError(
            status.HTTP_409_CONFLICT, CODE_INVALID_STATE_TRANSITION,
            f"Only draft quotations are editable (current status: {before['status']})",
        )

    if body.quotation_number and body.quotation_number.upper() != before["quotation_number"].upper():
        dup = (
            await session.execute(
                text(
                    "SELECT id FROM supplier_quotations WHERE company_id = :c AND supplier_id = :supplier "
                    "AND upper(quotation_number) = upper(:number) AND id != :id"
                ),
                {"c": claims.company_id, "supplier": before["supplier_id"], "number": body.quotation_number, "id": quotation_id},
            )
        ).mappings().first()
        if dup is not None:
            raise ApiError(status.HTTP_409_CONFLICT, CODE_DUPLICATE, f"A quotation numbered {body.quotation_number} already exists for this supplier")

    header_fields = body.model_dump(exclude_unset=True, exclude={"items", "freight_amount", "other_charges"})
    if header_fields:
        assignments = ", ".join(f"{k} = :{k}" for k in header_fields)
        await session.execute(
            text(f"UPDATE supplier_quotations SET {assignments}, row_version = row_version + 1 WHERE id = :id"),
            {**header_fields, "id": quotation_id},
        )

    if body.items is not None:
        await session.execute(
            text("DELETE FROM supplier_quotation_items WHERE quotation_id = :id AND company_id = :c"),
            {"id": quotation_id, "c": claims.company_id},
        )
        freight = body.freight_amount if body.freight_amount is not None else before["freight_amount"]
        other = body.other_charges if body.other_charges is not None else before["other_charges"]
        totals = await _totals_and_items(
            session, company_id=claims.company_id, quotation_id=quotation_id, items=body.items, freight=freight, other_charges=other,
        )
        await session.execute(
            text(
                "UPDATE supplier_quotations SET subtotal = :subtotal, discount_amount = :discount, "
                "taxable_value = :taxable, tax_amount = :tax, freight_amount = :freight, other_charges = :other, "
                "round_off = :round_off, total_amount = :total WHERE id = :id"
            ),
            {
                "id": quotation_id, "subtotal": totals["subtotal"], "discount": totals["discount_amount"],
                "taxable": totals["taxable_value"], "tax": totals["tax_amount"], "freight": totals["freight_amount"],
                "other": totals["other_charges"], "round_off": totals["round_off"], "total": totals["total_amount"],
            },
        )
    elif body.freight_amount is not None or body.other_charges is not None:
        freight = round2(D(body.freight_amount if body.freight_amount is not None else before["freight_amount"]))
        other = round2(D(body.other_charges if body.other_charges is not None else before["other_charges"]))
        taxable = D(before["taxable_value"])
        tax = D(before["tax_amount"])
        total_before_round = taxable + tax + freight + other
        total_amount = round_total(total_before_round, "nearest")
        round_off = round2(total_amount - total_before_round)
        await session.execute(
            text(
                "UPDATE supplier_quotations SET freight_amount = :freight, other_charges = :other, "
                "round_off = :round_off, total_amount = :total WHERE id = :id"
            ),
            {"freight": freight, "other": other, "round_off": round_off, "total": total_amount, "id": quotation_id},
        )

    after = await _load(session, company_id=claims.company_id, quotation_id=quotation_id)
    await audit.record(
        session, entity_type="supplier_quotation", action="updated", claims=claims, entity_id=quotation_id,
        entity_label=after["quotation_number"], before=before, after=after, request=request,
    )
    await session.commit()
    return after


async def approve_quotation(
    session: AsyncSession, *, claims: AccessTokenClaims, quotation_id: UUID, request: Optional[Request] = None
) -> dict:
    before = await _load(session, company_id=claims.company_id, quotation_id=quotation_id)
    if before["status"] not in ("draft", "under_review"):
        raise ApiError(
            status.HTTP_409_CONFLICT, CODE_INVALID_STATE_TRANSITION,
            f"Only a draft quotation can be approved (current status: {before['status']})",
        )
    # BR-QT-05: re-validated server-side, never trusting a client's
    # "can_approve" — every line needs a matched SKU before this quotation
    # can be compared or ordered from.
    unmatched = [i["line_no"] for i in before["items"] if not i["product_variant_id"]]
    if unmatched:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_UNRESOLVED_LINES,
            f"Line(s) {unmatched} have no matched product and must be resolved before approval",
        )

    await session.execute(
        text(
            "UPDATE supplier_quotations SET status = 'approved', approved_by = :approver, approved_at = now(), "
            "row_version = row_version + 1 WHERE id = :id"
        ),
        {"approver": claims.user_id, "id": quotation_id},
    )
    after = await _load(session, company_id=claims.company_id, quotation_id=quotation_id)
    await audit.record(
        session, entity_type="supplier_quotation", action="approved", claims=claims, entity_id=quotation_id,
        entity_label=after["quotation_number"], before=before, after=after, request=request,
    )
    await session.commit()
    return after


async def reject_quotation(
    session: AsyncSession, *, claims: AccessTokenClaims, quotation_id: UUID, body: QuotationRejectRequest, request: Optional[Request] = None
) -> dict:
    before = await _load(session, company_id=claims.company_id, quotation_id=quotation_id)
    if before["status"] not in ("draft", "under_review"):
        raise ApiError(
            status.HTTP_409_CONFLICT, CODE_INVALID_STATE_TRANSITION,
            f"Cannot reject a quotation in status {before['status']}",
        )
    await session.execute(
        text(
            "UPDATE supplier_quotations SET status = 'rejected', rejected_reason = :reason, "
            "row_version = row_version + 1 WHERE id = :id"
        ),
        {"reason": body.reason, "id": quotation_id},
    )
    after = await _load(session, company_id=claims.company_id, quotation_id=quotation_id)
    await audit.record(
        session, entity_type="supplier_quotation", action="rejected", claims=claims, entity_id=quotation_id,
        entity_label=after["quotation_number"], description=body.reason, before=before, after=after, request=request,
    )
    await session.commit()
    return after


async def delete_quotation(
    session: AsyncSession, *, claims: AccessTokenClaims, quotation_id: UUID, request: Optional[Request] = None
) -> None:
    before = await _load(session, company_id=claims.company_id, quotation_id=quotation_id)
    if before["status"] not in _EDITABLE_STATUSES:
        raise ApiError(
            status.HTTP_409_CONFLICT, CODE_INVALID_STATE_TRANSITION,
            f"Only draft quotations can be deleted (current status: {before['status']})",
        )
    await session.execute(text("DELETE FROM supplier_quotations WHERE id = :id AND company_id = :c"), {"id": quotation_id, "c": claims.company_id})
    await audit.record(
        session, entity_type="supplier_quotation", action="deleted", claims=claims, entity_id=quotation_id,
        entity_label=before["quotation_number"], before=before, request=request,
    )
    await session.commit()
