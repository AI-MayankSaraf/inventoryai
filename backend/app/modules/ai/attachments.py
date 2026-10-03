"""
Files attached to a business record — a delivery challan on a goods
receipt, a product photo, a signed copy — as opposed to files sent to AI
Documents to be *read*.

An attachment is an ordinary `documents` row, so it gets everything that
table already guarantees: private S3, server-side encryption, per-tenant
de-duplication, 5-minute signed links (BR-DOC-01..03). The difference is
`processing_status = 'uploaded'`: it is never queued for reading, and the
AI Documents list leaves such rows out. An AI upload that someone also
attaches to a record keeps its own status and stays in that list.

`store_file` is the shared half (checks, dedupe, the row, the bytes);
record-specific services (`catalog.product_files`, the record attachments
below) add the link and the audit entry and commit.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional
from uuid import UUID, uuid4

from fastapi import Request, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, storage
from app.core.config import get_settings
from app.core.db import commit_and_rescope
from app.core.deps import assert_godown_in_scope, godown_readable
from app.core.errors import CODE_DUPLICATE, CODE_NOT_FOUND, CODE_VALIDATION, ApiError
from app.core.security import AccessTokenClaims
from app.modules.ai import extraction_service
from app.modules.ai.parsing import UnsupportedFile, sniff

#: Photos, PDFs and Office files — what people attach as evidence. CSV and
#: legacy .xls are data, not attachments.
ATTACHMENT_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "pdf", "docx", "xlsx"}
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


@dataclass
class StoredFile:
    document_id: UUID
    #: Set only when a new object was written — the caller deletes it if
    #: its commit fails. `None` when an existing document was reused.
    new_key: Optional[str]
    extension: str
    filename: str


async def store_file(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    blob: bytes,
    filename: str,
    mime_type: str,
    document_type: str = "other",
) -> StoredFile:
    """Check, de-duplicate and store one file. Does not commit."""
    if not blob:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_VALIDATION, "The file is empty.")
    limit = get_settings().document_max_bytes
    if len(blob) > limit:
        raise ApiError(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "FILE_TOO_LARGE", f"Files are limited to {limit // (1024 * 1024)} MB."
        )
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ATTACHMENT_EXTENSIONS:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "UNSUPPORTED_FILE",
            "Upload a photo (.jpg, .png, .webp), a PDF, or a Word or Excel file.",
        )
    try:
        # The bytes decide what it is; a .png that is really a WebP is
        # stored as what it is, so the browser renders it.
        actual = sniff(blob, extension)
    except UnsupportedFile as exc:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.code, str(exc))
    if actual in IMAGE_EXTENSIONS:
        mime_type = f"image/{actual}"

    digest = hashlib.sha256(blob).hexdigest()
    existing = await extraction_service.find_duplicate(session, company_id=claims.company_id, digest=digest)
    if existing:
        # BR-DOC-02: the same bytes are one document per tenant.
        return StoredFile(existing["id"], None, actual, filename)

    document_id = uuid4()
    key = storage.build_key(company_id=claims.company_id, document_type=document_type, extension=actual)
    await session.execute(
        text(
            "INSERT INTO documents (id, company_id, original_filename, storage_bucket, storage_key, "
            " mime_type, file_extension, file_size_bytes, sha256_hash, document_type, "
            " processing_status, source, uploaded_by) "
            "VALUES (:id, :c, :name, :bucket, :key, :mime, :ext, :size, :hash, :dtype, "
            " 'uploaded', 'upload', :user)"
        ),
        {
            "id": document_id, "c": claims.company_id, "name": filename, "bucket": storage.bucket(), "key": key,
            "mime": mime_type, "ext": actual, "size": len(blob), "hash": digest, "dtype": document_type,
            "user": claims.user_id,
        },
    )
    # Row first, then bytes (the order `store_document` explains).
    await storage.aput(key, blob, content_type=mime_type)
    return StoredFile(document_id, key, actual, filename)


async def commit_or_discard(session: AsyncSession, claims: AccessTokenClaims, stored: StoredFile) -> None:
    """Commit; if that fails, remove the object no row will point at."""
    try:
        await commit_and_rescope(session, UUID(str(claims.company_id)))
    except Exception:
        if stored.new_key:
            await storage.adelete_quietly(stored.new_key)
        raise


async def delete_if_unused(session: AsyncSession, *, company_id: str, document_id: UUID) -> Optional[str]:
    """After a link is removed: delete the document too when it was an
    attachment and nothing else uses it. Returns the S3 key to delete once
    the caller has committed, or None."""
    status_now = (
        await session.execute(
            text("SELECT processing_status FROM documents WHERE company_id = :c AND id = :id"),
            {"c": company_id, "id": document_id},
        )
    ).scalar_one_or_none()
    # A file that came in through AI Documents is still that upload;
    # detaching it from a record must not delete it.
    if status_now != "uploaded":
        return None
    try:
        deleted = await extraction_service.delete_document(session, company_id=company_id, document_id=document_id)
    except (extraction_service.DocumentInUse, extraction_service.DocumentBusy):
        return None
    return deleted["storage_key"] if deleted else None


async def signed(row) -> dict:
    """A listing row plus a short-lived URL the browser can fetch directly."""
    out = {k: row[k] for k in row.keys() if k != "storage_key"}
    out["is_image"] = row["file_extension"] in IMAGE_EXTENSIONS
    url, expires_at = await storage.apresigned_get_url(
        row["storage_key"], filename=row["original_filename"], content_type=row["mime_type"]
    )
    out["url"], out["url_expires_at"] = url, expires_at
    return out


# ============================================================ record links


@dataclass(frozen=True)
class RecordKind:
    table: str
    label_column: str
    audit_entity: str
    view_permissions: tuple[str, ...]
    edit_permissions: tuple[str, ...]
    #: Godown-scoped records: writes need the godown in the caller's scope.
    godown_column: Optional[str] = None
    godown_override: str = ""


#: Records files can be attached to, keyed by `document_links.linked_type`.
#: Adding a record type is one entry here plus its screen.
RECORD_KINDS: dict[str, RecordKind] = {
    "goods_receipt": RecordKind(
        table="goods_receipts",
        label_column="grn_number",
        audit_entity="goods_receipt",
        view_permissions=("grn.view",),
        # Whoever can raise the receipt can attach its challan.
        edit_permissions=("grn.create", "grn.update"),
        godown_column="godown_id",
        godown_override="grn.receive_other_godown",
    ),
}

_LIST_SQL = """
    SELECT l.id AS link_id, d.id AS document_id, d.original_filename, d.mime_type, d.file_extension,
           d.file_size_bytes, d.document_type, d.uploaded_at, d.storage_key, l.link_role,
           COALESCE(u.full_name, '') AS uploaded_by_name
      FROM document_links l
      JOIN documents d ON d.id = l.document_id AND d.company_id = l.company_id
      LEFT JOIN users u ON u.id = d.uploaded_by
     WHERE l.company_id = :c AND {where}
     ORDER BY l.linked_at
"""


def _kind(linked_type: str) -> RecordKind:
    kind = RECORD_KINDS.get(linked_type)
    if kind is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Files cannot be attached to this kind of record")
    return kind


def _require_any(claims: AccessTokenClaims, codes: tuple[str, ...]) -> None:
    if not any(code in claims.permissions for code in codes):
        raise ApiError(status.HTTP_403_FORBIDDEN, "FORBIDDEN", f"Missing permission: {' or '.join(codes)}")


async def _record(session: AsyncSession, claims: AccessTokenClaims, kind: RecordKind, linked_id: UUID) -> dict:
    columns = f"id, {kind.label_column} AS label" + (f", {kind.godown_column} AS godown_id" if kind.godown_column else "")
    row = (
        await session.execute(
            text(f"SELECT {columns} FROM {kind.table} WHERE id = :id AND company_id = :c"),
            {"id": linked_id, "c": claims.company_id},
        )
    ).mappings().first()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Record not found")
    return dict(row)


async def list_for_record(
    session: AsyncSession, *, claims: AccessTokenClaims, linked_type: str, linked_id: UUID
) -> list[dict]:
    kind = _kind(linked_type)
    _require_any(claims, kind.view_permissions)
    record = await _record(session, claims, kind, linked_id)
    # Security audit H2/H3: a GRN's challan belongs to that godown. Same
    # read rule as the receipt itself — and the same 404 for out-of-scope.
    if kind.godown_column and not (
        godown_readable(claims, record["godown_id"])
        or (kind.godown_override and kind.godown_override in claims.permissions)
    ):
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Record not found")
    rows = (
        await session.execute(
            text(_LIST_SQL.replace("{where}", "l.linked_type = :t AND l.linked_id = :id")),
            {"c": claims.company_id, "t": linked_type, "id": linked_id},
        )
    ).mappings().all()
    return [await signed(r) for r in rows]


async def attach_to_record(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    linked_type: str,
    linked_id: UUID,
    blob: bytes,
    filename: str,
    mime_type: str,
    request: Request,
) -> dict:
    kind = _kind(linked_type)
    _require_any(claims, kind.edit_permissions)
    record = await _record(session, claims, kind, linked_id)
    if kind.godown_column:
        assert_godown_in_scope(claims, record["godown_id"], override_permission=kind.godown_override)

    stored = await store_file(session, claims=claims, blob=blob, filename=filename, mime_type=mime_type)
    link_id = uuid4()
    try:
        async with session.begin_nested():
            await session.execute(
                text(
                    "INSERT INTO document_links (id, company_id, document_id, linked_type, linked_id, link_role, linked_by) "
                    "VALUES (:id, :c, :d, :t, :lid, 'attachment', :user)"
                ),
                {"id": link_id, "c": claims.company_id, "d": stored.document_id, "t": linked_type,
                 "lid": linked_id, "user": claims.user_id},
            )
    except IntegrityError as exc:
        if stored.new_key:
            await storage.adelete_quietly(stored.new_key)
        if "uq_document_link" in str(getattr(exc, "orig", exc)):
            raise ApiError(status.HTTP_409_CONFLICT, CODE_DUPLICATE, "This file is already attached here.")
        raise

    await audit.record(
        session, entity_type=kind.audit_entity, action="updated", claims=claims, entity_id=linked_id,
        entity_label=record["label"], description=f"File attached: {filename}",
        after={"file": {"document_id": str(stored.document_id), "filename": filename}}, request=request,
    )
    await commit_or_discard(session, claims, stored)
    row = (
        await session.execute(text(_LIST_SQL.replace("{where}", "l.id = :id")), {"c": claims.company_id, "id": link_id})
    ).mappings().one()
    return await signed(row)


async def remove_from_record(
    session: AsyncSession, *, claims: AccessTokenClaims, linked_type: str, linked_id: UUID, link_id: UUID, request: Request
) -> None:
    kind = _kind(linked_type)
    _require_any(claims, kind.edit_permissions)
    record = await _record(session, claims, kind, linked_id)
    if kind.godown_column:
        assert_godown_in_scope(claims, record["godown_id"], override_permission=kind.godown_override)

    link = (
        await session.execute(
            text(
                "SELECT l.document_id, d.original_filename FROM document_links l JOIN documents d ON d.id = l.document_id "
                "WHERE l.id = :id AND l.company_id = :c AND l.linked_type = :t AND l.linked_id = :lid "
                "AND l.link_role = 'attachment'"
            ),
            {"id": link_id, "c": claims.company_id, "t": linked_type, "lid": linked_id},
        )
    ).mappings().first()
    if link is None:
        # Only attachments come off this way — a "source" link (the file a
        # quotation was read from) is part of that record's history.
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "File not found")

    await session.execute(text("DELETE FROM document_links WHERE id = :id AND company_id = :c"), {"id": link_id, "c": claims.company_id})
    key = await delete_if_unused(session, company_id=claims.company_id, document_id=link["document_id"])
    await audit.record(
        session, entity_type=kind.audit_entity, action="updated", claims=claims, entity_id=linked_id,
        entity_label=record["label"], description=f"File removed: {link['original_filename']}",
        before={"file": {"document_id": str(link["document_id"]), "filename": link["original_filename"]}},
        request=request,
    )
    await commit_and_rescope(session, UUID(str(claims.company_id)))
    if key:
        await storage.adelete_quietly(key)
