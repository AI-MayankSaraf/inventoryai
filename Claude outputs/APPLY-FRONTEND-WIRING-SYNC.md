# Frontend wiring phase — what changed and how to run it

Two things landed on your machine in this pass, both already copied into place — this
doc is just a record of what happened and how to run the result, not a manual step
you need to perform.

## 1. The frontend architecture-correction sync you hadn't applied yet

Your `frontend\src` was still the original prototype (`src/data`, `src/services`,
the `*-store.ts` files) — the corrected architecture from the earlier "frontend
correction" phase (`src/mock`, `src/hooks`, `src/lib/api`, `src/lib/domain`) had been
delivered as a zip but never extracted. I applied it: your old `src` is backed up
alongside it as `frontend\src-before-correction` (delete that once you've confirmed
everything below works — it's just a safety net).

## 2. Real backend wiring on top of the corrected architecture

The following now call your real FastAPI backend instead of the mock database:

- **Auth** — sign in, session bootstrap, sign out (`src/lib/api/auth.api.ts`,
  `src/lib/api/client.ts`, `src/hooks/use-session.tsx`)
- **Catalog masters** — products, variants, suppliers, godowns, categories, brands,
  UoMs (`src/lib/api/catalog.api.ts`, `src/lib/api/suppliers.api.ts`)
- **Company & users** — company profile/settings, users, invitations
  (`src/lib/api/admin.api.ts`, the users/company parts of it)
- **RFQ → PO → GRN** — the full procurement loop
  (`src/lib/api/procurement.api.ts`, `src/lib/api/receiving.api.ts`)

Areas with no backend yet — supplier quotations, quotation comparison, proforma
invoices, supplier invoices, purchase returns, AI document matching, alerts,
reports, custom roles/permissions, and the platform System Admin console — are
**unchanged and still run on the mock database**, so those screens keep working
exactly as before. Each function that stayed mock has a one-line comment marking it
as a known gap, so it's easy to find later if a backend for it gets built.

### A backend fix that came out of testing this: CORS

The backend had no CORS headers, so the browser was refusing every request the
frontend made to it (blocked before it even reached a route — you'd have seen this
as every screen failing to load data, or login silently not working). Fixed with a
small addition to `app/main.py` and a new setting in `app/core/config.py`
(`cors_allowed_origins`, defaulting to `http://localhost:3000` and
`http://127.0.0.1:3000` — override via `.env` if you ever run the frontend from a
different origin).

## Running it

1. Make sure the backend is running (`uvicorn app.main:app --reload` from
   `D:\E\Sharad Docs\inventoryai\backend`, as before — no new migration in this pass,
   just the CORS change above, which is picked up automatically on restart).
2. From `D:\E\Sharad Docs\inventoryai\frontend`: `npm install` (only needed if you
   haven't since the correction sync), then `npm run dev`.
3. Sign in at `/login` with `owner@acme-demo.test` / `Demo@12345` — this is the one
   real seeded account. (The old prototype's multi-role demo buttons are gone from
   the sign-in screen for the same reason: those accounts don't exist in the real
   backend.)

## Verified before delivery

Since the connection to your computer wasn't reliable enough to run a build there
(background processes and long builds kept getting cut off mid-run over the
bridge), everything was built and tested in a separate environment against a real
instance of your backend, then copied to your machine byte-for-byte:

- `npx tsc --noEmit` — 0 errors
- `npm run build` — clean, all 47 routes
- A real headless-browser run: signed in against the real backend, confirmed the
  access/refresh tokens and session both persist correctly (including surviving a
  page reload), and loaded Products, Suppliers, RFQ, Purchase Orders, Goods
  Receipt, Users, and Settings — all render with no console errors and no crashes.

Not covered by that browser run: actually exercising every create/edit form end to
end (only navigation + data loading was checked, not every write path). If you hit
something that doesn't save correctly on a specific screen, the fastest way to
narrow it down is to open the browser's Network tab and see what the request/response
looked like — the error message shown in the UI comes straight from the backend's
`detail` field.
