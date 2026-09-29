# 04 — API SPECIFICATION (FastAPI)

Every endpoint below exists because a screen, button or workflow step in the audited UI needs it, or because the RFQ→Invoice→Inventory loop cannot close without it. Endpoints in the second category are marked **[NO UI YET]**.

Companion: `05_UI_API_MAPPING.md` (screen → endpoint), `06_BUSINESS_RULES.md` (validation), `07_RBAC_MATRIX.md` (permissions).

---

## 1. Conventions

| Concern | Decision |
|---|---|
| Base | `/api/v1` — matches the frontend's `API_BASE = NEXT_PUBLIC_API_BASE_URL ?? "/api"` |
| Auth | `Authorization: Bearer <JWT>`. Access token 15 min; refresh token 30 days in an httpOnly cookie ("Keep me signed in"). JWT claims: `sub`, `company_id`, `role`, `permissions[]`, `godown_scope`, `impersonated_by?`, `jti`, `exp` |
| Tenant | **Never** from a request parameter. Always from `company_id` in the JWT → `SET LOCAL app.current_company_id` |
| Content | `application/json`; uploads `multipart/form-data` |
| IDs | UUIDs in paths. Business numbers are supported as an alternative lookup on read endpoints via `?number=PO-2026-00123` (the current UI routes by number) |
| Pagination | Keyset: `?limit=50&cursor=<opaque>`. Response envelope `{ "items": [...], "next_cursor": "...", "total": 1248 }`. `total` is an estimate above 10 000 rows |
| Filtering | Explicit query params per resource (`status`, `supplier_id`, `godown_id`, `category_id`, `date_from`, `date_to`) plus `q` for full-text/trigram search |
| Sorting | `?sort=-created_at` (leading `-` = desc); whitelisted fields only |
| Errors | RFC 9457 problem+json: `{ "type", "title", "status", "detail", "code", "errors": [{"field","message"}], "request_id" }` |
| Idempotency | `Idempotency-Key` header **required** on all POSTs that create documents or post inventory. Stored 24 h; a repeat returns the original response |
| Concurrency | `If-Match: <row_version>` on PUT/PATCH of business documents → `409 STALE_RECORD` on mismatch. This replaces the prototype's last-write-wins |
| Money | Sent and received as strings (`"341720.00"`) to avoid float drift |
| Dates | `date` as `YYYY-MM-DD`; instants as RFC 3339 with offset |
| Async | Long work (document processing, exports, bulk import) returns `202 Accepted` + `{"job_id"}`; progress via `GET /jobs/{id}` and/or SSE `GET /jobs/{id}/stream` |
| Rate limits | Per company + per user; stricter on `/documents/upload` and `/ai/*` |
| Audit | Every non-GET writes `audit_logs` with the request id |

### Standard error codes

| HTTP | `code` | Meaning |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Field-level failures in `errors[]` |
| 401 | `UNAUTHENTICATED` / `TOKEN_EXPIRED` | |
| 403 | `FORBIDDEN` / `GODOWN_OUT_OF_SCOPE` / `TENANT_MISMATCH` | |
| 404 | `NOT_FOUND` | Also returned instead of 403 for other tenants' ids |
| 409 | `STALE_RECORD` / `DUPLICATE` / `RECORD_IN_USE` / `INVALID_STATE_TRANSITION` | |
| 422 | `BUSINESS_RULE_VIOLATION` | Rule id in `detail`, e.g. `BR-GRN-03` |
| 429 | `RATE_LIMITED` | |
| 503 | `AI_PROVIDER_UNAVAILABLE` | Extraction degraded to manual |

---

## 2. Complete endpoint inventory

### 2.1 Auth & session

| Method | Endpoint | Purpose | Permission | Sync | UI origin |
|---|---|---|---|---|---|
| POST | `/auth/login` | Sign in with **username or email** | public | S | Login form |
| POST | `/auth/refresh` | Rotate access token | public+cookie | S | "Keep me signed in" |
| POST | `/auth/logout` | Revoke refresh token | auth | S | Sign out menu |
| GET | `/auth/me` | Current user + role + permissions + godown scope | auth | S | AppShell, role-gated nav |
| POST | `/auth/forgot-password` | Request reset | public | A | "Forgot password?" (dead link today) |
| POST | `/auth/reset-password` | Complete reset | public | S | — |
| POST | `/auth/change-password` | Change own password | auth | S | Settings/profile |
| GET | `/invitations/{id}` | Validate an invite link | public | S | `/accept-invite/[id]` |
| POST | `/invitations/{id}/accept` | Set password, activate membership | public | S | Accept-invite form |

### 2.2 Platform administration (Super Admin only)

| Method | Endpoint | Purpose | Sync | UI origin |
|---|---|---|---|---|
| GET | `/platform/companies` | List all tenants + filters | S | System Admin → Companies |
| POST | `/platform/companies` | Onboard a tenant | S | Add Company dialog |
| GET | `/platform/companies/{id}` | Tenant detail | S | — |
| PATCH | `/platform/companies/{id}` | Edit tenant | S | — |
| POST | `/platform/companies/{id}/suspend` | Suspend | S | Suspend button |
| POST | `/platform/companies/{id}/reactivate` | Reactivate | S | Reactivate button |
| GET | `/platform/users` | All users across tenants | S | System Admin → All Users |
| POST | `/platform/impersonate` | Start impersonation, returns scoped token | S | Impersonate button |
| POST | `/platform/impersonate/stop` | End impersonation | S | "Return to Super Admin" banner |
| GET | `/platform/activity` | Platform-wide audit feed | S | Platform Activity tab |
| GET | `/platform/kpis` | Companies/active/users/suspended | S | System Admin KPI cards |

### 2.3 Company, settings, users

| Method | Endpoint | Purpose | Permission | UI origin |
|---|---|---|---|---|
| GET | `/company` | Own tenant profile (buyer letterhead) | `company.view` | Print headers, Settings |
| PATCH | `/company` | Update business details/GSTIN/PAN/address | `company.manage` | Settings → Business Details |
| GET | `/company/settings` | All settings | `company.view` | Settings page |
| PUT | `/company/settings` | Save settings | `company.manage` | **Save Settings (inert today)** |
| GET | `/company/sequences` | Numbering config | `company.manage` | Settings → Document Numbering |
| PUT | `/company/sequences` | Update prefixes/padding | `company.manage` | same |
| GET | `/users` | Team list + filters | `user.view` | Users page |
| POST | `/users` | Create user directly (no invite) | `user.manage` | [NO UI YET] |
| GET | `/users/{id}` | User detail | `user.view` | — |
| PATCH | `/users/{id}` | Change role/godown scope/status | `user.manage` | [NO UI YET — UI can only remove] |
| DELETE | `/users/{id}` | Soft-remove member | `user.manage` | Remove button |
| GET | `/invitations` | Pending invitations | `user.view` | Pending Invitations panel |
| POST | `/invitations` | Invite a user | `user.manage` | Invite User dialog |
| POST | `/invitations/{id}/resend` | Resend (increments `resend_count`) | `user.manage` | Resend button |
| DELETE | `/invitations/{id}` | Revoke | `user.manage` | Revoke button |

### 2.4 Master data

| Method | Endpoint | Purpose | UI origin |
|---|---|---|---|
| GET/POST | `/categories` · `/categories/{id}` (GET/PATCH/DELETE) | Category tree | Product filters & form |
| GET/POST | `/brands` · `/brands/{id}` (GET/PATCH/DELETE) | Brands | Product filters & form |
| GET | `/uoms` | Units list | Every line-item form |
| POST/PATCH/DELETE | `/uoms` · `/uoms/{id}` | Manage units | [NO UI YET] |
| GET | `/godowns` | Godown cards + computed SKUs/value/capacity | Godowns, filters |
| POST | `/godowns` | Create | **"Add Godown" (inert today)** |
| GET/PATCH/DELETE | `/godowns/{id}` | Manage | [NO UI YET] |

### 2.5 Products

| Method | Endpoint | Purpose | UI origin |
|---|---|---|---|
| GET | `/products` | Paged list; `q`, `category_id`, `brand_id`, `stock_status`, `godown_id`, `sort` | Products screen |
| POST | `/products` | Create product + first variant | Add Product dialog |
| GET | `/products/{id}` | Detail with variants | — |
| GET | `/products/by-sku/{sku}` | Detail by SKU | `/products/[sku]` route |
| PATCH | `/products/{id}` | Update catalogue fields | Edit Product dialog |
| DELETE | `/products/{id}` | Soft delete | Delete action |
| GET | `/products/{id}/variants` · POST | Variant management | [NO UI YET — needed for variants] |
| PATCH/DELETE | `/variants/{id}` | Variant edit/delete | maps to today's product edit |
| GET | `/variants/{id}/stock` | Per-godown stock + batches | Product detail stock split |
| GET | `/variants/{id}/transactions` | Ledger for one SKU | Product detail history |
| GET | `/variants/{id}/suppliers` | Supplier aliases & prices | [NO UI YET] |
| GET/POST | `/variants/{id}/uom-conversions` · DELETE `/uom-conversions/{id}` | Box→Nos factors | [NO UI YET — required by I10] |
| GET/POST | `/products/{id}/images` · DELETE `/product-images/{id}` | Product photos | **"Images & Documents" placeholder** |
| GET/PUT | `/variants/{id}/godown-policies` | Per-godown reorder points | [NO UI YET — optional] |
| POST | `/products/match` | Resolve free text → candidate SKUs | RFQ line AI suggestion, extraction review |
| POST | `/products/import` | Excel catalogue import → job | **"Import Excel" (inert today)** |
| GET | `/products/export` | Export catalogue → job | Export button |

### 2.6 Suppliers

| Method | Endpoint | Purpose | UI origin |
|---|---|---|---|
| GET | `/suppliers` | Paged list; `q`, `type`, `city`, `status` | Suppliers screen |
| POST | `/suppliers` | Create | Add Supplier dialog |
| GET | `/suppliers/{id}` | Detail + contacts + performance | Supplier detail |
| PATCH | `/suppliers/{id}` | Update | Edit dialog |
| DELETE | `/suppliers/{id}` | Soft delete | Delete action |
| GET | `/suppliers/{id}/purchase-orders` | PO history | Supplier detail table |
| GET | `/suppliers/{id}/performance` | On-time %, quality, totals | Performance bars |
| GET/POST | `/suppliers/{id}/contacts` · PATCH/DELETE `/supplier-contacts/{id}` | Contacts | Contacts card |
| GET/POST | `/suppliers/{id}/products` | Supplier SKU aliases | [NO UI YET] |

### 2.7 Inventory

| Method | Endpoint | Purpose | UI origin |
|---|---|---|---|
| GET | `/inventory/stock` | Product × godown grid + KPIs; filters godown/category/brand/status | Current Stock |
| GET | `/inventory/stock/by-godown` | Grouped by godown | Stock by Godown |
| GET | `/inventory/low-stock` | Below reorder point + suggested qty + preferred supplier + last price | Low Stock |
| GET | `/inventory/transactions` | Ledger; filters type/godown/sku/date range | Transactions |
| POST | `/inventory/transactions` | Manual movement (damage / sales issue / correction) | New Transaction dialog |
| POST | `/inventory/transfers` | Godown-to-godown transfer (posts the OUT/IN pair) | Transfer kind + "Transfer Stock" |
| GET | `/inventory/transfers` · `/inventory/transfers/{id}` | Transfer documents | [NO UI YET] |
| POST | `/inventory/adjustments` | Bulk physical-count correction | [NO UI YET] |
| GET | `/inventory/valuation` | Stock value by godown/category | Reports, KPI |
| GET | `/inventory/export` | Export → job | Export button |

### 2.8 RFQ

| Method | Endpoint | Purpose | UI origin |
|---|---|---|---|
| GET | `/rfqs` | List; `status`, `supplier_id`, `q` | RFQ list |
| POST | `/rfqs` | Create draft (optionally `source: low_stock`) | RFQ create / low-stock handoff |
| GET | `/rfqs/{id}` | Detail with items + suppliers + quote counts | RFQ detail |
| PUT | `/rfqs/{id}` | Update draft (items replaced wholesale) | Edit draft |
| DELETE | `/rfqs/{id}` | Delete draft only | Delete (draft) |
| POST | `/rfqs/{id}/cancel` | Cancel a sent RFQ | [NO UI YET] |
| POST | `/rfqs/{id}/send` | Validate → render PDF → email suppliers → status `sent` | **Send RFQ** |
| GET | `/rfqs/{id}/quotations` | Quotations received | Quote-count link |
| GET | `/rfqs/{id}/quotation-comparison` | Computed comparison matrix | Comparison screen |
| GET | `/rfqs/{id}/pdf` | Printable RFQ | Print button |

### 2.9 Quotations

| Method | Endpoint | Purpose | UI origin |
|---|---|---|---|
| GET | `/quotations` | List; `status`, `supplier_id`, `rfq_id`, `source` | Quotations screen |
| POST | `/quotations` | Manual entry | `source: "Manual Entry"` exists with no form — **[NO UI YET]** |
| GET | `/quotations/{id}` | Detail with items | — |
| PUT | `/quotations/{id}` | Edit before approval | Extraction review edits |
| DELETE | `/quotations/{id}` | Discard | Delete action |
| POST | `/quotations/{id}/approve` | Human approval of an extraction | **Approve Quotation** |
| POST | `/quotations/{id}/reject` | Reject with reason | **Reject** |
| POST | `/quotations/from-extraction/{extraction_id}` | Promote AI result → quotation | Approve flow |

### 2.10 Comparison

| Method | Endpoint | Purpose | UI origin |
|---|---|---|---|
| POST | `/comparisons` | Build a comparison for an RFQ / a set of quotations | Compare Selected / Compare All |
| GET | `/comparisons/{id}` | Matrix + terms + recommendation + savings | Comparison screen |
| PATCH | `/comparisons/{id}/lines/{line_id}` | Override the supplier for one line | Clicking a supplier cell |
| POST | `/comparisons/{id}/reset` | Reset to recommended | "Reset to recommended" |
| POST | `/comparisons/{id}/convert-to-po` | Create one PO per selected supplier | **Create PO(s)** |

### 2.11 Purchase Orders

| Method | Endpoint | Purpose | UI origin |
|---|---|---|---|
| GET | `/purchase-orders` | List; `status`, `supplier_id`, date range | PO list |
| POST | `/purchase-orders` | Create draft | PO create |
| GET | `/purchase-orders/{id}` | Detail with items + fulfilment | PO detail |
| PUT | `/purchase-orders/{id}` | Update draft | Edit draft |
| DELETE | `/purchase-orders/{id}` | Delete **draft only** | Delete draft |
| POST | `/purchase-orders/{id}/submit` | Draft → pending_approval | [NO UI YET] |
| POST | `/purchase-orders/{id}/approve` | Approve | **Approve** |
| POST | `/purchase-orders/{id}/send` | Email supplier → `sent` | **Send to Supplier** |
| POST | `/purchase-orders/{id}/cancel` | Cancel with reason | replaces Delete on non-drafts |
| POST | `/purchase-orders/{id}/close` | Short-close remaining quantities | [NO UI YET] |
| GET | `/purchase-orders/{id}/pdf` | Printable PO (buyer letterhead) | Print |
| GET | `/purchase-orders/{id}/receipt-lines` | Open lines prepared for a GRN | **Import from PO** |
| GET | `/purchase-orders/open` | POs eligible for receipt | GRN form dropdown |

### 2.12 Proforma

| Method | Endpoint | Purpose | UI origin |
|---|---|---|---|
| GET | `/proforma-invoices` | List; `status`, `supplier_id` | Proforma list |
| POST | `/proforma-invoices` | Manual create | **[NO UI YET]** |
| GET | `/proforma-invoices/{id}` | Detail + PO variance + bank block | Proforma detail |
| PATCH | `/proforma-invoices/{id}` | Edit before approval | [NO UI YET] |
| POST | `/proforma-invoices/{id}/approve` | Approve for payment | [NO UI YET — status exists] |
| POST | `/proforma-invoices/{id}/reject` | Reject | [NO UI YET] |
| POST | `/proforma-invoices/{id}/raise-query` | Send a query to the supplier | **"Raise query" (inert today)** |
| GET | `/proforma-invoices/{id}/variance` | Line-level PO vs proforma differences | Difference cards |
| GET | `/proforma-invoices/{id}/pdf` | Print | Print |

### 2.13 Goods Receipt

| Method | Endpoint | Purpose | UI origin |
|---|---|---|---|
| GET | `/goods-receipts` | List; `status`, `godown_id`, `supplier_id` | GRN list |
| POST | `/goods-receipts` | Create draft (from PO or standalone) | GRN create |
| GET | `/goods-receipts/{id}` | Detail | GRN detail |
| PUT | `/goods-receipts/{id}` | Update draft | Save Draft |
| DELETE | `/goods-receipts/{id}` | Delete **draft only** | Delete (must be blocked once confirmed) |
| POST | `/goods-receipts/{id}/confirm` | **Validate → post inventory → update PO → raise variances/alerts** | **Confirm Receipt** |
| POST | `/goods-receipts/{id}/cancel` | Cancel a draft | — |
| POST | `/goods-receipts/{id}/reverse` | Reversing GRN for a confirmed receipt | [NO UI YET — replaces unsafe Delete] |
| GET | `/goods-receipts/{id}/pdf` | Print (internal document) | Print |
| POST | `/goods-receipts/{id}/documents` | Attach challan/photos | **Attachment input (inert today)** |

### 2.14 Supplier Invoice **[ENTIRE MODULE HAS NO UI]**

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/supplier-invoices` | List; `status`, `match_status`, `payment_status`, `supplier_id` |
| POST | `/supplier-invoices` | Create (manual or from extraction) |
| GET | `/supplier-invoices/{id}` | Detail |
| PATCH | `/supplier-invoices/{id}` | Edit before approval |
| POST | `/supplier-invoices/{id}/match` | Run 3-way match vs PO and GRN |
| POST | `/supplier-invoices/{id}/approve` | Approve for payment |
| POST | `/supplier-invoices/{id}/dispute` | Mark disputed with reason |
| GET | `/supplier-invoices/{id}/variance` | Invoice vs PO vs GRN differences |

### 2.15 Purchase Returns **[NO UI]**

`GET/POST /purchase-returns` · `GET/PATCH /purchase-returns/{id}` · `POST /purchase-returns/{id}/confirm` (posts `PURCHASE_RETURN` transactions) · `GET /purchase-returns/{id}/pdf`

### 2.16 Documents

| Method | Endpoint | Purpose | Sync | UI origin |
|---|---|---|---|---|
| POST | `/documents/upload` | Multipart upload, SHA-256 dedupe, enqueue processing | A | **Dropzone (inert today)** |
| GET | `/documents` | List; `processing_status`, `document_type`, `supplier_id` | S | AI Documents table |
| GET | `/documents/{id}` | Metadata + job state | S | Row polling |
| GET | `/documents/{id}/download` | Pre-signed S3 URL | S | **"Open file" (inert today)** |
| POST | `/documents/{id}/process` | Re-process / retry | A | **"Re-upload" on failed** |
| GET | `/documents/{id}/status` | Lightweight progress poll | S | Progress bar + stage |
| DELETE | `/documents/{id}` | Soft delete | S | — |
| POST | `/documents/{id}/links` · DELETE `/document-links/{id}` | Link/unlink to a business record | S | Attachment panels |
| GET | `/documents/{id}/extraction` | Extraction for review | S | **Review screen (currently id-less)** |

### 2.17 AI

| Method | Endpoint | Purpose | Sync | UI origin |
|---|---|---|---|---|
| POST | `/ai/extract` | Start extraction for a document | A | Auto after upload |
| GET | `/ai/jobs/{id}` | Job status/progress/stage | S | Progress bar |
| GET | `/ai/extractions/{id}` | Fields + lines + candidates + pipeline trace | S | Review screen |
| PATCH | `/ai/extractions/{id}/fields/{field_id}` | Human corrects a field | S | Editing a field |
| PATCH | `/ai/extractions/{id}/lines/{line_id}` | Human edits/matches a line | S | Selecting a product |
| POST | `/ai/extractions/{id}/approve` | Approve → promote to business record | S | **Approve Quotation** |
| POST | `/ai/extractions/{id}/reject` | Reject with reason | S | **Reject** |
| POST | `/ai/match` | Match description(s) → ranked SKUs | S | RFQ typing, line matching |
| POST | `/ai/match/confirm` | Confirm a match → writes `supplier_products` alias | S | Accepting a suggestion |
| GET | `/ai/schema-mappings` | Known supplier/document mappings | S | [NO UI YET] |
| POST | `/ai/schema-mappings` | Save a confirmed column mapping | S | [NO UI YET] |
| POST | `/ai/schema-mappings/suggest` | AI proposes column → canonical mapping | S | [NO UI YET] |
| GET | `/ai/canonical-fields` | Vocabulary for mapping UI | S | [NO UI YET] |
| POST | `/assistant/query` | Natural-language question → structured answer | S | AI Assistant |
| GET | `/assistant/suggestions` | Suggested questions | S | Assistant chips |

### 2.18 Alerts, dashboard, reports, audit

| Method | Endpoint | Purpose | UI origin |
|---|---|---|---|
| GET | `/alerts` | List; `severity`, `category`, `status` | Alerts screen |
| GET | `/alerts/summary` | Counts per severity + unread | Alert counters, header badge |
| POST | `/alerts/{id}/read` · `/alerts/read-all` | Mark read (per user) | Open / Mark all as read |
| POST | `/alerts/{id}/dismiss` · `/alerts/{id}/resolve` | Close an alert | [NO UI YET] |
| GET/PUT | `/alert-rules` · `/alert-rules/{rule_code}` | Enable/disable rules and set thresholds | Settings → Alerts section |
| GET/PUT | `/notification-preferences` | Per-user notification choices | [NO UI YET — optional] |
| GET | `/outbound-messages?related_type&related_id` | What was emailed, and whether it bounced | [NO UI YET — needed to make "Sent to supplier" trustworthy] |
| GET | `/dashboard/summary` | KPIs + stock status + low stock + activity + procurement tiles | Dashboard |
| GET | `/reports/{report_key}` | Parameterised report data | Reports cards |
| POST | `/reports/{report_key}/export` | Export → job | Export buttons |
| GET | `/audit-logs` | Filterable audit feed | Audit Trail cards, Team Activity |
| GET | `/audit-logs/{entity_type}/{entity_id}` | One record's history | Record Audit Trail |
| GET | `/jobs/{id}` | Generic async job status | Exports, imports, AI |
| GET | `/notifications/stream` | SSE for live document/job/alert updates | Progress bars |

**Endpoint count:** ~142. Of these, 41 back UI controls that are currently decorative, and 30 belong to modules with no UI at all (Supplier Invoice, Purchase Return, Schema Mapping, Stock Transfers, UoM conversions, alert rules).

---

## 3. Detailed specifications

Format for each: **Purpose · Auth/Permission · Parameters · Request · Response · Validation · Errors · Tables touched · Sync/Async**

---

### 3.1 `POST /auth/login`

**Purpose:** Authenticate by username **or** email (the UI accepts both since the `superadmin`/`useradmin` demo accounts were added) and return tokens plus the routing role.
**Auth:** public. **Rate limit:** 10/min/IP, 5 failures → 15-minute lock.

```jsonc
// Request
{ "identifier": "useradmin", "password": "•••••••", "remember_me": true }

// 200
{
  "access_token": "eyJ…", "token_type": "bearer", "expires_in": 900,
  "user": {
    "id": "usr_…", "full_name": "Sharad", "email": "useradmin@acmetraders.in",
    "role": { "code": "owner", "name": "Owner" },
    "company": { "id": "co_…", "name": "Acme Traders" },
    "permissions": ["po.approve", "grn.confirm", …],
    "godown_scope": { "all": true, "godown_ids": [] },
    "landing_route": "/dashboard"          // "/system-admin" for super_admin
  }
}
```

**Validation:** identifier non-empty; password ≥ 8 (the demo accounts use 9-char values, and the prototype's 6-char minimum should be raised for production).
**Errors:** `401 INVALID_CREDENTIALS` (never reveal which part was wrong) · `403 COMPANY_SUSPENDED` · `403 USER_INACTIVE` · `429 RATE_LIMITED`.
**Tables:** `users`, `roles`, `role_permissions`, `companies`, `refresh_tokens`, `user_godown_access`, `audit_logs`.
**Sync.** Refresh token set as `HttpOnly; Secure; SameSite=Lax` cookie only when `remember_me`.

---

### 3.2 `GET /auth/me`
Returns the same `user` object as login. Called on every app load to drive nav visibility and the role-gated System Admin item. **Permissions must be re-read here, never cached client-side beyond the token lifetime.**

---

### 3.3 `POST /invitations`

**Purpose:** Invite a colleague. **Permission:** `user.manage`.

```jsonc
// Request
{ "full_name": "Priya Nair", "email": "priya@acmetraders.in",
  "role_code": "staff", "godown_scope": "specific", "godown_ids": ["gd_…"] }

// 201
{ "id": "inv_…", "email": "priya@acmetraders.in", "status": "pending",
  "invited_at": "2026-09-14T10:00:00+05:30", "expires_at": "2026-09-21T10:00:00+05:30",
  "invite_url": "https://app.inventoryai.in/accept-invite/inv_…?t=<token>" }
```

**Validation:** email format; **no active user and no pending invite with that email in this tenant**; role must exist and must not be `super_admin`; `godown_ids` must belong to this tenant when scope = specific; an Owner invite requires `user.manage_owners`.
**Errors:** `409 DUPLICATE` (`EMAIL_ALREADY_MEMBER` / `INVITE_ALREADY_PENDING`) · `422` invalid role.
**Tables:** `invitations`, `users` (lookup), `outbound_messages`, `audit_logs`. **Async side-effect:** invitation email via Celery.

**`POST /invitations/{id}/accept`** — body `{ "token": "...", "password": "...", "password_confirm": "..." }`. Creates the `users` row (or activates it), writes `user_godown_access`, marks the invitation `accepted`, logs `invitation_accepted`. Errors: `404 INVITE_NOT_FOUND`, `410 INVITE_EXPIRED`, `409 ALREADY_ACCEPTED`, `400 PASSWORD_TOO_WEAK`. **The prototype has no expiry — that is a security gap.**

---

### 3.4 `GET /products`

**Purpose:** The Products screen, with the filters that are currently client-side. **Permission:** `product.view`.

**Query:** `q` (name/SKU/barcode trigram) · `category_id` · `brand_id` · `stock_status=in_stock|low_stock|out_of_stock` · `godown_id` · `is_active` · `sort=name|-created_at|current_stock` · `limit` · `cursor`

```jsonc
// 200
{ "items": [{
    "id": "prd_…", "name": "Pigeon Cooker 5L", "brand": "Pigeon",
    "category": "Home Appliances", "subcategory": "Cookware",
    "default_variant": {
      "id": "var_…", "sku": "SKU001", "unit": "Nos", "hsn_code": "7615", "gst_rate": "18.00",
      "purchase_price": "1180.0000", "sale_price": "1490.0000", "mrp": "1795.0000",
      "reorder_point": "20.000", "reorder_qty": "50.000"
    },
    "stock": { "total": "8.000", "reserved": "0.000", "available": "8.000",
               "status": "low_stock",
               "by_godown": [{ "godown_id": "gd_1", "godown": "Main Godown", "qty": "8.000" }] },
    "variant_count": 1, "display_emoji": "🍲"
  }],
  "next_cursor": "eyJjcmVh…", "total": 1248,
  "facets": { "categories": [...], "brands": [...], "godowns": [...] }
}
```

`stock` is joined from `stock_balances` — **never** stored on the product. `facets` replaces the hardcoded `CATEGORIES`/`BRANDS` arrays the filters use today.
**Tables:** `products`, `product_variants`, `stock_balances`, `categories`, `brands`, `uoms`.

---

### 3.5 `POST /products`

```jsonc
// Request
{ "name": "Pigeon Cooker 5L", "brand_id": "brd_…", "category_id": "cat_…",
  "hsn_code": "7615", "gst_rate": "18.00", "tracking_type": "none", "base_uom_id": "uom_nos",
  "variant": { "sku": "SKU001", "barcode": "8901234500011", "mpn": "PGN-PC-5L",
               "purchase_price": "1180", "sale_price": "1490", "mrp": "1795",
               "reorder_point": "20", "reorder_qty": "50",
               "attributes": { "Capacity": "5 Litre", "Material": "Aluminium" } },
  "opening_stock": [ { "godown_id": "gd_1", "quantity": "8", "unit_cost": "1180" } ]
}
// 201 → the created product with its variant and stock
```

**Validation:** name required; SKU required, unique per tenant (case-insensitive), `^[A-Z0-9._/-]{2,40}$`; barcode unique per tenant when present; `sale_price ≥ 0`, `mrp ≥ sale_price` (warning, not error); HSN 4/6/8 digits; GST rate in the allowed set; attributes ≤ 50 keys.
**Critical rule:** `opening_stock` does **not** write a stock column — it posts `OPENING_STOCK` inventory transactions. This is the corrected version of today's editable `currentStock` field (`06`, BR-INV-01).
**Errors:** `409 DUPLICATE_SKU` / `DUPLICATE_BARCODE` · `422 VALIDATION_ERROR`.
**Tables:** `products`, `product_variants`, `inventory_transactions`, `stock_balances`, `variant_embeddings` (async enqueue), `audit_logs`.

**`PATCH /products/{id}`** — same shape, all fields optional, `If-Match` required. **SKU is immutable once transactions exist** (`409 SKU_LOCKED`), mirroring the UI which already disables the SKU field on edit. Changing `purchase_price` does **not** revalue existing stock.

**`DELETE /products/{id}`** — soft delete. Blocked with `409 RECORD_IN_USE` when stock ≠ 0 or open PO/RFQ lines exist; the response lists the blockers so the UI can explain itself instead of failing silently.

---

### 3.6 `POST /products/match`

**Purpose:** The matching brain behind three UI features: RFQ line suggestions, extraction-review line matching, and future Excel import. **Permission:** `product.view`.

```jsonc
// Request
{ "queries": [ { "ref": "e3", "text": "LG FRIDGE 260 LTR DBL DOOR SHINY STEEL",
                 "supplier_id": "sup_…", "supplier_sku": "RR-LG-260",
                 "qty": 10, "unit": "Nos" } ],
  "limit": 5, "min_score": 0.55 }

// 200
{ "results": [ { "ref": "e3",
    "normalised_text": "lg refrigerator 260 l double door steel",
    "candidates": [
      { "product_variant_id": "var_…", "sku": "SKU003", "name": "LG Refrigerator 260L",
        "match_method": "embedding", "score": 0.91, "confidence": 62.0,
        "reasons": ["brand match: LG", "capacity 260L", "cosine 0.91"] }
    ],
    "auto_matched": false, "requires_review": true } ] }
```

**Escalation ladder (server-side, cheapest first — never call the LLM first):**
`exact_sku` → `supplier_alias` (`supplier_products.supplier_sku`) → `barcode/EAN` → `normalised_rule` (unit/abbreviation normalisation) → `trigram` (pg_trgm ≥ 0.45) → `embedding` (pgvector cosine ≥ 0.80) → `llm` (only when the top-2 embedding scores are within 0.05 or all are below threshold).
`auto_matched` is true only when `score ≥ 0.95` **and** the method is deterministic (`exact_sku`/`supplier_alias`/`barcode`) — an LLM or embedding result is never auto-accepted.
**Tables:** `product_variants`, `supplier_products`, `variant_embeddings`, `ai_match_candidates` (written for audit), `ai_processing_jobs` (when the LLM tier is reached).
**Sync** (target p95 < 400 ms without the LLM tier; the LLM tier returns `requires_review: true` and may be resolved asynchronously).

---

### 3.7 `GET /inventory/stock`

**Query:** `godown_id` · `category_id` · `brand_id` · `status` · `q` · `limit` · `cursor`

```jsonc
{ "items": [ { "product_variant_id": "var_…", "sku": "SKU001", "product": "Pigeon Cooker 5L",
               "brand": "Pigeon", "category": "Home Appliances",
               "godown_id": "gd_1", "godown": "Main Godown",
               "quantity": "8.000", "reserved": "0.000", "available": "8.000",
               "unit": "Nos", "status": "low_stock", "value": "9440.00" } ],
  "kpis": { "total_skus": 1248, "inventory_value": "1248500.00", "low_stock": 23, "out_of_stock": 7 },
  "next_cursor": null, "total": 1834 }
```

KPIs are computed for the **filtered** set and returned alongside — the prototype shows hardcoded KPIs that contradict its own rows.
**Tables:** `stock_balances`, `product_variants`, `products`, `godowns`, `categories`, `brands`.
**Scope:** results are filtered by the caller's `user_godown_access` unless they hold `inventory.view_all`.

---

### 3.8 `POST /inventory/transactions`

**Purpose:** The New Transaction dialog — damage, sales issue, stock correction. **Permission:** `inventory.adjust` (+ godown scope). Transfers use §3.9 instead.

```jsonc
// Request
{ "txn_type": "DAMAGE", "product_variant_id": "var_…", "godown_id": "gd_1",
  "batch_id": null, "quantity": "4", "uom_id": "uom_nos",
  "txn_date": "2026-09-11T10:42:00+05:30",
  "reason_code": "damaged_in_transit", "reference": null,
  "remarks": "Water damage in transit" }

// 201
{ "id": "txn_…", "txn_number": "DMG-2026-00013", "txn_type": "DAMAGE",
  "quantity": "-4.000", "balance_after": "36.000" }
```

**Important:** the client sends an **unsigned magnitude**; the server applies the sign from `txn_type` (and from `direction` for `STOCK_CORRECTION`). This removes a whole class of client bugs and matches how the dialog already behaves.
**Validation:** quantity > 0; variant active; godown in scope; batch required when `tracking_type='batch'`; `txn_date` not in the future and within an open period; resulting balance ≥ 0 unless `company_settings.allow_negative_stock` (default false) → `422 INSUFFICIENT_STOCK` naming the available quantity; `remarks` required for `DAMAGE` and `STOCK_CORRECTION` (**the UI collects remarks then discards them**).
**Tables:** `inventory_transactions`, `stock_balances`, `document_sequences`, `audit_logs`, `alerts` (if the movement crosses the reorder point).
**Sync**, single DB transaction. `Idempotency-Key` required.

---

### 3.9 `POST /inventory/transfers`

```jsonc
// Request
{ "from_godown_id": "gd_1", "to_godown_id": "gd_2", "transfer_date": "2026-09-12",
  "vehicle_number": "MH 04 GH 5521", "lr_number": "VRL/2026/88213", "eway_bill_number": "381004552271",
  "items": [ { "product_variant_id": "var_…", "batch_id": null, "quantity": "120", "uom_id": "uom_nos" } ],
  "remarks": "Rebalancing" }

// 201
{ "id": "trf_…", "transfer_number": "TRF-2026-00035", "status": "received",
  "transactions": [ { "id": "txn_a", "type": "TRANSFER_OUT", "quantity": "-120.000", "godown_id": "gd_1" },
                    { "id": "txn_b", "type": "TRANSFER_IN",  "quantity": "120.000",  "godown_id": "gd_2" } ] }
```

Both ledger rows are written in one transaction with `counterpart_txn_id` cross-set — exactly the pairing the UI dialog invented client-side. `from ≠ to`; sufficient stock at source; both godowns in the user's scope.
**Two-step mode:** when `company_settings` enables in-transit tracking, `POST` dispatches (`TRANSFER_OUT` only, status `in_transit`) and `POST /inventory/transfers/{id}/receive` posts `TRANSFER_IN`.

---

### 3.10 `POST /rfqs`

```jsonc
{ "rfq_date": "2026-09-14", "expected_delivery_date": "2026-09-25",
  "subject": "Kitchen and Home Appliances — Sep 2026",
  "delivery_godown_id": "gd_1", "notes": "Quote GST separately.",
  "supplier_ids": ["sup_a", "sup_b"], "created_from": "low_stock",
  "items": [ { "line_no": 1, "product_variant_id": "var_…", "description": "Pigeon Cooker 5L",
               "quantity": "50", "uom_id": "uom_nos", "expected_price": "1100" } ] }
// 201 → { "id", "rfq_number": "RFQ-2026-00059", "status": "draft", "estimated_value": "55000.00" }
```

**Validation:** ≥1 item; quantity > 0; `expected_delivery_date ≥ rfq_date`; suppliers active and in tenant; `product_variant_id` nullable (free-text lines allowed) but `description` then required.
**Note:** the RFQ number is allocated **on create**, not on send, because the prototype shows it in the form immediately.
**Tables:** `rfqs`, `rfq_items`, `rfq_suppliers`, `document_sequences`, `audit_logs`.

---

### 3.11 `POST /rfqs/{id}/send`

**Purpose:** The "Send RFQ" button. **Permission:** `rfq.send`.

```jsonc
// Request (optional overrides)
{ "supplier_ids": ["sup_a","sup_b"], "message": "Please quote by 20 Sep.",
  "attach_pdf": true, "cc_self": true }
// 202
{ "id": "rfq_…", "status": "sent", "sent_at": "…",
  "recipients": [ { "supplier_id": "sup_a", "email": "…", "status": "queued" } ],
  "job_id": "job_…" }
```

**Sequence:** validate (≥1 item, ≥1 supplier with an email) → allocate nothing (number already exists) → render PDF (Celery) → store as a `document` linked to the RFQ → send email per supplier → write `rfq_suppliers.sent_at/status` and `outbound_messages` → set `rfqs.status='sent'` → audit.
**Validation:** status must be `draft`; every selected supplier must have an email (`422 SUPPLIER_EMAIL_MISSING` listing them).
**Errors:** `409 INVALID_STATE_TRANSITION` when already sent.
**Async** — the endpoint returns immediately; per-recipient delivery state arrives via the job/SSE. The UI's fake 800 ms delay becomes a real job.

---

### 3.12 `GET /rfqs/{id}/quotation-comparison`

**Purpose:** Builds the comparison matrix the UI currently receives as static mock data. Returns a computed, explainable recommendation.

```jsonc
{ "rfq": { "id": "…", "rfq_number": "RFQ-2026-00057", "subject": "…" },
  "suppliers": [ { "supplier_id": "sup_f", "name": "Flipkart India Pvt Ltd",
                   "quotation_id": "qt_…", "quotation_number": "FK/QTN/8821",
                   "valid_until": "2026-09-21", "is_expired": false,
                   "total": "131250.00", "missing_lines": 0 } ],
  "rows": [ { "rfq_item_id": "ri_1", "product_variant_id": "var_1", "sku": "SKU001",
              "product": "Pigeon Cooker 5L", "quantity": "50", "unit": "Nos",
              "cells": [ { "supplier_id": "sup_r", "quotation_item_id": "qi_…",
                           "unit_price": "1100.0000", "line_total": "55000.00", "gst_rate": "18.00",
                           "is_available": true, "note": null, "is_lowest": true } ],
              "recommended_supplier_id": "sup_r",
              "recommendation_reason": "Lowest landed cost (₹55,000) and shortest delivery (4 days)",
              "recommendation_score": 0.93,
              "price_spread_pct": "13.64" } ],
  "terms": [ { "label": "Delivery period", "values": { "sup_r": "4 days" }, "best_supplier_id": "sup_r" } ],
  "totals": { "lowest_single_supplier": { "supplier_id": "sup_r", "total": "384000.00" },
              "split_total": "379000.00", "projected_savings": "5000.00" },
  "warnings": [ { "code": "PRICE_SPREAD_HIGH", "rfq_item_id": "ri_3", "spread_pct": "8.2" },
                { "code": "QUOTATION_EXPIRING", "supplier_id": "sup_f", "valid_until": "2026-09-21" } ] }
```

**Recommendation is computed** as a weighted score over landed cost (unit price + freight share + tax where non-creditable), delivery days, supplier on-time %, quality score and warranty — weights held in `company_settings` and returned in the response so the UI can say *why*. `price_spread_pct > 5` reproduces the UI's existing warning band.
**Tables:** `rfqs`, `rfq_items`, `supplier_quotations`, `supplier_quotation_items`, `suppliers`, `v_supplier_performance`.

---

### 3.13 `POST /comparisons/{id}/convert-to-po`

**Purpose:** The single most important workflow hand-off — replaces the `sessionStorage` blob.

```jsonc
// Request
{ "selections": [ { "rfq_item_id": "ri_1", "supplier_id": "sup_r", "quotation_item_id": "qi_1" } ],
  "po_defaults": { "expected_delivery_date": "2026-09-28", "delivery_godown_id": "gd_1",
                   "payment_terms": "30 Days", "delivery_terms": "FOR" },
  "create_as": "draft" }

// 201
{ "purchase_orders": [
    { "id": "po_…", "po_number": "PO-2026-00125", "supplier_id": "sup_r", "status": "draft",
      "line_count": 2, "total_amount": "139000.00" },
    { "id": "po_…", "po_number": "PO-2026-00126", "supplier_id": "sup_l", "status": "draft",
      "line_count": 1, "total_amount": "240000.00" } ],
  "comparison_status": "converted" }
```

One PO per distinct supplier, numbers allocated sequentially from `document_sequences` (the UI's `bumpNumber` guesswork disappears). Each PO line carries `quotation_item_id` and `rfq_item_id` so price provenance is permanent. The comparison is marked `converted` and its lines are frozen.
**Validation:** every selection references a quotation belonging to this comparison; quotations not expired (`422 QUOTATION_EXPIRED` unless `allow_expired: true`); no duplicate `rfq_item_id`.

---

### 3.14 `POST /purchase-orders`

```jsonc
{ "supplier_id": "sup_r", "rfq_id": "rfq_…", "quotation_id": "qt_…",
  "po_date": "2026-09-14", "expected_delivery_date": "2026-09-25",
  "delivery_godown_id": "gd_1", "payment_terms": "30 Days", "delivery_terms": "FOR",
  "freight_amount": "0", "other_charges": "0", "notes": "",
  "items": [ { "line_no": 1, "product_variant_id": "var_2", "quantity": "30", "uom_id": "uom_nos",
               "unit_price": "2800", "discount_pct": "0", "gst_rate": "18" } ] }

// 201
{ "id": "po_…", "po_number": "PO-2026-00125", "status": "draft",
  "is_inter_state": true, "place_of_supply_state_code": "23",
  "totals": { "subtotal": "84000.00", "discount_amount": "0.00", "taxable_value": "84000.00",
              "cgst_amount": "0.00", "sgst_amount": "0.00", "igst_amount": "15120.00",
              "cess_amount": "0.00", "freight_amount": "0.00", "round_off": "0.00",
              "total_amount": "99120.00" },
  "row_version": 1 }
```

**All totals are computed server-side and echoed back** — the client must display the response, never its own arithmetic. This kills the prototype's two divergent formulas.
**Validation:** supplier active; ≥1 item; every variant active and in tenant; quantity > 0; unit_price ≥ 0; discount 0–100; `expected_delivery_date ≥ po_date`; godown in scope; **`is_inter_state` derived server-side** from supplier vs godown state codes.
**Errors:** `422 SUPPLIER_INACTIVE` · `422 VARIANT_INACTIVE` · `409 DUPLICATE` (idempotency replay).
**Tables:** `purchase_orders`, `purchase_order_items`, `document_sequences`, `suppliers`, `product_variants`, `godowns`, `audit_logs`.

---

### 3.15 `POST /purchase-orders/{id}/approve`

**Purpose:** The Approve button. **Permission:** `po.approve` (+ `po.approve_high_value` above `require_po_approval_above`).

```jsonc
// Request { "note": "Approved for festive stocking" }
// 200 { "id", "status": "approved", "approved_by", "approved_at", "row_version": 3 }
```

**Validation (BR-PO-02):** status ∈ {`draft`,`pending_approval`}; ≥1 item; supplier has GSTIN **or** is explicitly marked unregistered; delivery godown set; expected delivery set; total > 0; approver ≠ creator when `require_maker_checker` is on; value within the approver's limit.
**Errors:** `409 INVALID_STATE_TRANSITION` · `403 APPROVAL_LIMIT_EXCEEDED` · `422 BUSINESS_RULE_VIOLATION` with the specific missing fields.
**Side-effects:** audit entry `approved`; alert to the purchase manager; PDF regenerated.

**`POST /purchase-orders/{id}/send`** — requires `approved`; renders the PDF on the buyer's letterhead (the convention the UI already implements: documents *we* issue carry *our* masthead), emails the supplier contact, stores `outbound_messages`, sets `sent`/`sent_at`. Async, returns `202`.

---

### 3.16 `GET /purchase-orders/{id}/receipt-lines`

**Purpose:** Powers "Import from PO" on the GRN form — the pending balance, not the original quantity. This is what makes the second GRN of a partial delivery correct.

```jsonc
{ "purchase_order": { "id", "po_number": "PO-2026-00123", "supplier": {...}, "delivery_godown": {...} },
  "lines": [ { "purchase_order_item_id": "poi_2", "product_variant_id": "var_3", "sku": "SKU003",
               "product": "LG Refrigerator 260L", "unit": "Nos", "unit_price": "24500.0000",
               "ordered_quantity": "10.000", "previously_received_quantity": "8.000",
               "pending_quantity": "2.000", "suggested_received_quantity": "2.000",
               "requires_batch": false, "line_status": "partially_received" } ] }
```

Lines with `line_status` in (`received`,`cancelled`,`short_closed`) are excluded unless `?include_closed=true`.

---

### 3.17 `POST /goods-receipts`

```jsonc
{ "purchase_order_id": "po_…", "grn_date": "2026-09-14", "godown_id": "gd_1",
  "received_by_user_id": "usr_…",
  "vehicle_number": "MH 04 GH 5521", "transporter_name": "VRL Logistics",
  "lr_number": "VRL/2026/88213", "eway_bill_number": "381004552271",
  "supplier_challan_number": "RR/DC/9921", "supplier_challan_date": "2026-09-13",
  "items": [ { "line_no": 1, "purchase_order_item_id": "poi_1", "product_variant_id": "var_2",
               "received_quantity": "30", "accepted_quantity": "30", "uom_id": "uom_nos",
               "issue_type": "none", "remarks": "" },
             { "line_no": 2, "purchase_order_item_id": "poi_2", "product_variant_id": "var_3",
               "received_quantity": "8", "accepted_quantity": "8", "uom_id": "uom_nos",
               "issue_type": "short", "remarks": "2 units short — balance on 18 Sep" } ],
  "status": "draft" }
// 201 → GRN with number, computed rejected quantities, and a discrepancy summary
```

**Validation:** godown in scope and matching the PO's delivery godown (override needs `grn.receive_other_godown`); `accepted ≤ received`; `received ≥ 0`; **excess** (`received > pending`) rejected with `422 EXCESS_RECEIPT_NOT_ALLOWED` unless `allow_grn_excess_receipt` (within `grn_excess_tolerance_pct`); `issue_type` must be `wrong_*` only when `expected_variant_id` is supplied; batch fields required for batch-tracked variants; all transport fields persisted (**the prototype throws all four away**).

---

### 3.18 `POST /goods-receipts/{id}/confirm` — the highest-risk endpoint

**Purpose:** The single point where stock comes into existence. **Permission:** `grn.confirm` + godown scope. **Idempotency-Key required.**

```jsonc
// Request { "confirm_discrepancies": true, "note": "Short shipment acknowledged by supplier" }
// 200
{ "id": "grn_…", "grn_number": "GRN-2026-00091", "status": "partially_received",
  "confirmed_at": "…", "confirmed_by": "usr_…",
  "inventory_postings": [ { "goods_receipt_item_id": "gri_1", "inventory_transaction_id": "txn_…",
                            "product_variant_id": "var_2", "godown_id": "gd_1",
                            "quantity": "30.000", "balance_after": "34.000" } ],
  "purchase_order": { "id": "po_…", "received_pct": "76.00", "status": "partially_received" },
  "variances": [ { "id": "dv_…", "variance_type": "quantity", "comparison_kind": "grn_vs_po",
                   "product_variant_id": "var_3", "base_value": "10.000", "compare_value": "8.000",
                   "difference": "-2.000", "severity": "warning" } ],
  "alerts_raised": ["alt_…"] }
```

**Transactional sequence (all in one DB transaction):**
1. Lock the GRN row; assert `status='draft'` → else `409`.
2. Re-validate every line against the **current** PO pending quantity (it may have moved since the draft was saved).
3. For each line with `accepted_quantity > 0`: insert `inventory_transactions` (`GOODS_RECEIPT`, +accepted, base UoM, `unit_cost` from the PO line, `source_type='goods_receipt'`, `source_id`, `source_line_id`), upsert `stock_balances`, store `inventory_transaction_id` back on the GRN line.
4. Create `batches` rows where the variant is batch-tracked.
5. Increment `purchase_order_items.received_quantity`; recompute each `line_status`; recompute `purchase_orders.received_pct` and header status (`partially_received` / `received`).
6. Create `document_variances` for every short/excess/wrong/damaged line.
7. Set GRN `status` (`received` if every line complete and nothing rejected, else `partially_received`), `confirmed_by/at`, `has_discrepancy`.
8. Write `audit_logs`.
9. **After commit:** enqueue alert generation, supplier-performance refresh, and reorder-point evaluation.

**Errors:** `409 INVALID_STATE_TRANSITION` (already confirmed) · `422 EXCESS_RECEIPT_NOT_ALLOWED` · `422 PO_CANCELLED` · `422 BATCH_REQUIRED` · `403 GODOWN_OUT_OF_SCOPE` · `409 STALE_RECORD`.
**Rollback guarantee:** if any posting fails, **nothing** is written — no partial stock. The prototype's "Confirm Receipt" does none of this; it only flips a local flag.

**`POST /goods-receipts/{id}/reverse`** — the correct replacement for deleting a confirmed GRN: creates a reversing GRN whose transactions carry `reverses_txn_id`, decrements `received_quantity`, and leaves both documents visible.

---

### 3.19 `POST /documents/upload`

**Purpose:** The dropzone. **Permission:** `document.upload`. `multipart/form-data`.

| Part | Type | Notes |
|---|---|---|
| `file` | binary | ≤ 20 MB; `xlsx, xls, csv, pdf, docx, jpg, jpeg, png` |
| `document_type` | string? | Optional hint; AI classifies when absent |
| `supplier_id` | uuid? | Optional hint |
| `link` | json? | `{ "linked_type": "purchase_order", "linked_id": "po_…" }` for contextual uploads (GRN attachments) |

```jsonc
// 202
{ "id": "doc_…", "original_filename": "reliance_quotation_sep26.xlsx",
  "sha256_hash": "9f86d0…", "processing_status": "queued",
  "job_id": "job_…", "duplicate_of": null }
// 200 when the hash already exists for this tenant
{ "id": "doc_existing", "duplicate_of": "doc_existing",
  "message": "This file was already uploaded on 12 Sep 2026 and is linked to QT-RR-3391." }
```

**Validation:** MIME sniffing (not just the extension), size, virus scan, page/sheet count, per-tenant storage quota.
**Pipeline:** S3 put (server-side encryption) → `documents` row → enqueue `ai_processing_jobs` when `ai_auto_process` is on → progress via `GET /documents/{id}/status` or SSE.
**Tables:** `documents`, `document_links`, `ai_processing_jobs`, `audit_logs`.

**`GET /documents/{id}/status`** → `{ "processing_status": "processing", "processing_stage": "Matching products to your SKUs", "processing_progress": 68, "extraction_confidence": null, "items_found": null, "error": null }` — exactly the fields the document table already renders, which today are static.

---

### 3.20 `GET /ai/extractions/{id}` and the review endpoints

```jsonc
// GET response (drives the whole Extraction Review screen)
{ "id": "ext_…", "document": { "id": "doc_…", "filename": "…", "page_count": 1,
                               "download_url": "https://s3…signed" },
  "supplier": { "id": "sup_r", "name": "Reliance Retail Ltd", "confidence": 99.0 },
  "document_type": "supplier_quotation", "overall_confidence": 96.0,
  "fields": [ { "id": "f1", "key": "number", "label": "Quotation Number", "value": "QT-RR-3391",
                "confidence": 97.0, "provenance": "ai_extracted", "corrected_value": null } ],
  "lines": [ { "id": "l3", "raw_description": "LG FRIDGE 260 LTR DBL DOOR SHINY STEEL",
               "supplier_sku": "RR-LG-260", "quantity": "10", "unit": "Nos",
               "unit_price": "24500.0000", "gst_rate": "28.00",
               "matched_variant": null, "confidence": 62.0, "provenance": "needs_review",
               "candidates": [ { "product_variant_id": "var_3", "sku": "SKU003",
                                 "name": "LG Refrigerator 260L", "score": 0.91,
                                 "match_method": "embedding" } ] } ],
  "pipeline": [ { "step": "Text & table parsing", "result": "3 line items found", "state": "done" } ],
  "totals": { "subtotal": "…", "tax": "…", "total": "…" },
  "unresolved_count": 1, "fields_needing_review": 1, "can_approve": false }
```

`PATCH …/fields/{field_id}` `{ "value": "45 days credit" }` → sets `corrected_value`, flips `provenance` to `user_approved`, writes `ai_review_actions` with before/after.
`PATCH …/lines/{line_id}` `{ "matched_variant_id": "var_3", "quantity": "10", "unit_price": "24500" }` → same, plus optionally `"save_supplier_alias": true` which upserts `supplier_products` so this supplier's `RR-LG-260` never needs matching again.
`POST …/approve` → **server re-validates that no line is unmatched** (`422 UNRESOLVED_LINES` — never trust the client's `can_approve`), recomputes every total from the reviewed lines, creates the `supplier_quotations` + items (or proforma/invoice by document type), links the document, sets the document `approved`, writes audit. Returns the created business record.
`POST …/reject` `{ "reason": "Wrong supplier" }` → document `rejected`, nothing promoted.

---

### 3.21 `POST /supplier-invoices/{id}/match` **[NO UI]**

Runs the 3-way match and persists the result.

```jsonc
{ "match_status": "variance",
  "summary": { "po_total": "341720.00", "grn_value": "334000.00", "invoice_total": "346220.00" },
  "variances": [ { "variance_type": "price", "product_variant_id": "var_3",
                   "base_value": "24500.0000", "compare_value": "24850.0000",
                   "difference": "350.0000", "difference_pct": "1.43", "severity": "warning" },
                 { "variance_type": "quantity", "product_variant_id": "var_3",
                   "base_value": "10.000", "compare_value": "8.000", "severity": "critical" } ] }
```

Tolerances come from `company_settings`; anything outside them blocks approval and raises an alert.

---

### 3.22 `POST /assistant/query`

```jsonc
// Request { "question": "How many Pigeon 5L cookers are in stock?", "conversation_id": "cnv_…" }
// 200
{ "intent": "stock_level_for_product",
  "answer": "You have 8 Pigeon Cooker 5L in Main Godown — below the reorder point of 20.",
  "source": "Inventory · stock by godown for SKU001",
  "breakdown": [ { "label": "Main Godown", "value": "8" }, { "label": "Reserved", "value": "0", "muted": true } ],
  "table": null,
  "link": { "label": "View product", "href": "/products/SKU001" },
  "confidence": 0.94, "latency_ms": 380 }
```

**Guardrails (non-negotiable):** the LLM classifies intent and extracts entities only. It **never** emits SQL. Each intent maps to a hand-written, parameterised repository function executed with the caller's tenant and godown scope under a read-only role with a statement timeout. Unrecognised intents return the "could not determine" answer rather than guessing. Every call is logged to `assistant_queries`.

---

### 3.23 `GET /dashboard/summary`

Returns exactly the five blocks the dashboard renders: `kpis` (total SKUs, low stock, pending POs, inventory value, out of stock, SKUs added this month, PO value pending, godown count), `stock_status` (three slices), `low_stock` (top N rows), `activity` (recent audit-derived feed), `procurement` (open RFQs, quotations received, pending approvals, pending deliveries with their deep links). Cacheable in Redis for 60 s per company; every number derived from real tables, unlike the current hardcoded constants.

---

## 4. Asynchronous processing

| Operation | Pattern | Progress |
|---|---|---|
| Document extraction | `POST /documents/upload` → `202` + `job_id`; Celery chain: fetch → OCR/parse → classify → map columns → extract → match SKUs → score | `GET /documents/{id}/status` (poll 2 s) or SSE `/notifications/stream` |
| RFQ/PO send | `202` + `job_id`; render PDF → email | job status; `rfq_suppliers.status` per recipient |
| Excel catalogue import | `202`; validate → stage → upsert | `GET /jobs/{id}` with row-level error report |
| Exports | `202`; generate → S3 → signed URL | `GET /jobs/{id}` → `download_url` |
| Embedding regeneration | Background on variant create/update | none (internal) |
| Alert generation | Celery beat: low stock (hourly), PO delay (daily 08:00 IST), quotation expiry (daily), batch expiry (daily), balance reconciliation (nightly) | — |

**Job envelope:** `{ "id", "type", "status": "queued|running|succeeded|failed", "progress": 0-100, "stage": "…", "result": {...}, "error": {...}, "created_at", "finished_at" }`.

Celery queues: `default`, `documents` (CPU/OCR heavy), `ai` (rate-limited by provider), `email`, `reports`. Retries with exponential backoff; failures land in a dead-letter queue and raise a `System` alert rather than disappearing.

---

## 5. Security notes specific to these APIs

| Risk | Control |
|---|---|
| Cross-tenant id guessing | RLS + composite FKs `(company_id, id)`; unknown ids return `404`, never `403` |
| Privilege escalation via role change | `PATCH /users/{id}` cannot grant a role above the caller's own; changing a role revokes that user's refresh tokens |
| Impersonation abuse | Short-lived scoped token, `impersonated_by` stamped on every audit row, banner enforced by the token claim, auto-expiry, platform-admin-only |
| Signed URL leakage | Download URLs expire in 5 minutes and are single-tenant scoped |
| Upload abuse | MIME sniffing, size cap, per-tenant quota, virus scan, no execution of uploaded content |
| LLM prompt injection from supplier documents | Extracted text is **data**, never instructions; the extraction prompt is parameterised and the model's output is schema-validated before it touches the database; financial totals are always recomputed server-side (`ai_never_autoapprove_financials`) |
| Mass export | `report.export` permission, rate limited, every export audited |

