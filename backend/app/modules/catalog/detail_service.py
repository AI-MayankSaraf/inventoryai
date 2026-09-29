"""
Supplier and catalogue detail panels — the data behind the Supplier detail
and Product detail screens that is not the master row itself:

  * supplier contacts                        (`supplier_contacts`)
  * supplier ⇄ SKU links ("aliases")         (`supplier_products`, plus
    pairs derived from purchase history)
  * supplier performance, PO history, price history (derived, never stored)
  * "is this record still in use" checks     (the BR-MD blocking rule)
  * UoM conversions per variant              (`product_uom_conversions`)
  * per-godown reorder levels                (`variant_godown_policies`)

Two conventions worth knowing before editing:

1. **Child changes are audited on the parent.** A contact edit is recorded
   as an `updated` event on the *supplier* (and a conversion/policy change
   on the *product_variant*) with a plain-English `description`. That is
   where a person looks for it — the parent's Audit Trail panel — and it
   needs no widening of the `audit_logs.entity_type` CHECK.

2. **Every statement carries `company_id = :c`**, same belt-and-braces rule
   as `crud.py`, even though RLS already enforces it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import Request, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.db import commit_and_rescope
from app.core.deps import assert_godown_in_scope
from app.core.errors import (
    CODE_BUSINESS_RULE_VIOLATION,
    CODE_DUPLICATE,
    CODE_NOT_FOUND,
    CODE_RECORD_IN_USE,
    CODE_VALIDATION,
    ApiError,
)
from app.core.security import AccessTokenClaims

# PO states that mean "we actually committed to buy at this price". Drafts
# and anything still awaiting approval are not a purchase yet.
_COMMITTED_PO = "('approved','sent','acknowledged','partially_received','received','closed')"
# PO states that block deactivating the supplier (BR-MD-10).
_OPEN_PO = "('draft','pending_approval','approved','sent','acknowledged','partially_received')"
# GRN states that posted stock.
_POSTED_GRN = "('confirmed','partially_received','received')"


def _f(value: Any) -> Optional[float]:
    return None if value is None else float(value)


def _not_found(what: str) -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, f"{what} not found")


# ============================================================== lookups

async def _supplier(session: AsyncSession, c: str, supplier_id: UUID) -> dict:
    row = (
        await session.execute(
            text("SELECT id, name, status FROM suppliers WHERE id = :id AND company_id = :c AND deleted_at IS NULL"),
            {"id": supplier_id, "c": c},
        )
    ).mappings().first()
    if row is None:
        raise _not_found("Supplier")
    return dict(row)


async def _variant(session: AsyncSession, c: str, variant_id: UUID) -> dict:
    row = (
        await session.execute(
            text(
                "SELECT pv.id, pv.sku, pv.uom_id FROM product_variants pv "
                "WHERE pv.id = :id AND pv.company_id = :c AND pv.deleted_at IS NULL"
            ),
            {"id": variant_id, "c": c},
        )
    ).mappings().first()
    if row is None:
        raise _not_found("Product variant")
    return dict(row)


async def _usable_uom(session: AsyncSession, c: str, uom_id: UUID, field: str) -> dict:
    row = (
        await session.execute(
            text(
                "SELECT id, code, is_active FROM uoms WHERE id = :id "
                "AND (company_id = :c OR company_id IS NULL)"
            ),
            {"id": uom_id, "c": c},
        )
    ).mappings().first()
    if row is None or not row["is_active"]:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_VALIDATION,
            "That unit of measure does not exist or is inactive",
            errors=[{"field": field, "message": "Choose an active unit"}],
        )
    return dict(row)


async def _audit_child(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    entity_type: str,
    entity_id: UUID,
    label: str,
    description: str,
    before: Optional[dict],
    after: Optional[dict],
    request: Optional[Request],
) -> None:
    await audit.record(
        session,
        entity_type=entity_type,
        action="updated",
        claims=claims,
        entity_id=entity_id,
        entity_label=label,
        description=description,
        before=before,
        after=after,
        request=request,
    )


# ============================================================= contacts

_CONTACT_COLS = "id, supplier_id, name, designation, phone, email, is_primary"


async def list_contacts(session: AsyncSession, *, claims: AccessTokenClaims, supplier_id: UUID) -> list[dict]:
    await _supplier(session, claims.company_id, supplier_id)
    rows = (
        await session.execute(
            text(
                f"SELECT {_CONTACT_COLS} FROM supplier_contacts "
                "WHERE supplier_id = :s AND company_id = :c AND is_active "
                "ORDER BY is_primary DESC, lower(name)"
            ),
            {"s": supplier_id, "c": claims.company_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def _contact_conflict(exc: IntegrityError) -> ApiError:
    if "uq_supplier_contact_email" in str(exc.orig):
        return ApiError(
            status.HTTP_409_CONFLICT,
            CODE_DUPLICATE,
            "This supplier already has a contact with that email",
            errors=[{"field": "email", "message": "Already used by another contact"}],
        )
    raise exc


async def _clear_primary(session: AsyncSession, c: str, supplier_id: UUID, keep: UUID) -> None:
    await session.execute(
        text(
            "UPDATE supplier_contacts SET is_primary = false "
            "WHERE supplier_id = :s AND company_id = :c AND id <> :keep AND is_primary"
        ),
        {"s": supplier_id, "c": c, "keep": keep},
    )


async def create_contact(
    session: AsyncSession, *, claims: AccessTokenClaims, supplier_id: UUID, values: dict, request: Request
) -> dict:
    c = claims.company_id
    supplier = await _supplier(session, c, supplier_id)

    # The first contact on a supplier is its primary one — otherwise a
    # supplier with a single contact would have "no primary contact".
    existing = (
        await session.execute(
            text("SELECT count(*) FROM supplier_contacts WHERE supplier_id = :s AND company_id = :c AND is_active"),
            {"s": supplier_id, "c": c},
        )
    ).scalar_one()
    is_primary = bool(values.get("is_primary")) or existing == 0

    new_id = uuid4()
    if is_primary:
        await _clear_primary(session, c, supplier_id, new_id)
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO supplier_contacts (id, company_id, supplier_id, name, designation, phone, email, is_primary) "
                    "VALUES (:id, :c, :s, :name, :designation, :phone, :email, :is_primary) "
                    f"RETURNING {_CONTACT_COLS}"
                ),
                {
                    "id": new_id,
                    "c": c,
                    "s": supplier_id,
                    "name": values["name"].strip(),
                    "designation": values.get("designation"),
                    "phone": values.get("phone"),
                    "email": values.get("email"),
                    "is_primary": is_primary,
                },
            )
        ).mappings().first()
    except IntegrityError as exc:
        raise _contact_conflict(exc)

    created = dict(row)
    await _audit_child(
        session, claims=claims, entity_type="supplier", entity_id=supplier_id, label=supplier["name"],
        description=f"Contact added: {created['name']}", before=None, after={"contact": created}, request=request,
    )
    await session.commit()
    return created


async def _contact(session: AsyncSession, c: str, contact_id: UUID) -> dict:
    row = (
        await session.execute(
            text(
                f"SELECT sc.{_CONTACT_COLS.replace(', ', ', sc.')}, s.name AS supplier_name "
                "FROM supplier_contacts sc JOIN suppliers s ON s.id = sc.supplier_id AND s.company_id = sc.company_id "
                "WHERE sc.id = :id AND sc.company_id = :c AND sc.is_active AND s.deleted_at IS NULL"
            ),
            {"id": contact_id, "c": c},
        )
    ).mappings().first()
    if row is None:
        raise _not_found("Contact")
    return dict(row)


async def update_contact(
    session: AsyncSession, *, claims: AccessTokenClaims, contact_id: UUID, values: dict, request: Request
) -> dict:
    c = claims.company_id
    before = await _contact(session, c, contact_id)
    supplier_name = before.pop("supplier_name")
    payload = {k: v for k, v in values.items() if k in ("name", "designation", "phone", "email", "is_primary")}
    if "name" in payload:
        if payload["name"] is None:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_VALIDATION, "A contact needs a name",
                errors=[{"field": "name", "message": "Required"}],
            )
        payload["name"] = payload["name"].strip()
    if "is_primary" in payload and payload["is_primary"] is None:
        payload.pop("is_primary")
    if not payload:
        return before

    if payload.get("is_primary"):
        await _clear_primary(session, c, before["supplier_id"], contact_id)

    sets = ", ".join(f"{k} = :{k}" for k in payload)
    try:
        row = (
            await session.execute(
                text(f"UPDATE supplier_contacts SET {sets} WHERE id = :id AND company_id = :c RETURNING {_CONTACT_COLS}"),
                {**payload, "id": contact_id, "c": c},
            )
        ).mappings().first()
    except IntegrityError as exc:
        raise _contact_conflict(exc)

    after = dict(row)
    await _audit_child(
        session, claims=claims, entity_type="supplier", entity_id=before["supplier_id"], label=supplier_name,
        description=f"Contact updated: {after['name']}", before={"contact": before}, after={"contact": after},
        request=request,
    )
    await session.commit()
    return after


async def delete_contact(session: AsyncSession, *, claims: AccessTokenClaims, contact_id: UUID, request: Request) -> None:
    c = claims.company_id
    before = await _contact(session, c, contact_id)
    supplier_name = before.pop("supplier_name")
    # Hard delete is safe: the only reference (`rfq_suppliers.supplier_contact_id`)
    # is ON DELETE SET NULL, and the RFQ keeps the email it was sent to.
    await session.execute(
        text("DELETE FROM supplier_contacts WHERE id = :id AND company_id = :c"), {"id": contact_id, "c": c}
    )
    await _audit_child(
        session, claims=claims, entity_type="supplier", entity_id=before["supplier_id"], label=supplier_name,
        description=f"Contact removed: {before['name']}", before={"contact": before}, after=None, request=request,
    )
    await session.commit()


# ============================================== supplier ⇄ SKU links

_LINKS_SQL = f"""
WITH links AS (
    SELECT DISTINCT ON (sp.supplier_id, sp.product_variant_id) sp.*
    FROM supplier_products sp
    WHERE sp.company_id = :c
      AND (CAST(:supplier_id AS uuid) IS NULL OR sp.supplier_id = CAST(:supplier_id AS uuid))
      AND (CAST(:variant_id AS uuid) IS NULL OR sp.product_variant_id = CAST(:variant_id AS uuid))
    ORDER BY sp.supplier_id, sp.product_variant_id, sp.is_preferred DESC, sp.confirmed_at DESC NULLS LAST
),
bought AS (
    SELECT DISTINCT po.supplier_id, poi.product_variant_id
    FROM purchase_order_items poi
    JOIN purchase_orders po ON po.id = poi.purchase_order_id AND po.company_id = poi.company_id
    WHERE poi.company_id = :c AND po.status IN {_COMMITTED_PO}
      AND (CAST(:supplier_id AS uuid) IS NULL OR po.supplier_id = CAST(:supplier_id AS uuid))
      AND (CAST(:variant_id AS uuid) IS NULL OR poi.product_variant_id = CAST(:variant_id AS uuid))
),
pairs AS (
    SELECT supplier_id, product_variant_id FROM links
    UNION
    SELECT supplier_id, product_variant_id FROM bought
)
SELECT l.id, pr.supplier_id, s.name AS supplier_name, pr.product_variant_id, pv.sku,
       TRIM(p.name || ' ' || COALESCE(pv.variant_name, '')) AS product_name,
       l.supplier_sku, l.supplier_description, l.supplier_uom_id,
       COALESCE(l.conversion_to_base, 1) AS conversion_to_base,
       l.last_quoted_price, l.last_quoted_at,
       COALESCE(lp.rate, l.last_purchase_price) AS last_purchase_price,
       COALESCE(lp.po_date, l.last_purchase_at) AS last_purchase_at,
       l.lead_time_days, COALESCE(l.is_preferred, false) AS is_preferred,
       COALESCE(l.match_source, 'purchase_history') AS match_source, l.confirmed_at
FROM pairs pr
JOIN suppliers s ON s.id = pr.supplier_id AND s.company_id = :c AND s.deleted_at IS NULL
JOIN product_variants pv ON pv.id = pr.product_variant_id AND pv.company_id = :c AND pv.deleted_at IS NULL
JOIN products p ON p.id = pv.product_id AND p.company_id = pv.company_id
LEFT JOIN links l ON l.supplier_id = pr.supplier_id AND l.product_variant_id = pr.product_variant_id
LEFT JOIN LATERAL (
    SELECT ROUND(poi.unit_price * (1 - COALESCE(poi.discount_pct, 0) / 100), 4) AS rate, po.po_date
    FROM purchase_order_items poi
    JOIN purchase_orders po ON po.id = poi.purchase_order_id AND po.company_id = poi.company_id
    WHERE poi.company_id = :c AND po.supplier_id = pr.supplier_id
      AND poi.product_variant_id = pr.product_variant_id AND po.status IN {_COMMITTED_PO}
    ORDER BY po.po_date DESC, po.po_number DESC
    LIMIT 1
) lp ON TRUE
ORDER BY {{order}}
"""


def _link_row(r) -> dict:
    d = dict(r)
    for k in ("conversion_to_base", "last_quoted_price", "last_purchase_price"):
        d[k] = _f(d[k])
    return d


async def list_links(
    session: AsyncSession, *, claims: AccessTokenClaims, supplier_id: Optional[UUID] = None,
    variant_id: Optional[UUID] = None,
) -> list[dict]:
    c = claims.company_id
    if supplier_id is not None:
        await _supplier(session, c, supplier_id)
        order = "pv.sku"
    else:
        await _variant(session, c, variant_id)
        order = "COALESCE(l.is_preferred, false) DESC, s.name"
    rows = (
        await session.execute(
            text(_LINKS_SQL.replace("{order}", order)),
            {"c": c, "supplier_id": supplier_id, "variant_id": variant_id},
        )
    ).mappings().all()
    return [_link_row(r) for r in rows]


async def upsert_link(
    session: AsyncSession, *, claims: AccessTokenClaims, supplier_id: UUID, values: dict, request: Request
) -> tuple[dict, bool]:
    """Returns (row, created)."""
    c = claims.company_id
    supplier = await _supplier(session, c, supplier_id)
    variant = await _variant(session, c, values["product_variant_id"])
    if values.get("supplier_uom_id"):
        await _usable_uom(session, c, values["supplier_uom_id"], "supplier_uom_id")
    sku = (values.get("supplier_sku") or "").strip() or None

    # Serialise concurrent upserts of the same pair — there is no unique
    # constraint on (supplier, variant) to lean on.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"sp:{supplier_id}:{variant['id']}"}
    )
    existing = (
        await session.execute(
            text(
                "SELECT * FROM supplier_products WHERE company_id = :c AND supplier_id = :s "
                "AND product_variant_id = :v ORDER BY is_preferred DESC LIMIT 1"
            ),
            {"c": c, "s": supplier_id, "v": variant["id"]},
        )
    ).mappings().first()

    params = {
        "c": c, "s": supplier_id, "v": variant["id"], "sku": sku,
        "descr": values.get("supplier_description"), "uom": values.get("supplier_uom_id"),
        "conv": Decimal(str(values.get("conversion_to_base") or 1)), "lead": values.get("lead_time_days"),
        "pref": bool(values.get("is_preferred")), "src": values.get("match_source") or "manual",
        "who": claims.user_id,
    }
    try:
        if existing is None:
            params["id"] = uuid4()
            await session.execute(
                text(
                    "INSERT INTO supplier_products (id, company_id, supplier_id, product_variant_id, supplier_sku, "
                    "supplier_description, supplier_uom_id, conversion_to_base, lead_time_days, is_preferred, "
                    "match_source, confirmed_by, confirmed_at) VALUES (:id, :c, :s, :v, :sku, :descr, :uom, :conv, "
                    ":lead, :pref, :src, :who, now())"
                ),
                params,
            )
            link_id = params["id"]
        else:
            link_id = existing["id"]
            params["id"] = link_id
            await session.execute(
                text(
                    "UPDATE supplier_products SET supplier_sku = :sku, supplier_description = :descr, "
                    "supplier_uom_id = :uom, conversion_to_base = :conv, lead_time_days = :lead, is_preferred = :pref, "
                    "match_source = :src, confirmed_by = :who, confirmed_at = now() WHERE id = :id AND company_id = :c"
                ),
                params,
            )
    except IntegrityError as exc:
        if "uq_supplier_sku" in str(exc.orig):
            raise ApiError(
                status.HTTP_409_CONFLICT, CODE_DUPLICATE,
                "This supplier's item code is already linked to another SKU",
                errors=[{"field": "supplier_sku", "message": "Already mapped to a different SKU"}],
            )
        raise

    if params["pref"]:
        # One preferred supplier per SKU — the reorder report and the
        # "suggested supplier" on Low Stock pick exactly one.
        await session.execute(
            text(
                "UPDATE supplier_products SET is_preferred = false WHERE company_id = :c "
                "AND product_variant_id = :v AND id <> :id AND is_preferred"
            ),
            {"c": c, "v": variant["id"], "id": link_id},
        )

    before = None if existing is None else {k: existing[k] for k in ("supplier_sku", "supplier_description", "is_preferred", "lead_time_days")}
    await _audit_child(
        session, claims=claims, entity_type="supplier", entity_id=supplier_id, label=supplier["name"],
        description=(
            f"Item code {sku} linked to {variant['sku']}" if sku else f"Linked to {variant['sku']}"
        ) + (" (preferred)" if params["pref"] else ""),
        before=before,
        after={"supplier_sku": sku, "supplier_description": params["descr"], "is_preferred": params["pref"],
               "lead_time_days": params["lead"], "product_variant": variant["sku"]},
        request=request,
    )
    await commit_and_rescope(session, UUID(c))
    rows = await list_links(session, claims=claims, supplier_id=supplier_id)
    row = next(r for r in rows if r["product_variant_id"] == variant["id"])
    return row, existing is None


async def delete_link(session: AsyncSession, *, claims: AccessTokenClaims, link_id: UUID, request: Request) -> None:
    c = claims.company_id
    row = (
        await session.execute(
            text(
                "SELECT sp.id, sp.supplier_id, sp.supplier_sku, s.name AS supplier_name, pv.sku "
                "FROM supplier_products sp "
                "JOIN suppliers s ON s.id = sp.supplier_id AND s.company_id = sp.company_id AND s.deleted_at IS NULL "
                "JOIN product_variants pv ON pv.id = sp.product_variant_id AND pv.company_id = sp.company_id "
                "WHERE sp.id = :id AND sp.company_id = :c"
            ),
            {"id": link_id, "c": c},
        )
    ).mappings().first()
    if row is None:
        raise _not_found("Supplier item link")
    await session.execute(text("DELETE FROM supplier_products WHERE id = :id AND company_id = :c"), {"id": link_id, "c": c})
    await _audit_child(
        session, claims=claims, entity_type="supplier", entity_id=row["supplier_id"], label=row["supplier_name"],
        description=f"Item link to {row['sku']} removed", before={"supplier_sku": row["supplier_sku"], "product_variant": row["sku"]},
        after=None, request=request,
    )
    await session.commit()


# ========================================================== performance

_PERFORMANCE_SQL = f"""
WITH sup AS (
    SELECT id FROM suppliers
    WHERE company_id = :c AND deleted_at IS NULL
      AND (CAST(:supplier_id AS uuid) IS NULL OR id = CAST(:supplier_id AS uuid))
),
pairs AS (
    SELECT sp.supplier_id, sp.product_variant_id FROM supplier_products sp
    JOIN product_variants pv ON pv.id = sp.product_variant_id AND pv.company_id = sp.company_id AND pv.deleted_at IS NULL
    WHERE sp.company_id = :c
    UNION
    SELECT po.supplier_id, poi.product_variant_id FROM purchase_order_items poi
    JOIN purchase_orders po ON po.id = poi.purchase_order_id AND po.company_id = poi.company_id
    JOIN product_variants pv ON pv.id = poi.product_variant_id AND pv.company_id = poi.company_id AND pv.deleted_at IS NULL
    WHERE poi.company_id = :c AND po.status IN {_COMMITTED_PO}
),
products AS (SELECT supplier_id, COUNT(*) AS n FROM pairs GROUP BY supplier_id),
orders AS (
    SELECT supplier_id, COUNT(*) FILTER (WHERE status IN {_OPEN_PO} AND status <> 'draft') AS open_orders
    FROM purchase_orders WHERE company_id = :c GROUP BY supplier_id
),
receipts AS (
    SELECT gr.supplier_id,
           SUM(gi.received_quantity) AS received,
           SUM(gi.accepted_quantity) AS accepted,
           SUM(gi.accepted_quantity * COALESCE(poi.unit_price * (1 - COALESCE(poi.discount_pct, 0) / 100), gi.unit_price, 0)) AS spend
    FROM goods_receipts gr
    JOIN goods_receipt_items gi ON gi.goods_receipt_id = gr.id AND gi.company_id = gr.company_id
    LEFT JOIN purchase_order_items poi ON poi.id = gi.purchase_order_item_id AND poi.company_id = gi.company_id
    WHERE gr.company_id = :c AND gr.status IN {_POSTED_GRN}
    GROUP BY gr.supplier_id
),
delivery AS (
    SELECT po.supplier_id, COUNT(*) AS due,
           COUNT(*) FILTER (WHERE g.first_grn <= po.expected_delivery_date) AS on_time
    FROM purchase_orders po
    JOIN LATERAL (
        SELECT MIN(gr.grn_date) AS first_grn FROM goods_receipts gr
        WHERE gr.purchase_order_id = po.id AND gr.company_id = po.company_id AND gr.status IN {_POSTED_GRN}
    ) g ON g.first_grn IS NOT NULL
    WHERE po.company_id = :c AND po.expected_delivery_date IS NOT NULL
    GROUP BY po.supplier_id
),
variances AS (
    SELECT s.id AS supplier_id, COUNT(dv.id) AS n
    FROM sup s
    JOIN document_variances dv ON dv.company_id = :c AND dv.status = 'open' AND (
        (dv.base_doc_type = 'purchase_order' AND dv.base_doc_id IN
            (SELECT id FROM purchase_orders WHERE company_id = :c AND supplier_id = s.id))
        OR (dv.base_doc_type = 'goods_receipt' AND dv.base_doc_id IN
            (SELECT id FROM goods_receipts WHERE company_id = :c AND supplier_id = s.id))
    )
    GROUP BY s.id
)
SELECT sup.id AS supplier_id,
       COALESCE(pr.n, 0) AS products_supplied,
       COALESCE(r.spend, 0) AS total_purchases,
       COALESCE(o.open_orders, 0) AS open_orders,
       CASE WHEN COALESCE(d.due, 0) > 0 THEN ROUND(d.on_time * 100.0 / d.due) ELSE 0 END AS on_time_delivery_pct,
       CASE WHEN COALESCE(r.received, 0) > 0 THEN ROUND(r.accepted * 100.0 / r.received) ELSE 0 END AS quality_score_pct,
       COALESCE(v.n, 0) AS open_variances
FROM sup
LEFT JOIN products pr ON pr.supplier_id = sup.id
LEFT JOIN orders o ON o.supplier_id = sup.id
LEFT JOIN receipts r ON r.supplier_id = sup.id
LEFT JOIN delivery d ON d.supplier_id = sup.id
LEFT JOIN variances v ON v.supplier_id = sup.id
"""


def _perf_row(r) -> dict:
    return {
        "supplier_id": r["supplier_id"],
        "products_supplied": int(r["products_supplied"]),
        "total_purchases": round(float(r["total_purchases"]), 2),
        "open_orders": int(r["open_orders"]),
        "on_time_delivery_pct": int(r["on_time_delivery_pct"]),
        "quality_score_pct": int(r["quality_score_pct"]),
        "open_variances": int(r["open_variances"]),
    }


async def performance(
    session: AsyncSession, *, claims: AccessTokenClaims, supplier_id: Optional[UUID] = None
) -> list[dict]:
    if supplier_id is not None:
        await _supplier(session, claims.company_id, supplier_id)
    rows = (
        await session.execute(text(_PERFORMANCE_SQL), {"c": claims.company_id, "supplier_id": supplier_id})
    ).mappings().all()
    return [_perf_row(r) for r in rows]


async def supplier_orders(session: AsyncSession, *, claims: AccessTokenClaims, supplier_id: UUID, limit: int) -> list[dict]:
    await _supplier(session, claims.company_id, supplier_id)
    rows = (
        await session.execute(
            text(
                "SELECT id, po_number, po_date, status, total_amount, received_pct FROM purchase_orders "
                "WHERE company_id = :c AND supplier_id = :s ORDER BY po_date DESC, po_number DESC LIMIT :limit"
            ),
            {"c": claims.company_id, "s": supplier_id, "limit": limit},
        )
    ).mappings().all()
    return [
        {**dict(r), "total_amount": float(r["total_amount"] or 0), "received_pct": float(r["received_pct"] or 0)}
        for r in rows
    ]


async def price_history(
    session: AsyncSession, *, claims: AccessTokenClaims, supplier_id: UUID, variant_id: UUID
) -> list[dict]:
    c = claims.company_id
    await _supplier(session, c, supplier_id)
    await _variant(session, c, variant_id)
    rows = (
        await session.execute(
            text(
                "SELECT po.id AS po_id, po.po_number, po.po_date, "
                "ROUND(poi.unit_price * (1 - COALESCE(poi.discount_pct, 0) / 100), 4) AS unit_price "
                "FROM purchase_order_items poi "
                "JOIN purchase_orders po ON po.id = poi.purchase_order_id AND po.company_id = poi.company_id "
                f"WHERE poi.company_id = :c AND po.supplier_id = :s AND poi.product_variant_id = :v AND po.status IN {_COMMITTED_PO} "
                "ORDER BY po.po_date DESC, po.po_number DESC, poi.line_no LIMIT 50"
            ),
            {"c": c, "s": supplier_id, "v": variant_id},
        )
    ).mappings().all()
    out = []
    for i, r in enumerate(rows):
        price = float(r["unit_price"])
        prev = float(rows[i + 1]["unit_price"]) if i + 1 < len(rows) else None
        change = round((price - prev) / prev * 100, 2) if prev else 0.0
        out.append({"po_id": r["po_id"], "po_number": r["po_number"], "po_date": r["po_date"],
                    "unit_price": price, "change_pct": change})
    return out


# ============================================================== in-use

async def supplier_usage(session: AsyncSession, *, company_id: str, supplier_id: UUID) -> dict:
    await _supplier(session, company_id, supplier_id)
    po = (
        await session.execute(
            text(
                f"SELECT po_number FROM purchase_orders WHERE company_id = :c AND supplier_id = :s AND status IN {_OPEN_PO} "
                "ORDER BY po_date LIMIT 1"
            ),
            {"c": company_id, "s": supplier_id},
        )
    ).scalar_one_or_none()
    if po:
        return {"in_use": True, "reason": f"Open purchase order {po}"}
    inv = (
        await session.execute(
            text(
                "SELECT invoice_number FROM supplier_invoices WHERE company_id = :c AND supplier_id = :s "
                "AND payment_status <> 'paid' AND status <> 'cancelled' ORDER BY invoice_date LIMIT 1"
            ),
            {"c": company_id, "s": supplier_id},
        )
    ).scalar_one_or_none()
    if inv:
        return {"in_use": True, "reason": f"Unpaid invoice {inv}"}
    return {"in_use": False, "reason": None}


async def variant_usage(session: AsyncSession, *, company_id: str, variant_id: UUID) -> dict:
    variant = await _variant(session, company_id, variant_id)
    on_hand = (
        await session.execute(
            text("SELECT COALESCE(SUM(quantity), 0) FROM stock_balances WHERE company_id = :c AND product_variant_id = :v"),
            {"c": company_id, "v": variant_id},
        )
    ).scalar_one()
    if on_hand and Decimal(str(on_hand)) > 0:
        qty = Decimal(str(on_hand)).normalize()
        return {"in_use": True, "reason": f"{qty:f} units of {variant['sku']} still in stock"}
    po = (
        await session.execute(
            text(
                "SELECT po.po_number FROM purchase_order_items poi "
                "JOIN purchase_orders po ON po.id = poi.purchase_order_id AND po.company_id = poi.company_id "
                "WHERE poi.company_id = :c AND poi.product_variant_id = :v "
                f"AND poi.line_status IN ('open','partially_received') AND po.status IN {_OPEN_PO} "
                "ORDER BY po.po_date LIMIT 1"
            ),
            {"c": company_id, "v": variant_id},
        )
    ).scalar_one_or_none()
    if po:
        return {"in_use": True, "reason": f"Used on open purchase order {po}"}
    return {"in_use": False, "reason": None}


def raise_in_use(usage: dict, noun: str) -> None:
    if usage["in_use"]:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_RECORD_IN_USE,
            f"This {noun} is still in use: {usage['reason']}",
        )


# ====================================================== UoM conversions

_CONV_SQL = """
SELECT cv.id, cv.product_variant_id, cv.from_uom_id, fu.code AS from_code, cv.to_uom_id, tu.code AS to_code,
       cv.factor, cv.is_purchase_default
FROM product_uom_conversions cv
JOIN uoms fu ON fu.id = cv.from_uom_id
JOIN uoms tu ON tu.id = cv.to_uom_id
WHERE cv.company_id = :c AND {where}
ORDER BY fu.code
"""


def _conv_row(r) -> dict:
    return {**dict(r), "factor": float(r["factor"])}


async def list_conversions(session: AsyncSession, *, claims: AccessTokenClaims, variant_id: UUID) -> list[dict]:
    await _variant(session, claims.company_id, variant_id)
    rows = (
        await session.execute(
            text(_CONV_SQL.replace("{where}", "cv.product_variant_id = :v")), {"c": claims.company_id, "v": variant_id}
        )
    ).mappings().all()
    return [_conv_row(r) for r in rows]


async def create_conversion(
    session: AsyncSession, *, claims: AccessTokenClaims, variant_id: UUID, values: dict, request: Request
) -> dict:
    c = claims.company_id
    variant = await _variant(session, c, variant_id)
    from_uom = await _usable_uom(session, c, values["from_uom_id"], "from_uom_id")
    if from_uom["id"] == variant["uom_id"]:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_BUSINESS_RULE_VIOLATION,
            "A unit cannot be converted to itself — pick a different unit than the item's base unit",
            errors=[{"field": "from_uom_id", "message": "Same as the base unit"}],
        )
    new_id = uuid4()
    if values.get("is_purchase_default"):
        await session.execute(
            text(
                "UPDATE product_uom_conversions SET is_purchase_default = false "
                "WHERE company_id = :c AND product_variant_id = :v AND is_purchase_default"
            ),
            {"c": c, "v": variant_id},
        )
    try:
        await session.execute(
            text(
                "INSERT INTO product_uom_conversions (id, company_id, product_variant_id, from_uom_id, to_uom_id, factor, "
                "is_purchase_default) VALUES (:id, :c, :v, :f, :t, :factor, :d)"
            ),
            {"id": new_id, "c": c, "v": variant_id, "f": from_uom["id"], "t": variant["uom_id"],
             "factor": Decimal(str(values["factor"])), "d": bool(values.get("is_purchase_default"))},
        )
    except IntegrityError as exc:
        if "uq_conversion" in str(exc.orig):
            raise ApiError(
                status.HTTP_409_CONFLICT, CODE_DUPLICATE,
                f"{variant['sku']} already has a conversion from {from_uom['code']}",
                errors=[{"field": "from_uom_id", "message": "Already has a conversion — remove it first to change the factor"}],
            )
        raise
    row = (
        await session.execute(text(_CONV_SQL.replace("{where}", "cv.id = :id")), {"c": c, "id": new_id})
    ).mappings().first()
    created = _conv_row(row)
    await _audit_child(
        session, claims=claims, entity_type="product_variant", entity_id=variant_id, label=variant["sku"],
        description=f"Unit conversion added: 1 {created['from_code']} = {created['factor']:g} {created['to_code']}",
        before=None, after={"conversion": created}, request=request,
    )
    await session.commit()
    return created


async def delete_conversion(session: AsyncSession, *, claims: AccessTokenClaims, conversion_id: UUID, request: Request) -> None:
    c = claims.company_id
    row = (
        await session.execute(
            text(
                _CONV_SQL.replace("{where}", "cv.id = :id")
                .replace("FROM product_uom_conversions cv", "FROM product_uom_conversions cv "
                         "JOIN product_variants pv ON pv.id = cv.product_variant_id AND pv.company_id = cv.company_id "
                         "AND pv.deleted_at IS NULL")
                .replace("SELECT cv.id,", "SELECT pv.sku, cv.id,")
            ),
            {"c": c, "id": conversion_id},
        )
    ).mappings().first()
    if row is None:
        raise _not_found("Unit conversion")
    before = _conv_row(row)
    sku = before.pop("sku")
    # Hard delete is safe: every document line froze the factor it used
    # (BR-INV-08), so removing the conversion never rewrites history.
    await session.execute(
        text("DELETE FROM product_uom_conversions WHERE id = :id AND company_id = :c"), {"id": conversion_id, "c": c}
    )
    await _audit_child(
        session, claims=claims, entity_type="product_variant", entity_id=before["product_variant_id"], label=sku,
        description=f"Unit conversion removed: {before['from_code']} → {before['to_code']}",
        before={"conversion": before}, after=None, request=request,
    )
    await session.commit()


# ================================================ per-godown policies

_POLICY_SQL = """
SELECT vgp.id, vgp.product_variant_id, vgp.godown_id, g.name AS godown_name, vgp.reorder_point, vgp.reorder_qty,
       vgp.max_stock, vgp.is_stocked
FROM variant_godown_policies vgp
JOIN godowns g ON g.id = vgp.godown_id AND g.company_id = vgp.company_id AND g.deleted_at IS NULL
WHERE vgp.company_id = :c AND vgp.product_variant_id = :v
ORDER BY g.name
"""


def _policy_row(r) -> dict:
    return {**dict(r), "reorder_point": float(r["reorder_point"]), "reorder_qty": float(r["reorder_qty"]),
            "max_stock": _f(r["max_stock"])}


async def list_policies(session: AsyncSession, *, claims: AccessTokenClaims, variant_id: UUID) -> list[dict]:
    await _variant(session, claims.company_id, variant_id)
    rows = (await session.execute(text(_POLICY_SQL), {"c": claims.company_id, "v": variant_id})).mappings().all()
    return [_policy_row(r) for r in rows]


def _policy_key(p: dict) -> tuple:
    return (
        round(float(p["reorder_point"]), 3), round(float(p["reorder_qty"]), 3),
        None if p.get("max_stock") is None else round(float(p["max_stock"]), 3), bool(p["is_stocked"]),
    )


async def replace_policies(
    session: AsyncSession, *, claims: AccessTokenClaims, variant_id: UUID, policies: list[dict], request: Request
) -> list[dict]:
    c = claims.company_id
    variant = await _variant(session, c, variant_id)

    seen: set = set()
    for i, p in enumerate(policies):
        if p["godown_id"] in seen:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_VALIDATION, "Each godown can appear only once",
                errors=[{"field": f"policies.{i}.godown_id", "message": "Duplicate godown"}],
            )
        seen.add(p["godown_id"])

    if seen:
        live = set(
            (
                await session.execute(
                    text(
                        "SELECT id FROM godowns WHERE company_id = :c AND deleted_at IS NULL "
                        "AND id = ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"c": c, "ids": [str(g) for g in seen]},
                )
            ).scalars().all()
        )
        for i, p in enumerate(policies):
            if p["godown_id"] not in live:
                raise ApiError(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_VALIDATION, "That godown does not exist",
                    errors=[{"field": f"policies.{i}.godown_id", "message": "Unknown godown"}],
                )

    before_rows = await list_policies(session, claims=claims, variant_id=variant_id)
    before = {r["godown_id"]: r for r in before_rows}
    after = {p["godown_id"]: p for p in policies}

    # BR-AUTH-12 on the write side: a godown-scoped user may only change
    # levels for godowns in their scope — adding, editing *or* removing.
    touched = [g for g in set(before) | set(after)
               if g not in before or g not in after or _policy_key(before[g]) != _policy_key(after[g])]
    for g in touched:
        assert_godown_in_scope(claims, g)

    removed = [g for g in before if g not in after]
    if removed:
        await session.execute(
            text(
                "DELETE FROM variant_godown_policies WHERE company_id = :c AND product_variant_id = :v "
                "AND godown_id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"c": c, "v": variant_id, "ids": [str(g) for g in removed]},
        )
    for g in touched:
        if g not in after:
            continue
        p = after[g]
        await session.execute(
            text(
                "INSERT INTO variant_godown_policies (id, company_id, product_variant_id, godown_id, reorder_point, "
                "reorder_qty, max_stock, is_stocked) VALUES (:id, :c, :v, :g, :rp, :rq, :mx, :st) "
                "ON CONFLICT (product_variant_id, godown_id) DO UPDATE SET reorder_point = EXCLUDED.reorder_point, "
                "reorder_qty = EXCLUDED.reorder_qty, max_stock = EXCLUDED.max_stock, is_stocked = EXCLUDED.is_stocked"
            ),
            {"id": uuid4(), "c": c, "v": variant_id, "g": g, "rp": Decimal(str(p["reorder_point"])),
             "rq": Decimal(str(p["reorder_qty"])), "mx": None if p.get("max_stock") is None else Decimal(str(p["max_stock"])),
             "st": bool(p["is_stocked"])},
        )

    if touched:
        await _audit_child(
            session, claims=claims, entity_type="product_variant", entity_id=variant_id, label=variant["sku"],
            description=f"Godown reorder levels changed ({len(touched)} godown{'s' if len(touched) != 1 else ''})",
            before={"policies": before_rows},
            after={"policies": [{**p, "godown_id": str(p["godown_id"])} for p in policies]},
            request=request,
        )
    await commit_and_rescope(session, UUID(c))
    return await list_policies(session, claims=claims, variant_id=variant_id)
