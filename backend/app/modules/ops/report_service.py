"""
Reports.

Each report is one SQL statement plus a column spec. The envelope the
Reports screen already renders -- `{key, title, generated_at, columns,
rows, totals}` -- carries its own column definitions, so a report can be
added here without the frontend knowing anything about it: the table is
drawn from whatever `columns` says.

Two deliberate choices:

* **Every figure is computed in SQL, not in Python over fetched rows.**
  A report over a year of movements should not pull a year of movements
  into memory to add them up.
* **Totals are only emitted where a total means something.** Summing a
  column of GST *rates*, or of reorder points, produces a number that looks
  authoritative and means nothing. Only money and quantity columns are
  totalled, and each report says which.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import scoped_godown_filter
from app.core.security import AccessTokenClaims


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    align: Optional[str] = None
    format: Optional[str] = None


@dataclass(frozen=True)
class ReportSpec:
    key: str
    name: str
    description: str
    group: str
    params: tuple[str, ...]
    columns: tuple[Column, ...]
    sql: str
    # Columns worth adding up. Everything else is left alone.
    # Never a quantity column that spans products: 12 coils + 2,400 metres
    # + 117 kg is not a number anyone can use. Money and counts only.
    total_columns: tuple[str, ...] = ()
    # Reports whose rows are per-godown honour the caller's godown scope.
    godown_column: Optional[str] = None


_M = "currency"
_N = "number"
_D = "date"

REPORTS: tuple[ReportSpec, ...] = (
    ReportSpec(
        key="stock_summary",
        name="Stock Summary",
        description="Closing balance and value by product and godown.",
        group="Inventory",
        params=("godown", "category"),
        columns=(
            Column("sku", "SKU"),
            Column("product", "Product"),
            Column("godown", "Godown"),
            Column("quantity", "Quantity", "right", _N),
            Column("value", "Value", "right", _M),
        ),
        total_columns=("value",),
        godown_column="sb.godown_id",
        sql="""
            SELECT pv.sku, TRIM(p.name || ' ' || COALESCE(pv.variant_name, '')) AS product,
                   g.name AS godown, SUM(sb.quantity) AS quantity,
                   ROUND(SUM(sb.quantity * COALESCE(pv.purchase_price, 0)), 2) AS value
            FROM stock_balances sb
            JOIN product_variants pv ON pv.id = sb.product_variant_id AND pv.company_id = sb.company_id
            JOIN products p ON p.id = pv.product_id AND p.company_id = pv.company_id
            JOIN godowns g ON g.id = sb.godown_id AND g.company_id = sb.company_id
            WHERE sb.company_id = :c AND pv.deleted_at IS NULL
              AND (CAST(:godown_id AS uuid) IS NULL OR sb.godown_id = CAST(:godown_id AS uuid))
              AND (CAST(:category_id AS uuid) IS NULL OR p.category_id = CAST(:category_id AS uuid))
              {godown_scope}
            GROUP BY pv.sku, p.name, pv.variant_name, g.name
            ORDER BY p.name, pv.sku, g.name
        """,
    ),
    ReportSpec(
        key="stock_ledger",
        name="Stock Ledger",
        description="Every movement for a product, with running balance.",
        group="Inventory",
        params=("dateRange", "godown", "category"),
        columns=(
            Column("txn_date", "Date", None, _D),
            Column("txn_number", "Document"),
            Column("sku", "SKU"),
            Column("product", "Product"),
            Column("godown", "Godown"),
            Column("txn_type", "Type"),
            Column("quantity", "Quantity", "right", _N),
            Column("balance_after", "Balance", "right", _N),
        ),
        godown_column="it.godown_id",
        sql="""
            SELECT it.txn_date, it.txn_number, pv.sku,
                   TRIM(p.name || ' ' || COALESCE(pv.variant_name, '')) AS product,
                   g.name AS godown, it.txn_type, it.quantity,
                   SUM(it.quantity) OVER (
                       PARTITION BY it.product_variant_id, it.godown_id
                       ORDER BY it.txn_date, it.posted_at
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                   ) AS balance_after
            FROM inventory_transactions it
            JOIN product_variants pv ON pv.id = it.product_variant_id AND pv.company_id = it.company_id
            JOIN products p ON p.id = pv.product_id AND p.company_id = pv.company_id
            JOIN godowns g ON g.id = it.godown_id AND g.company_id = it.company_id
            WHERE it.company_id = :c
              AND (CAST(:date_from AS date) IS NULL OR it.txn_date >= CAST(:date_from AS date))
              AND (CAST(:date_to AS date) IS NULL OR it.txn_date < CAST(:date_to AS date) + 1)
              AND (CAST(:godown_id AS uuid) IS NULL OR it.godown_id = CAST(:godown_id AS uuid))
              AND (CAST(:category_id AS uuid) IS NULL OR p.category_id = CAST(:category_id AS uuid))
              {godown_scope}
            ORDER BY it.txn_date DESC, it.posted_at DESC
        """,
    ),
    ReportSpec(
        key="low_stock",
        name="Low Stock & Reorder",
        description="Items at or below reorder point with suggested order quantity.",
        group="Inventory",
        params=("godown", "category"),
        columns=(
            Column("sku", "SKU"),
            Column("product", "Product"),
            Column("godown", "Godown"),
            Column("quantity", "On hand", "right", _N),
            Column("reorder_point", "Reorder at", "right", _N),
            Column("suggested_qty", "Suggested", "right", _N),
            Column("supplier", "Preferred supplier"),
        ),
        total_columns=(),
        godown_column="sb.godown_id",
        sql="""
            SELECT pv.sku, TRIM(p.name || ' ' || COALESCE(pv.variant_name, '')) AS product,
                   g.name AS godown, sb.quantity,
                   COALESCE(vgp.reorder_point, pv.reorder_point, 0) AS reorder_point,
                   GREATEST(
                     COALESCE(NULLIF(COALESCE(vgp.reorder_qty, pv.reorder_qty, 0), 0),
                              COALESCE(vgp.reorder_point, pv.reorder_point, 0) - sb.quantity),
                     1) AS suggested_qty,
                   COALESCE(s.name, '') AS supplier
            FROM (
                SELECT company_id, product_variant_id, godown_id, SUM(quantity) AS quantity
                FROM stock_balances GROUP BY company_id, product_variant_id, godown_id
            ) sb
            JOIN product_variants pv ON pv.id = sb.product_variant_id AND pv.company_id = sb.company_id
            JOIN products p ON p.id = pv.product_id AND p.company_id = pv.company_id
            JOIN godowns g ON g.id = sb.godown_id AND g.company_id = sb.company_id
            LEFT JOIN variant_godown_policies vgp
                   ON vgp.product_variant_id = sb.product_variant_id
                  AND vgp.godown_id = sb.godown_id AND vgp.company_id = sb.company_id
            LEFT JOIN LATERAL (
                SELECT sp.supplier_id FROM supplier_products sp
                WHERE sp.company_id = sb.company_id AND sp.product_variant_id = sb.product_variant_id
                ORDER BY sp.is_preferred DESC NULLS LAST LIMIT 1
            ) pref ON TRUE
            LEFT JOIN suppliers s ON s.id = pref.supplier_id AND s.company_id = sb.company_id
            WHERE sb.company_id = :c AND pv.deleted_at IS NULL
              AND COALESCE(vgp.reorder_point, pv.reorder_point, 0) > 0
              AND sb.quantity <= COALESCE(vgp.reorder_point, pv.reorder_point, 0)
              AND (CAST(:godown_id AS uuid) IS NULL OR sb.godown_id = CAST(:godown_id AS uuid))
              AND (CAST(:category_id AS uuid) IS NULL OR p.category_id = CAST(:category_id AS uuid))
              {godown_scope}
            ORDER BY (sb.quantity - COALESCE(vgp.reorder_point, pv.reorder_point, 0)), p.name
        """,
    ),
    ReportSpec(
        key="inventory_valuation",
        name="Inventory Valuation",
        description="Stock value at purchase cost, by category and godown.",
        group="Inventory",
        params=("godown", "category"),
        columns=(
            Column("category", "Category"),
            Column("godown", "Godown"),
            Column("skus", "SKUs", "right", _N),
            Column("quantity", "Quantity", "right", _N),
            Column("value", "Value", "right", _M),
        ),
        total_columns=("skus", "value"),
        godown_column="sb.godown_id",
        sql="""
            SELECT COALESCE(c.name, 'Uncategorised') AS category, g.name AS godown,
                   COUNT(DISTINCT sb.product_variant_id) AS skus,
                   SUM(sb.quantity) AS quantity,
                   ROUND(SUM(sb.quantity * COALESCE(pv.purchase_price, 0)), 2) AS value
            FROM stock_balances sb
            JOIN product_variants pv ON pv.id = sb.product_variant_id AND pv.company_id = sb.company_id
            JOIN products p ON p.id = pv.product_id AND p.company_id = pv.company_id
            JOIN godowns g ON g.id = sb.godown_id AND g.company_id = sb.company_id
            LEFT JOIN categories c ON c.id = p.category_id AND c.company_id = p.company_id
            WHERE sb.company_id = :c AND pv.deleted_at IS NULL
              AND (CAST(:godown_id AS uuid) IS NULL OR sb.godown_id = CAST(:godown_id AS uuid))
              AND (CAST(:category_id AS uuid) IS NULL OR p.category_id = CAST(:category_id AS uuid))
              {godown_scope}
            GROUP BY c.name, g.name
            ORDER BY value DESC
        """,
    ),
    ReportSpec(
        key="batch_expiry",
        name="Batch Expiry",
        description="Batches in stock by expiry date.",
        group="Inventory",
        params=("dateRange", "godown"),
        columns=(
            Column("expires_on", "Expires", None, _D),
            Column("batch_number", "Batch"),
            Column("sku", "SKU"),
            Column("product", "Product"),
            Column("godown", "Godown"),
            Column("quantity", "On hand", "right", _N),
            Column("days_left", "Days left", "right", _N),
        ),
        total_columns=(),
        godown_column="sb.godown_id",
        sql="""
            SELECT bt.expires_on, bt.batch_number, pv.sku,
                   TRIM(p.name || ' ' || COALESCE(pv.variant_name, '')) AS product,
                   g.name AS godown, SUM(sb.quantity) AS quantity,
                   (bt.expires_on - CURRENT_DATE) AS days_left
            FROM batches bt
            JOIN stock_balances sb ON sb.batch_id = bt.id AND sb.company_id = bt.company_id
            JOIN product_variants pv ON pv.id = bt.product_variant_id AND pv.company_id = bt.company_id
            JOIN products p ON p.id = pv.product_id AND p.company_id = pv.company_id
            JOIN godowns g ON g.id = sb.godown_id AND g.company_id = sb.company_id
            WHERE bt.company_id = :c AND bt.expires_on IS NOT NULL
              AND (CAST(:date_from AS date) IS NULL OR bt.expires_on >= CAST(:date_from AS date))
              AND (CAST(:date_to AS date) IS NULL OR bt.expires_on <= CAST(:date_to AS date))
              AND (CAST(:godown_id AS uuid) IS NULL OR sb.godown_id = CAST(:godown_id AS uuid))
              {godown_scope}
            GROUP BY bt.expires_on, bt.batch_number, pv.sku, p.name, pv.variant_name, g.name
            HAVING SUM(sb.quantity) > 0
            ORDER BY bt.expires_on
        """,
    ),
    ReportSpec(
        key="purchase_register",
        name="Purchase Register",
        description="Goods receipts and supplier invoices for a period, newest first.",
        group="Procurement",
        params=("dateRange", "supplier"),
        columns=(
            Column("doc_date", "Date", None, _D),
            Column("doc_type", "Type"),
            Column("doc_number", "Number"),
            Column("supplier", "Supplier"),
            Column("po_number", "PO"),
            Column("godown", "Godown"),
            Column("lines", "Lines", "right", _N),
            Column("quantity", "Quantity", "right", _N),
            Column("amount", "Amount", "right", _M),
            Column("status", "Status"),
        ),
        # No totals row: a receipt and the invoice for it cover the same
        # goods, so adding the two together would count them twice.
        total_columns=(),
        godown_column="r.godown_id",
        sql="""
            SELECT r.doc_date, r.doc_type, r.doc_number, r.supplier, r.po_number, r.godown,
                   r.lines, r.quantity, r.amount, r.status
            FROM (
                SELECT gr.grn_date AS doc_date, 'Goods receipt' AS doc_type, gr.grn_number AS doc_number,
                       COALESCE(s.name, '') AS supplier, COALESCE(po.po_number, '') AS po_number,
                       COALESCE(g.name, '') AS godown, gr.godown_id,
                       COUNT(gi.id) AS lines, COALESCE(SUM(gi.accepted_quantity), 0) AS quantity,
                       -- Received value at the PO rate, before GST.
                       ROUND(COALESCE(SUM(gi.accepted_quantity * COALESCE(gi.unit_price, 0)), 0), 2) AS amount,
                       gr.status
                FROM goods_receipts gr
                LEFT JOIN goods_receipt_items gi ON gi.goods_receipt_id = gr.id AND gi.company_id = gr.company_id
                LEFT JOIN suppliers s ON s.id = gr.supplier_id AND s.company_id = gr.company_id
                LEFT JOIN purchase_orders po ON po.id = gr.purchase_order_id AND po.company_id = gr.company_id
                LEFT JOIN godowns g ON g.id = gr.godown_id AND g.company_id = gr.company_id
                WHERE gr.company_id = :c
                  -- Only receipts that posted stock: a draft has moved
                  -- nothing yet and a cancelled one never will.
                  AND gr.status NOT IN ('draft', 'cancelled')
                  AND (CAST(:date_from AS date) IS NULL OR gr.grn_date >= CAST(:date_from AS date))
                  AND (CAST(:date_to AS date) IS NULL OR gr.grn_date <= CAST(:date_to AS date))
                  AND (CAST(:supplier_id AS uuid) IS NULL OR gr.supplier_id = CAST(:supplier_id AS uuid))
                GROUP BY gr.id, gr.grn_date, gr.grn_number, s.name, po.po_number, g.name, gr.godown_id, gr.status

                UNION ALL

                SELECT si.invoice_date, 'Supplier invoice', si.invoice_number,
                       COALESCE(s.name, ''), COALESCE(po.po_number, ''),
                       COALESCE(g.name, ''),
                       -- An invoice has no godown of its own: the one its
                       -- receipt went into, else where the PO delivers.
                       COALESCE(gr.godown_id, po.delivery_godown_id),
                       (SELECT COUNT(*) FROM supplier_invoice_items ii
                         WHERE ii.invoice_id = si.id AND ii.company_id = si.company_id),
                       (SELECT COALESCE(SUM(ii.quantity), 0) FROM supplier_invoice_items ii
                         WHERE ii.invoice_id = si.id AND ii.company_id = si.company_id),
                       -- The invoice total, including GST.
                       si.total_amount,
                       si.status
                FROM supplier_invoices si
                LEFT JOIN suppliers s ON s.id = si.supplier_id AND s.company_id = si.company_id
                LEFT JOIN purchase_orders po ON po.id = si.purchase_order_id AND po.company_id = si.company_id
                LEFT JOIN goods_receipts gr ON gr.id = si.goods_receipt_id AND gr.company_id = si.company_id
                LEFT JOIN godowns g ON g.id = COALESCE(gr.godown_id, po.delivery_godown_id) AND g.company_id = si.company_id
                WHERE si.company_id = :c
                  AND si.status <> 'cancelled'
                  AND (CAST(:date_from AS date) IS NULL OR si.invoice_date >= CAST(:date_from AS date))
                  AND (CAST(:date_to AS date) IS NULL OR si.invoice_date <= CAST(:date_to AS date))
                  AND (CAST(:supplier_id AS uuid) IS NULL OR si.supplier_id = CAST(:supplier_id AS uuid))
            ) r
            WHERE TRUE {godown_scope}
            ORDER BY r.doc_date DESC, r.doc_number DESC
        """,
    ),
    ReportSpec(
        key="po_status",
        name="PO Status",
        description="Open, partially received and closed purchase orders.",
        group="Procurement",
        params=("dateRange", "supplier", "status"),
        columns=(
            Column("po_date", "Date", None, _D),
            Column("po_number", "PO"),
            Column("supplier", "Supplier"),
            Column("expected_delivery_date", "Due", None, _D),
            Column("status", "Status"),
            Column("received_pct", "Received %", "right", _N),
            Column("total_amount", "Value", "right", _M),
        ),
        total_columns=("total_amount",),
        godown_column="po.delivery_godown_id",
        sql="""
            SELECT po.po_date, po.po_number, COALESCE(s.name, '') AS supplier,
                   po.expected_delivery_date, po.status,
                   ROUND(COALESCE(po.received_pct, 0), 1) AS received_pct, po.total_amount
            FROM purchase_orders po
            LEFT JOIN suppliers s ON s.id = po.supplier_id AND s.company_id = po.company_id
            WHERE po.company_id = :c
              AND (CAST(:date_from AS date) IS NULL OR po.po_date >= CAST(:date_from AS date))
              AND (CAST(:date_to AS date) IS NULL OR po.po_date <= CAST(:date_to AS date))
              AND (CAST(:supplier_id AS uuid) IS NULL OR po.supplier_id = CAST(:supplier_id AS uuid))
              AND (CAST(:status AS text) IS NULL OR po.status = :status)
              {godown_scope}
            ORDER BY po.po_date DESC, po.po_number DESC
        """,
    ),
    ReportSpec(
        key="pending_receipts",
        name="Pending Receipts",
        description="Ordered quantity still awaited, by PO line.",
        group="Procurement",
        params=("supplier", "godown"),
        columns=(
            Column("po_number", "PO"),
            Column("supplier", "Supplier"),
            Column("sku", "SKU"),
            Column("product", "Product"),
            Column("ordered", "Ordered", "right", _N),
            # Labelled "Accepted", not "Received": `purchase_order_items.
            # received_quantity` accumulates the *accepted* quantity of each GRN
            # (grn_service adds `:accepted`), so a delivery of 100 with 10
            # rejected advances it by 90 and leaves 10 still owed. Calling that
            # column "Received" would make the Pending figure look wrong.
            Column("received", "Accepted", "right", _N),
            Column("pending", "Pending", "right", _N),
            Column("expected_delivery_date", "Due", None, _D),
        ),
        total_columns=(),
        godown_column="po.delivery_godown_id",
        sql="""
            SELECT po.po_number, COALESCE(s.name, '') AS supplier, pv.sku,
                   TRIM(p.name || ' ' || COALESCE(pv.variant_name, '')) AS product,
                   poi.quantity AS ordered,
                   COALESCE(poi.received_quantity, 0) AS received,
                   (poi.quantity - COALESCE(poi.received_quantity, 0)) AS pending,
                   po.expected_delivery_date
            FROM purchase_order_items poi
            JOIN purchase_orders po ON po.id = poi.purchase_order_id AND po.company_id = poi.company_id
            JOIN product_variants pv ON pv.id = poi.product_variant_id AND pv.company_id = poi.company_id
            JOIN products p ON p.id = pv.product_id AND p.company_id = pv.company_id
            LEFT JOIN suppliers s ON s.id = po.supplier_id AND s.company_id = po.company_id
            WHERE poi.company_id = :c
              AND po.status IN ('approved', 'sent', 'acknowledged', 'partially_received')
              AND poi.quantity > COALESCE(poi.received_quantity, 0)
              AND (CAST(:supplier_id AS uuid) IS NULL OR po.supplier_id = CAST(:supplier_id AS uuid))
              AND (CAST(:godown_id AS uuid) IS NULL OR po.delivery_godown_id = CAST(:godown_id AS uuid))
              {godown_scope}
            ORDER BY po.expected_delivery_date NULLS LAST, po.po_number
        """,
    ),
    ReportSpec(
        key="supplier_performance",
        name="Supplier Performance",
        description="On-time delivery, short supply and rejection rate.",
        group="Procurement",
        params=("dateRange", "supplier"),
        columns=(
            Column("supplier", "Supplier"),
            Column("receipts", "Receipts", "right", _N),
            Column("delivered", "Delivered", "right", _N),
            Column("accepted", "Accepted", "right", _N),
            Column("rejected", "Rejected", "right", _N),
            Column("rejection_pct", "Rejected %", "right", _N),
        ),
        total_columns=("receipts",),
        sql="""
            SELECT COALESCE(s.name, '') AS supplier,
                   COUNT(DISTINCT gr.id) AS receipts,
                   SUM(gi.received_quantity) AS delivered,
                   SUM(gi.accepted_quantity) AS accepted,
                   SUM(gi.received_quantity - gi.accepted_quantity) AS rejected,
                   CASE WHEN SUM(gi.received_quantity) > 0
                        THEN ROUND(SUM(gi.received_quantity - gi.accepted_quantity)
                                   / SUM(gi.received_quantity) * 100, 2)
                        ELSE 0 END AS rejection_pct
            FROM goods_receipts gr
            JOIN goods_receipt_items gi ON gi.goods_receipt_id = gr.id AND gi.company_id = gr.company_id
            LEFT JOIN suppliers s ON s.id = gr.supplier_id AND s.company_id = gr.company_id
            WHERE gr.company_id = :c AND gr.status IN ('partially_received', 'received')
              AND (CAST(:date_from AS date) IS NULL OR gr.grn_date >= CAST(:date_from AS date))
              AND (CAST(:date_to AS date) IS NULL OR gr.grn_date <= CAST(:date_to AS date))
              AND (CAST(:supplier_id AS uuid) IS NULL OR gr.supplier_id = CAST(:supplier_id AS uuid))
            GROUP BY s.name
            ORDER BY rejection_pct DESC, supplier
        """,
    ),
    ReportSpec(
        key="price_variance",
        name="Price Variance",
        description="Invoice and proforma rates against PO rates.",
        group="Procurement",
        params=("dateRange", "supplier"),
        columns=(
            Column("document", "Document"),
            Column("kind", "Type"),
            Column("supplier", "Supplier"),
            Column("sku", "SKU"),
            Column("po_rate", "PO rate", "right", _M),
            Column("billed_rate", "Billed", "right", _M),
            Column("difference", "Difference", "right", _M),
            Column("variance_pct", "Variance %", "right", _N),
        ),
        sql="""
            -- The UNION is wrapped in a subquery deliberately: Postgres only
            -- accepts *result column names* in a UNION's ORDER BY, never an
            -- expression, so `ORDER BY ABS(difference)` on the union itself is a
            -- FeatureNotSupportedError. Sorting the wrapped result is legal.
            SELECT * FROM (
                SELECT si.invoice_number AS document, 'Invoice' AS kind,
                       COALESCE(s.name, '') AS supplier, COALESCE(pv.sku, '') AS sku,
                       ii.po_unit_price_snapshot AS po_rate, ii.unit_price AS billed_rate,
                       ROUND(ii.unit_price - ii.po_unit_price_snapshot, 2) AS difference,
                       ROUND(COALESCE(ii.price_variance_pct, 0), 2) AS variance_pct
                FROM supplier_invoice_items ii
                JOIN supplier_invoices si ON si.id = ii.invoice_id AND si.company_id = ii.company_id
                LEFT JOIN suppliers s ON s.id = si.supplier_id AND s.company_id = si.company_id
                LEFT JOIN product_variants pv ON pv.id = ii.product_variant_id AND pv.company_id = ii.company_id
                WHERE ii.company_id = :c AND ii.po_unit_price_snapshot IS NOT NULL
                  AND ii.unit_price <> ii.po_unit_price_snapshot
                  AND (CAST(:date_from AS date) IS NULL OR si.invoice_date >= CAST(:date_from AS date))
                  AND (CAST(:date_to AS date) IS NULL OR si.invoice_date <= CAST(:date_to AS date))
                  AND (CAST(:supplier_id AS uuid) IS NULL OR si.supplier_id = CAST(:supplier_id AS uuid))
                UNION ALL
                SELECT pf.proforma_number AS document, 'Proforma' AS kind,
                       COALESCE(s.name, '') AS supplier, COALESCE(pv.sku, '') AS sku,
                       pi.po_unit_price_snapshot AS po_rate, pi.unit_price AS billed_rate,
                       ROUND(pi.unit_price - pi.po_unit_price_snapshot, 2) AS difference,
                       ROUND(COALESCE(pi.price_variance_pct, 0), 2) AS variance_pct
                FROM proforma_invoice_items pi
                JOIN proforma_invoices pf ON pf.id = pi.proforma_id AND pf.company_id = pi.company_id
                LEFT JOIN suppliers s ON s.id = pf.supplier_id AND s.company_id = pf.company_id
                LEFT JOIN product_variants pv ON pv.id = pi.product_variant_id AND pv.company_id = pi.company_id
                WHERE pi.company_id = :c AND pi.po_unit_price_snapshot IS NOT NULL
                  AND pi.unit_price <> pi.po_unit_price_snapshot
                  AND (CAST(:date_from AS date) IS NULL OR pf.proforma_date >= CAST(:date_from AS date))
                  AND (CAST(:date_to AS date) IS NULL OR pf.proforma_date <= CAST(:date_to AS date))
                  AND (CAST(:supplier_id AS uuid) IS NULL OR pf.supplier_id = CAST(:supplier_id AS uuid))
            ) v
            ORDER BY ABS(v.difference) DESC
        """,
    ),
    ReportSpec(
        key="gst_purchase",
        name="GST Purchase Summary",
        description="Taxable value and tax by GST rate for the period.",
        group="Procurement",
        params=("dateRange", "supplier"),
        columns=(
            Column("gst_rate", "GST %", "right", _N),
            Column("invoices", "Invoices", "right", _N),
            Column("taxable_value", "Taxable value", "right", _M),
            Column("cgst", "CGST", "right", _M),
            Column("sgst", "SGST", "right", _M),
            Column("igst", "IGST", "right", _M),
            Column("total_tax", "Total tax", "right", _M),
        ),
        total_columns=("invoices", "taxable_value", "cgst", "sgst", "igst", "total_tax"),
        sql="""
            SELECT ii.gst_rate,
                   COUNT(DISTINCT si.id) AS invoices,
                   ROUND(SUM(ii.line_net), 2) AS taxable_value,
                   ROUND(SUM(CASE WHEN si.is_inter_state THEN 0 ELSE ii.line_tax / 2 END), 2) AS cgst,
                   ROUND(SUM(CASE WHEN si.is_inter_state THEN 0 ELSE ii.line_tax / 2 END), 2) AS sgst,
                   ROUND(SUM(CASE WHEN si.is_inter_state THEN ii.line_tax ELSE 0 END), 2) AS igst,
                   ROUND(SUM(ii.line_tax), 2) AS total_tax
            FROM supplier_invoice_items ii
            JOIN supplier_invoices si ON si.id = ii.invoice_id AND si.company_id = ii.company_id
            WHERE ii.company_id = :c AND si.status <> 'cancelled'
              AND (CAST(:date_from AS date) IS NULL OR si.invoice_date >= CAST(:date_from AS date))
              AND (CAST(:date_to AS date) IS NULL OR si.invoice_date <= CAST(:date_to AS date))
              AND (CAST(:supplier_id AS uuid) IS NULL OR si.supplier_id = CAST(:supplier_id AS uuid))
            GROUP BY ii.gst_rate
            ORDER BY ii.gst_rate
        """,
    ),
    ReportSpec(
        key="product_master",
        name="Product Master",
        description="Full catalogue with category, brand, HSN and rates.",
        group="Master Data",
        params=("category",),
        columns=(
            Column("sku", "SKU"),
            Column("product", "Product"),
            Column("category", "Category"),
            Column("brand", "Brand"),
            Column("hsn_code", "HSN"),
            Column("uom", "Unit"),
            Column("gst_rate", "GST %", "right", _N),
            Column("purchase_price", "Purchase", "right", _M),
            Column("reorder_point", "Reorder at", "right", _N),
        ),
        sql="""
            SELECT pv.sku, TRIM(p.name || ' ' || COALESCE(pv.variant_name, '')) AS product,
                   COALESCE(c.name, '') AS category, COALESCE(b.name, '') AS brand,
                   COALESCE(pv.hsn_code, p.hsn_code, '') AS hsn_code,
                   COALESCE(u.code, '') AS uom,
                   COALESCE(pv.gst_rate, p.gst_rate, 0) AS gst_rate,
                   COALESCE(pv.purchase_price, 0) AS purchase_price,
                   COALESCE(pv.reorder_point, 0) AS reorder_point
            FROM product_variants pv
            JOIN products p ON p.id = pv.product_id AND p.company_id = pv.company_id
            LEFT JOIN categories c ON c.id = p.category_id AND c.company_id = p.company_id
            LEFT JOIN brands b ON b.id = p.brand_id AND b.company_id = p.company_id
            LEFT JOIN uoms u ON u.id = pv.uom_id
            WHERE pv.company_id = :c AND pv.deleted_at IS NULL AND p.deleted_at IS NULL
              AND (CAST(:category_id AS uuid) IS NULL OR p.category_id = CAST(:category_id AS uuid))
            ORDER BY p.name, pv.sku
        """,
    ),
    ReportSpec(
        key="supplier_master",
        name="Supplier Master",
        description="Suppliers with GSTIN, terms and contact details.",
        group="Master Data",
        params=("status",),
        columns=(
            Column("name", "Supplier"),
            Column("gstin", "GSTIN"),
            Column("state_code", "State"),
            Column("city", "City"),
            Column("email", "Email"),
            Column("phone", "Phone"),
            Column("payment_terms", "Payment terms"),
            Column("status", "Status"),
        ),
        sql="""
            SELECT s.name, COALESCE(s.gstin, '') AS gstin, COALESCE(s.state_code, '') AS state_code,
                   COALESCE(s.city, '') AS city, COALESCE(s.email, '') AS email,
                   COALESCE(s.phone, '') AS phone, COALESCE(s.payment_terms, '') AS payment_terms,
                   s.status
            FROM suppliers s
            WHERE s.company_id = :c AND s.deleted_at IS NULL
              AND (CAST(:status AS text) IS NULL OR s.status = :status)
            ORDER BY s.name
        """,
    ),
)

REPORTS_BY_KEY = {r.key: r for r in REPORTS}


def list_reports() -> list[dict]:
    return [
        {
            "key": r.key,
            "name": r.name,
            "description": r.description,
            "group": r.group,
            "params": list(r.params),
        }
        for r in REPORTS
    ]


async def run_report(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    key: str,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    godown_id: Optional[UUID] = None,
    category_id: Optional[UUID] = None,
    supplier_id: Optional[UUID] = None,
    status_filter: Optional[str] = None,
    limit: int = 5000,
) -> Optional[dict]:
    spec = REPORTS_BY_KEY.get(key)
    if spec is None:
        return None

    params: dict[str, Any] = {
        "c": claims.company_id,
        "date_from": date_from,
        "date_to": date_to,
        "godown_id": godown_id,
        "category_id": category_id,
        "supplier_id": supplier_id,
        "status": status_filter,
    }

    # A report over godown-scoped rows shows only the godowns the caller may
    # see, exactly as the screens do (BR-AUTH-12). A report over master data
    # has no godown dimension and is unscoped.
    scope_sql = ""
    if spec.godown_column:
        fragment, scope_params = scoped_godown_filter(claims, spec.godown_column)
        if fragment:
            scope_sql = f"AND ({fragment})"
            params.update(scope_params)

    sql = spec.sql.format(godown_scope=scope_sql)
    rows = (await session.execute(text(f"{sql} LIMIT {int(limit)}"), params)).mappings().all()
    rows = [dict(r) for r in rows]

    totals: dict[str, float] = {}
    for column in spec.total_columns:
        total = sum(float(r[column] or 0) for r in rows)
        totals[column] = round(total, 2)

    return {
        "key": spec.key,
        "title": spec.name,
        "generated_at": datetime.now(timezone.utc),
        "columns": [
            {"key": c.key, "label": c.label, "align": c.align, "format": c.format}
            for c in spec.columns
        ],
        "rows": rows,
        "totals": totals or None,
        "row_count": len(rows),
    }

