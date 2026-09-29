"""
The alert rule catalogue and what each rule looks for.

BR-ALT-01: "alerts are generated server-side by named rules (`rule_code`),
never by the browser." This file is that list of names, and the SQL behind
each one.

Every rule is a query returning the things currently in a bad state. It
answers "what is wrong *right now*", not "what changed" -- which is what
makes BR-ALT-04 (auto-resolve when the condition clears) fall out for free:
anything the query stops returning has stopped being a problem, so its open
alert can be closed. A rule that emitted events instead would have no way
to know the problem had gone away.

`alert_rules` rows are **overrides**, not configuration that has to exist.
The defaults here apply to every tenant from day one; a row is written only
when someone changes a threshold or switches a rule off. That is what the
model means by "(OPTIONAL) makes thresholds tenant-editable instead of
hardcoded" -- and it means no seeding, and no backfill for the companies
that already exist.

Two rules in the frontend's vocabulary are deliberately absent:
`AI_LOW_CONFIDENCE` and `DOCUMENT_UNREADABLE` both fire off the AI
extraction pipeline, which does not exist. Listing them with no
implementation would be worse than leaving them out -- the Settings screen
would offer a switch that controls nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class RuleSpec:
    code: str
    label: str
    description: str
    # BR-ALT-05 fixes these. A tenant may override severity per rule, but
    # the default is the rule the spec names.
    severity: str
    category: str
    reference_type: Optional[str]
    thresholds: dict[str, Any] = field(default_factory=dict)


RULES: tuple[RuleSpec, ...] = (
    RuleSpec(
        code="OUT_OF_STOCK",
        label="Out of stock",
        description="An item a godown stocks has run to zero.",
        severity="critical",
        category="Inventory",
        reference_type="product_variant",
    ),
    RuleSpec(
        code="LOW_STOCK_BELOW_REORDER",
        label="Below reorder point",
        description="Available quantity has fallen to or below the reorder point.",
        severity="high",
        category="Inventory",
        reference_type="product_variant",
    ),
    RuleSpec(
        code="BATCH_EXPIRING",
        label="Batch expiring",
        description="A batch still holding stock is close to its expiry date.",
        severity="medium",
        category="Inventory",
        reference_type="product_variant",
        thresholds={"days_ahead": 30},
    ),
    RuleSpec(
        code="STOCK_BALANCE_DRIFT",
        label="Stock balance drift",
        description="A cached balance no longer equals the sum of its ledger (BR-INV-02).",
        severity="critical",
        category="System",
        reference_type="product_variant",
    ),
    RuleSpec(
        code="GRN_QTY_MISMATCH",
        label="Receipt quantity mismatch",
        description="A confirmed receipt accepted less than was delivered.",
        severity="high",
        category="Goods Receipt",
        reference_type="goods_receipt",
    ),
    RuleSpec(
        code="GRN_WRONG_PRODUCT",
        label="Wrong product received",
        description="A receipt line was flagged as the wrong item.",
        severity="critical",
        category="Goods Receipt",
        reference_type="goods_receipt",
    ),
    RuleSpec(
        code="PO_DELIVERY_DELAYED",
        label="Delivery overdue",
        description="A sent purchase order is past its expected delivery date and not fully received.",
        severity="medium",
        category="Procurement",
        reference_type="purchase_order",
        thresholds={"grace_days": 0},
    ),
    RuleSpec(
        code="QUOTATION_EXPIRING",
        label="Quotation expiring",
        description="An approved quotation is close to the end of its validity.",
        severity="medium",
        category="Procurement",
        reference_type="supplier_quotation",
        thresholds={"days_ahead": 7},
    ),
    RuleSpec(
        code="PROFORMA_VARIANCE",
        label="Proforma differs from the order",
        description="A proforma carries an unresolved difference beyond tolerance.",
        severity="high",
        category="Procurement",
        reference_type="proforma_invoice",
    ),
    RuleSpec(
        code="INVOICE_VARIANCE",
        label="Invoice differs from the order or receipt",
        description="A supplier invoice carries an unresolved difference beyond tolerance.",
        severity="high",
        category="Procurement",
        reference_type="supplier_invoice",
    ),
)

RULES_BY_CODE = {r.code: r for r in RULES}


# Each query returns one row per thing currently in a bad state, with the
# columns the alert row needs. `:c` is the company id; `:threshold_*` are
# filled from the rule's own (possibly overridden) thresholds.
#
# `dedupe_key` is what BR-ALT-02 deduplicates on together with the rule
# code. Where a rule is about a variant *in a godown*, the reference is the
# variant and the godown goes on `godown_id` -- the schema's partial unique
# index keys on (rule_code, reference_type, reference_id), so a variant low
# in two godowns would otherwise collapse into one alert. Those rules carry
# the godown in `reference_id` instead where that matters; see LOW_STOCK.

_STOCK_BASE = """
    FROM (
        SELECT company_id, product_variant_id, godown_id,
               SUM(quantity) AS quantity, SUM(available_quantity) AS available_quantity
        FROM stock_balances GROUP BY company_id, product_variant_id, godown_id
    ) sb
    JOIN product_variants pv ON pv.id = sb.product_variant_id AND pv.company_id = sb.company_id
    JOIN products p ON p.id = pv.product_id AND p.company_id = pv.company_id
    JOIN godowns g ON g.id = sb.godown_id AND g.company_id = sb.company_id
    LEFT JOIN variant_godown_policies vgp
           ON vgp.product_variant_id = sb.product_variant_id
          AND vgp.godown_id = sb.godown_id AND vgp.company_id = sb.company_id
    WHERE sb.company_id = :c AND pv.deleted_at IS NULL AND g.deleted_at IS NULL
"""

_REORDER = "COALESCE(vgp.reorder_point, pv.reorder_point, 0)"

QUERIES: dict[str, str] = {
    # A variant at zero in a godown that stocks it. `reference_id` is the
    # variant and the godown is carried separately, so the same item empty
    # in two godowns raises two alerts rather than one that flickers
    # between them.
    "OUT_OF_STOCK": f"""
        SELECT sb.product_variant_id AS reference_id, sb.godown_id,
               pv.sku, TRIM(p.name || ' ' || COALESCE(pv.variant_name, '')) AS product_name,
               g.name AS godown_name, sb.quantity, {_REORDER} AS reorder_point
        {_STOCK_BASE} AND sb.quantity <= 0 AND {_REORDER} > 0
    """,
    "LOW_STOCK_BELOW_REORDER": f"""
        SELECT sb.product_variant_id AS reference_id, sb.godown_id,
               pv.sku, TRIM(p.name || ' ' || COALESCE(pv.variant_name, '')) AS product_name,
               g.name AS godown_name, sb.quantity, sb.available_quantity,
               {_REORDER} AS reorder_point,
               COALESCE(vgp.reorder_qty, pv.reorder_qty, 0) AS reorder_qty
        {_STOCK_BASE} AND sb.quantity > 0 AND {_REORDER} > 0
              AND sb.available_quantity <= {_REORDER}
    """,
    "BATCH_EXPIRING": """
        SELECT bt.product_variant_id AS reference_id, sb.godown_id,
               pv.sku, TRIM(p.name || ' ' || COALESCE(pv.variant_name, '')) AS product_name,
               g.name AS godown_name, bt.batch_number, bt.expires_on,
               SUM(sb.quantity) AS quantity
        FROM batches bt
        JOIN stock_balances sb ON sb.batch_id = bt.id AND sb.company_id = bt.company_id
        JOIN product_variants pv ON pv.id = bt.product_variant_id AND pv.company_id = bt.company_id
        JOIN products p ON p.id = pv.product_id AND p.company_id = pv.company_id
        JOIN godowns g ON g.id = sb.godown_id AND g.company_id = sb.company_id
        WHERE bt.company_id = :c AND bt.expires_on IS NOT NULL
          AND bt.expires_on <= CURRENT_DATE + CAST(:threshold_days_ahead AS int)
        GROUP BY bt.product_variant_id, sb.godown_id, pv.sku, p.name, pv.variant_name,
                 g.name, bt.batch_number, bt.expires_on
        HAVING SUM(sb.quantity) > 0
    """,
    # BR-INV-02's nightly reconciliation, as an alert. Any row where the
    # cached balance and the ledger disagree is a data-integrity problem,
    # which is why it is `critical` and lives under `System`.
    "STOCK_BALANCE_DRIFT": """
        SELECT sb.product_variant_id AS reference_id, sb.godown_id,
               pv.sku, TRIM(p.name || ' ' || COALESCE(pv.variant_name, '')) AS product_name,
               g.name AS godown_name,
               sb.quantity AS balance_quantity, COALESCE(led.total, 0) AS ledger_quantity
        FROM stock_balances sb
        JOIN product_variants pv ON pv.id = sb.product_variant_id AND pv.company_id = sb.company_id
        JOIN products p ON p.id = pv.product_id AND p.company_id = pv.company_id
        JOIN godowns g ON g.id = sb.godown_id AND g.company_id = sb.company_id
        LEFT JOIN (
            SELECT company_id, product_variant_id, godown_id, batch_id, SUM(quantity) AS total
            FROM inventory_transactions
            GROUP BY company_id, product_variant_id, godown_id, batch_id
        ) led ON led.company_id = sb.company_id
             AND led.product_variant_id = sb.product_variant_id
             AND led.godown_id = sb.godown_id
             AND COALESCE(led.batch_id, '00000000-0000-0000-0000-000000000000'::uuid)
               = COALESCE(sb.batch_id, '00000000-0000-0000-0000-000000000000'::uuid)
        WHERE sb.company_id = :c AND sb.quantity <> COALESCE(led.total, 0)
    """,
    "GRN_QTY_MISMATCH": """
        SELECT gr.id AS reference_id, gr.godown_id, gr.grn_number,
               COALESCE(s.name, '') AS supplier_name,
               SUM(gi.received_quantity - gi.accepted_quantity) AS shortfall
        FROM goods_receipts gr
        JOIN goods_receipt_items gi ON gi.goods_receipt_id = gr.id AND gi.company_id = gr.company_id
        LEFT JOIN suppliers s ON s.id = gr.supplier_id AND s.company_id = gr.company_id
        WHERE gr.company_id = :c AND gr.status IN ('partially_received', 'received')
        GROUP BY gr.id, gr.godown_id, gr.grn_number, s.name
        HAVING SUM(gi.received_quantity - gi.accepted_quantity) > 0
    """,
    "GRN_WRONG_PRODUCT": """
        SELECT gr.id AS reference_id, gr.godown_id, gr.grn_number,
               COALESCE(s.name, '') AS supplier_name, COUNT(*) AS line_count
        FROM goods_receipts gr
        JOIN goods_receipt_items gi ON gi.goods_receipt_id = gr.id AND gi.company_id = gr.company_id
        LEFT JOIN suppliers s ON s.id = gr.supplier_id AND s.company_id = gr.company_id
        WHERE gr.company_id = :c
          AND gi.issue_type IN ('wrong_product', 'wrong_variant', 'wrong_model', 'wrong_brand')
        GROUP BY gr.id, gr.godown_id, gr.grn_number, s.name
    """,
    "PO_DELIVERY_DELAYED": """
        SELECT po.id AS reference_id, po.delivery_godown_id AS godown_id, po.po_number,
               COALESCE(s.name, '') AS supplier_name, po.expected_delivery_date,
               (CURRENT_DATE - po.expected_delivery_date) AS days_late,
               po.total_amount
        FROM purchase_orders po
        LEFT JOIN suppliers s ON s.id = po.supplier_id AND s.company_id = po.company_id
        WHERE po.company_id = :c
          AND po.status IN ('sent', 'acknowledged', 'partially_received')
          AND po.expected_delivery_date IS NOT NULL
          AND po.expected_delivery_date < CURRENT_DATE - CAST(:threshold_grace_days AS int)
    """,
    "QUOTATION_EXPIRING": """
        SELECT sq.id AS reference_id, NULL::uuid AS godown_id, sq.quotation_number,
               COALESCE(s.name, '') AS supplier_name, sq.valid_until,
               (sq.valid_until - CURRENT_DATE) AS days_left
        FROM supplier_quotations sq
        LEFT JOIN suppliers s ON s.id = sq.supplier_id AND s.company_id = sq.company_id
        WHERE sq.company_id = :c AND sq.status = 'approved'
          AND sq.valid_until IS NOT NULL
          AND sq.valid_until <= CURRENT_DATE + CAST(:threshold_days_ahead AS int)
    """,
    # Both variance rules read the severity already graded when the
    # variance was recorded, rather than re-deriving it -- so the alert can
    # never disagree with what the Variances screen is showing.
    "PROFORMA_VARIANCE": """
        SELECT pf.id AS reference_id, NULL::uuid AS godown_id, pf.proforma_number,
               COALESCE(s.name, '') AS supplier_name,
               COUNT(dv.id) AS variance_count,
               MAX(ABS(dv.difference)) AS worst_difference
        FROM proforma_invoices pf
        JOIN document_variances dv ON dv.compare_doc_id = pf.id AND dv.company_id = pf.company_id
        LEFT JOIN suppliers s ON s.id = pf.supplier_id AND s.company_id = pf.company_id
        WHERE pf.company_id = :c AND dv.status = 'open'
          AND dv.severity IN ('warning', 'critical')
          AND pf.status NOT IN ('rejected', 'cancelled')
        GROUP BY pf.id, pf.proforma_number, s.name
    """,
    "INVOICE_VARIANCE": """
        SELECT si.id AS reference_id, NULL::uuid AS godown_id, si.invoice_number,
               COALESCE(s.name, '') AS supplier_name,
               COUNT(dv.id) AS variance_count,
               MAX(ABS(dv.difference)) AS worst_difference
        FROM supplier_invoices si
        JOIN document_variances dv ON dv.compare_doc_id = si.id AND dv.company_id = si.company_id
        LEFT JOIN suppliers s ON s.id = si.supplier_id AND s.company_id = si.company_id
        WHERE si.company_id = :c AND dv.status = 'open'
          AND dv.severity IN ('warning', 'critical')
          AND si.status <> 'cancelled'
        GROUP BY si.id, si.invoice_number, s.name
    """,
}


def render(code: str, row: dict) -> tuple[str, str, str, str]:
    """Title, description, reference label and deep link for one finding.

    Written from the row's own numbers, never from a template with the
    figures left out: "3 items low" is only actionable if you can see which
    ones and by how much.
    """
    if code == "OUT_OF_STOCK":
        return (
            f"{row['sku']} is out of stock at {row['godown_name']}",
            f"{row['product_name']} has no stock left at {row['godown_name']}. "
            f"Reorder point is {row['reorder_point']}.",
            row["sku"],
            f"/inventory/current-stock?variant={row['reference_id']}",
        )
    if code == "LOW_STOCK_BELOW_REORDER":
        return (
            f"{row['sku']} is below its reorder point at {row['godown_name']}",
            f"{row['available_quantity']} left against a reorder point of {row['reorder_point']}. "
            f"Suggested order quantity {row['reorder_qty'] or max(row['reorder_point'] - row['available_quantity'], 1)}.",
            row["sku"],
            f"/inventory/low-stock?variant={row['reference_id']}",
        )
    if code == "BATCH_EXPIRING":
        return (
            f"Batch {row['batch_number']} of {row['sku']} expires {row['expires_on']}",
            f"{row['quantity']} still on hand at {row['godown_name']}, expiring {row['expires_on']}.",
            f"{row['sku']} / {row['batch_number']}",
            f"/inventory/current-stock?variant={row['reference_id']}",
        )
    if code == "STOCK_BALANCE_DRIFT":
        return (
            f"Stock balance drift on {row['sku']} at {row['godown_name']}",
            f"The cached balance says {row['balance_quantity']} but the ledger sums to "
            f"{row['ledger_quantity']}. Balances must equal the sum of their transactions (BR-INV-02).",
            row["sku"],
            f"/inventory/transactions?variant={row['reference_id']}",
        )
    if code == "GRN_QTY_MISMATCH":
        return (
            f"{row['grn_number']} accepted less than was delivered",
            f"{row['shortfall']} unit(s) received but not accepted from {row['supplier_name']}.",
            row["grn_number"],
            f"/goods-receipt/{row['reference_id']}",
        )
    if code == "GRN_WRONG_PRODUCT":
        return (
            f"Wrong product received on {row['grn_number']}",
            f"{row['line_count']} line(s) from {row['supplier_name']} were flagged as the wrong item.",
            row["grn_number"],
            f"/goods-receipt/{row['reference_id']}",
        )
    if code == "PO_DELIVERY_DELAYED":
        return (
            f"{row['po_number']} is {row['days_late']} day(s) overdue",
            f"{row['supplier_name']} was due to deliver on {row['expected_delivery_date']} "
            f"and the order is not fully received.",
            row["po_number"],
            f"/procurement/purchase-orders/{row['reference_id']}",
        )
    if code == "QUOTATION_EXPIRING":
        days = row["days_left"]
        when = "has expired" if days is not None and days < 0 else f"expires in {days} day(s)"
        return (
            f"Quotation {row['quotation_number']} {when}",
            f"{row['supplier_name']}'s approved quotation is valid until {row['valid_until']}.",
            row["quotation_number"],
            f"/procurement/quotations/{row['reference_id']}",
        )
    if code == "PROFORMA_VARIANCE":
        return (
            f"Proforma {row['proforma_number']} differs from the order",
            f"{row['variance_count']} unresolved difference(s) from {row['supplier_name']}, "
            f"the largest {row['worst_difference']}.",
            row["proforma_number"],
            f"/procurement/proforma/{row['reference_id']}",
        )
    if code == "INVOICE_VARIANCE":
        return (
            f"Invoice {row['invoice_number']} differs from the order or receipt",
            f"{row['variance_count']} unresolved difference(s) from {row['supplier_name']}, "
            f"the largest {row['worst_difference']}.",
            row["invoice_number"],
            f"/supplier-invoices/{row['reference_id']}",
        )
    raise ValueError(f"No renderer for rule {code}")
