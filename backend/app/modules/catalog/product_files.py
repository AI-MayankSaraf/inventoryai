"""
Product photos, spec sheets and certificates — the "Images & Documents"
panel on Product detail (`product_images`, 02_DATABASE_DESIGN.md §4).

Each file is an attachment (`app/modules/ai/attachments.py`): a
`documents` row never sent for reading, linked here by `product_images`
rather than `document_links` because a product image carries an order and
a "main photo" flag that a plain link does not.

Changes are audited on the variant, the same convention `detail_service`
uses for conversions and reorder levels.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.db import commit_and_rescope
from app.core.errors import CODE_DUPLICATE, CODE_NOT_FOUND, ApiError
from app.core.security import AccessTokenClaims
from app.modules.ai.attachments import IMAGE_EXTENSIONS, commit_or_discard, delete_if_unused, signed, store_file
from app.modules.catalog.detail_service import _audit_child, _variant

_LIST_SQL = """
    SELECT pi.id, pi.document_id, pi.product_variant_id, pi.is_primary, pi.sort_order,
           d.original_filename, d.mime_type, d.file_extension, d.file_size_bytes, d.uploaded_at,
           d.storage_key, COALESCE(u.full_name, '') AS uploaded_by_name
      FROM product_images pi
      JOIN documents d ON d.id = pi.document_id AND d.company_id = pi.company_id
      LEFT JOIN users u ON u.id = d.uploaded_by
     WHERE pi.company_id = :c AND {where}
     ORDER BY pi.is_primary DESC, pi.sort_order, d.uploaded_at
"""


async def _product_of(session: AsyncSession, c: str, variant_id: UUID) -> tuple[dict, UUID]:
    variant = await _variant(session, c, variant_id)
    product_id = (
        await session.execute(
            text("SELECT product_id FROM product_variants WHERE id = :id AND company_id = :c"),
            {"id": variant_id, "c": c},
        )
    ).scalar_one()
    return variant, product_id


async def list_files(session: AsyncSession, *, claims: AccessTokenClaims, variant_id: UUID) -> list[dict]:
    """Files for this SKU, plus the ones attached to its product as a whole."""
    c = claims.company_id
    _variant_row, product_id = await _product_of(session, c, variant_id)
    rows = (
        await session.execute(
            text(_LIST_SQL.replace(
                "{where}", "pi.product_id = :p AND (pi.product_variant_id IS NULL OR pi.product_variant_id = :v)"
            )),
            {"c": c, "p": product_id, "v": variant_id},
        )
    ).mappings().all()
    return [await signed(r) for r in rows]


async def upload_file(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    variant_id: UUID,
    blob: bytes,
    filename: str,
    mime_type: str,
    request: Request,
) -> dict:
    c = claims.company_id
    variant, product_id = await _product_of(session, c, variant_id)

    stored = await store_file(session, claims=claims, blob=blob, filename=filename, mime_type=mime_type)
    already = (
        await session.execute(
            text(
                "SELECT 1 FROM product_images WHERE company_id = :c AND product_id = :p "
                "AND document_id = :d AND (product_variant_id IS NULL OR product_variant_id = :v)"
            ),
            {"c": c, "p": product_id, "d": stored.document_id, "v": variant_id},
        )
    ).first()
    if already:
        raise ApiError(status.HTTP_409_CONFLICT, CODE_DUPLICATE, "This file is already attached to this product.")

    has_primary_image = (
        await session.execute(
            text("SELECT 1 FROM product_images WHERE company_id = :c AND product_id = :p AND is_primary"),
            {"c": c, "p": product_id},
        )
    ).first()
    link_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO product_images (id, company_id, product_id, product_variant_id, document_id, sort_order, is_primary) "
            "VALUES (:id, :c, :p, :v, :d, "
            " (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM product_images WHERE company_id = :c AND product_id = :p), :primary)"
        ),
        {
            "id": link_id, "c": c, "p": product_id, "v": variant_id, "d": stored.document_id,
            # The first photo becomes the product's picture.
            "primary": stored.extension in IMAGE_EXTENSIONS and not has_primary_image,
        },
    )
    await _audit_child(
        session, claims=claims, entity_type="product_variant", entity_id=variant_id, label=variant["sku"],
        description=f"File attached: {filename}", before=None,
        after={"file": {"document_id": str(stored.document_id), "filename": filename}}, request=request,
    )
    await commit_or_discard(session, claims, stored)

    row = (
        await session.execute(text(_LIST_SQL.replace("{where}", "pi.id = :id")), {"c": c, "id": link_id})
    ).mappings().one()
    return await signed(row)


async def remove_file(session: AsyncSession, *, claims: AccessTokenClaims, file_id: UUID, request: Request) -> None:
    """Detach the file; delete the document too when nothing else uses it."""
    c = claims.company_id
    row = (
        await session.execute(
            text(
                "SELECT pi.id, pi.document_id, pi.product_id, pi.product_variant_id, d.original_filename "
                "FROM product_images pi JOIN documents d ON d.id = pi.document_id "
                "WHERE pi.id = :id AND pi.company_id = :c"
            ),
            {"id": file_id, "c": c},
        )
    ).mappings().first()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "File not found")

    audit_variant = row["product_variant_id"] or (
        await session.execute(
            text(
                "SELECT id FROM product_variants WHERE company_id = :c AND product_id = :p "
                "AND deleted_at IS NULL ORDER BY created_at LIMIT 1"
            ),
            {"c": c, "p": row["product_id"]},
        )
    ).scalar_one()
    variant = await _variant(session, c, audit_variant)

    await session.execute(text("DELETE FROM product_images WHERE id = :id AND company_id = :c"), {"id": file_id, "c": c})
    key = await delete_if_unused(session, company_id=c, document_id=row["document_id"])
    await _audit_child(
        session, claims=claims, entity_type="product_variant", entity_id=variant["id"], label=variant["sku"],
        description=f"File removed: {row['original_filename']}",
        before={"file": {"document_id": str(row["document_id"]), "filename": row["original_filename"]}},
        after=None, request=request,
    )
    await commit_and_rescope(session, UUID(str(c)))
    if key:
        await storage.adelete_quietly(key)
