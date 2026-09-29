# Phase state — S3 document storage (23 Sep 2026)

**Verified against the Floci/LocalStack dev endpoint.** `scripts/verify_s3.py`
passes every check it is able to run there — public access block, ACL,
key shape, encryption, presigned expiry and content, round-trip, absent-key
and bad-bucket handling. Two checks (a tampered or unsigned link being
rejected) print `skip`: that emulator does not enforce SigV4 on presigned
GETs, which is a property of the emulator, not of this code. **Not yet run
against real AWS** — do that before signing off on BR-DOC-03 end to end.
The app itself boots successfully against the same endpoint
(`storage.assert_ready()` passes at `uvicorn` startup), which is the one
piece of this that real infrastructure, not a test script, just confirmed.

Uploaded files now live in a private S3 bucket and nowhere else. The local
directory is gone, and gone deliberately: a fallback that writes to disk
when S3 is unreachable is exactly the fallback that silently ships a
customer's invoices to a server's filesystem, unencrypted, with nothing in
the logs to say so. A misconfigured install refuses to start instead.

Redis remains out of scope and untouched.

## What changed, and why each thing changed

| Change | Why |
| --- | --- |
| `app/core/storage.py` replaces `app/modules/ai/storage.py` | Uploaded bytes stopped being an AI concern once the same `documents` table started holding purchase orders and proformas no model reads. The old path is a re-export so nothing breaks |
| Keys are random UUIDs, not content hashes, and carry no filename | A key built from the filename leaks `Acme_Q3_price_list.xlsx` into logs and signed URLs; a key built from the content hash lets someone who can guess the bytes confirm the guess by probing. Dedupe never needed the key — `uq_document_hash (company_id, sha256_hash)` does it in Postgres, per tenant, which is where BR-DOC-02 puts it |
| `ServerSideEncryption` on every `put_object` | Bucket default encryption is the usual answer and it is one console click away from being switched off. Sending it per object means an object cannot be written unencrypted even then |
| Downloads are a 307 to a pre-signed URL | BR-DOC-03 as written. The redirect rather than a JSON body keeps the existing contract: a browser, a `fetch`, or an `<a download>` all still get the file from `GET /ai/documents/{id}/file` |
| `Content-Disposition: attachment` is **inside** the signature | Otherwise the link can be edited into one that renders a supplier's HTML in the user's own session |
| DB row is inserted **before** the bytes are written | It used to be the other way round. Bytes first means a failed insert leaves an object nobody references and nothing will ever delete. Row first means a failed upload leaves an uncommitted row, and the transaction takes it away for free |
| Compensating delete if the final commit fails | The one remaining window where the two stores can disagree. What the delete cannot clean up, `scripts/s3_orphans.py` finds |
| Insert wrapped in a savepoint; `uq_document_hash` violation → BR-DOC-02's duplicate response | Two identical uploads can race past the dedupe read — a double-clicked Upload button is the ordinary way. It used to surface as a 500. It is now the same 200-with-`duplicate_of` a sequential duplicate gets |
| `storage.assert_ready()` in the app lifespan | A missing bucket or a dead credential stops the process now rather than surfacing as a 500 to whoever uploads first, in an environment where nobody may upload for a day |
| boto3 calls run on a worker thread | boto3 is synchronous. A 20 MB upload on the event loop stalls every other request on the process |

## Files changed

| File | Change |
| --- | --- |
| `app/core/storage.py` | **New.** The whole storage surface: keys, put/get/exists/delete, pre-signing, listing, startup check |
| `app/modules/ai/storage.py` | Now a re-export of the above, so existing imports keep working |
| `app/core/config.py` | S3 settings; `document_storage_dir` removed; Redis demoted to an explicitly-unread placeholder |
| `app/modules/ai/extraction_service.py` | `store_document` reordered and made race-safe, returns `(id, key)`; `DuplicateUpload`; pipeline reads bytes from S3 |
| `app/modules/ai/router.py` | Upload: duplicate race, storage failure → 503, compensating delete. Download: 307 to a pre-signed URL |
| `app/main.py` | `storage.assert_ready()` at boot |
| `requirements.txt` | boto3, botocore, s3transfer, jmespath, urllib3 |
| `.env` | S3 block |
| `scripts/verify_s3.py` | **New.** Proves the storage layer against the configured bucket |
| `scripts/s3_orphans.py` | **New.** Reconciles bucket against `documents` |

**No migration.** `documents.storage_bucket` and `storage_key` were already
S3-shaped from the first schema — the only thing that changes is what goes
into them.

## Consistency: where the two stores can disagree

```
insert row (uncommitted)  ──► upload bytes ──► run pipeline ──► COMMIT
        │                          │                               │
   fails → rollback,          fails → rollback,              fails → delete
   nothing written            row never existed,             the object,
                              no object written              then re-raise
```

The only leak is a crash between the upload and the compensating delete.
That leaves an **orphan object**: bytes with no row. Nothing can reach it —
every read path starts from a `documents` row — so it is a storage bill and
a retention problem, never a correctness one. `scripts/s3_orphans.py`
reports orphans and, with `--delete`, removes those older than a grace
period (default 24h, so an in-flight upload is never mistaken for one).

The reverse — a **dangling row**, whose object is gone — is never repaired
automatically. It means bytes were lost, and the choice between a versioned
restore and asking the user to re-upload belongs to a person. The script
exits non-zero when it finds one, so a scheduled run can alert.

## BR-DOC-03, clause by clause

| Clause | How |
| --- | --- |
| "stored only in S3" | The local storage class is deleted. No fallback, and the app will not boot without a reachable bucket |
| "with server-side encryption" | `ServerSideEncryption` on every write; `S3_SSE` must be `AES256` or `aws:kms` or startup fails |
| "downloads are pre-signed" | `generate_presigned_url`, SigV4 |
| "and expire in 5 minutes" | `S3_PRESIGN_TTL_SECONDS=300` |

Authorisation still happens on our side, before a URL exists: the
`document.download` permission, then the row read under the caller's RLS
scope — which is what makes another tenant's document id a 404 rather than
a redirect.

## Configuration

```dotenv
S3_BUCKET=inventoryai-documents
AWS_REGION=us-east-1
AWS_ENDPOINT_URL=http://localhost.floci.io:4566   # blank on real AWS
AWS_ACCESS_KEY_ID=test                            # blank on AWS → IAM role
AWS_SECRET_ACCESS_KEY=test                        # blank on AWS → IAM role
S3_SSE=AES256
S3_PRESIGN_TTL_SECONDS=300
```

On real AWS, leave both key variables blank so the instance or task role is
used — filling them in means a long-lived key sitting on a server, which is
the thing IAM roles exist to avoid. The bucket needs Block Public Access on
all four settings, default encryption, and versioning (versioning is what
makes a dangling row recoverable rather than terminal).

## Verification status

| Check | Local (Floci/LocalStack) | Real AWS |
| --- | --- | --- |
| Bucket reachable, settings valid | pass | not yet run |
| Public access blocked on all four settings | pass (bucket needed `put-public-access-block` applied manually — not on by default; step now in `BACKEND-SETUP.md`) | not yet run |
| Bucket ACL grants nothing to AllUsers/AuthenticatedUsers | pass | not yet run |
| Key randomness, tenant scoping, no filename in key | pass | not yet run |
| Round trip (put/get/exists/delete, absent-key handling) | pass | not yet run |
| Server-side encryption on the written object | pass | not yet run |
| Presigned link: ~5 min expiry, signed disposition, serves the bytes, forces download, correct filename | pass | not yet run |
| Tampered signature is rejected | **skip** — emulator does not enforce SigV4 | not yet run |
| Unsigned URL is rejected | **skip** — emulator does not enforce SigV4 | not yet run |
| Bad bucket raises without leaking credentials | pass | not yet run |
| App boots (`storage.assert_ready()`) against the real endpoint | **pass** — `uvicorn` started clean | not yet run |

The two skips are the only part of BR-DOC-03 this environment cannot prove.
Real AWS S3 enforces SigV4 unconditionally, so the code path is expected to
pass there; "expected" is not "verified", which is why it is listed as not
yet run rather than assumed.

## Still open

* **No document delete endpoint.** `document.delete` is seeded and granted
  to Owner and Purchase Manager, and no route uses it, so BR-DOC-04
  ("deleting a document never deletes the business record it produced") has
  nothing to govern. Building it means deciding what deletion means for a
  document that has already been approved into an invoice — a business
  rule, not a storage detail, so it is not being invented here.
* **`document_links` is still never written.** The table exists; no code
  path creates a link, so no PO or GRN screen shows its source document.
* **Multipart upload** is not used: files are capped at 20 MB (BR-DOC-01)
  and a single `put_object` is correct at that size.
* **No lifecycle rule.** `documents.retention_expires_at` exists and
  nothing acts on it; expiry belongs in an S3 lifecycle policy plus a
  sweeper, which is its own small phase.
