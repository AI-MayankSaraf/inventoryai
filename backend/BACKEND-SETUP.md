# InventoryAI Backend

Three phases built so far: the foundation (schema, migrations, seed data, health check), auth + RBAC + Row-Level Security, and Phase 1A completion (audit trail, document numbering, full master-data CRUD, company settings, users & invitations). Full write-ups live in the Claude project as `backend-foundation-phase-state.md`, `auth-rbac-phase-state.md` and `phase-1a-completion-state.md`.

## Prerequisites

- Python 3.11+
- Postgres 16+ with `pgcrypto`, `pg_trgm` and `vector` (pgvector) available.

## One-time setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
```

### Database roles

Three roles, not one — Row-Level Security needs a role it actually applies to, plus one that legitimately bypasses it. Run as a superuser (`psql -U postgres`):

```sql
-- Schema owner: Alembic migrates with this. Owns the tables, so it bypasses
-- RLS by default -- correct for DDL, never used at runtime.
CREATE ROLE inventoryai WITH LOGIN PASSWORD 'inventoryai_dev' CREATEDB;
CREATE DATABASE inventoryai OWNER inventoryai;
\c inventoryai
CREATE EXTENSION IF NOT EXISTS vector;   -- superuser only; pgcrypto/pg_trgm are created by the migration

-- Runtime role: NOT the owner, NOT BYPASSRLS, so every query it runs is
-- genuinely subject to the tenant-isolation policies.
CREATE ROLE inventoryai_app WITH LOGIN PASSWORD 'inventoryai_app_dev';

-- Platform/service role: BYPASSRLS, for seeding, auth token lookups (which
-- happen before any tenant is known) and impersonation.
CREATE ROLE inventoryai_platform WITH LOGIN PASSWORD 'inventoryai_platform_dev' BYPASSRLS;

GRANT CONNECT ON DATABASE inventoryai TO inventoryai_app, inventoryai_platform;
GRANT USAGE ON SCHEMA public TO inventoryai_app, inventoryai_platform;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO inventoryai_app, inventoryai_platform;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO inventoryai_app, inventoryai_platform;
ALTER DEFAULT PRIVILEGES FOR ROLE inventoryai IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO inventoryai_app, inventoryai_platform;
ALTER DEFAULT PRIVILEGES FOR ROLE inventoryai IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO inventoryai_app, inventoryai_platform;
```

If your database is owned by `postgres` rather than `inventoryai`, change the `ALTER DEFAULT PRIVILEGES FOR ROLE ...` lines to name the actual owner — those two lines are what makes *future* migrations grant the app roles access automatically.

Set all three connection strings in `.env` next to `alembic.ini`:

```
DATABASE_URL=postgresql+asyncpg://<owner>:<pw>@localhost:5432/inventoryai
APP_DATABASE_URL=postgresql+asyncpg://inventoryai_app:inventoryai_app_dev@localhost:5432/inventoryai
PLATFORM_DATABASE_URL=postgresql+asyncpg://inventoryai_platform:inventoryai_platform_dev@localhost:5432/inventoryai
```

**`APP_DATABASE_URL` must never point at a superuser or the table owner.** Superusers bypass RLS unconditionally, which would silently disable every tenant-isolation policy. The app refuses to start if you get this wrong — see below.

## Apply migrations

```bash
alembic upgrade head
```

There are 20 migrations; the foundational four are below, and each later one opens with a docstring saying what it changes and why (`alembic history` lists them all):

| Revision | What it does |
|---|---|
| `b16098bff981` | Initial schema — 66 tables, composite tenant FKs, the `inventory_transactions` append-only trigger |
| `746390963b46` | Row-Level Security — `tenant_isolation` policies on 64 tables |
| `efc6b3fb9fdb` | Widens the `audit_logs` action/entity vocabularies so login failures, permission denials and master-data changes can actually be recorded |
| `d613c7aa375a` | **Restores 73 foreign keys** that the initial migration declared but never created (Alembic silently drops `use_alter` constraints). Apply this — without it, most `created_by`/`uom_id` columns have no referential integrity |

Every migration has a downgrade. The newest two (`a8c4e1f7d2b6` record timestamps, `c7e2a9f4b1d3` lists and plans) have been checked with a downgrade and re-upgrade on a seeded database.

## Seed baseline data

The seed always writes the reference data every install needs — 9 UoMs, the permission catalogue, and the system roles with their grants (subscription plans come from migration `c7e2a9f4b1d3`). What else it creates is your choice. All of it is safe to re-run.

### A real start (no demo data)

```bash
python -m app.db.seed --admin-email you@yourcompany.com --admin-name "Your Name"
```

Creates the platform admin — the account that runs the service. The password is read from `PLATFORM_ADMIN_PASSWORD` if set, otherwise asked for twice without echoing; it must have at least 8 characters, a letter and a digit. Nothing else is created: no company, no demo logins.

Then sign in at `/login` with that account, open **System Admin → Onboard Company**, and create your company. Its Owner is sent an invitation and chooses their own password. Each new company starts with a Main Warehouse, its numbering series, and the default Settings → Lists (payment terms, delivery terms, supplier types), all editable.

### Demo data (development only)

```bash
python -m app.db.seed --demo
```

Adds one demo tenant — **Acme Trading Co** — and a demo platform admin, with well-known passwords:

```
owner:           owner@acme-demo.test / Demo@12345
platform admin:  platform-admin@inventoryai.test / Platform@12345
```

The test suites in `tests/` use these accounts. Never run `--demo` on a database other people can reach — anyone who has read this file can sign in.

### Reference data only

```bash
python -m app.db.seed
```

## Run

```bash
uvicorn app.main:app --reload
```

- `http://localhost:8000/health` — DB connectivity, current migration, extensions, RLS table count
- `http://localhost:8000/docs` — interactive docs for all 29 endpoints

On boot the app verifies that `APP_DATABASE_URL`'s role cannot bypass RLS, and refuses to start if it can, naming the role and the fix.

## Verify tenant isolation

```bash
python -m scripts.verify_rls
```

Prints which role each connection uses, then creates two throwaway tenants, proves neither can see the other's rows, proves a cross-tenant write is refused, and cleans up. Worth running after every migration. Exit code 0 only if all 10 checks pass.

## What exists

| Area | Endpoints |
|---|---|
| Auth | login, refresh (rotating), logout |
| Masters | products, variants, suppliers, godowns, categories, brands, UoMs — list/create/get/update/delete each |
| Company | profile and settings (read for all, edit for Owner) |
| Users | list, get, update role & godown scope, remove |
| Invitations | invite, list, resend, revoke, accept (accept is unauthenticated by design) |

Every mutation, every login (success and failure) and every permission denial writes an `audit_logs` row in the same transaction as the change.

## Not built yet

Godown-scope enforcement (scope is assignable and rides in the token, but no endpoint filters by it yet), email delivery for invitations (the token comes back in the API response for now — fine for development, must not ship), account lockout after repeated failed logins, and every transactional module: RFQ, purchase orders, GRN, inventory postings, the AI document pipeline, alerts and reports.

## Object storage (S3)

**Local development uses Floci with persistent storage**, so uploaded documents
survive Docker and PC restarts:

```bash
floci start --persist "C:/Users/<you>/AppData/Local/floci/data"
docker update --restart unless-stopped floci
```

`AWS_ENDPOINT_URL=http://localhost:4566` in `.env` (4566 is the S3 API; 4500 is
Floci's web console). Without `--persist`, Floci keeps files in memory and loses
them on restart while their database rows remain. In development the API
recreates a missing bucket on startup, but it cannot bring lost files back.


Uploaded documents live in a private S3 bucket and nowhere else — there is
no local-disk fallback, and the API refuses to start if the bucket is not
reachable. Full write-up in `docs/s3-storage-phase-state.md`.

### Local development (Floci / LocalStack)

```bash
# with the endpoint running on :4566
aws --endpoint-url http://localhost.floci.io:4566 s3 mb s3://inventoryai-documents

# Not on by default on a freshly created bucket, and it is the first thing
# verify_s3.py checks — without it "public access is blocked" fails.
aws --endpoint-url http://localhost.floci.io:4566 s3api put-public-access-block \
  --bucket inventoryai-documents \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

The `.env` block is already filled in for that endpoint. Then prove it
before starting the API:

```bash
cd backend
.venv\Scripts\activate
python -m scripts.verify_s3
```

It writes and deletes one object under `co/_verify/`, and checks
encryption, the pre-signed link, key shape and the failure paths. Exit code
0 means uploads will work.

Two checks — that a tampered or unsigned link is rejected — print `skip`
rather than `ok` against a local emulator: LocalStack Community / Floci
does not enforce SigV4 signatures on presigned GETs, so a request that
should be refused gets served anyway. That is the emulator, not the app —
boto3 signs the URL the same way regardless of what answers on the other
end. Run `verify_s3` against a real AWS bucket at least once before
treating BR-DOC-03's signing as proven.

### Real AWS

Create the bucket with **Block Public Access on all four settings**,
default encryption, and **versioning** — versioning is what makes a lost
object recoverable rather than terminal. Then:

```dotenv
S3_BUCKET=your-bucket
AWS_REGION=ap-south-1
AWS_ENDPOINT_URL=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
```

Leave the two key variables **blank** so the instance or task IAM role is
used. The role needs `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` and
`s3:ListBucket` on that bucket only.

### Housekeeping

```bash
python -m scripts.s3_orphans              # report
python -m scripts.s3_orphans --delete     # remove orphan objects > 24h old
```

Reconciles the bucket against the `documents` table. Exits non-zero if any
row has lost its bytes, so a scheduled run can alert on it.

## AI models (optional)

Spreadsheet column mapping — RFQ import and AI Documents — can use a model
for headings the built-in rules don't know. Everything a model suggests is
shown for a person to confirm, and if the provider is down the app falls
back to rules plus manual mapping; nothing fails.

Local, free, no key — [Ollama](https://ollama.com):

```bash
ollama pull nomic-embed-text
ollama pull llama3.2
```

```
AI_PROVIDER=ollama              # none | ollama | openai (any OpenAI-compatible API)
AI_BASE_URL=http://localhost:11434
AI_API_KEY=                     # needed for hosted APIs only
AI_MODEL_SMALL=llama3.2:latest
AI_EMBEDDING_MODEL=nomic-embed-text
AI_EMBEDDING_DIMENSIONS=768
AI_TIMEOUT_SECONDS=60
```

How a column gets mapped, in order (`app/modules/ai/column_assist.py`):

1. A layout already imported and confirmed — reused exactly.
2. Heading synonyms (Particulars, Qty., Per, UoM, Rate…).
3. **The column's values** — units, serial numbers, codes, "10 Nos",
   long item text, the numbers next to the unit column. Instant and the
   most reliable signal.
4. **Embeddings** of the heading, only to choose between fields the values
   already allow ("Count" vs "Budget").
5. **The language model**, only while a required field is still missing,
   and its answer is dropped unless the column's values fit it. On a CPU a
   3B model takes ~15–30 s and is often wrong on its own; the check is what
   makes it safe.

### Product matching by meaning

With an embedding model configured, supplier lines are also matched to your
catalogue by meaning ("circuit breaker 32 amp 2 pole" → *Havells MCB 32A
Double Pole*), as suggestions a person confirms — never auto-accepted.

* Vectors live in `variant_embeddings.embedding` — `vector(768)` with an HNSW
  cosine index (migration `d4e9f2a6b8c1`). `AI_EMBEDDING_DIMENSIONS` must
  match the column; the service refuses to write a vector of another size.
* The index keeps itself fresh: a product whose name, brand, pack or
  category changed is re-embedded before the next document is matched.
* After changing `AI_EMBEDDING_MODEL`, re-index everything — Settings →
  *Product matching by meaning* → **Re-index all**, or:

  ```bash
  python -m scripts.rebuild_embeddings --all
  ```

* `AI_EMBEDDING_FLOOR` (default 0.60) is the similarity below which nothing
  is suggested; measured with nomic-embed-text, right answers scored
  0.67–0.83 and unrelated items at most 0.54.
* The language model is not run per line (15–30 s per call on a CPU).

## Browser tests

```bash
cd tests
npm i playwright && npx playwright install chromium   # once
set TEST_DATABASE_URL=postgresql://<owner>:<pw>@localhost:5432/inventoryai   # browser_auth.js only
node browser_receiving.js
```

`PW_CHROMIUM` points them at a specific Chromium if needed.

## Email

Development sends real SMTP to **Mailpit**, a local mail catcher, so invitations,
password resets and supplier-portal links can be opened and clicked:

```bash
docker run -d --name mailpit --restart unless-stopped -p 1025:1025 -p 8025:8025 axllent/mailpit
```

Inbox: http://localhost:8025. `.env` has `EMAIL_PROVIDER=smtp`, `SMTP_HOST=localhost`,
`SMTP_PORT=1025`, `SMTP_USE_TLS=false`. For real delivery put your provider there
(the `.env` block lists Gmail, Zoho, Brevo and SES settings), or set a company's own
server under Settings → Email, which takes priority.

## OCR (scanned images and image-only PDFs)

```bash
winget install -e --id UB-Mannheim.TesseractOCR
```

Hindi isn't in the installer; keep language files in a user folder with `eng`, `osd`
and `hin.traineddata` from https://github.com/tesseract-ocr/tessdata_fast, then:

```
OCR_PROVIDER=tesseract
OCR_TESSERACT_CMD=C:/Program Files/Tesseract-OCR/tesseract.exe
OCR_TESSDATA_DIR=C:/Users/<you>/AppData/Local/tessdata
OCR_LANGUAGES=eng+hin
```

Pages are rendered at 300 dpi, words are read with their positions, and the item
table is rebuilt row by row onto the heading's columns (`app/modules/ai/ocr.py`), so
a scan goes through the same column mapping and product matching as a spreadsheet.
OCR can misread a digit on a poor scan; every OCR'd document lands on the review
screen for that reason.

## Supplier Portal

Suppliers sign in at `/supplier-portal/login` with their own account
(`supplier_portal_accounts`, migration `f3c6a8e2b4d7`) — never a staff login. A
company gives a contact access from the supplier's page (**Supplier Portal access →
Give access**); they get an email to set a password. One login covers every company
that gives them access. They see, per company, RFQs sent to them, their quotations
and POs once sent — read-only. Revoking takes effect immediately. "Send password
link" on the same card is how a supplier who forgot their password gets back in.
