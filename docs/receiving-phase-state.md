# Phase state — Receiving leftovers (23 Sep 2026)

Goal: retire the mock reads behind the goods-receipt detail panels and give a
draft receipt a real edit path. Done. `receiving.api.ts` and
`inventory.api.ts` now read no mock data at all.

## What changed

| Area | Before | Now |
| --- | --- | --- |
| Edit a draft receipt | mock-only, dead code | `PATCH /procurement/goods-receipts/{id}`, optimistic-locked, with an **Edit Draft** screen |
| Variances panel | mock (always empty) | `grn_vs_po` rows recorded at confirm, read back per receipt |
| Purchase returns panel | mock | `GET /purchase-returns?goods_receipt_id=` |
| "Posted" column per line | guessed from the receipt's status | the real ledger figure (`inventory_transaction_id` + posted quantity) |
| Confirmation result | postings/variances/alerts all empty | the full §3.18 response: postings with balances, PO progress, variances, alert ids |
| Reversal | "reversed by GRN-x" links that never existed | a banner reading who reversed it, when and why, plus the offsetting ledger rows |
| Stock postings | not shown | new panel listing every ledger row the receipt produced, reversals marked |
| Batch number / expiry on a line | not returned | returned and shown |
| Period pre-check (BR-INV-10) | mock settings, never fired | real `/company/settings`, checked before submit |
| Excess-receipt and batch pre-checks | looked up mock rows, silently no-op | the PO's **current** pending balance and the real tracking type |
| Returnable quantities | never subtracted what was already returned | each live return is fetched and subtracted |

## Backend — 4 new endpoints (168 → 172)

| Endpoint | Permission |
| --- | --- |
| `PATCH /procurement/goods-receipts/{id}` | `grn.update` (draft only, `row_version` required) |
| `GET /procurement/goods-receipts/{id}/postings` | `grn.view` + `inventory.view` |
| `GET /procurement/goods-receipts/{id}/variances` | `grn.view` |
| `GET /purchase-returns?goods_receipt_id=` | `return.view` (new filter on the existing list) |

`POST .../confirm` now returns `GrnConfirmOut` (`goods_receipt`,
`inventory_postings`, `purchase_order`, `variances`, `alerts_raised`) instead
of the bare receipt — the shape 04_API_SPECIFICATION.md §3.18 always
specified. `GET .../goods-receipts/{id}` gained `reversal` on the header and
`inventory_transaction_id` / `batch_number` / `manufactured_on` /
`expires_on` / `posted_quantity` on each line.

**No migration.** Migration head is still `b3f7a1c2d804`.

## Decisions worth remembering

1. **Create and edit share one validator.** `_write_items()` holds the whole
   per-line rule set (BR-GRN-01..05, BR-GRN-11), so a draft saved a second
   time is held to exactly the same rules — and re-reads the PO's pending
   balance, which may have moved since the draft was first saved.
2. **Supplier and PO are fixed at creation.** The lines' `purchase_order_item_id`s
   belong to that PO, so a different order is a different receipt. The edit
   screen shows both read-only.
3. **One variance per line, not three.** `_grn_findings` picks the most
   significant fact: a wrong item (`product`) beats a short delivery
   (`quantity` vs ordered), which beats a rejection (`quantity` received vs
   accepted). Stacking all three buried the real one.
4. **A reversal is not a second document.** `reverse_grn` posts offsetting
   rows against the same receipt, so the frontend's old `reversalOf` /
   `reversedBy` links pointed at documents that never existed. The detail
   screen now reads the reversal off the audit trail instead.
5. **Alerts run after the commit and can never fail a receipt** (spec §3.18
   step 9): `refresh_grn_alerts` swallows its own errors and reports no
   alerts rather than rolling back posted stock.
6. **Two real bugs fixed on the way:**
   * `GRN_WRONG_PRODUCT` matched `issue_type = 'wrong_item'`, a value the
     CHECK constraint does not allow — the rule could never fire. It now
     matches the four `wrong_*` values.
   * `getReturnableLines` read the returns *list*, which does not hydrate
     line items, so already-returned quantities were never subtracted and
     the form offered quantities the backend would refuse.
7. **A short line now says its note is required** rather than "Optional
   note" — BR-GRN-05 has always required it; the form just didn't say so.

## Tests

| Suite | Checks |
| --- | --- |
| `backend/scripts/e2e_receiving.py` | 45 |
| `backend/scripts/e2e_supplier_catalogue.py` | 98 |
| `backend/scripts/verify_rls.py` | 10 |
| `tests/browser_receiving.js` (Playwright) | 16 |
| `tests/browser_supplier_catalogue.js` (Playwright) | 15 |

All green.

```bash
cd backend && ./.venv/bin/python -m scripts.e2e_receiving     # server on :8000
node tests/browser_receiving.js                               # + next dev on :3000
```

One more trap for the recurring list: **`alert_service.evaluate()` commits,
so the tenant scope has to be re-asserted before every rule** — evaluating
two rules in a row failed on the second with `invalid input syntax for type
uuid: ""`. Same root cause as trap #1, new place.

## Still open after this phase

* `documents.api.ts` (69 mock reads — the AI pipeline), `auth.api.ts` (7),
  `admin.api.ts` (6, deliberately deferred).
* Confirming still has no `Idempotency-Key` header (BR-GRN-09 is satisfied by
  the status check, not by a key).
* `gate_entry_number` is accepted by the API but has no field on the form.
