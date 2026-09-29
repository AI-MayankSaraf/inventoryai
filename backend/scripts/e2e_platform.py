"""
E2E HTTP suite — the Platform System Admin console.

The console runs on a BYPASSRLS session, so the only thing between it and
every tenant's data is `require_platform_admin`. This suite is mostly about
that boundary:

  * a tenant Owner — the most privileged role inside a company — must get
    403 on every console endpoint, including the read-only ones;
  * an impersonation token must not reach the console at all, or "support
    logs in as a customer" would become "customer's browser now holds a
    platform session";
  * onboarding must produce a tenant that actually works end to end (the
    invited Owner can accept, sign in, and see their own company and nobody
    else's), because a half-built tenant is worse than none;
  * suspension must stop live tokens on the next request (BR-AUTH-04), not
    when they expire.

    python -m scripts.e2e_platform [base_url]

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
SFX = uuid.uuid4().hex[:6].lower()
#: Unique per run: `uq_companies_gstin` is global, so a fixed value would
#: collide with the tenant the previous run onboarded.
GSTIN = f"29AABC{SFX.upper()}1Z5"

PLATFORM_EMAIL = "platform-admin@inventoryai.test"
PLATFORM_PASSWORD = "Platform@12345"

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


def db(sql: str, params: dict | None = None) -> list[dict]:
    """A fresh engine per call: the suite is sync, and a pooled async engine
    outlives the loop `asyncio.run` closes ("Future attached to a different
    loop")."""

    async def _run():
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        from app.core.config import get_settings

        engine = create_async_engine(get_settings().platform_database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(sql), params or {})
                return [dict(r) for r in result.mappings().all()] if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(_run())


CONSOLE_READS = [
    ("GET", "/platform/kpis"),
    ("GET", "/platform/companies"),
    ("GET", "/platform/users"),
    ("GET", "/platform/activity"),
]


def main() -> int:  # noqa: C901 - a boundary suite is a long list of cases
    admin = login(PLATFORM_EMAIL, PLATFORM_PASSWORD)
    owner = login("owner@acme-demo.test", "Demo@12345")
    beta_owner = login("owner@beta-demo.test", "Demo@12345")

    # ==================================================== who may even look
    print("\n[the boundary]")
    for i, (method, path) in enumerate(CONSOLE_READS, start=1):
        st, b = call(method, path, owner)
        check(f"B0{i} a tenant Owner is refused {path}", st == 403, (st, b))

    st, b = call("GET", "/platform/companies")
    check("B05 …and so is an anonymous caller", st == 401, (st, b))
    st, b = call("GET", "/platform/companies", "not-a-token")
    check("B06 …and a forged token", st == 401, (st, b))
    st, b = call("POST", "/platform/companies", owner, {
        "name": f"Escalation {SFX}", "state_code": "27", "state_name": "Maharashtra",
        "owner_email": f"esc.{SFX}@x.test", "owner_full_name": "Escalation Attempt",
    })
    check("B07 an Owner cannot onboard a company", st == 403, (st, b))
    check("B08 …and no company was created",
          not db("SELECT id FROM companies WHERE name = :n", {"n": f"Escalation {SFX}"}), "row exists")

    acme_id = ok(*call("GET", "/auth/me", owner))["company_id"]
    st, b = call("GET", f"/platform/companies/{acme_id}", owner)
    check("B09 an Owner cannot read even their own company through the console", st == 403, (st, b))

    # ================================================== the console's reads
    print("\n[reads]")
    kpis = ok(*call("GET", "/platform/kpis", admin))
    check("R01 KPIs count companies", kpis["companies"] >= 2, kpis)
    check("R02 active + suspended never exceeds the total",
          kpis["active_companies"] + kpis["suspended_companies"] <= kpis["companies"], kpis)
    check("R03 the user count excludes platform admins",
          kpis["users"] == db("SELECT COUNT(*) AS n FROM users WHERE deleted_at IS NULL "
                              "AND NOT is_platform_admin")[0]["n"], kpis)
    check("R04 30-day actives never exceed total users", kpis["active_users_30d"] <= kpis["users"], kpis)

    companies = ok(*call("GET", "/platform/companies", admin))
    check("R05 every tenant is listed", len(companies) >= 2, len(companies))
    acme = next((c for c in companies if c["id"] == acme_id), None)
    check("R06 the demo tenant carries its owner", acme and acme["owner_email"] == "owner@acme-demo.test", acme)
    check("R07 …and real counts, not zeros", acme and acme["user_count"] > 0 and acme["sku_count"] > 0, acme)

    st, b = call("GET", "/platform/companies?q=Acme", admin)
    check("R08 search narrows the list", st == 200 and all("acme" in c["name"].lower() for c in b), b)
    st, b = call("GET", "/platform/companies?status=suspended", admin)
    check("R09 the status filter is honoured",
          st == 200 and all(c["status"] == "suspended" for c in b), b)
    st, b = call("GET", "/platform/companies?status=deleted", admin)
    check("R10 an unknown status is rejected, not ignored", st == 400, (st, b))
    st, b = call("GET", "/platform/companies?plan=Enterprise", admin)
    check("R11 the plan filter is honoured", st == 200 and all(c["plan"] == "Enterprise" for c in b), b)

    users = ok(*call("GET", "/platform/users", admin))
    check("R12 users span more than one tenant", len({u["company_id"] for u in users}) >= 2, len(users))
    check("R13 platform admins are not offered for impersonation",
          all(u["email"] != PLATFORM_EMAIL for u in users), "platform admin listed")
    st, b = call("GET", f"/platform/users?company_id={acme_id}", admin)
    check("R14 users can be narrowed to one tenant",
          st == 200 and all(u["company_id"] == acme_id for u in b), len(b or []))

    feed = ok(*call("GET", "/platform/activity?limit=25", admin))
    check("R15 the activity feed is cross-tenant", len(feed) > 0, len(feed))
    check("R16 …newest first", feed == sorted(feed, key=lambda r: r["created_at"], reverse=True), "out of order")
    check("R17 …and carries impersonated_by", all("impersonated_by" in r for r in feed), feed[:1])

    st, b = call("GET", f"/platform/companies/{uuid.uuid4()}", admin)
    check("R18 an unknown company is a 404, not a 500", st == 404, (st, b))
    st, b = call("GET", "/platform/companies/not-a-uuid", admin)
    check("R19 …and a malformed id is a readable 400", st == 400, (st, b))

    # ========================================================== onboarding
    print("\n[onboarding]")
    name = f"Zeta Traders {SFX}"
    owner_email = f"zeta.owner.{SFX}@zeta.test"
    body = {
        "name": name, "legal_name": f"Zeta Traders Pvt Ltd {SFX}", "state_code": "29",
        "state_name": "Karnataka", "city": "Bengaluru", "plan": "Starter",
        "email": f"hello.{SFX}@zeta.test", "phone": "9876500000",
        "owner_email": owner_email, "owner_full_name": "Zeta Owner",
    }
    st, created = call("POST", "/platform/companies", admin, body)
    check("O01 a company is onboarded", st == 201, (st, created))
    new_id = created["company"]["id"]
    invite_token = created["invitation_token"]
    check("O02 the invite token comes back in development", bool(invite_token), created)
    check("O03 no password was set for the owner — they are invited",
          "password" not in json.dumps(created).lower(), created)

    seq = db("SELECT doc_type, prefix FROM document_sequences WHERE company_id = :c", {"c": new_id})
    check("O04 all eight numbering series exist", len(seq) == 8, seq)
    godown = db("SELECT name, is_default, state_code FROM godowns WHERE company_id = :c", {"c": new_id})
    check("O05 a default godown exists with the company's state code",
          len(godown) == 1 and godown[0]["is_default"] and godown[0]["state_code"] == "29", godown)
    settings_row = db("SELECT default_godown_id FROM company_settings WHERE company_id = :c", {"c": new_id})
    check("O06 settings point at that godown", len(settings_row) == 1 and settings_row[0]["default_godown_id"], settings_row)
    check("O07 the owner has an invitation, not an account",
          not db("SELECT id FROM users WHERE lower(email) = :e", {"e": owner_email})
          and len(db("SELECT id FROM invitations WHERE company_id = :c AND status = 'pending'", {"c": new_id})) == 1,
          "unexpected state")
    check("O08 the listing shows the pending owner's email",
          next(c for c in ok(*call("GET", f"/platform/companies?q={SFX}", admin)))["owner_email"] == owner_email,
          "owner_email missing")

    st, b = call("POST", "/platform/companies", admin, body)
    check("O09 the same name cannot be onboarded twice", st == 409, (st, b))
    # An owner email that already has an ordinary login is now *linked*
    # (BR-AUTH-13, see scripts/e2e_multi_company.py); only an account that
    # cannot own a company — a platform admin — is still refused.
    st, b = call("POST", "/platform/companies", admin, {**body, "name": f"{name} II",
                                                       "owner_email": PLATFORM_EMAIL})
    check("O10 …nor an owner email that belongs to a platform admin", st == 409, (st, b))
    st, b = call("POST", "/platform/companies", admin, {**body, "name": f"{name} III", "state_code": "ZZ"})
    check("O11 a bad state code is refused", st == 400, (st, b))
    st, b = call("POST", "/platform/companies", admin, {**body, "name": f"{name} IV", "plan": "Platinum"})
    check("O12 …and an invented plan", st == 400, (st, b))
    st, b = call("POST", "/platform/companies", admin, {**body, "name": f"{name} V", "owner_email": "not-an-email"})
    check("O13 …and a malformed owner email", st == 400, (st, b))
    check("O14 none of those left a half-built tenant",
          len(db("SELECT id FROM companies WHERE name LIKE :n", {"n": f"{name}%"})) == 1, "extra rows")

    # ================================================ the tenant really works
    print("\n[the new tenant works]")
    st, accepted = call("POST", "/invitations/accept", body={
        "invitation_token": invite_token, "password": "Zeta@12345",
    })
    check("T01 the invited owner can accept", st == 201, (st, accepted))
    check("T02 …as an Owner", accepted.get("role_code") == "owner", accepted)
    zeta = login(owner_email, "Zeta@12345")
    me = ok(*call("GET", "/auth/me", zeta))
    check("T03 they sign in to their own company", me["company_id"] == new_id, me)

    st, b = call("GET", "/catalog/suppliers", zeta)
    check("T04 their tenant starts empty, not with someone else's data", st == 200 and b == [], b)
    st, b = call("GET", "/users", zeta)
    check("T05 …and holds exactly one user", st == 200 and len(b) == 1, b)
    st, b = call("GET", "/catalog/godowns", zeta)
    check("T06 …and the default godown", st == 200 and len(b) == 1 and b[0]["is_default"], b)
    st, b = call("GET", f"/platform/companies/{acme_id}", zeta)
    check("T07 the fresh Owner cannot see the console either", st == 403, (st, b))
    st, b = call("POST", "/invitations/accept", body={
        "invitation_token": invite_token, "password": "Zeta@12345",
    })
    check("T08 the invite token is single-use", st in (400, 404, 409, 422), (st, b))

    # ================================================================ editing
    print("\n[editing a tenant]")
    st, b = call("PATCH", f"/platform/companies/{new_id}", admin, {"plan": "Growth", "city": "Mysuru"})
    check("E01 plan and city update", st == 200 and b["plan"] == "Growth" and b["city"] == "Mysuru", b)
    st, b = call("PATCH", f"/platform/companies/{new_id}", admin, {"plan": "Platinum"})
    check("E02 an invented plan is refused", st == 400, (st, b))
    st, b = call("PATCH", f"/platform/companies/{new_id}", admin, {"name": " "})
    check("E03 …and a blank name", st == 400, (st, b))
    st, b = call("PATCH", f"/platform/companies/{new_id}", admin, {"gstin": GSTIN})
    check("E04 a GSTIN can be set", st == 200 and b["gstin"] == GSTIN, b)
    st, b = call("PATCH", f"/platform/companies/{acme_id}", admin, {"gstin": GSTIN})
    check("E05 …but not twice across tenants", st == 409, (st, b))
    st, b = call("PATCH", f"/platform/companies/{new_id}", owner, {"plan": "Enterprise"})
    check("E06 an Owner cannot edit a company through the console", st == 403, (st, b))
    check("E07 …and the plan is unchanged",
          ok(*call("GET", f"/platform/companies/{new_id}", admin))["plan"] == "Growth", "changed")
    audit_rows = db(
        "SELECT action FROM audit_logs WHERE entity_type = 'company' AND entity_id = :c ORDER BY created_at",
        {"c": new_id},
    )
    check("E08 onboarding and edits are audited",
          "created" in [r["action"] for r in audit_rows] and "updated" in [r["action"] for r in audit_rows],
          audit_rows)

    # ========================================================== suspension
    print("\n[suspension — BR-AUTH-04]")
    st, b = call("POST", f"/platform/companies/{new_id}/suspend", admin, {"reason": "Payment overdue"})
    check("S01 a company can be suspended",
          st == 200 and b["status"] == "suspended" and b["suspended_reason"] == "Payment overdue", b)
    check("S02 the suspension is timestamped", b.get("suspended_at"), b)
    st, b = call("GET", "/auth/me", zeta)
    check("S03 a live token of that tenant stops working on the next request", st == 403, (st, b))
    st, b = call("POST", "/auth/login", body={"email": owner_email, "password": "Zeta@12345"})
    check("S04 …and they cannot sign in again", st == 403, (st, b))
    st, b = call("GET", "/auth/me", owner)
    check("S05 other tenants are unaffected", st == 200, (st, b))

    st, b = call("POST", f"/platform/companies/{new_id}/suspend", admin, {"reason": "again"})
    check("S06 suspending twice is harmless", st == 200 and b["status"] == "suspended", b)
    st, b = call("POST", f"/platform/companies/{new_id}/suspend", admin, {"reason": "x"})
    check("S07 a reason that says nothing is refused", st == 400, (st, b))
    st, b = call("POST", f"/platform/companies/{new_id}/suspend", owner, {"reason": "Competitor removal"})
    check("S08 an Owner cannot suspend anyone", st == 403, (st, b))

    st, b = call("POST", f"/platform/companies/{new_id}/reactivate", admin)
    check("S09 reactivating clears the flag",
          st == 200 and b["status"] == "active" and not b["suspended_reason"] and not b["suspended_at"], b)
    zeta = login(owner_email, "Zeta@12345")
    st, b = call("GET", "/auth/me", zeta)
    check("S10 …and the tenant can sign in again", st == 200 and b["company_id"] == new_id, b)

    # ======================================================= impersonation
    print("\n[impersonation round trip — BR-AUTH-07]")
    zeta_user_id = me["id"]
    st, imp = call("POST", "/platform/impersonate", admin,
                   {"user_id": zeta_user_id, "reason": "Customer reported a missing godown"})
    check("I01 the platform admin can impersonate the tenant Owner", st == 200, (st, imp))
    imp_token = imp["access_token"]
    check("I02 the session expires in 30 minutes", imp["expires_in"] == 1800, imp)
    check("I03 no refresh token is issued", "refresh_token" not in imp, list(imp))

    st, b = call("GET", "/auth/me", imp_token)
    check("I04 the impersonation token acts as the target", st == 200 and b["id"] == zeta_user_id, b)
    st, b = call("GET", "/platform/companies", imp_token)
    check("I05 …but cannot reach the console", st == 403, (st, b))
    st, b = call("POST", "/platform/impersonate", imp_token,
                 {"user_id": zeta_user_id, "reason": "nesting"})
    check("I06 …nor impersonate again", st == 403, (st, b))
    st, b = call("POST", "/platform/companies", imp_token, {
        "name": f"Nested {SFX}", "state_code": "27", "state_name": "Maharashtra",
        "owner_email": f"nested.{SFX}@x.test", "owner_full_name": "Nested",
    })
    check("I07 …nor onboard a company", st == 403, (st, b))

    ok(*call("GET", "/catalog/suppliers", imp_token))
    stamped = db(
        "SELECT impersonated_by FROM audit_logs WHERE company_id = :c AND impersonated_by IS NOT NULL",
        {"c": new_id},
    )
    check("I08 impersonated actions are stamped", len(stamped) >= 1, stamped)

    st, b = call("POST", "/platform/impersonate/stop", imp_token)
    check("I09 the session can be stopped", st == 200 and b["ended_at"], b)
    st, b = call("GET", "/auth/me", imp_token)
    check("I10 the token dies immediately, not in 30 minutes", st == 401, (st, b))
    st, b = call("GET", "/platform/kpis", admin)
    check("I11 the platform admin's own token still works", st == 200, (st, b))

    st, b = call("POST", "/platform/impersonate", admin,
                 {"user_id": str(db("SELECT id FROM users WHERE lower(email) = :e",
                                    {"e": PLATFORM_EMAIL})[0]["id"]), "reason": "Reaching for more"})
    check("I12 a platform admin cannot be impersonated", st == 403, (st, b))
    st, b = call("POST", "/platform/impersonate", owner, {"user_id": zeta_user_id, "reason": "nope"})
    check("I13 …and a tenant Owner cannot impersonate at all", st == 403, (st, b))

    st, b = call("POST", f"/platform/companies/{new_id}/suspend", admin, {"reason": "Cooling off"})
    assert st == 200, b
    st, b = call("POST", "/platform/impersonate", admin, {"user_id": zeta_user_id, "reason": "support"})
    check("I14 a suspended tenant cannot be impersonated into", st == 403, (st, b))
    ok(*call("POST", f"/platform/companies/{new_id}/reactivate", admin))

    # =================================================== tenancy still holds
    print("\n[tenancy is unchanged by all this]")
    st, b = call("GET", "/catalog/suppliers", beta_owner)
    beta_names = {s["name"] for s in b} if st == 200 else set()
    st, b = call("GET", "/catalog/suppliers", owner)
    acme_names = {s["name"] for s in b} if st == 200 else set()
    check("X01 two tenants still see different supplier sets",
          bool(acme_names) and not (acme_names & beta_names), (len(acme_names), len(beta_names)))
    st, b = call("GET", "/users", zeta)
    check("X02 the new tenant still sees only itself", st == 200 and len(b) == 1, b)
    check("X03 the console did not leak into tenant routes",
          call("GET", "/platform/kpis", zeta)[0] == 403, "leaked")

    print(f"\n{passed} passed, {len(failed)} failed")
    for f in failed:
        print("  -", f)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
