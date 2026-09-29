# Write-path testing pass — what changed and what you need to do

11 files were synced directly onto your machine (already written, byte-for-byte
verified) — nothing to extract or copy. Two things you do need to do by hand,
both one-time and both explained below.

## What this pass was

Following up on the frontend-wiring phase, this pass actually drove the real UI
forms — create a supplier, create a product, raise an RFQ, send it, create a PO,
approve it, send it, receive it via a GRN — against your real backend, the way a
person actually would. The earlier phase's browser check only covered navigation
and data loading, not saves; this is the pass that covers saves, and it found four
real bugs, all now fixed and re-verified end to end (12/12 steps pass, PO reached
`received`/100%, GRN `received`, zero console errors).

## Bugs found and fixed

**1. Every unit-of-measure dropdown was empty for a real tenant.** The 9 seeded
units (Kg, Nos, Box, ...) are shared system rows with no `company_id`, and the
frontend was calling the tenant-scoped `/catalog/uoms` list, which — correctly,
by that endpoint's own design — never returns them. Every product/RFQ/PO/GRN
form that needs a unit came up with nothing to pick, since the backend already
has a purpose-built `/catalog/uoms-available` endpoint for exactly this (a
comment in the backend router even says so) that the frontend just wasn't
calling. Fixed in `catalog.api.ts`, `procurement.api.ts`, `receiving.api.ts`.

**2. "Save & Submit for Approval" on a new PO silently created a draft instead.**
The backend's create-PO endpoint has no `status` field — it always creates a
draft, and moving it to pending-approval is a separate `/submit` call. The
frontend's PO form built the right payload but never made that second call, so
clicking "Submit for Approval" looked like it worked (no error) but the PO sat in
Draft, needing an unprompted extra click on its detail page to actually reach
pending-approval. Fixed in `procurement.api.ts`'s `createPurchaseOrder`.

**3. Approving/sending/cancelling a PO, or reversing/confirming/cancelling a
GRN, didn't update the screen you were looking at.** These actions all succeed
on the backend but the detail page doesn't refetch afterward, so the same
button set stays on screen until you manually reload — you'd see "Approve"
sitting there after you'd already approved it, easy to mistake for a failure.
The correct pattern (`state.refresh()` after the mutation) was already used
correctly on the RFQ and Quotation detail screens; it had just been missed on
the PO and GRN ones. Fixed in `po-detail-screen.tsx` and `grn-detail-screen.tsx`.

**4. Creating or editing a product, supplier, or godown from its list page
didn't show up in the list without navigating away and back.** Same root cause
as #3, one level up — the "Add"/"Edit" dialogs on the Products, Suppliers, and
Godowns screens had no way to tell the list underneath them to refetch. Fixed
by wiring an `onSaved` callback through in `products-list-screen.tsx`,
`product-table.tsx` (the per-row edit dialog too), `suppliers-list-screen.tsx`,
`godowns-screen.tsx`, and `godown-form-dialog.tsx` (which didn't even accept an
`onSaved` prop before this).

## The two things you need to do

**A. Fix your existing "Main Warehouse" godown's state — one-time, through the
UI.** It was seeded without a state code (a pre-existing gap in `seed.py`, now
fixed for any *future* fresh seed — see below — but that doesn't retroactively
fix your already-seeded database). Without a state, submitting a PO for
approval 422s with "A delivery godown, an expected delivery date and a total
greater than zero are required" — confusing, since the godown clearly *is*
set. Fix: Godowns → edit "Main Warehouse" → fill in City and State → Save.
Same thing found and fixed live during this pass's testing.

**B. Restart both dev servers** so the new code is actually running:
- Backend: stop and restart `uvicorn` (`Ctrl+C` then the usual `uvicorn
  app.main:app --reload` from `backend/`) — no new migration, just the seed
  script change, which only affects a *future* fresh seed, not your current
  database.
- Frontend: stop and restart `npm run dev` (or just let it hot-reload — Next
  should pick up the 10 changed files on its own, but a restart is the safe
  bet if anything looks stale).

## Not covered by this pass

Everything outside RFQ→PO→GRN, products, suppliers, and godowns — users,
company settings, and everything still on mock — wasn't exercised here. The
same "list doesn't refresh after a same-page mutation" bug class (#3/#4 above)
is plausible anywhere else a detail or list screen was wired to real HTTP
without an explicit `state.refresh()`; this pass fixed every instance it found
in the screens it actually drove, not a codebase-wide audit.
