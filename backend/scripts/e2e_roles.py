"""
E2E HTTP suite — custom roles, and the privilege-escalation rules around
them (BR-AUTH-09, BR-AUTH-10, BR-AUTH-11).

The question this suite exists to answer: can anyone reach a permission
they do not already hold by going through a role they define themselves?

    python -m scripts.e2e_roles [base_url]

Exit code 0 only if every check passes.
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.error
import urllib.request
import uuid

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
SFX = uuid.uuid4().hex[:6].upper()

passed = 0
failed: list[str] = []


def check(name: str, cond: bool, info: object = "") -> None:
    global passed
    if cond:
        passed += 1
        print(f"  ok   {name}")
    else:
        failed.append(name)
        print(f"  FAIL {name}  -> {str(info)[:300]}")


def call(method: str, path: str, token: str | None = None, body: object = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw.decode(errors="replace")


def login(email: str, password: str) -> str:
    st, body = call("POST", "/auth/login", body={"email": email, "password": password})
    assert st == 200, (email, st, body)
    return body["access_token"]


def ok(st: int, body: object, expected: int = 200) -> object:
    assert st == expected, (st, body)
    return body


def make_users() -> dict[str, str]:
    """One user per role we need to act as."""

    async def _make():
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        from app.core.config import get_settings
        from app.core.security import hash_password

        out = {}
        engine = create_async_engine(get_settings().platform_database_url, poolclass=NullPool)
        async with engine.begin() as conn:
            cid = (
                await conn.execute(text("SELECT id FROM companies WHERE name = 'Acme Trading Co' ORDER BY id LIMIT 1"))
            ).scalar_one()
            for role in ("purchase_manager", "staff", "owner"):
                rid = (
                    await conn.execute(
                        text("SELECT id FROM roles WHERE company_id IS NULL AND code = :r"), {"r": role}
                    )
                ).scalar_one()
                email = f"roles.{role}.{SFX.lower()}@acme-demo.test"
                await conn.execute(
                    text(
                        "INSERT INTO users (company_id, email, full_name, role_id, is_platform_admin, "
                        "has_all_godowns, status, password_hash, password_changed_at) "
                        "VALUES (:c, :e, :n, :r, false, true, 'active', :pw, now())"
                    ),
                    {"c": cid, "e": email, "n": f"roles {role} {SFX}", "r": rid, "pw": hash_password("Test@12345")},
                )
                out[role] = email
        await engine.dispose()
        return out

    return asyncio.run(_make())


def main() -> int:
    owner = login("owner@acme-demo.test", "Demo@12345")
    beta = login("owner@beta-demo.test", "Demo@12345")
    users = make_users()
    pm = login(users["purchase_manager"], "Test@12345")
    staff = login(users["staff"], "Test@12345")
    second_owner = login(users["owner"], "Test@12345")

    roles = {r["code"]: r for r in ok(*call("GET", "/roles", owner))}
    owner_role_id = roles["owner"]["id"]
    viewer_role_id = roles["viewer"]["id"]

    # ======================================================= defining a role
    print("\n[defining a role]")
    st, created = call("POST", "/roles", owner, {
        "name": f"Store Supervisor {SFX}",
        "description": "Receives stock and adjusts it",
        "permissions": ["grn.view", "grn.create", "grn.confirm", "inventory.view"]})
    check("D01 an Owner can define a role", st == 201 and created["is_system"] is False, created)
    check("D02 its code is derived from the name", created["code"].startswith("store_supervisor"), created.get("code"))
    check("D03 it holds exactly the permissions given",
          sorted(created["permissions"]) == ["grn.confirm", "grn.create", "grn.view", "inventory.view"], created)
    role_id = created["id"]

    st, listed = call("GET", "/roles", owner)
    check("D04 it appears alongside the built-ins", st == 200 and any(r["id"] == role_id for r in listed), st)
    st, b = call("GET", "/roles", beta)
    check("D05 another tenant cannot see it", st == 200 and all(r["id"] != role_id for r in b), st)

    st, b = call("POST", "/roles", owner, {"name": f"Store Supervisor {SFX}", "permissions": ["grn.view"]})
    check("D06 the same code twice → 409", st == 409 and b.get("code") == "DUPLICATE", b)
    st, b = call("POST", "/roles", owner, {"name": "Owner clone", "code": "owner", "permissions": ["grn.view"]})
    check("D07 a built-in code cannot be re-used", st == 409, b)
    st, b = call("POST", "/roles", owner, {"name": "No permissions", "permissions": []})
    check("D08 a role with no permissions is refused", st == 422, b)
    st, b = call("POST", "/roles", owner, {"name": "Made up", "permissions": ["not.a.permission"]})
    check("D09 an unknown permission is refused", st == 422, b)
    st, b = call("POST", "/roles", owner, {"name": "x", "permissions": ["grn.view"]})
    check("D10 a one-character name is refused", st == 400, b)
    st, b = call("POST", "/roles", owner, {"name": "Bad code", "code": "Has Spaces", "permissions": ["grn.view"]})
    check("D11 a malformed code is refused", st == 400, b)

    # ================================================ privilege escalation
    print("\n[privilege escalation]")
    # The interesting attacker is not a Staff user (who cannot reach the
    # endpoint at all) but someone trusted with `user.manage` and nothing
    # else — a team lead who can invite people. They must not be able to
    # define a role that reaches past their own permissions.
    st, lead_role = call("POST", "/roles", owner, {
        "name": f"Team Lead {SFX}",
        "permissions": ["user.view", "user.manage", "dashboard.view", "po.view", "supplier.view", "grn.view"]})
    ok(st, lead_role, 201)
    lead_email = users["purchase_manager"]
    st, all_now = call("GET", "/users", owner)
    lead_id = next((u["id"] for u in all_now if u["email"] == lead_email), None)
    ok(*call("PATCH", f"/users/{lead_id}", owner, {"role_code": lead_role["code"]}))
    pm = login(lead_email, "Test@12345")
    st, me = call("GET", "/auth/me", pm)
    check("E00 a custom role can itself carry user.manage", st == 200 and me["role_code"] == lead_role["code"], me)
    st, b = call("POST", "/roles", pm, {"name": f"Shadow Owner {SFX}", "permissions": ["user.manage_owners"]})
    check("E01 a team lead cannot mint a role holding a permission they lack",
          st == 403 and b.get("code") == "ROLE_ESCALATION", b)
    st, b = call("POST", "/roles", pm, {"name": f"Self Clone {SFX}", "clone_from_role_id": owner_role_id})
    check("E02 …nor by cloning Owner", st == 403 and b.get("code") == "ROLE_ESCALATION", b)
    st, pm_role = call("POST", "/roles", pm, {"name": f"Buyer Assistant {SFX}", "permissions": ["po.view", "supplier.view"]})
    check("E03 …but may define one within what they hold", st == 201, pm_role)
    st, b = call("PATCH", f"/roles/{pm_role['id']}", pm, {"permissions": ["po.view", "user.manage_owners"]})
    check("E04 …and cannot widen it afterwards either", st == 403 and b.get("code") == "ROLE_ESCALATION", b)
    st, b = call("POST", "/roles", staff, {"name": f"Staff Attempt {SFX}", "permissions": ["grn.view"]})
    check("E05 a Staff user cannot define roles at all (no user.manage)", st == 403, b)
    st, b = call("POST", "/roles", beta, {"name": f"Cross Tenant {SFX}", "clone_from_role_id": role_id})
    check("E06 another tenant cannot clone our role", st == 404, b)

    st, b = call("PATCH", f"/roles/{owner_role_id}", owner, {"name": "Owner+"})
    check("E07 a built-in role cannot be renamed", st == 409, b)
    st, b = call("PATCH", f"/roles/{viewer_role_id}", owner, {"permissions": ["dashboard.view"]})
    check("E08 a built-in role's permissions cannot be edited", st == 409, b)
    st, b = call("DELETE", f"/roles/{viewer_role_id}", owner)
    check("E09 a built-in role cannot be deleted", st == 409, b)
    st, b = call("PATCH", f"/roles/{role_id}", beta, {"name": "Hijacked"})
    check("E10 another tenant cannot edit our role", st == 404, b)
    st, b = call("DELETE", f"/roles/{role_id}", beta)
    check("E11 …nor delete it", st == 404, b)

    st, b = call("PATCH", f"/roles/{lead_role['id']}", pm, {"permissions": ["user.view", "user.manage"]})
    check("E06b a team lead cannot rewrite the role they are standing on",
          st == 422 and b.get("code") == "BUSINESS_RULE_VIOLATION", b)

    own_role = next(r for r in listed if r["code"] == "owner")
    st, b = call("PATCH", f"/roles/{own_role['id']}", owner, {"permissions": ["dashboard.view"]})
    check("E12 you cannot cut down the role you are signed in with", st == 409, b)

    # ==================================================== using a role
    print("\n[assigning and using a custom role]")
    st, invited = call("POST", "/users/invite", owner, {
        "email": f"custom.{SFX.lower()}@acme-demo.test", "full_name": f"Custom Role User {SFX}",
        "role_code": created["code"]})
    check("U01 a custom role can be invited into", st == 201, invited)

    # Put an existing user on it, then check what their token actually carries.
    staff_id = None
    st, all_users = call("GET", "/users", owner, None)
    if st == 200:
        staff_id = next((u["id"] for u in all_users if u["email"] == users["staff"]), None)
    st, b = call("PATCH", f"/users/{staff_id}", owner, {"role_code": created["code"]})
    check("U02 an existing user can be moved onto it", st == 200 and b["role_code"] == created["code"], b)
    st, b = call("GET", "/auth/me", staff)
    check("U03 their old token is dead immediately (BR-AUTH-11)", st == 401, b)

    staff = login(users["staff"], "Test@12345")
    st, me = call("GET", "/auth/me", staff)
    check("U04 signing back in puts them on the custom role", st == 200 and me["role_code"] == created["code"], me)
    st, b = call("GET", "/procurement/goods-receipts?limit=1", staff)
    check("U05 a permission the role grants works", st == 200, b)
    st, b = call("GET", "/catalog/suppliers?limit=1", staff)
    check("U06 a permission it does not grant is refused", st == 403, b)

    st, usage = call("GET", f"/roles/{role_id}/usage", owner)
    check("U07 usage reports who is on it", st == 200 and usage["in_use"] and usage["user_count"] >= 1, usage)
    st, b = call("DELETE", f"/roles/{role_id}", owner)
    check("U08 a role in use cannot be deleted", st == 409 and b.get("code") == "RECORD_IN_USE", b)

    # Editing the role must reach the people standing on it.
    st, widened = call("PATCH", f"/roles/{role_id}", owner,
                       {"permissions": ["grn.view", "grn.create", "grn.confirm", "inventory.view", "supplier.view"]})
    check("U09 an Owner can widen a custom role", st == 200 and "supplier.view" in widened["permissions"], widened)
    st, b = call("GET", "/auth/me", staff)
    check("U10 everyone on that role is signed out at once", st == 401 and b.get("code") == "SESSION_REVOKED", b)
    staff = login(users["staff"], "Test@12345")
    st, b = call("GET", "/catalog/suppliers?limit=1", staff)
    check("U11 after signing in again they have the new permission", st == 200, b)

    # ===================================================== deleting a role
    print("\n[deleting a role]")
    st, b = call("PATCH", f"/users/{staff_id}", owner, {"role_code": "staff"})
    check("D12 moving the last holder off frees the role", st == 200, b)
    st, invites = call("GET", "/invitations", owner)
    pending = [i for i in invites if i["role_code"] == created["code"] and i["status"] == "pending"] if st == 200 else []
    st, usage = call("GET", f"/roles/{role_id}/usage", owner)
    check("D12b with nobody on it, a pending invitation still holds it",
          st == 200 and usage["in_use"] and usage["invitation_count"] == len(pending) and len(pending) == 1, usage)
    for invite in pending:
        ok(*call("DELETE", f"/invitations/{invite['id']}", owner), 204)
    st, usage = call("GET", f"/roles/{role_id}/usage", owner)
    # A revoked invitation still pins the role: `invitations.role_id` is ON
    # DELETE RESTRICT, so "free" has to mean free of those too.
    check("D13 a revoked invitation still counts as a reference",
          st == 200 and usage["in_use"] and usage["invitation_count"] >= 1, usage)
    st, b = call("DELETE", f"/roles/{role_id}", owner)
    check("D14 a role with invitation history cannot be deleted (and never 500s)",
          st == 409 and b.get("code") == "RECORD_IN_USE", b)

    # A role nobody has ever been invited into deletes cleanly.
    st, spare = call("POST", "/roles", owner, {"name": f"Spare Role {SFX}", "permissions": ["dashboard.view"]})
    ok(st, spare, 201)
    st, b = call("DELETE", f"/roles/{spare['id']}", owner)
    check("D15 an untouched custom role deletes cleanly", st == 204, b)
    st, b = call("GET", f"/roles/{spare['id']}", owner)
    check("D15b it is gone", st == 404, b)
    role_id = spare["id"]
    st, trail = call("GET", f"/audit-logs/role/{created['id']}", owner)
    actions = {e["action"] for e in trail} if st == 200 else set()
    check("D16 defining and editing a role are both on its audit trail",
          {"created", "updated"} <= actions, actions)
    st, spare_trail = call("GET", f"/audit-logs/role/{role_id}", owner)
    check("D17 so is deleting one",
          st == 200 and "deleted" in {e["action"] for e in spare_trail}, spare_trail)

    # a pending invitation also blocks deletion
    st, blocked = call("POST", "/roles", owner, {"name": f"Invite Blocked {SFX}", "permissions": ["grn.view"]})
    ok(*call("POST", "/users/invite", owner, {
        "email": f"blocked.{SFX.lower()}@acme-demo.test", "full_name": "Blocked Invite",
        "role_code": blocked["code"]}), 201)
    st, b = call("DELETE", f"/roles/{blocked['id']}", owner)
    check("D18 a pending invitation also blocks deletion", st == 409, b)

    # ============================================================ last owner
    print("\n[last owner — BR-AUTH-10]")
    # Acted out through a *custom* role cloned from Owner: the rule has to
    # hold for a role the tenant invented, not only for the built-in one.
    # Cloning matters here — BR-AUTH-09 refuses to let anyone hand out a
    # role granting more than they hold, so a narrow "user admin" could not
    # demote an Owner to Viewer at all (Viewer grants reads it lacks).
    st, owner_admin = call("POST", "/roles", owner, {
        "name": f"Owner Admin {SFX}", "clone_from_role_id": owner_role_id})
    check("L01 an Owner can clone their own role into a custom one", st == 201, owner_admin)

    st, all_users = call("GET", "/users", owner)
    staff_user_id = next((u["id"] for u in all_users if u["email"] == users["staff"]), None)
    demo_owner_id = next((u["id"] for u in all_users if u["email"] == "owner@acme-demo.test"), None)
    ok(*call("PATCH", f"/users/{staff_user_id}", owner, {"role_code": owner_admin["code"]}))
    admin = login(users["staff"], "Test@12345")
    st, me = call("GET", "/auth/me", admin)
    check("L02 the holder has Owner's powers without being an Owner",
          st == 200 and me["role_code"] == owner_admin["code"], me)

    # Earlier runs leave their own Owners behind, so the "last Owner" state
    # is arranged explicitly rather than assumed.
    others = [
        u["id"] for u in all_users
        if u["role_code"] == "owner" and u["id"] != demo_owner_id and u["status"] == "active"
    ]
    demotions = [call("PATCH", f"/users/{other}", admin, {"role_code": "viewer"})[0] for other in others]
    check("L03 it can demote the other Owners", all(s == 200 for s in demotions) if others else True, demotions)

    st, b = call("PATCH", f"/users/{demo_owner_id}", admin, {"role_code": "viewer"})
    check("L04 the last Owner cannot be demoted", st == 422 and b.get("code") == "LAST_OWNER", b)
    st, b = call("DELETE", f"/users/{demo_owner_id}", admin)
    check("L05 …nor removed", st == 422 and b.get("code") == "LAST_OWNER", b)
    st, b = call("PATCH", f"/users/{demo_owner_id}", admin, {"status": "inactive"})
    check("L06 …nor deactivated", st == 422 and b.get("code") == "LAST_OWNER", b)
    st, b = call("PATCH", f"/users/{demo_owner_id}", owner, {"role_code": "viewer"})
    check("L07 and they cannot demote themselves either", st == 403, b)
    st, b = call("GET", "/auth/me", owner)
    check("L08 the Owner's account is untouched after all that",
          st == 200 and b["role_code"] == "owner" and b["status"] == "active", b)

    # tidy up so a re-run starts from the same place
    ok(*call("PATCH", f"/users/{staff_user_id}", owner, {"role_code": "staff"}))
    call("PATCH", f"/users/{lead_id}", owner, {"role_code": "purchase_manager"})
    _ = second_owner

    print(f"\n{passed} passed, {len(failed)} failed")
    for f in failed:
        print("  -", f)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
