"""
Human review, and the one door from `ai_*` into the business tables.

BR-AI-01 says AI never writes to a business table. That rule is kept here
structurally rather than by intent: the pipeline module has no import of
`quotation_service`, `proforma_service` or `invoice_service` at all, and
this module — every function of which takes a reviewer's user id — is the
only place that does.

BR-AI-02 is kept the same way. `approve` builds the *same* create body a
person typing the document by hand would submit, hands it to the existing
service, and lets the money engine compute subtotal, tax and total. No
number the model read off the page is ever stored as a financial value; the
printed total was kept only as a cross-check and is discarded here.

Every edit below writes an `ai_review_actions` row with the AI's value and
the human's (BR-AI-05). That table is the audit record and the training set
at the same time, which is why "accept" is recorded as explicitly as
"change" — knowing what the model got right matters as much as knowing what
it got wrong.
"""

from __future__ import annotations

import json
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
    CODE_INVALID_STATE_TRANSITION,
    CODE_NOT_FOUND,
    CODE_VALIDATION,
    ApiError,
)
from app.core.security import AccessTokenClaims
from app.modules.ai import matching_service
from app.modules.ai.normalise import normalise
from app.modules.ai.values import parse_date, parse_number

#: Which business document an extraction of each type becomes.
PROMOTION_TARGET: dict[str, str] = {
    "supplier_quotation": "supplier_quotation",
    "rate_list": "supplier_quotation",
    "price_revision": "supplier_quotation",
    "proforma_invoice": "proforma_invoice",
    "tax_invoice": "supplier_invoice",
}


# ================================================================ loading


async def load_extraction(session: AsyncSession, *, company_id: str, document_id: UUID) -> dict:
    result = (
        await session.execute(
            text(
                "SELECT * FROM ai_extraction_results "
                "WHERE company_id = :c AND document_id = :d AND superseded_by IS NULL"
            ),
            {"c": company_id, "d": document_id},
        )
    ).mappings().first()
    if result is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            CODE_NOT_FOUND,
            "This document has no extraction yet.",
        )
    return dict(result)


async def _line(session: AsyncSession, *, company_id: str, line_id: UUID) -> dict:
    row = (
        await session.execute(
            text("SELECT * FROM ai_extracted_lines WHERE company_id = :c AND id = :id"),
            {"c": company_id, "id": line_id},
        )
    ).mappings().first()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Line not found")
    return dict(row)


async def _assert_open(session: AsyncSession, *, company_id: str, result_id: UUID) -> dict:
    row = (
        await session.execute(
            text("SELECT * FROM ai_extraction_results WHERE company_id = :c AND id = :id"),
            {"c": company_id, "id": result_id},
        )
    ).mappings().first()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Extraction not found")
    if row["review_status"] in ("approved", "rejected"):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_INVALID_STATE_TRANSITION,
            f"This extraction was already {row['review_status']} and cannot be edited.",
        )
    if row["superseded_by"] is not None:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_INVALID_STATE_TRANSITION,
            "This extraction was replaced by a newer run of the document.",
        )
    return dict(row)


async def _record_action(
    session: AsyncSession,
    *,
    company_id: str,
    result_id: UUID,
    target_type: str,
    target_id: UUID,
    action: str,
    before: Optional[dict],
    after: Optional[dict],
    reviewer_id: str,
    reason: Optional[str] = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO ai_review_actions (id, company_id, extraction_result_id, target_type, target_id, "
            " action, before_value, after_value, reason, reviewer_id) "
            "VALUES (:id, :c, :r, :tt, :ti, :a, CAST(:before AS jsonb), CAST(:after AS jsonb), :reason, :who)"
        ),
        {
            "id": uuid4(),
            "c": company_id,
            "r": result_id,
            "tt": target_type,
            "ti": target_id,
            "a": action,
            "before": json.dumps(before, default=str) if before is not None else None,
            "after": json.dumps(after, default=str) if after is not None else None,
            "reason": reason,
            "who": reviewer_id,
        },
    )
    # The first edit moves the extraction out of "pending": somebody is
    # working on it, and two people opening the same document should be able
    # to see that.
    await session.execute(
        text(
            "UPDATE ai_extraction_results SET review_status = 'in_review' "
            "WHERE company_id = :c AND id = :r AND review_status = 'pending'"
        ),
        {"c": company_id, "r": result_id},
    )


# ================================================================ editing


async def correct_field(
    session: AsyncSession, *, claims: AccessTokenClaims, field_id: UUID, value: str
) -> dict:
    row = (
        await session.execute(
            text("SELECT * FROM ai_extracted_fields WHERE company_id = :c AND id = :id"),
            {"c": claims.company_id, "id": field_id},
        )
    ).mappings().first()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Field not found")
    await _assert_open(session, company_id=claims.company_id, result_id=row["extraction_result_id"])

    cleaned = (value or "").strip()
    normalised, error = _validate_field(row["value_type"], cleaned)
    if error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_VALIDATION,
            error,
            errors=[{"field": row["field_key"], "message": error}],
        )

    await session.execute(
        text(
            "UPDATE ai_extracted_fields SET corrected_value = :v, normalised_value = :n, "
            " corrected_by = :who, corrected_at = now(), provenance = 'user_approved', "
            " validation_error = NULL, confidence = 100 "
            "WHERE company_id = :c AND id = :id"
        ),
        {"v": cleaned, "n": normalised, "who": claims.user_id, "c": claims.company_id, "id": field_id},
    )
    await _record_action(
        session,
        company_id=claims.company_id,
        result_id=row["extraction_result_id"],
        target_type="field",
        target_id=field_id,
        action="edit" if cleaned != (row["raw_value"] or "") else "accept",
        before={"value": row["corrected_value"] or row["raw_value"], "confidence": float(row["confidence"] or 0)},
        after={"value": cleaned},
        reviewer_id=claims.user_id,
    )
    return await _field(session, company_id=claims.company_id, field_id=field_id)


def _validate_field(value_type: str, value: str) -> tuple[Optional[str], Optional[str]]:
    if not value:
        return None, "Enter a value, or leave the AI's reading in place."
    if value_type == "date":
        parsed = parse_date(value)
        return (parsed.isoformat() if parsed else None), (None if parsed else "That is not a date we can read.")
    if value_type in ("number", "currency"):
        parsed = parse_number(value)
        return (str(parsed) if parsed is not None else None), (None if parsed is not None else "That is not a number.")
    return value, None


async def _field(session: AsyncSession, *, company_id: str, field_id: UUID) -> dict:
    row = (
        await session.execute(
            text("SELECT * FROM ai_extracted_fields WHERE company_id = :c AND id = :id"),
            {"c": company_id, "id": field_id},
        )
    ).mappings().one()
    return dict(row)


async def update_line(
    session: AsyncSession, *, claims: AccessTokenClaims, line_id: UUID, values: dict
) -> dict:
    """Edit what was read off a row: quantity, price, discount, GST, HSN.

    Not the line total — there is no such column to edit, because there is
    no stored line total until the money engine computes one at approval.
    """
    row = await _line(session, company_id=claims.company_id, line_id=line_id)
    await _assert_open(session, company_id=claims.company_id, result_id=row["extraction_result_id"])

    allowed = {"quantity", "unit_price", "discount_pct", "gst_rate", "hsn_code", "raw_uom"}
    fields = {k: v for k, v in values.items() if k in allowed and v is not None}
    if not fields:
        return row

    if "quantity" in fields and Decimal(str(fields["quantity"])) <= 0:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_VALIDATION, "Quantity must be more than zero",
            errors=[{"field": "quantity", "message": "Must be more than zero"}],
        )
    if "unit_price" in fields and Decimal(str(fields["unit_price"])) < 0:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_VALIDATION, "A price cannot be negative",
            errors=[{"field": "unit_price", "message": "Cannot be negative"}],
        )

    assignments = ", ".join(f"{k} = :{k}" for k in fields)
    await session.execute(
        text(
            f"UPDATE ai_extracted_lines SET {assignments}, provenance = 'user_approved', "
            " validation_errors = '[]'::jsonb WHERE company_id = :c AND id = :id"
        ),
        {**fields, "c": claims.company_id, "id": line_id},
    )
    await _record_action(
        session,
        company_id=claims.company_id,
        result_id=row["extraction_result_id"],
        target_type="line",
        target_id=line_id,
        action="edit",
        before={k: row[k] for k in fields},
        after=fields,
        reviewer_id=claims.user_id,
    )
    return await _line(session, company_id=claims.company_id, line_id=line_id)


async def suggest_matches(session: AsyncSession, *, company_id: str, line_id: UUID) -> dict:
    """Re-run the ladder for one line and refresh its shortlist.

    Used after a description is corrected, and by the "show me other
    options" control on the review screen.
    """
    row = await _line(session, company_id=company_id, line_id=line_id)
    result_row = (
        await session.execute(
            text("SELECT supplier_id FROM ai_extraction_results WHERE company_id = :c AND id = :id"),
            {"c": company_id, "id": row["extraction_result_id"]},
        )
    ).mappings().one()

    match = await matching_service.match_line(
        session,
        company_id=company_id,
        description=row["raw_description"],
        supplier_sku=row["supplier_sku"],
        supplier_id=result_row["supplier_id"],
    )
    await matching_service.record_candidates(
        session,
        company_id=company_id,
        line_id=line_id,
        supplier_id=result_row["supplier_id"],
        query_text=row["raw_description"],
        result=match,
        selected_variant_id=row["final_variant_id"],
    )
    return {
        "line_id": line_id,
        "rung_reached": match.rung_reached,
        "auto_matched": match.auto_matched,
        "skipped_rungs": match.skipped_rungs,
        "candidates": [
            {
                "product_variant_id": c.product_variant_id,
                "sku": c.sku,
                "product_name": c.product_name,
                "match_method": c.method,
                "score": c.score,
                "confidence": c.confidence,
                "reasons": c.reasons,
            }
            for c in match.candidates
        ],
    }


async def confirm_match(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    line_id: UUID,
    product_variant_id: UUID,
    save_alias: bool = True,
) -> dict:
    """A person settles a line. BR-AI-06: the confirmation becomes an alias,
    so the same supplier code never needs matching again."""
    row = await _line(session, company_id=claims.company_id, line_id=line_id)
    result = await _assert_open(session, company_id=claims.company_id, result_id=row["extraction_result_id"])

    variant = (
        await session.execute(
            text(
                "SELECT v.id, v.sku, p.name FROM product_variants v JOIN products p ON p.id = v.product_id "
                "WHERE v.company_id = :c AND v.id = :id AND v.deleted_at IS NULL"
            ),
            {"c": claims.company_id, "id": product_variant_id},
        )
    ).mappings().first()
    if variant is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "That product is not in your catalogue")

    changed = row["matched_variant_id"] != product_variant_id
    alias_written = False
    if save_alias and result["supplier_id"] and row["supplier_sku"]:
        alias_written = await _save_alias(
            session,
            company_id=claims.company_id,
            supplier_id=result["supplier_id"],
            variant_id=product_variant_id,
            supplier_sku=row["supplier_sku"],
            description=row["raw_description"],
            user_id=claims.user_id,
        )

    await session.execute(
        text(
            "UPDATE ai_extracted_lines SET final_variant_id = :v, final_decision = :d, "
            " match_method = COALESCE(match_method, 'manual'), provenance = 'user_approved', "
            " decided_by = :who, decided_at = now(), alias_saved = :alias "
            "WHERE company_id = :c AND id = :id"
        ),
        {
            "v": product_variant_id,
            "d": "changed" if changed else "accepted_ai",
            "who": claims.user_id,
            "alias": alias_written,
            "c": claims.company_id,
            "id": line_id,
        },
    )
    await session.execute(
        text(
            "UPDATE ai_match_candidates SET is_selected = (product_variant_id = :v) "
            "WHERE company_id = :c AND extracted_line_id = :l"
        ),
        {"v": product_variant_id, "c": claims.company_id, "l": line_id},
    )
    await _record_action(
        session,
        company_id=claims.company_id,
        result_id=row["extraction_result_id"],
        target_type="line",
        target_id=line_id,
        action="match",
        before={"variant_id": str(row["matched_variant_id"]) if row["matched_variant_id"] else None,
                "method": row["match_method"]},
        after={"variant_id": str(product_variant_id), "sku": variant["sku"], "alias_saved": alias_written},
        reviewer_id=claims.user_id,
    )
    if alias_written:
        await _record_action(
            session,
            company_id=claims.company_id,
            result_id=row["extraction_result_id"],
            target_type="line",
            target_id=line_id,
            action="save_alias",
            before=None,
            after={"supplier_sku": row["supplier_sku"], "variant_id": str(product_variant_id)},
            reviewer_id=claims.user_id,
        )
    return await _line(session, company_id=claims.company_id, line_id=line_id)


async def _save_alias(
    session: AsyncSession, *, company_id: str, supplier_id: UUID, variant_id: UUID,
    supplier_sku: str, description: str, user_id: str,
) -> bool:
    """Write the learned mapping, or leave an existing one alone.

    An alias already pointing somewhere else is *not* silently repointed: a
    supplier reusing a code for a different product is a real thing that a
    person should see, and quietly rewriting history would break the audit
    trail behind every earlier document that used it.
    """
    existing = (
        await session.execute(
            text(
                "SELECT id, product_variant_id FROM supplier_products "
                "WHERE company_id = :c AND supplier_id = :s AND lower(supplier_sku) = lower(:sku)"
            ),
            {"c": company_id, "s": supplier_id, "sku": supplier_sku},
        )
    ).mappings().first()
    if existing:
        return False
    await session.execute(
        text(
            "INSERT INTO supplier_products (id, company_id, supplier_id, product_variant_id, supplier_sku, "
            " supplier_description, match_source, confirmed_by, confirmed_at) "
            "VALUES (:id, :c, :s, :v, :sku, :desc, 'ai_confirmed', :who, now())"
        ),
        {
            "id": uuid4(),
            "c": company_id,
            "s": supplier_id,
            "v": variant_id,
            "sku": supplier_sku,
            "desc": description[:500],
            "who": user_id,
        },
    )
    return True


async def skip_line(
    session: AsyncSession, *, claims: AccessTokenClaims, line_id: UUID, reason: str
) -> dict:
    """Leave a line out of the promoted document.

    A reason is required. "Skipped" with no explanation is indistinguishable
    from "forgotten" six months later, and this row is the only record that
    the line was ever on the supplier's document at all.
    """
    if len((reason or "").strip()) < 3:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_VALIDATION,
            "Say why this line is being left out",
            errors=[{"field": "reason", "message": "A short reason is required"}],
        )
    row = await _line(session, company_id=claims.company_id, line_id=line_id)
    await _assert_open(session, company_id=claims.company_id, result_id=row["extraction_result_id"])

    await session.execute(
        text(
            "UPDATE ai_extracted_lines SET final_decision = 'skipped', final_variant_id = NULL, "
            " provenance = 'user_approved', decided_by = :who, decided_at = now() "
            "WHERE company_id = :c AND id = :id"
        ),
        {"who": claims.user_id, "c": claims.company_id, "id": line_id},
    )
    await _record_action(
        session,
        company_id=claims.company_id,
        result_id=row["extraction_result_id"],
        target_type="line",
        target_id=line_id,
        action="reject_line",
        before={"variant_id": str(row["matched_variant_id"]) if row["matched_variant_id"] else None},
        after={"decision": "skipped"},
        reason=reason.strip(),
        reviewer_id=claims.user_id,
    )
    return await _line(session, company_id=claims.company_id, line_id=line_id)


# ============================================================== the door


async def unresolved_lines(session: AsyncSession, *, company_id: str, result_id: UUID) -> list[dict]:
    """Lines a person has not settled. While this is non-empty the
    extraction cannot be approved (§4.3)."""
    rows = (
        await session.execute(
            text(
                "SELECT id, line_no, raw_description FROM ai_extracted_lines "
                "WHERE company_id = :c AND extraction_result_id = :r "
                "  AND final_decision IS NULL "
                "ORDER BY line_no"
            ),
            {"c": company_id, "r": result_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def approve(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    document_id: UUID,
    rfq_id: Optional[UUID] = None,
    request: Optional[Request] = None,
) -> dict:
    """Promote an extraction into a real document.

    The only path from `ai_*` into the business tables, and it takes a
    reviewer's identity (BR-AI-01, and the "auto-approval creep" guardrail
    in §8 — there is no endpoint that promotes without a user id).
    """
    result = await load_extraction(session, company_id=claims.company_id, document_id=document_id)
    if result["review_status"] == "approved":
        raise ApiError(
            status.HTTP_409_CONFLICT, CODE_INVALID_STATE_TRANSITION,
            "This document has already been approved.",
        )
    if result["review_status"] == "rejected":
        raise ApiError(
            status.HTTP_409_CONFLICT, CODE_INVALID_STATE_TRANSITION,
            "This document was rejected. Re-run the extraction to try again.",
        )

    unresolved = await unresolved_lines(session, company_id=claims.company_id, result_id=result["id"])
    if unresolved:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_VALIDATION,
            f"{len(unresolved)} line(s) still need a decision before this can be approved.",
            errors=[
                {"field": f"line_{row['line_no']}", "message": f"{row['raw_description'][:60]} is unresolved"}
                for row in unresolved[:10]
            ],
        )

    if result["supplier_id"] is None:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_VALIDATION,
            "Set the supplier before approving — a purchase document has to belong to someone.",
            errors=[{"field": "supplier_id", "message": "No supplier identified"}],
        )

    target = PROMOTION_TARGET.get(result["document_type"])
    if target is None:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_VALIDATION,
            f"A {result['document_type'].replace('_', ' ')} cannot be turned into a purchase document.",
        )

    lines = (
        await session.execute(
            text(
                "SELECT * FROM ai_extracted_lines WHERE company_id = :c AND extraction_result_id = :r "
                "  AND final_decision <> 'skipped' AND final_variant_id IS NOT NULL ORDER BY line_no"
            ),
            {"c": claims.company_id, "r": result["id"]},
        )
    ).mappings().all()
    if not lines:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_VALIDATION,
            "Every line was skipped — there is nothing to create.",
        )

    fields = await _field_values(session, company_id=claims.company_id, result_id=result["id"])
    items = await _build_items(session, company_id=claims.company_id, lines=lines)

    # ---------------------------------------------------------- ordering
    #
    # `create_quotation` and its siblings commit their own unit of work —
    # that is their contract with every other caller, and not something to
    # change from here. So the AI-side updates are written *first*, while
    # the transaction is still open, and the create service's commit then
    # commits them together with the document it creates. Promoting first
    # and updating after would make the two separately committable, and the
    # first time the second half failed the result was exactly that: a real
    # quotation on the books with an extraction still showing "pending".
    #
    # Only `promoted_to_id` cannot be written yet, because the id does not
    # exist until the create returns. It is filled in afterwards, on a
    # re-scoped session — a single UPDATE, and the worst case if it fails is
    # a missing cross-reference rather than a phantom purchase document.
    await session.execute(
        text(
            "UPDATE ai_extraction_results SET review_status = 'approved', reviewed_by = :who, "
            " reviewed_at = now(), promoted_to_type = :t "
            "WHERE company_id = :c AND id = :id"
        ),
        {"who": claims.user_id, "t": target, "c": claims.company_id, "id": result["id"]},
    )
    await session.execute(
        text(
            "UPDATE documents SET processing_status = 'approved', processing_stage = 'Approved' "
            "WHERE company_id = :c AND id = :id"
        ),
        {"c": claims.company_id, "id": document_id},
    )
    await _record_action(
        session,
        company_id=claims.company_id,
        result_id=result["id"],
        target_type="document",
        target_id=document_id,
        action="approve_document",
        before={"review_status": result["review_status"]},
        after={"promoted_to_type": target, "lines": len(items)},
        reviewer_id=claims.user_id,
    )
    await audit.record(
        session,
        entity_type="document",
        action="approved",
        claims=claims,
        entity_id=document_id,
        entity_label=result["document_type"],
        description=f"Extraction approved and promoted to a {target.replace('_', ' ')}",
        request=request,
    )

    promoted_id = await _promote(
        session,
        claims=claims,
        target=target,
        result=result,
        fields=fields,
        items=items,
        rfq_id=rfq_id,
        request=request,
    )

    # The create service's commit ended the transaction, and with it the
    # transaction-scoped tenant setting every RLS policy reads.
    await set_tenant(session, claims.company_id)
    await session.execute(
        text("UPDATE ai_extraction_results SET promoted_to_id = :pid WHERE company_id = :c AND id = :id"),
        {"pid": promoted_id, "c": claims.company_id, "id": result["id"]},
    )
    # The record points back at the file it was read from: its screen shows
    # "Source document", and the file can no longer be deleted (BR-DOC-04).
    await session.execute(
        text(
            "INSERT INTO document_links (id, company_id, document_id, linked_type, linked_id, link_role, linked_by) "
            "VALUES (gen_random_uuid(), :c, :d, :t, :pid, 'source', :u) ON CONFLICT DO NOTHING"
        ),
        {"c": claims.company_id, "d": document_id, "t": target, "pid": promoted_id, "u": claims.user_id},
    )
    return {
        "extraction_result_id": result["id"],
        "promoted_to_type": target,
        "promoted_to_id": promoted_id,
        "line_count": len(items),
    }


async def _field_values(session: AsyncSession, *, company_id: str, result_id: UUID) -> dict[str, str]:
    rows = (
        await session.execute(
            text(
                "SELECT field_key, COALESCE(corrected_value, normalised_value, raw_value) AS value "
                "FROM ai_extracted_fields WHERE company_id = :c AND extraction_result_id = :r"
            ),
            {"c": company_id, "r": result_id},
        )
    ).mappings().all()
    return {r["field_key"]: r["value"] for r in rows if r["value"]}


async def _build_items(session: AsyncSession, *, company_id: str, lines) -> list[dict]:
    """Turn settled lines into create-body items.

    Note what is *not* carried across: `line_total_as_printed`. The printed
    figure did its job as a cross-check during extraction and has no place
    in a stored document (BR-AI-02).
    """
    items: list[dict] = []
    for line in lines:
        uom_id = await _resolve_uom(
            session, company_id=company_id, raw_uom=line["raw_uom"], variant_id=line["final_variant_id"]
        )
        gst_rate = line["gst_rate"]
        if gst_rate is None:
            gst_rate = (
                await session.execute(
                    text("SELECT COALESCE(gst_rate, 18) FROM product_variants WHERE company_id = :c AND id = :v"),
                    {"c": company_id, "v": line["final_variant_id"]},
                )
            ).scalar_one_or_none() or 18
        if line["quantity"] is None or line["unit_price"] is None:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                CODE_VALIDATION,
                f"Line {line['line_no']} has no quantity or price — fill it in or skip the line.",
                errors=[{"field": f"line_{line['line_no']}", "message": "Quantity and price are both required"}],
            )
        items.append(
            {
                "product_variant_id": line["final_variant_id"],
                "raw_description": line["raw_description"],
                "description": line["raw_description"],
                "supplier_sku": line["supplier_sku"],
                "hsn_code": line["hsn_code"],
                "quantity": float(line["quantity"]),
                "uom_id": uom_id,
                "unit_price": float(line["unit_price"]),
                "discount_pct": float(line["discount_pct"] or 0),
                "gst_rate": float(gst_rate),
                "cess_rate": 0.0,
            }
        )
    return items


async def _resolve_uom(session: AsyncSession, *, company_id: str, raw_uom: Optional[str], variant_id: UUID) -> UUID:
    """The supplier's unit word, if we recognise it; otherwise the
    variant's own unit. Never a guess that changes the quantity's meaning."""
    if raw_uom:
        needle = normalise(raw_uom)
        row = (
            await session.execute(
                text(
                    "SELECT id FROM uoms WHERE company_id = :c AND is_active "
                    "  AND (lower(code) = :n OR lower(name) = :n) LIMIT 1"
                ),
                {"c": company_id, "n": needle},
            )
        ).scalar_one_or_none()
        if row:
            return row
    row = (
        await session.execute(
            text("SELECT uom_id FROM product_variants WHERE company_id = :c AND id = :v"),
            {"c": company_id, "v": variant_id},
        )
    ).scalar_one_or_none()
    if row:
        return row
    fallback = (
        await session.execute(
            text("SELECT id FROM uoms WHERE company_id = :c AND is_active ORDER BY code LIMIT 1"),
            {"c": company_id},
        )
    ).scalar_one_or_none()
    if fallback is None:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_VALIDATION, "No unit of measure is set up")
    return fallback


async def _promote(
    session: AsyncSession, *, claims, target: str, result: dict, fields: dict, items: list[dict],
    rfq_id: Optional[UUID], request,
) -> UUID:
    """Hand the reviewed content to the ordinary create service.

    Imported inside the function on purpose: the import graph then shows
    that nothing in the AI package reaches the business services except
    through this one call.
    """
    number = fields.get("document_number") or _fallback_number(result)
    doc_date = parse_date(fields.get("document_date")) or clock.today()

    if target == "supplier_quotation":
        from app.modules.procurement import quotation_service
        from app.modules.procurement.schemas import QuotationCreate, QuotationItemIn

        body = QuotationCreate(
            supplier_id=result["supplier_id"],
            rfq_id=rfq_id,
            quotation_number=number[:100],
            quotation_date=doc_date,
            valid_until=parse_date(fields.get("valid_until")),
            payment_terms=fields.get("payment_terms"),
            delivery_terms=fields.get("delivery_terms"),
            items=[
                QuotationItemIn(
                    product_variant_id=i["product_variant_id"],
                    raw_description=i["raw_description"],
                    supplier_sku=i["supplier_sku"],
                    quantity=i["quantity"],
                    uom_id=i["uom_id"],
                    unit_price=i["unit_price"],
                    discount_pct=i["discount_pct"],
                    gst_rate=i["gst_rate"],
                )
                for i in items
            ],
        )
        created = await quotation_service.create_quotation(session, claims=claims, body=body, request=request)
        return created["id"]

    if target == "proforma_invoice":
        from app.modules.documents import proforma_service
        from app.modules.documents.schemas import ProformaCreate, ProformaItemIn

        body = ProformaCreate(
            supplier_id=result["supplier_id"],
            proforma_number=number[:100],
            proforma_date=doc_date,
            valid_until=parse_date(fields.get("valid_until")),
            items=[
                ProformaItemIn(
                    product_variant_id=i["product_variant_id"],
                    description=i["description"],
                    hsn_code=i["hsn_code"],
                    quantity=i["quantity"],
                    uom_id=i["uom_id"],
                    unit_price=i["unit_price"],
                    gst_rate=i["gst_rate"],
                )
                for i in items
            ],
        )
        created = await proforma_service.create_proforma(session, claims=claims, body=body, request=request)
        return created["id"]

    from app.modules.documents import invoice_service
    from app.modules.documents.schemas import InvoiceCreate, InvoiceItemIn

    body = InvoiceCreate(
        supplier_id=result["supplier_id"],
        invoice_number=number[:100],
        invoice_date=doc_date,
        supplier_gstin=fields.get("supplier_gstin"),
        items=[
            InvoiceItemIn(
                product_variant_id=i["product_variant_id"],
                description=i["description"],
                hsn_code=i["hsn_code"],
                quantity=i["quantity"],
                uom_id=i["uom_id"],
                unit_price=i["unit_price"],
                discount_pct=i["discount_pct"],
                gst_rate=i["gst_rate"],
            )
            for i in items
        ],
    )
    created = await invoice_service.create_invoice(session, claims=claims, body=body, request=request)
    return created["id"]


def _fallback_number(result: dict) -> str:
    """A document with no readable number still has to be filed under
    something traceable, and a random string would be worse than useless."""
    return f"AI-{str(result['id'])[:8].upper()}"


async def reject(
    session: AsyncSession, *, claims: AccessTokenClaims, document_id: UUID, reason: str,
    request: Optional[Request] = None,
) -> dict:
    if len((reason or "").strip()) < 3:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_VALIDATION, "Say why this document is being rejected",
            errors=[{"field": "reason", "message": "A short reason is required"}],
        )
    result = await load_extraction(session, company_id=claims.company_id, document_id=document_id)
    if result["review_status"] == "approved":
        raise ApiError(
            status.HTTP_409_CONFLICT, CODE_INVALID_STATE_TRANSITION,
            "This document was already approved and cannot be rejected.",
        )

    await session.execute(
        text(
            "UPDATE ai_extraction_results SET review_status = 'rejected', reviewed_by = :who, "
            " reviewed_at = now(), rejection_reason = :reason WHERE company_id = :c AND id = :id"
        ),
        {"who": claims.user_id, "reason": reason.strip(), "c": claims.company_id, "id": result["id"]},
    )
    await session.execute(
        text(
            "UPDATE documents SET processing_status = 'rejected', processing_stage = 'Rejected' "
            "WHERE company_id = :c AND id = :id"
        ),
        {"c": claims.company_id, "id": document_id},
    )
    await _record_action(
        session,
        company_id=claims.company_id,
        result_id=result["id"],
        target_type="document",
        target_id=document_id,
        action="reject_document",
        before={"review_status": result["review_status"]},
        after={"review_status": "rejected"},
        reason=reason.strip(),
        reviewer_id=claims.user_id,
    )
    await audit.record(
        session, entity_type="document", action="rejected", claims=claims, entity_id=document_id,
        entity_label=result["document_type"], description=reason.strip(), request=request,
    )
    return {"extraction_result_id": result["id"], "review_status": "rejected"}
