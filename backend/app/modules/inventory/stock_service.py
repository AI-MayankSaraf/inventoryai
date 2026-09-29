"""
Stock reads.

Nothing in this file writes. Balances come from `stock_balances` (the
derived cache the ledger maintains in the same transaction as every
posting), never from a live SUM over the ledger -- except in
`verify_balances`, whose whole job is to compare the two.

Two things are computed on read rather than stored, both because
`06_BUSINESS_RULES.md` says so:

* **status** (BR-INV-11) -- `qty = 0 -> out_of_stock`;
  `available <= reorder_point -> low_stock`; else `in_stock`.
* **value** (BR-INV-12) -- `quantity x purchase_price`, standard costing.
  `stock_balances.avg_cost` is maintained by the ledger for the day weighted
  -average costing is switched on, but Phase 1 does not value stock with it.

The grid is one row per *variant x godown*. `stock_balances` is finer than
that -- one row per variant x godown x batch -- so every query here sums
over batches. Forgetting that is how a batch-tracked item ends up listed
several times with a fraction of its stock on each line.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import scoped_godown_filter
from app.core.security import AccessTokenClaims

# Reorder point for a (variant, godown): the per-godown policy row wins,
# the variant's own default is the fallback, and 0 means "not stocked to a
# level" rather than "reorder at zero".
_REORDER = "COALESCE(vgp.reorder_point, pv.reorder_point, 0)"
_REORDER_QTY = "COALESCE(vgp.reorder_qty, pv.reorder_qty, 0)"

# One row per variant x godown, batches summed. Everything below selects
# from this so the grid, the KPIs and the low-stock list can never disagree
# about what "available" means.
_BALANCE_BASE = """
    FROM (
        SELECT company_id, product_variant_id, godown_id,
               SUM(quantity) AS quantity,
               SUM(reserved_quantity) AS reserved_quantity,
               SUM(available_quantity) AS available_quantity
        FROM stock_balances
        GROUP BY company_id, product_variant_id, godown_id
    ) sb
    JOIN product_variants pv ON pv.id = sb.product_variant_id AND pv.company_id = sb.company_id
    JOIN products p ON p.id = pv.product_id AND p.company_id = pv.company_id
    JOIN godowns g ON g.id = sb.godown_id AND g.company_id = sb.company_id
    LEFT JOIN categories c ON c.id = p.category_id AND c.company_id = p.company_id
    LEFT JOIN brands b ON b.id = p.brand_id AND b.company_id = p.company_id
    LEFT JOIN uoms u ON u.id = pv.uom_id
    LEFT JOIN variant_godown_policies vgp
           ON vgp.product_variant_id = sb.product_variant_id
          AND vgp.godown_id = sb.godown_id
          AND vgp.company_id = sb.company_id
"""

_STATUS_EXPR = f"""
    CASE WHEN sb.quantity <= 0 THEN 'out_of_stock'
         WHEN {_REORDER} > 0 AND sb.available_quantity <= {_REORDER} THEN 'low_stock'
         ELSE 'in_stock' END
"""


def _filters(
    claims: AccessTokenClaims,
    *,
    godown_id: Optional[UUID],
    category_id: Optional[UUID],
    brand_id: Optional[UUID],
    q: Optional[str],
    status_filter: Optional[str],
) -> tuple[list[str], dict]:
    where = ["sb.company_id = :c", "pv.deleted_at IS NULL", "p.deleted_at IS NULL", "g.deleted_at IS NULL"]
    params: dict = {"c": claims.company_id}

    # BR-AUTH-12: a scoped user sees only their own godowns, unless they
    # hold `inventory.view_all` (which overrides for read, not for write).
    scope_sql, scope_params = scoped_godown_filter(claims, "sb.godown_id")
    if scope_sql:
        where.append(scope_sql)
        params.update(scope_params)

    if godown_id:
        where.append("sb.godown_id = :godown_id")
        params["godown_id"] = godown_id
    if category_id:
        where.append("p.category_id = :category_id")
        params["category_id"] = category_id
    if brand_id:
        where.append("p.brand_id = :brand_id")
        params["brand_id"] = brand_id
    if q:
        where.append("(pv.sku ILIKE :q OR p.name ILIKE :q OR pv.variant_name ILIKE :q)")
        params["q"] = f"%{q}%"
    if status_filter in ("in_stock", "low_stock", "out_of_stock"):
        where.append(f"({_STATUS_EXPR}) = :status_filter")
        params["status_filter"] = status_filter

    return where, params


async def list_stock(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    godown_id: Optional[UUID] = None,
    category_id: Optional[UUID] = None,
    brand_id: Optional[UUID] = None,
    q: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> dict:
    where, params = _filters(
        claims, godown_id=godown_id, category_id=category_id, brand_id=brand_id, q=q, status_filter=status_filter
    )
    clause = " AND ".join(where)

    rows = (
        await session.execute(
            text(
                f"""
                SELECT sb.product_variant_id, sb.godown_id, p.id AS product_id,
                       pv.sku, p.name AS product_name, pv.variant_name,
                       COALESCE(b.name, '') AS brand_name,
                       COALESCE(c.name, '') AS category_name,
                       g.name AS godown_name,
                       sb.quantity, sb.reserved_quantity, sb.available_quantity,
                       COALESCE(u.code, '') AS uom_code,
                       COALESCE(pv.purchase_price, 0) AS purchase_price,
                       {_REORDER} AS reorder_point,
                       ({_STATUS_EXPR}) AS status
                {_BALANCE_BASE}
                WHERE {clause}
                ORDER BY p.name, pv.sku, g.name
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": limit, "offset": offset},
        )
    ).mappings().all()

    # KPIs are for the filtered set, not the whole tenant (§3.7). They are a
    # separate query rather than a tally of `rows` because `rows` is one
    # page -- counting the page would make every KPI depend on pagination.
    kpis = (
        await session.execute(
            text(
                f"""
                SELECT COUNT(DISTINCT sb.product_variant_id) AS total_skus,
                       COALESCE(SUM(sb.quantity * COALESCE(pv.purchase_price, 0)), 0) AS inventory_value,
                       COUNT(*) FILTER (WHERE ({_STATUS_EXPR}) = 'low_stock') AS low_stock,
                       COUNT(*) FILTER (WHERE ({_STATUS_EXPR}) = 'out_of_stock') AS out_of_stock,
                       COUNT(*) AS total
                {_BALANCE_BASE}
                WHERE {clause}
                """
            ),
            params,
        )
    ).mappings().first()

    return {
        "items": [
            {
                "id": f"{r['product_variant_id']}:{r['godown_id']}",
                "product_id": r["product_id"],
                "product_variant_id": r["product_variant_id"],
                "sku": r["sku"],
                "product_name": (
                    f"{r['product_name']} {r['variant_name']}".strip() if r["variant_name"] else r["product_name"]
                ),
                "brand_name": r["brand_name"],
                "category_name": r["category_name"],
                "godown_id": r["godown_id"],
                "godown_name": r["godown_name"],
                "quantity": r["quantity"],
                "reserved_quantity": r["reserved_quantity"],
                "available_quantity": r["available_quantity"],
                "uom_code": r["uom_code"],
                "status": r["status"],
                "value": Decimal(str(r["quantity"])) * Decimal(str(r["purchase_price"])),
            }
            for r in rows
        ],
        "kpis": {
            "total_skus": kpis["total_skus"] or 0,
            "inventory_value": kpis["inventory_value"] or Decimal("0"),
            "low_stock": kpis["low_stock"] or 0,
            "out_of_stock": kpis["out_of_stock"] or 0,
        },
        "total": kpis["total"] or 0,
    }


async def stock_by_variant(session: AsyncSession, *, claims: AccessTokenClaims, product_variant_id: UUID) -> list[dict]:
    """Every godown holding one variant -- the Stock by Godown drill-down."""
    result = await list_stock(session, claims=claims, limit=500)
    return [row for row in result["items"] if row["product_variant_id"] == product_variant_id]


async def list_low_stock(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    godown_id: Optional[UUID] = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    """Below the reorder point, with what it would take to fix it.

    `suggested_qty` is the configured reorder quantity when there is one,
    and otherwise enough to get back to the reorder point -- never zero,
    since a suggestion of zero is worse than no suggestion.

    The preferred supplier and last price come from `supplier_products`,
    which the GRN/PO path maintains. A variant nobody has bought yet simply
    has no supplier here; it is not an error, and the row still lists.
    """
    where, params = _filters(
        claims, godown_id=godown_id, category_id=None, brand_id=None, q=None, status_filter=None
    )
    where.append(f"({_STATUS_EXPR}) IN ('low_stock', 'out_of_stock')")
    clause = " AND ".join(where)

    rows = (
        await session.execute(
            text(
                f"""
                SELECT sb.product_variant_id, sb.godown_id,
                       pv.sku, p.name AS product_name, pv.variant_name,
                       COALESCE(b.name, '') AS brand_name,
                       g.name AS godown_name,
                       sb.quantity, sb.available_quantity,
                       COALESCE(u.code, '') AS uom_code,
                       {_REORDER} AS reorder_point,
                       {_REORDER_QTY} AS reorder_qty,
                       ({_STATUS_EXPR}) AS status,
                       sp.supplier_id AS preferred_supplier_id,
                       COALESCE(s.name, '') AS preferred_supplier_name,
                       COALESCE(sp.last_purchase_price, sp.last_quoted_price, pv.purchase_price, 0) AS last_purchase_price
                {_BALANCE_BASE}
                LEFT JOIN LATERAL (
                    SELECT sp2.supplier_id, sp2.last_purchase_price, sp2.last_quoted_price
                    FROM supplier_products sp2
                    WHERE sp2.company_id = sb.company_id AND sp2.product_variant_id = sb.product_variant_id
                    ORDER BY sp2.is_preferred DESC NULLS LAST, sp2.last_purchase_at DESC NULLS LAST
                    LIMIT 1
                ) sp ON TRUE
                LEFT JOIN suppliers s ON s.id = sp.supplier_id AND s.company_id = sb.company_id
                WHERE {clause}
                ORDER BY (sb.available_quantity - {_REORDER}), p.name
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": limit, "offset": offset},
        )
    ).mappings().all()

    out = []
    for r in rows:
        reorder_point = Decimal(str(r["reorder_point"] or 0))
        available = Decimal(str(r["available_quantity"] or 0))
        reorder_qty = Decimal(str(r["reorder_qty"] or 0))
        suggested = reorder_qty if reorder_qty > 0 else max(reorder_point - available, Decimal("1"))
        out.append(
            {
                "id": f"{r['product_variant_id']}:{r['godown_id']}",
                "product_variant_id": r["product_variant_id"],
                "sku": r["sku"],
                "product_name": (
                    f"{r['product_name']} {r['variant_name']}".strip() if r["variant_name"] else r["product_name"]
                ),
                "brand_name": r["brand_name"],
                "godown_id": r["godown_id"],
                "godown_name": r["godown_name"],
                "current_stock": r["quantity"],
                "reorder_point": reorder_point,
                "suggested_qty": suggested,
                "uom_code": r["uom_code"],
                "preferred_supplier_id": r["preferred_supplier_id"],
                "preferred_supplier_name": r["preferred_supplier_name"],
                "last_purchase_price": r["last_purchase_price"],
                "status": r["status"],
            }
        )
    return out


async def list_batches(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    product_variant_id: UUID,
    godown_id: Optional[UUID] = None,
) -> list[dict]:
    """Batches of one variant with what is actually on hand, so a movement
    form can offer a batch that still has stock rather than every batch ever
    received."""
    params: dict = {"c": claims.company_id, "v": product_variant_id}
    balance_where = ["sb.company_id = :c", "sb.product_variant_id = :v"]

    scope_sql, scope_params = scoped_godown_filter(claims, "sb.godown_id")
    if scope_sql:
        balance_where.append(scope_sql)
        params.update(scope_params)
    if godown_id:
        balance_where.append("sb.godown_id = :godown_id")
        params["godown_id"] = godown_id

    rows = (
        await session.execute(
            text(
                f"""
                SELECT bt.id, bt.product_variant_id, bt.batch_number, bt.supplier_batch_number,
                       bt.manufactured_on, bt.expires_on, bt.mrp, bt.received_on, bt.is_quarantined,
                       COALESCE((
                           SELECT SUM(sb.quantity) FROM stock_balances sb
                           WHERE sb.batch_id = bt.id AND {' AND '.join(balance_where)}
                       ), 0) AS quantity_on_hand
                FROM batches bt
                WHERE bt.company_id = :c AND bt.product_variant_id = :v
                ORDER BY bt.expires_on NULLS LAST, bt.batch_number
                """
            ),
            params,
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def verify_balances(session: AsyncSession, *, claims: AccessTokenClaims) -> dict:
    """BR-INV-02 on demand: every `stock_balances` row must equal the sum of
    its own ledger rows. The nightly job re-derives on drift; this endpoint
    only reports, because silently rewriting a balance from an API call
    would hide exactly the bug it is meant to surface.
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT sb.product_variant_id, sb.godown_id, sb.batch_id,
                       sb.quantity AS balance_quantity,
                       COALESCE(led.total, 0) AS ledger_quantity
                FROM stock_balances sb
                LEFT JOIN (
                    SELECT company_id, product_variant_id, godown_id, batch_id, SUM(quantity) AS total
                    FROM inventory_transactions
                    GROUP BY company_id, product_variant_id, godown_id, batch_id
                ) led
                  ON led.company_id = sb.company_id
                 AND led.product_variant_id = sb.product_variant_id
                 AND led.godown_id = sb.godown_id
                 AND COALESCE(led.batch_id, '00000000-0000-0000-0000-000000000000'::uuid)
                   = COALESCE(sb.batch_id, '00000000-0000-0000-0000-000000000000'::uuid)
                WHERE sb.company_id = :c
                """
            ),
            {"c": claims.company_id},
        )
    ).mappings().all()

    drifts = [
        {
            "product_variant_id": r["product_variant_id"],
            "godown_id": r["godown_id"],
            "batch_id": r["batch_id"],
            "balance_quantity": r["balance_quantity"],
            "ledger_quantity": r["ledger_quantity"],
            "drift": Decimal(str(r["balance_quantity"])) - Decimal(str(r["ledger_quantity"])),
        }
        for r in rows
        if Decimal(str(r["balance_quantity"])) != Decimal(str(r["ledger_quantity"]))
    ]
    return {"checked": len(rows), "ok": not drifts, "drifts": drifts}
