"""
The document-reading worker.

An upload only queues a job (`extraction_service.enqueue`); this reads it.
Jobs live in `ai_processing_jobs`, so the queue needs no service beyond
Postgres, and it survives restarts: a queued job waits in the table until
some worker is running.

    python -m app.worker           # a dedicated worker process (Docker: `worker`)

or, with EXTRACTION_WORKER=embedded (the default), the same loop runs inside
the API process — nothing extra to start on a development machine or a
small single-server install.

Claiming uses `FOR UPDATE SKIP LOCKED`, so any number of workers, embedded
or not, can run side by side and never take the same job. The claim runs
on the platform connection (the queue spans tenants); the pipeline itself
runs on the ordinary tenant connection with the job's company set, so Row-
Level Security applies to everything it reads and writes, exactly as it did
inside the request.

What a failure means:

* The file cannot be read (unsupported, corrupt, no table): the pipeline
  records it on the job and the document. Final — retrying would not make
  the file readable; a person can press Retry after fixing the cause.
* The worker died mid-job (crash, deploy, power): the job stays `running`
  with nobody working on it. After WORKER_STALE_AFTER_MINUTES it is put back
  in the queue, up to WORKER_MAX_RETRIES times, then dead-lettered and the
  document marked failed with a reason.
* Something unexpected escaped the pipeline (the database went away): the
  job is put back with a growing delay, under the same limit.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import AppSessionLocal, PlatformSessionLocal, set_tenant
from app.modules.ai import extraction_service

log = logging.getLogger("inventoryai.worker")

_wake = asyncio.Event()


def nudge() -> None:
    """Tell an embedded worker in this process that a job was just queued,
    so it starts now rather than at its next poll."""
    _wake.set()


async def claim_next() -> Optional[tuple[UUID, UUID]]:
    """Take the oldest ready job, or None. Returns (job_id, company_id)."""
    async with PlatformSessionLocal() as session, session.begin():
        row = (
            await session.execute(
                text(
                    "UPDATE ai_processing_jobs SET status = 'running', stage = 'Starting', "
                    " started_at = now(), finished_at = NULL "
                    "WHERE id = ("
                    "  SELECT id FROM ai_processing_jobs "
                    "  WHERE status = 'queued' AND job_type = 'extraction' AND available_at <= now() "
                    "  ORDER BY available_at, created_at "
                    "  FOR UPDATE SKIP LOCKED LIMIT 1"
                    ") RETURNING id, company_id"
                )
            )
        ).first()
    return (row[0], row[1]) if row else None


async def run_job(job_id: UUID, company_id: UUID) -> None:
    try:
        async with AppSessionLocal() as session:
            async with session.begin():
                await set_tenant(session, company_id)
                await extraction_service.process_job(session, company_id=str(company_id), job_id=job_id)
    except asyncio.CancelledError:
        # Shutting down (a deploy, a --reload): the pipeline's transaction
        # rolled back, so hand the job straight back rather than leaving it
        # 'running' until it is presumed abandoned. Not a failure; not counted.
        await asyncio.shield(_release(job_id))
        raise
    except Exception as exc:  # noqa: BLE001 — the loop must outlive any one job
        log.exception("extraction job %s crashed", job_id)
        await _put_back(job_id, f"The worker hit an unexpected error: {exc}")


async def _release(job_id: UUID) -> None:
    async with PlatformSessionLocal() as session, session.begin():
        row = (
            await session.execute(
                text(
                    "UPDATE ai_processing_jobs SET status = 'queued', stage = 'Queued', progress = 0, "
                    " started_at = NULL, available_at = now() "
                    "WHERE id = :id AND status = 'running' RETURNING company_id, document_id"
                ),
                {"id": job_id},
            )
        ).first()
        if row:
            await session.execute(
                text(
                    "UPDATE documents SET processing_status = 'queued', processing_stage = 'Queued', "
                    " processing_progress = 0 WHERE company_id = :c AND id = :d"
                ),
                {"c": row[0], "d": row[1]},
            )


async def _put_back(job_id: UUID, reason: str) -> None:
    """Requeue with back-off (30 s, 2 min, 8 min…) or, past the limit,
    dead-letter the job and fail its document."""
    settings = get_settings()
    async with PlatformSessionLocal() as session, session.begin():
        row = (
            await session.execute(
                text(
                    "UPDATE ai_processing_jobs SET "
                    "  status = CASE WHEN retry_count < :max THEN 'queued' ELSE 'dead_letter' END, "
                    "  stage = CASE WHEN retry_count < :max THEN 'Queued' ELSE 'Failed' END, "
                    "  available_at = now() + make_interval(secs => 30 * power(4, retry_count)), "
                    "  retry_count = retry_count + 1, "
                    "  error_code = 'WORKER_ERROR', error_message = :reason, "
                    "  finished_at = CASE WHEN retry_count < :max THEN NULL ELSE now() END "
                    "WHERE id = :id AND status = 'running' RETURNING status, company_id, document_id"
                ),
                {"id": job_id, "max": settings.worker_max_retries, "reason": reason[:1000]},
            )
        ).first()
        if row is None:
            return
        status, company_id, document_id = row
        if status == "dead_letter":
            message = "This document could not be read after several attempts. Press Retry to try again."
            code = "WORKER_GAVE_UP"
            log.error("extraction job %s dead-lettered: %s", job_id, reason)
        else:
            message, code = None, None
        await session.execute(
            text(
                "UPDATE documents SET "
                "  processing_status = CASE WHEN CAST(:code AS text) IS NULL THEN 'queued' ELSE 'failed' END, "
                "  processing_stage = CASE WHEN CAST(:code AS text) IS NULL THEN 'Queued' ELSE 'Failed' END, "
                "  processing_progress = CASE WHEN CAST(:code AS text) IS NULL THEN 0 ELSE 100 END, "
                "  error_code = CAST(:code AS text), error_message = CAST(:msg AS text) "
                "WHERE company_id = :c AND id = :d"
            ),
            {"code": code, "msg": message, "c": company_id, "d": document_id},
        )


async def recover_stale() -> int:
    """Put back jobs whose worker stopped reporting. Returns how many."""
    settings = get_settings()
    async with PlatformSessionLocal() as session, session.begin():
        stale = (
            await session.execute(
                text(
                    "SELECT id FROM ai_processing_jobs "
                    "WHERE status = 'running' AND job_type = 'extraction' "
                    "  AND started_at < now() - make_interval(mins => :mins) "
                    "FOR UPDATE SKIP LOCKED"
                ),
                {"mins": settings.worker_stale_after_minutes},
            )
        ).scalars().all()
    for job_id in stale:
        await _put_back(job_id, "The worker stopped before finishing (restart or crash).")
    if stale:
        log.warning("put %d stale extraction job(s) back in the queue", len(stale))
    return len(stale)


async def run_forever(stop: Optional[asyncio.Event] = None) -> None:
    """Work the queue until `stop` is set (or the task is cancelled)."""
    settings = get_settings()
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    next_recovery = 0.0
    log.info("extraction worker started (poll every %ss)", settings.worker_poll_seconds)
    while not stop.is_set():
        try:
            if loop.time() >= next_recovery:
                await recover_stale()
                next_recovery = loop.time() + 60
            claimed = await claim_next()
            if claimed:
                await run_job(*claimed)
                continue  # there may be more waiting
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — database down: wait and try again
            log.exception("extraction worker: queue unavailable, retrying")
        _wake.clear()
        try:
            await asyncio.wait_for(_wake.wait(), timeout=settings.worker_poll_seconds)
        except asyncio.TimeoutError:
            pass
    log.info("extraction worker stopped")
