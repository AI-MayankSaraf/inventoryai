"""
Document variances -- the shared comparison engine.

Three different comparisons in this system ask the same question in
different clothes: does what the supplier is claiming match what we agreed
and what we actually got?

* `proforma_vs_po`  -- BR-PF-02/03, before any money moves
* `grn_vs_po`       -- what arrived against what was ordered
* `invoice_vs_po` / `invoice_vs_grn` -- the 3-way match

They differ only in which two documents are being held up against each
other, so the recording, severity grading and resolution workflow live here
once rather than three times. Callers work out the pairs of numbers; this
module decides whether a difference matters and writes it down.

Severity comes from the tenant's own tolerances
(`company_settings.variance_price_tolerance_pct` and
`variance_amount_tolerance`), never from a constant in this file -- a 2%
overcharge is noise to one business and a serious problem to another.

Nothing here raises. A variance is a finding, not a failure: the services
that call it decide whether a finding blocks an approval (BR-PF-03 says it
does, above tolerance, unless the caller holds `proforma.approve_variance`).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import D, round2

# `document_variances.variance_type` and `comparison_kind` vocabularies are
# fixed by CHECK constraints in the initial schema; these mirror them so a
# typo fails in Python rather than as a constraint violation mid-transaction.
VARIANCE_TYPES = ("price", "quantity", "tax", "total", "product", "delivery_date")
COMPARISON_KINDS = ("proforma_vs_po", "grn_vs_po", "invoice_vs_po", "invoice_vs_grn")


@dataclass
class Finding:
    """One difference the caller has already computed.

    `base` is the agreed/expected side (the PO, or the GRN for a
    quantity check) and `compare` is what the supplier is claiming. The
    sign of `difference` therefore reads naturally: positive means the
    supplier is asking for more than was agreed.
    """

    variance_type: str
    base_value: Decimal
    compare_value: Decimal
    product_variant_id: Optional[UUID] = None
    base_line_id: Optional[UUID] = None
    compare_line_id: Optional[UUID] = None


async def _tolerances(session: AsyncSession, company_id: UUID) -> tuple[Decimal, Decimal]:
    row = (
        await session.execute(
            text(
                "SELECT COALESCE(variance_price_tolerance_pct, 0) AS pct, "
                "       COALESCE(variance_amount_tolerance, 0) AS amt "
                "FROM company_settings WHERE company_id = :c"
            ),
            {"c": company_id},
        )
    ).mappings().first()
    if row is None:
        return Decimal("0"), Decimal("0")
    return D(row["pct"]), D(row["amt"])


def _severity(
    variance_type: str, difference: Decimal, difference_pct: Decimal, pct_tol: Decimal, amt_tol: Decimal
) -> str:
    """Grade one finding against the tenant's tolerances.

    Within both tolerances it is `info` -- recorded, because the trail is
    the point, but not something to act on. Outside one of them it is a
    `warning`. A wrong *product* is always `critical`: no tolerance makes
    receiving the wrong item acceptable, and there is no meaningful
    percentage to compare it against.
    """
    if variance_type == "product":
        return "critical"

    abs_diff = abs(difference)
    abs_pct = abs(difference_pct)

    within_pct = pct_tol > 0 and abs_pct <= pct_tol
    within_amt = amt_tol > 0 and abs_diff <= amt_tol

    # With both tolerances at 0 (the default until a tenant sets them), any
    # non-zero difference is a warning -- the conservative reading, and the
    # one that makes a fresh tenant see its variances rather than silently
    # classifying everything as noise.
    if within_pct or within_amt:
        return "info"
    if abs_pct > (pct_tol * 3 if pct_tol > 0 else Decimal("25")):
        return "critical"
    return "warning"


async def record_variances(
    session: AsyncSession,
    *,
    company_id: UUID,
    comparison_kind: str,
    base_doc_type: str,
    base_doc_id: UUID,
    compare_doc_type: str,
    compare_doc_id: UUID,
    findings: list[Finding],
    replace_existing: bool = True,
) -> list[dict]:
    """Write the findings that actually differ, and return them.

    `replace_existing` clears prior rows for this exact document pair first,
    which is what makes re-running a match idempotent: a second run after a
    correction should leave one accurate set of variances, not two
    contradictory ones. Rows a human has already acted on (`accepted`,
    `disputed`, `resolved`) are kept -- deleting those would erase the
    decision along with the finding.
    """
    if comparison_kind not in COMPARISON_KINDS:
        raise ValueError(f"Unknown comparison_kind: {comparison_kind}")

    if replace_existing:
        await session.execute(
            text(
                "DELETE FROM document_variances "
                "WHERE company_id = :c AND comparison_kind = :kind "
                "AND base_doc_id = :base AND compare_doc_id = :compare AND status = 'open'"
            ),
            {"c": company_id, "kind": comparison_kind, "base": base_doc_id, "compare": compare_doc_id},
        )

    pct_tol, amt_tol = await _tolerances(session, company_id)
    written: list[dict] = []

    for f in findings:
        if f.variance_type not in VARIANCE_TYPES:
            raise ValueError(f"Unknown variance_type: {f.variance_type}")

        base = D(f.base_value)
        compare = D(f.compare_value)
        difference = round2(compare - base)
        if difference == 0 and f.variance_type != "product":
            continue  # Not a variance. Recording zeros would bury the real ones.

        difference_pct = round2(difference / base * 100) if base != 0 else Decimal("0")
        severity = _severity(f.variance_type, difference, difference_pct, pct_tol, amt_tol)

        row_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO document_variances "
                "(id, company_id, variance_type, comparison_kind, base_doc_type, base_doc_id, base_line_id, "
                " compare_doc_type, compare_doc_id, compare_line_id, product_variant_id, "
                " base_value, compare_value, difference, difference_pct, severity, status) "
                "VALUES (:id, :c, :vtype, :kind, :base_type, :base_id, :base_line, "
                " :compare_type, :compare_id, :compare_line, :variant, "
                " :base_value, :compare_value, :difference, :difference_pct, :severity, 'open')"
            ),
            {
                "id": row_id,
                "c": company_id,
                "vtype": f.variance_type,
                "kind": comparison_kind,
                "base_type": base_doc_type,
                "base_id": base_doc_id,
                "base_line": f.base_line_id,
                "compare_type": compare_doc_type,
                "compare_id": compare_doc_id,
                "compare_line": f.compare_line_id,
                "variant": f.product_variant_id,
                "base_value": base,
                "compare_value": compare,
                "difference": difference,
                "difference_pct": difference_pct,
                "severity": severity,
            },
        )
        written.append(
            {
                "id": row_id,
                "variance_type": f.variance_type,
                "base_value": base,
                "compare_value": compare,
                "difference": difference,
                "difference_pct": difference_pct,
                "severity": severity,
            }
        )

    return written


async def exceeds_tolerance(
    session: AsyncSession, *, company_id: UUID, compare_doc_id: UUID
) -> bool:
    """Does this document carry any open variance beyond tolerance?

    BR-PF-03's gate. Reads the severity already graded at record time
    rather than re-deriving it, so the answer can never disagree with what
    the variance screen is showing.
    """
    count = (
        await session.execute(
            text(
                "SELECT COUNT(*) FROM document_variances "
                "WHERE company_id = :c AND compare_doc_id = :d "
                "AND status = 'open' AND severity IN ('warning', 'critical')"
            ),
            {"c": company_id, "d": compare_doc_id},
        )
    ).scalar_one()
    return bool(count)


async def list_variances(
    session: AsyncSession,
    *,
    company_id: UUID,
    comparison_kind: Optional[str] = None,
    severity: Optional[str] = None,
    status_filter: Optional[str] = None,
    compare_doc_id: Optional[UUID] = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    where = ["dv.company_id = :c"]
    params: dict = {"c": company_id}

    if comparison_kind:
        where.append("dv.comparison_kind = :kind")
        params["kind"] = comparison_kind
    if severity:
        where.append("dv.severity = :severity")
        params["severity"] = severity
    if status_filter:
        where.append("dv.status = :status_filter")
        params["status_filter"] = status_filter
    if compare_doc_id:
        where.append("dv.compare_doc_id = :compare_doc_id")
        params["compare_doc_id"] = compare_doc_id

    rows = (
        await session.execute(
            text(
                "SELECT dv.id, dv.variance_type, dv.comparison_kind, dv.base_doc_type, dv.base_doc_id, "
                "       dv.base_line_id, dv.compare_doc_type, dv.compare_doc_id, dv.compare_line_id, "
                "       dv.product_variant_id, COALESCE(pv.sku, '') AS sku, "
                "       TRIM(COALESCE(p.name, '') || ' ' || COALESCE(pv.variant_name, '')) AS product_name, "
                "       dv.base_value, dv.compare_value, dv.difference, dv.difference_pct, "
                "       dv.severity, dv.status, dv.resolved_by, dv.resolved_at, dv.resolution_note "
                "FROM document_variances dv "
                "LEFT JOIN product_variants pv ON pv.id = dv.product_variant_id AND pv.company_id = dv.company_id "
                "LEFT JOIN products p ON p.id = pv.product_id AND p.company_id = pv.company_id "
                f"WHERE {' AND '.join(where)} "
                "ORDER BY CASE dv.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, "
                "         ABS(dv.difference) DESC "
                "LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": limit, "offset": offset},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def get_variance(session: AsyncSession, *, company_id: UUID, variance_id: UUID) -> Optional[dict]:
    rows = (
        await session.execute(
            text(
                "SELECT dv.id, dv.variance_type, dv.comparison_kind, dv.base_doc_type, dv.base_doc_id, "
                "       dv.base_line_id, dv.compare_doc_type, dv.compare_doc_id, dv.compare_line_id, "
                "       dv.product_variant_id, COALESCE(pv.sku, '') AS sku, "
                "       TRIM(COALESCE(p.name, '') || ' ' || COALESCE(pv.variant_name, '')) AS product_name, "
                "       dv.base_value, dv.compare_value, dv.difference, dv.difference_pct, "
                "       dv.severity, dv.status, dv.resolved_by, dv.resolved_at, dv.resolution_note "
                "FROM document_variances dv "
                "LEFT JOIN product_variants pv ON pv.id = dv.product_variant_id AND pv.company_id = dv.company_id "
                "LEFT JOIN products p ON p.id = pv.product_id AND p.company_id = pv.company_id "
                "WHERE dv.id = :id AND dv.company_id = :c"
            ),
            {"id": variance_id, "c": company_id},
        )
    ).mappings().first()
    return dict(rows) if rows else None


async def resolve_variance(
    session: AsyncSession,
    *,
    company_id: UUID,
    variance_id: UUID,
    status: str,
    note: str,
    resolved_by: UUID,
) -> Optional[dict]:
    """Close a variance with a decision and a reason.

    The note is required by the caller, not defaulted here: "accepted" with
    no explanation is exactly the audit gap this table exists to close.
    """
    updated = (
        await session.execute(
            text(
                "UPDATE document_variances SET status = :status, resolution_note = :note, "
                " resolved_by = :who, resolved_at = now() "
                "WHERE id = :id AND company_id = :c RETURNING id"
            ),
            {"status": status, "note": note, "who": resolved_by, "id": variance_id, "c": company_id},
        )
    ).mappings().first()
    if updated is None:
        return None
    return await get_variance(session, company_id=company_id, variance_id=variance_id)
