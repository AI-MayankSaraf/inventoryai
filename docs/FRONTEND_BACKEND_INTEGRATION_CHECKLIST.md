# Frontend → Backend Integration Checklist

**Purpose:** what the backend must provide for this frontend to work against it, and what changes in the frontend when it does.

The frontend calls `src/lib/api/*.api.ts` and nothing else. Each module is written as if it were HTTP. **Integration means replacing the body of those functions with `fetch` — the signatures, the shapes and every screen above them stay exactly as they are.**

---

## 1. The seam

| File | Replace with | Screens affected if the contract changes |
|---|---|---|
| `lib/api/client.ts` | real `fetch` + auth header + error mapping | all |
| `lib/api/auth.api.ts` | `POST /auth/login`, `GET /auth/me`, impersonation | login, shell, every permission check |
| `lib/api/catalog.api.ts` | products, variants, categories, brands, UoMs | Products, forms with a product picker |
| `lib/api/suppliers.api.ts` | suppliers, contacts, supplier-product aliases | Suppliers, AI review, comparison |
| `lib/api/inventory.api.ts` | stock, ledger, transfers, adjustments | Inventory, Dashboard, Products |
| `lib/api/procurement.api.ts` | RFQ, quotations, comparison, PO, proforma | all procurement screens |
| `lib/api/receiving.api.ts` | GRN lifecycle | Goods Receipt |
| `lib/api/invoices.api.ts` | supplier invoices, three-way match, returns | Payables |
| `lib/api/documents.api.ts` | uploads, AI jobs, extractions, schema mappings, assistant | AI Documents, Schema Mappings, Assistant |
| `lib/api/ops.api.ts` | alerts, audit, dashboard, reports | Dashboard, Alerts, Audit, Reports |
| `lib/api/admin.api.ts` | users, roles, godowns, settings, tenants | Administration |

---

## 2. Cross-cutting contracts

### 2.1 List endpoints

Every collection endpoint must accept `ListParams` and return `ListResponse<T>`:

```ts
ListParams  { q?, filters?: Record<string,string>, sort?: "field" | "-field",
              limit?, cursor?, dateFrom?, dateTo? }
ListResponse{ items: T[], nextCursor: string | null, total: number,
              facets?: Record<string, {value,label,count}[]> }
```

`cursor` is opaque to the client. `facets` drives the filter dropdowns — omit it and the filters still work, they just lose their counts.

### 2.2 Errors

Non-2xx must carry:

```json
{ "error": "human sentence", "code": "BR-GRN-03",
  "fieldErrors": [{ "field": "lines.2.quantity", "message": "..." }] }
```

`code` is the rule id from `06_BUSINESS_RULES.md`. `field` uses the dotted path of the request body — forms render the message under exactly that input. **53 business-rule codes are already referenced by name in the frontend** (`BR-INV-*`, `BR-GRN-*`, `BR-PO-*`, `BR-AI-*`, `BR-AUTH-*`, `BR-MD-*`, `BR-RET-*`, `BR-VAR-*`, `BR-QT-*`, `BR-RFQ-*`, `BR-CMP-*`, `BR-DOC-*`, `BR-ALT-*`, `BR-FIN-*`); the UI shows the server's message verbatim, so the wording is the backend's to own.

### 2.3 Money

The backend computes and returns every financial figure. The frontend must never be the source of a total.

Each financial document returns: `subtotal`, `discountAmount`, `taxableValue`, `cgstAmount`, `sgstAmount`, `igstAmount`, `cessAmount`, `freightAmount`, `otherCharges`, `roundOff`, `totalAmount`, `isInterState`. Detail endpoints also return `taxRows` (the GST breakdown by rate).

Order of operations must match `lib/domain/money.ts`: line net → line tax (per line, not on the document subtotal) → sum → split by place of supply → round the grand total. `isInterState` is derived from supplier state vs place of supply and returned, never accepted from the client.

Values travel as `NUMERIC` strings in the real API; the frontend's `Money = number` becomes `string` and `money.ts` becomes a formatter. That is a one-file change.

### 2.4 State transitions

Every detail endpoint returns `allowedActions` — the transitions legal from the current status. The UI renders only those. An illegal transition must return HTTP 409 with `code: "INVALID_STATE_TRANSITION"`.

The eight tables are in `lib/domain/state-machines.ts` and must be mirrored server-side exactly.

### 2.5 Permissions

**The frontend's permission checks are presentation only.** Every endpoint must enforce the same permission independently — the matrix is `07_RBAC_MATRIX.md`, and the ~90 codes are in `types/master.ts › PermissionCode`.

Also enforce server-side:
- **godown scoping** — a user scoped to one godown must not receive another's rows (BR-AUTH-12);
- **value thresholds** — `po.approve_high_value` above `settings.requirePoApprovalAbove` (BR-PO-03);
- **last-owner protection** (BR-AUTH-04).

`GET /auth/me` returns the resolved `SessionUser`: user, company name, role name and the flattened permission list.

---

## 3. What the backend must own that the mock only pretends to

| Concern | Mock behaviour | Required backend behaviour |
|---|---|---|
| **Document numbers** | consumes an in-memory sequence | a real sequence per tenant × doc type × financial year, allocated transactionally. Gaps are normal and the UI already says so |
| **Ledger + balance** | appends and refolds in one function | **one database transaction**: insert the ledger rows and update `stock_balances` together, or neither |
| **GRN confirmation** | one function does all four steps | one transaction: post stock, advance PO lines and header, write variances, raise alerts |
| **Negative stock** | checked against the cached balance | `SELECT … FOR UPDATE` on the balance row, or a check constraint — concurrent issues must not both pass |
| **Period lock** | compares a date | reject on the server; the client check is a courtesy |
| **Duplicate documents** | hashes filename + size | SHA-256 of the bytes, unique per tenant (BR-DOC-02) |
| **AI extraction** | stage progress on a timer, deterministic local matching | real pipeline. The frontend already labels its own version as simulated — remove that wording when it is real |
| **Match ladder** | runs `exact_sku`, `supplier_alias`, `barcode`, `normalised_rule`, `trigram` in the browser | add `embedding` and `llm`. The frontend renders whichever rung the server reports |
| **Three-way match** | computed on read | compute server-side and persist the variances |
| **Audit log** | written by each API function | a database trigger plus an application actor, so it cannot be skipped |
| **Outbound email** | rows in `outboundMessages` | a real sender, with the same row as the delivery record |
| **Session** | a user id in `localStorage` | a real token; `authApi` becomes login/refresh/logout |

---

## 4. Endpoint inventory

Grouped as the frontend calls them. Names follow `04_API_SPECIFICATION.md`.

**Auth** — `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `POST /platform/impersonation`, `DELETE /platform/impersonation`

**Master data** — `GET|POST /products`, `GET|PATCH /products/{variantId}`, `POST /products/{variantId}/deactivate`, `GET /products/{variantId}/usage`, `GET /categories`, `GET /brands`, `GET /uoms`, `GET /product-uom-conversions`, `GET|POST /godowns`, `GET|PATCH /godowns/{id}`, `GET /godowns/{id}/usage`, `GET|POST /suppliers`, `GET|PATCH /suppliers/{id}`, `GET /suppliers/{id}/usage`, `POST /supplier-products`, `GET /suppliers/{id}/price-history`

**Inventory** — `GET /stock`, `GET /stock/kpis`, `GET /stock/by-godown/{variantId}`, `GET /stock/low`, `GET /inventory-transactions`, `POST /inventory-transactions`, `POST /inventory-transactions/{id}/reverse`, `GET|POST /stock-transfers`, `GET /batches`, `GET /stock/verify`

**Procurement** — `GET|POST /rfqs`, `GET /rfqs/{id}`, `POST /rfqs/{id}/send`, `POST /rfqs/{id}/cancel`, `DELETE /rfqs/{id}`, `GET|POST /quotations`, `GET /quotations/{id}`, `POST /quotations/{id}/status`, `GET /rfqs/{id}/comparison`, `POST /comparisons/{id}/lines/{lineId}/select`, `POST /comparisons/{id}/convert`, `GET|POST /purchase-orders`, `GET /purchase-orders/{id}`, `POST /purchase-orders/{id}/status`, `GET /proformas`, `GET /proformas/{id}`, `POST /proformas/{id}/status`, `POST /proformas/{id}/query`, `GET /variances`, `POST /variances/{id}/resolve`

**Receiving** — `GET|POST /goods-receipts`, `GET|PATCH /goods-receipts/{id}`, `GET /purchase-orders/{id}/receipt-lines`, `POST /goods-receipts/{id}/confirm`, `POST /goods-receipts/{id}/reverse`, `POST /goods-receipts/{id}/cancel`, `GET /goods-receipts/{id}/returnable-lines`

**Payables** — `GET|POST /supplier-invoices`, `GET /supplier-invoices/{id}`, `POST /supplier-invoices/{id}/match`, `POST /supplier-invoices/{id}/status`, `POST /supplier-invoices/{id}/payments`, `GET|POST /purchase-returns`, `GET /purchase-returns/{id}`, `POST /purchase-returns/{id}/status`

**Documents & AI** — `GET|POST /documents`, `GET /documents/{id}`, `GET /documents/{id}/status`, `POST /documents/{id}/retry`, `GET /documents/{id}/extraction`, `POST /extracted-lines/{id}/match`, `POST /extracted-lines/{id}/skip`, `PATCH /extracted-fields/{id}`, `POST /documents/{id}/approve`, `POST /documents/{id}/reject`, `GET /schema-mappings`, `GET /schema-mappings/{id}`, `PATCH /schema-mapping-fields/{id}`, `POST /schema-mappings/{id}/confirm`, `GET /canonical-fields`, `POST /assistant/ask`

**Ops** — `GET /alerts`, `GET /alerts/summary`, `PATCH /alerts/{id}`, `POST /alerts/read-all`, `GET|PATCH /alert-rules`, `GET /audit-logs`, `GET /audit-logs/{entityType}/{entityId}`, `GET /dashboard`, `GET /reports`, `GET /reports/{key}`

**Admin** — `GET /users`, `PATCH /users/{id}`, `DELETE /users/{id}`, `GET|POST /invitations`, `POST /invitations/{id}/resend`, `DELETE /invitations/{id}`, `GET|POST /roles`, `PATCH /roles/{id}`, `GET|PATCH /company`, `GET|PATCH /company/settings`, `POST /company/settings/close-period`, `GET /document-sequences`, `POST /document-sequences/{docType}/next`, `GET /platform/companies`, `PATCH /platform/companies/{id}`

---

## 5. Integration order

1. **Auth + `/auth/me`** — nothing else is meaningful until the session is real.
2. **Master data reads** (products, suppliers, godowns, categories, brands, UoMs) — read-only, low risk, exercises `ListParams` end to end.
3. **Inventory reads**, then `POST /inventory-transactions` — this is where the ledger-and-balance transaction gets proven.
4. **Procurement reads**, then PO create and status transitions.
5. **GRN confirm** — the highest-value integration and the one most worth testing hard: it must be atomic across stock, PO progress, variances and alerts.
6. **Payables**, then **documents/AI**, then **admin and reports**.

At each step, delete the corresponding mock and keep the module's exported signature. The screens do not change.

---

## 6. Pre-integration checks

- [ ] `GET /auth/me` returns `SessionUser` with a flattened permission list
- [ ] Every list endpoint accepts `ListParams` and returns `ListResponse`
- [ ] Errors carry `code` and `fieldErrors` with dotted field paths
- [ ] Every financial document returns the full money block plus `isInterState`
- [ ] Every detail endpoint returns `allowedActions`
- [ ] Ledger write and balance update share one transaction
- [ ] GRN confirm is atomic across all four effects
- [ ] Document numbers come from a server sequence
- [ ] Every endpoint enforces its permission **and** godown scope independently of the UI
- [ ] Audit rows are written by the server, not the client
