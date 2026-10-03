"""
The dashboard roll-up.

`04_API_SPECIFICATION.md` §3.23 asks for one endpoint returning all five
blocks, and the frontend's own comment says why: "one query feeds every
tile, the chart, the low-stock table and the feed, so a KPI can never
disagree with the list behind it (I12)." Two endpoints would let the tile
say 23 low-stock items while the table under it lists 19.

Every figure is derived from a real table. The stock blocks reuse
`stock_service` rather than re-deriving status and value with a second copy
of the same SQL -- if BR-INV-11's thresholds ever change, they change in
one place and the dashboard follows.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import procurement_godown_filter
from app.core.security import AccessTokenClaims
from app.modules.inventory import stock_service

# The entity types worth surfacing in a feed a buyer reads every morning.
# A product edit or a settings change is audited, but it is not "activity"
# in the sense this panel means, and mixing them buries the documents.
_ACTIVITY_ENTITIES = (
    "purchase_order",
    "goods_receipt",
    "rfq",
    "supplier_quotation",
    "quotation_comparison",
    "stock_transfer",
    "supplier_invoice",
    "purchase_return",
)

_ACTION_PHRASES = {
    "created": "created",
    "updated": "updated",
    "deleted": "deleted",
    "status_changed": "status changed",
    "approved": "approved",
    "rejected": "rejected",
    "sent": "sent",
    "confirmed": "confirmed",
    "cancelled": "cancelled",
    "submitted": "submitted for approval",
    "closed": "closed",
    "reversed": "reversed",
}

_ENTITY_NOUNS = {
    "purchase_order": "Purchase order",
    "goods_receipt": "Goods receipt",
    "rfq": "RFQ",
    "supplier_quotation": "Quotation",
    "quotation_comparison": "Comparison",
    "stock_transfer": "Stock transfer",
    "supplier_invoice": "Supplier invoice",
    "purchase_return": "Purchase return",
}


async def dashboard_summary(
    session: AsyncSession, *, claims: AccessTokenClaims, godown_id: Optional[UUID] = None
) -> dict:
    stock = await stock_service.list_stock(session, claims=claims, godown_id=godown_id, limit=1000)
    kpis = stock["kpis"]
    rows = stock["items"]

    in_stock = sum(1 for r in rows if r["status"] == "in_stock")
    low_stock_rows = await stock_service.list_low_stock(session, claims=claims, godown_id=godown_id, limit=8)

    # Security audit H3 / BR-AUTH-12: a godown-scoped user's tiles count
    # their own godowns only. Each fragment is "" (no restriction) for an
    # all-godowns user. The fragments share one bind parameter.
    po_scope, scope_params = procurement_godown_filter(claims, "delivery_godown_id")
    rfq_scope, _ = procurement_godown_filter(claims, "delivery_godown_id", include_null=True)
    godown_scope, _ = procurement_godown_filter(claims, "id")
    po_and = f" AND {po_scope}" if po_scope else ""
    rfq_and = f" AND {rfq_scope}" if rfq_scope else ""
    godown_and = f" AND {godown_scope}" if godown_scope else ""

    counts = (
        await session.execute(
            text(
                f"""
                SELECT
                  (SELECT COUNT(*) FROM godowns
                    WHERE company_id = :c AND deleted_at IS NULL AND is_active{godown_and}) AS godown_count,
                  -- Neither `products` nor `product_variants` carries a
                  -- created_at column, so "added this month" cannot come
                  -- from the catalogue itself. The audit log is the actual
                  -- record of when a variant was created, so it is counted
                  -- from there. Consequence worth knowing: variants that
                  -- pre-date auditing (or arrived via a seed) have no such
                  -- row and are not counted -- this figure can understate,
                  -- never overstate, which is the right way round for a
                  -- "new this month" tile.
                  (SELECT COUNT(DISTINCT entity_id) FROM audit_logs
                    WHERE company_id = :c AND entity_type = 'product_variant'
                      AND action = 'created'
                      AND created_at >= date_trunc('month', CURRENT_DATE)) AS skus_added_this_month,
                  (SELECT COUNT(*) FROM purchase_orders
                    WHERE company_id = :c
                      AND status IN ('draft', 'pending_approval', 'approved', 'sent',
                                     'acknowledged', 'partially_received'){po_and}) AS pending_pos,
                  (SELECT COALESCE(SUM(total_amount), 0) FROM purchase_orders
                    WHERE company_id = :c
                      AND status IN ('draft', 'pending_approval', 'approved', 'sent',
                                     'acknowledged', 'partially_received'){po_and}) AS po_value_pending,
                  (SELECT COUNT(*) FROM rfqs
                    WHERE company_id = :c
                      AND status IN ('sent', 'partially_quoted', 'quoted', 'under_review'){rfq_and}) AS open_rfqs,
                  (SELECT COUNT(*) FROM supplier_quotations
                    WHERE company_id = :c AND status IN ('draft', 'under_review')) AS quotations_pending,
                  (SELECT COUNT(*) FROM purchase_orders
                    WHERE company_id = :c AND status = 'pending_approval'{po_and}) AS approvals_pending,
                  (SELECT COUNT(*) FROM purchase_orders
                    WHERE company_id = :c
                      AND status IN ('sent', 'acknowledged', 'partially_received'){po_and}) AS deliveries_pending
                """
            ),
            {"c": claims.company_id, **scope_params},
        )
    ).mappings().first()

    # Security audit H3: the feed is audit-log rows, so it needs `audit.view`
    # — the same gate as the audit trail screen. Without it the panel is
    # simply empty rather than a side door into the log.
    activity_rows = [] if "audit.view" not in claims.permissions else (
        await session.execute(
            text(
                """
                SELECT id, entity_type, entity_id, COALESCE(entity_label, '') AS entity_label,
                       action, description, COALESCE(actor_name, (SELECT u.full_name FROM users u WHERE u.id = audit_logs.actor_user_id), '') AS actor_name, created_at
                FROM audit_logs
                WHERE company_id = :c AND entity_type = ANY(:types)
                ORDER BY created_at DESC
                LIMIT 8
                """
            ),
            {"c": claims.company_id, "types": list(_ACTIVITY_ENTITIES)},
        )
    ).mappings().all()

    activity = []
    for r in activity_rows:
        noun = _ENTITY_NOUNS.get(r["entity_type"], r["entity_type"].replace("_", " ").capitalize())
        phrase = _ACTION_PHRASES.get(r["action"], r["action"].replace("_", " "))
        label = r["entity_label"] or ""
        activity.append(
            {
                "id": r["id"],
                "entity_type": r["entity_type"],
                "entity_id": r["entity_id"],
                "action": r["action"],
                "title": f"{noun} {label}".strip(),
                # The audit row's own description when it has one; otherwise
                # say who did what, which is the minimum that makes a feed
                # entry useful. Never a fabricated summary.
                "detail": r["description"] or f"{phrase.capitalize()} by {r['actor_name'] or 'system'}",
                "created_at": r["created_at"],
            }
        )

    return {
        "kpis": {
            "total_skus": kpis["total_skus"],
            "low_stock_items": kpis["low_stock"],
            "out_of_stock": kpis["out_of_stock"],
            "inventory_value": kpis["inventory_value"],
            "pending_pos": counts["pending_pos"] or 0,
            "po_value_pending": counts["po_value_pending"] or Decimal("0"),
            "godown_count": counts["godown_count"] or 0,
            "skus_added_this_month": counts["skus_added_this_month"] or 0,
        },
        "stock_status": [
            {"key": "in_stock", "value": in_stock},
            {"key": "low_stock", "value": kpis["low_stock"]},
            {"key": "out_of_stock", "value": kpis["out_of_stock"]},
        ],
        "low_stock": [
            {
                "product_variant_id": r["product_variant_id"],
                "sku": r["sku"],
                "product_name": r["product_name"],
                "godown_name": r["godown_name"],
                "current_stock": r["current_stock"],
                "reorder_point": r["reorder_point"],
                "uom_code": r["uom_code"],
                "status": r["status"],
            }
            for r in low_stock_rows
        ],
        "activity": activity,
        "procurement": [
            {"key": "open_rfqs", "value": counts["open_rfqs"] or 0},
            {"key": "quotations", "value": counts["quotations_pending"] or 0},
            {"key": "approvals", "value": counts["approvals_pending"] or 0},
            {"key": "deliveries", "value": counts["deliveries_pending"] or 0},
        ],
    }
