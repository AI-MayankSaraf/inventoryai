"""Supplier Portal: grants, set-password link, sign-in, isolation, revoke, lockout.

Run with the backend venv (needs openpyxl/Pillow):
    backend/.venv/Scripts/python.exe tests/api_supplier_portal.py
"""
import os
API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")
PLATFORM_DB = os.environ.get(
    "TEST_PLATFORM_DATABASE_URL", "postgresql://inventoryai_platform:inventoryai_platform_dev@localhost/inventoryai"
)
import json, random, re, string, subprocess, urllib.error, urllib.request, uuid, os

B = API_URL
T = "".join(random.choices(string.ascii_lowercase, k=5))
EMAIL = f"ravi.{T}@supplier.example"
passed, failed = 0, []


def check(n, c, info=""):
    global passed
    if c:
        passed += 1; print("  ok  ", n)
    else:
        failed.append(n); print("  FAIL", n, "->", str(info)[:500])


def api(m, p, body=None, tok=None):
    h = {"content-type": "application/json"}
    if tok:
        h["authorization"] = "Bearer " + tok
    r = urllib.request.Request(B + p, data=json.dumps(body).encode() if body is not None else None, headers=h, method=m)
    try:
        x = urllib.request.urlopen(r, timeout=60)
        raw = x.read()
        return x.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw[:200]


def items(x):
    return x.get("items", []) if isinstance(x, dict) else x


def last_link(email):
    env = dict(os.environ)
    out = subprocess.run(["psql", PLATFORM_DB, "-At", "-c",
                          f"select body_preview from outbound_messages where to_address='{email}' order by queued_at desc limit 1"],
                         capture_output=True, text=True, env=env).stdout
    m = re.search(r"set-password\?token=([A-Za-z0-9_\-]+)", out)
    return m.group(1) if m else None


owner = api("POST", "/auth/login", {"email": "owner@acme-demo.test", "password": "Demo@12345"})[1]["access_token"]
sups = items(api("GET", "/catalog/suppliers?limit=500", tok=owner)[1])
_env = dict(os.environ)
_sid = subprocess.run(["psql", PLATFORM_DB, "-At", "-c",
    "select s.id from suppliers s where exists (select 1 from rfq_suppliers r where r.supplier_id=s.id) "
    "and exists (select 1 from supplier_quotations q where q.supplier_id=s.id) "
    "and exists (select 1 from purchase_orders p where p.supplier_id=s.id and p.status in ('sent','partially_received','received','closed')) "
    "limit 1"], capture_output=True, text=True, env=_env).stdout.strip()
sup = api("GET", f"/catalog/suppliers/{_sid}", tok=owner)[1]
print("   using supplier:", sup["name"])
other = next(s for s in sups if s["id"] != sup["id"])

print("== company grants access")
s, g = api("POST", f"/catalog/suppliers/{sup['id']}/portal-access", {"email": EMAIL, "full_name": "Ravi Kumar"}, owner)
check("G1 access granted, account waiting for a password", s == 201 and g["account_status"] == "invited", (s, g))
s, lst = api("GET", f"/catalog/suppliers/{sup['id']}/portal-access", tok=owner)
check("G2 listed on the supplier", s == 200 and any(a["email"] == EMAIL for a in lst), lst)
s, bad = api("POST", f"/catalog/suppliers/{uuid.uuid4()}/portal-access", {"email": "x@y.example"}, owner)
check("G3 unknown supplier -> 404", s == 404, (s, bad))

print("== supplier sets a password from the emailed link")
import time; time.sleep(1.5)
link = last_link(EMAIL)
check("P1 set-password link was emailed", bool(link), link)
s, r = api("POST", "/supplier-portal/set-password", {"token": link, "password": "short"})
check("P2 weak password refused", s in (400, 422), (s, r))
s, r = api("POST", "/supplier-portal/set-password", {"token": link, "password": "Supplier@2026"})
check("P3 password set", s == 204, (s, r))
s, r = api("POST", "/supplier-portal/set-password", {"token": link, "password": "Supplier@2027"})
check("P4 link works only once", s == 400, (s, r))

print("== sign in and see own documents")
s, r = api("POST", "/supplier-portal/login", {"email": EMAIL, "password": "wrong-password"})
check("L1 wrong password -> 401", s == 401, (s, r))
s, login = api("POST", "/supplier-portal/login", {"email": EMAIL.upper(), "password": "Supplier@2026"})
check("L2 signs in (email case-insensitive)", s == 200 and login.get("access_token"), (s, login))
tok = login["access_token"]
comps = login["principal"]["companies"]
check("L3 sees Acme as the company, as the right supplier", len(comps) == 1 and comps[0]["supplier_id"] == sup["id"], comps)
acc = comps[0]["access_id"]
s, act = api("GET", f"/supplier-portal/access/{acc}/activity", tok=tok)
check("A1 activity loads", s == 200, (s, act))
print(f"     rfqs={len(act['rfqs'])} quotations={len(act['quotations'])} pos={len(act['purchase_orders'])}")
check("A2 sees RFQs sent to them", len(act["rfqs"]) >= 1, act["rfqs"][:1])
check("A3 sees their quotations", len(act["quotations"]) >= 1, act["quotations"][:1])
check("A4 sees POs sent to them, never drafts", all(p["status"] in ("sent", "acknowledged", "partially_received", "received", "closed") for p in act["purchase_orders"]), act["purchase_orders"])
own_sup_quotes = items(api("GET", f"/procurement/quotations?limit=500", tok=owner)[1])
other_numbers = {q.get("quotation_number") for q in own_sup_quotes if q.get("supplier_id") and q.get("supplier_id") != sup["id"]}
check("A5 none of another supplier's quotations leak in", not ({q["number"] for q in act["quotations"]} & other_numbers - {None}), "")

print("== isolation")
s, r = api("GET", "/catalog/products?limit=1", tok=tok)
check("I1 supplier token refused on staff endpoints", s == 401, (s, r))
s, r = api("GET", "/supplier-portal/me", tok=owner)
check("I2 staff token refused on the portal", s == 401, (s, r))
s, r = api("GET", f"/supplier-portal/access/{uuid.uuid4()}/activity", tok=tok)
check("I3 someone else's / unknown access id -> 404", s == 404, (s, r))
s, r = api("GET", "/supplier-portal/me")
check("I4 no token -> 401", s == 401, (s, r))

print("== second company, same login")
s, cos = api("GET", "/auth/me/companies", tok=owner)
second = next((c for c in cos if not c["is_current"]), None)
if second:
    s, sw = api("POST", "/auth/switch-company", {"company_id": second["company_id"]}, owner)
    tok2 = sw["access_token"]
    s, sup2 = api("POST", "/catalog/suppliers", {"name": f"Portal Supplier {T}", "supplier_type": "Distributor", "gst_treatment": "unregistered",
                                                 "city": "Pune", "state_code": "27", "state_name": "Maharashtra"}, tok2)
    s, g2 = api("POST", f"/catalog/suppliers/{sup2['id']}/portal-access", {"email": EMAIL, "full_name": "Ravi Kumar"}, tok2)
    check("M1 a second company grants the same person", s == 201 and g2["account_status"] == "active", (s, g2))
    s, me = api("GET", "/supplier-portal/me", tok=tok)
    names = sorted(c["company_name"] for c in me["companies"])
    check("M2 one login now lists both companies", len(me["companies"]) == 2, names)
    s, lst1 = api("GET", f"/catalog/suppliers/{sup['id']}/portal-access", tok=tok2)
    check("M3 the second company can't see the first one's grants", s in (200, 404) and not (isinstance(lst1, list) and lst1), (s, lst1))
else:
    print("     (skipped: owner belongs to one company only)")

print("== revoke, lockout")
s, r = api("DELETE", f"/catalog/suppliers/{sup['id']}/portal-access/{acc}", tok=owner)
check("R1 company revokes access", s == 204, (s, r))
s, r = api("GET", f"/supplier-portal/access/{acc}/activity", tok=tok)
check("R2 revoked access is gone at once", s == 404, (s, r))
s, me = api("GET", "/supplier-portal/me", tok=tok)
check("R3 …and no longer listed", all(c["access_id"] != acc for c in me["companies"]), me)
for _ in range(5):
    api("POST", "/supplier-portal/login", {"email": EMAIL, "password": "nope-nope"})
s, r = api("POST", "/supplier-portal/login", {"email": EMAIL, "password": "Supplier@2026"})
check("K1 5 wrong passwords lock the account (429)", s == 429, (s, r))
s, aud = api("GET", "/audit-logs?limit=50", tok=owner)
check("K2 grants and revokes are in the audit trail", sum(1 for a in items(aud) if a.get("entity_type") == "supplier_portal_access") >= 2, "")
print(f"\n{passed} passed, {len(failed)} failed", failed)
