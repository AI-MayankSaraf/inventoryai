"""
Goods receipt service — 06_BUSINESS_RULES.md §9 ("the highest-risk area",
BR-GRN-01..13) plus the inward half of §4 (BR-INV-*). This is where a piece
of paper at the gate turns into real stock, so BR-GRN-06/07's "posts exactly
one GOODS_RECEIPT transaction per accepted line... atomic" is the rule this
whole module is built around: everything in `confirm_grn` either lands
together in one commit or nothing lands at all.
"""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from fastapi import Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core import audit
from app.core.deps import assert_godown_in_scope
from app.core.errors import (
    CODE_BATCH_EXPIRED,
    CODE_BATCH_REQUIRED,
    CODE_BUSINESS_RULE_VIOLATION,
    CODE_EXCESS_RECEIPT_NOT_ALLOWED,
    CODE_EXPECTED_VARIANT_REQUIRED,
    CODE_GRN_CONFIRMED,
    CODE_INVALID_PO_STATE,
    CODE_INVALID_STATE_TRANSITION,
    CODE_NOT_FOUND,
    CODE_PO_CANCELLED,
    CODE_REMARKS_REQUIRED,
    CODE_STALE_RECORD,
    CODE_VALIDATION,
    ApiError,
)
from app.core.inventory import assert_period_open, post_transaction, resolve_conversion_factor
from app.core.money import D
from app.core.numbering import allocate
from app.core.security import AccessTokenClaims
from app.core.db import commit_and_rescope, set_tenant
from app.modules.documents import variance_service
from app.modules.documents.variance_service import Finding
from app.modules.procurement import po_service
from app.modules.procurement.schemas import GrnCancelRequest, GrnCreate, GrnReverseRequest, GrnUpdate

_WRONG_TYPES = {"wrong_product", "wrong_variant", "wrong_model", "wrong_brand"}
_MANUAL_TYPES = _WRONG_TYPES | {"damaged", "expired"}
_PO_LINKABLE_STATUSES = ("approved", "sent", "acknowledged", "partially_received")


async def _load(session: AsyncSession, *, company_id: str, grn_id: UUID) -> dict:
    header = (
        await session.execute(
            text(
                "SELECT id, grn_number, grn_date, supplier_id, purchase_order_id, godown_id, received_by, "
                "vehicle_number, transporter_name, lr_number, eway_bill_number, gate_entry_number, "
                "supplier_challan_number, supplier_challan_date, status, confirmed_by, confirmed_at, "
                "cancelled_at, cancelled_by, cancellation_reason, has_discrepancy, remarks, row_version, "
                "created_at, updated_at, "
                "(SELECT u.full_name FROM users u WHERE u.id = goods_receipts.cancelled_by) AS cancelled_by_name "
                "FROM goods_receipts WHERE id = :id AND company_id = :c"
            ),
            {"id": grn_id, "c": company_id},
        )
    ).mappings().first()
    if header is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Goods receipt not found")
    items = (
        await session.execute(
            text(
                "SELECT gi.id, gi.line_no, gi.purchase_order_item_id, gi.product_variant_id, gi.batch_id, "
                "gi.ordered_quantity, gi.previously_received_quantity, gi.received_quantity, gi.accepted_quantity, "
                "gi.rejected_quantity, gi.uom_id, gi.conversion_factor, gi.unit_price, gi.issue_type, "
                "gi.expected_variant_id, gi.rejection_reason, gi.remarks, gi.inventory_transaction_id, "
                "b.batch_number, b.manufactured_on, b.expires_on, "
                "txn.quantity AS posted_quantity "
                "FROM goods_receipt_items gi "
                "LEFT JOIN batches b ON b.id = gi.batch_id AND b.company_id = gi.company_id "
                "LEFT JOIN inventory_transactions txn ON txn.id = gi.inventory_transaction_id "
                "AND txn.company_id = gi.company_id "
                "WHERE gi.goods_receipt_id = :id AND gi.company_id = :c ORDER BY gi.line_no"
            ),
            {"id": grn_id, "c": company_id},
        )
    ).mappings().all()
    out = dict(header)
    out["items"] = [dict(r) for r in items]
    out["reversal"] = await _reversal(session, grn_id=grn_id)
    return out


async def _reversal(session: AsyncSession, *, grn_id: UUID) -> Optional[dict]:
    """A reversal is not a second GRN — `reverse_grn` posts offsetting
    transactions against this same receipt (BR-GRN-08). The record of it is
    therefore its audit row, which is what the detail screen's "this receipt
    was reversed" banner reads."""
    row = (
        await session.execute(
            text(
                "SELECT a.created_at, a.actor_user_id, COALESCE(a.actor_name, u.full_name, '') AS actor_name, "
                "a.description FROM audit_logs a LEFT JOIN users u ON u.id = a.actor_user_id "
                "WHERE a.entity_type = 'goods_receipt' AND a.entity_id = :id AND a.action = 'reversed' "
                "ORDER BY a.created_at DESC LIMIT 1"
            ),
            {"id": grn_id},
        )
    ).mappings().first()
    if row is None:
        return None
    return {
        "reversed_at": row["created_at"],
        "reversed_by": row["actor_user_id"],
        "reversed_by_name": row["actor_name"],
        "reason": row["description"],
    }


async def list_grns(
    session: AsyncSession, *, company_id: str, limit: int = 100, offset: int = 0, status_filter: Optional[str] = None,
    purchase_order_id: Optional[UUID] = None,
) -> list[dict]:
    where = ["company_id = :c"]
    params: dict = {"c": company_id, "limit": limit, "offset": offset}
    if status_filter:
        where.append("status = :status")
        params["status"] = status_filter
    if purchase_order_id:
        where.append("purchase_order_id = :po")
        params["po"] = purchase_order_id
    rows = (
        await session.execute(
            text(
                "SELECT id, grn_number, grn_date, supplier_id, purchase_order_id, godown_id, received_by, "
                "vehicle_number, transporter_name, lr_number, eway_bill_number, gate_entry_number, "
                "supplier_challan_number, supplier_challan_date, status, confirmed_by, confirmed_at, "
                "cancelled_at, cancelled_by, cancellation_reason, has_discrepancy, remarks, row_version, "
                "created_at, updated_at, "
                "(SELECT u.full_name FROM users u WHERE u.id = goods_receipts.cancelled_by) AS cancelled_by_name "
                f"FROM goods_receipts WHERE {' AND '.join(where)} ORDER BY grn_date DESC, grn_number DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
    ).mappings().all()
    return [{**dict(r), "items": []} for r in rows]


async def get_grn(session: AsyncSession, *, company_id: str, grn_id: UUID) -> dict:
    return await _load(session, company_id=company_id, grn_id=grn_id)


async def _resolve_batch(session: AsyncSession, *, company_id: str, product_variant_id: UUID, item) -> Optional[UUID]:
    if not item.batch_number:
        return None
    existing = (
        await session.execute(
            text(
                "SELECT id FROM batches WHERE company_id = :c AND product_variant_id = :v AND batch_number = :n"
            ),
            {"c": company_id, "v": product_variant_id, "n": item.batch_number},
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    batch_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO batches (id, company_id, product_variant_id, batch_number, manufactured_on, expires_on, "
            "mrp, received_on) VALUES (:id, :c, :v, :n, :mfg, :exp, :mrp, CURRENT_DATE)"
        ),
        {
            "id": batch_id,
            "c": company_id,
            "v": product_variant_id,
            "n": item.batch_number,
            "mfg": item.manufactured_on,
            "exp": item.expires_on,
            "mrp": item.mrp,
        },
    )
    return batch_id


async def _grn_excess_settings(session: AsyncSession, company_id: str) -> tuple[bool, Decimal]:
    settings = (
        await session.execute(
            text("SELECT allow_grn_excess_receipt, grn_excess_tolerance_pct FROM company_settings WHERE company_id = :c"),
            {"c": company_id},
        )
    ).mappings().first() or {}
    return bool(settings.get("allow_grn_excess_receipt")), D(settings.get("grn_excess_tolerance_pct") or 0)


async def _write_items(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    grn_id: UUID,
    purchase_order_id: Optional[UUID],
    items,
    allow_excess: bool,
    tolerance_pct: Decimal,
) -> bool:
    """Validate and insert every line of a receipt. Shared by create and by
    the draft edit, so a draft saved a second time is held to exactly the
    same rules as the first — BR-GRN-01..05 and BR-GRN-11 in one place.
    Returns whether any line carries a discrepancy."""
    has_discrepancy = False
    for line_no, item in enumerate(items, start=1):
        variant = (
            await session.execute(
                text(
                    "SELECT v.uom_id AS base_uom_id, p.tracking_type FROM product_variants v "
                    "JOIN products p ON p.id = v.product_id AND p.company_id = v.company_id "
                    "WHERE v.id = :id AND v.company_id = :c"
                ),
                {"id": item.product_variant_id, "c": claims.company_id},
            )
        ).mappings().first()
        if variant is None:
            raise ApiError(status.HTTP_400_BAD_REQUEST, CODE_VALIDATION, "One of the selected products does not exist")

        po_item = None
        ordered_quantity = None
        previously_received = None
        if item.purchase_order_item_id:
            po_item = (
                await session.execute(
                    text(
                        "SELECT id, quantity, received_quantity, pending_quantity FROM purchase_order_items "
                        "WHERE id = :id AND company_id = :c AND purchase_order_id = :po"
                    ),
                    {"id": item.purchase_order_item_id, "c": claims.company_id, "po": purchase_order_id},
                )
            ).mappings().first()
            if po_item is None:
                raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Purchase order line not found on this PO")
            ordered_quantity = po_item["quantity"]
            previously_received = po_item["received_quantity"]
            pending = D(po_item["pending_quantity"])
            excess = D(item.received_quantity) - pending
            if excess > 0:
                # BR-GRN-02
                tolerance_qty = pending * tolerance_pct / Decimal(100)
                if not allow_excess or excess > tolerance_qty:
                    raise ApiError(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        CODE_EXCESS_RECEIPT_NOT_ALLOWED,
                        f"Line {line_no}: received quantity ({item.received_quantity}) exceeds the PO line's pending quantity ({pending})",
                    )

        # BR-GRN-03: auto-derive unless the caller explicitly chose a
        # manual code (damaged/expired/wrong_*), which is preserved as-is.
        #
        # Only 'excess' is derived from the quantity comparison -- a
        # receipt short of the PO line's pending quantity is completely
        # ordinary for a staged/split delivery (more due in a later GRN)
        # and is not itself a discrepancy. A genuine shortage shows up as
        # `rejected_quantity > 0` when what physically arrived is less than
        # what the line's own paperwork claimed, which BR-GRN-05 already
        # requires remarks for independently of issue_type.
        issue_type = item.issue_type
        if issue_type == "none" and ordered_quantity is not None:
            pending_for_line = D(ordered_quantity) - D(previously_received or 0)
            if D(item.received_quantity) > pending_for_line:
                issue_type = "excess"

        accepted_quantity = item.accepted_quantity
        expected_variant_id = item.expected_variant_id
        if issue_type in _WRONG_TYPES:
            # BR-GRN-04
            if not expected_variant_id:
                raise ApiError(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    CODE_EXPECTED_VARIANT_REQUIRED,
                    f"Line {line_no}: issue_type {issue_type} requires expected_variant_id",
                )
            accepted_quantity = 0

        rejected_quantity = D(item.received_quantity) - D(accepted_quantity)
        if (rejected_quantity > 0 or issue_type != "none") and not (item.remarks and item.remarks.strip()):
            # BR-GRN-05
            raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_REMARKS_REQUIRED, f"Line {line_no}: remarks are required")
        if issue_type != "none":
            has_discrepancy = True

        # BR-INV-09 / BR-GRN-11: batch-tracked variants require a batch
        # number on every movement that actually receives quantity.
        if variant["tracking_type"] == "batch" and not item.batch_number and D(item.received_quantity) > 0:
            raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_BATCH_REQUIRED, f"Line {line_no}: this item is batch-tracked; a batch number is required")
        if item.expires_on and item.expires_on <= clock.today() and issue_type != "expired":
            raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_BATCH_EXPIRED, f"Line {line_no}: expiry date must be in the future")

        batch_id = await _resolve_batch(session, company_id=claims.company_id, product_variant_id=item.product_variant_id, item=item)

        conversion_factor = await resolve_conversion_factor(
            session,
            company_id=UUID(claims.company_id),
            product_variant_id=item.product_variant_id,
            base_uom_id=variant["base_uom_id"],
            line_uom_id=item.uom_id,
        )

        await session.execute(
            text(
                "INSERT INTO goods_receipt_items "
                "(company_id, goods_receipt_id, line_no, purchase_order_item_id, product_variant_id, batch_id, "
                " ordered_quantity, previously_received_quantity, received_quantity, accepted_quantity, uom_id, "
                " conversion_factor, unit_price, issue_type, expected_variant_id, rejection_reason, remarks) "
                "VALUES (:c, :grn_id, :line_no, :po_item, :variant, :batch, :ordered, :prev_received, :received, "
                " :accepted, :uom, :factor, :price, :issue_type, :expected_variant, :rejection_reason, :remarks)"
            ),
            {
                "c": claims.company_id,
                "grn_id": grn_id,
                "line_no": line_no,
                "po_item": item.purchase_order_item_id,
                "variant": item.product_variant_id,
                "batch": batch_id,
                "ordered": ordered_quantity,
                "prev_received": previously_received,
                "received": item.received_quantity,
                "accepted": accepted_quantity,
                "uom": item.uom_id,
                "factor": conversion_factor,
                "price": item.unit_price,
                "issue_type": issue_type,
                "expected_variant": expected_variant_id,
                "rejection_reason": item.rejection_reason,
                "remarks": item.remarks,
            },
        )

    return has_discrepancy


async def create_grn(
    session: AsyncSession, *, claims: AccessTokenClaims, body: GrnCreate, request: Optional[Request] = None
) -> dict:
    supplier = (
        await session.execute(
            text("SELECT id FROM suppliers WHERE id = :id AND company_id = :c AND deleted_at IS NULL"),
            {"id": body.supplier_id, "c": claims.company_id},
        )
    ).scalar_one_or_none()
    if supplier is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Supplier not found")

    godown = (
        await session.execute(
            text("SELECT id FROM godowns WHERE id = :id AND company_id = :c AND deleted_at IS NULL"),
            {"id": body.godown_id, "c": claims.company_id},
        )
    ).scalar_one_or_none()
    if godown is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Godown not found")
    # BR-GRN-10
    assert_godown_in_scope(claims, body.godown_id, override_permission="grn.receive_other_godown")

    grn_date = body.grn_date or clock.today()
    await assert_period_open(session, company_id=UUID(claims.company_id), on=grn_date)

    po = None
    if body.purchase_order_id:
        po = (
            await session.execute(
                text(
                    "SELECT id, status, supplier_id FROM purchase_orders WHERE id = :id AND company_id = :c"
                ),
                {"id": body.purchase_order_id, "c": claims.company_id},
            )
        ).mappings().first()
        if po is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Purchase order not found")
        if po["status"] == "cancelled":
            # BR-PO-07: "a cancelled PO cannot receive goods."
            raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_PO_CANCELLED, "This PO is cancelled and cannot receive goods")
        if po["status"] not in _PO_LINKABLE_STATUSES:
            # BR-GRN-12
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                CODE_INVALID_PO_STATE,
                f"Cannot receive against a PO in status {po['status']}",
            )
        if str(po["supplier_id"]) != str(body.supplier_id):
            raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_INVALID_PO_STATE, "This PO belongs to a different supplier")

    allow_excess, tolerance_pct = await _grn_excess_settings(session, claims.company_id)

    grn_id = uuid4()
    grn_number = await allocate(session, company_id=UUID(claims.company_id), doc_type="grn", on=grn_date)
    has_discrepancy = False

    # Header first (placeholder has_discrepancy, corrected below): line
    # rows carry a NOT NULL FK to this row, so it has to exist first.
    await session.execute(
        text(
            "INSERT INTO goods_receipts "
            "(id, company_id, grn_number, grn_date, supplier_id, purchase_order_id, godown_id, received_by, "
            " vehicle_number, transporter_name, lr_number, eway_bill_number, gate_entry_number, "
            " supplier_challan_number, supplier_challan_date, remarks, has_discrepancy) "
            "VALUES (:id, :c, :number, :grn_date, :supplier, :po, :godown, :received_by, :vehicle, :transporter, "
            " :lr, :eway, :gate_entry, :challan_no, :challan_date, :remarks, false)"
        ),
        {
            "id": grn_id,
            "c": claims.company_id,
            "number": grn_number,
            "grn_date": grn_date,
            "supplier": body.supplier_id,
            "po": body.purchase_order_id,
            "godown": body.godown_id,
            "received_by": claims.user_id,
            "vehicle": body.vehicle_number,
            "transporter": body.transporter_name,
            "lr": body.lr_number,
            "eway": body.eway_bill_number,
            "gate_entry": body.gate_entry_number,
            "challan_no": body.supplier_challan_number,
            "challan_date": body.supplier_challan_date,
            "remarks": body.remarks,
        },
    )

    has_discrepancy = await _write_items(
        session,
        claims=claims,
        grn_id=grn_id,
        purchase_order_id=body.purchase_order_id,
        items=body.items,
        allow_excess=allow_excess,
        tolerance_pct=tolerance_pct,
    )

    if has_discrepancy:
        await session.execute(
            text("UPDATE goods_receipts SET has_discrepancy = true WHERE id = :id"), {"id": grn_id}
        )

    result = await _load(session, company_id=claims.company_id, grn_id=grn_id)
    await audit.record(
        session, entity_type="goods_receipt", action="created", claims=claims, entity_id=grn_id,
        entity_label=grn_number, after=result, request=request,
    )
    await session.commit()
    return result


async def confirm_grn(
    session: AsyncSession, *, claims: AccessTokenClaims, grn_id: UUID, request: Optional[Request] = None
) -> dict:
    before = await _load(session, company_id=claims.company_id, grn_id=grn_id)

    if before["status"] in ("confirmed", "partially_received", "received"):
        # BR-GRN-09: idempotent -- a retried confirm on an already-confirmed
        # GRN returns the original result rather than posting twice.
        before["postings"] = await list_postings(session, company_id=claims.company_id, grn_id=grn_id)
        before["variances"] = await variance_service.list_variances(
            session, company_id=UUID(claims.company_id), compare_doc_id=grn_id
        )
        return before
    if before["status"] == "cancelled":
        raise ApiError(status.HTTP_409_CONFLICT, CODE_INVALID_STATE_TRANSITION, "This GRN is cancelled")

    assert_godown_in_scope(claims, before["godown_id"], override_permission="grn.receive_other_godown")
    await assert_period_open(session, company_id=UUID(claims.company_id), on=before["grn_date"])

    settings = (
        await session.execute(text("SELECT allow_negative_stock FROM company_settings WHERE company_id = :c"), {"c": claims.company_id})
    ).mappings().first() or {}
    allow_negative_stock = bool(settings.get("allow_negative_stock"))

    txn_date = datetime.combine(before["grn_date"], time(hour=12))
    fully_received_overall = True

    for item in before["items"]:
        accepted = D(item["accepted_quantity"])
        if accepted > 0:
            base_qty = accepted * D(item["conversion_factor"])
            posted = await post_transaction(
                session,
                company_id=UUID(claims.company_id),
                txn_type="GOODS_RECEIPT",
                txn_number=before["grn_number"],
                txn_date=txn_date,
                product_variant_id=item["product_variant_id"],
                godown_id=before["godown_id"],
                quantity=base_qty,
                uom_id=item["uom_id"],
                batch_id=item["batch_id"],
                unit_cost=D(item["unit_price"]) if item["unit_price"] is not None else None,
                source_type="goods_receipt",
                source_id=before["id"],
                source_line_id=item["id"],
                performed_by=UUID(claims.user_id),
                allow_negative_stock=True,  # inward movement; never goes negative
            )
            await session.execute(
                text("UPDATE goods_receipt_items SET inventory_transaction_id = :txn WHERE id = :id"),
                {"txn": posted["id"], "id": item["id"]},
            )

        if item["purchase_order_item_id"]:
            row = (
                await session.execute(
                    text(
                        "UPDATE purchase_order_items SET received_quantity = received_quantity + :accepted, "
                        "line_status = CASE WHEN received_quantity + :accepted >= quantity THEN 'received' "
                        "WHEN received_quantity + :accepted > 0 THEN 'partially_received' ELSE line_status END "
                        "WHERE id = :id RETURNING quantity, received_quantity"
                    ),
                    {"accepted": accepted, "id": item["purchase_order_item_id"]},
                )
            ).mappings().first()
            if row and D(row["received_quantity"]) < D(row["quantity"]):
                fully_received_overall = False
        if accepted < D(item["received_quantity"]):
            fully_received_overall = False

    grn_status = "received" if fully_received_overall else "partially_received"
    await session.execute(
        text(
            "UPDATE goods_receipts SET status = :status, confirmed_by = :who, confirmed_at = now(), "
            "row_version = row_version + 1 WHERE id = :id"
        ),
        {"status": grn_status, "who": claims.user_id, "id": grn_id},
    )

    variances: list[dict] = []
    if before["purchase_order_id"]:
        await po_service.recompute_receipt_state(session, company_id=claims.company_id, po_id=before["purchase_order_id"])
        # Spec §3.18 step 6, in the same transaction as the postings
        # (BR-GRN-07): what arrived against what was ordered.
        variances = await variance_service.record_variances(
            session,
            company_id=UUID(claims.company_id),
            comparison_kind="grn_vs_po",
            base_doc_type="purchase_order",
            base_doc_id=before["purchase_order_id"],
            compare_doc_type="goods_receipt",
            compare_doc_id=grn_id,
            findings=_grn_findings(before["items"]),
        )

    after = await _load(session, company_id=claims.company_id, grn_id=grn_id)
    await audit.record(
        session, entity_type="goods_receipt", action="confirmed", claims=claims, entity_id=grn_id,
        entity_label=after["grn_number"], before=before, after=after, request=request,
    )
    await commit_and_rescope(session, UUID(claims.company_id))
    after["postings"] = await list_postings(session, company_id=claims.company_id, grn_id=grn_id)
    # Read the variances back in the full shape the payables screens use
    # (sku, status, resolution) rather than the slim record-time dicts.
    after["variances"] = (
        await variance_service.list_variances(session, company_id=UUID(claims.company_id), compare_doc_id=grn_id)
        if variances
        else []
    )
    return after


async def update_draft_grn(
    session: AsyncSession, *, claims: AccessTokenClaims, grn_id: UUID, body: GrnUpdate, request: Optional[Request] = None
) -> dict:
    """Edit a draft receipt: header fields and the whole set of lines.

    Only a draft — BR-GRN-08 makes a confirmed receipt immutable, corrected
    by a reversal instead. `row_version` is the optimistic-lock token (the
    same contract `PATCH /purchase-orders/{id}` uses): two people editing
    the same draft, the second one is told rather than silently winning.

    The supplier and the linked PO are fixed at creation. Changing either
    would change what the lines mean (their `purchase_order_item_id`s belong
    to that PO), so a different order or supplier is a different receipt.
    """
    before = await _load(session, company_id=claims.company_id, grn_id=grn_id)
    if before["status"] != "draft":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_GRN_CONFIRMED,
            f"Only a draft receipt can be edited (current status: {before['status']}). Reverse it instead.",
        )
    if body.row_version != before["row_version"]:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_STALE_RECORD,
            "This receipt was changed by someone else. Reload and try again.",
        )

    assert_godown_in_scope(claims, before["godown_id"], override_permission="grn.receive_other_godown")
    godown_id = body.godown_id or before["godown_id"]
    if body.godown_id and str(body.godown_id) != str(before["godown_id"]):
        exists = (
            await session.execute(
                text("SELECT id FROM godowns WHERE id = :id AND company_id = :c AND deleted_at IS NULL"),
                {"id": body.godown_id, "c": claims.company_id},
            )
        ).scalar_one_or_none()
        if exists is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Godown not found")
        assert_godown_in_scope(claims, body.godown_id, override_permission="grn.receive_other_godown")

    grn_date = body.grn_date or before["grn_date"]
    await assert_period_open(session, company_id=UUID(claims.company_id), on=grn_date)

    # A draft holds no stock and no ledger rows, so its lines can simply be
    # replaced. `previously_received_quantity` and the excess ceiling are
    # re-read from the PO inside `_write_items`, which is the point: the PO
    # may have moved on since the draft was first saved.
    await session.execute(
        text("DELETE FROM goods_receipt_items WHERE goods_receipt_id = :id AND company_id = :c"),
        {"id": grn_id, "c": claims.company_id},
    )
    allow_excess, tolerance_pct = await _grn_excess_settings(session, claims.company_id)
    has_discrepancy = await _write_items(
        session,
        claims=claims,
        grn_id=grn_id,
        purchase_order_id=before["purchase_order_id"],
        items=body.items,
        allow_excess=allow_excess,
        tolerance_pct=tolerance_pct,
    )

    fields = {
        "grn_date": grn_date,
        "godown_id": godown_id,
        "vehicle_number": body.vehicle_number,
        "transporter_name": body.transporter_name,
        "lr_number": body.lr_number,
        "eway_bill_number": body.eway_bill_number,
        "gate_entry_number": body.gate_entry_number,
        "supplier_challan_number": body.supplier_challan_number,
        "supplier_challan_date": body.supplier_challan_date,
        "remarks": body.remarks,
    }
    assignments = ", ".join(f"{k} = :{k}" for k in fields)
    await session.execute(
        text(
            f"UPDATE goods_receipts SET {assignments}, has_discrepancy = :disc, "
            "row_version = row_version + 1 WHERE id = :id AND company_id = :c AND status = 'draft'"
        ),
        {**fields, "disc": has_discrepancy, "id": grn_id, "c": claims.company_id},
    )

    after = await _load(session, company_id=claims.company_id, grn_id=grn_id)
    await audit.record(
        session, entity_type="goods_receipt", action="updated", claims=claims, entity_id=grn_id,
        entity_label=after["grn_number"], before=before, after=after, request=request,
    )
    await session.commit()
    return after


async def list_postings(session: AsyncSession, *, company_id: str, grn_id: UUID) -> list[dict]:
    """Every ledger row this receipt produced — the confirmation postings
    and, if it was reversed, the offsetting ones. The detail screen's
    "posted" column and the confirmation panel both read this."""
    await _load(session, company_id=company_id, grn_id=grn_id)
    rows = (
        await session.execute(
            text(
                "SELECT it.id AS inventory_transaction_id, it.source_line_id AS goods_receipt_item_id, "
                "it.txn_number, it.txn_type, it.txn_date, it.posted_at, it.product_variant_id, "
                "COALESCE(pv.sku, '') AS sku, it.godown_id, COALESCE(g.name, '') AS godown_name, "
                "it.quantity, it.uom_id, it.reverses_txn_id, "
                "(SELECT sb.quantity FROM stock_balances sb WHERE sb.company_id = it.company_id "
                " AND sb.product_variant_id = it.product_variant_id AND sb.godown_id = it.godown_id "
                " AND (sb.batch_id = it.batch_id OR (sb.batch_id IS NULL AND it.batch_id IS NULL))) AS balance_now "
                "FROM inventory_transactions it "
                "LEFT JOIN product_variants pv ON pv.id = it.product_variant_id AND pv.company_id = it.company_id "
                "LEFT JOIN godowns g ON g.id = it.godown_id AND g.company_id = it.company_id "
                "WHERE it.company_id = :c AND it.source_type = 'goods_receipt' AND it.source_id = :id "
                "ORDER BY it.posted_at, it.txn_number"
            ),
            {"c": company_id, "id": grn_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def refresh_grn_alerts(session: AsyncSession, *, claims: AccessTokenClaims, grn_id: UUID) -> list[UUID]:
    """Re-run the two GRN alert rules and return the alerts now open against
    this receipt. Spec §3.18 step 9 puts alert generation after the commit
    precisely so a failure here can never roll back a posted receipt — so
    this swallows its own errors and reports no alerts instead.
    """
    from app.modules.ops import alert_service

    company_id = UUID(claims.company_id)
    try:
        for rule in ("GRN_QTY_MISMATCH", "GRN_WRONG_PRODUCT"):
            # `evaluate` commits its own work, and a commit ends the
            # transaction-scoped tenant setting — so the scope is re-asserted
            # before every rule, not just once (recurring trap #1).
            await set_tenant(session, company_id)
            await alert_service.evaluate(session, company_id=company_id, only_rule=rule)
        await commit_and_rescope(session, company_id)
        rows = (
            await session.execute(
                text(
                    "SELECT id FROM alerts WHERE company_id = :c AND reference_type = 'goods_receipt' "
                    "AND reference_id = :id AND status IN ('new', 'acknowledged')"
                ),
                {"c": claims.company_id, "id": grn_id},
            )
        ).scalars().all()
        return list(rows)
    except Exception:  # noqa: BLE001 - alerts are never worth failing a receipt for
        await session.rollback()
        await set_tenant(session, company_id)
        return []


async def list_variances(session: AsyncSession, *, company_id: str, grn_id: UUID) -> list[dict]:
    await _load(session, company_id=company_id, grn_id=grn_id)
    return await variance_service.list_variances(
        session, company_id=UUID(company_id), compare_doc_id=grn_id
    )


def _grn_findings(items: list[dict]) -> list[Finding]:
    """One variance per line that did not go to plan (spec §3.18 step 6),
    picking the most significant fact rather than stacking three rows on one
    line: the wrong item beats a short delivery, which beats a rejection."""
    findings: list[Finding] = []
    for item in items:
        received = D(item["received_quantity"])
        accepted = D(item["accepted_quantity"])
        expected = None
        if item["ordered_quantity"] is not None:
            expected = D(item["ordered_quantity"]) - D(item["previously_received_quantity"] or 0)

        common = {
            "base_line_id": item["purchase_order_item_id"],
            "compare_line_id": item["id"],
            "product_variant_id": item["product_variant_id"],
        }
        if item["issue_type"] in _WRONG_TYPES:
            findings.append(Finding(variance_type="product", base_value=received, compare_value=accepted, **common))
        elif expected is not None and received != expected:
            findings.append(Finding(variance_type="quantity", base_value=expected, compare_value=received, **common))
        elif accepted < received:
            findings.append(Finding(variance_type="quantity", base_value=received, compare_value=accepted, **common))
    return findings


async def cancel_grn(
    session: AsyncSession, *, claims: AccessTokenClaims, grn_id: UUID,
    body: Optional[GrnCancelRequest] = None, request: Optional[Request] = None,
) -> dict:
    before = await _load(session, company_id=claims.company_id, grn_id=grn_id)
    if before["status"] != "draft":
        # State diagram: "cancelled (draft only)"
        raise ApiError(status.HTTP_409_CONFLICT, CODE_INVALID_STATE_TRANSITION, f"Only draft GRNs can be cancelled (current status: {before['status']})")
    await session.execute(
        text(
            "UPDATE goods_receipts SET status = 'cancelled', cancelled_at = now(), cancelled_by = :who, "
            "cancellation_reason = :reason, row_version = row_version + 1 WHERE id = :id"
        ),
        {"id": grn_id, "who": claims.user_id, "reason": ((body.reason or "").strip() or None) if body else None},
    )
    after = await _load(session, company_id=claims.company_id, grn_id=grn_id)
    await audit.record(
        session, entity_type="goods_receipt", action="cancelled", claims=claims, entity_id=grn_id,
        entity_label=after["grn_number"], before=before, after=after, request=request,
    )
    await session.commit()
    return after


async def reverse_grn(
    session: AsyncSession, *, claims: AccessTokenClaims, grn_id: UUID, body: GrnReverseRequest, request: Optional[Request] = None
) -> dict:
    """BR-GRN-08: a confirmed GRN is never edited or deleted -- a correction
    posts new, offsetting `inventory_transactions` rows (`STOCK_CORRECTION`,
    since `GOODS_RECEIPT` is constrained to positive quantities) rather than
    touching history. One reversal per GRN: a second attempt is refused
    rather than risking a double-reversal with no per-line "already
    reversed" ledger to check against.
    """
    before = await _load(session, company_id=claims.company_id, grn_id=grn_id)
    if before["status"] not in ("confirmed", "partially_received", "received"):
        raise ApiError(status.HTTP_409_CONFLICT, CODE_INVALID_STATE_TRANSITION, f"Only a confirmed GRN can be reversed (current status: {before['status']})")

    already_reversed = (
        await session.execute(
            text("SELECT 1 FROM audit_logs WHERE entity_type = 'goods_receipt' AND entity_id = :id AND action = 'reversed' LIMIT 1"),
            {"id": grn_id},
        )
    ).scalar_one_or_none()
    if already_reversed:
        raise ApiError(status.HTTP_409_CONFLICT, "GRN_ALREADY_REVERSED", "This GRN has already been reversed")

    assert_godown_in_scope(claims, before["godown_id"], override_permission="grn.receive_other_godown")

    settings = (
        await session.execute(text("SELECT allow_negative_stock FROM company_settings WHERE company_id = :c"), {"c": claims.company_id})
    ).mappings().first() or {}
    allow_negative_stock = bool(settings.get("allow_negative_stock"))

    requested = {line.goods_receipt_item_id: D(line.quantity) for line in (body.lines or [])}
    items_by_id = {item["id"]: item for item in before["items"]}
    targets = requested or {item["id"]: D(item["accepted_quantity"]) for item in before["items"] if D(item["accepted_quantity"]) > 0}

    for item_id, qty in targets.items():
        item = items_by_id.get(item_id)
        if item is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "GRN line not found on this receipt")
        accepted = D(item["accepted_quantity"])
        if qty > accepted:
            raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_BUSINESS_RULE_VIOLATION, f"Cannot reverse more than was accepted on line {item['line_no']}")
        if qty <= 0:
            continue

        base_qty = qty * D(item["conversion_factor"])
        await post_transaction(
            session,
            company_id=UUID(claims.company_id),
            txn_type="STOCK_CORRECTION",
            txn_number=f"{before['grn_number']}-REV",
            txn_date=datetime.now(),
            product_variant_id=item["product_variant_id"],
            godown_id=before["godown_id"],
            quantity=-base_qty,
            uom_id=item["uom_id"],
            batch_id=item["batch_id"],
            reason_code="GRN_REVERSAL",
            remarks=body.reason,
            source_type="goods_receipt",
            source_id=before["id"],
            source_line_id=item["id"],
            reverses_txn_id=item["inventory_transaction_id"],
            performed_by=UUID(claims.user_id),
            allow_negative_stock=allow_negative_stock,
        )

        if item["purchase_order_item_id"]:
            await session.execute(
                text(
                    "UPDATE purchase_order_items SET received_quantity = GREATEST(received_quantity - :qty, 0), "
                    "line_status = CASE WHEN GREATEST(received_quantity - :qty, 0) <= 0 THEN 'open' "
                    "WHEN GREATEST(received_quantity - :qty, 0) < quantity THEN 'partially_received' ELSE line_status END "
                    "WHERE id = :id"
                ),
                {"qty": qty, "id": item["purchase_order_item_id"]},
            )

    if before["purchase_order_id"]:
        await po_service.recompute_receipt_state(session, company_id=claims.company_id, po_id=before["purchase_order_id"])

    after = await _load(session, company_id=claims.company_id, grn_id=grn_id)
    await audit.record(
        session, entity_type="goods_receipt", action="reversed", claims=claims, entity_id=grn_id,
        entity_label=after["grn_number"], description=body.reason, before=before, after=after, request=request,
    )
    await session.commit()
    return after
