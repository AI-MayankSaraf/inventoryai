# Phase state — Auth gaps (23 Sep 2026)

Password reset, impersonation (BR-AUTH-07), instant session revocation and
per-company SMTP. `auth.api.ts` now reads no mock data.

## Migration — `c5d9e2f47a13` (head moves from `b3f7a1c2d804`)

| Change | Why |
| --- | --- |
| `password_reset_tokens` | Only the SHA-256 is stored, like refresh tokens. RLS on with **no policy** (deny-all): reset tokens are looked up before any tenant is known |
| `users.sessions_revoked_at` | The instant-revocation marker an access token's issue time is compared against |
| `company_email_settings` | Per-tenant SMTP; the password is encrypted with pgcrypto (`APP_SECRET_KEY`, falling back to the JWT secret) |

Run `alembic upgrade head`, then `python -m app.db.seed` once more — it now
also creates the platform admin (`platform-admin@inventoryai.test` /
`Platform@12345`), idempotently.

## What changed

| Area | Before | Now |
| --- | --- | --- |
| "Forgot password?" | a dead `href="#"` | `/forgot-password` → emailed link → `/reset-password` |
| Change your own password | nothing | a card in Settings; ends every session |
| Impersonation | client-side make-believe in the mock store | real 30-minute scoped token from `POST /platform/impersonate` |
| Suspending a company / changing a role | took effect when the token expired (up to 15 min) | refused on the very next request |
| Outgoing email | one global env-configured relay | per-company SMTP with a **Send test** button |
| Audit trail | no `impersonated_by` anywhere | stamped on every row written under an impersonation token |

## Backend — 8 new endpoints (172 → 180)

| Endpoint | Gate |
| --- | --- |
| `POST /auth/forgot-password` · `/auth/reset-password` | public |
| `POST /auth/change-password` | any signed-in user (refused while impersonating) |
| `POST /platform/impersonate` · `/impersonate/stop` | platform admin / the impersonation token itself |
| `GET PUT /company/email-settings`, `POST /company/email-settings/test` | `company.view` / `company.manage` |

## Decisions worth remembering

1. **`/auth/forgot-password` always answers 202** — for unknown addresses
   too. Anything else is an account-enumeration oracle. The probe is still
   recorded in the audit trail.
2. **One live reset link per mailbox.** Requesting again marks the previous
   one used; tokens last an hour and are single-use. A completed reset also
   clears the BR-AUTH-03 lockout — being locked out is precisely when people
   reset.
3. **Instant revocation costs one indexed query per request.** This
   deliberately reverses the original "never re-queries the database per
   request" note in `core/deps.py`: a revocation that takes 15 minutes is
   not a revocation. The check covers user status, soft-deletion, company
   suspension, the revocation marker, and whether an impersonation session
   has ended.
4. **Tokens carry `iat_ms`.** A standard JWT `iat` has one-second
   resolution, and a role change plus the user signing back in commonly land
   in the same second — with second resolution the fresh token was being
   refused. Millisecond precision makes the comparison unambiguous.
5. **`get_current_claims` rolls back after its check.** It shares the
   platform session with the handler, so leaving the implicit transaction
   open broke any handler that opens `session.begin()` (it did, once).
6. **Impersonation is deliberately narrow:** 30 minutes, no refresh token
   issued at all (so there is nothing to refresh), cannot nest, cannot
   change the target's password, cannot target another platform admin, and
   dies the moment the session is stopped rather than when the clock runs
   out. The admin's own tokens are kept aside in the browser, so "Return to
   Super Admin" is a restore, not a second sign-in.
7. **The SMTP password is write-only.** Stored `pgp_sym_encrypt`-ed, never
   returned; the API reports `has_password`. Omitting the field keeps it,
   sending `""` clears it. Rotating `APP_SECRET_KEY` makes stored passwords
   unreadable — worth knowing before rotating it.
8. **Test email uses the saved settings, not the form**, because the
   question being answered is "will invitations actually arrive".

## Tests

| Suite | Checks |
| --- | --- |
| `backend/scripts/e2e_auth.py` | 60 |
| `backend/scripts/e2e_receiving.py` | 45 |
| `backend/scripts/e2e_supplier_catalogue.py` | 98 |
| `backend/scripts/verify_rls.py` | 10 |
| `tests/browser_auth.js` | 16 |
| `tests/browser_receiving.js` | 16 |
| `tests/browser_supplier_catalogue.js` | 15 |

All green. The auth suite needs the platform admin seeded first.

## Still open after this phase

* `/auth/me/companies` and `/auth/switch-company` (BR-AUTH-13) — the
  multi-company switcher is still unbuilt.
* The System Admin console screens still read mock companies; impersonation
  inside them now calls the real endpoint, so the picker works once that
  console is wired (next phase but one).
* No rate limit on `/auth/forgot-password` itself beyond the per-user
  single-live-token rule.
* An impersonation session has no server-side idle timeout beyond the
  30-minute token.
