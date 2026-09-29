# 09 — GAPS, INCONSISTENCIES & RECOMMENDATIONS

What the prototype promises but cannot do, what the business needs but the prototype does not show, and what must be corrected rather than designed around.

**Severity:**
- **CRITICAL** — data integrity, money correctness, security, or the core loop is broken. Must be fixed in Phase 1.
- **IMPORTANT** — real business impact; belongs in Phase 1 unless deliberately deferred.
- **OPTIONAL** — safe to defer without harming the product.
- **FUTURE** — Phase 2+; design space reserved, nothing built now.

---

## 1. CRITICAL

### C1 — Confirming a Goods Receipt posts no inventory
`grn-form.tsx` → `confirm()` waits 800 ms, sets `confirmed=true`, writes the GRN to `localStorage`, and shows *"one inventory transaction per accepted line"*. **No transaction is created.** Stock on every screen comes from the static `PRODUCTS[].godowns[]` array.
**Impact:** the entire RFQ → PO → GRN → Inventory loop — the product's reason to exist — is a display.
**Fix:** `POST /goods-receipts/{id}/confirm` performs the atomic posting sequence in `04 §3.18` under rules BR-GRN-06/07.

### C2 — The Product form edits stock directly
`ProductFormDialog` exposes `currentStock` as an editable number and `productStore.upsert()` saves it. This is precisely the anti-pattern the brief forbids.
**Fix:** remove the field from the edit path. On create it becomes an `OPENING_STOCK` posting; afterwards stock changes only through `POST /inventory/transactions` (BR-INV-01). The Product form keeps every other field — nothing is lost.

### C3 — The Supplier Invoice module does not exist
No route, component, type or mock data anywhere in the codebase. Yet the workflow requires it, the GRN form's What's-Next panel offers a "Record Supplier Invoice" link that leads nowhere, and `INV-` already appears as a transaction reference prefix.
**Impact:** no three-way match, no payables, no input-tax-credit record — the financial half of procurement is absent.
**Fix:** build `supplier_invoices`/`_items` (schema ready in `02 §6.13`) plus list, detail and match screens.

### C4 — Two different money formulas, both client-side
`lib/tax.ts summarise()` computes `taxable + tax + freight` then rounds. `lib/po-store.ts poTotal()` computes `Σ qty×price×(1−disc)×(1+gst) + freight`, unrounded. The same PO shows different totals depending on which screen you are on.
**Impact:** a purchase order sent to a supplier may not match the order stored in the system.
**Fix:** delete both client formulas. The server computes totals (BR-TAX-01…10) and returns them; the UI renders the response.

### C5 — RBAC is decorative
Role is consulted in exactly three places, all client-side: the System Admin route guard, the System Admin menu item, and hiding Remove for an Owner. Every other action is available to every signed-in user, and every route is reachable by URL.
**Impact:** a Staff user can approve purchase orders, delete products, and read every godown's valuation.
**Fix:** permission-checked endpoints (`07`), godown scoping, RLS. The UI keeps every screen — it just hides what the token forbids.

### C6 — A confirmed GRN can be deleted, and the UI says inventory is not reversed
`grn-detail-screen.tsx` offers Delete with the description *"The inventory transactions it already created are not reversed."* That sentence describes a data-integrity hole in plain language.
**Fix:** confirmed GRNs are terminal (BR-GRN-08). Corrections go through `POST /goods-receipts/{id}/reverse`, which posts offsetting transactions and leaves both documents visible.

### C7 — Master data is hard-deleted with no in-use check
`productStore.remove()` / `supplierStore.remove()` erase the record. A deleted supplier leaves POs pointing at a name that no longer exists.
**Fix:** soft delete + blocking rule BR-MD-04, returning the blocking references so the UI can explain why.

### C8 — Document numbers are generated as `max + 1` in the browser
`nextPoNumber()` scans `localStorage` for the highest trailing digits. Two users creating a PO at the same time produce the same number.
**Fix:** `document_sequences` with row-level locking inside the creating transaction (BR-NUM-01).

### C9 — Filtering, search, sorting and pagination are client-side over the full dataset
`use-table-filter.ts` filters an in-memory array; `TablePagination` is passed `page=1, pageSize=filtered.length` and its buttons do nothing. The app claims 1,248 SKUs while shipping 12.
**Impact:** the first real tenant with a few thousand SKUs and a year of transactions makes every list page unusable.
**Fix:** server-side filtering and keyset pagination on every list endpoint; the existing filter components bind to query parameters instead of arrays.

### C10 — A confirmed GRN never updates the purchase order
`PurchaseOrder.received` is static mock data. Nothing recomputes it, and `purchase_order_items` do not exist, so there is no per-line received quantity.
**Impact:** partial delivery — the most common real-world case and an explicit requirement — cannot be tracked. The second GRN against a PO has no idea what the first one received.
**Fix:** `goods_receipt_items.purchase_order_item_id` + `received_quantity` accumulation + derived `line_status`/`received_pct` (BR-PO-05).

### C11 — Rejected goods have nowhere to go
The GRN captures `rejectedQty` and `damaged / expired / wrong_product / wrong_variant / wrong_model / wrong_brand`, then nothing consumes any of it. There is no return, no debit note, no scrap.
**Impact:** goods physically present in the godown are invisible to the system, and the supplier is never debited.
**Fix:** `purchase_returns` (`02 §6.14`) and the rule that rejected quantities never enter stock (BR-GRN-06).

### C12 — Cross-document links are free text, and GRN lines match positionally
`PoRecord.linkedRfq` is a typed string; `GrnRecord.poNumber` is a string; GRN lines are copied from `PO_LINES_BY_NUMBER` by array position with no line identity.
**Impact:** renaming or re-numbering breaks the chain silently; partial receipts cannot be attributed to a PO line; no referential integrity anywhere in the procurement chain.
**Fix:** real foreign keys at header **and line** level (`03 §4`).

### C13 — The document dropzone is not connected
`DocumentDropzone` accepts an `onFiles` callback that `ai-documents/page.tsx` never passes. Nothing can be uploaded. The GRN attachment input is likewise unwired, and "Open file" and "Re-upload" have no handlers.
**Impact:** the AI capability — the product's main differentiator — has no input path.
**Fix:** `POST /documents/upload` with SHA-256 dedupe and job-based progress (`04 §3.19`).

### C14 — Inter-state supply is hardcoded to `true`
Every call to `summarise()` passes `interState: true`, so IGST is always applied and CGST/SGST are dead code — even though the seeded buyer is in Madhya Pradesh and several suppliers are too.
**Impact:** wrong tax on every intra-state purchase; documents that would not survive an audit.
**Fix:** derive from supplier vs place-of-supply state codes and freeze on the document (BR-PO-06).

---

## 2. IMPORTANT

| ID | Finding | Evidence | Recommendation |
|---|---|---|---|
| I1 | **User edits are silently discarded.** PO date, PO expected delivery, RFQ date, RFQ delivery date, GRN date, `receivedBy`, `vehicleNumber`, `transporter`, `lrNumber`, `ewayBill` are uncontrolled inputs; `persist()` writes defaults instead. Transaction `remarks` is captured in state and never saved. | `po-form.tsx`, `rfq-form.tsx`, `grn-form.tsx`, `new-transaction-dialog.tsx` | Make them controlled and persist them. E-way bill and LR number are legally significant for goods movement in India |
| I2 | Godown scope is captured on every member and invitation and then ignored | `team-store.ts`, no consumer | Enforce per `07 §4` |
| I3 | The entire Settings page is inert — GSTIN, numbering prefixes, GST defaults, rounding, AI thresholds, alert rules | `settings/page.tsx` | Wire to `company_settings`; these values are inputs to tax, numbering and AI behaviour, so they cannot stay decorative |
| I4 | Alert read state lives in React state, there is no dismiss, and no rule engine generates alerts | `alerts-screen.tsx`, static `ALERTS` | `alerts` + `alert_reads` + scheduled rules (`05 §3.9`) |
| I5 | Comparison recommendations are hardcoded strings; the sourcing decision is lost in `sessionStorage` | `data/procurement.ts`, `handoff.ts` | Compute and explain the recommendation; persist the decision in `quotation_comparisons` |
| I6 | `reserved` and "Available = qty − reserved" appear on four screens, but nothing can create a reservation | `StockRow`, `GodownStock` | Keep the column at 0 and say so, or hide it until Sales Orders exist. Do not fabricate a source |
| I7 | `Quotation.source = "Manual Entry"` exists with no form to create one | `data/procurement.ts` | Add `POST /quotations` + a manual-entry screen; not every supplier sends a file |
| I8 | Proforma is read-only, and `getProformaById()` returns the **same line items for every record** | `procurement.service.ts` | Real per-record data; add create/edit for manually received proformas |
| I9 | No batch or expiry anywhere, despite `GrnIssue = expired` and a catalogue of atta, oil, tea and namkeen | `data/products.ts` | Ship `batches` in the first migration; retrofitting a ledger later is painful |
| I10 | No unit conversion, though `Box`, `Pack` and `Set` are offered as purchase units in the RFQ form while stock is kept in `Nos` — and the seeded RFQ data uses `Pkt` and `Bag`, which no picker even offers | `UNITS` in `rfq-form.tsx:39`; `RFQ_LINES_BY_NUMBER` in `data/procurement.ts` | `product_uom_conversions` + conversion frozen on each transaction; seed the full UoM list |
| I11 | No column/schema-mapping UI, though the dropzone accepts `.xlsx`/`.csv` | requirement STEP 11 | Build the confirm-mapping screen; the backend model is ready (`08 §5`) |
| I12 | Invitations never expire; password minimum is 6 characters; the mock compares plaintext | `team-store.ts`, `auth.service.ts` | 7-day expiry, ≥8 chars, Argon2id (BR-AUTH-02/08) |
| I13 | Excess receipt is accepted with no policy | `grn-form.tsx` auto-detects `excess` and continues | `allow_grn_excess_receipt` + tolerance (BR-GRN-02) |
| I14 | "Add Godown" and "Transfer Stock" are decorative | `godowns/page.tsx`, `by-godown/page.tsx` | `POST /godowns`, `POST /inventory/transfers` |
| I15 | The extraction review route carries no document id (`/ai-documents/review`), and the mock service has no per-document extraction path | `documents.service.ts` | `/ai-documents/review/[documentId]` + `GET /documents/{id}/extraction` |
| I16 | Dashboard and inventory KPIs are hardcoded and contradict the seeded rows (1,248 SKUs vs 12 products) | `data/dashboard.ts`, `data/inventory.ts` | Real aggregates; KPIs must reflect the filtered dataset |
| I17 | Denormalised counters have no source of truth: `quotesReceived`, `items`, `value`, `productsSupplied`, `totalPurchases`, `openOrders`, `onTimeDelivery`, `qualityScore`, `usersCount`, godown `skus`/`value`/`capacityUsed` | throughout | Derive them (`02 §9`); only `received_quantity`, `received_pct` and `stock_balances` stay denormalised, and each is written with its source |
| I18 | Freight is added untaxed | `lib/tax.ts` | Under GST, supplier-charged freight on a tax invoice is normally taxable at the principal supply's rate. Make it a configurable, taxable charge |
| I19 | Numbering format differs from the brief (5-digit `PO-2026-00123` vs 6-digit `PO-2026-000001`) | `data/procurement.ts` vs brief | Make padding configurable; default to the UI's 5 so existing references stay valid |
| I20 | Impersonation has no time limit, no reason capture and no server-side audit | `auth.service.ts` | 30-minute scoped token, reason required, `impersonated_by` on every audit row |

---

## 3. OPTIONAL

| ID | Finding | Recommendation |
|---|---|---|
| O1 | The Reports page is twelve links plus three inert filters and two inert Export buttons | Implement 3–4 reports users actually ask for (stock valuation, PO vs received, supplier performance, low stock) rather than twelve stubs |
| O2 | Five Export buttons and one Import button do nothing | Implement export as an async job returning a signed URL; implement Excel import for the catalogue first |
| O3 | Product "Images & Documents" is an empty placeholder | `product_images` + `document_links` |
| O4 | "Raise query" on a proforma does nothing | `POST /proforma-invoices/{id}/raise-query` → email + status |
| O5 | The assistant is a regex table over canned answers | Real intent classification with hand-written query functions (`04 §3.22`); keep the read-only guarantee the UI advertises |
| O6 | `product.emoji` is a display gimmick | Harmless; keep as `display_emoji` |
| O7 | The Supplier detail page renders static data while the list renders the store | Resolves itself once both read the same API |
| O8 | PO header totals do not reconcile with their own line items — `PO-2026-00123` states ₹3,41,720 while its two lines sum to ₹4,12,720 including GST (`PO-2026-00122` does reconcile) | Mock-data artefact, but it illustrates C4 precisely: when totals are stored rather than derived, they drift from the lines they claim to summarise |

---

## 4. FUTURE (Phase 2+)

| ID | Capability | Why it is not now |
|---|---|---|
| F1 | Sales orders, dispatch and stock reservation | The `reserved` field exists but Phase 1 is explicitly purchase-side |
| F2 | Payments, outstanding, ageing, supplier ledger | Payment terms are captured everywhere but nothing consumes them; needs an accounting decision first |
| F3 | Serial-number tracking | `tracking_type` already allows `serial`; no UI demand yet |
| F4 | e-Invoice IRN generation and GSTR reconciliation | Columns reserved; only relevant above the turnover threshold |
| F5 | Multi-currency and import purchases | `currency_code` reserved; the catalogue is domestic |
| F6 | Landed-cost allocation (freight/duty across lines) | Requires the costing decision in F2 |
| F7 | Barcode scanning / mobile GRN | Barcode/EAN already modelled |
| F8 | Demand forecasting and automatic reorder suggestions | Needs 6–12 months of real transaction history |
| F9 | Supplier portal for direct quotation entry | Removes most document processing, but needs supplier adoption |
| F10 | WhatsApp/email ingestion of supplier documents | `documents.source` already allows `email`/`whatsapp` |

---

## 5. UI features that cannot work without backend support

| UI element | Needs |
|---|---|
| Document upload, progress bar, stage text, confidence meters | Upload endpoint, Celery pipeline, job status, OCR, LLM extraction |
| "Needs Review" queue and the whole Extraction Review screen | Extraction storage, per-field provenance, match candidates |
| AI product suggestions while typing an RFQ line | Match endpoint + embeddings |
| AI Assistant | Intent classification + guarded query execution |
| Current Stock, Low Stock, Stock by Godown, product stock split | Transaction ledger + balance cache |
| PO received % and partial delivery | PO line quantities updated by GRN confirmation |
| Proforma vs PO difference cards | Linked PO, line snapshots, variance computation |
| GRN "Import from PO" with correct pending quantities | PO line balances |
| Quotation comparison, savings, recommendations | Real quotation data + scoring |
| Alerts of every kind | Rule engine + scheduler |
| Audit Trail panels (already built) | `audit_logs` |
| Users, invitations, accept-invite | Auth, email delivery, token validation |
| System Admin, impersonation | Platform APIs, scoped tokens, audit |
| Settings | Persistence, and consumption by tax/numbering/AI |
| Print/PDF with letterhead | Server-rendered PDFs stored as documents |
| Every filter, search box and pagination control | Server-side querying |

---

## 6. Inconsistencies to correct rather than design around

| # | Inconsistency | Correction |
|---|---|---|
| 1 | One flat `Product` carries SKU, stock, pricing and attributes, yet GRN issue codes include `wrong_variant` and `wrong_model` | Split `products` / `product_variants`; today's products map 1:1 to a single variant, so no UI change is forced |
| 2 | `DocStatus` is a single 12-value union shared by RFQ, quotation, PO and GRN, so `partially_received` is a legal RFQ status | Per-document status enums with explicit state machines (`06 §14`) |
| 3 | Detail routes key off business numbers (`/purchase-orders/PO-2026-00123`) while proforma and supplier use ids | Expose UUID as canonical, keep number lookups as an alternative; be consistent |
| 4 | `godown` is a string everywhere (`"Main Godown"`), and a name change would orphan every record | `godown_id` FK |
| 5 | Supplier, product and category are stored as display names on documents rather than ids | FK + snapshot column where the printed text matters |
| 6 | `paymentTerms` is free text (`"30 Days"`) but drives nothing | Keep the label, add `payment_terms_days` for due-date maths |
| 7 | `Company.plan` exists with no entitlement logic | Either enforce plan limits (users, documents/month, storage) or drop the field |
| 8 | The tenant's own identity is a hardcoded `BUYER_PROFILE` constant used on printed documents | Read from `companies` — otherwise every tenant prints "Acme Traders" on their purchase orders |
| 9 | Client-side audit log in `localStorage`, capped at 2,000 entries | Server-side `audit_logs`; keep the excellent UI component |
| 10 | `handoff.ts` passes business state between screens through `sessionStorage` with read-once semantics | Server-side drafts and real ids; the pattern loses data on refresh and cannot be audited |

---

## 7. Recommended sequencing

| Phase | Scope | Outcome |
|---|---|---|
| **1A — Foundation** (3–4 wks) | Tenancy, RLS, auth/JWT, roles & permissions, users & invitations, company settings, numbering sequences, masters (categories, brands, UoMs, godowns, products/variants, suppliers), audit log, S3 | The prototype's masters run on real data with real access control |
| **1B — Inventory core** (2–3 wks) | `inventory_transactions`, `stock_balances`, transfers, adjustments, batches, low-stock/valuation queries, reconciliation job | **C1/C2 closed** — stock becomes truth |
| **1C — Procurement** (4–5 wks) | RFQ (+send), quotations, comparison + scoring, PO (+approve/send), proforma + variance, **GRN with atomic posting**, PO fulfilment tracking, purchase returns | **C3/C10/C11 closed** — the loop closes |
| **1D — Documents & AI** (4–5 wks) | Upload + dedupe, Celery pipeline, OCR, extraction, schema mapping + confirm UI, SKU match ladder, embeddings, review & approve, supplier-alias learning | The differentiator becomes real |
| **1E — Supplier invoice & hardening** (2–3 wks) | Invoices + 3-way match, alert rule engine, reports, exports, rate limits, load testing, penetration testing | Audit-ready |
| **2** | Sales orders & reservations, payments & ageing, forecasting, mobile GRN, supplier portal | |

Frontend work runs alongside: replace `mockRequest` with `fetch` module by module (`05 §2`), add server-side pagination, gate actions by permission, and build the four missing screens (Supplier Invoice, Purchase Return, Schema Mapping, Godown form).

---

## 8. Final recommended architecture

| Layer | Choice | Rationale |
|---|---|---|
| **Frontend** | Next.js 16 / React 19 / TypeScript / Tailwind / shadcn — **unchanged** | The prototype is good; it needs data, not redesign |
| **Backend** | FastAPI **modular monolith** (`app/modules/{auth,catalog,inventory,procurement,documents,ai,alerts,platform}`) | One deployable, one database transaction across PO→GRN→inventory. Microservices here would mean distributed transactions over an inventory ledger — all cost, no benefit at this scale |
| **ORM / migrations** | SQLAlchemy 2.x (async) + Alembic | |
| **Database** | PostgreSQL 16 + `pgvector`, `pg_trgm`, `pgcrypto` — **single source of truth** | RLS for tenancy; one engine for relational, text-similarity and vector search keeps the stack small |
| **Cache** | Redis — sessions, permissions, schema mappings, dashboard counters, job progress, idempotency keys. **Never authoritative** | |
| **Queue / workers** | Celery + Redis broker; queues `default`, `documents`, `ai`, `email`, `reports`; Celery beat for scheduled rules | |
| **Object storage** | S3, SSE-KMS, lifecycle rules, pre-signed URLs (5 min) | |
| **OCR** | AWS Textract for scanned PDFs and images; `openpyxl`/`pandas` for Excel; `pdfplumber` for digital PDFs | Only pay for OCR when the file actually needs it |
| **LLM** | Llama 3 8B on Bedrock as the default tier, 70B on escalation; Titan embeddings for pgvector | Matches the stated preference; the match ladder keeps LLM calls rare |
| **Email** | SES with delivery/bounce webhooks recorded in `outbound_messages` | |
| **PDF** | WeasyPrint or Playwright rendering HTML templates, stored as `documents` | Reuses the letterhead conventions the UI already implements |
| **Auth** | JWT access (15 min) + rotating refresh (30 d, httpOnly); Argon2id | |
| **Infrastructure** | ECS Fargate (api + workers), RDS PostgreSQL Multi-AZ, ElastiCache Redis, S3, ALB, CloudWatch, Secrets Manager, ECR | Managed services; no Kubernetes at this stage |
| **Observability** | Structured JSON logs with `request_id`, OpenTelemetry traces, Sentry, `pg_stat_statements`, AI cost dashboards per tenant | |
| **CI/CD** | GitHub Actions → migrations → tests (incl. cross-tenant negative tests) → deploy; blue/green on ECS | |
| **Backups** | RDS PITR (7 days) + nightly logical dumps to S3; documented restore drill; S3 versioning | |

**Explicitly not recommended:** microservices, a separate vector database, event sourcing for inventory (the append-only ledger already provides the audit properties without the complexity), a GraphQL layer, and any design in which Redis or the LLM holds state the database does not.

---

## 9. Quality-check verification

| Check | Status | Where |
|---|---|---|
| Every UI screen has data entities | ✅ | `01 §3` ↔ `02 §2` |
| Every create/edit/delete action has an API | ✅ | `04 §2`, `05 §1` |
| Every UI table has a backend source | ✅ | `05 §1` |
| Every important workflow has API support | ✅ | `05 §3` |
| Inventory is transaction-based | ✅ | `02 §5`, BR-INV-01 |
| Multi-tenancy supported | ✅ | `02 §1.1`, `06 §16` |
| AI data auditable | ✅ | `08 §3` (`ai_review_actions`, jobs, candidates) |
| Documents traceable to business records | ✅ | `document_links` |
| Partial GRNs supported | ✅ | `03 §4`, BR-PO-05 |
| PO vs GRN mismatch supported | ✅ | `goods_receipt_items.issue_type`, `document_variances` |
| PO vs Invoice mismatch supported | ✅ | `04 §3.21` |
| Supplier-specific SKU mapping | ✅ | `supplier_products` |
| Supplier-specific schema mapping | ✅ | `08 §5` |
| Indian GST fields where appropriate | ✅ | `02 §7` — and **not** on RFQ/proforma as tax documents |
| Financial calculations deterministic and backend-owned | ✅ | BR-TAX-01…10 |
| AI cannot modify inventory without approval | ✅ | BR-AI-01/02 |
| RBAC supported | ✅ | `07` |
| Audit logging supported | ✅ | `06 §15` |
| Indexes defined | ✅ | `02 §12` |
| Unique constraints defined (not blindly global) | ✅ | `02 §13` — barcode unique **per tenant**, with the reasoning |
| Soft delete / cancellation strategy | ✅ | `02 §10` |
| No unnecessary microservices | ✅ | §8 |
| PostgreSQL is the source of truth | ✅ | §8 |
| Redis is cache only | ✅ | §8, `02 §16` |
| No arbitrary SQL by the LLM | ✅ | BR-AI-08 |

**How this table was verified.** An independent pass cross-checked every table, column, enum, endpoint and rule id referenced across all nine documents against `02`, and re-checked the load-bearing claims in `01` and `09` against the actual source files. It found and we corrected: six operations tables (`alerts`, `alert_reads`, `alert_rules`, `audit_logs`, `outbound_messages`, `notification_preferences`) that were referenced throughout but never given column definitions; four `company_settings` columns that rules depended on but did not exist (`allow_negative_stock`, `allow_nonstandard_gst`, `inventory_locked_through`, plus variance tolerances); a missing permission (`inventory.transfer_any`); three status enums omitted from the §11 catalogue; two enum definitions that disagreed with §11 (`proforma_invoices.status`, `quotation_comparisons.status`); `documents.status` vs `processing_status` naming drift in `05`'s diagrams; three tables with no endpoint to populate them (`product_uom_conversions`, `product_images`, `variant_godown_policies`); and two overstated claims about the codebase (an alert referencing invoice mismatches — no such alert exists; a duplicate key in `PO_ITEMS_BY_NUMBER` — there is none). The claims in C1–C14 were each re-verified against source.

---

## 10. The five things to decide before backend work starts

1. **Product vs variant** — adopt the split now (recommended, `02 §4`), or stay flat and accept that `wrong_variant`/`wrong_model` handling and precise SKU matching will be weak.
2. **Batch/expiry in Phase 1 schema** — recommended yes (columns now, UI later); retrofitting a populated ledger is expensive.
3. **Supplier Invoice in Phase 1** — recommended yes; without it there is no three-way match and the procurement loop stops at receipt.
4. **Approval policy** — is a purchase-value threshold with maker-checker required from day one, or is Owner-approves-everything acceptable at launch?
5. **Reserved stock** — confirm it stays 0 until Sales Orders exist, and decide whether the UI hides it until then.

Nothing in this document has been implemented. No frontend file was modified during this audit.
