# Phase state — Supplier & catalogue detail panels (22 Sep 2026)

Goal of this phase: retire the mock reads behind the supplier and product
detail screens. Done. `suppliers.api.ts` and `catalog.api.ts` now read no
mock data at all — the only thing still imported from `@/mock/repository`
is `query()`, the pure client-side search/sort/paging helper.

## What changed

| Area | Before | Now |
| --- | --- | --- |
| Supplier contacts | mock table, read-only card | `supplier_contacts`, with add / edit / remove in the UI |
| Linked products | mock `supplierProducts` | real links **plus** SKUs derived from approved POs (`match_source: purchase_history`) |
| Supplier performance | computed in the browser from mock POs | derived server-side from POs + GRNs |
| PO history, price history | mock | real, and gated on `po.view` as well as `supplier.view` |
| Supplier in-use check | mock | real, and now **enforced** on the PATCH/DELETE too (409 `RECORD_IN_USE`) |
| Bank details & notes | accepted by the form, silently dropped | persisted (`bank_name`, `bank_account_no`, `bank_ifsc`, `notes`) |
| Product stock total on the list | mock ledger | `/inventory/stock` |
| UoM conversions | mock, not shown anywhere | real, with a new card on product detail |
| Per-godown reorder levels | mock, not shown anywhere | real (`variant_godown_policies`), new card, BR-AUTH-12 enforced on write |
| Variant in-use check | mock | real, enforced on delete and on `is_active: false` |

## Backend — 18 new endpoints (150 → 168)

All under `/catalog`, in two new files: `detail_router.py` (permissions and
shapes) and `detail_service.py` (logic). `catalog/router.py` gained only
the supplier bank/notes columns and two guard hooks.

| Endpoint | Permission |
| --- | --- |
| `GET /supplier-performance` | `supplier.view` |
| `GET /suppliers/{id}/performance` · `/usage` | `supplier.view` |
| `GET /suppliers/{id}/purchase-orders` · `/price-history` | `supplier.view` **+ `po.view`** |
| `GET POST /suppliers/{id}/contacts` | view / `supplier.update` |
| `PATCH DELETE /supplier-contacts/{id}` | `supplier.update` |
| `GET POST /suppliers/{id}/products` | view / `supplier.update` |
| `DELETE /supplier-products/{id}` | `supplier.update` |
| `GET /variants/{id}/suppliers` · `/usage` | `product.view` |
| `GET POST /variants/{id}/uom-conversions`, `DELETE /uom-conversions/{id}` | view / `product.update` |
| `GET PUT /variants/{id}/godown-policies` | view / `product.update` |

**No migration.** Migration head is still `b3f7a1c2d804`.

## Decisions worth remembering

1. **Child changes are audited on the parent.** A contact edit is an
   `updated` event on the *supplier*; a conversion or level change is one on
   the *product_variant*, with a plain-English `description`. That is where
   a person looks for it (the detail screen's Audit Trail panel) and it
   avoids widening the `audit_logs.entity_type` CHECK yet again.
2. **Linked products are a union.** `supplier_products` rows plus every
   (supplier, SKU) pair that appears on an approved PO. Without this the
   panel would stay empty forever, since only the unbuilt AI pipeline writes
   that table. Derived rows come back with `id: null` and
   `match_source: "purchase_history"`; the frontend gives them a synthetic
   React key. `last_purchase_price` prefers the latest PO net rate
   (`unit_price × (1 − discount_pct/100)`) over the stored column, which
   nothing writes yet.
3. **Performance is derived, never stored** (02_DATABASE_DESIGN §9).
   On-time = first posted GRN date ≤ PO expected date. Quality =
   accepted ÷ received. Spend = accepted qty × net PO rate. Open orders
   excludes drafts, fully-received, closed and cancelled. One bulk endpoint
   feeds the list so it is not an N+1.
4. **`po.view` is checked separately.** Staff hold `supplier.view` but not
   `po.view`, so PO numbers and values must not leak through the supplier
   screen. The frontend catches that 403 and the Purchase History panel says
   the orders are hidden for their role rather than showing "none".
5. **Godown scope on the write side.** `PUT …/godown-policies` replaces the
   whole set, so it asserts scope on every godown added, changed *or*
   removed — otherwise a scoped user could delete another godown's level by
   omission.
6. **UoM conversions are add/remove, not edit.** Documents freeze the factor
   they used (BR-INV-08), so deleting one never rewrites history — but
   editing one in place would invite the assumption that it does.
7. **Contacts are hard-deleted.** The only reference,
   `rfq_suppliers.supplier_contact_id`, is `ON DELETE SET NULL`, and the RFQ
   keeps the address it was actually sent to.
8. The first contact on a supplier is automatically the primary one, and
   setting a new primary clears the old one. Creating a supplier from the
   form also creates that primary contact.

## Tests

| Suite | Checks |
| --- | --- |
| `backend/scripts/e2e_supplier_catalogue.py` | 98 |
| `backend/scripts/verify_rls.py` | 10 |
| `tests/browser_supplier_catalogue.js` (Playwright) | 15 |

All green. Both suites now live **in the project**, not in the session
scratchpad, so the next session does not have to rewrite them:

```bash
# backend, with the server running on :8000
cd backend && ./.venv/bin/python -m scripts.e2e_supplier_catalogue

# browser, with backend on :8000 and `next dev` on :3000
node tests/browser_supplier_catalogue.js        # needs `npm i playwright`
```

The E2E suite creates its own users, godowns, products and suppliers with a
per-run suffix, so it is safe to re-run against the same database.

Two traps it cost time to find, worth adding to the recurring list:

* `EmailStr` rejects reserved TLDs, so it refuses every `.test` address in
  the demo data. Contact emails use a plain shape check instead.
* In a Playwright login, wait for the token to appear in `localStorage`
  before navigating — the login form writes it just after the redirect, and
  navigating in the same tick loses it, after which every call 401s.

## Still open after this phase

* `receiving.api.ts` (11 mock reads), `auth.api.ts` (7), `admin.api.ts` (6,
  deliberate), `inventory.api.ts` (2), `documents.api.ts` (69 — the AI
  pipeline).
* `inventory.api.ts`'s `reorderPointFor` still reads mock rows. It is dead
  code (nothing calls it); the real per-godown levels are served by
  `/catalog/variants/{id}/godown-policies` and already used by the low-stock
  and reorder reports.
* Linked products and supplier item codes are still read-only in the UI —
  the write endpoint exists (`POST /suppliers/{id}/products`) and is what
  the AI match-confirm flow will call.
* No UI for `is_stocked` / `max_stock` beyond the max column; nothing reads
  `is_stocked` yet.
