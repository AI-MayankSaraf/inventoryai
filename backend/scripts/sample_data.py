"""
Sample data for manual testing — every role, every main scenario, through
the real API.

Builds three companies on a clean database (see BACKEND-SETUP.md, "A real
start") and drives each step as the person whose job it is, so the audit
trail, numbering, stock ledger and alerts are exactly what real use leaves:

  * Shree Ganesh Electricals (Indore) — the main tenant. Every system role,
    a custom role, a godown-scoped manager, a deactivated user and a pending
    invitation. Catalogue, suppliers, opening stock, the full purchase cycle
    in each of its states, receiving with shortages/damage/excess, invoices
    matched and disputed, returns, transfers, write-offs, AI document
    review, alerts, reports and a supplier-portal login.
  * Patel Hardware Mart (Ahmedabad) — a second tenant, for isolation, and
    linked to the Ganesh owner so company switching can be tried.
  * Old Town Traders (Bhopal) — onboarded and then suspended.

Expected refusals (a Staff user creating a PO, a scoped manager touching
another godown, ...) are recorded as checks too: the step passes when the
API refuses.

    python -m scripts.sample_data                 # build it
    python -m scripts.sample_data --report out.json

Needs the API running in development mode (invitation tokens are returned
only there) and a platform admin. It creates one if it is missing:
qa-admin@inventoryai.test. Every sample login uses the password
Sample@2026. Refuses to run twice — it stops if the main company exists.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone

BASE = os.environ.get("API_URL", "http://127.0.0.1:8000")
PASSWORD = "Sample@2026"
QA_ADMIN = "qa-admin@inventoryai.test"
IST = timezone(timedelta(hours=5, minutes=30))
TODAY = datetime.now(IST).date()


def d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def ahead(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


# ----------------------------------------------------------------- results

RESULTS: list[dict] = []
SECTION = ""


def section(name: str) -> None:
    global SECTION
    SECTION = name
    print(f"\n== {name}")


def record(actor: str, action: str, ok: bool, detail: object = "", expected: str = "success") -> None:
    RESULTS.append({"section": SECTION, "actor": actor, "action": action, "ok": ok,
                    "expected": expected, "detail": detail if ok else _short(detail)})
    print(f"  {'ok  ' if ok else 'FAIL'} [{actor}] {action}" + ("" if ok else f"  -> {_short(detail)}"))


def _short(x: object) -> str:
    s = x if isinstance(x, str) else json.dumps(x, default=str)
    return s[:500]


# ----------------------------------------------------------------- HTTP


def _request(method: str, path: str, token: str | None, body: object = None,
             raw: bytes | None = None, content_type: str = "application/json") -> tuple[int, object]:
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", content_type)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            payload = r.read()
            return r.status, (json.loads(payload) if payload else None)
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, json.loads(payload)
        except Exception:
            return e.code, payload.decode(errors="replace")[:300]


def items(x: object) -> list:
    return x.get("items", []) if isinstance(x, dict) else (x or [])


class Actor:
    """A signed-in person. Re-signs in once if a long run outlives the token."""

    def __init__(self, label: str, email: str, password: str = PASSWORD):
        self.label, self.email, self.password = label, email, password
        self.token: str | None = None
        self.user_id: str | None = None

    def login(self) -> bool:
        st, b = _request("POST", "/auth/login", None, {"email": self.email, "password": self.password})
        if st == 200:
            self.token = b["access_token"]
            return True
        return False

    def call(self, method: str, path: str, body: object = None, **kw) -> tuple[int, object]:
        st, b = _request(method, path, self.token, body, **kw)
        if st == 401 and self.login():
            st, b = _request(method, path, self.token, body, **kw)
        return st, b

    # Expected to succeed: records the step, returns the body (None on failure).
    def do(self, action: str, method: str, path: str, body: object = None, **kw):
        st, b = self.call(method, path, body, **kw)
        ok = 200 <= st < 300
        record(self.label, action, ok, b if ok else {"status": st, "body": b})
        return b if ok else None

    # Expected to be refused: passes on a 4xx.
    def refused(self, action: str, method: str, path: str, body: object = None, codes=(400, 403, 404, 409, 422)):
        st, b = self.call(method, path, body)
        record(self.label, action, st in codes, {"status": st, "body": b}, expected=f"refused ({st})")
        return st


def accept_invitation(token: str, full_name: str) -> bool:
    st, _ = _request("POST", "/invitations/accept", None,
                     {"invitation_token": token, "password": PASSWORD, "full_name": full_name})
    return st in (200, 201)


def platform_sql(query: str) -> list:
    """Read-only lookups the API deliberately does not expose (emailed links)."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.core.config import get_settings
    import asyncpg

    url = get_settings().platform_database_url.replace("+asyncpg", "")

    async def run():
        conn = await asyncpg.connect(url)
        try:
            return [dict(r) for r in await conn.fetch(query)]
        finally:
            await conn.close()

    return asyncio.run(run())


def gstin(state: str, pan: str) -> str:
    """A GSTIN with a correct check character."""
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    body = f"{state}{pan}1Z"
    total = 0
    for i, c in enumerate(body):
        p = chars.index(c) * (2 if i % 2 else 1)
        total += p // 36 + p % 36
    return body + chars[(36 - total % 36) % 36]


def upload(actor: Actor, filename: str, content: bytes, supplier_id: str | None = None):
    boundary = f"----sample{uuid.uuid4().hex}"
    parts = [(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
              "Content-Type: text/csv\r\n\r\n").encode() + content + b"\r\n"]
    if supplier_id:
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"supplier_id\"\r\n\r\n{supplier_id}\r\n".encode())
    raw = b"".join(parts) + f"--{boundary}--\r\n".encode()
    return actor.call("POST", "/ai/documents", raw=raw, content_type=f"multipart/form-data; boundary={boundary}")


# ======================================================================


def ensure_qa_admin() -> Actor:
    admin = Actor("QA Platform Admin", QA_ADMIN)
    if not admin.login():
        env = dict(os.environ, PLATFORM_ADMIN_PASSWORD=PASSWORD)
        backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        subprocess.run([sys.executable, "-m", "app.db.seed", "--admin-email", QA_ADMIN,
                        "--admin-name", "QA Platform Admin"], cwd=backend, env=env, check=True,
                       capture_output=True)
        if not admin.login():
            sys.exit("Could not sign in as the QA platform admin.")
    return admin


def onboard(admin: Actor, label: str, body: dict) -> tuple[str, Actor]:
    out = admin.do(f"Onboard company '{body['name']}' on the {body['plan']} plan", "POST", "/platform/companies", body)
    if not out:
        sys.exit("Onboarding failed; nothing else can run.")
    company_id = (out.get("company") or {}).get("id") or out.get("id") or out.get("company_id")
    owner = Actor(label, body["owner_email"])
    ok = accept_invitation(out["invitation_token"], body["owner_full_name"]) and owner.login()
    record(label, "Accept the Owner invitation and set a password", ok, out)
    return company_id, owner


def invite(owner: Actor, label: str, email: str, name: str, role: str, godown_ids: list[str] | None = None,
           accept: bool = True) -> Actor:
    body = {"email": email, "full_name": name, "role_code": role}
    if godown_ids:
        body.update(godown_scope="specific", godown_ids=godown_ids)
    out = owner.do(f"Invite {name} as {role}" + (" (godown-scoped)" if godown_ids else ""), "POST", "/users/invite", body)
    actor = Actor(label, email)
    if out and accept:
        ok = accept_invitation(out["invitation_token"], name) and actor.login()
        record(label, "Accept invitation, set password, sign in", ok, out)
        me = actor.call("GET", "/auth/me")[1] or {}
        actor.user_id = (me.get("user") or me).get("id")
    return actor


def main() -> int:  # noqa: C901 — a scenario script is a long list of steps
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", help="write the step results as JSON here")
    args = parser.parse_args()

    st, health = _request("GET", "/health", None)
    if st != 200:
        sys.exit(f"API not reachable at {BASE}: {st}")

    # ================================================== platform
    section("1. Platform admin: onboard companies")
    admin = ensure_qa_admin()
    record(admin.label, f"Sign in as {QA_ADMIN}", True)
    existing = items(admin.call("GET", "/platform/companies", None)[1])
    if any(c.get("name") == "Shree Ganesh Electricals" for c in existing):
        sys.exit("Sample data already exists (Shree Ganesh Electricals). Reset the database first.")

    ganesh_id, owner = onboard(admin, "Owner · Rajesh Agarwal", {
        "name": "Shree Ganesh Electricals", "legal_name": "Shree Ganesh Electricals Pvt Ltd",
        "gstin": gstin("23", "AAKCS4821M"), "state_code": "23", "state_name": "Madhya Pradesh", "city": "Indore",
        "email": "accounts@ganesh-electricals.test", "phone": "9826012345", "plan": "Growth",
        "owner_email": "rajesh@ganesh-electricals.test", "owner_full_name": "Rajesh Agarwal"})
    patel_id, patel = onboard(admin, "Owner · Bhavesh Patel", {
        "name": "Patel Hardware Mart", "gstin": gstin("24", "AAFFP7731K"), "state_code": "24",
        "state_name": "Gujarat", "city": "Ahmedabad", "plan": "Starter",
        "owner_email": "bhavesh@patel-hardware.test", "owner_full_name": "Bhavesh Patel"})
    oldtown_id, oldtown = onboard(admin, "Owner · Imran Khan", {
        "name": "Old Town Traders", "state_code": "23", "state_name": "Madhya Pradesh", "city": "Bhopal",
        "plan": "Trial", "owner_email": "imran@oldtown-traders.test", "owner_full_name": "Imran Khan"})

    # ================================================== company setup
    section("2. Owner: company settings, godowns, team")
    owner.do("Set approval limit ₹2,00,000, 1% price tolerance, 5% excess receipt", "PATCH", "/company/settings", {
        "require_po_approval_above": 200000, "variance_price_tolerance_pct": 1,
        "allow_grn_excess_receipt": True, "grn_excess_tolerance_pct": 5, "po_delay_grace_days": 2})
    owner.do("Add payment term '60 Days'", "POST", "/company/lists", {"list_key": "payment_terms", "value": "60 Days"})
    uoms = {u["code"]: u["id"] for u in owner.call("GET", "/catalog/uoms-available")[1]}
    NOS, BOX, PACK, MTR, KG = uoms["Nos"], uoms["Box"], uoms["Pack"], uoms["Metre"], uoms["Kg"]
    main_gd = next(g for g in items(owner.call("GET", "/catalog/godowns?limit=50")[1]) if g["is_default"])
    MAIN = main_gd["id"]
    owner.do("Rename default godown to 'Main Warehouse – Siyaganj'", "PATCH", f"/catalog/godowns/{MAIN}",
             {"name": "Main Warehouse – Siyaganj", "city": "Indore", "address": "42 Siyaganj Main Road, Indore"})
    pith = owner.do("Create godown 'Pithampur Warehouse'", "POST", "/catalog/godowns", {
        "name": "Pithampur Warehouse", "code": "PTH", "city": "Pithampur", "state_code": "23",
        "address": "Plot 7, Sector 3, Pithampur Industrial Area", "capacity_value": 5000, "capacity_uom_id": NOS})
    PITH = pith["id"]
    retail = owner.do("Create godown 'Retail Counter – Rajwada'", "POST", "/catalog/godowns", {
        "name": "Retail Counter – Rajwada", "code": "RJW", "city": "Indore", "state_code": "23"})
    RETAIL = retail["id"]

    sup_perms = sorted({"dashboard.view", "godown.view", "grn.view", "grn.create", "grn.confirm", "inventory.view",
                        "inventory.transfer", "product.view", "supplier.view", "master.view", "company.view",
                        "document.view", "document.upload", "alert.view", "ai.assistant", "po.view"})
    role = owner.do("Create custom role 'Store Supervisor' (receive + confirm + transfer)", "POST", "/roles", {
        "name": "Store Supervisor", "code": "store_supervisor",
        "description": "Receives and confirms goods and moves stock between godowns", "permissions": sup_perms})
    owner.refused("Owner cannot put a platform-admin permission into a custom role", "POST", "/roles",
                  {"name": "Bad Role", "permissions": ["platform.companies.manage"]})

    pm = invite(owner, "Purchase Manager · Priya Sharma", "priya@ganesh-electricals.test", "Priya Sharma", "purchase_manager")
    gm = invite(owner, "Godown Manager · Suresh Yadav", "suresh@ganesh-electricals.test", "Suresh Yadav", "godown_manager")
    gm2 = invite(owner, "Godown Manager (Pithampur only) · Anil Verma", "anil@ganesh-electricals.test",
                 "Anil Verma", "godown_manager", godown_ids=[PITH])
    acct = invite(owner, "Accountant · Neha Jain", "neha@ganesh-electricals.test", "Neha Jain", "accountant")
    staff = invite(owner, "Staff (Main only) · Ramesh Kumar", "ramesh@ganesh-electricals.test", "Ramesh Kumar",
                   "staff", godown_ids=[MAIN])
    viewer = invite(owner, "Viewer · CA Vikas Mehta", "vikas@ganesh-electricals.test", "CA Vikas Mehta", "viewer")
    sup_role = (role or {}).get("code", "store_supervisor")
    supv = invite(owner, "Store Supervisor · Kavita Singh", "kavita@ganesh-electricals.test", "Kavita Singh", sup_role)
    former = invite(owner, "Staff (leaver) · Deepak Joshi", "deepak@ganesh-electricals.test", "Deepak Joshi", "staff")
    invite(owner, "-", "pooja@ganesh-electricals.test", "Pooja Malviya", "staff", accept=False)

    if gm2.user_id:
        owner.do("Make Anil Verma in-charge of Pithampur Warehouse", "PATCH", f"/catalog/godowns/{PITH}",
                 {"incharge_user_id": gm2.user_id})
    if former.user_id:
        owner.do("Deactivate Deepak Joshi (left the company)", "PATCH", f"/users/{former.user_id}", {"status": "inactive"})
        st, _ = _request("POST", "/auth/login", None, {"email": former.email, "password": PASSWORD})
        record(former.label, "Deactivated user cannot sign in", st in (401, 403), {"status": st}, expected=f"refused ({st})")

    # ================================================== master data
    section("3. Purchase Manager: catalogue and suppliers")
    cats = {}
    for name in ("Wires & Cables", "Switchgear & MCBs", "Switches & Sockets", "Lighting", "Fans", "Batteries", "Accessories"):
        c = pm.do(f"Category '{name}'", "POST", "/catalog/categories", {"name": name})
        cats[name] = c and c["id"]
    brands = {}
    for name, mfr in (("Polycab", "Polycab India Ltd"), ("Havells", "Havells India Ltd"), ("Anchor", "Panasonic Life Solutions"),
                      ("Philips", "Signify Innovations"), ("Crompton", "Crompton Greaves Consumer"), ("Legrand", "Legrand India"),
                      ("Duracell", "Duracell India")):
        b = pm.do(f"Brand '{name}'", "POST", "/catalog/brands", {"name": name, "manufacturer_name": mfr})
        brands[name] = b and b["id"]

    V: dict[str, dict] = {}

    def product(name, cat, brand, hsn, gst, uom, variants, tracking="none", active=True):
        p = pm.do(f"Product '{name}'", "POST", "/catalog/products", {
            "name": name, "base_uom_id": uom, "category_id": cats.get(cat), "brand_id": brands.get(brand),
            "hsn_code": hsn, "gst_rate": gst, "tracking_type": tracking, "is_active": active})
        if not p:
            return
        for sku, vname, buy, sell, mrp, rop, roq in variants:
            v = pm.do(f"  Variant {sku} — {vname}", "POST", "/catalog/variants", {
                "product_id": p["id"], "sku": sku, "uom_id": uom, "variant_name": vname, "purchase_price": buy,
                "sale_price": sell, "mrp": mrp, "reorder_point": rop, "reorder_qty": roq, "lead_time_days": 7,
                "is_active": active})
            if v:
                V[sku] = {"id": v["id"], "uom": uom, "price": buy, "gst": gst, "name": f"{name} {vname}"}

    product("Polycab FR PVC Wire (90 m coil)", "Wires & Cables", "Polycab", "8544", 18, NOS, [
        ("PC-FR-1.5-RD", "1.5 sq mm Red", 1350, 1550, 1890, 40, 100),
        ("PC-FR-1.5-BK", "1.5 sq mm Black", 1350, 1550, 1890, 40, 100),
        ("PC-FR-2.5-RD", "2.5 sq mm Red", 2150, 2450, 2990, 30, 60),
        ("PC-FR-4.0-RD", "4.0 sq mm Red", 3400, 3850, 4700, 10, 20)])
    product("Havells MCB", "Switchgear & MCBs", "Havells", "8536", 18, NOS, [
        ("HV-MCB-16A-SP", "16A Single Pole C-curve", 180, 240, 310, 100, 240),
        ("HV-MCB-32A-DP", "32A Double Pole C-curve", 520, 690, 880, 30, 60)])
    product("Anchor Roma Modular", "Switches & Sockets", "Anchor", "8536", 18, NOS, [
        ("AN-ROMA-SW6A", "6A 1-way Switch", 28, 38, 52, 300, 600),
        ("AN-ROMA-SK16A", "16A 3-pin Socket", 95, 125, 160, 100, 200)])
    product("Philips LED Bulb", "Lighting", "Philips", "8539", 12, NOS, [
        ("PH-LED-9W", "9W Cool Day Light B22", 78, 110, 140, 200, 500),
        ("PH-LED-12W", "12W Cool Day Light B22", 105, 145, 190, 150, 300)])
    product("Philips LED Batten 20W", "Lighting", "Philips", "9405", 18, NOS, [
        ("PH-BAT-20W", "4 ft Cool White", 210, 280, 360, 60, 120)])
    product("Crompton HS Plus Ceiling Fan 1200 mm", "Fans", "Crompton", "8414", 18, NOS, [
        ("CR-FAN-1200-BR", "Brown", 1650, 2050, 2600, 20, 50),
        ("CR-FAN-1200-WH", "White", 1650, 2050, 2600, 20, 50)])
    product("Legrand Distribution Board 8-way SPN", "Switchgear & MCBs", "Legrand", "8537", 18, NOS, [
        ("LG-DB-8W", "8-way Single Door", 1150, 1450, 1850, 10, 20)])
    product("PVC Conduit Pipe 20 mm", "Accessories", None, "3917", 18, MTR, [
        ("ACC-CONDUIT-20", "Medium gauge, per metre", 18, 24, 30, 500, 1500)])
    product("Copper Earthing Wire 8 SWG", "Wires & Cables", None, "7408", 18, KG, [
        ("ACC-EARTH-8SWG", "Bare copper, per kg", 860, 980, 1100, 20, 50)])
    product("Duracell AA Alkaline (Pack of 4)", "Batteries", "Duracell", "8506", 18, PACK, [
        ("DU-AA-4", "Pack of 4", 150, 185, 220, 50, 120)], tracking="batch")
    product("Anchor Penta Switch 6A (discontinued)", "Switches & Sockets", "Anchor", "8536", 18, NOS, [
        ("AN-PENTA-SW6A", "Old range", 18, 25, 32, 0, 0)], active=False)

    if "HV-MCB-16A-SP" in V:
        pm.do("MCB 16A is bought in boxes of 12 (unit conversion)", "POST",
              f"/catalog/variants/{V['HV-MCB-16A-SP']['id']}/uom-conversions",
              {"from_uom_id": BOX, "factor": 12, "is_purchase_default": False})
    if "PC-FR-1.5-RD" in V:
        gm.do("Per-godown reorder levels for 1.5 sq mm Red wire", "PUT",
              f"/catalog/variants/{V['PC-FR-1.5-RD']['id']}/godown-policies", {"policies": [
                  {"godown_id": MAIN, "reorder_point": 30, "reorder_qty": 80, "max_stock": 200, "is_stocked": True},
                  {"godown_id": PITH, "reorder_point": 15, "reorder_qty": 40, "max_stock": 100, "is_stocked": True},
                  {"godown_id": RETAIL, "reorder_point": 0, "reorder_qty": 0, "is_stocked": False}]})

    S: dict[str, str] = {}

    def supplier(key, body, contacts=(), links=()):
        s = pm.do(f"Supplier '{body['name']}' ({body.get('city')}, {body.get('gst_treatment', 'regular')})",
                  "POST", "/catalog/suppliers", body)
        if not s:
            return
        S[key] = s["id"]
        for c in contacts:
            pm.do(f"  Contact {c['name']}", "POST", f"/catalog/suppliers/{s['id']}/contacts", c)
        for sku, their_sku, preferred in links:
            if sku in V:
                pm.do(f"  Supplies {sku} as '{their_sku}'", "POST", f"/catalog/suppliers/{s['id']}/products", {
                    "product_variant_id": V[sku]["id"], "supplier_sku": their_sku, "is_preferred": preferred,
                    "lead_time_days": 5, "match_source": "manual"})

    supplier("malwa", {"name": "Malwa Cable Distributors", "supplier_type": "Distributor", "supplier_code": "SUP-MCD",
                       "gstin": gstin("23", "AAHFM2290Q"), "pan": "AAHFM2290Q", "city": "Indore", "state_code": "23",
                       "state_name": "Madhya Pradesh", "address": "18 Loha Mandi, Indore", "pincode": "452002",
                       "primary_contact_name": "Mahesh Gupta", "phone": "9425011111", "email": "sales@malwacables.test",
                       "payment_terms": "30 Days", "payment_terms_days": 30, "credit_limit": 500000,
                       "bank_name": "HDFC Bank", "bank_account_no": "50200012345678", "bank_ifsc": "HDFC0000123"},
             contacts=[{"name": "Mahesh Gupta", "designation": "Sales Head", "phone": "9425011111",
                        "email": "sales@malwacables.test", "is_primary": True},
                       {"name": "Sunita Gupta", "designation": "Accounts", "email": "accounts@malwacables.test"}],
             links=[("PC-FR-1.5-RD", "POLY-FRLS-1.5R", True), ("PC-FR-1.5-BK", "POLY-FRLS-1.5B", True),
                    ("PC-FR-2.5-RD", "POLY-FRLS-2.5R", True), ("PC-FR-4.0-RD", "POLY-FRLS-4R", True),
                    ("ACC-EARTH-8SWG", "CU-8SWG", True)])
    supplier("shyam", {"name": "Shree Shyam Electricals", "supplier_type": "Distributor", "supplier_code": "SUP-SSE",
                       "gstin": gstin("27", "AAPFS6612L"), "city": "Mumbai", "state_code": "27",
                       "state_name": "Maharashtra", "address": "Lohar Chawl, Mumbai", "phone": "9820022222",
                       "email": "orders@shyamelectricals.test", "payment_terms": "45 Days", "payment_terms_days": 45,
                       "credit_limit": 800000},
             contacts=[{"name": "Gopal Agarwal", "designation": "Proprietor", "phone": "9820022222", "is_primary": True}],
             links=[("HV-MCB-16A-SP", "HAV-DHMGCSPF016", True), ("HV-MCB-32A-DP", "HAV-DHMGCDPF032", True),
                    ("CR-FAN-1200-BR", "CG-HSPLUS-48-BR", True), ("CR-FAN-1200-WH", "CG-HSPLUS-48-WH", True),
                    ("LG-DB-8W", "LEG-607808", False)])
    supplier("gujarat", {"name": "Gujarat Switchgear Traders", "supplier_type": "Distributor", "supplier_code": "SUP-GST",
                         "gstin": gstin("24", "AAGFG4401D"), "city": "Ahmedabad", "state_code": "24",
                         "state_name": "Gujarat", "phone": "9898033333", "email": "quotes@gujswitchgear.test",
                         "payment_terms": "30 Days", "payment_terms_days": 30},
             links=[("AN-ROMA-SW6A", "ROMA-30001", True), ("AN-ROMA-SK16A", "ROMA-30016", True),
                    ("LG-DB-8W", "LEG-DB8", True), ("HV-MCB-16A-SP", "HAV-MCB16", False)])
    supplier("bright", {"name": "Bright Lights Agencies", "supplier_type": "Distributor", "supplier_code": "SUP-BLA",
                        "gstin": gstin("07", "AAJFB9087C"), "city": "New Delhi", "state_code": "07", "state_name": "Delhi",
                        "phone": "9811044444", "email": "sales@brightlights.test", "payment_terms": "Advance"},
             links=[("PH-LED-9W", "PH-9W-CDL", True), ("PH-LED-12W", "PH-12W-CDL", True),
                    ("PH-BAT-20W", "PH-BN018-20W", True), ("DU-AA-4", "DUR-AA4", True)])
    supplier("rajwada", {"name": "Rajwada Electric Stores", "supplier_type": "Local Supplier", "gst_treatment": "unregistered",
                         "city": "Indore", "state_code": "23", "state_name": "Madhya Pradesh", "phone": "9300055555",
                         "payment_terms": "Cash on Delivery"},
             links=[("ACC-CONDUIT-20", "PVC 20mm", True)])
    supplier("oldstar", {"name": "Old Star Electricals", "supplier_type": "Local Supplier", "gst_treatment": "unregistered",
                         "city": "Indore", "state_code": "23", "state_name": "Madhya Pradesh", "status": "inactive",
                         "notes": "Stopped dealing — repeated quality issues"})

    # ================================================== opening stock
    section("4. Godown managers: opening stock")
    opening = {MAIN: {"PC-FR-1.5-RD": 85, "PC-FR-1.5-BK": 60, "PC-FR-2.5-RD": 45, "PC-FR-4.0-RD": 12,
                      "HV-MCB-16A-SP": 300, "HV-MCB-32A-DP": 40, "AN-ROMA-SW6A": 900, "AN-ROMA-SK16A": 260,
                      "PH-LED-9W": 380, "PH-LED-12W": 140, "PH-BAT-20W": 90, "CR-FAN-1200-BR": 35,
                      "CR-FAN-1200-WH": 18, "LG-DB-8W": 14, "ACC-CONDUIT-20": 2400, "ACC-EARTH-8SWG": 65},
               PITH: {"PC-FR-1.5-RD": 40, "PC-FR-2.5-RD": 30, "HV-MCB-16A-SP": 120, "CR-FAN-1200-BR": 25,
                      "ACC-CONDUIT-20": 1500}}
    for gd, who, gname in ((MAIN, gm, "Main"), (PITH, gm2, "Pithampur")):
        for sku, qty in opening[gd].items():
            if sku in V:
                who.do(f"Opening stock {qty} × {sku} at {gname}", "POST", "/inventory/transactions", {
                    "txn_type": "OPENING_STOCK", "product_variant_id": V[sku]["id"], "godown_id": gd, "quantity": qty,
                    "uom_id": V[sku]["uom"], "direction": "increase", "txn_date": d(60), "remarks": "Opening balance"})
    gm2.refused("Pithampur-only manager cannot post stock at Main Warehouse", "POST", "/inventory/transactions", {
        "txn_type": "OPENING_STOCK", "product_variant_id": V["LG-DB-8W"]["id"], "godown_id": MAIN, "quantity": 5,
        "uom_id": NOS, "direction": "increase", "txn_date": d(60)})

    def line(sku, qty, price=None, **extra):
        v = V[sku]
        return {"product_variant_id": v["id"], "quantity": qty, "uom_id": v["uom"],
                "unit_price": v["price"] if price is None else price, "gst_rate": v["gst"], **extra}

    def po_items(po):
        return {i["product_variant_id"]: i for i in po["items"]}

    def run_po(who, po, steps=("submit", "approve", "send")):
        for step in steps:
            # Above the approval limit only the Owner (po.approve_high_value) may approve.
            actor = owner if step == "approve" and float(po.get("total_amount") or 0) > 200000 else who
            r = actor.do(f"PO {po.get('po_number', '')} → {step}" + (" (above ₹2 lakh limit)" if actor is owner else ""),
                         "POST", f"/procurement/purchase-orders/{po['id']}/{step}")
            if r is None:
                return None
        return pm.call("GET", f"/procurement/purchase-orders/{po['id']}")[1]

    # ================================================== scenario A
    section("5. Scenario A: RFQ → 3 quotations → comparison → PO → proforma → GRN → invoice → paid")
    rfq = pm.do("RFQ for wires (3 lines, delivery to Main)", "POST", "/procurement/rfqs", {
        "subject": "Monthly wire replenishment – September", "rfq_date": d(40), "delivery_godown_id": MAIN,
        "expected_delivery_date": d(30), "notes": "Polycab FR only. Fresh stock (2026 manufacturing).",
        "items": [{"product_variant_id": V[s]["id"], "quantity": q, "uom_id": NOS, "expected_price": V[s]["price"]}
                  for s, q in (("PC-FR-1.5-RD", 100), ("PC-FR-1.5-BK", 60), ("PC-FR-2.5-RD", 50))]})
    pm.do("Send RFQ to Malwa, Shyam and Gujarat", "POST", f"/procurement/rfqs/{rfq['id']}/send",
          {"supplier_ids": [S["malwa"], S["shyam"], S["gujarat"]]})
    rfq_items = {i["product_variant_id"]: i["id"] for i in rfq["items"]}
    quotes = {}
    for key, num, prices, terms in (("malwa", "MCD/Q/2026/0912", (1330, 1330, 2120), "30 Days"),
                                    ("shyam", "SSE-QT-5581", (1310, 1345, 2160), "45 Days"),
                                    ("gujarat", "GST/2026/Q-221", (1395, 1395, 2240), "Advance")):
        q = pm.do(f"Record quotation {num} from {key}", "POST", "/procurement/quotations", {
            "supplier_id": S[key], "rfq_id": rfq["id"], "quotation_number": num, "quotation_date": d(38),
            "valid_until": ahead(30), "payment_terms": terms, "delivery_period_days": 7, "freight_terms": "Free delivery",
            "items": [dict(line(s, q_, p), rfq_item_id=rfq_items[V[s]["id"]])
                      for s, q_, p in zip(("PC-FR-1.5-RD", "PC-FR-1.5-BK", "PC-FR-2.5-RD"), (100, 60, 50), prices)]})
        quotes[key] = q
    pm.do("Approve Malwa quotation", "POST", f"/procurement/quotations/{quotes['malwa']['id']}/approve")
    pm.do("Approve Shyam quotation", "POST", f"/procurement/quotations/{quotes['shyam']['id']}/approve")
    pm.do("Reject Gujarat quotation (advance payment, highest price)", "POST",
          f"/procurement/quotations/{quotes['gujarat']['id']}/reject", {"reason": "Highest price and wants full advance"})
    cmp_ = pm.do("Build comparison of approved quotations", "POST", "/procurement/comparisons",
                 {"rfq_id": rfq["id"], "name": "Wire replenishment – Sept"})
    if cmp_:
        # Shyam is ₹20 cheaper on 1.5 Red but from Mumbai with 45-day lead; buy local.
        malwa_items = {i["product_variant_id"]: i["id"] for i in quotes["malwa"]["items"]}
        for row in cmp_.get("rows") or []:
            if row.get("product_variant_id") == V["PC-FR-1.5-RD"]["id"]:
                pm.do("Override 1.5 Red line to Malwa (local, faster delivery)", "PATCH",
                      f"/procurement/comparisons/{cmp_['id']}/lines/{row['line_id']}",
                      {"quotation_item_id": malwa_items[V["PC-FR-1.5-RD"]["id"]],
                       "reason": "Local supplier, 2-day delivery vs 7 days from Mumbai"})
        conv = pm.do("Convert comparison into purchase orders", "POST", f"/procurement/comparisons/{cmp_['id']}/convert",
                     {"delivery_godown_id": MAIN, "expected_delivery_date": d(30)})
        pos_a = conv if isinstance(conv, list) else (conv or {}).get("purchase_orders", [conv] if conv else [])
        for po in pos_a:
            po = run_po(pm, po)
            if not po:
                continue
            is_malwa = po["supplier_id"] == S["malwa"]
            sup_name = "Malwa" if is_malwa else "Shyam"
            pi = pm.do(f"Proforma from {sup_name} against {po['po_number']}", "POST", "/proforma-invoices", {
                "supplier_id": po["supplier_id"], "purchase_order_id": po["id"], "proforma_number": f"PI-{po['po_number']}",
                "proforma_date": d(35), "valid_until": d(20),
                "items": [{"purchase_order_item_id": i["id"], "product_variant_id": i["product_variant_id"],
                           "quantity": float(i["quantity"]), "uom_id": i["uom_id"], "unit_price": float(i["unit_price"]),
                           "gst_rate": float(i["gst_rate"])} for i in po["items"]]})
            if pi:
                acct.do(f"Approve proforma {pi.get('proforma_number')} (matches PO)", "POST", f"/proforma-invoices/{pi['id']}/approve")
            grn = staff.do(f"Draft GRN at Main for {po['po_number']} (full quantity)", "POST", "/procurement/goods-receipts", {
                "supplier_id": po["supplier_id"], "purchase_order_id": po["id"], "godown_id": MAIN, "grn_date": d(31),
                "vehicle_number": "MP09 GH 4521", "transporter_name": "Indore Roadways", "lr_number": f"LR{po['po_number'][-4:]}",
                "supplier_challan_number": f"DC-{po['po_number'][-4:]}", "supplier_challan_date": d(32),
                "items": [{"purchase_order_item_id": i["id"], "product_variant_id": i["product_variant_id"],
                           "received_quantity": float(i["quantity"]), "accepted_quantity": float(i["quantity"]),
                           "uom_id": i["uom_id"], "unit_price": float(i["unit_price"])} for i in po["items"]]})
            if not grn:
                continue
            staff.refused("Staff cannot confirm a GRN", "POST", f"/procurement/goods-receipts/{grn['id']}/confirm")
            gm.do(f"Confirm GRN {grn['grn_number']} → stock in", "POST", f"/procurement/goods-receipts/{grn['id']}/confirm")
            grn = gm.call("GET", f"/procurement/goods-receipts/{grn['id']}")[1]
            gitems = {i["product_variant_id"]: i["id"] for i in grn["items"]}
            inv = acct.do(f"Record {sup_name} tax invoice for {grn['grn_number']}", "POST", "/supplier-invoices", {
                "supplier_id": po["supplier_id"], "invoice_number": f"{'MCD' if is_malwa else 'SSE'}/26-27/{po['po_number'][-4:]}",
                "invoice_date": d(30), "due_date": d(0 if is_malwa else -15), "purchase_order_id": po["id"],
                "goods_receipt_id": grn["id"],
                "items": [{"purchase_order_item_id": i["id"], "goods_receipt_item_id": gitems[i["product_variant_id"]],
                           "product_variant_id": i["product_variant_id"], "quantity": float(i["quantity"]),
                           "uom_id": i["uom_id"], "unit_price": float(i["unit_price"]), "gst_rate": float(i["gst_rate"])}
                          for i in po["items"]]})
            if not inv:
                continue
            acct.do("3-way match invoice ↔ PO ↔ GRN", "POST", f"/supplier-invoices/{inv['id']}/match")
            acct.do("Send invoice for review", "POST", f"/supplier-invoices/{inv['id']}/status", {"status": "under_review"})
            acct.do("Approve invoice", "POST", f"/supplier-invoices/{inv['id']}/approve")
            total = float(acct.call("GET", f"/supplier-invoices/{inv['id']}")[1].get("total_amount") or 0)
            if is_malwa:
                acct.do(f"Pay in full (₹{total:,.0f})", "POST", f"/supplier-invoices/{inv['id']}/payments", {"amount": total})
            else:
                acct.do("Part payment ₹50,000", "POST", f"/supplier-invoices/{inv['id']}/payments", {"amount": 50000})

    # ================================================== scenario B
    section("6. Scenario B: high-value fan order — approval limit, partial + damaged receipt, return, disputed invoice")
    po_b = pm.do("Direct PO to Shyam: 120 fans + 4 DBs (≈ ₹2.4 lakh, above the limit)", "POST",
                 "/procurement/purchase-orders", {
                     "supplier_id": S["shyam"], "delivery_godown_id": PITH, "po_date": d(25), "expected_delivery_date": d(15),
                     "payment_terms": "45 Days", "delivery_terms": "Door Delivery", "freight_amount": 2500,
                     "notes": "Pre-summer stock for Pithampur. Deliver before 20th.",
                     "items": [line("CR-FAN-1200-BR", 80), line("CR-FAN-1200-WH", 40), line("LG-DB-8W", 4)]})
    if po_b:
        pm.do(f"Submit {po_b['po_number']} for approval", "POST", f"/procurement/purchase-orders/{po_b['id']}/submit")
        pm.refused("Purchase Manager cannot approve a PO above ₹2,00,000", "POST",
                   f"/procurement/purchase-orders/{po_b['id']}/approve", codes=(403, 409, 422))
        acct.refused("Accountant cannot approve purchase orders", "POST", f"/procurement/purchase-orders/{po_b['id']}/approve")
        owner.do("Owner approves the high-value PO", "POST", f"/procurement/purchase-orders/{po_b['id']}/approve")
        pm.do("Send PO to supplier", "POST", f"/procurement/purchase-orders/{po_b['id']}/send")
        po_b = pm.call("GET", f"/procurement/purchase-orders/{po_b['id']}")[1]
        pi_b = pm.do("Proforma from Shyam quotes fans at ₹1,720 (PO: ₹1,650)", "POST", "/proforma-invoices", {
            "supplier_id": S["shyam"], "purchase_order_id": po_b["id"], "proforma_number": "SSE/PI/7781",
            "proforma_date": d(24), "advance_percent": 20,
            "items": [{"purchase_order_item_id": i["id"], "product_variant_id": i["product_variant_id"],
                       "quantity": float(i["quantity"]), "uom_id": i["uom_id"],
                       "unit_price": 1720 if i["product_variant_id"] in (V["CR-FAN-1200-BR"]["id"], V["CR-FAN-1200-WH"]["id"]) else float(i["unit_price"]),
                       "gst_rate": float(i["gst_rate"])} for i in po_b["items"]]})
        if pi_b:
            pm.do("Raise a query on the price difference", "POST", f"/proforma-invoices/{pi_b['id']}/raise-query",
                  {"note": "PO price is ₹1,650 per fan as per quotation SSE-QT-5581. Please revise."})
            acct.refused("Accountant cannot approve a proforma with a price variance", "POST",
                         f"/proforma-invoices/{pi_b['id']}/approve", codes=(403, 409, 422))
            owner.do("Owner accepts the variance (supplier cites copper price rise)", "POST", f"/proforma-invoices/{pi_b['id']}/approve")
        it = po_items(po_b)
        fb, fw, db_ = it[V["CR-FAN-1200-BR"]["id"]], it[V["CR-FAN-1200-WH"]["id"]], it[V["LG-DB-8W"]["id"]]
        staff.refused("Main-only staff cannot receive at Pithampur", "POST", "/procurement/goods-receipts", {
            "supplier_id": S["shyam"], "purchase_order_id": po_b["id"], "godown_id": PITH, "grn_date": d(18),
            "items": [{"purchase_order_item_id": fb["id"], "product_variant_id": fb["product_variant_id"],
                       "received_quantity": 1, "accepted_quantity": 1, "uom_id": NOS}]})
        grn_b = gm2.do("GRN at Pithampur: 80 brown (6 damaged), 25 of 40 white, 4 DBs", "POST", "/procurement/goods-receipts", {
            "supplier_id": S["shyam"], "purchase_order_id": po_b["id"], "godown_id": PITH, "grn_date": d(18),
            "vehicle_number": "MH04 KL 8890", "transporter_name": "VRL Logistics", "lr_number": "VRL-552190",
            "eway_bill_number": "231009876543", "supplier_challan_number": "SSE/DC/4410",
            "items": [{"purchase_order_item_id": fb["id"], "product_variant_id": fb["product_variant_id"],
                       "received_quantity": 80, "accepted_quantity": 74, "uom_id": NOS, "unit_price": 1650,
                       "issue_type": "damaged", "rejection_reason": "6 cartons crushed, blades bent", "remarks": "6 rejected at unloading — photos sent to supplier"},
                      {"purchase_order_item_id": fw["id"], "product_variant_id": fw["product_variant_id"],
                       "received_quantity": 25, "accepted_quantity": 25, "uom_id": NOS, "unit_price": 1650,
                       "issue_type": "short", "remarks": "Balance 15 to follow"},
                      {"purchase_order_item_id": db_["id"], "product_variant_id": db_["product_variant_id"],
                       "received_quantity": 4, "accepted_quantity": 4, "uom_id": NOS, "unit_price": 1150}]})
        if grn_b:
            gm2.do(f"Confirm {grn_b['grn_number']}", "POST", f"/procurement/goods-receipts/{grn_b['id']}/confirm")
            grn_b = gm2.call("GET", f"/procurement/goods-receipts/{grn_b['id']}")[1]
            gi = {i["product_variant_id"]: i for i in grn_b["items"]}
            ret = pm.do("Purchase return: 3 more fans found with motor noise", "POST", "/purchase-returns", {
                "supplier_id": S["shyam"], "godown_id": PITH, "goods_receipt_id": grn_b["id"], "purchase_order_id": po_b["id"],
                "return_date": d(17), "reason": "Motor noise on test run", "debit_note_number": "DN/26-27/014",
                "items": [{"goods_receipt_item_id": gi[V["CR-FAN-1200-BR"]["id"]]["id"],
                           "product_variant_id": V["CR-FAN-1200-BR"]["id"], "quantity": 3, "unit_price": 1650, "gst_rate": 18}]})
            if ret:
                pm.do("Confirm return → stock out, marked sent to supplier", "POST", f"/purchase-returns/{ret['id']}/confirm")
                pm.do("Supplier accepted the return", "POST", f"/purchase-returns/{ret['id']}/status", {"status": "accepted"})
                pm.do("Credit note received", "POST", f"/purchase-returns/{ret['id']}/status",
                      {"status": "credited", "note": "Credit note SSE/CN/221"})
            inv_b = acct.do("Shyam invoice bills all 80 brown fans at ₹1,720", "POST", "/supplier-invoices", {
                "supplier_id": S["shyam"], "invoice_number": "SSE/26-27/1187", "invoice_date": d(16), "due_date": ahead(29),
                "purchase_order_id": po_b["id"], "goods_receipt_id": grn_b["id"], "freight_amount": 2500,
                "items": [{"purchase_order_item_id": fb["id"], "goods_receipt_item_id": gi[fb["product_variant_id"]]["id"],
                           "product_variant_id": fb["product_variant_id"], "quantity": 80, "uom_id": NOS, "unit_price": 1720, "gst_rate": 18},
                          {"purchase_order_item_id": fw["id"], "goods_receipt_item_id": gi[fw["product_variant_id"]]["id"],
                           "product_variant_id": fw["product_variant_id"], "quantity": 25, "uom_id": NOS, "unit_price": 1720, "gst_rate": 18},
                          {"purchase_order_item_id": db_["id"], "goods_receipt_item_id": gi[db_["product_variant_id"]]["id"],
                           "product_variant_id": db_["product_variant_id"], "quantity": 4, "uom_id": NOS, "unit_price": 1150, "gst_rate": 18}]})
            if inv_b:
                acct.do("3-way match → variance (billed 80, accepted 74)", "POST", f"/supplier-invoices/{inv_b['id']}/match")
                acct.do("Send for review", "POST", f"/supplier-invoices/{inv_b['id']}/status", {"status": "under_review"})
                acct.refused("Cannot approve an invoice with an unresolved variance", "POST",
                             f"/supplier-invoices/{inv_b['id']}/approve", codes=(409, 422))
                acct.do("Dispute invoice", "POST", f"/supplier-invoices/{inv_b['id']}/dispute",
                        {"reason": "Billed for 80 brown fans; 6 rejected at receipt and 3 returned. Issue credit note."})

    # ================================================== scenario C
    section("7. Scenario C: other purchase-order states")
    po_c = pm.do("PO to Bright Lights for LED bulbs (expected 10 days ago, nothing received → overdue)", "POST",
                 "/procurement/purchase-orders", {
                     "supplier_id": S["bright"], "delivery_godown_id": MAIN, "po_date": d(20), "expected_delivery_date": d(10),
                     "payment_terms": "Advance", "items": [line("PH-LED-9W", 500), line("PH-LED-12W", 300)]})
    if po_c:
        run_po(pm, po_c)
    po_d = pm.do("PO to Malwa for 4 sq mm wire + earthing (partly received, then short-closed)", "POST",
                 "/procurement/purchase-orders", {
                     "supplier_id": S["malwa"], "delivery_godown_id": MAIN, "po_date": d(22), "expected_delivery_date": d(14),
                     "items": [line("PC-FR-4.0-RD", 20), line("ACC-EARTH-8SWG", 50)]})
    if po_d and (po_d := run_po(pm, po_d)):
        it = po_items(po_d)
        g = supv.do("Store Supervisor receives 4 sq mm ×10 and 52 kg earthing (2 kg excess, within 5%)", "POST",
                    "/procurement/goods-receipts", {
                        "supplier_id": S["malwa"], "purchase_order_id": po_d["id"], "godown_id": MAIN, "grn_date": d(12),
                        "items": [{"purchase_order_item_id": it[V["PC-FR-4.0-RD"]["id"]]["id"], "product_variant_id": V["PC-FR-4.0-RD"]["id"],
                                   "received_quantity": 10, "accepted_quantity": 10, "uom_id": NOS, "unit_price": 3400, "issue_type": "short", "remarks": "Supplier sent 10 of 20; balance not coming"},
                                  {"purchase_order_item_id": it[V["ACC-EARTH-8SWG"]["id"]]["id"], "product_variant_id": V["ACC-EARTH-8SWG"]["id"],
                                   "received_quantity": 52, "accepted_quantity": 52, "uom_id": KG, "unit_price": 860, "issue_type": "excess", "remarks": "Coil weighed 52 kg; 2 kg over, accepted within tolerance"}]})
        if g:
            supv.do("Store Supervisor confirms the GRN (custom-role permission)", "POST", f"/procurement/goods-receipts/{g['id']}/confirm")
        pm.do("Short-close the PO (4 sq mm no longer needed)", "POST", f"/procurement/purchase-orders/{po_d['id']}/close",
              {"reason": "Balance 10 coils not required — project cancelled"})
    po_e = pm.do("PO to Gujarat for switches (cancelled)", "POST", "/procurement/purchase-orders", {
        "supplier_id": S["gujarat"], "delivery_godown_id": MAIN, "po_date": d(9), "expected_delivery_date": ahead(5),
        "items": [line("AN-ROMA-SW6A", 600, 27), line("AN-ROMA-SK16A", 200, 92)]})
    if po_e:
        pm.do("Submit", "POST", f"/procurement/purchase-orders/{po_e['id']}/submit")
        pm.do("Cancel PO", "POST", f"/procurement/purchase-orders/{po_e['id']}/cancel",
              {"reason": "Supplier cannot deliver before Diwali"})
    po_f = pm.do("PO to Rajwada for conduit pipe (submitted, awaiting approval)", "POST", "/procurement/purchase-orders", {
        "supplier_id": S["rajwada"], "delivery_godown_id": RETAIL, "po_date": d(2), "expected_delivery_date": ahead(3),
        "items": [line("ACC-CONDUIT-20", 1000, 17.5)]})
    if po_f:
        pm.do("Submit for approval", "POST", f"/procurement/purchase-orders/{po_f['id']}/submit")
    pm.do("PO to Bright Lights for battens (left as draft)", "POST", "/procurement/purchase-orders", {
        "supplier_id": S["bright"], "delivery_godown_id": MAIN, "items": [line("PH-BAT-20W", 120)],
        "notes": "Waiting for revised price list"})
    po_g = pm.do("PO to Bright Lights for Duracell AA (batch-tracked)", "POST", "/procurement/purchase-orders", {
        "supplier_id": S["bright"], "delivery_godown_id": MAIN, "po_date": d(28), "expected_delivery_date": d(26), "items": [line("DU-AA-4", 200)]})
    if po_g and (po_g := run_po(pm, po_g)):
        pi_ = po_items(po_g)[V["DU-AA-4"]["id"]]
        # Two deliveries, one batch each.
        for batch, made, expires, qty, days, note in (
                ("DUR-2409A", "2024-09-01", ahead(20), 60, 26, "old stock — expires in 20 days"),
                ("DUR-2607K", "2026-07-01", "2028-06-30", 140, 24, "fresh stock — expires 2028")):
            g = gm.do(f"GRN batch {batch}: {qty} packs ({note})", "POST", "/procurement/goods-receipts", {
                "supplier_id": S["bright"], "purchase_order_id": po_g["id"], "godown_id": MAIN, "grn_date": d(days),
                "items": [{"purchase_order_item_id": pi_["id"], "product_variant_id": V["DU-AA-4"]["id"], "batch_number": batch,
                           "manufactured_on": made, "expires_on": expires, "mrp": 220, "received_quantity": qty,
                           "accepted_quantity": qty, "uom_id": PACK, "unit_price": 150}]})
            if g:
                gm.do(f"Confirm batch {batch} GRN", "POST", f"/procurement/goods-receipts/{g['id']}/confirm")
    # A GRN entered against the wrong PO, then cancelled; and a GRN reversed after posting.
    if po_c:
        pc = pm.call("GET", f"/procurement/purchase-orders/{po_c['id']}")[1]
        pci = po_items(pc)
        g = staff.do("Draft GRN for LED bulbs (wrong vehicle details)", "POST", "/procurement/goods-receipts", {
            "supplier_id": S["bright"], "purchase_order_id": pc["id"], "godown_id": MAIN, "grn_date": d(1),
            "items": [{"purchase_order_item_id": pci[V["PH-LED-9W"]["id"]]["id"], "product_variant_id": V["PH-LED-9W"]["id"],
                       "received_quantity": 500, "accepted_quantity": 500, "uom_id": NOS}]})
        if g:
            gm.do("Cancel the draft GRN", "POST", f"/procurement/goods-receipts/{g['id']}/cancel",
                  {"reason": "Truck was for another firm — nothing unloaded"})
    rev_po = pm.do("PO to Gujarat for 16A sockets", "POST", "/procurement/purchase-orders", {
        "supplier_id": S["gujarat"], "delivery_godown_id": MAIN, "po_date": d(15), "expected_delivery_date": d(11), "items": [line("AN-ROMA-SK16A", 100, 95)]})
    if rev_po and (rev_po := run_po(pm, rev_po)):
        it = po_items(rev_po)[V["AN-ROMA-SK16A"]["id"]]
        g = gm.do("GRN 100 sockets", "POST", "/procurement/goods-receipts", {
            "supplier_id": S["gujarat"], "purchase_order_id": rev_po["id"], "godown_id": MAIN, "grn_date": d(11),
            "items": [{"purchase_order_item_id": it["id"], "product_variant_id": V["AN-ROMA-SK16A"]["id"],
                       "received_quantity": 100, "accepted_quantity": 100, "uom_id": NOS, "unit_price": 95}]})
        if g and gm.do("Confirm", "POST", f"/procurement/goods-receipts/{g['id']}/confirm") is not None:
            g = gm.call("GET", f"/procurement/goods-receipts/{g['id']}")[1]
            gm.refused("Godown Manager cannot reverse a posted GRN", "POST", f"/procurement/goods-receipts/{g['id']}/reverse",
                       {"reason": "x"})
            owner.do("Owner reverses 20 sockets (counted 80 on recount)", "POST", f"/procurement/goods-receipts/{g['id']}/reverse",
                     {"reason": "Physical recount found 80, not 100", "lines": [{"goods_receipt_item_id": g["items"][0]["id"], "quantity": 20}]})

    # ================================================== RFQ states
    section("8. RFQs in other states, and an AI-read quotation")
    pm.do("RFQ left as draft (switch sockets for a project)", "POST", "/procurement/rfqs", {
        "subject": "Sockets for Vijay Nagar apartment project", "delivery_godown_id": MAIN,
        "items": [{"product_variant_id": V["AN-ROMA-SK16A"]["id"], "quantity": 400, "uom_id": NOS}]})
    r = pm.do("RFQ for MCBs (then cancelled)", "POST", "/procurement/rfqs", {
        "subject": "MCB bulk order", "items": [{"product_variant_id": V["HV-MCB-16A-SP"]["id"], "quantity": 480, "uom_id": NOS}]})
    if r:
        pm.do("Cancel RFQ", "POST", f"/procurement/rfqs/{r['id']}/cancel", {"reason": "Got a scheme from Havells directly"})
    rfq_ai = pm.do("RFQ for switches and DBs, sent to Gujarat (awaiting quote)", "POST", "/procurement/rfqs", {
        "subject": "Switches & DBs – Diwali stock", "delivery_godown_id": MAIN, "expected_delivery_date": ahead(10),
        "items": [{"product_variant_id": V[s]["id"], "quantity": q, "uom_id": NOS}
                  for s, q in (("AN-ROMA-SW6A", 800), ("LG-DB-8W", 15))]})
    if rfq_ai:
        pm.do("Send RFQ to Gujarat Switchgear", "POST", f"/procurement/rfqs/{rfq_ai['id']}/send", {"supplier_ids": [S["gujarat"]]})
    owner.do("Rebuild product search index for AI matching", "POST", "/ai/embeddings/rebuild")
    csv = "\n".join([
        "Gujarat Switchgear Traders", "12 Relief Road, Ahmedabad 380001", "QUOTATION", "",
        "Quotation No: GST/2026/Q-305", f"Date: {TODAY.strftime('%d/%m/%Y')}", "Payment Terms: 30 days", "",
        "Item Code,Description,HSN,Qty,UOM,Rate,GST %,Amount",
        "ROMA-30001,Anchor Roma 6A 1-way switch,8536,800,Nos,27.50,18,22000.00",
        "LEG-DB8,Legrand DB 8 way SPN single door,8537,15,Nos,1135.00,18,17025.00",
        "Total,,,,,,,39025.00"]).encode() + b"\n"
    st, up = upload(pm, "gujarat-quotation-GST-Q-305.csv", csv, S["gujarat"])
    record(pm.label, "Upload supplier quotation (CSV) for AI reading", st == 201, up)
    if st == 201:
        doc_id = up["document"]["id"]
        deadline = time.monotonic() + 240
        while True:
            job = pm.call("GET", f"/ai/documents/{doc_id}/job")[1] or {}
            if job.get("processing_status") not in ("queued", "processing") or time.monotonic() > deadline:
                break
            time.sleep(2)
        record(pm.label, "AI reads it and sends it to review", job.get("processing_status") == "review_required", job)
        ext = pm.call("GET", f"/ai/documents/{doc_id}/extraction")[1] or {}
        for ln in ext.get("lines", []):
            if not ln.get("matched_variant_id") or ln.get("final_decision") is None:
                cand = (ln.get("candidates") or [{}])[0].get("product_variant_id")
                if cand:
                    pm.do(f"Confirm AI match for '{(ln.get('raw_description') or '')[:40]}'", "POST",
                          f"/ai/lines/{ln['id']}/match", {"product_variant_id": cand, "save_alias": True})
        appr = pm.do("Approve extraction into a quotation on the RFQ", "POST", f"/ai/documents/{doc_id}/approve",
                     {"rfq_id": rfq_ai["id"] if rfq_ai else None})
        if appr:
            q = pm.call("GET", f"/procurement/quotations/{appr['promoted_to_id']}")[1] or {}
            record(pm.label, f"Quotation total recomputed: ₹{float(q.get('total_amount') or 0):,.2f} (page said 39,025 before GST)",
                   abs(float(q.get("subtotal") or 0) - 39025) < 1, q)
    st, up2 = upload(acct, "malwa-pending-quote.csv", "\n".join([
        "Malwa Cable Distributors", "QUOTATION", "Quotation No: MCD/Q/2026/0977", "",
        "Description,Qty,UOM,Rate", "Polycab FRLS 1.5 sq mm red 90m,120,Nos,1340", "Polycab 6 sq mm green 90m,20,Nos,5150"]).encode() + b"\n",
        S["malwa"])
    record(acct.label, "Upload a second quotation and leave it waiting in the AI review queue", st == 201, up2)
    staff.refused("Staff cannot approve an AI extraction", "POST",
                  f"/ai/documents/{(up2 or {}).get('document', {}).get('id', uuid.uuid4())}/approve", {})

    # ================================================== inventory
    section("9. Inventory: transfers, sales issues, write-offs, corrections")
    gm.do("Transfer Main → Retail: 40 switches, 30 sockets, 60 bulbs, 10 wire coils", "POST", "/inventory/transfers", {
        "from_godown_id": MAIN, "to_godown_id": RETAIL, "transfer_date": d(8), "vehicle_number": "MP09 LT 1102",
        "remarks": "Counter replenishment",
        "items": [{"product_variant_id": V[s]["id"], "quantity": q, "uom_id": NOS}
                  for s, q in (("AN-ROMA-SW6A", 40), ("AN-ROMA-SK16A", 30), ("PH-LED-9W", 60), ("PC-FR-1.5-RD", 10))]})
    supv.do("Store Supervisor transfers 20 MCBs Main → Pithampur", "POST", "/inventory/transfers", {
        "from_godown_id": MAIN, "to_godown_id": PITH, "transfer_date": d(6),
        "items": [{"product_variant_id": V["HV-MCB-16A-SP"]["id"], "quantity": 20, "uom_id": NOS}]})
    gm2.refused("Pithampur-only manager cannot move stock out of Main", "POST", "/inventory/transfers", {
        "from_godown_id": MAIN, "to_godown_id": PITH,
        "items": [{"product_variant_id": V["HV-MCB-16A-SP"]["id"], "quantity": 5, "uom_id": NOS}]})
    gm.refused("Cannot transfer a godown to itself", "POST", "/inventory/transfers", {
        "from_godown_id": MAIN, "to_godown_id": MAIN, "items": [{"product_variant_id": V["LG-DB-8W"]["id"], "quantity": 1, "uom_id": NOS}]})
    for sku, qty, days, gd in (("PC-FR-1.5-RD", 150, 7, MAIN), ("PC-FR-2.5-RD", 82, 6, MAIN), ("PH-LED-12W", 128, 5, MAIN),
                               ("HV-MCB-32A-DP", 31, 5, MAIN), ("CR-FAN-1200-WH", 16, 4, MAIN), ("LG-DB-8W", 12, 3, MAIN),
                               ("AN-ROMA-SW6A", 25, 2, RETAIL), ("PH-LED-9W", 45, 2, RETAIL), ("PC-FR-1.5-RD", 32, 3, PITH),
                               ("CR-FAN-1200-BR", 60, 2, PITH)):
        who = gm2 if gd == PITH else gm
        who.do(f"Sales issue {qty} × {sku}", "POST", "/inventory/transactions", {
            "txn_type": "SALES_ISSUE", "product_variant_id": V[sku]["id"], "godown_id": gd, "quantity": qty,
            "uom_id": V[sku]["uom"], "direction": "decrease", "txn_date": d(days), "reference": f"Tally bill batch {days}"})
    dmg = gm.do("Damage write-off: 4 battens cracked", "POST", "/inventory/transactions", {
        "txn_type": "DAMAGE", "product_variant_id": V["PH-BAT-20W"]["id"], "godown_id": MAIN, "quantity": 4,
        "uom_id": NOS, "direction": "decrease", "txn_date": d(5), "reason_code": "breakage", "remarks": "Fell from rack B3"})
    dmg2 = gm.do("Damage write-off: 2 MCBs (later found fine)", "POST", "/inventory/transactions", {
        "txn_type": "DAMAGE", "product_variant_id": V["HV-MCB-32A-DP"]["id"], "godown_id": MAIN, "quantity": 2,
        "uom_id": NOS, "direction": "decrease", "txn_date": d(4), "remarks": "Tripping on test bench"})
    if dmg2:
        gm.do("Reverse that write-off", "POST", f"/inventory/transactions/{dmg2['id']}/reverse", {"reason": "Tested OK, back to stock"})
    gm.do("Stock correction after cycle count: conduit −35 m", "POST", "/inventory/transactions", {
        "txn_type": "STOCK_CORRECTION", "product_variant_id": V["ACC-CONDUIT-20"]["id"], "godown_id": MAIN, "quantity": 35,
        "uom_id": MTR, "direction": "decrease", "txn_date": d(3), "reason_code": "cycle_count", "remarks": "Cycle count Sept"})
    gm.refused("Cannot write off more than is in stock", "POST", "/inventory/transactions", {
        "txn_type": "DAMAGE", "product_variant_id": V["LG-DB-8W"]["id"], "godown_id": MAIN, "quantity": 999, "uom_id": NOS, "remarks": "Test: more than on hand",
        "direction": "decrease", "txn_date": d(1)})
    staff.refused("Staff cannot adjust stock", "POST", "/inventory/transactions", {
        "txn_type": "DAMAGE", "product_variant_id": V["LG-DB-8W"]["id"], "godown_id": MAIN, "quantity": 1, "uom_id": NOS,
        "direction": "decrease"})
    batches = [b for b in items(gm.call("GET", f"/inventory/batches?product_variant_id={V['DU-AA-4']['id']}")[1])
               if b.get("batch_number") == "DUR-2409A"]
    if not batches:
        record(gm.label, "Find batch DUR-2409A for the expiry write-off", False, "batch not found")
    else:
        gm.do("Write off 8 packs of the near-expiry Duracell batch (leaking)", "POST", "/inventory/transactions", {
            "txn_type": "EXPIRY_WRITE_OFF", "product_variant_id": V["DU-AA-4"]["id"], "godown_id": MAIN,
            "batch_id": batches[0]["id"], "quantity": 8, "uom_id": PACK, "direction": "decrease", "txn_date": d(1),
            "remarks": "Leaking cells in batch DUR-2409A"})
    vb = gm.call("GET", "/inventory/verify-balances")[1] or {}
    record(gm.label, "Stock ledger and balances agree", not vb.get("mismatches") and vb.get("ok", True) is not False, vb)

    # ================================================== alerts, variances
    section("10. Alerts and variances")
    owner.do("Evaluate alert rules", "POST", "/alerts/evaluate")
    alerts = items(gm.call("GET", "/alerts?limit=200")[1])
    record(gm.label, f"Alerts raised: {len(alerts)} ({', '.join(sorted({a.get('alert_type') or a.get('rule_code') or '?' for a in alerts}))})",
           len(alerts) > 0, alerts[:3])
    low = [a for a in alerts if "low" in json.dumps(a).lower()]
    if low:
        gm.do("Acknowledge a low-stock alert", "POST", f"/alerts/{low[0]['id']}/status", {"status": "acknowledged"})
    if len(low) > 1:
        gm.do("Resolve another (reorder placed)", "POST", f"/alerts/{low[1]['id']}/status", {"status": "resolved"})
    viewer.do("Viewer marks all alerts read", "POST", "/alerts/read-all")
    vs = items(pm.call("GET", "/variances?limit=100")[1])
    record(pm.label, f"Variances recorded: {len(vs)}", len(vs) > 0, vs[:2])
    open_v = [v for v in vs if v.get("status") in ("open", "pending", None)]
    if open_v:
        pm.do("Accept one variance with a note", "POST", f"/variances/{open_v[0]['id']}/resolve",
              {"status": "accepted", "note": "Copper price rise — accepted for this order only"})

    # ================================================== supplier portal
    section("11. Supplier portal")
    grant = pm.do("Give Malwa's sales head a supplier-portal login", "POST", f"/catalog/suppliers/{S['malwa']}/portal-access",
                  {"email": "mahesh@malwacables.test", "full_name": "Mahesh Gupta"})
    link = None
    if grant:
        rows = platform_sql("select body_preview from outbound_messages where to_address='mahesh@malwacables.test' "
                            "order by queued_at desc limit 1")
        m = re.search(r"set-password\?token=([A-Za-z0-9_\-]+)", rows[0]["body_preview"] if rows else "")
        link = m and m.group(1)
    if link:
        st, _ = _request("POST", "/supplier-portal/set-password", None, {"token": link, "password": PASSWORD})
        record("Supplier · Mahesh Gupta", "Set password from the emailed link", st in (200, 201, 204), st)
        st, sp = _request("POST", "/supplier-portal/login", None, {"email": "mahesh@malwacables.test", "password": PASSWORD})
        record("Supplier · Mahesh Gupta", "Sign in to the supplier portal", st == 200, sp)
        if st == 200:
            st, me = _request("GET", "/supplier-portal/me", sp["access_token"])
            record("Supplier · Mahesh Gupta", "Sees their own portal page", st == 200, me)
            st, _ = _request("GET", "/catalog/products", sp["access_token"])
            record("Supplier · Mahesh Gupta", "Supplier token refused on staff APIs", st == 401, st, expected=f"refused ({st})")
    else:
        record(pm.label, "Find the portal set-password link", False, "no email found")

    # ================================================== other tenants
    section("12. Second company, company switching, suspension, impersonation")
    up_ = {u["code"]: u["id"] for u in patel.call("GET", "/catalog/uoms-available")[1]}
    pg = next(g for g in items(patel.call("GET", "/catalog/godowns?limit=10")[1]) if g["is_default"])["id"]
    pvars = []
    for name, sku, buy, hsn in (("Godrej Navtal Padlock 7 Lever", "GD-NAVTAL-7L", 640, "8301"),
                                ("Stanley Claw Hammer 450 g", "ST-HAM-450", 385, "8205"),
                                ("Fevicol SH 1 kg", "PD-FEVI-SH1", 290, "3506")):
        p = patel.do(f"Product '{name}'", "POST", "/catalog/products", {"name": name, "base_uom_id": up_["Nos"], "hsn_code": hsn, "gst_rate": 18})
        if p:
            v = patel.do(f"  Variant {sku}", "POST", "/catalog/variants", {"product_id": p["id"], "sku": sku, "uom_id": up_["Nos"],
                                                                           "purchase_price": buy, "sale_price": round(buy * 1.25), "mrp": round(buy * 1.45),
                                                                           "reorder_point": 10, "reorder_qty": 30})
            if v:
                pvars.append(v)
                patel.do(f"  Opening stock 25 × {sku}", "POST", "/inventory/transactions", {
                    "txn_type": "OPENING_STOCK", "product_variant_id": v["id"], "godown_id": pg, "quantity": 25,
                    "uom_id": up_["Nos"], "direction": "increase", "txn_date": d(30)})
    ps = patel.do("Supplier 'Kalupur Hardware Wholesale'", "POST", "/catalog/suppliers", {
        "name": "Kalupur Hardware Wholesale", "supplier_type": "Distributor", "gstin": gstin("24", "AAKFK3321B"),
        "city": "Ahmedabad", "state_code": "24", "state_name": "Gujarat"})
    if ps and pvars:
        pp = patel.do("PO for padlocks", "POST", "/procurement/purchase-orders", {
            "supplier_id": ps["id"], "delivery_godown_id": pg, "expected_delivery_date": ahead(7),
            "items": [{"product_variant_id": pvars[0]["id"], "quantity": 50, "uom_id": up_["Nos"], "unit_price": 630, "gst_rate": 18}]})
        if pp:
            for s_ in ("submit", "approve", "send"):
                patel.do(f"PO {s_}", "POST", f"/procurement/purchase-orders/{pp['id']}/{s_}")
    if pvars:
        owner.refused("Ganesh owner cannot open a Patel Hardware product (tenant isolation)", "GET",
                      f"/catalog/variants/{pvars[0]['id']}", codes=(403, 404))
    admin.do("Link Rajesh Agarwal to Patel Hardware Mart as a member", "POST", f"/platform/companies/{patel_id}/members",
             {"email": owner.email})
    mine = owner.call("GET", "/auth/me/companies")[1] or []
    record(owner.label, f"Rajesh now belongs to {len(items(mine))} companies", len(items(mine)) == 2, mine)
    st, sw = owner.call("POST", "/auth/switch-company", {"company_id": patel_id})
    if st == 200:
        tmp = Actor(owner.label, owner.email)
        tmp.token = sw["access_token"]
        seen = items(tmp.call("GET", "/catalog/variants?limit=50")[1])
        record(owner.label, f"After switching, sees Patel's catalogue ({len(seen)} items, none of Ganesh's)",
               {x["sku"] for x in seen} == {v["sku"] for v in pvars}, [x["sku"] for x in seen])
    else:
        record(owner.label, "Switch to Patel Hardware Mart", False, {"status": st, "body": sw})
    owner.refused("A company Owner cannot use the platform console", "GET", "/platform/companies", codes=(401, 403))
    admin.do("Suspend Old Town Traders (payment overdue)", "POST", f"/platform/companies/{oldtown_id}/suspend",
             {"reason": "Subscription payment overdue by 45 days"})
    st, _ = _request("POST", "/auth/login", None, {"email": oldtown.email, "password": PASSWORD})
    record(oldtown.label, "Owner of a suspended company cannot sign in", st in (401, 403, 423), {"status": st},
           expected=f"refused ({st})")
    if acct.user_id:
        imp = admin.do("Impersonate Neha Jain (support ticket)", "POST", "/platform/impersonate",
                       {"user_id": acct.user_id, "reason": "Ticket #1042: invoice SSE/26-27/1187 shows wrong status"})
        if imp:
            as_neha = Actor("QA Admin as Neha", acct.email)
            as_neha.token = imp["access_token"]
            as_neha.do("Read the disputed invoice while impersonating", "GET", "/supplier-invoices?limit=5")
            as_neha.refused("Impersonation token cannot reach the platform console", "GET", "/platform/companies", codes=(401, 403))
            as_neha.do("Stop impersonating", "POST", "/platform/impersonate/stop")

    # ================================================== read-only roles
    section("13. Viewer, reports, dashboard, assistant, audit")
    viewer.refused("Viewer cannot create a supplier", "POST", "/catalog/suppliers", {"name": "X", "supplier_type": "Distributor"})
    viewer.refused("Viewer cannot create a PO", "POST", "/procurement/purchase-orders", {
        "supplier_id": S["malwa"], "delivery_godown_id": MAIN, "items": [line("LG-DB-8W", 1)]})
    staff.refused("Staff cannot create a PO", "POST", "/procurement/purchase-orders", {
        "supplier_id": S["malwa"], "delivery_godown_id": MAIN, "items": [line("LG-DB-8W", 1)]})
    staff.refused("Staff cannot open Users", "GET", "/users")
    reps = viewer.call("GET", "/reports")[1] or []
    ok_reps = [r["key"] for r in reps if viewer.call("GET", f"/reports/{r['key']}")[0] == 200]
    record(viewer.label, f"Runs all {len(reps)} reports ({len(ok_reps)} ok)", reps and len(ok_reps) == len(reps), ok_reps)
    dash = viewer.do("Dashboard summary", "GET", "/dashboard/summary")
    for who, q in ((viewer, "What is low on stock?"), (owner, "Which purchase orders are still pending?"),
                   (acct, "Which supplier invoices are unpaid?")):
        a = who.do(f"Assistant: “{q}”", "POST", "/ai/assistant", {"question": q})
    aud = owner.call("GET", "/audit-logs?limit=500")[1]
    record(owner.label, f"Audit trail has {len(items(aud))} entries", len(items(aud)) > 50, len(items(aud)))
    owner.do(f"Lock inventory through {d(45)} (period close)", "PATCH", "/company/settings", {"inventory_locked_through": d(45)})
    gm.refused("Backdated adjustment into the closed period is refused", "POST", "/inventory/transactions", {
        "txn_type": "STOCK_CORRECTION", "product_variant_id": V["LG-DB-8W"]["id"], "godown_id": MAIN, "quantity": 1,
        "uom_id": NOS, "direction": "increase", "txn_date": d(50)})

    # ================================================== summary
    passed = sum(r["ok"] for r in RESULTS)
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"\n{passed} passed, {len(failed)} failed")
    for r in failed:
        print(f"  - [{r['section']}] {r['actor']}: {r['action']}")
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump({"run_at": datetime.now(IST).isoformat(), "results": RESULTS, "dashboard": dash}, f, indent=1, default=str)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
