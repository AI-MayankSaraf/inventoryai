# InventoryAI tests

End-to-end tests that drive the running app: the backend on `:8000`, the
frontend on `:3000`, Postgres, S3 (Floci), and for the AI tests Ollama and
Tesseract. They create their own records (suffixed with a random tag), so they
can be run repeatedly against the demo company.

## One-time setup

```bash
cd tests
npm install
npx playwright install chromium
```

The Python tests use the backend's virtualenv (they need `openpyxl` and
`Pillow`), run from the repository root.

## What's here

| Test | Covers |
|---|---|
| `api_business_flow.py` | The whole purchase cycle: RFQ, two quotations, comparison, PO, proforma, GRN, stock, 3-way-matched invoice and a variance, payment, return, transfer, write-off and reversal, stock guards, low-stock alert, reports, audit trail |
| `api_endpoint_sweep.py` | Every GET endpoint, list and detail, as the tenant owner and the platform admin |
| `api_supplier_portal.py` | Supplier Portal: grant, emailed set-password link, sign-in, what a supplier can see, isolation from staff APIs, a second company, revoke, lockout |
| `api_ai_features.py` | RFQ import mapping, AI column assist, product embedding index, matching by meaning, the assistant |
| `api_ocr.py` | Scanned PNG and image-only PDF quotations read by OCR into the review screen |
| `browser_auth.js` | Sign-in, password reset, invitations, email settings (needs `TEST_DATABASE_URL`) |
| `browser_receiving.js` | Draft GRN edit, confirm, postings and variances, reversal |
| `browser_supplier_catalogue.js` | Supplier catalogue and aliases |
| `browser_roles.js` | Custom roles |
| `browser_ai_documents.js` | Upload a quotation, review, approve into a quotation |
| `browser_platform.js` | Platform console |
| `browser_supplier_portal.js` | The Supplier Portal as staff and supplier use it |
| `browser_godowns_numbering_register.js` | Godown in-charge and capacity, document-number previews, purchase register |
| `browser_screen_walk.js` | Opens every screen and reports any API or console error |

## Running

```bash
# from the repository root
backend/.venv/Scripts/python.exe tests/api_business_flow.py
node tests/browser_screen_walk.js
```

Every test prints `ok` / `FAIL` per check and a `N passed, M failed` line.

## Settings

All optional; the defaults match a local development install.

| Variable | Default |
|---|---|
| `APP_URL` (or the first argument of a browser test) | `http://localhost:3000` |
| `API_URL` | `http://127.0.0.1:8000` |
| `TEST_PLATFORM_DATABASE_URL` | `postgresql://inventoryai_platform:inventoryai_platform_dev@localhost/inventoryai` |
| `TEST_DATABASE_URL` (`browser_auth.js` only) | the owner connection from `backend/.env`, without `+asyncpg` |
| `PW_CHROMIUM` | Playwright's own Chromium |

Screenshots taken on failure go to the system temp folder.
