"""
E2E HTTP suite for the security audit of 3 Oct 2026, findings H2-H4.

Runs against the sample data (`python -m scripts.sample_data`) and proves
each fix from the outside, the way the audit's "Reproduce" steps did:

  H2  a Staff user cannot list or download quotations / invoices through
      /ai/documents; an Accountant still can
  H3  a godown-scoped manager sees only their godowns' GRNs, POs, alerts and
      dashboard figures; another godown's GRN or PO is a 404; the dashboard
      activity feed is empty without `audit.view`
  H4  a custom role with comparison.create but not comparison.convert/po.create
      cannot convert a comparison into purchase orders

    python -m scripts.e2e_security_audit [base_url]

Exit code 0 only if every check passes. Creates one custom role and one user
(named with a random suffix) and nothing else.
"""

from __future__ import annotations

import base64
import json
import sys
import urllib.error
import urllib.request
import uuid

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
PASSWORD = "Sample@2026"
SFX = uuid.uuid4().hex[:6]

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
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            try:
                return r.status, (json.loads(raw) if raw else None)
            except ValueError:  # a followed redirect to the file itself
                return r.status, raw[:200].decode(errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw.decode(errors="replace")


def login(email: str, password: str = PASSWORD) -> str:
    st, body = call("POST", "/auth/login", body={"email": email, "password": password})
    if st != 200:
        sys.exit(f"Cannot sign in as {email} ({st}). Run `python -m scripts.sample_data` on a clean database first.")
    return body["access_token"]


def claims(token: str) -> dict:
    part = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def items(x: object) -> list:
    return x.get("items", []) if isinstance(x, dict) else (x or [])


def main() -> int:
    owner = login("rajesh@ganesh-electricals.test")
    staff = login("ramesh@ganesh-electricals.test")      # Staff, Main godown only
    scoped_gm = login("anil@ganesh-electricals.test")    # Godown Manager, Pithampur only
    accountant = login("neha@ganesh-electricals.test")

    # ------------------------------------------------------------------ H2
    print("\n[H2] documents follow the permission of the record they feed")
    st, owner_docs = call("GET", "/ai/documents?limit=500", owner)
    check("H2.01 Owner lists AI documents", st == 200, owner_docs)
    owner_docs = items(owner_docs)
    restricted = [d for d in owner_docs if d.get("document_type") in
                  ("supplier_quotation", "rate_list", "price_revision", "proforma_invoice", "tax_invoice")]
    check("H2.02 sample data has quotation/proforma/invoice documents to test with", bool(restricted),
          [d.get("document_type") for d in owner_docs])

    st, staff_docs = call("GET", "/ai/documents?limit=500", staff)
    staff_me = claims(staff)
    staff_docs = items(staff_docs)
    leaked = [d for d in staff_docs if d.get("document_type") in
              ("supplier_quotation", "rate_list", "price_revision", "proforma_invoice", "tax_invoice")
              and d.get("uploaded_by") != staff_me.get("sub")]
    check("H2.03 Staff list shows no quotations, proformas or invoices", st == 200 and not leaked,
          [(d.get("original_filename"), d.get("document_type")) for d in leaked])
    st, tax = call("GET", "/ai/documents?document_type=tax_invoice", staff)
    check("H2.04 Staff filtering for tax_invoice gets nothing", st == 200 and not items(tax), tax)

    if restricted:
        doc = restricted[0]
        for path, label in ((f"/ai/documents/{doc['id']}", "metadata"),
                            (f"/ai/documents/{doc['id']}/download-link", "download link"),
                            (f"/ai/documents/{doc['id']}/file", "file"),
                            (f"/ai/documents/{doc['id']}/job", "job status")):
            st, body = call("GET", path, staff)
            check(f"H2.05 Staff gets 404 for a {doc['document_type']}'s {label}", st == 404, (st, body))
        st, body = call("GET", f"/ai/documents/{doc['id']}/download-link", accountant)
        check("H2.06 Accountant (holds the module permission) still gets the download link",
              st in (200, 404) and (st == 200 or "missing" in str(body).lower()), (st, body))
        st, body = call("GET", f"/ai/documents/{doc['id']}", owner)
        check("H2.07 Owner still reads it", st == 200, (st, body))

    # ------------------------------------------------------------------ H3
    print("\n[H3] godown scope on reads")
    gm_scope = claims(scoped_gm).get("godown_scope", {})
    in_scope = set(gm_scope.get("godown_ids", []))
    check("H3.00 the scoped manager really is scoped", not gm_scope.get("all") and bool(in_scope), gm_scope)

    st, all_grns = call("GET", "/procurement/goods-receipts?limit=500", owner)
    all_grns = items(all_grns)
    outside_grns = [g for g in all_grns if g["godown_id"] not in in_scope]
    check("H3.01 Owner sees receipts outside the manager's godown (so the test means something)",
          bool(outside_grns), len(all_grns))
    st, gm_grns = call("GET", "/procurement/goods-receipts?limit=500", scoped_gm)
    gm_grns = items(gm_grns)
    check("H3.02 scoped manager's GRN list holds only their godown", st == 200 and all(g["godown_id"] in in_scope for g in gm_grns),
          [g["godown_id"] for g in gm_grns if g["godown_id"] not in in_scope])
    if outside_grns:
        gid = outside_grns[0]["id"]
        for suffix in ("", "/postings", "/variances"):
            st, body = call("GET", f"/procurement/goods-receipts/{gid}{suffix}", scoped_gm)
            check(f"H3.03 another godown's GRN{suffix or ''} is a 404", st in (403, 404) if suffix == "/postings" else st == 404, (st, body))
        st, body = call("GET", f"/ai/attachments/goods_receipt/{gid}", scoped_gm)
        check("H3.04 another godown's GRN attachments are a 404", st == 404, (st, body))

    st, all_pos = call("GET", "/procurement/purchase-orders?limit=500", owner)
    outside_pos = [p for p in items(all_pos) if p["delivery_godown_id"] not in in_scope]
    st, gm_pos = call("GET", "/procurement/purchase-orders?limit=500", scoped_gm)
    check("H3.05 scoped manager's PO list holds only their godown",
          st == 200 and all(p["delivery_godown_id"] in in_scope for p in items(gm_pos)), st)
    if outside_pos:
        st, body = call("GET", f"/procurement/purchase-orders/{outside_pos[0]['id']}", scoped_gm)
        check("H3.06 another godown's PO is a 404", st == 404, (st, body))

    st, alerts = call("GET", "/alerts?limit=500", scoped_gm)
    check("H3.07 scoped manager's alerts are their godown's or company-wide",
          st == 200 and all(a.get("godown_id") in (None, *in_scope) for a in items(alerts)),
          [a.get("godown_id") for a in items(alerts) if a.get("godown_id") not in (None, *in_scope)])
    st_o, owner_summary = call("GET", "/alerts/summary", owner)
    st_g, gm_summary = call("GET", "/alerts/summary", scoped_gm)
    check("H3.08 alert badge count is scoped too", st_g == 200 and gm_summary["total"] == len(
        [a for a in items(alerts) if a.get("status") in ("new", "acknowledged")]), (gm_summary, owner_summary))

    st, owner_alerts = call("GET", "/alerts?limit=500", owner)
    other = [a for a in items(owner_alerts) if a.get("godown_id") and a["godown_id"] not in in_scope]
    if other:
        st, body = call("POST", f"/alerts/{other[0]['id']}/read", scoped_gm)
        check("H3.08b marking another godown's alert as read is a 404", st == 404, (st, body))
    st, dash = call("GET", "/dashboard/summary", scoped_gm)
    check("H3.09 scoped manager's dashboard counts only their godowns",
          st == 200 and dash["kpis"]["godown_count"] == len(in_scope), dash.get("kpis") if isinstance(dash, dict) else dash)
    staff_perms = set(claims(staff).get("permissions", []))
    st, dash = call("GET", "/dashboard/summary", staff)
    check("H3.10 dashboard activity feed is empty without audit.view",
          "audit.view" not in staff_perms and st == 200 and dash["activity"] == [], (st, dash.get("activity") if isinstance(dash, dict) else dash))
    st, dash = call("GET", "/dashboard/summary", owner)
    check("H3.11 Owner (audit.view) still gets the feed", st == 200 and len(dash["activity"]) > 0, st)

    # ------------------------------------------------------------------ H4
    print("\n[H4] converting a comparison needs comparison.convert AND po.create")
    st, role = call("POST", "/roles", owner, {
        "name": f"Buyer-lite {SFX}", "code": f"buyer_lite_{SFX}",
        "description": "security audit H4 test", "permissions": sorted(
            {"comparison.view", "comparison.create", "quotation.view", "rfq.view", "dashboard.view"})})
    check("H4.01 Owner creates a role with comparison.create only", st in (200, 201), (st, role))
    email = f"buyer-{SFX}@ganesh-electricals.test"
    st, inv = call("POST", "/users/invite", owner, {"email": email, "full_name": f"Buyer {SFX}",
                                                    "role_code": f"buyer_lite_{SFX}"})
    token = (inv or {}).get("invitation_token") if isinstance(inv, dict) else None
    check("H4.02 invite a user with that role (development returns the token)", st in (200, 201) and token, (st, inv))
    if token:
        call("POST", "/invitations/accept", None, {"invitation_token": token, "password": PASSWORD, "full_name": f"Buyer {SFX}"})
        buyer = login(email)
        st, comps = call("GET", "/procurement/comparisons", owner)
        comps = items(comps)
        check("H4.03 there is a comparison to try", bool(comps), comps)
        godown = next(iter(claims(owner).get("godown_scope", {}).get("godown_ids", [])), None) or \
            (all_grns[0]["godown_id"] if all_grns else str(uuid.uuid4()))
        if comps:
            st, body = call("POST", f"/procurement/comparisons/{comps[0]['id']}/convert", buyer,
                            {"delivery_godown_id": godown})
            check("H4.04 the convert endpoint refuses with 403 before doing anything",
                  st == 403 and "comparison.convert" in json.dumps(body), (st, body))

    print(f"\n{passed} passed, {len(failed)} failed")
    for name in failed:
        print(f"  - {name}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
