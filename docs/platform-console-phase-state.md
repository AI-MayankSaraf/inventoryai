# Phase state — Platform System Admin console (23 Sep 2026)

The System Admin screen was the last screen still reading the mock
repository. It now runs entirely on `/platform/*`, and a platform admin can
onboard a tenant, edit it, suspend and reactivate it, browse every user on
the installation and read a cross-tenant audit feed.

No migration. The schema already had everything this needed
(`companies.suspended_at` / `suspended_reason`, `impersonation_sessions`,
`audit_logs.impersonated_by`); what was missing was the API and the screen.

## Backend — 9 new endpoints (184 → 193)

| Endpoint | What it does |
| --- | --- |
| `GET /platform/kpis` | companies / active / suspended / users / 30-day actives |
| `GET /platform/companies` | every tenant, with `q`, `status`, `plan` |
| `POST /platform/companies` | onboard a tenant and invite its first Owner |
| `GET /platform/companies/{id}` | one tenant |
| `PATCH /platform/companies/{id}` | name, GSTIN, plan, contact details |
| `POST /platform/companies/{id}/suspend` | reason required |
| `POST /platform/companies/{id}/reactivate` | clears status, reason and timestamp |
| `GET /platform/users` | every user on the installation, `company_id` / `q` |
| `GET /platform/activity` | the cross-tenant audit feed |

All of them run on the BYPASSRLS platform session behind
`require_platform_admin`, in `app/modules/platform/console_router.py`; the
work itself is in `console_service.py`.

## Decisions worth remembering

1. **The permission check is the only boundary here.** These handlers run
   with RLS bypassed, so the company id in the URL says *which* tenant to
   act on and never *whether* the caller may act. 9 of the 85 E2E checks do
   nothing but hammer that from a tenant Owner's token.
2. **An impersonation token cannot reach the console.** Support signing in
   as a customer must not hand that customer's browser a platform session,
   so `require_platform_admin` refuses a token carrying `impersonated_by`,
   and `_not_impersonating` says so explicitly on every handler.
3. **Onboarding invites the first Owner; it never sets their password.**
   A password chosen by whoever pressed the button is a password the Owner
   never picked. The dialog has no password field, and the response carries
   the invite token only in development — same rule as `/users/invite`.
4. **An onboarded tenant is complete or it is not created.** Company,
   settings, a default godown carrying the company's own state code, and one
   document-sequence row per document type, all in one transaction. The
   godown's state code matters: without it every PO delivered there 422s at
   approval with no obvious cause.
5. **Suspension does not enumerate sessions.** `set_status` flips one row;
   `deps.assert_session_live` re-reads it on every request, so a suspended
   tenant's live tokens stop working on their *next* call (BR-AUTH-04)
   rather than when they expire. The confirmation dialog says "immediately"
   and means it.
6. **Suspending requires a reason, reactivating does not.** The tenant's
   users are shown the reason, so "why is my account locked" has an answer;
   there is nothing to explain about being let back in.
7. **The owner column falls back to the pending invitation.** Otherwise a
   company onboarded a minute ago shows a blank owner until someone accepts.
8. **The KPIs are one server-side aggregate**, not a client-side sum over a
   page of companies — the previous screen summed whatever rows the table
   had fetched, which stopped being the truth at 200 tenants.

## Bugs found and fixed along the way

* **Impersonation was broken in the browser** (shipped in the Auth-gaps
  phase, not caught there). `startImpersonation` stored the token pair as
  `{accessToken, refreshToken: ""}`, but `getStoredTokens` treats a missing
  half as "not signed in" and returns `null` — so every request during an
  impersonation session went out with no `Authorization` header and came
  back 401. The access token now goes in both slots, which still makes a
  refresh fail (an access token never matches a stored refresh-token hash),
  which is what BR-AUTH-07 asks for.
* **The impersonation picker read `/users`**, a tenant endpoint. A platform
  admin's token carries no company, so it returned nothing for the one
  person allowed to impersonate. It now reads `/platform/users`, which is
  cross-tenant and already excludes platform admins — they cannot be
  impersonated, so offering them was offering a button that fails.
* **The activity tab read `/audit-logs`**, also tenant-scoped, for the same
  reason. It now reads `/platform/activity`.
* **The header asked `/alerts/summary` for platform admins**, 403ing on
  every screen they opened and showing a bell that could never mean
  anything. The query is skipped when the signed-in user has no tenant.

## Frontend

`admin.api.ts` no longer reads the mock repository for anything — the last
two functions that did (`listCompanies`, `setCompanyStatus`) are real, and
`onboardCompany`, `getPlatformKpis`, `listPlatformUsers` and
`listPlatformActivity` are new. Searching and filtering happen on the
server, because the list can span every company on the installation.

The GST state list moved out of `godown-form-dialog.tsx` into
`src/lib/gst-states.ts` — the onboarding dialog needs the same list, and the
2-digit code is not cosmetic (it decides CGST+SGST vs IGST).

## Tests

| Suite | Checks |
| --- | --- |
| `backend/scripts/e2e_platform.py` | 85 |
| `backend/scripts/e2e_roles.py` | 53 |
| `backend/scripts/e2e_auth.py` | 60 |
| `backend/scripts/e2e_receiving.py` | 45 |
| `backend/scripts/e2e_supplier_catalogue.py` | 98 |
| `backend/scripts/verify_rls.py` | 10 |
| Browser: platform / roles / auth / receiving / supplier-catalogue | 26 / 8 / 16 / 16 / 15 |

All green. `e2e_platform.py` onboards a real tenant each run and drives it
all the way through — the invited Owner accepts, signs in, sees an empty
company of their own and nothing of anyone else's — because a half-built
tenant is worse than no tenant, and only an end-to-end pass proves it isn't
one. The browser suite covers the two things only a browser can: the
onboarding dialog producing a real company, and an impersonation round trip
that swaps the session and puts it back.

## Still open after this phase

* Onboarded test tenants accumulate; there is no delete, by design
  (`companies` is ON DELETE RESTRICT everywhere and a tenant is deactivated
  via `status`, never removed).
* The company list is not paginated in the UI — it fetches up to 200 and
  shows them all. Fine at this scale, not at a thousand tenants.
* There is no per-tenant drill-down screen yet: `GET /platform/companies/{id}`
  exists and nothing routes to it.
* Plan changes are not billing events — they set a column and land in the
  audit trail, nothing more.
