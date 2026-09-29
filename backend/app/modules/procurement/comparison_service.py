"""
Quotation comparison service — 06_BUSINESS_RULES.md §6 (BR-CMP-01..04) and
the comparison arm of §14's state machine: `draft -> decided -> converted`,
`-> discarded`.

BR-CMP-01 asks for a weighted score over "landed cost, delivery days,
supplier on-time %, quality score and warranty" with the weights returned
in the response. `company_settings.comparison_weights` already carries all
five weights (seeded), but only two of the five inputs actually exist as
real data anywhere in this schema: a quotation's own unit price (+ freight/
other apportioned across its lines) and its `delivery_period_days`. There
is no supplier on-time/quality/warranty metric table or view — the
`v_supplier_performance` view 04_API_SPECIFICATION.md's example response
names was never built. Rather than inventing numbers for the other three
weights, this re-normalises over just {cost, delivery} and says so in the
returned reason string — matching this codebase's "honest, never
fabricated" rule for anything computed (see frontend-correction-phase-
state's "Honest AI" section). When supplier performance data exists, the
other three weights slot in without changing this function's shape.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from fastapi import Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.db import set_tenant
from app.core.errors import (
    CODE_BUSINESS_RULE_VIOLATION,
    CODE_INCOMPARABLE,
    CODE_NO_ITEMS,
    CODE_NOT_FOUND,
    CODE_QUOTATION_EXPIRED,
    ApiError,
)
from app.core.money import D
from app.core.security import AccessTokenClaims
from app.modules.procurement import po_service
from app.modules.procurement.schemas import ComparisonBuildRequest, ComparisonConvertRequest, ComparisonOverrideRequest, PoCreate, PoItemIn

_DEFAULT_WEIGHTS = {"cost": 0.5, "delivery": 0.2, "on_time": 0.15, "quality": 0.1, "warranty": 0.05}


async def _company_weights(session: AsyncSession, *, company_id: str) -> dict:
    row = (
        await session.execute(text("SELECT comparison_weights FROM company_settings WHERE company_id = :c"), {"c": company_id})
    ).mappings().first()
    return (row or {}).get("comparison_weights") or _DEFAULT_WEIGHTS


async def _gather_matrix(
    session: AsyncSession, *, company_id: str, rfq_id: UUID, supplier_ids: list[UUID], weights: dict
) -> dict:
    rfq_items = (
        await session.execute(
            text(
                "SELECT id, line_no, product_variant_id, quantity FROM rfq_items "
                "WHERE rfq_id = :rfq_id AND company_id = :c ORDER BY line_no"
            ),
            {"rfq_id": rfq_id, "c": company_id},
        )
    ).mappings().all()

    quotations = (
        await session.execute(
            text(
                "SELECT id, supplier_id, quotation_number, valid_until, total_amount, taxable_value, "
                "freight_amount, other_charges, delivery_period_days "
                "FROM supplier_quotations WHERE company_id = :c AND rfq_id = :rfq_id AND status = 'approved' "
                "AND supplier_id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"c": company_id, "rfq_id": rfq_id, "ids": supplier_ids},
        )
    ).mappings().all()
    quotation_ids = [q["id"] for q in quotations]
    quotations_by_id = {q["id"]: q for q in quotations}

    supplier_names = {}
    if quotations:
        rows = (
            await session.execute(
                text("SELECT id, name FROM suppliers WHERE company_id = :c AND id = ANY(CAST(:ids AS uuid[]))"),
                {"c": company_id, "ids": [q["supplier_id"] for q in quotations]},
            )
        ).mappings().all()
        supplier_names = {r["id"]: r["name"] for r in rows}

    items: list = []
    if quotation_ids:
        items = (
            await session.execute(
                text(
                    "SELECT id, quotation_id, rfq_item_id, unit_price, gst_rate, line_net, line_total, "
                    "is_available, availability_note FROM supplier_quotation_items "
                    "WHERE company_id = :c AND quotation_id = ANY(CAST(:ids AS uuid[])) AND rfq_item_id IS NOT NULL"
                ),
                {"c": company_id, "ids": quotation_ids},
            )
        ).mappings().all()

    # Apportion each quotation's freight+other across its own lines by
    # taxable-value share, so a cell's "landed cost" reflects delivered
    # cost, not just the quoted unit price.
    taxable_by_quotation: dict = {}
    for it in items:
        taxable_by_quotation[it["quotation_id"]] = taxable_by_quotation.get(it["quotation_id"], Decimal("0")) + D(it["line_net"])

    items_by_rfq_item: dict = {}
    for it in items:
        items_by_rfq_item.setdefault(it["rfq_item_id"], []).append(it)

    cost_weight = Decimal(str(weights.get("cost", 0.5)))
    delivery_weight = Decimal(str(weights.get("delivery", 0.2)))
    weight_sum = cost_weight + delivery_weight
    if weight_sum <= 0:
        cost_weight, delivery_weight, weight_sum = Decimal("1"), Decimal("0"), Decimal("1")

    rows_out = []
    warnings = []
    for rfq_item in rfq_items:
        candidates = items_by_rfq_item.get(rfq_item["id"], [])
        cells = []
        for it in candidates:
            q = quotations_by_id[it["quotation_id"]]
            addon = q["freight_amount"] + q["other_charges"]
            taxable_total = taxable_by_quotation.get(it["quotation_id"], Decimal("0"))
            share = (D(it["line_net"]) / taxable_total) if taxable_total > 0 else (Decimal("1") / max(len(candidates), 1))
            apportioned = D(addon) * share
            landed_unit_cost = D(it["unit_price"]) + (apportioned / D(rfq_item["quantity"]) if D(rfq_item["quantity"]) else Decimal("0"))
            cells.append(
                {
                    "supplier_id": q["supplier_id"],
                    "quotation_id": it["quotation_id"],
                    "quotation_item_id": it["id"],
                    "unit_price": float(it["unit_price"]),
                    "landed_unit_cost": float(landed_unit_cost.quantize(Decimal("0.0001"))),
                    "line_total": float(it["line_total"]),
                    "gst_rate": float(it["gst_rate"]),
                    "is_available": it["is_available"],
                    "availability_note": it["availability_note"],
                    "is_lowest": False,
                    "delivery_period_days": q["delivery_period_days"],
                }
            )

        available = [c for c in cells if c["is_available"]]
        recommended = None
        score = None
        spread_pct = None
        if available:
            min_cost = min(c["landed_unit_cost"] for c in available)
            max_cost = max(c["landed_unit_cost"] for c in available)
            spread_pct = round(((max_cost - min_cost) / min_cost) * 100, 2) if min_cost else 0.0
            for c in available:
                if c["landed_unit_cost"] == min_cost:
                    c["is_lowest"] = True

            delivery_days = [c["delivery_period_days"] for c in available if c["delivery_period_days"]]
            min_delivery = min(delivery_days) if delivery_days else None
            best = None
            best_score = None
            for c in available:
                cost_score = 100.0 * (min_cost / c["landed_unit_cost"]) if c["landed_unit_cost"] else 0.0
                if c["delivery_period_days"] and min_delivery:
                    delivery_score = 100.0 * (min_delivery / c["delivery_period_days"])
                else:
                    delivery_score = 50.0  # neutral — no delivery estimate to score
                combined = float(
                    (Decimal(str(cost_score)) * cost_weight + Decimal(str(delivery_score)) * delivery_weight) / weight_sum
                )
                if best_score is None or combined > best_score:
                    best_score, best = combined, c
            recommended = best
            score = round(best_score, 3)

            if spread_pct and spread_pct > 5:
                warnings.append({"code": "PRICE_SPREAD_HIGH", "rfq_item_id": str(rfq_item["id"]), "spread_pct": spread_pct})

        rows_out.append(
            {
                "rfq_item_id": rfq_item["id"],
                "product_variant_id": rfq_item["product_variant_id"],
                "quantity": float(rfq_item["quantity"]),
                "cells": cells,
                "recommended_quotation_item_id": recommended["quotation_item_id"] if recommended else None,
                "recommended_supplier_id": recommended["supplier_id"] if recommended else None,
                "recommendation_reason": (
                    f"Best weighted score on landed cost + delivery "
                    f"(cost {float(cost_weight/weight_sum):.0%} / delivery {float(delivery_weight/weight_sum):.0%} of this "
                    f"tenant's comparison_weights; on-time/quality/warranty weights not applied — no supplier "
                    f"performance data collected yet)."
                    if recommended
                    else None
                ),
                "recommendation_score": score,
                "price_spread_pct": spread_pct,
            }
        )

    today = date.today()
    suppliers_out = []
    covered_by_quotation: dict = {}
    for row in rows_out:
        for c in row["cells"]:
            covered_by_quotation.setdefault(c["quotation_id"], set()).add(row["rfq_item_id"])
    for q in quotations:
        is_expired = bool(q["valid_until"] and q["valid_until"] < today)
        suppliers_out.append(
            {
                "supplier_id": q["supplier_id"],
                "name": supplier_names.get(q["supplier_id"], ""),
                "quotation_id": q["id"],
                "quotation_number": q["quotation_number"],
                "valid_until": q["valid_until"],
                "is_expired": is_expired,
                "total_amount": float(q["total_amount"]),
                "missing_lines": len(rfq_items) - len(covered_by_quotation.get(q["id"], set())),
            }
        )
        if not is_expired and q["valid_until"] and q["valid_until"] <= today + timedelta(days=7):
            warnings.append({"code": "QUOTATION_EXPIRING", "supplier_id": str(q["supplier_id"]), "valid_until": str(q["valid_until"])})

    # BR-CMP-03: single-supplier baseline only from a supplier covering
    # every row with an available cell.
    full_coverage_totals = []
    for q in quotations:
        rows_for_q = {
            row["rfq_item_id"]: next((c for c in row["cells"] if c["quotation_id"] == q["id"] and c["is_available"]), None)
            for row in rows_out
        }
        if all(rows_for_q.values()):
            full_coverage_totals.append((q["id"], sum(D(c["line_total"]) for c in rows_for_q.values())))
    single_supplier_best = min(full_coverage_totals, key=lambda t: t[1]) if full_coverage_totals else None

    split_total = Decimal("0")
    for row in rows_out:
        pick = next((c for c in row["cells"] if c["quotation_item_id"] == row["recommended_quotation_item_id"]), None)
        if pick:
            split_total += D(pick["line_total"])

    return {
        "rfq_items": rfq_items,
        "rows": rows_out,
        "suppliers": suppliers_out,
        "warnings": warnings,
        "single_supplier_best_total": float(single_supplier_best[1]) if single_supplier_best else None,
        "split_total": float(split_total) if rows_out else None,
    }


async def _load(session: AsyncSession, *, company_id: str, comparison_id: UUID) -> dict:
    header = (
        await session.execute(
            text(
                "SELECT id, rfq_id, name, compared_supplier_ids, strategy, single_supplier_best_total, "
                "split_total, projected_savings, decided_by, decided_at, status, notes "
                "FROM quotation_comparisons WHERE id = :id AND company_id = :c"
            ),
            {"id": comparison_id, "c": company_id},
        )
    ).mappings().first()
    if header is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Comparison not found")

    weights = await _company_weights(session, company_id=company_id)
    matrix = await _gather_matrix(
        session, company_id=company_id, rfq_id=header["rfq_id"], supplier_ids=list(header["compared_supplier_ids"] or []), weights=weights
    )

    lines = (
        await session.execute(
            text(
                "SELECT id, rfq_item_id, selected_quotation_item_id, selected_supplier_id, override_reason "
                "FROM quotation_comparison_lines WHERE comparison_id = :id AND company_id = :c"
            ),
            {"id": comparison_id, "c": company_id},
        )
    ).mappings().all()
    lines_by_rfq_item = {l["rfq_item_id"]: l for l in lines}

    rows = []
    for row in matrix["rows"]:
        line = lines_by_rfq_item.get(row["rfq_item_id"], {})
        selected_supplier = line.get("selected_supplier_id")
        cell = next((c for c in row["cells"] if c["quotation_item_id"] == line.get("selected_quotation_item_id")), None)
        rows.append(
            {
                "line_id": line.get("id"),
                **row,
                "selected_quotation_item_id": line.get("selected_quotation_item_id"),
                "selected_supplier_id": selected_supplier or (cell["supplier_id"] if cell else None),
                "override_reason": line.get("override_reason"),
            }
        )

    out = dict(header)
    out["rows"] = rows
    out["suppliers"] = matrix["suppliers"]
    out["warnings"] = matrix["warnings"]
    return out


async def list_comparisons(session: AsyncSession, *, company_id: str, rfq_id: Optional[UUID] = None, limit: int = 100, offset: int = 0) -> list[dict]:
    where = ["company_id = :c"]
    params: dict = {"c": company_id, "limit": limit, "offset": offset}
    if rfq_id:
        where.append("rfq_id = :rfq_id")
        params["rfq_id"] = rfq_id
    rows = (
        await session.execute(
            text(
                "SELECT id FROM quotation_comparisons WHERE " + " AND ".join(where) +
                " ORDER BY id DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
    ).mappings().all()
    return [await _load(session, company_id=company_id, comparison_id=r["id"]) for r in rows]


async def get_comparison(session: AsyncSession, *, company_id: str, comparison_id: UUID) -> dict:
    return await _load(session, company_id=company_id, comparison_id=comparison_id)


async def build_comparison(
    session: AsyncSession, *, claims: AccessTokenClaims, body: ComparisonBuildRequest, request: Optional[Request] = None
) -> dict:
    rfq = (
        await session.execute(text("SELECT id FROM rfqs WHERE id = :id AND company_id = :c"), {"id": body.rfq_id, "c": claims.company_id})
    ).mappings().first()
    if rfq is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "RFQ not found")

    if body.quotation_ids:
        chosen = (
            await session.execute(
                text(
                    "SELECT id, supplier_id, rfq_id FROM supplier_quotations "
                    "WHERE company_id = :c AND id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"c": claims.company_id, "ids": body.quotation_ids},
            )
        ).mappings().all()
        found_ids = {r["id"] for r in chosen}
        missing = set(body.quotation_ids) - found_ids
        if missing:
            raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, f"Quotation(s) not found: {missing}")
        # BR-CMP-02: only quotations against this RFQ may be compared together.
        wrong_rfq = [str(r["id"]) for r in chosen if r["rfq_id"] != body.rfq_id]
        if wrong_rfq:
            raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_INCOMPARABLE, f"Quotation(s) {wrong_rfq} were not raised against this RFQ")
        supplier_ids = list({r["supplier_id"] for r in chosen})
    else:
        rows = (
            await session.execute(
                text("SELECT DISTINCT supplier_id FROM supplier_quotations WHERE company_id = :c AND rfq_id = :rfq_id AND status = 'approved'"),
                {"c": claims.company_id, "rfq_id": body.rfq_id},
            )
        ).mappings().all()
        supplier_ids = [r["supplier_id"] for r in rows]

    if not supplier_ids:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_NO_ITEMS, "No approved quotations exist for this RFQ yet")

    weights = await _company_weights(session, company_id=claims.company_id)
    matrix = await _gather_matrix(session, company_id=claims.company_id, rfq_id=body.rfq_id, supplier_ids=supplier_ids, weights=weights)

    comparison_id = uuid4()
    single_best = matrix["single_supplier_best_total"]
    split_total = matrix["split_total"]
    savings = (single_best - split_total) if (single_best is not None and split_total is not None) else None

    await session.execute(
        text(
            "INSERT INTO quotation_comparisons "
            "(id, company_id, rfq_id, name, compared_supplier_ids, strategy, single_supplier_best_total, "
            " split_total, projected_savings) "
            "VALUES (:id, :c, :rfq_id, :name, CAST(:suppliers AS uuid[]), 'lowest_price', :single_best, :split_total, :savings)"
        ),
        {
            "id": comparison_id, "c": claims.company_id, "rfq_id": body.rfq_id, "name": body.name,
            "suppliers": supplier_ids, "single_best": single_best, "split_total": split_total, "savings": savings,
        },
    )

    for row in matrix["rows"]:
        await session.execute(
            text(
                "INSERT INTO quotation_comparison_lines "
                "(company_id, comparison_id, rfq_item_id, product_variant_id, quantity, selected_quotation_item_id, "
                " selected_supplier_id, recommended_quotation_item_id, recommendation_reason, recommendation_score, "
                " price_spread_pct) "
                "VALUES (:c, :comparison_id, :rfq_item_id, :variant, :quantity, :selected_qi, :selected_supplier, "
                " :recommended_qi, :reason, :score, :spread)"
            ),
            {
                "c": claims.company_id, "comparison_id": comparison_id, "rfq_item_id": row["rfq_item_id"],
                "variant": row["product_variant_id"], "quantity": row["quantity"],
                "selected_qi": row["recommended_quotation_item_id"], "selected_supplier": row["recommended_supplier_id"],
                "recommended_qi": row["recommended_quotation_item_id"], "reason": row["recommendation_reason"],
                "score": row["recommendation_score"], "spread": row["price_spread_pct"],
            },
        )

    result = await _load(session, company_id=claims.company_id, comparison_id=comparison_id)
    await audit.record(
        session, entity_type="quotation_comparison", action="created", claims=claims, entity_id=comparison_id,
        entity_label=body.name or f"Comparison for RFQ {body.rfq_id}", after={"status": result["status"], "rfq_id": str(body.rfq_id)},
        request=request,
    )
    await session.commit()
    return result


async def override_line(
    session: AsyncSession, *, claims: AccessTokenClaims, comparison_id: UUID, line_id: UUID, body: ComparisonOverrideRequest, request: Optional[Request] = None
) -> dict:
    before = await _load(session, company_id=claims.company_id, comparison_id=comparison_id)
    if before["status"] not in ("draft", "decided"):
        raise ApiError(status.HTTP_409_CONFLICT, CODE_BUSINESS_RULE_VIOLATION, f"Cannot change selections on a comparison in status {before['status']}")

    line = (
        await session.execute(
            text("SELECT id, rfq_item_id FROM quotation_comparison_lines WHERE id = :id AND comparison_id = :cmp AND company_id = :c"),
            {"id": line_id, "cmp": comparison_id, "c": claims.company_id},
        )
    ).mappings().first()
    if line is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Comparison line not found")

    qi = (
        await session.execute(
            text(
                "SELECT sqi.id, sqi.rfq_item_id, sq.supplier_id, sq.status FROM supplier_quotation_items sqi "
                "JOIN supplier_quotations sq ON sq.id = sqi.quotation_id AND sq.company_id = sqi.company_id "
                "WHERE sqi.id = :id AND sqi.company_id = :c"
            ),
            {"id": body.quotation_item_id, "c": claims.company_id},
        )
    ).mappings().first()
    if qi is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Quotation line not found")
    if qi["rfq_item_id"] != line["rfq_item_id"]:
        # BR-CMP-02: a cell may only be selected for the row it actually quotes.
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_INCOMPARABLE, "That quotation line doesn't quote this RFQ item")
    if qi["status"] != "approved":
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_BUSINESS_RULE_VIOLATION, "Only an approved quotation's lines can be selected")

    await session.execute(
        text(
            "UPDATE quotation_comparison_lines SET selected_quotation_item_id = :qi, selected_supplier_id = :supplier, "
            "override_reason = :reason WHERE id = :id"
        ),
        {"qi": body.quotation_item_id, "supplier": qi["supplier_id"], "reason": body.reason, "id": line_id},
    )
    if before["status"] == "draft":
        await session.execute(
            text("UPDATE quotation_comparisons SET status = 'decided', decided_by = :who, decided_at = now() WHERE id = :id"),
            {"who": claims.user_id, "id": comparison_id},
        )

    after = await _load(session, company_id=claims.company_id, comparison_id=comparison_id)
    await audit.record(
        session, entity_type="quotation_comparison", action="updated", claims=claims, entity_id=comparison_id,
        entity_label=after.get("name") or str(comparison_id), description="Line override", request=request,
    )
    await session.commit()
    return after


async def reset_comparison(session: AsyncSession, *, claims: AccessTokenClaims, comparison_id: UUID, request: Optional[Request] = None) -> dict:
    before = await _load(session, company_id=claims.company_id, comparison_id=comparison_id)
    if before["status"] not in ("draft", "decided"):
        raise ApiError(status.HTTP_409_CONFLICT, CODE_BUSINESS_RULE_VIOLATION, f"Cannot reset a comparison in status {before['status']}")

    await session.execute(
        text(
            "UPDATE quotation_comparison_lines SET selected_quotation_item_id = recommended_quotation_item_id, "
            "selected_supplier_id = (SELECT sq.supplier_id FROM supplier_quotation_items sqi "
            "JOIN supplier_quotations sq ON sq.id = sqi.quotation_id AND sq.company_id = sqi.company_id "
            "WHERE sqi.id = quotation_comparison_lines.recommended_quotation_item_id), override_reason = NULL "
            "WHERE comparison_id = :id AND company_id = :c"
        ),
        {"id": comparison_id, "c": claims.company_id},
    )
    await session.execute(
        text("UPDATE quotation_comparisons SET status = 'draft', decided_by = NULL, decided_at = NULL WHERE id = :id"),
        {"id": comparison_id},
    )
    after = await _load(session, company_id=claims.company_id, comparison_id=comparison_id)
    await audit.record(
        session, entity_type="quotation_comparison", action="updated", claims=claims, entity_id=comparison_id,
        entity_label=after.get("name") or str(comparison_id), description="Reset to recommended", request=request,
    )
    await session.commit()
    return after


async def convert_comparison(
    session: AsyncSession, *, claims: AccessTokenClaims, comparison_id: UUID, body: ComparisonConvertRequest, request: Optional[Request] = None
) -> tuple[list[dict], str]:
    before = await _load(session, company_id=claims.company_id, comparison_id=comparison_id)
    if before["status"] not in ("draft", "decided"):
        raise ApiError(status.HTTP_409_CONFLICT, CODE_BUSINESS_RULE_VIOLATION, f"Cannot convert a comparison in status {before['status']}")

    selections_by_rfq_item = {}
    if body.selections:
        row_by_rfq_item = {r["rfq_item_id"]: r for r in before["rows"]}
        for sel in body.selections:
            if sel.rfq_item_id not in row_by_rfq_item:
                raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_INCOMPARABLE, f"RFQ item {sel.rfq_item_id} is not part of this comparison")
            selections_by_rfq_item[sel.rfq_item_id] = sel.quotation_item_id
    else:
        for row in before["rows"]:
            if not row["selected_quotation_item_id"]:
                raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_NO_ITEMS, f"RFQ item {row['rfq_item_id']} has no selected supplier")
            selections_by_rfq_item[row["rfq_item_id"]] = row["selected_quotation_item_id"]

    # Resolve each selection to its quotation item + parent quotation +
    # source rfq item, and check expiry (BR-QT-03) before anything is written.
    resolved = []
    for rfq_item_id, quotation_item_id in selections_by_rfq_item.items():
        qi = (
            await session.execute(
                text(
                    "SELECT sqi.id AS quotation_item_id, sqi.product_variant_id, sqi.raw_description, sqi.uom_id, "
                    "sqi.unit_price, sqi.discount_pct, sqi.gst_rate, sqi.cess_rate, "
                    "sq.id AS quotation_id, sq.supplier_id, sq.valid_until, sq.status "
                    "FROM supplier_quotation_items sqi "
                    "JOIN supplier_quotations sq ON sq.id = sqi.quotation_id AND sq.company_id = sqi.company_id "
                    "WHERE sqi.id = :id AND sqi.company_id = :c"
                ),
                {"id": quotation_item_id, "c": claims.company_id},
            )
        ).mappings().first()
        if qi is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Quotation line not found")
        if qi["status"] != "approved":
            raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_BUSINESS_RULE_VIOLATION, "Only an approved quotation can be converted")
        if qi["valid_until"] and qi["valid_until"] < date.today() and not body.allow_expired:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_QUOTATION_EXPIRED,
                f"Quotation for supplier {qi['supplier_id']} expired on {qi['valid_until']}; pass allow_expired to use it anyway",
            )
        if not qi["product_variant_id"]:
            raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_BUSINESS_RULE_VIOLATION, "Cannot order a line with no matched product")
        row = next(r for r in before["rows"] if r["rfq_item_id"] == rfq_item_id)
        resolved.append({**qi, "rfq_item_id": rfq_item_id, "quantity": row["quantity"]})

    groups: dict = {}
    for r in resolved:
        groups.setdefault(r["supplier_id"], []).append(r)

    # A PO needs an expected delivery date before it can be submitted, and
    # the documents behind it already say when: the RFQ asked for a date,
    # and each quotation promised a delivery period. Without these defaults
    # every converted PO landed as a draft nobody could submit.
    rfq_expected = (
        await session.execute(
            text("SELECT expected_delivery_date FROM rfqs WHERE id = :id AND company_id = :c"),
            {"id": before["rfq_id"], "c": claims.company_id},
        )
    ).scalar_one_or_none()
    quote_terms = {
        row["id"]: row
        for row in (
            await session.execute(
                text(
                    "SELECT id, delivery_period_days, payment_terms, delivery_terms FROM supplier_quotations "
                    "WHERE company_id = :c AND id = ANY(:ids)"
                ),
                {"c": claims.company_id, "ids": list({r["quotation_id"] for r in resolved})},
            )
        ).mappings().all()
    }

    created_pos: list[dict] = []
    for supplier_id, lines in groups.items():
        terms = quote_terms.get(lines[0]["quotation_id"]) or {}
        expected = body.expected_delivery_date or rfq_expected
        if expected is None and terms.get("delivery_period_days"):
            expected = date.today() + timedelta(days=int(terms["delivery_period_days"]))
        po_body = PoCreate(
            supplier_id=supplier_id,
            delivery_godown_id=body.delivery_godown_id,
            expected_delivery_date=expected,
            payment_terms=body.payment_terms or terms.get("payment_terms"),
            delivery_terms=body.delivery_terms or terms.get("delivery_terms"),
            rfq_id=before["rfq_id"],
            items=[
                PoItemIn(
                    product_variant_id=l["product_variant_id"],
                    description=l["raw_description"],
                    quantity=l["quantity"],
                    uom_id=l["uom_id"],
                    unit_price=float(l["unit_price"]),
                    discount_pct=float(l["discount_pct"]),
                    gst_rate=float(l["gst_rate"]),
                    cess_rate=float(l["cess_rate"]),
                    rfq_item_id=l["rfq_item_id"],
                    quotation_item_id=l["quotation_item_id"],
                )
                for l in lines
            ],
        )
        po = await po_service.create_po(session, claims=claims, body=po_body, request=request)
        # `create_po()` ends with its own `session.commit()` (every service
        # in this module is written to commit its own unit of work). That
        # commit ends the transaction the RLS tenant scope was set on —
        # `set_tenant()`'s `set_config(..., is_local => true)` is
        # transaction-scoped by design (core/db.py) — so the very next
        # statement on this same session would otherwise run with no
        # tenant scope at all and fail RLS. Re-assert it before touching
        # `purchase_orders` again. (Found by this phase's own E2E test:
        # the UPDATE below failed with "invalid input syntax for type
        # uuid: ''" the first time this ran for a second supplier group.)
        await set_tenant(session, UUID(claims.company_id))
        primary_quotation_id = lines[0]["quotation_id"]
        await session.execute(
            text("UPDATE purchase_orders SET quotation_id = :q, comparison_id = :c WHERE id = :id"),
            {"q": primary_quotation_id, "c": comparison_id, "id": po["id"]},
        )
        po["quotation_id"] = primary_quotation_id
        po["comparison_id"] = comparison_id
        created_pos.append(po)

    quotation_ids = list({r["quotation_id"] for r in resolved})
    await session.execute(
        text("UPDATE supplier_quotations SET status = 'converted' WHERE id = ANY(CAST(:ids AS uuid[])) AND status = 'approved'"),
        {"ids": quotation_ids},
    )
    await session.execute(
        text("UPDATE quotation_comparisons SET status = 'converted', decided_by = :who, decided_at = now() WHERE id = :id"),
        {"who": claims.user_id, "id": comparison_id},
    )

    after = await _load(session, company_id=claims.company_id, comparison_id=comparison_id)
    await audit.record(
        session, entity_type="quotation_comparison", action="status_changed", claims=claims, entity_id=comparison_id,
        entity_label=after.get("name") or str(comparison_id),
        description=f"Converted to {len(created_pos)} purchase order(s)",
        before={"status": before["status"]}, after={"status": "converted"}, request=request,
    )
    await session.commit()
    return created_pos, "converted"
