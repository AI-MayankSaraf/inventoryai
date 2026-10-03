"""
The AI document pipeline's endpoints — `04_API_SPECIFICATION.md` §2.16.

Permissions, and why each one:

* `document.upload` / `document.view` / `document.download` — the file
  itself, independent of what the AI made of it. On top of these, each
  document is only visible to someone who may read the record it feeds
  (`query_service.DOCUMENT_TYPE_PERMISSION`, security audit H2).
* `ai.view` — read an extraction.
* `ai.review` — correct a field, edit a line, confirm or skip a match.
  Reviewing is *not* approving.
* `ai.approve_extraction` — promote it into a quotation, proforma or
  invoice. This is the only endpoint in the package that writes to a
  business table, and it is separately granted because approving a
  supplier's invoice is a financial act.
* `ai.manage_mappings` — confirm a learned column mapping, which changes
  how every *future* document from that supplier is read.
* `ai.assistant` — ask a question.

Uploads run the pipeline inline (see `extraction_service`), so this router
has no background-task machinery to go wrong; when a worker exists, the one
call moves and the endpoints stay as they are.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, storage
from app.core.config import get_settings
from app.core.db import commit_and_rescope, set_tenant
from app.core.deps import get_current_claims, get_tenant_session, require_permission, scoped_godown_filter
from app.core.errors import CODE_DUPLICATE, CODE_NOT_FOUND, CODE_RECORD_IN_USE, CODE_VALIDATION, ApiError
from app.core.security import AccessTokenClaims
from app.modules.ai import (
    assistant_service,
    attachments,
    embedding_service,
    extraction_service,
    mapping_review_service,
    query_service,
    review_service,
    schemas,
)
from app.modules.ai import worker as extraction_worker
from app.modules.ai.parsing import SUPPORTED_EXTENSIONS, UnsupportedFile

router = APIRouter(prefix="/ai", tags=["ai-documents"])


# ============================================================== documents


@router.get("/documents", response_model=list[schemas.DocumentOut])
async def list_documents(
    q: Optional[str] = Query(default=None, max_length=200),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    document_type: Optional[str] = Query(default=None),
    supplier_id: Optional[UUID] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    claims: AccessTokenClaims = Depends(require_permission("document.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await query_service.list_documents(
        session,
        company_id=claims.company_id,
        claims=claims,
        q=q,
        status_filter=status_filter,
        document_type=document_type,
        supplier_id=supplier_id,
        limit=limit,
        offset=offset,
    )


@router.post("/documents", response_model=schemas.UploadResultOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    document_type: Optional[str] = Form(default=None),
    supplier_id: Optional[UUID] = Form(default=None),
    claims: AccessTokenClaims = Depends(require_permission("document.upload")),
    session: AsyncSession = Depends(get_tenant_session),
):
    settings = get_settings()
    blob = await file.read()
    if not blob:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_VALIDATION, "The file is empty.")
    if len(blob) > settings.document_max_bytes:
        raise ApiError(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "FILE_TOO_LARGE",
            f"Files are limited to {settings.document_max_bytes // (1024 * 1024)} MB.",
        )

    filename = file.filename or "upload"
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in SUPPORTED_EXTENSIONS:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "UNSUPPORTED_FILE",
            f"Upload one of: {', '.join(sorted(SUPPORTED_EXTENSIONS))}.",
        )

    digest = extraction_service.sha256(blob)
    duplicate = await extraction_service.find_duplicate(session, company_id=claims.company_id, digest=digest)
    if duplicate:
        # BR-DOC-02 — the same bytes are not processed twice. Returned as
        # the existing document rather than an error: the person uploading
        # did nothing wrong, and what they want is that document.
        existing = await query_service.get_document(
            session, company_id=claims.company_id, document_id=duplicate["id"]
        )
        return {"document": existing, "job_id": None, "duplicate_of": existing}

    try:
        document_id, storage_key = await extraction_service.store_document(
            session,
            company_id=claims.company_id,
            user_id=claims.user_id,
            blob=blob,
            filename=filename,
            extension=extension,
            mime_type=file.content_type or "application/octet-stream",
            digest=digest,
            supplier_id=supplier_id,
            document_type=document_type,
        )
    except extraction_service.DuplicateUpload:
        # The dedupe check above lost a race with a concurrent identical
        # upload — a double-clicked button, usually. BR-DOC-02's answer does
        # not change because the race happened: hand back the document that
        # won. Nothing was written to S3, because the row is reserved first.
        await session.rollback()
        await set_tenant(session, claims.company_id)
        winner = await extraction_service.find_duplicate(
            session, company_id=claims.company_id, digest=digest
        )
        if winner is None:  # pragma: no cover — the constraint just fired
            raise ApiError(
                status.HTTP_409_CONFLICT,
                CODE_DUPLICATE,
                "This file is already being uploaded. Try again in a moment.",
            )
        existing = await query_service.get_document(
            session, company_id=claims.company_id, document_id=winner["id"]
        )
        return {"document": existing, "job_id": None, "duplicate_of": existing}
    except storage.StorageError as exc:
        # The row is uncommitted and the bytes never landed; unwinding takes
        # both away. Worth a distinct code so an operator reading the log
        # knows to look at the bucket and not at the database.
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "STORAGE_UNAVAILABLE",
            "The file could not be stored. Nothing was saved — please try again.",
        ) from exc

    # Reading happens in the worker, after this commits; the response says
    # "queued" and the screen follows the job (GET /documents/{id}/job).
    job_id = await extraction_service.enqueue(
        session, company_id=claims.company_id, user_id=claims.user_id, document_id=document_id
    )

    try:
        await commit_and_rescope(session, claims.company_id)
    except Exception:
        # The only window where the two stores can disagree: the object is
        # written and the row is not. Take the object back out, so the
        # failure leaves the system exactly as it was. If even that fails,
        # `scripts/s3_orphans.py` will find it — an orphan is a cost and a
        # retention problem, never a correctness one, because nothing can
        # reach an object with no row pointing at it.
        await storage.adelete_quietly(storage_key)
        raise
    extraction_worker.nudge()

    document = await query_service.get_document(
        session, company_id=claims.company_id, document_id=document_id
    )
    return {"document": document, "job_id": job_id, "duplicate_of": None}


async def _assert_visible(session: AsyncSession, claims: AccessTokenClaims, document_id: UUID) -> None:
    """Security audit H2: every single-document endpoint answers 404 — not
    403, which would confirm the id exists — unless the caller may read that
    *type* of document (a tax invoice needs `invoice.view`, and so on; see
    `query_service.DOCUMENT_TYPE_PERMISSION`)."""
    if not await query_service.document_visible(session, claims=claims, document_id=document_id):
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Document not found")


@router.get("/documents/{document_id}", response_model=schemas.DocumentOut)
async def get_document(
    document_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("document.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    await _assert_visible(session, claims, document_id)
    document = await query_service.get_document(
        session, company_id=claims.company_id, document_id=document_id
    )
    if document is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Document not found")
    return document


@router.get("/documents/{document_id}/file", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
async def download_document(
    document_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("document.download")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """A pre-signed, 5-minute link to the original bytes (BR-DOC-03).

    Authorisation happens here and only here: `document.download`, then the
    row read under the caller's RLS scope, which is what makes a document
    id from another tenant a 404 rather than a redirect. The URL is issued
    after both, and it addresses exactly one object for a few minutes.

    A redirect rather than a JSON body so the existing contract holds — a
    browser, a fetch, or an `<a download>` all still get the file from this
    URL — while the bytes come from S3 instead of through this process.
    The signature covers `Content-Disposition: attachment`, so the link
    cannot be rewritten into one that renders a supplier's HTML in the
    user's session.
    """
    await _assert_visible(session, claims, document_id)
    url, expires_at = await _signed_download(session, claims.company_id, document_id)
    return RedirectResponse(
        url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={
            # Never let a signed URL sit in a shared cache.
            "Cache-Control": "no-store, private",
            "X-Url-Expires-At": expires_at.isoformat(),
        },
    )


@router.get("/documents/{document_id}/download-link", response_model=schemas.DownloadLinkOut)
async def download_link(
    document_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("document.download")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """The same signed link as `/file`, as JSON — for a web page, which
    sends its token in a header and so cannot simply follow a redirect."""
    await _assert_visible(session, claims, document_id)
    url, expires_at = await _signed_download(session, claims.company_id, document_id)
    return {"url": url, "expires_at": expires_at}


async def _signed_download(session: AsyncSession, company_id, document_id: UUID):
    """Authorise (the row is read under the caller's RLS scope, so another
    tenant's id is a 404) and sign a 5-minute download link."""
    document = await query_service.get_document(session, company_id=company_id, document_id=document_id)
    if document is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Document not found")
    key = (
        await session.execute(
            text("SELECT storage_key FROM documents WHERE company_id = :c AND id = :id"),
            {"c": company_id, "id": document_id},
        )
    ).scalar_one()

    # Cheaper than discovering it as a 404 from S3 after the redirect, and
    # it keeps the error inside our own error format.
    if not await storage.aexists(key):
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "The stored file is missing")

    return await storage.apresigned_get_url(
        key, filename=document["original_filename"], content_type=document["mime_type"]
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("document.delete")),
    session: AsyncSession = Depends(get_tenant_session),
) -> None:
    """Delete an upload nothing was made from (BR-DOC-04). A document behind
    a quotation, proforma, invoice, image or logo is refused with 409."""
    await _assert_visible(session, claims, document_id)
    try:
        deleted = await extraction_service.delete_document(
            session, company_id=claims.company_id, document_id=document_id
        )
    except extraction_service.DocumentBusy:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "INVALID_STATE_TRANSITION",
            "This document is being read right now. Wait for it to finish, then delete it.",
        )
    except extraction_service.DocumentInUse as exc:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_RECORD_IN_USE,
            f"This document is the source of a {', '.join(exc.uses)} and is kept as its evidence. "
            "Delete or cancel that record instead if it is wrong.",
        )
    if deleted is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Document not found")
    await audit.record(
        session,
        entity_type="document",
        action="deleted",
        claims=claims,
        entity_id=document_id,
        entity_label=deleted["original_filename"],
        description="Uploaded document deleted",
        before={
            "original_filename": deleted["original_filename"],
            "sha256": deleted["sha256_hash"],
            "document_type": deleted["document_type"],
            "processing_status": deleted["processing_status"],
        },
        request=request,
    )
    await session.commit()
    # After the commit: the row is gone for good, so the bytes can go too.
    # If this fails the object is an orphan `scripts/s3_orphans.py` finds.
    await storage.adelete_quietly(deleted["storage_key"])


# Attachments: permission is per record type (a GRN's challan needs
# `grn.*`, not `document.*`), so it is checked in `attachments`, not here.

@router.get("/attachments/{linked_type}/{linked_id}", response_model=list[schemas.AttachmentOut])
async def list_attachments(
    linked_type: str,
    linked_id: UUID,
    claims: AccessTokenClaims = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await attachments.list_for_record(session, claims=claims, linked_type=linked_type, linked_id=linked_id)


@router.post(
    "/attachments/{linked_type}/{linked_id}",
    response_model=schemas.AttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_attachment(
    linked_type: str,
    linked_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    claims: AccessTokenClaims = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await attachments.attach_to_record(
        session,
        claims=claims,
        linked_type=linked_type,
        linked_id=linked_id,
        blob=await file.read(),
        filename=file.filename or "file",
        mime_type=file.content_type or "application/octet-stream",
        request=request,
    )


@router.delete("/attachments/{linked_type}/{linked_id}/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_attachment(
    linked_type: str,
    linked_id: UUID,
    link_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> None:
    await attachments.remove_from_record(
        session, claims=claims, linked_type=linked_type, linked_id=linked_id, link_id=link_id, request=request
    )


@router.get("/sources/{linked_type}/{linked_id}", response_model=list[schemas.SourceDocumentOut])
async def source_documents(
    linked_type: str,
    linked_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("document.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """The uploaded files a business record was made from."""
    return await query_service.source_documents(
        session, company_id=claims.company_id, linked_type=linked_type, linked_id=linked_id, claims=claims
    )


@router.get("/documents/{document_id}/job", response_model=schemas.JobStatusOut)
async def job_status(
    document_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("document.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    await _assert_visible(session, claims, document_id)
    job = await query_service.job_status(session, company_id=claims.company_id, document_id=document_id)
    if job is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Document not found")
    return job


@router.post("/documents/{document_id}/retry", response_model=schemas.JobStatusOut)
async def retry_extraction(
    document_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("ai.review")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """Queue the document to be read again.

    The previous result is superseded rather than deleted — a reviewer's
    corrections on the old run stay readable, which matters when the
    question is "why did this change?".
    """
    await _assert_visible(session, claims, document_id)
    document = await query_service.get_document(
        session, company_id=claims.company_id, document_id=document_id
    )
    if document is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Document not found")
    if document["processing_status"] == "approved":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "INVALID_STATE_TRANSITION",
            "This document was approved. Re-reading it would not change what was created.",
        )

    attempt = (
        await session.execute(
            text(
                "SELECT COALESCE(MAX(attempt), 0) + 1 FROM ai_processing_jobs "
                "WHERE company_id = :c AND document_id = :d"
            ),
            {"c": claims.company_id, "d": document_id},
        )
    ).scalar_one()
    if document["processing_status"] in ("queued", "processing"):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "INVALID_STATE_TRANSITION",
            "This document is already being read. Wait for it to finish.",
        )
    await extraction_service.enqueue(
        session,
        company_id=claims.company_id,
        user_id=claims.user_id,
        document_id=document_id,
        attempt=attempt,
    )
    await commit_and_rescope(session, claims.company_id)
    extraction_worker.nudge()
    return await query_service.job_status(session, company_id=claims.company_id, document_id=document_id)


# ============================================================= extraction


@router.get("/documents/{document_id}/extraction", response_model=schemas.ExtractionOut)
async def get_extraction(
    document_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("ai.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    await _assert_visible(session, claims, document_id)
    extraction = await query_service.get_extraction(
        session, company_id=claims.company_id, document_id=document_id
    )
    if extraction is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            CODE_NOT_FOUND,
            "This document has no extraction — it may still be processing, or it failed to parse.",
        )
    return extraction


@router.patch("/fields/{field_id}", response_model=schemas.ExtractedFieldOut)
async def correct_field(
    field_id: UUID,
    body: schemas.FieldCorrection,
    claims: AccessTokenClaims = Depends(require_permission("ai.review")),
    session: AsyncSession = Depends(get_tenant_session),
):
    field = await review_service.correct_field(
        session, claims=claims, field_id=field_id, value=body.value
    )
    await commit_and_rescope(session, claims.company_id)
    return field


@router.patch("/lines/{line_id}", response_model=schemas.ExtractedLineOut)
async def update_line(
    line_id: UUID,
    body: schemas.LineUpdate,
    claims: AccessTokenClaims = Depends(require_permission("ai.review")),
    session: AsyncSession = Depends(get_tenant_session),
):
    line = await review_service.update_line(
        session, claims=claims, line_id=line_id, values=body.model_dump(exclude_unset=True)
    )
    await commit_and_rescope(session, claims.company_id)
    return line | {"candidates": [], "validation_errors": []}


@router.get("/lines/{line_id}/candidates", response_model=schemas.SuggestionsOut)
async def suggest_matches(
    line_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("ai.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    result = await review_service.suggest_matches(
        session, company_id=claims.company_id, line_id=line_id
    )
    await commit_and_rescope(session, claims.company_id)
    return result


@router.post("/lines/{line_id}/match", response_model=schemas.ExtractedLineOut)
async def confirm_match(
    line_id: UUID,
    body: schemas.ConfirmMatchRequest,
    claims: AccessTokenClaims = Depends(require_permission("ai.review")),
    session: AsyncSession = Depends(get_tenant_session),
):
    line = await review_service.confirm_match(
        session,
        claims=claims,
        line_id=line_id,
        product_variant_id=body.product_variant_id,
        save_alias=body.save_alias,
    )
    await commit_and_rescope(session, claims.company_id)
    return line | {"candidates": [], "validation_errors": []}


@router.post("/lines/{line_id}/skip", response_model=schemas.ExtractedLineOut)
async def skip_line(
    line_id: UUID,
    body: schemas.SkipLineRequest,
    claims: AccessTokenClaims = Depends(require_permission("ai.review")),
    session: AsyncSession = Depends(get_tenant_session),
):
    line = await review_service.skip_line(session, claims=claims, line_id=line_id, reason=body.reason)
    await commit_and_rescope(session, claims.company_id)
    return line | {"candidates": [], "validation_errors": []}


@router.post("/documents/{document_id}/approve", response_model=schemas.ApprovalOut)
async def approve_extraction(
    document_id: UUID,
    body: schemas.ApproveRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("ai.approve_extraction")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """The only endpoint in this package that writes a business document.

    It takes the reviewer's identity from their token and cannot be called
    without one, which is the "no auto-approval" guardrail in §8 expressed
    as an API shape rather than a setting.
    """
    await _assert_visible(session, claims, document_id)
    result = await review_service.approve(
        session, claims=claims, document_id=document_id, rfq_id=body.rfq_id, request=request
    )
    await commit_and_rescope(session, claims.company_id)
    return result


@router.post("/documents/{document_id}/reject", response_model=schemas.RejectionOut)
async def reject_extraction(
    document_id: UUID,
    body: schemas.RejectRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("ai.review")),
    session: AsyncSession = Depends(get_tenant_session),
):
    await _assert_visible(session, claims, document_id)
    result = await review_service.reject(
        session, claims=claims, document_id=document_id, reason=body.reason, request=request
    )
    await commit_and_rescope(session, claims.company_id)
    return result


# ======================================================== schema mappings


@router.get("/schema-mappings", response_model=list[schemas.SchemaMappingOut])
async def list_mappings(
    status_filter: Optional[str] = Query(default=None, alias="status", pattern="^(proposed|confirmed|deprecated)$"),
    limit: int = Query(default=100, ge=1, le=500),
    claims: AccessTokenClaims = Depends(require_permission("ai.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await query_service.list_mappings(
        session, company_id=claims.company_id, status_filter=status_filter, limit=limit
    )


@router.get("/schema-mappings/{mapping_id}", response_model=schemas.SchemaMappingOut)
async def get_mapping(
    mapping_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("ai.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    mapping = await query_service.get_mapping(
        session, company_id=claims.company_id, mapping_id=mapping_id
    )
    if mapping is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Mapping not found")
    return mapping


@router.patch("/schema-mappings/{mapping_id}/fields/{field_id}", response_model=schemas.SchemaMappingOut)
async def update_mapping_field(
    mapping_id: UUID,
    field_id: UUID,
    body: schemas.MappingFieldUpdate,
    claims: AccessTokenClaims = Depends(require_permission("ai.manage_mappings")),
    session: AsyncSession = Depends(get_tenant_session),
):
    await mapping_review_service.update_field(
        session,
        claims=claims,
        mapping_id=mapping_id,
        field_id=field_id,
        values=body.model_dump(exclude_unset=True),
    )
    await commit_and_rescope(session, claims.company_id)
    return await query_service.get_mapping(session, company_id=claims.company_id, mapping_id=mapping_id)


@router.post("/schema-mappings/{mapping_id}/fields", response_model=schemas.SchemaMappingOut,
             status_code=status.HTTP_201_CREATED)
async def add_mapping_column(
    mapping_id: UUID,
    body: schemas.MappingColumnAdd,
    claims: AccessTokenClaims = Depends(require_permission("ai.manage_mappings")),
    session: AsyncSession = Depends(get_tenant_session),
):
    await mapping_review_service.add_column(
        session,
        claims=claims,
        mapping_id=mapping_id,
        source_column=body.source_column,
        source_column_index=body.source_column_index,
        canonical_field_id=body.canonical_field_id,
    )
    await commit_and_rescope(session, claims.company_id)
    return await query_service.get_mapping(session, company_id=claims.company_id, mapping_id=mapping_id)


@router.post("/schema-mappings/{mapping_id}/confirm", response_model=schemas.SchemaMappingOut)
async def confirm_mapping(
    mapping_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("ai.manage_mappings")),
    session: AsyncSession = Depends(get_tenant_session),
):
    await mapping_review_service.confirm(session, claims=claims, mapping_id=mapping_id, request=request)
    await commit_and_rescope(session, claims.company_id)
    return await query_service.get_mapping(session, company_id=claims.company_id, mapping_id=mapping_id)


@router.post("/schema-mappings/{mapping_id}/deprecate", response_model=schemas.SchemaMappingOut)
async def deprecate_mapping(
    mapping_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("ai.manage_mappings")),
    session: AsyncSession = Depends(get_tenant_session),
):
    await mapping_review_service.deprecate(session, claims=claims, mapping_id=mapping_id, request=request)
    await commit_and_rescope(session, claims.company_id)
    return await query_service.get_mapping(session, company_id=claims.company_id, mapping_id=mapping_id)


@router.get("/canonical-fields", response_model=list[schemas.CanonicalFieldOut])
async def list_canonical_fields(
    field_group: Optional[str] = Query(default=None, pattern="^(header|line)$"),
    claims: AccessTokenClaims = Depends(require_permission("ai.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await query_service.list_canonical_fields(session, field_group=field_group)


# ============================================================ embeddings


async def _embedding_status(session: AsyncSession, company_id: str) -> dict:
    state = await embedding_service.status(session, company_id)
    progress = embedding_service.rebuild_progress(company_id)
    return {
        **state,
        "rebuilding": progress is not None,
        "rebuild_embedded": progress["embedded"] if progress else 0,
        "last_error": (progress or {}).get("error") or embedding_service.last_error(company_id),
    }


@router.get("/embeddings/status", response_model=schemas.EmbeddingStatusOut)
async def embedding_status(
    claims: AccessTokenClaims = Depends(require_permission("ai.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """How much of the catalogue is indexed for matching by meaning."""
    return await _embedding_status(session, claims.company_id)


@router.post("/embeddings/rebuild", response_model=schemas.EmbeddingStatusOut, status_code=status.HTTP_202_ACCEPTED)
async def rebuild_embeddings(
    everything: bool = Query(default=False, description="Re-embed every product, not just new or changed ones"),
    claims: AccessTokenClaims = Depends(require_permission("ai.manage_mappings")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """Index the catalogue in the background. Day to day this isn't needed —
    matching tops the index up before each document — but it is after the
    embedding model changes, or to index a large catalogue up front."""
    if not embedding_service.providers.embeddings.configured:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_VALIDATION,
            "No embedding model is configured (AI_PROVIDER / AI_EMBEDDING_MODEL).",
        )
    embedding_service.start_rebuild(claims.company_id, everything=everything)
    return await _embedding_status(session, claims.company_id)


# ============================================================== assistant


@router.get("/assistant/suggestions", response_model=list[schemas.AssistantSuggestionOut])
async def assistant_suggestions(
    claims: AccessTokenClaims = Depends(require_permission("ai.assistant")),
) -> list[dict]:
    """Example questions, one per question type the assistant can answer."""
    return assistant_service.suggestions()


@router.post("/assistant", response_model=schemas.AssistantAnswerOut)
async def ask_assistant(
    body: schemas.AssistantRequest,
    claims: AccessTokenClaims = Depends(require_permission("ai.assistant")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """BR-AI-08: no SQL is generated. The question picks an intent, the
    intent picks a hand-written query, and the caller's godown scope is
    applied to it from their token — never from the question."""
    clause, params = scoped_godown_filter(claims, "sb.godown_id")
    # The fragment is ANDed into a WHERE that already has a tenant
    # predicate, so it carries its own conjunction or it is empty.
    godown_filter = f"AND {clause}" if clause else ""
    answer = await assistant_service.ask(
        session, claims=claims, question=body.question, godown_filter=godown_filter, params=params
    )
    await commit_and_rescope(session, claims.company_id)
    return answer
