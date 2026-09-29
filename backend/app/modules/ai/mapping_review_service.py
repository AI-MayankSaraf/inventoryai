"""
Confirming what a column means — BR-AI-09.

A proposal is a screen; a *confirmed* mapping is a rule the pipeline will
apply to every future document with the same layout without asking anyone.
That is why confirming is its own endpoint with its own permission, and why
nothing else in this package sets `status = 'confirmed'`.

Deprecating is the other half. §5 step 8 has a mapping whose success rate
falls below 80% retired and relearned as `version + 1`; the automatic part
of that is not built, but the manual escape hatch is, because a supplier
who changes their template should not need a developer.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID, uuid4

from fastapi import Request, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.errors import CODE_DUPLICATE, CODE_INVALID_STATE_TRANSITION, CODE_NOT_FOUND, CODE_VALIDATION, ApiError
from app.core.security import AccessTokenClaims


async def _mapping(session: AsyncSession, *, company_id: str, mapping_id: UUID) -> dict:
    row = (
        await session.execute(
            text("SELECT * FROM document_schema_mappings WHERE company_id = :c AND id = :id"),
            {"c": company_id, "id": mapping_id},
        )
    ).mappings().first()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Mapping not found")
    return dict(row)


async def update_field(
    session: AsyncSession, *, claims: AccessTokenClaims, mapping_id: UUID, field_id: UUID, values: dict
) -> dict:
    mapping = await _mapping(session, company_id=claims.company_id, mapping_id=mapping_id)
    if mapping["status"] == "deprecated":
        raise ApiError(
            status.HTTP_409_CONFLICT, CODE_INVALID_STATE_TRANSITION,
            "This mapping was retired. Upload the supplier's file again to learn the new layout.",
        )
    row = (
        await session.execute(
            text("SELECT * FROM document_schema_mapping_fields WHERE id = :id AND mapping_id = :m"),
            {"id": field_id, "m": mapping_id},
        )
    ).mappings().first()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Column not found on this mapping")

    fields = {k: v for k, v in values.items() if k in {"canonical_field_id", "transform", "transform_arg"} and v is not None}
    if not fields:
        return dict(row)

    assignments = ", ".join(f"{k} = :{k}" for k in fields)
    try:
        await session.execute(
            text(
                f"UPDATE document_schema_mapping_fields SET {assignments}, confidence = 100, "
                " confirmed_by = :who, confirmed_at = now() WHERE id = :id"
            ),
            {**fields, "who": claims.user_id, "id": field_id},
        )
        await session.flush()
    except IntegrityError:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_DUPLICATE,
            "Another column on this mapping already points at that field. "
            "Two columns cannot mean the same thing.",
        )

    # Changing a column after confirmation means the layout was not right,
    # so the mapping goes back to being a proposal rather than silently
    # continuing to be applied.
    if mapping["status"] == "confirmed":
        await session.execute(
            text("UPDATE document_schema_mappings SET status = 'proposed' WHERE id = :id"),
            {"id": mapping_id},
        )
    return dict(row) | fields


async def add_column(
    session: AsyncSession, *, claims: AccessTokenClaims, mapping_id: UUID, source_column: str,
    source_column_index: Optional[int], canonical_field_id: UUID,
) -> dict:
    await _mapping(session, company_id=claims.company_id, mapping_id=mapping_id)
    field_id = uuid4()
    try:
        await session.execute(
            text(
                "INSERT INTO document_schema_mapping_fields (id, mapping_id, source_column, "
                " source_column_index, canonical_field_id, transform, is_required, confidence, "
                " confirmed_by, confirmed_at) "
                "VALUES (:id, :m, :col, :idx, :cf, 'none', false, 100, :who, now())"
            ),
            {
                "id": field_id,
                "m": mapping_id,
                "col": source_column.strip(),
                "idx": source_column_index,
                "cf": canonical_field_id,
                "who": claims.user_id,
            },
        )
        await session.flush()
    except IntegrityError:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_DUPLICATE,
            "That column, or that field, is already mapped on this layout.",
        )
    return {"id": field_id}


async def confirm(
    session: AsyncSession, *, claims: AccessTokenClaims, mapping_id: UUID, request: Optional[Request] = None
) -> dict:
    mapping = await _mapping(session, company_id=claims.company_id, mapping_id=mapping_id)
    if mapping["status"] == "deprecated":
        raise ApiError(
            status.HTTP_409_CONFLICT, CODE_INVALID_STATE_TRANSITION, "A retired mapping cannot be confirmed."
        )

    mapped = (
        await session.execute(
            text(
                "SELECT cf.code FROM document_schema_mapping_fields f "
                "JOIN canonical_fields cf ON cf.id = f.canonical_field_id WHERE f.mapping_id = :m"
            ),
            {"m": mapping_id},
        )
    ).scalars().all()

    # A layout that cannot yield a description, a quantity and a price is
    # not a purchase document, and confirming it would teach the pipeline
    # to produce lines nobody can approve.
    required = {"product_description", "quantity", "unit_price"}
    missing = sorted(required - set(mapped))
    if missing:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_VALIDATION,
            "Map the description, quantity and price columns before confirming.",
            errors=[{"field": code, "message": "No column is mapped to this field"} for code in missing],
        )

    await session.execute(
        text(
            "UPDATE document_schema_mappings SET status = 'confirmed', confirmed_by = :who, "
            " confirmed_at = now(), confidence = 100 WHERE company_id = :c AND id = :id"
        ),
        {"who": claims.user_id, "c": claims.company_id, "id": mapping_id},
    )
    await audit.record(
        session,
        # `ai_extraction` rather than `document`: a mapping is a rule the
        # pipeline learned, not an event on any one uploaded file.
        entity_type="ai_extraction",
        action="confirmed",
        claims=claims,
        entity_id=mapping_id,
        entity_label=mapping["mapping_name"] or mapping["column_signature"][:12],
        description=f"Column mapping confirmed for {mapping['document_type'].replace('_', ' ')}",
        request=request,
    )
    return await _mapping(session, company_id=claims.company_id, mapping_id=mapping_id)


async def deprecate(
    session: AsyncSession, *, claims: AccessTokenClaims, mapping_id: UUID, request: Optional[Request] = None
) -> dict:
    mapping = await _mapping(session, company_id=claims.company_id, mapping_id=mapping_id)
    await session.execute(
        text("UPDATE document_schema_mappings SET status = 'deprecated' WHERE company_id = :c AND id = :id"),
        {"c": claims.company_id, "id": mapping_id},
    )
    await audit.record(
        session,
        entity_type="ai_extraction",
        action="status_changed",
        claims=claims,
        entity_id=mapping_id,
        entity_label=mapping["mapping_name"] or mapping["column_signature"][:12],
        description="Column mapping retired",
        request=request,
    )
    return await _mapping(session, company_id=claims.company_id, mapping_id=mapping_id)
