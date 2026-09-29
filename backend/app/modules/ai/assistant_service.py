"""
The inventory assistant — BR-AI-08.

    "The assistant never generates or executes SQL. Intents map to
    hand-written parameterised queries run with the caller's tenant and
    godown scope."

So that is literally what this is: a small intent classifier over the
question text, and one hand-written query per intent. A model, if one were
ever configured, would be allowed to pick the *intent* and pull out the
entity names — it would never be allowed to write the query, because a
model that can write SQL against a tenant's database is a model that can
read another tenant's.

Every answer says where its number came from, in the `source` field, so an
answer can be checked rather than believed.
"""

from __future__ import annotations

import re
import time
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AccessTokenClaims

_INTENTS: list[tuple[str, re.Pattern[str]]] = [
    ("out_of_stock", re.compile(r"out of stock|zero stock|nothing left|stocked out", re.I)),
    ("low_stock", re.compile(
        r"low (on )?stock|stock (is )?(running )?low|reorder|running (out|low)|need to order|below (the )?minimum", re.I)),
    ("inventory_value", re.compile(r"inventory value|stock value|worth|valuation", re.I)),
    # `orders?` rather than `order\b`: "open purchase orders" is how anyone
    # actually asks this, and `\b` after "order" does not match the plural.
    # Either word order: "pending orders" and "orders still pending".
    ("open_purchase_orders", re.compile(
        r"(pending|open|outstanding)[\w\s]{0,14}(orders?|pos?)\b"
        r"|\b(pos?|orders?)\b[\w\s]{0,20}(pending|open|outstanding)", re.I)),
    ("open_variances", re.compile(r"variance|mismatch|dispute|discrepanc", re.I)),
]

#: One example question per intent, in the order the screen offers them.
#: Served by `GET /ai/assistant/suggestions`, so the suggestions can only
#: ever be questions this module actually answers.
EXAMPLES: dict[str, str] = {
    "out_of_stock": "What is out of stock?",
    "low_stock": "What is low on stock?",
    "inventory_value": "What is my inventory worth?",
    "open_purchase_orders": "Which purchase orders are still pending?",
    "open_variances": "Are there any unresolved variances?",
}
assert set(EXAMPLES) == {intent for intent, _ in _INTENTS}


def suggestions() -> list[dict]:
    return [{"intent": intent, "question": question} for intent, question in EXAMPLES.items()]


HELP = (
    "I can answer questions about stock levels, inventory value, open purchase orders and "
    "unresolved variances — for example \"what is out of stock?\" or \"what is my inventory worth?\"."
)


def detect_intent(question: str) -> tuple[str, float]:
    for intent, pattern in _INTENTS:
        if pattern.search(question or ""):
            return intent, 90.0
    return "unknown", 0.0


# Every suggested question must route to its own intent.
assert all(detect_intent(q)[0] == intent for intent, q in EXAMPLES.items()), "assistant example misroutes"


async def ask(
    session: AsyncSession, *, claims: AccessTokenClaims, question: str, godown_filter: str = "", params: Optional[dict] = None
) -> dict:
    started = time.monotonic()
    intent, confidence = detect_intent(question)
    handler = {
        "out_of_stock": _out_of_stock,
        "low_stock": _low_stock,
        "inventory_value": _inventory_value,
        "open_purchase_orders": _open_purchase_orders,
        "open_variances": _open_variances,
    }.get(intent)

    if handler is None:
        answer = {"intent": "unknown", "source": "no matching query", "answer": HELP}
    else:
        answer = await handler(session, claims.company_id, godown_filter, params or {})
        answer["intent"] = intent

    await session.execute(
        text(
            "INSERT INTO assistant_queries (id, company_id, user_id, question, detected_intent, "
            " intent_confidence, query_plan, answer_text, latency_ms) "
            "VALUES (:id, :c, :u, :q, :i, :conf, :plan, :a, :ms)"
        ),
        {
            "id": uuid4(),
            "c": claims.company_id,
            "u": claims.user_id,
            "q": question[:2000],
            "i": intent,
            "conf": confidence,
            "plan": answer.get("source"),
            "a": answer.get("answer"),
            "ms": int((time.monotonic() - started) * 1000),
        },
    )
    return answer


# ------------------------------------------------------------- the queries
#
# Each one is fixed text with bound parameters. `godown_filter` is a
# fragment built by `deps.scoped_godown_filter` from the caller's token, not
# from anything they typed.


async def _out_of_stock(session, company_id: str, godown_filter: str, params: dict) -> dict:
    rows = (
        await session.execute(
            text(
                "SELECT v.sku, p.name AS product, g.name AS godown "
                "FROM stock_balances sb "
                "JOIN product_variants v ON v.id = sb.product_variant_id "
                "JOIN products p ON p.id = v.product_id "
                "JOIN godowns g ON g.id = sb.godown_id "
                f"WHERE sb.company_id = :c AND sb.quantity <= 0 {godown_filter} "
                "ORDER BY p.name LIMIT 100"
            ),
            {"c": company_id, **params},
        )
    ).mappings().all()
    return {
        "source": "stock_balances where quantity <= 0",
        "answer": (
            f"{len(rows)} item{'' if len(rows) == 1 else 's'} {'is' if len(rows) == 1 else 'are'} out of stock."
            if rows
            else "Nothing is out of stock right now."
        ),
        "table": {
            "columns": ["SKU", "Product", "Godown"],
            "rows": [[r["sku"], r["product"], r["godown"]] for r in rows],
        }
        if rows
        else None,
        "link": {"label": "Open inventory", "href": "/inventory?status=out_of_stock"},
    }


async def _low_stock(session, company_id: str, godown_filter: str, params: dict) -> dict:
    rows = (
        await session.execute(
            text(
                "SELECT v.sku, SUM(sb.quantity) AS on_hand, MAX(v.reorder_point) AS reorder_point "
                "FROM stock_balances sb JOIN product_variants v ON v.id = sb.product_variant_id "
                f"WHERE sb.company_id = :c {godown_filter} "
                "GROUP BY v.sku HAVING SUM(sb.quantity) > 0 AND SUM(sb.quantity) <= MAX(v.reorder_point) "
                "ORDER BY v.sku LIMIT 100"
            ),
            {"c": company_id, **params},
        )
    ).mappings().all()
    return {
        "source": "stock_balances totalled per SKU, compared with each variant's reorder point",
        "answer": f"{len(rows)} item{'' if len(rows) == 1 else 's'} at or below the reorder point.",
        "table": {
            "columns": ["SKU", "On hand", "Reorder point"],
            "rows": [[r["sku"], f"{r['on_hand']:g}", f"{r['reorder_point']:g}"] for r in rows],
        },
        "link": {"label": "Open the low-stock list", "href": "/inventory/low-stock"},
    }


async def _inventory_value(session, company_id: str, godown_filter: str, params: dict) -> dict:
    total = (
        await session.execute(
            text(
                "SELECT COALESCE(SUM(sb.quantity * COALESCE(v.purchase_price, 0)), 0) "
                "FROM stock_balances sb JOIN product_variants v ON v.id = sb.product_variant_id "
                f"WHERE sb.company_id = :c {godown_filter}"
            ),
            {"c": company_id, **params},
        )
    ).scalar_one()
    breakdown = (
        await session.execute(
            text(
                "SELECT g.name, COALESCE(SUM(sb.quantity * COALESCE(v.purchase_price, 0)), 0) AS value "
                "FROM stock_balances sb JOIN product_variants v ON v.id = sb.product_variant_id "
                "JOIN godowns g ON g.id = sb.godown_id "
                f"WHERE sb.company_id = :c {godown_filter} "
                "GROUP BY g.name ORDER BY value DESC"
            ),
            {"c": company_id, **params},
        )
    ).mappings().all()
    return {
        "source": "sum of stock_balances.quantity x the variant's purchase price",
        "answer": f"Stock on hand is worth {_rupees(total)} at purchase cost.",
        "breakdown": [{"label": r["name"], "value": _rupees(r["value"])} for r in breakdown],
    }


async def _open_purchase_orders(session, company_id: str, godown_filter: str, params: dict) -> dict:
    rows = (
        await session.execute(
            text(
                "SELECT po.po_number, s.name AS supplier, po.total_amount, "
                "  COALESCE(po.received_pct, 0) AS received_pct "
                "FROM purchase_orders po JOIN suppliers s ON s.id = po.supplier_id "
                "WHERE po.company_id = :c AND po.status NOT IN ('draft', 'closed', 'cancelled') "
                "  AND COALESCE(po.received_pct, 0) < 100 "
                "ORDER BY po.po_date DESC LIMIT 100"
            ),
            {"c": company_id},
        )
    ).mappings().all()
    total = sum(float(r["total_amount"] or 0) for r in rows)
    return {
        "source": "purchase_orders that are live and not fully received",
        "answer": (
            f"{len(rows)} purchase order{'' if len(rows) == 1 else 's'} awaiting delivery, "
            f"worth {_rupees(total)}."
        ),
        "table": {
            "columns": ["PO", "Supplier", "Received"],
            "rows": [[r["po_number"], r["supplier"], f"{float(r['received_pct'] or 0):g}%"] for r in rows],
        },
        "link": {"label": "Open purchase orders", "href": "/purchase-orders"},
    }


async def _open_variances(session, company_id: str, godown_filter: str, params: dict) -> dict:
    rows = (
        await session.execute(
            text(
                # The issue reads "price on MCB-32A: 90 → 99".
                "SELECT dv.compare_doc_type, dv.severity, "
                "dv.variance_type || COALESCE(' on ' || v.sku, '') || COALESCE(': ' || "
                "  trim(trailing '.' FROM trim(trailing '0' FROM dv.base_value::text)) || ' → ' || "
                "  trim(trailing '.' FROM trim(trailing '0' FROM dv.compare_value::text)), '') AS issue "
                "FROM document_variances dv "
                "LEFT JOIN product_variants v ON v.id = dv.product_variant_id AND v.company_id = dv.company_id "
                "WHERE dv.company_id = :c AND dv.status IN ('open', 'disputed') "
                "ORDER BY CASE dv.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, abs(COALESCE(dv.difference_pct, 0)) DESC "
                "LIMIT 100"
            ),
            {"c": company_id},
        )
    ).mappings().all()
    return {
        "source": "document_variances still open or disputed",
        "answer": f"{len(rows)} unresolved variance{'' if len(rows) == 1 else 's'} across your documents.",
        "table": {
            "columns": ["Document", "Issue", "Severity"],
            "rows": [[(r["compare_doc_type"] or "").replace("_", " "), r["issue"], r["severity"]] for r in rows],
        },
        "link": {"label": "Review variances", "href": "/alerts"},
    }


def _rupees(value) -> str:
    """Indian grouping — 12,34,567.89, not 1,234,567.89. A number formatted
    the wrong way is read wrong at a glance, which is the only way anyone
    reads a total."""
    amount = float(value or 0)
    negative = amount < 0
    whole, _, fraction = f"{abs(amount):.2f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{'-' if negative else ''}Rs {whole}.{fraction}"
