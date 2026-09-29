# 05 — UI ↔ API MAPPING & WORKFLOW SEQUENCES

Every screen in the audited prototype, the endpoints it needs, and the mock function each one replaces. Endpoints marked **⊕** back controls that exist in the UI but do nothing today; **⊗** marks endpoints with no UI yet.

---

## 1. Screen → endpoint map

### Auth

| Screen | Endpoints | Replaces |
|---|---|---|
| `/login` | `POST /auth/login` · `POST /auth/forgot-password` ⊕ | `signIn()` in `auth.service.ts` |
| `/accept-invite/[id]` | `GET /invitations/{id}` · `POST /invitations/{id}/accept` | `findInvitation()`, `acceptInvitation()` in `team-store.ts` |
| App shell (all routes) | `GET /auth/me` · `POST /auth/refresh` · `POST /auth/logout` · `GET /alerts/summary` | `getSessionUser()` |

### Dashboard

| Screen | Endpoints | Replaces |
|---|---|---|
| `/dashboard` | `GET /dashboard/summary` (KPIs, stock status, low stock, activity, procurement tiles) · `GET /alerts/summary` | `getDashboardSummary()` → static `KPIS`, `STOCK_STATUS`, `LOW_STOCK_ROWS`, `RECENT_ACTIVITY`, `PROCUREMENT_OVERVIEW` |

### Products & catalogue

| Screen | Endpoints | Replaces |
|---|---|---|
| `/products` | `GET /products?q&category_id&brand_id&stock_status&godown_id&sort&cursor` · `GET /categories` · `GET /brands` · `GET /godowns` · `POST /products` · `PATCH /products/{id}` · `DELETE /products/{id}` · `POST /products/import` ⊕ · `GET /products/export` ⊕ | `listProducts()`, `productStore.*` |
| `/products/[sku]` | `GET /products/by-sku/{sku}` · `GET /variants/{id}/stock` · `GET /variants/{id}/transactions?limit=10` · `GET /audit-logs/product/{id}` · `GET /documents?linked_type=product&linked_id={id}` ⊕ · `PATCH`/`DELETE` as above | `getProduct()`, `transactionStore` filter, client audit log |

### Suppliers

| Screen | Endpoints | Replaces |
|---|---|---|
| `/suppliers` | `GET /suppliers?q&type&city&status` · `POST /suppliers` · `PATCH /suppliers/{id}` · `DELETE /suppliers/{id}` | `listSuppliers()`, `supplierStore.*` |
| `/suppliers/[id]` | `GET /suppliers/{id}` · `GET /suppliers/{id}/purchase-orders` · `GET /suppliers/{id}/performance` · `GET /suppliers/{id}/contacts` · `GET /audit-logs/supplier/{id}` | `findSupplier()` + `listPurchaseOrders()` filtered client-side |

### Inventory

| Screen | Endpoints | Replaces |
|---|---|---|
| `/inventory/current-stock` | `GET /inventory/stock?godown_id&category_id&brand_id&status&q` (returns rows **and** KPIs) · `GET /godowns` · `GET /inventory/export` ⊕ | `getCurrentStock()` → `STOCK_ROWS` + hardcoded `INVENTORY_KPIS` |
| `/inventory/by-godown` | `GET /inventory/stock/by-godown` · `POST /inventory/transfers` ⊕ ("Transfer Stock") | same mock |
| `/inventory/low-stock` | `GET /inventory/low-stock?godown_id&supplier_id&status` · `POST /rfqs` (with `created_from: "low_stock"`) | `listLowStock()` + `sessionStorage` handoff |
| `/inventory/transactions` | `GET /inventory/transactions?type&godown_id&sku&date_from&date_to` · `POST /inventory/transactions` · `POST /inventory/transfers` · `GET /products?minimal=true` (SKU picker) | `listTransactions()`, `transactionStore.upsert()` |
| `/godowns` | `GET /godowns` (with computed SKU count, value, capacity %) · `POST /godowns` ⊕ · `PATCH /godowns/{id}` ⊗ | `listGodowns()` |

### Procurement

| Screen | Endpoints | Replaces |
|---|---|---|
| `/procurement/rfq` | `GET /rfqs?status&supplier_id&q` | `listRfqs()`, `rfqStore` |
| `/procurement/rfq/new` | `GET /products?minimal=true` · `GET /suppliers?status=active` · `POST /products/match` (line suggestions) · `POST /rfqs` · `POST /rfqs/{id}/send` | `rfqStore.upsert()` + regex `NORMALISATIONS` |
| `/procurement/rfq/[id]` | `GET /rfqs/{id}` · `PUT /rfqs/{id}` · `DELETE /rfqs/{id}` · `POST /rfqs/{id}/send` · `GET /rfqs/{id}/pdf` · `GET /audit-logs/rfq/{id}` | store lookup by number |
| `/procurement/quotations` | `GET /quotations?status&supplier_id&rfq_id` · `DELETE /quotations/{id}` · `POST /comparisons` (Compare Selected / Compare All) | `listQuotations()`, `quotationStore` |
| `/procurement/comparison` | `POST /comparisons` or `GET /rfqs/{id}/quotation-comparison` · `GET /comparisons/{id}` · `PATCH /comparisons/{id}/lines/{line_id}` · `POST /comparisons/{id}/reset` · `POST /comparisons/{id}/convert-to-po` | `getComparison()` → static rows/terms + `sessionStorage` handoff |
| `/procurement/purchase-orders` | `GET /purchase-orders?status&supplier_id&date_from&date_to` | `listPurchaseOrders()`, `poStore` |
| `/procurement/purchase-orders/new` | `GET /suppliers` · `GET /products?minimal=true` · `GET /rfqs?status=sent` (RFQ link autocomplete) · `GET /rfqs/{id}` (pull items) · `POST /purchase-orders` · `POST /purchase-orders/{id}/approve` · `POST /purchase-orders/{id}/send` | `poStore.upsert()`, `RFQ_LINES_BY_NUMBER` |
| `/procurement/purchase-orders/[id]` | `GET /purchase-orders/{id}` · `PUT` · `DELETE` (draft) · `POST /purchase-orders/{id}/cancel` · `GET /purchase-orders/{id}/pdf` · `GET /audit-logs/purchase_order/{id}` | store lookup by number |
| `/procurement/proforma` | `GET /proforma-invoices?status&supplier_id` | `listProforma()` |
| `/procurement/proforma/[id]` | `GET /proforma-invoices/{id}` · `GET /proforma-invoices/{id}/variance` · `POST /proforma-invoices/{id}/raise-query` ⊕ · `POST /proforma-invoices/{id}/approve` ⊗ · `GET /documents/{doc_id}/download` ⊕ | `getProformaById()` (returns identical lines for every record) |
| `/goods-receipt` | `GET /goods-receipts?status&godown_id&supplier_id` | `getGrnDraft().list` |
| `/goods-receipt/new` | `GET /purchase-orders/open` · `GET /purchase-orders/{id}/receipt-lines` · `POST /goods-receipts` · `PUT /goods-receipts/{id}` · `POST /goods-receipts/{id}/confirm` · `POST /goods-receipts/{id}/documents` ⊕ | `getGrnDraft()`, `grnStore.upsert()` |
| `/goods-receipt/[id]` | `GET /goods-receipts/{id}` · `GET /goods-receipts/{id}/pdf` · `POST /goods-receipts/{id}/reverse` ⊗ (replaces the unsafe Delete) · `GET /audit-logs/grn/{id}` | store lookup |
| **Supplier Invoice** ⊗ | `GET/POST /supplier-invoices` · `POST /supplier-invoices/{id}/match` · `POST /supplier-invoices/{id}/approve` | **no screen exists** |

### AI & documents

| Screen | Endpoints | Replaces |
|---|---|---|
| `/ai-documents` | `POST /documents/upload` ⊕ · `GET /documents?processing_status&document_type&supplier_id` · `GET /documents/{id}/status` (poll/SSE) · `POST /documents/{id}/process` ⊕ · `GET /documents/{id}/download` ⊕ | `listDocuments()` → static `AI_DOCUMENTS` |
| `/ai-documents/review` | `GET /documents/{id}/extraction` **(needs a document id in the route — it has none today)** · `PATCH /ai/extractions/{id}/fields/{field_id}` · `PATCH /ai/extractions/{id}/lines/{line_id}` · `POST /products/match` · `POST /ai/extractions/{id}/approve` · `POST /ai/extractions/{id}/reject` · `GET /products?minimal=true` | `getExtraction()` → static `EXTRACTION` + `EXTRACTION_PIPELINE` |
| `/assistant` | `POST /assistant/query` · `GET /assistant/suggestions` | regex table in `data/assistant.ts` |

### Operations & admin

| Screen | Endpoints | Replaces |
|---|---|---|
| `/alerts` | `GET /alerts?severity&category&status` · `GET /alerts/summary` · `POST /alerts/{id}/read` · `POST /alerts/read-all` · `POST /alerts/{id}/dismiss` ⊗ | `listAlerts()` + React-state read flags |
| `/reports` | `GET /reports/{key}?date_from&date_to&godown_id&category_id` ⊕ · `POST /reports/{key}/export` ⊕ | nothing — all 12 cards are links, all filters inert |
| `/settings` | `GET /company` · `PATCH /company` · `GET /company/settings` · `PUT /company/settings` · `GET/PUT /company/sequences` | **nothing — the entire page is inert** |
| `/users` | `GET /users?role&status&q` · `DELETE /users/{id}` · `GET /invitations` · `POST /invitations` · `POST /invitations/{id}/resend` · `DELETE /invitations/{id}` · `GET /audit-logs?entity_type=team_member` · `PATCH /users/{id}` ⊗ (change role/godown) | `team-store.ts` |
| `/system-admin` | `GET /platform/kpis` · `GET /platform/companies` · `POST /platform/companies` · `POST /platform/companies/{id}/suspend` · `/reactivate` · `GET /platform/users` · `POST /platform/impersonate` · `POST /platform/impersonate/stop` · `GET /platform/activity` | `COMPANIES` constant + React state + `impersonate()` |

---

## 2. Mock service → endpoint cutover table

The frontend is one file away from the backend. Each `mockRequest` path becomes a real call:

| Current mock | Real endpoint | Shape change needed |
|---|---|---|
| `/auth/login` | `POST /api/v1/auth/login` | `{identifier,password}`; response gains `permissions[]`, `godown_scope`, `landing_route` |
| `/dashboard/summary` | `GET /dashboard/summary` | none |
| `/products` | `GET /products` | paged envelope + `facets` replaces `{products, categories, brands, godowns, total}` |
| `/products/{sku}` | `GET /products/by-sku/{sku}` | `stock` block instead of `currentStock`/`godowns[]` |
| `/suppliers`, `/suppliers/{id}` | same | paged envelope; performance block |
| `/inventory/stock` | `GET /inventory/stock` | KPIs computed for the filtered set |
| `/inventory/transactions` | `GET`/`POST /inventory/transactions` | server applies the sign; `remarks` now persisted |
| `/inventory/low-stock` | `GET /inventory/low-stock` | `supplier`/`lastPrice` now from `supplier_products` |
| `/godowns` | `GET /godowns` | computed `skus`/`value`/`capacity_used` |
| `/rfqs` | `GET /rfqs` | paged |
| `/quotations` | `GET /quotations` | paged |
| `/quotations/comparison` | `GET /rfqs/{id}/quotation-comparison` **or** `POST /comparisons` | recommendation now computed + explained |
| `/purchase-orders` | `GET /purchase-orders` | `received` % now derived from GRNs |
| `/purchase-orders/draft` | **delete** — replaced by `POST /comparisons/{id}/convert-to-po` and real drafts | |
| `/proforma`, `/proforma/{id}` | same | each record returns its own lines (today they all share one) |
| `/grn/draft` | split into `GET /purchase-orders/open` + `GET /purchase-orders/{id}/receipt-lines` + `POST /goods-receipts` | pending quantity replaces ordered quantity |
| `/documents` | `GET /documents` | live `processing_status`/`stage`/`progress` |
| `/documents/extraction` | `GET /documents/{id}/extraction` | **id must be added to the route** |
| `/alerts` | `GET /alerts` | per-user read state |

All `localStorage` record stores (`inventoryai:*`) are deleted; the dirty-form guard, confirmation dialogs, print headers and audit-trail component stay as they are and simply bind to server data.

---

## 3. Workflow sequences

### 3.1 Low stock → RFQ → send

```mermaid
sequenceDiagram
  participant U as Buyer
  participant FE as Next.js
  participant API as FastAPI
  participant DB as PostgreSQL
  participant Q as Celery
  U->>FE: Select 5 low-stock items → Create RFQ
  FE->>API: GET /inventory/low-stock (already loaded)
  FE->>API: POST /rfqs {items, supplier_ids, created_from:"low_stock"}
  API->>DB: allocate RFQ-2026-00059 (document_sequences FOR UPDATE)
  API->>DB: insert rfqs + rfq_items + rfq_suppliers
  API-->>FE: 201 {id, rfq_number, status:"draft"}
  U->>FE: Send RFQ (confirm dialog)
  FE->>API: POST /rfqs/{id}/send
  API->>DB: validate ≥1 item, ≥1 supplier with email
  API->>Q: render PDF + email each supplier
  API->>DB: rfqs.status='sent'; rfq_suppliers.sent_at; audit_logs
  API-->>FE: 202 {job_id, recipients[]}
  Q->>DB: documents (PDF) + document_links + outbound_messages
  Q-->>FE: SSE job progress → per-recipient delivery state
```

### 3.2 AI document processing (upload → extraction → review → approval)

```mermaid
sequenceDiagram
  participant U as User
  participant API as FastAPI
  participant S3
  participant Q as Celery (ai queue)
  participant LLM as Llama (Bedrock)
  participant DB as PostgreSQL
  U->>API: POST /documents/upload (xlsx, 48 KB)
  API->>API: sniff MIME, size, SHA-256
  API->>DB: SELECT by (company_id, sha256) → duplicate?
  API->>S3: put object (SSE)
  API->>DB: insert documents(processing_status='queued') + ai_processing_jobs
  API-->>U: 202 {document_id, job_id}
  Q->>S3: fetch
  Q->>Q: parse sheets / OCR (Textract for jpg,png,scanned pdf)
  Q->>DB: update stage='Reading document', progress=20
  Q->>DB: lookup document_schema_mappings (supplier + doc type) ─ Redis cache first
  alt mapping found
    Q->>Q: apply stored column → canonical field mapping
  else no mapping
    Q->>LLM: propose column mapping (headers + 3 sample rows only)
    Q->>DB: store proposed mapping (status='proposed') for human confirmation
  end
  Q->>DB: stage='Extracting fields', progress=45
  Q->>LLM: extract header fields + line items (schema-constrained JSON)
  Q->>DB: ai_extraction_results + ai_extracted_fields + ai_extracted_lines
  Q->>Q: per line → match ladder (exact → alias → barcode → trigram → embedding → LLM)
  Q->>DB: ai_match_candidates; stage='Matching products to your SKUs', progress=68
  Q->>DB: compute confidences; documents.processing_status = 'extracted' (label "Needs Review")
  Q->>DB: alert if overall_confidence < ai_review_confidence_threshold
  U->>API: GET /documents/{id}/extraction
  U->>API: PATCH …/lines/{id} {matched_variant_id, save_supplier_alias:true}
  API->>DB: ai_review_actions (before/after) + supplier_products upsert
  U->>API: POST /ai/extractions/{id}/approve
  API->>DB: re-validate all lines matched; RECOMPUTE totals server-side
  API->>DB: insert supplier_quotations + items; link document; documents.processing_status='approved'
  API-->>U: 201 {quotation_id, quotation_number}
```

**Guardrail:** the LLM's arithmetic is never trusted — `line_total`, tax and document totals are recomputed from quantity × price × rate by backend code before anything is written (`ai_never_autoapprove_financials`).

### 3.3 Quotation comparison → split PO

```mermaid
sequenceDiagram
  participant U as Purchase Manager
  participant API
  participant DB
  U->>API: POST /comparisons {rfq_id} (or {quotation_ids[]})
  API->>DB: load rfq_items + all quotation items + supplier performance
  API->>API: score each cell (landed cost, delivery, on-time %, quality, warranty)
  API->>DB: insert quotation_comparisons + lines (recommended + reason + score)
  API-->>U: 201 matrix + totals + savings + warnings
  U->>API: PATCH /comparisons/{id}/lines/{line} {supplier_id} (override)
  API->>DB: update selected_quotation_item_id + override_reason
  U->>API: POST /comparisons/{id}/convert-to-po
  API->>DB: group selections by supplier
  loop per supplier
    API->>DB: allocate PO number; insert purchase_orders + items (carrying quotation_item_id, rfq_item_id)
  end
  API->>DB: comparison.status='converted'; quotations.status='converted'
  API-->>U: 201 [{po_number, total}, …]
```

### 3.4 PO approve → send

`POST /purchase-orders/{id}/approve` → validate completeness + approver limit → `approved` + audit → `POST …/send` → render PDF on **buyer letterhead** → email supplier → `sent` + `outbound_messages` → What's-Next panel offers Proforma / GRN.

### 3.5 Proforma received → variance check

```
POST /documents/upload (proforma PDF)
  → AI extraction → POST /ai/extractions/{id}/approve
  → creates proforma_invoices + items with po_unit_price_snapshot from the linked PO
  → server computes document_variances (price/total)
  → if variance ≠ 0 → alert "Proforma total differs from PO-2026-00123 by ₹4,500" (high)
  → buyer reviews → POST /proforma-invoices/{id}/approve  (or /raise-query → email supplier)
```

### 3.6 Goods receipt → inventory (the critical path)

```mermaid
sequenceDiagram
  participant U as Godown Manager
  participant API
  participant DB
  participant Q as Celery
  U->>API: GET /purchase-orders/open
  U->>API: GET /purchase-orders/{id}/receipt-lines
  API-->>U: lines with pending_quantity (not ordered_quantity)
  U->>API: POST /goods-receipts {lines, transport, status:"draft"}
  API->>DB: insert goods_receipts + items; compute rejected = received − accepted
  U->>API: POST /goods-receipts/{id}/confirm  (Idempotency-Key)
  Note over API,DB: ONE transaction
  API->>DB: lock GRN; assert status='draft'
  API->>DB: re-validate against current pending qty
  API->>DB: insert inventory_transactions (GOODS_RECEIPT, +accepted) per line
  API->>DB: upsert stock_balances
  API->>DB: create batches (batch-tracked variants)
  API->>DB: purchase_order_items.received_quantity += accepted; line_status
  API->>DB: purchase_orders.received_pct + status
  API->>DB: document_variances for short/excess/damaged/wrong
  API->>DB: goods_receipts.status + confirmed_by/at; audit_logs
  API-->>U: 200 {postings[], po.received_pct, variances[]}
  API->>Q: (after commit) alerts, supplier performance, reorder evaluation
  Q->>DB: alerts: "Received quantity mismatch", low-stock recheck
```

### 3.7 Supplier invoice → 3-way match ⊗

```
POST /documents/upload (invoice PDF) → extraction → approve
  → supplier_invoices + items, linked to PO and GRN
  → POST /supplier-invoices/{id}/match
      compare: invoice qty vs GRN accepted qty     → quantity variance
               invoice rate vs PO rate             → price variance
               invoice tax vs recomputed tax       → tax variance
      within tolerance → match_status='matched' → approvable
      outside          → match_status='variance' → document_variances + alert, approval blocked
  → POST /supplier-invoices/{id}/approve (Accountant) → payable
```

### 3.8 Manual inventory movement

```
POST /inventory/transactions {txn_type:"DAMAGE", quantity:"4", remarks required}
  → server applies sign (−4), checks godown scope and resulting balance ≥ 0
  → ledger insert + balance upsert (one transaction)
  → if balance crosses reorder point → low-stock alert
```
Transfer uses `POST /inventory/transfers` and writes the OUT/IN pair with `counterpart_txn_id`.

### 3.9 Low-stock / reorder alert generation

```
Celery beat (hourly)
  → for each company: SELECT from stock_balances JOIN product_variants
       WHERE available_quantity <= reorder_point (× low_stock_threshold_mode multiplier)
  → upsert alerts (dedupe by rule_code + reference_id + open status — never spam the same alert hourly)
  → severity: out_of_stock → critical; below reorder → high
  → daily digest email when alert_daily_low_stock_digest is on
```
Other scheduled rules: PO delivery delay (daily, `expected_delivery_date < today − grace` and status in sent/partially_received), quotation expiry (daily, `valid_until` within 3 days), batch expiry (daily), AI low-confidence (event-driven at extraction), stock-balance reconciliation (nightly, raises a `System` alert on drift).

### 3.10 Invite → accept → active member

```
POST /invitations → token hashed, email queued, status 'pending', expires in 7 days
GET /invitations/{id} (public, token in query) → validity check
POST /invitations/{id}/accept {token, password} → users row activated + user_godown_access
  → invitation 'accepted'; audit 'invitation_accepted'; user appears in /users, disappears from Pending
```

---

## 4. Polling, streaming and refresh strategy

| UI element | Strategy |
|---|---|
| Document processing progress bar | SSE `/notifications/stream`, fallback poll `GET /documents/{id}/status` every 2 s while `queued\|processing` |
| Alert badge | Poll `GET /alerts/summary` every 60 s, or SSE |
| Dashboard | Fetch on mount; `stale-while-revalidate` 60 s |
| Lists | Fetch per filter change with a 300 ms debounce on `q`; cursor pagination |
| GRN/PO forms | Fetch on open; `If-Match` on save to detect a concurrent edit |
| After a write | Re-fetch the affected resource from the response body — never patch client state blindly (the prototype's local stores diverge from the server's computed totals) |
