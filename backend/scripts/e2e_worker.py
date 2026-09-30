"""
E2E suite — the background extraction worker.

Needs the API running (with EXTRACTION_WORKER=embedded, the default, or a
separate `python -m app.worker`) and the demo data.

    python -m scripts.e2e_worker [base_url]

What it answers:

  * Does an upload return before the document is read, and does a worker
    then read it?
  * Is a file that cannot be read failed once, with a reason — not retried
    for ever?
  * Is a job whose worker died put back in the queue, with a delay, and
    given up on (dead-lettered, document failed) after the retry limit?
  * Is a job interrupted by a shutdown handed straight back?

Exit code 0 only if every check passes.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

from sqlalchemy import text

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
SFX = uuid.uuid4().hex[:6].upper()

passed = 0
failed: list[str] = []


def check(name: str, cond: bool, info: object = "") -> None:
    global passed
    if cond:
        passed += 1
        print(f"  ok   {name}")
    else:
        failed.append(name)
        print(f"  FAIL {name}  -> {str(info)[:300]}")


def call(method: str, path: str, token: str | None = None, body: object = None,
         raw: bytes | None = None, content_type: str = "application/json") -> tuple[int, object]:
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", content_type)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            payload = r.read()
            return r.status, (json.loads(payload) if payload else None)
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, json.loads(payload)
        except Exception:
            return e.code, payload.decode(errors="replace")


def upload(token: str, filename: str, content: bytes) -> tuple[int, object]:
    boundary = f"----e2e{uuid.uuid4().hex}"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return call("POST", "/ai/documents", token, raw=body, content_type=f"multipart/form-data; boundary={boundary}")


def wait_for_job(token: str, document_id: str, timeout: float = 120) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        st, job = call("GET", f"/ai/documents/{document_id}/job", token)
        if st != 200 or job["processing_status"] not in ("queued", "processing") or time.monotonic() > deadline:
            return job
        time.sleep(0.5)


async def checks_against_the_queue(document_id: str) -> None:
    """Drive the worker's recovery paths directly. The document is a real,
    already-read one; the jobs made here are ones a dead worker would leave."""
    from app.core.config import get_settings
    from app.core.db import PlatformSessionLocal, engine, platform_engine
    from app.modules.ai import worker

    settings = get_settings()

    async def sql(statement: str, **params):
        async with PlatformSessionLocal() as session, session.begin():
            result = await session.execute(text(statement), params)
            return result.mappings().all() if result.returns_rows else []

    async def abandoned_job(minutes_ago: int, retry_count: int = 0) -> uuid.UUID:
        row = (await sql(
            "INSERT INTO ai_processing_jobs (id, company_id, document_id, job_type, status, stage, progress, "
            " attempt, retry_count, started_at) "
            "SELECT gen_random_uuid(), company_id, id, 'extraction', 'running', 'Parsing', 10, 1, :r, "
            "       now() - make_interval(mins => :m) FROM documents WHERE id = CAST(:d AS uuid) RETURNING id",
            d=document_id, m=minutes_ago, r=retry_count,
        ))[0]
        await sql("UPDATE documents SET processing_status = 'processing' WHERE id = CAST(:d AS uuid)", d=document_id)
        return row["id"]

    async def job(job_id):
        return dict((await sql(
            "SELECT status, retry_count, available_at > now() AS delayed, error_code FROM ai_processing_jobs "
            "WHERE id = :id", id=job_id,
        ))[0])

    async def document():
        return dict((await sql(
            "SELECT processing_status, error_code FROM documents WHERE id = CAST(:d AS uuid)", d=document_id,
        ))[0])

    try:
        print("\n[a worker that died mid-job]")
        stale = await abandoned_job(settings.worker_stale_after_minutes + 5)
        await worker.recover_stale()  # the API's own worker may get there first; same outcome
        state = await job(stale)
        check("D01 a job abandoned by a dead worker goes back in the queue",
              state["status"] == "queued" and state["retry_count"] == 1, state)
        check("D02 …after a delay, not straight away", state["delayed"], state)
        check("D03 …and its document says it is waiting again",
              (await document())["processing_status"] == "queued", await document())

        fresh = await abandoned_job(1)
        await worker.recover_stale()
        check("D04 a job that is merely slow is left alone", (await job(fresh))["status"] == "running",
              await job(fresh))
        await sql("DELETE FROM ai_processing_jobs WHERE id = :id", id=fresh)

        await sql(
            "UPDATE ai_processing_jobs SET status = 'running', retry_count = :max, "
            " started_at = now() - interval '1 day' WHERE id = :id",
            id=stale, max=settings.worker_max_retries,
        )
        await worker.recover_stale()
        state = await job(stale)
        check("D05 past the retry limit the job is dead-lettered", state["status"] == "dead_letter", state)
        doc = await document()
        check("D06 …and the document is failed with a reason a person can act on",
              doc["processing_status"] == "failed" and doc["error_code"] == "WORKER_GAVE_UP", doc)

        print("\n[a worker that is shut down mid-job]")
        interrupted = await abandoned_job(0)
        await worker._release(interrupted)
        state = await job(interrupted)
        check("S01 the job is handed straight back, not counted as a failure",
              state["status"] == "queued" and state["retry_count"] == 0 and not state["delayed"], state)
        await sql("DELETE FROM ai_processing_jobs WHERE id = :id", id=interrupted)
        await sql(
            "UPDATE documents SET processing_status = 'failed' WHERE id = CAST(:d AS uuid)", d=document_id
        )
    finally:
        await engine.dispose()
        await platform_engine.dispose()


def main() -> int:
    st, body = call("POST", "/auth/login", body={"email": "owner@acme-demo.test", "password": "Demo@12345"})
    assert st == 200, body
    owner = body["access_token"]

    print("\n[upload and read]")
    csv = f"QUOTATION\nQuotation No: W-{SFX}\n\nDescription,Qty,UOM,Rate\nWorker probe {SFX},5,Nos,100\n".encode()
    started = time.monotonic()
    st, up = upload(owner, f"worker-{SFX}.csv", csv)
    took = time.monotonic() - started
    check("U01 the upload is accepted and queued", st == 201 and up["document"]["processing_status"] == "queued",
          (st, up))
    check("U02 …and returns without reading the file first", took < 5, f"{took:.1f}s")
    job = wait_for_job(owner, up["document"]["id"])
    check("U03 a worker reads it", job["processing_status"] == "review_required" and job["items_found"] == 1, job)
    good_document = up["document"]["id"]

    print("\n[a file that cannot be read]")
    st, up = upload(owner, f"broken-{SFX}.pdf", b"%PDF-1.4 this is not really a PDF " + SFX.encode())
    check("F01 the upload is accepted", st == 201, (st, up))
    job = wait_for_job(owner, up["document"]["id"])
    check("F02 the worker records it as failed, with a reason",
          job["processing_status"] == "failed" and job["error_code"] and job["error_message"], job)
    rows = asyncio.run(_job_rows(up["document"]["id"]))
    check("F03 …once: an unreadable file is not retried by itself",
          len(rows) == 1 and rows[0]["status"] == "failed" and rows[0]["retry_count"] == 0, rows)

    asyncio.run(checks_against_the_queue(good_document))

    print(f"\n{passed} passed, {len(failed)} failed")
    return 1 if failed else 0


async def _job_rows(document_id: str) -> list[dict]:
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import get_settings

    db = create_async_engine(get_settings().platform_database_url, poolclass=NullPool)
    try:
        async with db.begin() as conn:
            result = await conn.execute(
                text("SELECT status, retry_count FROM ai_processing_jobs WHERE document_id = CAST(:d AS uuid)"),
                {"d": document_id},
            )
            return [dict(r) for r in result.mappings().all()]
    finally:
        await db.dispose()


if __name__ == "__main__":
    sys.exit(main())
