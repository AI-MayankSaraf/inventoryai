# Phase state — Custom roles (23 Sep 2026)

A company can now define roles of its own beside the seven built-ins, and
the privilege-escalation rules that make that safe are tested properly.

## Migration — `d81b6c4e9f27` (head moves from `c5d9e2f47a13`)

`roles.code` was pinned to the seven built-in codes by
`ck_roles_code_valid`. It now checks the *shape* instead
(`^[a-z][a-z0-9_]{1,39}$`) — a stable machine handle for a role whose
display name people edit. A second constraint keeps the two kinds of row
honest: a system role belongs to no tenant, a tenant role is never a system
one.

`uq_roles_code` is unchanged, so a tenant's codes are unique within that
tenant and can never collide with the system rows.

## Backend — 4 new endpoints (180 → 184)

| Endpoint | Gate |
| --- | --- |
| `POST /roles` (optionally `clone_from_role_id`) | `user.manage` |
| `PATCH /roles/{id}` | `user.manage` |
| `GET /roles/{id}/usage` | `user.view` |
| `DELETE /roles/{id}` | `user.manage` |

`UserUpdate.role_code` and `InvitationCreate.role_code` no longer hard-code
the six assignable built-ins — the shape is checked in the schema and the
*existence* and *escalation* questions are answered where they belong, in
`_resolve_assignable_role` and `_assert_no_escalation`.

## Decisions worth remembering

1. **BR-AUTH-09 applies to defining a role, not only to assigning one.**
   Otherwise escalation is two calls away: mint a role holding
   `user.manage_owners`, then assign it. `_assert_permissions_within_caller`
   refuses any permission the caller does not already hold — including via
   `clone_from_role_id`.
2. **Nobody can edit the role they are signed in with.** Shrinking the role
   you are standing on is how a company locks itself out of its own user
   management. The screen says so instead of hiding the button.
3. **Editing a role signs out everyone holding it.** Permissions are baked
   into the access token at sign-in, so without this a widened or narrowed
   role would take up to 15 minutes to bite — the same reasoning as
   BR-AUTH-11, applied to the role rather than to one membership.
4. **A narrow "user admin" cannot hand out broad roles.** This falls out of
   BR-AUTH-09 as written and is worth knowing before it surprises someone: a
   role holding only `user.*` cannot assign Viewer, because Viewer grants
   reads it does not hold. Delegating user management means cloning a role
   that already holds what you intend to hand out.
5. **`invitations.role_id` is ON DELETE RESTRICT**, so a *revoked* or
   accepted invitation still pins a role. The usage endpoint counts all
   invitation rows, not just pending ones — counting only pending ones had
   the screen offering a delete the database then refused with a 500. The
   delete also catches the integrity error as a backstop.
6. **The screen greys out what the signed-in user cannot grant**, and says
   why once rather than on every line.

## Tests

| Suite | Checks |
| --- | --- |
| `backend/scripts/e2e_roles.py` | 53 |
| `backend/scripts/e2e_auth.py` | 60 |
| `backend/scripts/e2e_receiving.py` | 45 |
| `backend/scripts/e2e_supplier_catalogue.py` | 98 |
| `backend/scripts/verify_rls.py` | 10 |
| Browser: roles / auth / receiving / supplier-catalogue | 8 / 16 / 16 / 15 |

All green. The roles suite arranges the "last Owner" state explicitly rather
than assuming it — earlier runs leave their own Owners behind.

## Still open after this phase

* Custom roles cannot be reordered or grouped; the list is alphabetical.
* There is no "duplicate this role" button on the screen, though the API
  supports `clone_from_role_id`.
* A role's permission set is not versioned — the audit trail records the
  before/after, which is the honest record but not a rollback.
