# Phase state — Security Phase 1: audit findings H1–H5 + Secrets Manager (3 Oct 2026)

Source: *InventoryAI — Security Audit* (3 Oct 2026). This phase fixes the five
High findings and moves every password and key out of `backend/.env` into
Secrets Manager (Floci locally, AWS later). The Medium (M1–M9) and Low
findings are **not** part of this phase.

## Result

| ID | Finding | Fix | Proven by |
| --- | --- | --- | --- |
| H1 | Next.js 16.3.5 has a critical RCE advisory (CVE-2026-94545) | `next` pinned to exactly **16.3.8** in `package.json` and `package-lock.json` | `npm audit --omit=dev` → 0 vulnerabilities |
| H2 | Staff / GM / Viewer could list and download every quotation, proforma and invoice via `/ai/documents` | Each document type needs the permission of the record it feeds (table below). Applied to the list, every `/ai/documents/{id}/…` endpoint and `/ai/sources`. Out-of-scope id → **404** | `e2e_security_audit` H2.01–H2.07 |
| H3 | Godown-scoped users could read every godown's GRNs, POs, alerts, dashboard figures | `procurement_godown_filter` on GRN list/detail/postings/variances, PO list/detail, alerts (list, badge, read, status), dashboard counts, GRN attachments. Dashboard activity feed now needs `audit.view` | `e2e_security_audit` H3.00–H3.11 |
| H4 | `comparison.create` alone could create POs via `/comparisons/{id}/convert` | Endpoint now needs **both** `comparison.convert` and `po.create` (`require_all_permissions`) | `e2e_security_audit` H4.01–H4.04 |
| H5 | Backend signed tokens with the public key `dev-secret-change-me` | API refuses to start — in **every** environment — with a blank/default/short `JWT_SECRET` or a missing/equal `SECRETS_KEY`. Escape hatch `ALLOW_DEV_SECRET=true` works in development only. Secrets moved to Secrets Manager | `verify_security_config` S01–S08, M01–M05; a token forged with the old key → 401 |

### H2 — document type → permission

| Document type | Needs |
| --- | --- |
| supplier_quotation, rate_list, price_revision | `quotation.view` |
| proforma_invoice | `proforma.view` |
| tax_invoice | `invoice.view` |
| purchase_order | `po.view` |
| delivery_challan | `grn.view` |
| other / unrecognised / not yet classified | `ai.view` |
| anything the user uploaded themselves | always visible to the uploader |

### H3 — one decision to note

For GRNs, POs, alerts and the dashboard, `inventory.view_all` does **not**
widen the scope. That permission means "view stock in all godowns"
(07_RBAC_MATRIX.md), not "see every godown's receipts and purchase prices".
Only an *All godowns* scope sees everything. Stock screens are unchanged
(there `inventory.view_all` still overrides, per BR-AUTH-12). Company-wide
alerts (no godown) and RFQs with no delivery godown stay visible to scoped
users.

## Secrets Manager

| | Before | After |
| --- | --- | --- |
| DB URLs (3), JWT_SECRET, SECRETS_KEY, SMTP_USERNAME/PASSWORD, AI_API_KEY | plain text in `backend/.env` | one secret `inventoryai/backend` (JSON) in Floci on :4566 |
| `.env` | holds the values | holds `SECRETS_MANAGER_SECRET_ID=inventoryai/backend` and blanks |
| Secret unreachable | n/a | API refuses to start (fail closed, same rule as S3) |
| Precedence | env vars > `.env` | env vars > **secret** > `.env` > defaults |

`AWS_ACCESS_KEY_ID=test` / `AWS_SECRET_ACCESS_KEY=test` stay in `.env`:
they are Floci's dummy credentials, not secrets. On AWS they are blank and
the server's IAM role needs `secretsmanager:GetSecretValue` on this secret.

Tool: `python -m scripts.secrets_manager push | verify | strip-env | show | reveal KEY`.
`push` generates a strong `JWT_SECRET` and a separate `SECRETS_KEY`, and
re-encrypts stored company SMTP passwords from the old key to the new one in
the same database transaction (rolled back, and the previous secret restored,
if anything fails). `strip-env` refuses to run unless the secret is complete,
strong and matches `.env`.

## Files changed

Backend: `app/core/config.py`, `app/core/deps.py`, `app/core/secrets_manager.py` (new),
`app/main.py`, `app/modules/ai/{router,query_service,attachments}.py`,
`app/modules/procurement/{router,grn_service,po_service}.py`,
`app/modules/ops/{alert_service,dashboard_service}.py`,
`scripts/secrets_manager.py` (new), `scripts/e2e_security_audit.py` (new),
`scripts/verify_security_config.py`, `.env.example`, `BACKEND-SETUP.md`.
Frontend: `package.json`, `package-lock.json`. Tests: `tests/test_stack.py`
(reads DB URLs from the secret once `.env` is stripped). No migration.

## Verification (sandbox copy of the project, 3 Oct 2026)

Run on Postgres 16 + pgvector, a local S3/Secrets Manager emulator (moto),
the real migrations and `scripts.sample_data`:

| Suite | Before fix | After fix |
| --- | --- | --- |
| e2e_security_audit (new) | 12 passed, **16 failed** (every finding reproduced) | **29 / 29** |
| verify_security_config | 31 / 32 | 40 / 40 |
| verify_rls, verify_s3 | pass | pass (27/27) |
| e2e_auth / roles / platform / receiving | — | 60 / 53 / 85 / 45 |
| e2e_supplier_catalogue / ai_documents / multi_company / rfq_import / worker | — | 98 / 107 / 65 / 34 / 13 |
| secrets_manager push → verify → strip-env → API start | — | pass, 1 SMTP password re-encrypted |

**Not yet run on Sharad's PC** (the PC shell was unavailable this session):
the Floci Secrets Manager flow, `npm install` + `next build` on 16.3.8, and
the browser suites.

## Steps to finish on the PC

```bash
cd backend
.venv\Scripts\activate
python -m scripts.secrets_manager push
python -m scripts.secrets_manager verify
docker restart floci && python -m scripts.secrets_manager verify   # survives restart?
python -m scripts.secrets_manager strip-env
uvicorn app.main:app --reload --host 127.0.0.1
python -m scripts.e2e_security_audit      # needs sample data
cd ..\frontend && npm install && npm audit --omit=dev && npm run build
```

Everyone signs in again once (new JWT key).

## Still open (next phases)

M1–M9 and the Low findings from the audit, notably M8 (compose publishes
ports on all interfaces), M4 (security headers) and M2 (audit log can be
altered). Not started.
