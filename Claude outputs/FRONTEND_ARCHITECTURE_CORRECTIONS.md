# Frontend Architecture Corrections

**Project:** InventoryAI · **Phase:** Frontend architecture correction (no backend)
**Date:** 15 September 2026
**Scope:** Bring the existing Next.js prototype into agreement with the approved backend architecture (documents 01–09) so it is backend-ready.

This phase changed **where data comes from and what the screens are allowed to do**. It did not redesign the UI. Colours, typography, spacing, the sidebar, navigation, cards, tables and dialogs are unchanged except where a functional correction required it; those exceptions are listed in §7.

---

## 1. What was actually wrong

The prototype looked complete and behaved plausibly, but underneath it made seven promises it could not keep:

| # | The prototype did this | Why it could never work |
|---|---|---|
| 1 | Stored `currentStock` as an editable field on a product | Two people editing the same product overwrite each other's stock; there is no record of *why* stock changed |
| 2 | Let a product form set stock directly | Stock and its history become two unrelated things |
| 3 | Confirmed a goods receipt without moving stock | The document said goods arrived; the warehouse figure disagreed |
| 4 | Linked documents by their printed number (`"PO-123"`) | Renumber a document, or have two with the same number, and every link breaks |
| 5 | Recomputed tax in each screen that showed money | Four screens, four slightly different totals |
| 6 | Generated document numbers as `max + 1` in the browser | Two people creating a PO at the same time get the same number |
| 7 | Used one 12-value status union for every document | An RFQ could be "partially received"; a GRN could be "expired" |

Everything below follows from fixing those.

---

## 2. The new shape

```
UI component
    ↓  (only ever calls a hook)
Feature hook            src/hooks/use-*.ts
    ↓  (only ever calls an API module)
Mock API                src/lib/api/*.api.ts          ← the seam the real backend replaces
    ↓
Repository + mock DB    src/mock/repository.ts, src/mock/db.ts
```

**The rule:** a component may not import `@/mock/*`, may not touch `localStorage` for business data, and may not do money arithmetic. All three are now true of every screen in the app.

`src/lib/api/*` is written as if it were HTTP: async, fallible, returning the shapes in `04_API_SPECIFICATION.md`, throwing `ApiError` with the business-rule id from `06_BUSINESS_RULES.md`. Replacing it with `fetch` changes nothing above that line.

---

## 3. Inventory is a ledger

This is the correction everything else hangs from.

**Before:** `product.currentStock = 42`.

**Now:** an append-only `inventoryTransactions` table, and `stockBalances` as a derived cache folded out of it. The seed states 32 *movements* — opening stock, goods receipts, a purchase return, a transfer, a damage, an expiry write-off, sales issues — and all 19 balances are computed from them. Change a movement and every balance, KPI, valuation and low-stock row moves with it, because they all read the same fold.

There is no `setStock` anywhere in the codebase. The only writer of `stockBalances` is one private function in `inventory.api.ts`, called in the same operation that appends to the ledger. A mistake is corrected by posting a compensating row that points at what it reverses — history is never edited.

**Proven in test:** receiving 30 units moved SKU002 from 12 → 42, wrote the ledger rows, and advanced the purchase order — all from one action.

---

## 4. Critical corrections (C1–C14)

| Code | Correction | Where it now lives |
|---|---|---|
| **C1** | Confirming a GRN posts stock, advances the PO, records variances and raises alerts — in one call, returning proof of each | `receiving.api.ts › confirmGoodsReceipt`, surfaced on the GRN detail screen |
| **C2** | Stock is derived from transactions, never stored on a product | `types/inventory.ts`, `inventory.api.ts`, `mock/seed/inventory.ts` |
| **C3** | The product form cannot set stock; creating a product may post an *opening stock* transaction instead | `product-form-dialog.tsx`, `catalog.api.ts › ProductInput.openingStock` |
| **C4/C5** | Permission checks are presentation only, and the app says so | `lib/domain/permissions.ts`, `permission-gate.tsx › PermissionDisclaimer` |
| **C6** | A confirmed GRN is never edited; a reversing GRN posts the opposite movements and links both ways | `receiving.api.ts › reverseGoodsReceipt` |
| **C7** | Eight per-document state machines replace the shared status union; screens render only `allowedActions` | `lib/domain/state-machines.ts` |
| **C8** | The AI review screen names the match rung that produced each suggestion and labels simulated processing as simulated | `lib/domain/matching.ts`, `extraction-review.tsx` |
| **C10** | Receiving starts from the **pending balance**, not the ordered quantity | `receiving.api.ts › getReceiptLines`, `grn-form.tsx` |
| **C11** | Document numbers come from a per-tenant, per-year sequence; forms show a *preview* and say the final number may differ | `lib/domain/numbering.ts` |
| **C12** | Every cross-document link is an id; numbers are display values. Routes are `/purchase-orders/{id}`, `/products/{variantId}` | throughout `types/`, `api/`, and the route tree |
| **C13** | One money engine: line net → line tax → document totals. No component multiplies quantity by price | `lib/domain/money.ts` |
| **C14** | CGST/SGST vs IGST is derived from supplier state vs place of supply — no toggle | `money.ts › isInterState` |

---

## 5. Important corrections (I1–I20)

| Code | Correction |
|---|---|
| **I1** | **Supplier Invoices** — a whole workflow that did not exist. Includes a three-way match: invoice ↔ PO ↔ goods actually accepted |
| **I2** | **Purchase Returns** — also entirely new. Rejected goods were booked into stock and stayed there forever; a confirmed return now posts a negative transaction |
| **I3** | **Manual quotation entry** — a quote arriving by phone or on paper had no way into the system |
| **I5** | Comparison recommendations are computed from the quotes on the table, with the reason and price spread shown — not hardcoded prose |
| **I6** | No fake reservations. `reservedQuantity` is always 0 in this product and the UI no longer implies otherwise |
| **I8** | Per-godown reorder policy overrides the variant default |
| **I9** | Batch capture on receipt for batch-tracked products, with expiry validation |
| **I10** | UoM conversions, so a PO line can be entered in boxes |
| **I12** | Dashboard KPIs and the lists behind them read one query, so they cannot disagree |
| **I13** | No decorative counts. Sidebar badges, the alert bell and every figure come from a real query |
| **I14/I15** | Settings writes real values that the rest of the app reads back — tolerances, approval thresholds, the period lock, numbering |
| **I17** | Supplier performance is derived from actual POs, GRNs and returns, not stored fields someone typed |
| **I19** | Reports that are defined but not implemented say so instead of rendering empty |

---

## 6. Files

**Created (53):** `src/types/` (7), `src/mock/` (11), `src/lib/domain/` (5), `src/lib/api/` (13), `src/hooks/` (10), `src/components/payables/` (6), plus shared `async-state.tsx` and `permission-gate.tsx`.

**Deleted (29):** `src/data/` (10 static-data files), `src/services/` (7), and `src/lib/{record,po,rfq,grn,product,supplier,quotation,transaction,godown,team}-store.ts`, `tax.ts`, `audit-log.ts`.

**New screens (11):** Supplier Invoice list/detail/form, Purchase Return list/detail/form, Manual Quotation entry, Quotation detail, Schema Mappings list/detail, Stock Transfers, Roles & Permissions, Audit Trail, Proforma detail.

**Refactored:** every remaining screen — 38 routes in total.

---

## 7. Deliberate visual changes

Only where a correction forced it:

1. **Product form** — the "Current Stock" field is gone. Creating a product offers an optional opening-stock section; editing shows per-godown stock read-only.
2. **GRN form** — three new read-only columns (Ordered / Already received / Pending) so double-receipt is visibly impossible, plus batch fields on batch-tracked lines.
3. **Inventory grid** — the "Reserved" column was removed rather than showing a column that is always zero.
4. **PO form** — the inter-state toggle was removed; the tax treatment is now derived and explained.
5. **PO detail** — read-only plus status actions, because a draft PO has no update endpoint in the approved API.
6. **System Admin** — "Add Company" removed (no backing endpoint); "All Users" replaced with a per-company impersonation flow.
7. **Users** — the ad-hoc activity panel was replaced by the dedicated Audit Trail screen.

---

## 8. Verification

```
TypeScript      0 errors across 205 files
ESLint          0 errors, 6 warnings (hook-dependency hints)
next build      ✓ 38 routes
Console errors  0
```

**Browser tests, against a production build:**

- 22/22 screen checks — every route renders, inventory value is non-zero and derived, the product form has no stock field, the GRN form shows pending balances, all new screens exist.
- 10/10 workflow checks — receiving against PO-2026-00123 moved SKU002 from 12 → 42, wrote ledger rows, advanced the PO from 0% → 95% with status "Partially received", and raised an alert for the short line.
- 6/6 guard checks — after receiving, the completed line disappeared from the receipt form and the short line showed "already received 8"; over-receipting was refused with *"Only 2 pending on this PO line."*

That last result is the C10 correction proving itself: **receiving 8 of 10 twice is now impossible.**

---

## 9. What this phase deliberately did not do

No PostgreSQL, SQLAlchemy, Alembic, FastAPI, Redis, Celery, S3 or AWS. No real authentication, OCR, AI calls or email. No backend of any kind. Every service in `src/lib/api/` is a mock that runs in the browser — but it is shaped so that swapping it for HTTP is a change of implementation, not of contract.
