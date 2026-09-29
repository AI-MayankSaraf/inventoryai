"""
E2E HTTP suite — one login, several companies (BR-AUTH-13).

What this has to prove, in order of how badly it would hurt to get wrong:

  * switching really moves the session: after a switch, every tenant read
    and write lands in the new company, and the old company's data is not
    reachable through the new token (the cross-company leak BR-AUTH-13
    exists to prevent);
  * it is membership-gated: a login cannot switch into a company it has no
    active membership of, an impersonation token cannot switch at all, and
    removing or suspending a membership ends a live session on its next
    request rather than when the token expires;
  * `/auth/refresh` keeps a switched session where it is, instead of
    quietly dropping it back into the home company;
  * the new `member_read` RLS policy grants *read* of a member's user row
    in the company they were linked into — and nothing else: no update, no
    visibility from a third company, no appearance in that company's own
    user list.

    python -m scripts.e2e_multi_company [base_url]

Needs the seeded demo tenant (owner@acme-demo.test), the beta tenant
(owner@beta-demo.test) and the platform admin. Exit code 0 only if every
check passes.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import urllib.error
import urllib.request
import uuid

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
SFX = uuid.uuid4().hex[:6].lower()

PLATFORM_EMAIL = "platform-admin@inventoryai.test"
PLATFORM_PASSWORD = "Platform@12345"
ACME_OWNER = "owner@acme-demo.test"
BETA_OWNER = "owner@beta-demo.test"
PASSWORD = "Demo@12345"

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


def login_pair(email: str, password: str) -> tuple[str, str]:
    st, body = call("POST", "/auth/login", body={"email": email, "password": password})
    assert st == 200, (email, st, body)
    return body["access_token"], body["refresh_token"]


def ok(st: int, body: object, expected: int = 200) -> object:
    assert st == expected, (st, body)
    return body


def claims_of(token: str) -> dict:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def db(sql: str, params: dict | None = None, *, url_attr: str = "platform_database_url",
       tenant: str | None = None) -> list[dict]:
    """Fresh engine per call (same reason as e2e_platform). `tenant` runs the
    statement on the RLS-bound app role with that company set, the way a
    real request does."""

    async def _run():
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        from app.core.config import get_settings

        engine = create_async_engine(getattr(get_settings(), url_attr), poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                if tenant:
                    await conn.execute(text("SELECT set_config('app.current_company_id', :c, true)"), {"c": tenant})
                result = await conn.execute(text(sql), params or {})
                return [dict(r) for r in result.mappings().all()] if result.returns_rows else [
                    {"rowcount": result.rowcount}
                ]
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def supplier_body(name: str) -> dict:
    return {
        "name": f"{name} {SFX}", "supplier_type": "Distributor", "gst_treatment": "unregistered",
        "state_code": "27", "state_name": "Maharashtra", "city": "Mumbai",
        "email": f"{name.lower().replace(' ', '')}{SFX}@sup.test",
    }


def main() -> int:  # noqa: C901 - a boundary suite is a long list of cases
    admin, _ = login_pair(PLATFORM_EMAIL, PLATFORM_PASSWORD)
    acme, acme_refresh = login_pair(ACME_OWNER, PASSWORD)
    beta, _ = login_pair(BETA_OWNER, PASSWORD)
    acme_me = ok(*call("GET", "/auth/me", acme))
    acme_id, acme_user_id = acme_me["company_id"], acme_me["id"]
    beta_id = ok(*call("GET", "/auth/me", beta))["company_id"]

    # ============================================================ baseline
    print("\n[before any second company]")
    st, b = call("GET", "/auth/me/companies", acme)
    # Earlier runs (or e2e_platform) may already have linked this owner
    # elsewhere, so this checks shape, not a count.
    check("M01 the home company is listed first, flagged home and current",
          st == 200 and b[0]["is_home"] and b[0]["is_current"] and b[0]["company_id"] == acme_id
          and sum(1 for c in b if c["is_home"]) == 1, b)
    before_count = len(b) if st == 200 else 0
    check("M02 /auth/me reports the home company as both active and home",
          acme_me["home_company_id"] == acme_id, acme_me)

    # ============================================== onboarding links a login
    print("\n[onboarding with an owner email that already has a login]")
    gamma_name = f"Gamma Retail {SFX}"
    st, b = call("POST", "/platform/companies", admin, {
        "name": gamma_name, "state_code": "29", "state_name": "Karnataka", "city": "Bengaluru",
        "plan": "Starter", "owner_email": ACME_OWNER, "owner_full_name": "ignored when linking",
    })
    check("O01 onboarding succeeds instead of refusing the existing email", st == 201, (st, b))
    gamma_id = b["company"]["id"] if st == 201 else None
    check("O02 …and says the owner was linked, not invited",
          st == 201 and b["owner_linked"] is True and b["invitation_token"] is None, b)
    check("O03 no invitation row was created for it",
          not db("SELECT id FROM invitations WHERE company_id = :c", {"c": gamma_id}), "invitation exists")
    check("O04 the tenant list shows the linked owner",
          st == 201 and b["company"]["owner_email"] == ACME_OWNER, b)
    check("O05 the owner's home company did not move",
          db("SELECT company_id FROM users WHERE id = :u", {"u": acme_user_id})[0]["company_id"].__str__() == acme_id,
          "home changed")

    # ================================================================ list
    print("\n[the switcher list]")
    st, b = call("GET", "/auth/me/companies", acme)
    ids = [c["company_id"] for c in b] if st == 200 else []
    check("L01 the existing token now lists the new company too, home still first",
          st == 200 and ids[0] == acme_id and gamma_id in ids and len(ids) == before_count + 1, b)
    gamma_entry = next((c for c in b if c["company_id"] == gamma_id), {}) if st == 200 else {}
    check("L02 the linked company carries the Owner role and is not current",
          gamma_entry.get("role_code") == "owner" and not gamma_entry.get("is_current")
          and not gamma_entry.get("is_home"), gamma_entry)
    st, b = call("GET", "/auth/me/companies", beta)
    check("L03 an unrelated login still sees only its own company",
          st == 200 and [c["company_id"] for c in b] == [beta_id], b)
    st, b = call("GET", "/auth/me/companies", admin)
    check("L04 a platform admin has no companies to switch between", st == 200 and b == [], b)

    # ============================================================== switch
    print("\n[switching]")
    ok(*call("POST", "/catalog/suppliers", acme, supplier_body("Acme Only")), 201)
    st, sw = call("POST", "/auth/switch-company", acme, {"company_id": gamma_id, "refresh_token": acme_refresh})
    check("W01 an active member can switch without a password", st == 200 and "access_token" in sw, (st, sw))
    gamma_tok, gamma_refresh = sw["access_token"], sw["refresh_token"]
    c = claims_of(gamma_tok)
    check("W02 the new token is scoped to the new company", c["company_id"] == gamma_id, c)
    check("W03 …with the role held there and its permissions",
          c["role"] == "owner" and "rfq.create" in c["permissions"], c["role"])
    check("W04 …and all-godown scope", c["godown_scope"]["all"] is True, c["godown_scope"])
    st, b = call("POST", "/auth/refresh", body={"refresh_token": acme_refresh})
    check("W05 the refresh token that was presented is revoked", st == 401, (st, b))

    st, me = call("GET", "/auth/me", gamma_tok)
    check("W06 /auth/me now describes the new company",
          st == 200 and me["company_id"] == gamma_id and me["company_name"] == gamma_name
          and me["home_company_id"] == acme_id and me["role_code"] == "owner", me)
    st, b = call("GET", "/auth/me/companies", gamma_tok)
    check("W07 the switcher now marks the new company as current",
          st == 200 and [x["company_id"] for x in b if x["is_current"]] == [gamma_id], b)

    # ======================================================== data follows
    print("\n[data follows the token — no cross-company leak]")
    st, b = call("GET", "/catalog/suppliers", gamma_tok)
    check("D01 the new company starts with none of the old company's suppliers",
          st == 200 and not any(s["name"].startswith("Acme Only") for s in b), b if st != 200 else len(b))
    st, sup = call("POST", "/catalog/suppliers", gamma_tok, supplier_body("Gamma Only"))
    check("D02 a write in the new company succeeds", st == 201, (st, sup))
    row = db("SELECT company_id FROM suppliers WHERE id = :id", {"id": sup["id"]}) if st == 201 else []
    check("D03 …and lands in the new company", row and str(row[0]["company_id"]) == gamma_id, row)
    st, b = call("GET", "/catalog/suppliers", acme)
    check("D04 the old company's (still valid) token does not see it",
          st == 200 and not any(s["name"].startswith("Gamma Only") for s in b), len(b) if st == 200 else b)
    st, b = call("GET", "/catalog/suppliers", acme)
    check("D05 the previous access token was not revoked by the switch (BR-AUTH-13)",
          st == 200 and any(s["name"].startswith("Acme Only") for s in b), st)
    st, b = call("GET", f"/catalog/suppliers/{sup['id']}", acme)
    check("D06 fetching the new company's row by id from the old company is a 404", st == 404, (st, b))

    # ============================================================ refresh
    print("\n[refresh keeps the session where it is]")
    st, rf = call("POST", "/auth/refresh", body={"refresh_token": gamma_refresh})
    check("F01 a switched session refreshes", st == 200, (st, rf))
    check("F02 …into the same company, not back to home",
          st == 200 and claims_of(rf["access_token"])["company_id"] == gamma_id,
          claims_of(rf["access_token"]) if st == 200 else rf)
    gamma_tok, gamma_refresh = rf["access_token"], rf["refresh_token"]
    stored = db("SELECT company_id FROM refresh_tokens "
                "WHERE token_hash = encode(sha256(convert_to(:t, 'UTF8')), 'hex')", {"t": gamma_refresh})
    check("F03 the stored refresh token remembers the company",
          stored and str(stored[0]["company_id"]) == gamma_id, stored)

    # ======================================================= user records
    print("\n[the member's user row inside the linked company]")
    st, b = call("GET", "/users", gamma_tok)
    check("U01 the linked company's own user list does not absorb the visitor",
          st == 200 and all(u["id"] != acme_user_id for u in b), b)
    st, b = call("PATCH", f"/users/{acme_user_id}", gamma_tok, {"full_name": "Hijacked"})
    check("U02 the linked company cannot edit the visitor's user record", st in (404, 422), (st, b))
    vis = db("SELECT full_name FROM users WHERE id = :u", {"u": acme_user_id},
             url_attr="app_database_url", tenant=gamma_id)
    check("U03 RLS lets the linked company *read* the member's row (names resolve)", len(vis) == 1, vis)
    upd = db("UPDATE users SET full_name = 'Hijacked' WHERE id = :u", {"u": acme_user_id},
             url_attr="app_database_url", tenant=gamma_id)
    check("U04 …but not update it", upd and upd[0]["rowcount"] == 0, upd)
    vis_beta = db("SELECT 1 FROM users WHERE id = :u", {"u": acme_user_id},
                  url_attr="app_database_url", tenant=beta_id)
    check("U05 …and a third company still cannot see it at all", vis_beta == [], vis_beta)

    # ===================================================== who may switch
    print("\n[membership-gated]")
    st, b = call("POST", "/auth/switch-company", gamma_tok, {"company_id": beta_id})
    check("G01 no switching into a company you are not a member of",
          st == 403 and isinstance(b, dict) and b.get("code") == "NOT_A_MEMBER", (st, b))
    st, b = call("POST", "/auth/switch-company", gamma_tok, {"company_id": str(uuid.uuid4())})
    check("G02 …nor into a company that does not exist (same answer)",
          st == 403 and isinstance(b, dict) and b.get("code") == "NOT_A_MEMBER", (st, b))
    st, b = call("POST", "/auth/switch-company", beta, {"company_id": gamma_id})
    check("G03 an unrelated owner cannot switch into it", st == 403, (st, b))
    st, b = call("POST", "/auth/switch-company", admin, {"company_id": gamma_id})
    check("G04 a platform admin cannot switch", st == 403, (st, b))
    st, back = call("POST", "/auth/switch-company", gamma_tok, {"company_id": acme_id, "refresh_token": gamma_refresh})
    check("G05 switching back home works",
          st == 200 and claims_of(back["access_token"])["company_id"] == acme_id, (st, back))
    home_refresh = back["refresh_token"] if st == 200 else None
    stored_home = db("SELECT company_id FROM refresh_tokens WHERE token_hash = encode(sha256(convert_to(:t, 'UTF8')), 'hex')",
                     {"t": home_refresh}) if home_refresh else []
    check("G06 …and its refresh token is stored as 'home' (NULL)",
          stored_home and stored_home[0]["company_id"] is None, stored_home)

    # ====================================================== impersonation
    print("\n[impersonation cannot become multi-company access]")
    st, imp = call("POST", "/platform/impersonate", admin, {"user_id": acme_user_id, "reason": "multi-company check"})
    check("P01 the admin can still impersonate a multi-company owner", st == 200, (st, imp))
    imp_tok = imp["access_token"] if st == 200 else ""
    st, b = call("GET", "/auth/me/companies", imp_tok)
    check("P02 an impersonation session sees only the company it is visiting",
          st == 200 and [c["company_id"] for c in b] == [acme_id], b)
    st, b = call("POST", "/auth/switch-company", imp_tok, {"company_id": gamma_id})
    check("P03 …and cannot switch into the owner's other companies", st == 403, (st, b))
    call("POST", "/platform/impersonate/stop", imp_tok)

    # ====================================================== console links
    print("\n[System Admin: linked owners]")
    st, b = call("GET", f"/platform/companies/{gamma_id}/members", admin)
    check("C01 the console lists the linked owner with their home company",
          st == 200 and len(b) == 1 and b[0]["email"] == ACME_OWNER and b[0]["home_company_id"] == acme_id, b)
    st, b = call("GET", f"/platform/companies/{gamma_id}/members", acme)
    check("C02 a tenant owner cannot read the console's member list", st == 403, (st, b))
    st, b = call("POST", f"/platform/companies/{gamma_id}/members", admin, {"email": BETA_OWNER})
    check("C03 the console can link another existing login", st == 201 and b["role_code"] == "owner", (st, b))
    st, b = call("POST", f"/platform/companies/{gamma_id}/members", admin, {"email": BETA_OWNER})
    check("C04 …but not twice", st == 409, (st, b))
    st, b = call("POST", f"/platform/companies/{gamma_id}/members", admin, {"email": f"nobody.{SFX}@x.test"})
    check("C05 an unknown email is a 404", st == 404, (st, b))
    st, b = call("POST", f"/platform/companies/{gamma_id}/members", admin, {"email": PLATFORM_EMAIL})
    check("C06 a platform admin cannot be linked", st == 422, (st, b))
    st, b = call("POST", f"/platform/companies/{acme_id}/members", admin, {"email": ACME_OWNER})
    check("C07 a user cannot be linked into their own home company", st == 409, (st, b))
    st, b = call("POST", f"/platform/companies/{gamma_id}/members", acme, {"email": BETA_OWNER})
    check("C08 a tenant owner cannot link people themselves", st == 403, (st, b))

    beta_sw = ok(*call("POST", "/auth/switch-company", beta, {"company_id": gamma_id}))
    beta_gamma = beta_sw["access_token"]
    st, _b = call("GET", "/catalog/suppliers", beta_gamma)
    check("C09 the newly linked owner can work in the company", st == 200, st)
    st, _b = call("DELETE", f"/platform/companies/{gamma_id}/members/{ok(*call('GET', '/auth/me', beta))['id']}", admin)
    check("C10 the console can remove a link", st == 204, st)
    st, b = call("GET", "/catalog/suppliers", beta_gamma)
    check("C11 removal ends their live session in that company on the next request",
          st == 401 and isinstance(b, dict) and b.get("code") == "SESSION_REVOKED", (st, b))
    st, b = call("POST", "/auth/refresh", body={"refresh_token": beta_sw["refresh_token"]})
    check("C12 …and their refresh token for it no longer works", st == 401, (st, b))
    st, b = call("GET", "/catalog/suppliers", beta)
    check("C13 …while their home company is untouched", st == 200, st)
    st, b = call("DELETE", f"/platform/companies/{gamma_id}/members/{uuid.uuid4()}", admin)
    check("C14 removing a link that does not exist is a 404", st == 404, (st, b))

    # ========================================================= suspension
    print("\n[suspension]")
    gamma_again = ok(*call("POST", "/auth/switch-company", acme, {"company_id": gamma_id}))["access_token"]
    ok(*call("POST", f"/platform/companies/{gamma_id}/suspend", admin, {"reason": "multi-company check"}))
    st, b = call("GET", "/catalog/suppliers", gamma_again)
    check("S01 suspending the linked company stops a live token for it",
          st == 403 and isinstance(b, dict) and b.get("code") == "COMPANY_SUSPENDED", (st, b))
    st, b = call("GET", "/catalog/suppliers", acme)
    check("S02 …but not the owner's home-company session", st == 200, st)
    st, b = call("POST", "/auth/switch-company", acme, {"company_id": gamma_id})
    check("S03 switching into a suspended company is refused", st == 403, (st, b))
    st, b = call("GET", "/auth/me/companies", acme)
    g = next((c for c in b if c["company_id"] == gamma_id), {}) if st == 200 else {}
    check("S04 the switcher still lists it, flagged suspended", g.get("company_status") == "suspended", b)
    ok(*call("POST", f"/platform/companies/{gamma_id}/reactivate", admin))

    ok(*call("POST", f"/platform/companies/{acme_id}/suspend", admin, {"reason": "home suspended check"}))
    try:
        st, b = call("POST", "/auth/login", body={"email": ACME_OWNER, "password": PASSWORD})
        check("S05 a suspended home company no longer locks out a multi-company owner", st == 200, (st, b))
        if st == 200:
            landed = claims_of(b["access_token"])["company_id"]
            members = db("SELECT company_id FROM company_users WHERE user_id = :u AND status = 'active'",
                         {"u": acme_user_id})
            check("S06 …they land in one of their other active companies",
                  landed != acme_id and landed in {str(m["company_id"]) for m in members}, landed)
            st2, b2 = call("POST", "/auth/switch-company", b["access_token"], {"company_id": acme_id})
            check("S07 …and cannot switch back into the suspended home company", st2 == 403, (st2, b2))
        st, b = call("POST", "/auth/login", body={"email": BETA_OWNER, "password": PASSWORD})
        check("S08 an unrelated login is unaffected", st == 200, (st, b))
    finally:
        ok(*call("POST", f"/platform/companies/{acme_id}/reactivate", admin))

    # ============================================================== audit
    print("\n[audit trail]")
    rows = db("SELECT action, description FROM audit_logs WHERE company_id = :c AND actor_user_id = :u "
              "AND description = 'Switched company (multi-company login)'", {"c": gamma_id, "u": acme_user_id})
    check("A01 every switch is recorded in the target company's own log", len(rows) >= 2, rows)
    rows = db("SELECT 1 FROM audit_logs WHERE company_id = :c AND description LIKE 'Access to % removed%'",
              {"c": gamma_id})
    check("A02 removing a link is recorded", len(rows) == 1, rows)

    print(f"\n{passed} passed, {len(failed)} failed")
    if failed:
        print("Failed:", *failed, sep="\n  ")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
