"""
The pipeline — `08_AI_DATA_MODEL.md` §2, end to end.

    upload → dedupe → parse → classify → schema map → extract → match → review

Everything here writes to `ai_*` tables and to `documents`. Nothing here
writes a quotation, a proforma or an invoice: that is BR-AI-01, and it is
why `review_service.approve` is a separate module with a user id in its
signature.

The run is synchronous. The design assumes a Celery worker and a progress
bar, and this installation has no broker, so the pipeline runs inside the
upload request and the job row records the real stages and real timings
rather than a simulated crawl. The job table's shape is unchanged, so
moving the call into a worker later is a scheduling change, not a rewrite.

Financial values are read but never trusted: `line_total_as_printed` is
stored as a cross-check, and a printed total that disagrees with
quantity × price becomes a validation error on the line (BR-AI-02). The
totals a human eventually approves are recomputed by the money engine.
"""

from __future__ import annotations

import asyncio

import hashlib
import json
import re
import time
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.config import get_settings
from app.core.db import set_tenant
from app.modules.ai import classify, embedding_service, mapping_service, matching_service, parsing, providers
from app.modules.ai.normalise import looks_like_injection, normalise
from app.modules.ai.parsing import ParsedDocument, ParsedTable, UnsupportedFile
from app.modules.ai.values import clean, parse_date, parse_number, parse_percent

PROMPT_VERSION = "deterministic-v1"

#: Header fields worth hunting for in the free text, and the labels that
#: introduce them on a real document. Order matters: the first label that
#: matches wins, so `invoice no` is tried before the bare `no`.
_HEADER_HUNTS: list[tuple[str, str, str, list[str]]] = [
    ("document_number", "Document Number", "string",
     ["invoice no", "invoice number", "quotation no", "quotation number", "quote no", "pi no",
      "bill no", "document no", "ref no", "reference no"]),
    ("document_date", "Document Date", "date",
     ["invoice date", "quotation date", "bill date", "dated", "date"]),
    ("valid_until", "Valid Until", "date",
     ["valid till", "valid upto", "valid until", "validity", "quote valid"]),
    ("supplier_gstin", "Supplier GSTIN", "gstin", ["gstin", "gst no", "gst number", "gstin/uin"]),
    ("payment_terms", "Payment Terms", "string", ["payment terms", "terms of payment", "payment"]),
    ("delivery_terms", "Delivery Terms", "string", ["delivery terms", "delivery", "lead time"]),
    ("po_reference", "PO Reference", "string", ["po no", "purchase order no", "your order no"]),
    ("place_of_supply", "Place of Supply", "string", ["place of supply", "pos"]),
    ("freight_amount", "Freight", "currency", ["freight", "transport charges", "packing & forwarding"]),
    ("total_amount", "Total Amount (as printed)", "currency",
     ["grand total", "total amount", "net amount", "amount payable", "invoice value"]),
]


class PipelineError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ============================================================ entry points


def sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


async def find_duplicate(session: AsyncSession, *, company_id: str, digest: str) -> Optional[dict]:
    """BR-DOC-02 — per tenant, never global. Two wholesalers uploading the
    same manufacturer rate card is normal and must not collide."""
    row = (
        await session.execute(
            text(
                "SELECT id, original_filename, processing_status, uploaded_at, document_type "
                "FROM documents WHERE company_id = :c AND sha256_hash = :h LIMIT 1"
            ),
            {"c": company_id, "h": digest},
        )
    ).mappings().first()
    return dict(row) if row else None


class DuplicateUpload(Exception):
    """Two identical uploads raced each other past the dedupe check.

    `find_duplicate` reads, and the insert writes, and between the two a
    second request carrying the same bytes can slip through — a user
    double-clicking Upload is the ordinary way this happens, not an attack.
    `uq_document_hash` catches it in the database, which is the only place
    that can, and this exception turns that catch back into BR-DOC-02's
    documented answer: the existing document, not an error.
    """


async def store_document(
    session: AsyncSession,
    *,
    company_id: str,
    user_id: str,
    blob: bytes,
    filename: str,
    extension: str,
    mime_type: str,
    digest: str,
    supplier_id: Optional[UUID] = None,
    document_type: Optional[str] = None,
) -> tuple[UUID, str]:
    """Reserve the row, then write the bytes. Returns the id and the S3 key.

    The order matters and used to be the other way round. Bytes first means
    a failed insert — a duplicate, a dead connection, an RLS refusal —
    leaves an object in the bucket that no row references and nothing will
    ever delete: an orphan, holding a customer's document, growing a bill.
    Row first means a failed *upload* leaves an uncommitted row, and the
    transaction takes it away for free.

    Neither order survives a failure of the final commit, which happens
    after this function returns and after the pipeline has run; the caller
    handles that with a compensating delete, and the leftovers it cannot
    delete are what `scripts/s3_orphans.py` exists to find.

    The insert runs inside a savepoint so the duplicate case is recoverable.
    Without one, the unique violation poisons the whole transaction and the
    handler cannot go on to read the existing document back.
    """
    document_id = uuid4()
    key = storage.build_key(company_id=company_id, document_type=document_type, extension=extension)

    try:
        async with session.begin_nested():
            await session.execute(
                text(
                    "INSERT INTO documents (id, company_id, original_filename, storage_bucket, storage_key, "
                    " mime_type, file_extension, file_size_bytes, sha256_hash, document_type, supplier_id, "
                    " processing_status, processing_stage, processing_progress, source, uploaded_by) "
                    "VALUES (:id, :c, :name, :bucket, :key, :mime, :ext, :size, :hash, :dtype, :sup, "
                    " 'queued', 'Queued', 0, 'upload', :user)"
                ),
                {
                    "id": document_id,
                    "c": company_id,
                    "name": filename,
                    "bucket": storage.bucket(),
                    "key": key,
                    "mime": mime_type,
                    "ext": extension,
                    "size": len(blob),
                    "hash": digest,
                    "dtype": document_type,
                    "sup": supplier_id,
                    "user": user_id,
                },
            )
    except IntegrityError as exc:
        # Only the per-tenant hash constraint means "someone already
        # uploaded this". Any other violation is a bug and must not be
        # dressed up as a duplicate.
        if "uq_document_hash" in str(getattr(exc, "orig", exc)):
            raise DuplicateUpload from exc
        raise

    # The row exists (uncommitted). Now the bytes. A storage failure raises,
    # the request unwinds, the transaction rolls back, and nothing is left
    # behind in either place.
    await storage.aput(key, blob, content_type=mime_type)
    return document_id, key


async def enqueue(
    session: AsyncSession, *, company_id: str, user_id: str, document_id: UUID, attempt: int = 1
) -> UUID:
    """Queue the document for reading. Returns the job id.

    Only writes two rows, so an upload returns as soon as the file is
    stored; a worker (`app/modules/ai/worker.py`) picks the job up after
    the caller commits. Reading a scanned 20 MB PDF takes a minute, and a
    request is the wrong place to spend it.
    """
    job_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO ai_processing_jobs (id, company_id, document_id, job_type, status, stage, "
            " progress, provider, prompt_name, prompt_version, attempt, triggered_by) "
            "VALUES (:id, :c, :d, 'extraction', 'queued', 'Queued', 0, :prov, 'extract_purchase_document', "
            " :ver, :attempt, :user)"
        ),
        {
            "id": job_id,
            "c": company_id,
            "d": document_id,
            "prov": get_settings().ai_provider,
            "ver": PROMPT_VERSION,
            "attempt": attempt,
            "user": user_id,
        },
    )
    await session.execute(
        text(
            "UPDATE documents SET processing_status = 'queued', processing_stage = 'Queued', "
            " processing_progress = 0, error_code = NULL, error_message = NULL "
            "WHERE company_id = :c AND id = :id"
        ),
        {"c": company_id, "id": document_id},
    )
    return job_id


async def process_job(session: AsyncSession, *, company_id: str, job_id: UUID) -> None:
    """Parse → classify → map → extract → match, for a job a worker has
    claimed. `session` is scoped to the job's tenant; the caller commits.

    Failures are recorded on the job *and* the document and then returned
    normally: a supplier sending an unreadable file is an ordinary event in
    this system, not a crash, and retrying it would not make it readable.
    """
    started = time.monotonic()
    document_id = (
        await session.execute(
            text("SELECT document_id FROM ai_processing_jobs WHERE company_id = :c AND id = :id"),
            {"c": company_id, "id": job_id},
        )
    ).scalar_one()
    await session.execute(
        text(
            "UPDATE ai_processing_jobs SET status = 'running', stage = 'Parsing', progress = 10, "
            " started_at = COALESCE(started_at, now()) WHERE company_id = :c AND id = :id"
        ),
        {"c": company_id, "id": job_id},
    )
    await _progress(session, company_id, document_id, job_id, "Parsing", 10)

    document = (
        await session.execute(
            text(
                "SELECT id, storage_key, file_extension, original_filename, supplier_id, document_type "
                "FROM documents WHERE company_id = :c AND id = :id"
            ),
            {"c": company_id, "id": document_id},
        )
    ).mappings().one()

    trace: list[dict] = []

    def step(stage: str, detail: str, **extra) -> None:
        trace.append({"stage": stage, "detail": detail, "at_ms": int((time.monotonic() - started) * 1000), **extra})

    # Everything the pipeline writes goes inside a savepoint. On a fresh
    # upload the document row itself is still uncommitted in this same
    # transaction, so a failure must undo only the pipeline's work — a full
    # rollback would delete the very row `_fail` is about to mark failed,
    # and the upload would 500 with its file orphaned in S3.
    savepoint = await session.begin_nested()
    try:
        blob = await storage.aget(document["storage_key"])
        if blob is None:
            raise PipelineError("FILE_MISSING", "The stored file could not be read back.")

        # The canonical vocabulary doubles as the header-row detector's
        # hint list: a row containing "Qty" and "Rate" is the column
        # heading, whatever the letterhead above it looks like.
        canonical = await mapping_service.load_canonical_fields(session)
        hints = {
            normalise(word)
            for field in canonical
            for word in [field["code"].replace("_", " "), field["label"], *(field["synonyms"] or [])]
            if normalise(word)
        }
        # On a worker thread: parsing is CPU-bound, and OCR of a scanned
        # PDF takes seconds per page, which must not stall the event loop.
        parsed = await asyncio.to_thread(parsing.parse, blob, document["file_extension"], hints)
        step("parse", "; ".join(parsed.notes) or "Read the file.", tables=len(parsed.tables))
        await _progress(session, company_id, document_id, job_id, "Classifying", 35)

        table = parsed.primary
        headers = table.headers if table else []
        doc_type, type_confidence = classify.classify_type(parsed.text, headers)
        if document["document_type"]:
            # A person chose the type at upload; that beats a guess.
            doc_type, type_confidence = document["document_type"], 100.0
        supplier_id, supplier_confidence, supplier_reasons = await classify.identify_supplier(
            session,
            company_id=company_id,
            text_body=parsed.text,
            hint_supplier_id=document["supplier_id"],
        )
        step("classify", f"Read as a {doc_type.replace('_', ' ')}. " + "; ".join(supplier_reasons))

        injection = looks_like_injection(parsed.text)
        if injection:
            step("guardrail", "Suspicious instructions found in the document text: " + "; ".join(injection))

        await _progress(session, company_id, document_id, job_id, "Mapping columns", 55)
        mapping = None
        if table:
            mapping = await mapping_service.resolve_mapping(
                session,
                company_id=company_id,
                supplier_id=supplier_id,
                document_type=doc_type,
                table=table,
                document_id=document_id,
                canonical=canonical,
            )
            for note in mapping.trace:
                step("schema_mapping", note, mapping_id=str(mapping.mapping_id), status=mapping.status)
        else:
            step("schema_mapping", "No table to map — header fields only.")

        await _progress(session, company_id, document_id, job_id, "Extracting", 70)

        result_id = uuid4()
        await _retire_previous(session, company_id, document_id)

        fields = _extract_header_fields(parsed, table, doc_type)
        columns = _effective_columns(mapping, table, canonical)
        lines = _extract_lines(table, columns) if table else []

        await session.execute(
            text(
                "INSERT INTO ai_extraction_results (id, company_id, document_id, job_id, schema_mapping_id, "
                " document_type, supplier_id, supplier_confidence, overall_confidence, page_count, "
                " line_count, raw_payload, validation_errors, pipeline_trace, review_status) "
                "VALUES (:id, :c, :d, :j, :m, :t, :sup, :supconf, :conf, :pages, :lines, "
                " CAST(:raw AS jsonb), CAST(:errors AS jsonb), CAST(:trace AS jsonb), 'pending')"
            ),
            {
                "id": result_id,
                "c": company_id,
                "d": document_id,
                "j": job_id,
                "m": mapping.mapping_id if mapping else None,
                "t": doc_type,
                "sup": supplier_id,
                "supconf": supplier_confidence,
                "conf": 0,  # replaced below, once the lines have been matched
                "pages": parsed.page_count,
                "lines": len(lines),
                "raw": json.dumps(
                    {
                        "headers": headers,
                        "sample_rows": (table.rows[:3] if table else []),
                        "sheet": table.sheet_name if table else None,
                    }
                ),
                "errors": json.dumps(
                    [{"code": "PROMPT_INJECTION", "message": note} for note in injection]
                ),
                "trace": json.dumps(trace),
            },
        )

        await _link_supersession(session, company_id, document_id, result_id)

        for field in fields:
            await session.execute(
                text(
                    "INSERT INTO ai_extracted_fields (id, company_id, extraction_result_id, field_key, "
                    " field_label, raw_value, normalised_value, value_type, confidence, provenance, source_cell) "
                    "VALUES (:id, :c, :r, :key, :label, :raw, :norm, :vtype, :conf, :prov, :cell)"
                ),
                {
                    "id": uuid4(),
                    "c": company_id,
                    "r": result_id,
                    "key": field["field_key"],
                    "label": field["field_label"],
                    "raw": field["raw_value"],
                    "norm": field["normalised_value"],
                    "vtype": field["value_type"],
                    "conf": field["confidence"],
                    "prov": field["provenance"],
                    "cell": field.get("source_cell"),
                },
            )

        await _progress(session, company_id, document_id, job_id, "Matching items", 85)
        if lines and providers.embeddings.configured:
            # Top the product index up first, so a product added since the
            # last document can be found by meaning. Capped: a big first
            # backfill belongs to the rebuild script, not to one upload.
            synced = await embedding_service.sync(session, company_id, limit=500)
            if synced["embedded"]:
                step("embeddings", f"Indexed {synced['embedded']} new or changed product(s) for matching by meaning.")
            if synced["error"]:
                step("embeddings", f"Could not update the product index: {synced['error']}")
        matched_count = 0
        skipped_rungs: set[str] = set()
        semantic_used = 0
        for line in lines:
            line_id = uuid4()
            match = await matching_service.match_line(
                session,
                company_id=company_id,
                description=line["raw_description"],
                supplier_sku=line["supplier_sku"],
                barcode=line.get("barcode"),
                supplier_id=supplier_id,
            )
            skipped_rungs.update(match.skipped_rungs)
            semantic_used += any(c.method == "embedding" for c in match.candidates)
            auto = match.auto_matched and match.best is not None
            if auto:
                matched_count += 1
            best = match.best
            await session.execute(
                text(
                    "INSERT INTO ai_extracted_lines (id, company_id, extraction_result_id, line_no, "
                    " raw_description, normalised_description, supplier_sku, raw_quantity, quantity, "
                    " raw_uom, unit_price, discount_pct, gst_rate, hsn_code, line_total_as_printed, "
                    " matched_variant_id, match_method, match_score, confidence, provenance, "
                    " suggestion_text, final_variant_id, final_decision, validation_errors) "
                    "VALUES (:id, :c, :r, :no, :desc, :norm, :sku, :rawqty, :qty, :uom, :price, "
                    " :disc, :gst, :hsn, :printed, :matched, :method, :score, :conf, :prov, "
                    " :suggestion, :final, :decision, CAST(:errors AS jsonb))"
                ),
                {
                    "id": line_id,
                    "c": company_id,
                    "r": result_id,
                    "no": line["line_no"],
                    "desc": line["raw_description"],
                    "norm": normalise(line["raw_description"]),
                    "sku": line["supplier_sku"],
                    "rawqty": line["raw_quantity"],
                    "qty": line["quantity"],
                    "uom": line["raw_uom"],
                    "price": line["unit_price"],
                    "disc": line["discount_pct"],
                    "gst": line["gst_rate"],
                    "hsn": line["hsn_code"],
                    "printed": line["line_total_as_printed"],
                    "matched": best.product_variant_id if best else None,
                    "method": best.method if best else None,
                    "score": best.score if best else None,
                    "conf": best.confidence if best else None,
                    "prov": "ai_extracted" if auto else ("ai_suggested" if best else "needs_review"),
                    "suggestion": _suggestion_text(match),
                    "final": best.product_variant_id if auto else None,
                    "decision": "accepted_ai" if auto else None,
                    "errors": json.dumps(line["validation_errors"]),
                },
            )
            await matching_service.record_candidates(
                session,
                company_id=company_id,
                line_id=line_id,
                supplier_id=supplier_id,
                query_text=line["raw_description"],
                result=match,
                selected_variant_id=best.product_variant_id if auto else None,
            )

        overall = _overall_confidence(fields, lines, matched_count, type_confidence)
        await session.execute(
            text("UPDATE ai_extraction_results SET overall_confidence = :conf WHERE id = :id"),
            {"conf": overall, "id": result_id},
        )

        note = (
            f"{matched_count} of {len(lines)} line(s) matched automatically; "
            f"{len(lines) - matched_count} need a person."
        )
        if "embedding" not in skipped_rungs and lines:
            note += f" Matching by meaning ran; it suggested products for {semantic_used} line(s)."
        elif not providers.embeddings.configured:
            note += " The embedding rung was not attempted — no provider is configured."
        else:
            note += " The embedding rung was not attempted — the embedding model could not be reached."
        note += " The llm rung is not run per line."
        step("match", note)
        await session.execute(
            text("UPDATE ai_extraction_results SET pipeline_trace = CAST(:t AS jsonb) WHERE id = :id"),
            {"t": json.dumps(trace), "id": result_id},
        )

        # §6: every extracted document goes to a human. `ai_auto_process`
        # governs whether extraction *starts* by itself, never whether a
        # person approves.
        await session.execute(
            text(
                "UPDATE documents SET processing_status = 'review_required', processing_stage = 'Needs review', "
                " processing_progress = 100, document_type = :t, document_type_confidence = :tc, "
                " supplier_id = COALESCE(:sup, supplier_id), supplier_confidence = :sc, "
                " extraction_confidence = :conf, items_found = :items, page_count = :pages, "
                " error_code = NULL, error_message = NULL "
                "WHERE company_id = :c AND id = :id"
            ),
            {
                "t": doc_type,
                "tc": type_confidence,
                "sup": supplier_id,
                "sc": supplier_confidence,
                "conf": overall,
                "items": len(lines),
                "pages": parsed.page_count,
                "c": company_id,
                "id": document_id,
            },
        )
        await savepoint.commit()
        await _finish_job(session, company_id, job_id, "succeeded", started, trace)
        return

    except (UnsupportedFile, PipelineError, providers.ProviderNotConfigured, providers.ProviderError) as exc:
        code = getattr(exc, "code", "PIPELINE_FAILED")
        await _fail(session, company_id, document_id, job_id, code, str(exc), started, trace, savepoint)
        return
    except Exception as exc:  # noqa: BLE001 — a parser crash must not 500 the upload
        await _fail(
            session,
            company_id,
            document_id,
            job_id,
            "PIPELINE_FAILED",
            f"The file could not be processed: {exc}",
            started,
            trace,
            savepoint,
        )
        return


class DocumentInUse(Exception):
    """The document backs a business record and must be kept (BR-DOC-04)."""

    def __init__(self, uses: list[str]):
        super().__init__(", ".join(uses))
        self.uses = uses


class DocumentBusy(Exception):
    """A worker is reading the document right now."""


async def delete_document(session: AsyncSession, *, company_id: str, document_id: UUID) -> Optional[dict]:
    """Delete an uploaded document that nothing was made from.

    The rule (BR-DOC-04): a document that became a business record — a
    quotation, proforma or invoice, a product image, a logo — is part of
    that record's evidence and is kept; deleting it is refused with the
    records that use it named. Anything else (a wrong upload, a rejected
    or never-reviewed extraction) can go, together with its AI results and
    jobs (they cascade). Returns the deleted row's summary, or None if there
    was no such document; the caller commits and then removes the S3
    object, so a failed commit never leaves a row pointing at nothing.
    """
    document = (
        await session.execute(
            text(
                "SELECT id, original_filename, storage_key, sha256_hash, processing_status, document_type "
                "FROM documents WHERE company_id = :c AND id = :id FOR UPDATE"
            ),
            {"c": company_id, "id": document_id},
        )
    ).mappings().first()
    if document is None:
        return None
    if document["processing_status"] in ("queued", "processing"):
        raise DocumentBusy()

    uses = [
        f"{row[0].replace('_', ' ')}"
        for row in (
            await session.execute(
                text(
                    "SELECT linked_type FROM document_links WHERE company_id = :c AND document_id = :id "
                    "UNION ALL SELECT 'supplier_quotation' FROM supplier_quotations WHERE company_id = :c AND document_id = :id "
                    "UNION ALL SELECT 'proforma_invoice' FROM proforma_invoices WHERE company_id = :c AND document_id = :id "
                    "UNION ALL SELECT 'supplier_invoice' FROM supplier_invoices WHERE company_id = :c AND document_id = :id "
                    "UNION ALL SELECT 'product_image' FROM product_images WHERE company_id = :c AND document_id = :id "
                    "UNION ALL SELECT 'company_logo' FROM companies WHERE id = :c AND logo_document_id = :id "
                    "UNION ALL SELECT 'profile_picture' FROM users WHERE avatar_document_id = :id "
                    "UNION ALL SELECT 'approved_extraction' FROM ai_extraction_results "
                    "  WHERE company_id = :c AND document_id = :id AND review_status = 'approved'"
                ),
                {"c": company_id, "id": document_id},
            )
        ).all()
    ]
    if uses:
        raise DocumentInUse(sorted(set(uses)))

    # Schema mappings keep their rules; they just lose the sample file.
    await session.execute(
        text(
            "UPDATE document_schema_mappings SET sample_document_id = NULL "
            "WHERE company_id = :c AND sample_document_id = :id"
        ),
        {"c": company_id, "id": document_id},
    )
    await session.execute(
        text("DELETE FROM documents WHERE company_id = :c AND id = :id"),
        {"c": company_id, "id": document_id},
    )
    return dict(document)


# ================================================================ internals


async def _progress(session: AsyncSession, company_id: str, document_id: UUID, job_id: UUID, stage: str, pct: int) -> None:
    await session.execute(
        text(
            "UPDATE documents SET processing_status = 'processing', processing_stage = :s, "
            "processing_progress = :p WHERE company_id = :c AND id = :id"
        ),
        {"s": stage, "p": pct, "c": company_id, "id": document_id},
    )
    await session.execute(
        text("UPDATE ai_processing_jobs SET stage = :s, progress = :p WHERE company_id = :c AND id = :id"),
        {"s": stage, "p": pct, "c": company_id, "id": job_id},
    )


async def _finish_job(session, company_id: str, job_id: UUID, status: str, started: float, trace: list[dict]) -> None:
    await session.execute(
        text(
            "UPDATE ai_processing_jobs SET status = :st, stage = :stage, progress = 100, finished_at = now(), "
            " duration_ms = :ms, response_payload = CAST(:trace AS jsonb) "
            "WHERE company_id = :c AND id = :id"
        ),
        {
            "st": status,
            "stage": "Finished" if status == "succeeded" else "Failed",
            "ms": int((time.monotonic() - started) * 1000),
            "trace": json.dumps({"trace": trace}),
            "c": company_id,
            "id": job_id,
        },
    )


async def _fail(session, company_id, document_id, job_id, code, message, started, trace, savepoint=None) -> None:
    """Record the failure on the job and the document.

    The rollback is load-bearing, not tidiness. If the pipeline died on a
    database error — a unique violation, a constraint — the transaction is
    already aborted and every further statement is refused, so the handler
    that exists to *report* the failure would itself fail and the caller
    would get a 500 with nothing written anywhere. Rolling back to the
    pipeline's savepoint clears that state while keeping the document and
    job rows written before it; the tenant scope is re-asserted anyway.
    """
    if savepoint is not None and savepoint.is_active:
        await savepoint.rollback()
    else:
        await session.rollback()
    await set_tenant(session, company_id)
    trace.append({"stage": "failed", "detail": message})
    await session.execute(
        text(
            "UPDATE ai_processing_jobs SET status = 'failed', stage = 'Failed', progress = 100, "
            " finished_at = now(), duration_ms = :ms, error_code = :code, error_message = :msg "
            "WHERE company_id = :c AND id = :id"
        ),
        {"ms": int((time.monotonic() - started) * 1000), "code": code, "msg": message, "c": company_id, "id": job_id},
    )
    await session.execute(
        text(
            "UPDATE documents SET processing_status = 'failed', processing_stage = 'Failed', "
            " processing_progress = 100, error_code = :code, error_message = :msg "
            "WHERE company_id = :c AND id = :id"
        ),
        {"code": code, "msg": message, "c": company_id, "id": document_id},
    )


async def _retire_previous(session, company_id: str, document_id: UUID) -> None:
    """Make room for a new result, before it exists.

    Two constraints pull in opposite directions here.
    `uq_ai_extraction_active` allows one row per document with
    `superseded_by IS NULL`, so the old result must be retired *before* the
    new one is inserted — but `superseded_by` is a foreign key back into
    this same table, so it cannot point at a row that does not exist yet.
    Writing the new id first fails with a foreign-key violation; writing the
    new row first fails on the unique index.

    So the old row is retired by pointing at *itself*, which satisfies both,
    and `_link_supersession` re-points it at its actual successor once that
    row exists. A crash between the two leaves a result marked as replaced
    by itself — visibly retired, which is the honest reading, rather than
    two rows both claiming to be current.
    """
    await session.execute(
        text(
            "UPDATE ai_extraction_results SET superseded_by = id "
            "WHERE company_id = :c AND document_id = :d AND superseded_by IS NULL"
        ),
        {"c": company_id, "d": document_id},
    )


async def _link_supersession(session, company_id: str, document_id: UUID, new_result_id: UUID) -> None:
    await session.execute(
        text(
            "UPDATE ai_extraction_results SET superseded_by = :new "
            "WHERE company_id = :c AND document_id = :d AND superseded_by = id AND id <> :new"
        ),
        {"new": new_result_id, "c": company_id, "d": document_id},
    )


def _extract_header_fields(parsed: ParsedDocument, table: Optional[ParsedTable], doc_type: str) -> list[dict]:
    """Hunt for labelled values in the document's text.

    Everything found is a *proposal* with a confidence, and every one is
    editable on the review screen — including the ones found with high
    confidence, because a GSTIN read off the wrong line is still a GSTIN.
    """
    body = parsed.text or ""
    found: list[dict] = []
    seen: set[str] = set()

    for key, label, value_type, labels in _HEADER_HUNTS:
        if key in seen:
            continue
        for needle in labels:
            pattern = re.compile(
                rf"{re.escape(needle)}\s*[:\-#]?\s*(?P<value>[^\n\r|]{{1,80}})",
                re.IGNORECASE,
            )
            match = pattern.search(body)
            if not match:
                continue
            raw = clean(match.group("value"))
            if not raw:
                continue
            normalised, confidence, ok = _normalise_header_value(value_type, raw)
            if not ok:
                continue
            found.append(
                {
                    "field_key": key,
                    "field_label": label,
                    "raw_value": raw[:200],
                    "normalised_value": normalised,
                    "value_type": "string" if value_type == "gstin" else value_type,
                    "confidence": confidence,
                    "provenance": "ai_extracted" if confidence >= 90 else "needs_review",
                    "source_cell": None,
                }
            )
            seen.add(key)
            break

    # A GSTIN anywhere in the text is better evidence than a labelled one
    # that did not parse, so it is added even when the label hunt missed.
    if "supplier_gstin" not in seen:
        gstin = classify.GSTIN.search(body.upper())
        if gstin:
            found.append(
                {
                    "field_key": "supplier_gstin",
                    "field_label": "Supplier GSTIN",
                    "raw_value": gstin.group(0),
                    "normalised_value": gstin.group(0),
                    "value_type": "string",
                    "confidence": 95.0,
                    "provenance": "ai_extracted",
                    "source_cell": None,
                }
            )
    return found


def _normalise_header_value(value_type: str, raw: str) -> tuple[Optional[str], float, bool]:
    if value_type == "date":
        parsed = parse_date(raw)
        return (parsed.isoformat() if parsed else None), (92.0 if parsed else 45.0), parsed is not None
    if value_type == "currency":
        parsed = parse_number(raw)
        return (str(parsed) if parsed is not None else None), (88.0 if parsed is not None else 40.0), parsed is not None
    if value_type == "gstin":
        found = classify.GSTIN.search(raw.upper())
        return (found.group(0) if found else None), (97.0 if found else 40.0), found is not None
    return raw, 80.0, True


def _effective_columns(mapping, table: Optional[ParsedTable], canonical: list[dict]) -> dict[str, int]:
    """Which column holds which canonical field.

    A *confirmed* mapping is authoritative. A proposal is used too — but it
    was itself derived from the header synonyms, and the extraction it
    produces is going to a human either way, so this is a display decision
    and not an unreviewed write (BR-AI-09 governs persistence, which
    `confirm_mapping` still gates).
    """
    if mapping and mapping.columns:
        return mapping.columns
    if table is None:
        return {}
    return {
        p.canonical_code: p.source_column_index
        for p in mapping_service.propose_columns(table, canonical)
        if p.canonical_code
    }


def _extract_lines(table: ParsedTable, columns: dict[str, int]) -> list[dict]:
    """Read the grid into line dictionaries.

    A row with no description and no code is not a line — it is a spacer,
    a subtotal, or the "Total" row at the bottom of the table.
    """
    def cell(row: list[str], key: str) -> Optional[str]:
        index = columns.get(key)
        if index is None or index >= len(row):
            return None
        value = row[index]
        return value if str(value).strip() else None

    lines: list[dict] = []
    for row in table.rows:
        description = clean(cell(row, "product_description") or "")
        code = clean(cell(row, "supplier_sku") or "")
        if not description and not code:
            continue
        # The summary row at the foot of the table is not a line item. It
        # is tested against whichever cell the row actually used, because
        # "Total" lands in the description column on some templates and in
        # the code column on others.
        if _is_summary_row(description) or (not description and _is_summary_row(code)):
            continue

        raw_quantity = cell(row, "quantity")
        quantity = parse_number(raw_quantity)
        unit_price = parse_number(cell(row, "unit_price"))
        printed_total = parse_number(cell(row, "line_total"))
        gst_rate = parse_percent(cell(row, "gst_rate"))
        discount = parse_percent(cell(row, "discount_pct"))

        errors: list[dict] = []
        if quantity is None:
            errors.append({"field": "quantity", "message": "No quantity could be read from this row"})
        elif quantity <= 0:
            errors.append({"field": "quantity", "message": "Quantity is not a positive number"})
        if unit_price is None:
            errors.append({"field": "unit_price", "message": "No unit price could be read from this row"})

        # BR-AI-02's cross-check. The printed figure is never adopted; a
        # disagreement is reported so the reviewer can see which of the two
        # the supplier meant.
        if quantity is not None and unit_price is not None and printed_total is not None:
            expected = (quantity * unit_price).quantize(Decimal("0.01"))
            if abs(expected - printed_total) > max(Decimal("1.00"), expected * Decimal("0.01")):
                errors.append(
                    {
                        "field": "line_total",
                        "message": (
                            f"The printed total {printed_total} does not equal quantity x price "
                            f"({expected}). The printed figure is not used."
                        ),
                    }
                )

        lines.append(
            {
                "line_no": len(lines) + 1,
                "raw_description": description or code,
                "supplier_sku": code or None,
                "raw_quantity": clean(raw_quantity) if raw_quantity else None,
                "quantity": quantity,
                "raw_uom": clean(cell(row, "uom") or "") or None,
                "unit_price": unit_price,
                "discount_pct": discount,
                "gst_rate": gst_rate,
                "hsn_code": clean(cell(row, "hsn_code") or "") or None,
                "line_total_as_printed": printed_total,
                "barcode": None,
                "validation_errors": errors,
            }
        )
    return lines


def _is_summary_row(value: str) -> bool:
    return bool(
        re.fullmatch(
            r"(sub\s*)?total|grand\s*total|net\s*total|amount\s*in\s*words.*|round\s*off|t\s*o\s*t\s*a\s*l",
            value.strip().lower(),
        )
    )


def _overall_confidence(fields: list[dict], lines: list[dict], matched: int, type_confidence: float) -> float:
    """A blend, weighted towards the lines — a document whose header reads
    perfectly and whose items are all unrecognised is not a good
    extraction."""
    if not lines and not fields:
        return 0.0
    field_score = sum(f["confidence"] for f in fields) / len(fields) if fields else 60.0
    line_score = (matched / len(lines) * 100) if lines else 50.0
    clean_lines = sum(1 for line in lines if not line["validation_errors"])
    completeness = (clean_lines / len(lines) * 100) if lines else 60.0
    return round(0.2 * type_confidence + 0.2 * field_score + 0.4 * line_score + 0.2 * completeness, 2)


def _suggestion_text(match: matching_service.MatchResult) -> Optional[str]:
    if match.best is None:
        return "No candidate in your catalogue looked close enough — choose the item or add it as new."
    label = matching_service.METHOD_LABELS.get(match.best.method, match.best.method)
    if match.auto_matched:
        return f"Matched to {match.best.sku} by {label.lower()}."
    return f"Best guess {match.best.sku} ({label.lower()}, {match.best.confidence:g}% confidence) — please confirm."
