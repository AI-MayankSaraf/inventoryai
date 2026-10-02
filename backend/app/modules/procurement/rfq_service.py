"""
RFQ service — 06_BUSINESS_RULES.md §5 (BR-RFQ-01..07) and the RFQ arm of
§14's state machine: `draft -> sent -> ... -> closed`, `-> cancelled` from
either draft or sent.

Quotations, comparison and the rest of the RFQ's downstream chain
(`supplier_quotations`, `quotation_comparisons`) are out of scope for this
pass — a PO can be created directly from RFQ items (BR-PO-08) without a
quotation step in between, so RFQ here only ever reaches `sent` or
`cancelled`; `partially_quoted`/`quoted`/`closed` are reachable once
quotation intake exists and are left unimplemented on purpose rather than
half-built.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID, uuid4

from fastapi import Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core import audit
from app.core.deps import assert_godown_in_scope
from app.core.errors import (
    CODE_INVALID_STATE_TRANSITION,
    CODE_NO_ITEMS,
    CODE_NOT_FOUND,
    CODE_SUPPLIER_EMAIL_MISSING,
    CODE_VALIDATION,
    ApiError,
)
from app.core.numbering import allocate
from app.core.security import AccessTokenClaims
from app.modules.procurement import rfq_import
from app.modules.procurement.schemas import RfqCancelRequest, RfqCreate, RfqSendRequest, RfqUpdate


_RFQ_HEADER_COLUMNS = (
    "id, rfq_number, rfq_date, expected_delivery_date, subject, delivery_godown_id, "
    "notes, status, sent_at, closed_at, estimated_value, created_from, row_version, "
    "external_source_name, external_reference_number, source_file_name, created_at, updated_at"
)


async def _load(session: AsyncSession, *, company_id: str, rfq_id: UUID) -> dict:
    header = (
        await session.execute(
            text(f"SELECT {_RFQ_HEADER_COLUMNS} FROM rfqs WHERE id = :id AND company_id = :c"),
            {"id": rfq_id, "c": company_id},
        )
    ).mappings().first()
    if header is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "RFQ not found")

    items = (
        await session.execute(
            text(
                "SELECT id, line_no, product_variant_id, description, quantity, uom_id, expected_price, "
                "target_delivery_date, remarks FROM rfq_items WHERE rfq_id = :id AND company_id = :c "
                "ORDER BY line_no"
            ),
            {"id": rfq_id, "c": company_id},
        )
    ).mappings().all()

    suppliers = (
        await session.execute(
            text(
                "SELECT id, supplier_id, status, sent_at, responded_at FROM rfq_suppliers "
                "WHERE rfq_id = :id AND company_id = :c ORDER BY sent_at NULLS LAST"
            ),
            {"id": rfq_id, "c": company_id},
        )
    ).mappings().all()

    out = dict(header)
    out["items"] = [dict(r) for r in items]
    out["suppliers"] = [dict(r) for r in suppliers]
    return out


async def list_rfqs(
    session: AsyncSession, *, company_id: str, limit: int = 100, offset: int = 0, status_filter: Optional[str] = None
) -> list[dict]:
    where = "company_id = :c"
    params: dict = {"c": company_id, "limit": limit, "offset": offset}
    if status_filter:
        where += " AND status = :status"
        params["status"] = status_filter
    rows = (
        await session.execute(
            text(
                f"SELECT {_RFQ_HEADER_COLUMNS} "
                f"FROM rfqs WHERE {where} ORDER BY rfq_date DESC, rfq_number DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
    ).mappings().all()
    if not rows:
        return []

    # The list screens count suppliers, quotes in and items per RFQ, and the
    # Quotation Comparison chooser shows only RFQs with a quote — so these
    # cannot be left empty. Two queries for the whole page, not one per RFQ.
    ids = [r["id"] for r in rows]
    by_rfq: dict = {rid: {"items": [], "suppliers": []} for rid in ids}
    for kind, sql in (
        (
            "items",
            "SELECT rfq_id, id, line_no, product_variant_id, description, quantity, uom_id, expected_price, "
            "target_delivery_date, remarks FROM rfq_items WHERE company_id = :c AND rfq_id = ANY(CAST(:ids AS uuid[])) "
            "ORDER BY line_no",
        ),
        (
            "suppliers",
            "SELECT rfq_id, id, supplier_id, status, sent_at, responded_at FROM rfq_suppliers "
            "WHERE company_id = :c AND rfq_id = ANY(CAST(:ids AS uuid[])) ORDER BY sent_at NULLS LAST",
        ),
    ):
        for child in (await session.execute(text(sql), {"c": company_id, "ids": ids})).mappings().all():
            entry = dict(child)
            by_rfq[entry.pop("rfq_id")][kind].append(entry)
    return [{**dict(r), **by_rfq[r["id"]]} for r in rows]


async def get_rfq(session: AsyncSession, *, company_id: str, rfq_id: UUID) -> dict:
    return await _load(session, company_id=company_id, rfq_id=rfq_id)


async def _active_suppliers(
    session: AsyncSession, company_id: str, supplier_ids: list[UUID], *, require_email: bool
) -> list[dict]:
    """The suppliers, each active and in this company — or a 404/422 naming
    the ones that are not. An email is required only to actually send
    (BR-RFQ-03); a draft may list a supplier whose address is added later."""
    suppliers = (
        await session.execute(
            text(
                "SELECT id, name, email FROM suppliers WHERE company_id = :c AND id = ANY(CAST(:ids AS uuid[])) "
                "AND status = 'active' AND deleted_at IS NULL"
            ),
            {"c": company_id, "ids": list(supplier_ids)},
        )
    ).mappings().all()
    missing = set(supplier_ids) - {r["id"] for r in suppliers}
    if missing:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, f"Supplier(s) not found or inactive: {missing}")
    if require_email:
        missing_email = [r["name"] for r in suppliers if not r["email"]]
        if missing_email:
            # BR-RFQ-03
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                CODE_SUPPLIER_EMAIL_MISSING,
                f"These suppliers have no email address: {', '.join(missing_email)}",
            )
    return [dict(r) for r in suppliers]


async def _insert_items(session: AsyncSession, *, company_id: str, rfq_id: UUID, items: list) -> float:
    estimated_value = 0.0
    for line_no, item in enumerate(items, start=1):
        description = item.description
        if not description and item.product_variant_id:
            # `rfq_items.description` is NOT NULL in the schema (it's a
            # printable line label, not just the BR-RFQ-02 free-text-
            # sourcing field) -- BR-RFQ-02 only requires the *caller* supply
            # one of product_variant_id/description, so a variant-only line
            # gets its label filled in from the catalogue instead.
            variant = (
                await session.execute(
                    text(
                        "SELECT v.sku, v.variant_name, p.name AS product_name FROM product_variants v "
                        "JOIN products p ON p.id = v.product_id AND p.company_id = v.company_id "
                        "WHERE v.id = :id AND v.company_id = :c"
                    ),
                    {"id": item.product_variant_id, "c": company_id},
                )
            ).mappings().first()
            if variant is None:
                raise ApiError(status.HTTP_400_BAD_REQUEST, CODE_VALIDATION, "One of the selected products does not exist")
            description = f"{variant['product_name']} ({variant['sku']})" if not variant["variant_name"] else f"{variant['product_name']} - {variant['variant_name']} ({variant['sku']})"

        await session.execute(
            text(
                "INSERT INTO rfq_items (company_id, rfq_id, line_no, product_variant_id, description, "
                "quantity, uom_id, expected_price, target_delivery_date, remarks) "
                "VALUES (:c, :rfq_id, :line_no, :variant, :description, :quantity, :uom, :price, :target_date, :remarks)"
            ),
            {
                "c": company_id,
                "rfq_id": rfq_id,
                "line_no": line_no,
                "variant": item.product_variant_id,
                "description": description,
                "quantity": item.quantity,
                "uom": item.uom_id,
                "price": item.expected_price,
                "target_date": item.target_delivery_date,
                "remarks": item.remarks,
            },
        )
        estimated_value += item.quantity * item.expected_price
    return estimated_value


async def create_rfq(
    session: AsyncSession, *, claims: AccessTokenClaims, body: RfqCreate, request: Optional[Request] = None
) -> dict:
    # BR-AUTH-12, same gap as the PO path: a scoped user may not raise a
    # request for goods to be delivered to a godown outside their scope.
    if body.delivery_godown_id:
        assert_godown_in_scope(claims, body.delivery_godown_id)

    rfq_id = uuid4()
    rfq_date = body.rfq_date or clock.today()
    rfq_number = await allocate(session, company_id=UUID(claims.company_id), doc_type="rfq", on=rfq_date)

    await session.execute(
        text(
            "INSERT INTO rfqs (id, company_id, rfq_number, rfq_date, expected_delivery_date, subject, "
            "delivery_godown_id, notes, created_from) "
            "VALUES (:id, :c, :number, :rfq_date, :expected, :subject, :godown, :notes, 'manual')"
        ),
        {
            "id": rfq_id,
            "c": claims.company_id,
            "number": rfq_number,
            "rfq_date": rfq_date,
            "expected": body.expected_delivery_date,
            "subject": body.subject,
            "godown": body.delivery_godown_id,
            "notes": body.notes,
        },
    )
    estimated_value = await _insert_items(session, company_id=claims.company_id, rfq_id=rfq_id, items=body.items)
    if estimated_value:
        await session.execute(
            text("UPDATE rfqs SET estimated_value = :v WHERE id = :id"), {"v": estimated_value, "id": rfq_id}
        )
    if body.supplier_ids:
        supplier_ids = list(dict.fromkeys(body.supplier_ids))
        await _active_suppliers(session, claims.company_id, supplier_ids, require_email=False)
        for supplier_id in supplier_ids:
            await session.execute(
                text(
                    "INSERT INTO rfq_suppliers (company_id, rfq_id, supplier_id, status) "
                    "VALUES (:c, :rfq_id, :supplier_id, 'pending')"
                ),
                {"c": claims.company_id, "rfq_id": rfq_id, "supplier_id": supplier_id},
            )

    result = await _load(session, company_id=claims.company_id, rfq_id=rfq_id)
    await audit.record(
        session,
        entity_type="rfq",
        action="created",
        claims=claims,
        entity_id=rfq_id,
        entity_label=rfq_number,
        after=result,
        request=request,
    )
    await session.commit()
    return result


async def update_rfq(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    rfq_id: UUID,
    body: RfqUpdate,
    request: Optional[Request] = None,
) -> dict:
    before = await _load(session, company_id=claims.company_id, rfq_id=rfq_id)
    if before["status"] != "draft":
        # BR-RFQ-04
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_INVALID_STATE_TRANSITION,
            f"Only draft RFQs are editable (current status: {before['status']})",
        )

    if body.delivery_godown_id is not None:
        assert_godown_in_scope(claims, body.delivery_godown_id)

    fields = body.model_dump(exclude_unset=True, exclude={"items"})
    if fields:
        assignments = ", ".join(f"{k} = :{k}" for k in fields)
        await session.execute(
            text(f"UPDATE rfqs SET {assignments} WHERE id = :id AND company_id = :c"),
            {**fields, "id": rfq_id, "c": claims.company_id},
        )

    if body.items is not None:
        await session.execute(
            text("DELETE FROM rfq_items WHERE rfq_id = :id AND company_id = :c"),
            {"id": rfq_id, "c": claims.company_id},
        )
        estimated_value = await _insert_items(session, company_id=claims.company_id, rfq_id=rfq_id, items=body.items)
        await session.execute(
            text("UPDATE rfqs SET estimated_value = :v WHERE id = :id"), {"v": estimated_value, "id": rfq_id}
        )

    # BR-RFQ-05, checked again post-update since either date may have changed independently.
    check = (
        await session.execute(
            text("SELECT rfq_date, expected_delivery_date FROM rfqs WHERE id = :id"), {"id": rfq_id}
        )
    ).mappings().first()
    if check["expected_delivery_date"] and check["expected_delivery_date"] < check["rfq_date"]:
        raise ApiError(status.HTTP_400_BAD_REQUEST, CODE_VALIDATION, "expected_delivery_date must be on or after rfq_date")

    after = await _load(session, company_id=claims.company_id, rfq_id=rfq_id)
    await audit.record(
        session,
        entity_type="rfq",
        action="updated",
        claims=claims,
        entity_id=rfq_id,
        entity_label=after["rfq_number"],
        before=before,
        after=after,
        request=request,
    )
    await session.commit()
    return after


async def send_rfq(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    rfq_id: UUID,
    body: RfqSendRequest,
    request: Optional[Request] = None,
) -> dict:
    before = await _load(session, company_id=claims.company_id, rfq_id=rfq_id)
    if before["status"] != "draft":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_INVALID_STATE_TRANSITION,
            f"Only draft RFQs can be sent (current status: {before['status']})",
        )
    if not before["items"]:
        # BR-RFQ-01
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_NO_ITEMS, "An RFQ needs at least one item before it can be sent")

    # No list in the request means "the suppliers chosen on this draft".
    supplier_ids = list(body.supplier_ids) or [s["supplier_id"] for s in before["suppliers"]]
    if not supplier_ids:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_VALIDATION,
            "Add at least one supplier before sending this RFQ",
        )
    await _active_suppliers(session, claims.company_id, supplier_ids, require_email=True)
    # Suppliers picked on the draft but left out of an explicit send list
    # were not sent to; they must not linger as "pending" on a sent RFQ.
    await session.execute(
        text(
            "DELETE FROM rfq_suppliers WHERE company_id = :c AND rfq_id = :rfq_id AND status = 'pending' "
            "AND NOT (supplier_id = ANY(CAST(:ids AS uuid[])))"
        ),
        {"c": claims.company_id, "rfq_id": rfq_id, "ids": supplier_ids},
    )

    for supplier_id in supplier_ids:
        await session.execute(
            text(
                "INSERT INTO rfq_suppliers (company_id, rfq_id, supplier_id, status, sent_at, sent_channel) "
                "VALUES (:c, :rfq_id, :supplier_id, 'sent', now(), 'email') "
                "ON CONFLICT ON CONSTRAINT uq_rfq_supplier DO UPDATE SET status = 'sent', sent_at = now()"
            ),
            {"c": claims.company_id, "rfq_id": rfq_id, "supplier_id": supplier_id},
        )

    await session.execute(
        text("UPDATE rfqs SET status = 'sent', sent_at = now(), row_version = row_version + 1 WHERE id = :id"),
        {"id": rfq_id},
    )

    after = await _load(session, company_id=claims.company_id, rfq_id=rfq_id)
    await audit.record(
        session,
        entity_type="rfq",
        action="sent",
        claims=claims,
        entity_id=rfq_id,
        entity_label=after["rfq_number"],
        description=f"Sent to {len(supplier_ids)} supplier(s)",
        before=before,
        after=after,
        request=request,
    )
    await session.commit()
    return after


async def add_suppliers(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    rfq_id: UUID,
    supplier_ids: list[UUID],
    request: Optional[Request] = None,
) -> dict:
    """Add suppliers to an RFQ. On a draft they wait as `pending` for the
    send; on a sent RFQ they are sent to now — only them, so suppliers who
    already have the RFQ are not sent it twice."""
    before = await _load(session, company_id=claims.company_id, rfq_id=rfq_id)
    if before["status"] not in ("draft", "sent"):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_INVALID_STATE_TRANSITION,
            f"Suppliers can only be added to a draft or sent RFQ (current status: {before['status']})",
        )
    sending = before["status"] == "sent"
    if sending and "rfq.send" not in claims.permissions:
        raise ApiError(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "Missing permission: rfq.send")

    already = {s["supplier_id"] for s in before["suppliers"]}
    new_ids = [s for s in dict.fromkeys(supplier_ids) if s not in already]
    if not new_ids:
        raise ApiError(status.HTTP_409_CONFLICT, CODE_VALIDATION, "These suppliers are already on this RFQ")
    added = await _active_suppliers(session, claims.company_id, new_ids, require_email=sending)

    for supplier_id in new_ids:
        await session.execute(
            text(
                "INSERT INTO rfq_suppliers (company_id, rfq_id, supplier_id, status, sent_at, sent_channel) "
                "VALUES (:c, :rfq_id, :supplier_id, :status, CASE WHEN :sending THEN now() END, :channel)"
            ),
            {
                "c": claims.company_id,
                "rfq_id": rfq_id,
                "supplier_id": supplier_id,
                "status": "sent" if sending else "pending",
                "sending": sending,
                "channel": "email" if sending else None,
            },
        )

    after = await _load(session, company_id=claims.company_id, rfq_id=rfq_id)
    names = ", ".join(s["name"] for s in added)
    await audit.record(
        session,
        entity_type="rfq",
        action="sent" if sending else "updated",
        claims=claims,
        entity_id=rfq_id,
        entity_label=after["rfq_number"],
        description=f"{'Sent to' if sending else 'Supplier(s) added'}: {names}",
        before=before,
        after=after,
        request=request,
    )
    await session.commit()
    return after


async def remove_supplier(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    rfq_id: UUID,
    supplier_id: UUID,
    request: Optional[Request] = None,
) -> dict:
    """Take a supplier off a draft. Once sent, the supplier has the RFQ —
    removing the row would only hide that, so it is refused."""
    before = await _load(session, company_id=claims.company_id, rfq_id=rfq_id)
    if before["status"] != "draft":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_INVALID_STATE_TRANSITION,
            "Suppliers can only be removed while the RFQ is a draft",
        )
    deleted = (
        await session.execute(
            text(
                "DELETE FROM rfq_suppliers WHERE company_id = :c AND rfq_id = :rfq_id AND supplier_id = :s "
                "RETURNING id"
            ),
            {"c": claims.company_id, "rfq_id": rfq_id, "s": supplier_id},
        )
    ).first()
    if deleted is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "That supplier is not on this RFQ")

    after = await _load(session, company_id=claims.company_id, rfq_id=rfq_id)
    await audit.record(
        session,
        entity_type="rfq",
        action="updated",
        claims=claims,
        entity_id=rfq_id,
        entity_label=after["rfq_number"],
        description="Supplier removed",
        before=before,
        after=after,
        request=request,
    )
    await session.commit()
    return after


async def cancel_rfq(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    rfq_id: UUID,
    body: RfqCancelRequest,
    request: Optional[Request] = None,
) -> dict:
    before = await _load(session, company_id=claims.company_id, rfq_id=rfq_id)
    if before["status"] not in ("draft", "sent"):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_INVALID_STATE_TRANSITION,
            f"Cannot cancel an RFQ in status {before['status']}",
        )
    await session.execute(
        text("UPDATE rfqs SET status = 'cancelled', row_version = row_version + 1 WHERE id = :id"), {"id": rfq_id}
    )
    after = await _load(session, company_id=claims.company_id, rfq_id=rfq_id)
    await audit.record(
        session,
        entity_type="rfq",
        action="cancelled",
        claims=claims,
        entity_id=rfq_id,
        entity_label=after["rfq_number"],
        description=body.reason,
        before=before,
        after=after,
        request=request,
    )
    await session.commit()
    return after


async def delete_rfq(
    session: AsyncSession, *, claims: AccessTokenClaims, rfq_id: UUID, request: Optional[Request] = None
) -> None:
    before = await _load(session, company_id=claims.company_id, rfq_id=rfq_id)
    if before["status"] != "draft":
        # BR-RFQ-04: "sent RFQs are cancelled instead" -- delete is draft-only.
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_INVALID_STATE_TRANSITION,
            f"Only draft RFQs can be deleted (current status: {before['status']}); cancel it instead",
        )
    await session.execute(text("DELETE FROM rfqs WHERE id = :id AND company_id = :c"), {"id": rfq_id, "c": claims.company_id})
    await audit.record(
        session,
        entity_type="rfq",
        action="deleted",
        claims=claims,
        entity_id=rfq_id,
        entity_label=before["rfq_number"],
        before=before,
        request=request,
    )
    await session.commit()


# ================================================================= Import
#
# BR-RFQ-09 / `rfq.import`. Reading the file — header detection, column
# mapping, Indian unit spellings, saved layouts — lives in `rfq_import.py`;
# this section only turns the parsed lines into an RFQ. Every imported line
# is free-text sourced (BR-RFQ-02) rather than matched to a catalogue SKU at
# import time — the RFQ is a normal draft afterwards, so a person can link
# items to SKUs by editing it before sending, the same as any manually-
# created RFQ.


async def preview_import(
    session: AsyncSession,
    *,
    company_id: str,
    filename: str,
    content: bytes,
    column_map: Optional[dict[str, int]] = None,
    header_row: Optional[int] = None,
    sheet_index: Optional[int] = None,
    default_uom_id: Optional[UUID] = None,
) -> dict:
    result = await rfq_import.parse(
        session,
        company_id=company_id,
        filename=filename,
        content=content,
        column_map=column_map,
        header_row=header_row,
        sheet_index=sheet_index,
        default_uom_id=default_uom_id,
    )
    return result.as_dict()


async def import_rfq(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    filename: str,
    content: bytes,
    external_source_name: str,
    external_reference_number: Optional[str] = None,
    subject: Optional[str] = None,
    delivery_godown_id: Optional[UUID] = None,
    column_map: Optional[dict[str, int]] = None,
    header_row: Optional[int] = None,
    sheet_index: Optional[int] = None,
    default_uom_id: Optional[UUID] = None,
    request: Optional[Request] = None,
) -> dict:
    if delivery_godown_id:
        assert_godown_in_scope(claims, delivery_godown_id)

    parsed = await rfq_import.parse(
        session,
        company_id=claims.company_id,
        filename=filename,
        content=content,
        column_map=column_map,
        header_row=header_row,
        sheet_index=sheet_index,
        default_uom_id=default_uom_id,
    )
    rows, errors = parsed.rows, parsed.errors
    if errors:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_VALIDATION,
            "Fix these before importing: " + "; ".join(errors[:10]),
        )
    if not rows:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_NO_ITEMS, "No items found in the file")

    rfq_id = uuid4()
    rfq_date = clock.today()
    rfq_number = await allocate(session, company_id=UUID(claims.company_id), doc_type="rfq", on=rfq_date)
    source_name = external_source_name.strip()

    await session.execute(
        text(
            "INSERT INTO rfqs (id, company_id, rfq_number, rfq_date, subject, delivery_godown_id, "
            "created_from, external_source_name, external_reference_number, source_file_name) "
            "VALUES (:id, :c, :number, :rfq_date, :subject, :godown, 'imported', :src, :ref, :file)"
        ),
        {
            "id": rfq_id,
            "c": claims.company_id,
            "number": rfq_number,
            "rfq_date": rfq_date,
            "subject": (subject or "").strip() or f"Imported from {source_name}",
            "godown": delivery_godown_id,
            "src": source_name,
            "ref": (external_reference_number or "").strip() or None,
            "file": filename,
        },
    )

    estimated_value = 0.0
    for line_no, row in enumerate(rows, start=1):
        await session.execute(
            text(
                "INSERT INTO rfq_items (company_id, rfq_id, line_no, description, quantity, uom_id, "
                "expected_price, remarks) "
                "VALUES (:c, :rfq_id, :line_no, :description, :quantity, :uom, :price, :remarks)"
            ),
            {
                "c": claims.company_id,
                "rfq_id": rfq_id,
                "line_no": line_no,
                "description": row["description"],
                "quantity": row["quantity"],
                "uom": row["uom_id"],
                "price": row["expected_price"],
                "remarks": row["remarks"],
            },
        )
        estimated_value += row["quantity"] * row["expected_price"]

    await session.execute(
        text("UPDATE rfqs SET estimated_value = :v WHERE id = :id"), {"v": estimated_value, "id": rfq_id}
    )

    result = await _load(session, company_id=claims.company_id, rfq_id=rfq_id)
    await audit.record(
        session,
        entity_type="rfq",
        action="created",
        claims=claims,
        entity_id=rfq_id,
        entity_label=rfq_number,
        after=result,
        description=f"Imported {len(rows)} item(s) from {source_name}",
        request=request,
    )
    # The person saw this mapping in the preview and confirmed it, so the
    # next file with the same header row maps itself.
    await rfq_import.save_layout(
        session, company_id=claims.company_id, user_id=claims.user_id, result=parsed, filename=filename
    )
    await session.commit()
    return result
