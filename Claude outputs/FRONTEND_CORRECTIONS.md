# Frontend Corrections — Change Log

**Project:** InventoryAI · **Date:** 15 September 2026
Companion to `FRONTEND_ARCHITECTURE_CORRECTIONS.md` (why) and `FRONTEND_BACKEND_INTEGRATION_CHECKLIST.md` (what the backend must provide). This document is the record of **what changed, file by file**.

---

## 1. Critical corrections — status

| Code | Correction | Status | Evidence |
|---|---|---|---|
| C1 | GRN confirmation posts stock, advances the PO, writes variances and raises alerts in one call | ✅ Done | `receiving.api.ts › confirmGoodsReceipt` returns `GrnConfirmationResult`; the detail screen renders every posting with its resulting balance |
| C2 | Inventory represented as transactions + derived balance | ✅ Done | 32 seeded movements → 19 folded balances; no `setStock` exists |
| C3 | Editable Current Stock removed from the Product form | ✅ Done | Verified in browser: field absent; opening-stock section present on create only |
| C4 | Client-side RBAC no longer presented as security | ✅ Done | `PermissionDisclaimer` on Users and Roles; header comment in `permissions.ts` |
| C5 | Permission-based UI visibility | ✅ Done | Nav filtered by permission; `PermissionGate` / `PermissionButton` throughout |
| C6 | Confirmed GRN is reversed, never edited | ✅ Done | `reverseGoodsReceipt` posts mirror rows and links both documents |
| C7 | Per-document state machines replace the shared status union | ✅ Done | 8 tables in `state-machines.ts`; screens render only `allowedActions` |
| C8 | AI honesty — match rung named, simulation labelled | ✅ Done | `matching.ts` ladder; `MATCH_LABELS` rendered per line; "simulated" stated on the documents screen |
| C9 | *(not present in the original list)* | — | — |
| C10 | Receiving works from the pending balance | ✅ Done | Verified: after receiving 8 of 10, the form showed 2 pending and refused 99 |
| C11 | Document numbers from a sequence, not `max + 1` | ✅ Done | `numbering.ts`; forms show a preview with `PREVIEW_NUMBER_NOTE` |
| C12 | FK-like IDs in mock types; numbers are display only | ✅ Done | Every route is id-based; `grn.purchaseOrderId`, not `poNumber` |
| C13 | Single mock financial service | ✅ Done | `money.ts`; `lib/tax.ts` deleted; no component does money arithmetic |
| C14 | Inter-state derived from state codes | ✅ Done | `isInterState()`; the PO form's toggle removed |

---

## 2. Important corrections — status

| Code | Correction | Status |
|---|---|---|
| I1 | Supplier Invoice UI (list, detail, entry, three-way match) | ✅ Done — new |
| I2 | Purchase Return UI (list, detail, entry, posts negative stock) | ✅ Done — new |
| I3 | Manual quotation entry | ✅ Done — new |
| I4 | *(not present in the original list)* | — |
| I5 | Computed comparison recommendation with reason and spread | ✅ Done |
| I6 | No fake reservations | ✅ Done — column removed |
| I7 | *(not present in the original list)* | — |
| I8 | Per-godown reorder policy | ✅ Done |
| I9 | Batch capture on receipt, with expiry validation | ✅ Done |
| I10 | UoM conversions on purchase lines | ✅ Done |
| I11 | *(not present in the original list)* | — |
| I12 | Dashboard KPIs and lists from one query | ✅ Done |
| I13 | No decorative counts — every figure from a query | ✅ Done |
| I14 | Settings screen writes real values | ✅ Done |
| I15 | Those values are read back by the rest of the app | ✅ Done |
| I16 | *(not present in the original list)* | — |
| I17 | Supplier performance derived, not stored | ✅ Done |
| I18 | *(not present in the original list)* | — |
| I19 | Unimplemented reports say so | ✅ Done |
| I20 | *(not present in the original list)* | — |

**Note on gaps:** the working brief listed corrections as ranges (C1–C14, I1–I20) rather than as an itemised list I retained verbatim. Codes above are the ones referenced by name in the code comments; the rows marked *(not present)* are numbers I have no recorded text for. If you still have the original itemisation, send it and I will map the remainder.

---

## 3. Files created (53)

**Types** — `src/types/{common,master,inventory,procurement,documents,ops,index}.ts`

**Mock database** — `src/mock/{ids,db,repository}.ts`, `src/mock/seed/{tenancy,catalog,suppliers,inventory,procurement,documents,ops,index}.ts`

**Domain services** — `src/lib/domain/{money,numbering,permissions,state-machines,matching}.ts`

**API layer** — `src/lib/api/{client,audit,auth,catalog,suppliers,inventory,procurement,receiving,invoices,documents,ops,admin,index}.ts`

**Hooks** — `src/hooks/{use-api,use-session,use-catalog,use-inventory,use-suppliers,use-procurement,use-receiving,use-invoices,use-documents,use-ops,use-admin}.ts`

**Components** — `common/{async-state,permission-gate}.tsx`; `payables/` (6 files); `inventory/{stock-transfer-dialog,transfers-screen}.tsx`; `procurement/{quotation-form,proforma-detail-screen}.tsx`; `documents/schema-mapping-screen.tsx`; `admin/{roles-screen,settings-screen,audit-log-screen}.tsx`

**Routes** — `/supplier-invoices`, `/purchase-returns`, `/schema-mappings`, `/roles`, `/audit`, `/inventory/transfers`, `/procurement/quotations/new`, `/procurement/quotations/[id]`, `/procurement/comparison/[rfqId]`, `/products/[variantId]`, `/ai-documents/review/[documentId]`

## 4. Files deleted (29)

`src/data/` — `alerts, assistant, companies, company, dashboard, documents, inventory, procurement, products, suppliers`

`src/services/` — `auth, catalog, dashboard, documents, http, inventory, procurement`

`src/lib/` — `record-store, po-store, rfq-store, grn-store, product-store, supplier-store, quotation-store, transaction-store, godown-store, team-store, tax, audit-log`

## 5. Files deprecated in place

`src/app/(auth)/accept-invite/[id]` — invitation acceptance is a server flow with no endpoint in the approved API. The page now says so rather than pretending to accept.

---

## 6. New and changed screens

**New (11):** Supplier Invoices (list, detail, entry) · Purchase Returns (list, detail, entry) · Manual Quotation entry · Quotation detail · Schema Mappings (list, detail) · Stock Transfers · Roles & Permissions · Audit Trail · Proforma detail

**Materially changed:** Product form (stock field removed, opening stock added) · GRN form (pending-balance columns, batch capture) · GRN detail (confirmation result panel) · PO form (derived tax treatment, money engine) · PO detail (derived receipt progress, linked documents) · Comparison (computed recommendations, warnings) · Extraction review (match rungs, recomputed totals, by document id) · Dashboard (single query) · Alerts (rule codes, deep links) · Settings (writes real values) · Users (real godown scoping) · System Admin (real impersonation)

**Refactored onto the new layer:** every other screen — 38 routes.

---

## 7. New types

`Id · Money · Quantity · Percent · ListParams · ListResponse<T> · ApiResult<T> · MoneyTotals · TaxableLine · LineTotals · Provenance · MatchMethod · AuditFields · SoftDeletable` · `Company · CompanySettings · DocumentSequence · Role · PermissionCode (~90) · User · SessionUser · Invitation · Category · Brand · Uom · Product · ProductVariant · StockPolicy · Godown · Supplier · SupplierProduct · SupplierPerformance` · `InventoryTransaction · StockBalance · StockRow · Batch · StockTransfer` · `Rfq · SupplierQuotation · QuotationComparison · ComparisonView · PurchaseOrder · PurchaseOrderItem · ReceiptLine · ProformaInvoice · GoodsReceipt · GrnConfirmationResult · SupplierInvoice · ThreeWayMatch · PurchaseReturn · DocumentVariance` · `StoredDocument · AiProcessingJob · AiExtractionResult · AiExtractedLine · AiMatchCandidate · ExtractionView · CanonicalField · DocumentSchemaMapping` · `Alert · AlertRule · AuditLog · DashboardSummary · ReportDefinition · ReportResult`

## 8. New mock services

`authApi · catalogApi · suppliersApi · inventoryApi · procurementApi · receivingApi · invoicesApi · documentsApi · opsApi · adminApi` — all under `src/lib/api/`, all async, all fallible, all matching `04_API_SPECIFICATION.md`.

---

## 9. Known limitations of the prototype

1. **Everything runs in the browser.** One localStorage key holds the whole database. Clearing site data resets to seed.
2. **Permission checks are cosmetic.** Any of them can be bypassed with devtools. The app says so where it matters.
3. **AI processing is simulated.** Stage progress runs on a timer. The matching that does run is the deterministic ladder (`exact_sku` → `supplier_alias` → `barcode` → `normalised_rule` → `trigram`); the `embedding` and `llm` rungs are represented but not executed.
4. **No concurrency control.** `rowVersion` exists on documents but nothing checks it — that is the backend's job.
5. **No file storage.** Uploads record metadata; the bytes go nowhere.
6. **No email.** `outboundMessages` records what *would* be sent.
7. **Invitation acceptance** is not implemented (no endpoint).
8. **Reservations do not exist.** `reservedQuantity` is always 0 until Sales Orders exist.
9. **Some reports are catalogued but not implemented.** Those say so on screen.
10. **Sign-in selects a seeded user.** There is no authentication.

---

## 10. Backend dependencies

Fully specified in `FRONTEND_BACKEND_INTEGRATION_CHECKLIST.md`. The load-bearing ones:

1. **Atomic ledger + balance write** — same transaction, or the whole model is a lie.
2. **Atomic GRN confirmation** — stock, PO progress, variances and alerts together.
3. **Server-issued document numbers** from a per-tenant, per-year sequence.
4. **Server-side permission and godown-scope enforcement** on every endpoint.
5. **Server-computed money**, with `isInterState` derived and returned.
6. **`allowedActions` on every detail endpoint**, with 409 on an illegal transition.
7. **`ListParams` / `ListResponse` on every collection endpoint.**
8. **Errors carrying `code` and `fieldErrors`** with dotted field paths.
9. **Server-written audit rows.**
10. **Real AI pipeline**, reporting which match rung resolved each line.

---

## 11. Decisions that need your approval

These were judgement calls made to keep the app honest. Each is reversible.

1. **A draft PO cannot be edited.** The approved API has no PO update endpoint, so the detail screen is read-only plus status actions. *If drafts should be editable, the backend needs `PATCH /purchase-orders/{id}` restricted to draft status.*

2. **"Add Company" was removed from System Admin.** No `createCompany` endpoint exists. *Confirm whether tenant creation is a platform-console feature or a signup flow.*

3. **"All Users" became a per-company impersonation flow.** There is no list-all-platform-users endpoint. *Confirm whether the platform admin should see a global user list.*

4. **Multi-supplier PO creation moved to the comparison screen.** It used to be a tab in the PO form. Splitting an order across suppliers is now a comparison outcome, which is where the decision actually gets made. *Confirm this is the right home.*

5. **Quotations are rejected, not deleted.** There is no delete endpoint; rejecting keeps the record and its reason. *Confirm that hard deletion is not wanted.*

6. **Invitation acceptance is stubbed.** *Confirm the intended flow: emailed token → password set → account activated?*

7. **Excess receipt is off by default** (`allowGrnExcessReceipt: false`, tolerance 0). *Confirm the default, and whether the tolerance should be per-supplier rather than per-company.*

8. **PO approval threshold defaults to ₹5,00,000.** *Confirm the figure, and whether it should vary by role or by category.*

9. **Standard costing for valuation.** Stock is valued at the variant's purchase price, not moving-average or FIFO. *Confirm — this changes the database design if you want a costing method.*

10. **Supplier performance is computed on read.** Fine at this scale; at real volume it needs a materialised view. *Confirm this is acceptable for launch.*

---

## 12. Verification results

```
TypeScript      0 errors (205 files)
ESLint          0 errors, 6 warnings (hook-dependency hints)
next build      ✓ 38 routes
Console errors  0
```

| Suite | Result |
|---|---|
| Screen checks | 22/22 |
| Workflow — receive against a PO | 10/10 |
| Guards — double receipt, over-receipt | 6/6 |

**The workflow test, in full:** signed in, opened the receipt form for PO-2026-00123, received 30 of one line and 8 of 10 on the other, confirmed. SKU002 moved 12 → 42 at Main Godown. The ledger recorded the goods-receipt rows. PO-2026-00123 advanced 0% → 95% with status "Partially received". An alert was raised for the short line. Reopening the form showed the completed line gone and the short line reading "already received 8"; attempting to receive 99 was refused with *"Only 2 pending on this PO line."*

That is the correction the whole phase was for.
