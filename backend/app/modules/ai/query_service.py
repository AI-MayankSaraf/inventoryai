"""
Reads for the document list, the review screen and the mapping screen.

Kept apart from the pipeline and the review door so that the modules that
*write* stay small enough to audit: everything in here is a SELECT.

`totals` on the review screen deserves a note. It is computed here from
the reviewed quantities and prices rather than read from the document,
which makes it a *preview* of what approval will produce. The figure the
screen shows and the figure the money engine stores therefore come from the
same inputs, and a reviewer who sees a total they disagree with is looking
at their own lines, not at a number the model invented (BR-AI-02).
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai import providers

_DOCUMENT_SELECT = """
    SELECT d.id, d.original_filename, d.mime_type, d.file_extension, d.file_size_bytes,
           d.sha256_hash, d.page_count, d.document_type, d.document_type_confidence,
           d.supplier_id, COALESCE(s.name, '') AS supplier_name, d.supplier_confidence,
           d.processing_status, d.processing_stage, COALESCE(d.processing_progress, 0) AS processing_progress,
           d.extraction_confidence, d.items_found, d.error_code, d.error_message, d.source,
           d.uploaded_by, COALESCE(u.full_name, '') AS uploaded_by_name, d.uploaded_at,
           (SELECT r.id FROM ai_extraction_results r
             WHERE r.company_id = d.company_id AND r.document_id = d.id AND r.superseded_by IS NULL
             LIMIT 1) AS extraction_result_id
      FROM documents d
      LEFT JOIN suppliers s ON s.id = d.supplier_id
      LEFT JOIN users u ON u.id = d.uploaded_by
"""


async def list_documents(
    session: AsyncSession,
    *,
    company_id: str,
    q: Optional[str] = None,
    status_filter: Optional[str] = None,
    document_type: Optional[str] = None,
    supplier_id: Optional[UUID] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    where = [
        "d.company_id = :c",
        "NOT d.is_archived",
        # Attachments (product photos, a GRN's challan) live in `documents`
        # too but were never sent for reading — every AI upload is queued
        # the moment it lands — so they belong on their record, not here.
        "d.processing_status <> 'uploaded'",
    ]
    params: dict = {"c": company_id, "limit": limit, "offset": offset}
    if q:
        where.append("(d.original_filename ILIKE :q OR COALESCE(s.name, '') ILIKE :q)")
        params["q"] = f"%{q.strip()}%"
    if status_filter:
        where.append("d.processing_status = :status")
        params["status"] = status_filter
    if document_type:
        where.append("d.document_type = :dtype")
        params["dtype"] = document_type
    if supplier_id:
        where.append("d.supplier_id = :sup")
        params["sup"] = supplier_id

    rows = (
        await session.execute(
            text(f"{_DOCUMENT_SELECT} WHERE {' AND '.join(where)} ORDER BY d.uploaded_at DESC LIMIT :limit OFFSET :offset"),
            params,
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def get_document(session: AsyncSession, *, company_id: str, document_id: UUID) -> Optional[dict]:
    row = (
        await session.execute(
            text(f"{_DOCUMENT_SELECT} WHERE d.company_id = :c AND d.id = :id"),
            {"c": company_id, "id": document_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def job_status(session: AsyncSession, *, company_id: str, document_id: UUID) -> Optional[dict]:
    document = await get_document(session, company_id=company_id, document_id=document_id)
    if document is None:
        return None
    job = (
        await session.execute(
            text(
                "SELECT id, status, stage, progress, duration_ms, error_code, error_message "
                "FROM ai_processing_jobs WHERE company_id = :c AND document_id = :d "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"c": company_id, "d": document_id},
        )
    ).mappings().first()
    return {
        "document_id": document_id,
        "job_id": job["id"] if job else None,
        "processing_status": document["processing_status"],
        "processing_stage": document["processing_stage"],
        "processing_progress": document["processing_progress"] or 0,
        "extraction_confidence": document["extraction_confidence"],
        "items_found": document["items_found"],
        "extraction_result_id": document["extraction_result_id"],
        "duration_ms": job["duration_ms"] if job else None,
        "error_code": document["error_code"],
        "error_message": document["error_message"],
    }


async def source_documents(
    session: AsyncSession, *, company_id: str, linked_type: str, linked_id: UUID
) -> list[dict]:
    """The files a business record was made from (`document_links`)."""
    rows = (
        await session.execute(
            text(
                "SELECT d.id, d.original_filename, d.mime_type, d.file_size_bytes, d.document_type, "
                "       d.uploaded_at, l.link_role, l.linked_at "
                "FROM document_links l JOIN documents d ON d.id = l.document_id "
                "WHERE l.company_id = :c AND l.linked_type = :t AND l.linked_id = :id "
                "ORDER BY l.linked_at"
            ),
            {"c": company_id, "t": linked_type, "id": linked_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def get_extraction(session: AsyncSession, *, company_id: str, document_id: UUID) -> Optional[dict]:
    result = (
        await session.execute(
            text(
                "SELECT r.*, COALESCE(s.name, '') AS supplier_name FROM ai_extraction_results r "
                "LEFT JOIN suppliers s ON s.id = r.supplier_id "
                "WHERE r.company_id = :c AND r.document_id = :d AND r.superseded_by IS NULL"
            ),
            {"c": company_id, "d": document_id},
        )
    ).mappings().first()
    if result is None:
        return None

    document = await get_document(session, company_id=company_id, document_id=document_id)
    job = await job_status(session, company_id=company_id, document_id=document_id)

    fields = [
        dict(r)
        for r in (
            await session.execute(
                text(
                    "SELECT * FROM ai_extracted_fields WHERE company_id = :c AND extraction_result_id = :r "
                    "ORDER BY field_key"
                ),
                {"c": company_id, "r": result["id"]},
            )
        ).mappings().all()
    ]

    line_rows = (
        await session.execute(
            text(
                "SELECT l.*, COALESCE(v.sku, '') AS matched_sku, "
                "  TRIM(COALESCE(p.name, '') || COALESCE(' — ' || NULLIF(v.variant_name, ''), '')) AS matched_product_name "
                "FROM ai_extracted_lines l "
                "LEFT JOIN product_variants v ON v.id = COALESCE(l.final_variant_id, l.matched_variant_id) "
                "LEFT JOIN products p ON p.id = v.product_id "
                "WHERE l.company_id = :c AND l.extraction_result_id = :r ORDER BY l.line_no"
            ),
            {"c": company_id, "r": result["id"]},
        )
    ).mappings().all()

    candidate_rows = (
        await session.execute(
            text(
                "SELECT mc.*, COALESCE(v.sku, '') AS sku, "
                "  TRIM(COALESCE(p.name, '') || COALESCE(' — ' || NULLIF(v.variant_name, ''), '')) AS product_name "
                "FROM ai_match_candidates mc "
                "LEFT JOIN product_variants v ON v.id = mc.product_variant_id "
                "LEFT JOIN products p ON p.id = v.product_id "
                "WHERE mc.company_id = :c AND mc.extracted_line_id IN ("
                "  SELECT id FROM ai_extracted_lines WHERE company_id = :c AND extraction_result_id = :r) "
                "ORDER BY mc.extracted_line_id, mc.rank"
            ),
            {"c": company_id, "r": result["id"]},
        )
    ).mappings().all()
    by_line: dict[UUID, list[dict]] = {}
    for row in candidate_rows:
        by_line.setdefault(row["extracted_line_id"], []).append(
            {
                "id": row["id"],
                "product_variant_id": row["product_variant_id"],
                "sku": row["sku"],
                "product_name": row["product_name"],
                "rank": row["rank"],
                "match_method": row["match_method"],
                "score": float(row["score"]) if row["score"] is not None else None,
                "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
                "reasons": _as_list(row["reasons"]),
                "is_selected": row["is_selected"],
            }
        )

    lines = []
    for row in line_rows:
        line = dict(row)
        line["validation_errors"] = _as_list(row["validation_errors"])
        line["candidates"] = by_line.get(row["id"], [])
        lines.append(line)

    totals = _preview_totals(lines)
    unresolved = [l for l in lines if l["final_decision"] is None]
    needing_review = [f for f in fields if f["provenance"] == "needs_review" and not f["corrected_value"]]

    blocking: Optional[str] = None
    if result["review_status"] == "approved":
        blocking = "This document has already been approved."
    elif result["review_status"] == "rejected":
        blocking = "This document was rejected."
    elif not lines:
        # Checked before the supplier: "no supplier" on a page nothing was
        # read from sends the reviewer to fix the wrong thing.
        blocking = (
            "No line items could be read from this document. Reject it and upload the "
            "supplier's PDF or spreadsheet, or a sharper image."
        )
    elif unresolved:
        blocking = (
            f"{len(unresolved)} line{'' if len(unresolved) == 1 else 's'} still need"
            f"{'s' if len(unresolved) == 1 else ''} a decision."
        )
    elif result["supplier_id"] is None:
        blocking = "No supplier is set — a purchase document has to belong to someone."
    elif not [l for l in lines if l["final_decision"] != "skipped"]:
        blocking = "Every line was skipped, so there is nothing to create."

    return {
        "id": result["id"],
        "document": document,
        "job": job,
        "document_type": result["document_type"],
        "schema_mapping_id": result["schema_mapping_id"],
        "supplier_id": result["supplier_id"],
        "supplier_name": result["supplier_name"],
        "supplier_confidence": result["supplier_confidence"],
        "overall_confidence": result["overall_confidence"],
        "review_status": result["review_status"],
        "rejection_reason": result["rejection_reason"],
        "promoted_to_type": result["promoted_to_type"],
        "promoted_to_id": result["promoted_to_id"],
        "fields": fields,
        "lines": lines,
        "totals": totals,
        "unresolved_count": len(unresolved),
        "fields_needing_review": len(needing_review),
        "can_approve": blocking is None,
        "blocking_reason": blocking,
        "pipeline_trace": _as_list(result["pipeline_trace"]),
        "validation_errors": _as_list(result["validation_errors"]),
        "providers": [
            {
                "kind": s.kind,
                "configured": s.configured,
                "provider": s.provider,
                "model_id": s.model_id,
                "note": s.note,
            }
            for s in providers.all_statuses()
        ],
    }


def _preview_totals(lines: list[dict]) -> dict[str, float]:
    """quantity x price, less discount, plus GST — the same arithmetic the
    money engine will do, on the same inputs."""
    subtotal = Decimal("0")
    tax = Decimal("0")
    for line in lines:
        if line["final_decision"] == "skipped":
            continue
        quantity = Decimal(str(line["quantity"] or 0))
        price = Decimal(str(line["unit_price"] or 0))
        discount = Decimal(str(line["discount_pct"] or 0))
        gst = Decimal(str(line["gst_rate"] or 0))
        gross = quantity * price
        taxable = gross - (gross * discount / Decimal(100))
        subtotal += taxable
        tax += taxable * gst / Decimal(100)
    cents = Decimal("0.01")
    subtotal = subtotal.quantize(cents, rounding=ROUND_HALF_UP)
    tax = tax.quantize(cents, rounding=ROUND_HALF_UP)
    return {
        "subtotal": float(subtotal),
        "tax": float(tax),
        "total": float((subtotal + tax).quantize(cents, rounding=ROUND_HALF_UP)),
    }


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


# ------------------------------------------------------- schema mappings


async def list_mappings(
    session: AsyncSession, *, company_id: str, status_filter: Optional[str] = None, limit: int = 100
) -> list[dict]:
    where = ["m.company_id = :c"]
    params: dict = {"c": company_id, "limit": limit}
    if status_filter:
        where.append("m.status = :status")
        params["status"] = status_filter
    rows = (
        await session.execute(
            text(
                "SELECT m.*, COALESCE(s.name, '') AS supplier_name FROM document_schema_mappings m "
                "LEFT JOIN suppliers s ON s.id = m.supplier_id "
                f"WHERE {' AND '.join(where)} "
                # Proposals first: they are the screen's actual worklist.
                # Retired layouts last, because they are history.
                "ORDER BY CASE m.status WHEN 'proposed' THEN 0 WHEN 'confirmed' THEN 1 ELSE 2 END, "
                "  COALESCE(m.last_used_at, m.confirmed_at) DESC NULLS LAST, m.version DESC "
                "LIMIT :limit"
            ),
            params,
        )
    ).mappings().all()
    return [dict(r) | {"fields": [], "unmapped_columns": []} for r in rows]


async def get_mapping(session: AsyncSession, *, company_id: str, mapping_id: UUID) -> Optional[dict]:
    row = (
        await session.execute(
            text(
                "SELECT m.*, COALESCE(s.name, '') AS supplier_name FROM document_schema_mappings m "
                "LEFT JOIN suppliers s ON s.id = m.supplier_id "
                "WHERE m.company_id = :c AND m.id = :id"
            ),
            {"c": company_id, "id": mapping_id},
        )
    ).mappings().first()
    if row is None:
        return None

    fields = [
        dict(f)
        for f in (
            await session.execute(
                text(
                    "SELECT f.*, cf.code AS canonical_code, cf.label AS canonical_label "
                    "FROM document_schema_mapping_fields f "
                    "JOIN canonical_fields cf ON cf.id = f.canonical_field_id "
                    "WHERE f.mapping_id = :m ORDER BY COALESCE(f.source_column_index, 99)"
                ),
                {"m": mapping_id},
            )
        ).mappings().all()
    ]

    # Which columns of the sample file nobody mapped — the reviewer's
    # actual worklist on the mapping screen.
    unmapped: list[str] = []
    if row["sample_document_id"]:
        sample = (
            await session.execute(
                text(
                    "SELECT raw_payload FROM ai_extraction_results "
                    # The live one: `uq_ai_extraction_active` guarantees
                    # there is at most a single row with no successor.
                    "WHERE company_id = :c AND document_id = :d AND superseded_by IS NULL LIMIT 1"
                ),
                {"c": company_id, "d": row["sample_document_id"]},
            )
        ).scalar_one_or_none()
        if sample:
            payload = sample if isinstance(sample, dict) else json.loads(sample)
            mapped = {f["source_column"] for f in fields}
            unmapped = [h for h in payload.get("headers", []) if h and h not in mapped]

    return dict(row) | {"fields": fields, "unmapped_columns": unmapped}


async def list_canonical_fields(
    session: AsyncSession, *, field_group: Optional[str] = None
) -> list[dict]:
    where = "WHERE field_group = :g" if field_group else ""
    rows = (
        await session.execute(
            text(
                "SELECT id, code, label, field_group, data_type, is_required, "
                "COALESCE(synonyms, ARRAY[]::text[]) AS synonyms, description "
                f"FROM canonical_fields {where} ORDER BY field_group, label"
            ),
            {"g": field_group} if field_group else {},
        )
    ).mappings().all()
    return [dict(r) for r in rows]
