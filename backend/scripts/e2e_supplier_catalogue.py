"""
E2E HTTP suite — supplier & catalogue detail panels.

Runs against a live backend (default http://127.0.0.1:8000) seeded with the
demo tenants. Creates its own users/godowns/products/suppliers with a
per-run suffix, so it can be re-run on the same database.

    python -m scripts.e2e_supplier_catalogue [base_url]

Exit code 0 only if every check passes.
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import date, timedelta

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
SFX = uuid.uuid4().hex[:6].upper()
TODAY = date.today()

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


async def make_users(acme_godown_a: str) -> dict[str, str]:
    """Role users straight into the DB (the invite flow needs email)."""
    from sqlalchemy import text

    from app.core.db import platform_engine
    from app.core.security import hash_password

    pw = hash_password("Test@12345")
    out = {}
    async with platform_engine.begin() as conn:
        cid = (await conn.execute(text("SELECT id FROM companies WHERE name = 'Acme Trading Co' ORDER BY id LIMIT 1"))).scalar_one()
        for role, scoped in (("staff", False), ("godown_manager", True), ("purchase_manager", False), ("viewer", False)):
            rid = (await conn.execute(text("SELECT id FROM roles WHERE company_id IS NULL AND code = :r"), {"r": role})).scalar_one()
            email = f"{role}.{SFX.lower()}@acme-demo.test"
            uid = (
                await conn.execute(
                    text(
                        "INSERT INTO users (company_id, email, full_name, role_id, is_platform_admin, has_all_godowns, "
                        "status, password_hash, password_changed_at) VALUES (:c, :e, :n, :r, false, :all, 'active', :pw, now()) "
                        "RETURNING id"
                    ),
                    {"c": cid, "e": email, "n": f"{role} {SFX}", "r": rid, "all": not scoped, "pw": pw},
                )
            ).scalar_one()
            if scoped:
                await conn.execute(
                    text("INSERT INTO user_godown_access (user_id, godown_id) VALUES (:u, :g)"),
                    {"u": uid, "g": acme_godown_a},
                )
            out[role] = email
    return out


def main() -> int:
    owner = login("owner@acme-demo.test", "Demo@12345")
    beta = login("owner@beta-demo.test", "Demo@12345")

    # ------------------------------------------------------------ fixtures
    uoms = {u["code"]: u["id"] for u in ok(*call("GET", "/catalog/uoms-available", owner))}
    gA = ok(*call("POST", "/catalog/godowns", owner, {"name": f"GA {SFX}", "code": f"GA{SFX}", "city": "Pune", "state_code": "27"}), 201)["id"]
    gB = ok(*call("POST", "/catalog/godowns", owner, {"name": f"GB {SFX}", "code": f"GB{SFX}", "city": "Nashik", "state_code": "27"}), 201)["id"]
    beta_godown = ok(*call("POST", "/catalog/godowns", beta, {"name": f"BG {SFX}", "code": f"BG{SFX}", "city": "Surat", "state_code": "24"}), 201)["id"]
    beta_uom = ok(*call("POST", "/catalog/uoms", beta, {"code": f"BU{SFX}", "name": "Beta unit", "uom_type": "count", "decimal_places": 0}), 201)["id"]

    def product(name: str) -> str:
        p = ok(*call("POST", "/catalog/products", owner, {"name": f"{name} {SFX}", "base_uom_id": uoms["Nos"], "hsn_code": "8471", "gst_rate": 18}), 201)
        v = ok(*call("POST", "/catalog/variants", owner, {"product_id": p["id"], "sku": f"{name[:3].upper()}-{SFX}", "uom_id": uoms["Nos"], "purchase_price": 100, "sale_price": 150, "mrp": 200}), 201)
        return v["id"]

    v1, v2, v3 = product("Router"), product("Switch"), product("Cable")
    beta_p = ok(*call("POST", "/catalog/products", beta, {"name": f"Beta item {SFX}", "base_uom_id": uoms["Nos"]}), 201)
    beta_v = ok(*call("POST", "/catalog/variants", beta, {"product_id": beta_p["id"], "sku": f"BV-{SFX}", "uom_id": uoms["Nos"]}), 201)["id"]

    def supplier(name: str) -> str:
        return ok(*call("POST", "/catalog/suppliers", owner, {
            "name": f"{name} {SFX}", "supplier_type": "Distributor", "gst_treatment": "unregistered",
            "state_code": "27", "state_name": "Maharashtra", "city": "Mumbai", "email": f"{name.lower()}{SFX.lower()}@sup.test"}), 201)["id"]

    s1, s2, s3 = supplier("Alpha"), supplier("Bravo"), supplier("Charlie")

    users = asyncio.run(make_users(gA))
    staff = login(users["staff"], "Test@12345")
    gm = login(users["godown_manager"], "Test@12345")
    pm = login(users["purchase_manager"], "Test@12345")
    viewer = login(users["viewer"], "Test@12345")

    # ============================================================ contacts
    print("\n[contacts]")
    st, b = call("GET", f"/catalog/suppliers/{s1}/contacts", owner)
    check("C01 new supplier has no contacts", st == 200 and b == [], b)
    st, c1 = call("POST", f"/catalog/suppliers/{s1}/contacts", owner, {"name": " Ravi Kumar ", "designation": "Sales", "phone": "9820000001", "email": "ravi@alpha.test"})
    check("C02 first contact created and auto-primary", st == 201 and c1["is_primary"] is True and c1["name"] == "Ravi Kumar", c1)
    st, c2 = call("POST", f"/catalog/suppliers/{s1}/contacts", pm, {"name": "Priya", "email": "priya@alpha.test", "is_primary": True})
    check("C03 purchase manager adds a second, primary contact", st == 201 and c2["is_primary"], c2)
    st, b = call("GET", f"/catalog/suppliers/{s1}/contacts", viewer)
    prim = [x for x in b if x["is_primary"]] if st == 200 else []
    check("C04 only one primary afterwards, listed first", st == 200 and len(b) == 2 and len(prim) == 1 and b[0]["id"] == c2["id"], b)
    st, b = call("POST", f"/catalog/suppliers/{s1}/contacts", owner, {"name": "Dup", "email": "RAVI@alpha.test"})
    check("C05 duplicate email (case-insensitive) → 409 on email", st == 409 and b.get("errors", [{}])[0].get("field") == "email", b)
    st, b = call("POST", f"/catalog/suppliers/{s1}/contacts", owner, {"name": "Bad", "email": "not-an-email"})
    check("C06 malformed email → 400", st == 400, b)
    st, b = call("POST", f"/catalog/suppliers/{s1}/contacts", owner, {"name": ""})
    check("C07 empty name → 400", st == 400, b)
    st, b = call("PATCH", f"/catalog/supplier-contacts/{c1['id']}", owner, {"designation": "Key accounts"})
    check("C08 PATCH one field leaves the rest", st == 200 and b["designation"] == "Key accounts" and b["email"] == "ravi@alpha.test", b)
    st, b = call("PATCH", f"/catalog/supplier-contacts/{c1['id']}", owner, {"name": None})
    check("C09 PATCH name to null → 422", st == 422, b)
    st, b = call("PATCH", f"/catalog/supplier-contacts/{c1['id']}", owner, {"is_primary": True})
    st2, lst = call("GET", f"/catalog/suppliers/{s1}/contacts", owner)
    check("C10 making C1 primary clears C2", st == 200 and [x["id"] for x in lst if x["is_primary"]] == [c1["id"]], lst)
    st, b = call("PATCH", f"/catalog/supplier-contacts/{c2['id']}", owner, {"email": "ravi@alpha.test"})
    check("C11 PATCH into a clashing email → 409", st == 409, b)
    st, b = call("POST", f"/catalog/suppliers/{s1}/contacts", staff, {"name": "Nope"})
    check("C12 staff cannot add contacts → 403", st == 403, b)
    st, b = call("PATCH", f"/catalog/supplier-contacts/{c1['id']}", viewer, {"name": "X"})
    check("C13 viewer cannot edit contacts → 403", st == 403, b)
    st, b = call("GET", f"/catalog/suppliers/{s1}/contacts", beta)
    check("C14 other tenant cannot list contacts → 404", st == 404, b)
    st, b = call("PATCH", f"/catalog/supplier-contacts/{c1['id']}", beta, {"name": "Hijack"})
    check("C15 other tenant cannot edit a contact → 404", st == 404, b)
    st, b = call("DELETE", f"/catalog/supplier-contacts/{c1['id']}", beta)
    check("C16 other tenant cannot delete a contact → 404", st == 404, b)
    st, b = call("POST", f"/catalog/suppliers/{s1}/contacts", beta, {"name": "Cross"})
    check("C17 other tenant cannot add to our supplier → 404", st == 404, b)
    st, b = call("DELETE", f"/catalog/supplier-contacts/{c2['id']}", owner)
    st2, lst = call("GET", f"/catalog/suppliers/{s1}/contacts", owner)
    check("C18 delete contact → 204 and gone", st == 204 and len(lst) == 1, (st, lst))
    st, b = call("DELETE", f"/catalog/supplier-contacts/{c2['id']}", owner)
    check("C19 deleting twice → 404", st == 404, b)
    st, b = call("GET", f"/catalog/suppliers/{uuid.uuid4()}/contacts", owner)
    check("C20 unknown supplier → 404", st == 404, b)
    st, b = call("GET", "/catalog/suppliers/not-a-uuid/contacts", owner)
    check("C21 malformed id → 400", st == 400, b)
    call("DELETE", f"/catalog/suppliers/{s3}", owner)
    st, b = call("POST", f"/catalog/suppliers/{s3}/contacts", owner, {"name": "Ghost"})
    check("C22 contact on a deleted supplier → 404", st == 404, b)
    st, trail = call("GET", f"/audit-logs/supplier/{s1}", owner)
    descs = [e.get("description") or "" for e in (trail if isinstance(trail, list) else trail.get("items", []))] if st == 200 else []
    check("C23 contact changes appear on the supplier's audit trail", any("Contact added" in d for d in descs) and any("Contact removed" in d for d in descs), (st, descs[:5]))

    # ============================================================== bank
    print("\n[supplier bank fields + in-use guard]")
    st, b = call("PATCH", f"/catalog/suppliers/{s1}", owner, {"bank_name": "HDFC Bank", "bank_account_no": "50100012345678", "bank_ifsc": "HDFC0001234", "notes": "Pays on time"})
    check("B01 bank details now persist", st == 200 and b["bank_ifsc"] == "HDFC0001234" and b["notes"] == "Pays on time", b)
    st, b = call("PATCH", f"/catalog/suppliers/{s1}", owner, {"bank_ifsc": "hdfc12"})
    check("B02 malformed IFSC → 400", st == 400, b)

    # =============================================================== links
    print("\n[supplier ⇄ SKU links]")
    st, l1 = call("POST", f"/catalog/suppliers/{s1}/products", owner, {"product_variant_id": v1, "supplier_sku": "ALP-R1", "supplier_description": "Router 4 port"})
    check("L01 new link → 201, manual, confirmed", st == 201 and l1["match_source"] == "manual" and l1["confirmed_at"] and l1["sku"] == f"ROU-{SFX}", l1)
    st, l1b = call("POST", f"/catalog/suppliers/{s1}/products", owner, {"product_variant_id": v1, "supplier_sku": "ALP-R1X", "lead_time_days": 4})
    check("L02 same pair again → 200 update, same id", st == 200 and l1b["id"] == l1["id"] and l1b["supplier_sku"] == "ALP-R1X" and l1b["lead_time_days"] == 4, l1b)
    st, b = call("POST", f"/catalog/suppliers/{s1}/products", owner, {"product_variant_id": v2, "supplier_sku": "alp-r1x"})
    check("L03 their code already mapped to another SKU → 409", st == 409 and b["errors"][0]["field"] == "supplier_sku", b)
    st, b = call("POST", f"/catalog/suppliers/{s1}/products", owner, {"product_variant_id": v1, "supplier_sku": "ALP-R1X", "is_preferred": True})
    st, b = call("POST", f"/catalog/suppliers/{s2}/products", owner, {"product_variant_id": v1, "supplier_sku": "BRV-9", "is_preferred": True})
    st2, vs = call("GET", f"/catalog/variants/{v1}/suppliers", owner)
    prefs = [x["supplier_id"] for x in vs if x["is_preferred"]] if st2 == 200 else []
    check("L04 one preferred supplier per SKU (latest wins), preferred first", st == 201 and prefs == [s2] and vs[0]["supplier_id"] == s2, vs)
    st, b = call("POST", f"/catalog/suppliers/{s1}/products", owner, {"product_variant_id": beta_v})
    check("L05 other tenant's variant → 404", st == 404, b)
    st, b = call("POST", f"/catalog/suppliers/{s1}/products", owner, {"product_variant_id": v2, "conversion_to_base": 0})
    check("L06 conversion_to_base 0 → 400", st == 400, b)
    st, b = call("POST", f"/catalog/suppliers/{s1}/products", owner, {"product_variant_id": v2, "match_source": "hacked"})
    check("L07 unknown match_source → 400", st == 400, b)
    st, b = call("POST", f"/catalog/suppliers/{s1}/products", owner, {"product_variant_id": v2, "supplier_uom_id": beta_uom})
    check("L08 other tenant's unit → 422", st == 422, b)
    st, b = call("POST", f"/catalog/suppliers/{s1}/products", staff, {"product_variant_id": v2})
    check("L09 staff cannot link → 403", st == 403, b)
    st, b = call("GET", f"/catalog/suppliers/{s1}/products", beta)
    check("L10 other tenant cannot read links → 404", st == 404, b)
    st, b = call("DELETE", f"/catalog/supplier-products/{l1['id']}", beta)
    check("L11 other tenant cannot delete a link → 404", st == 404, b)
    st, tmp = call("POST", f"/catalog/suppliers/{s1}/products", owner, {"product_variant_id": v3, "supplier_sku": "TMP"})
    st, b = call("DELETE", f"/catalog/supplier-products/{tmp['id']}", owner)
    st2, lst = call("GET", f"/catalog/suppliers/{s1}/products", owner)
    check("L12 delete link → 204 and gone", st == 204 and all(x["product_variant_id"] != v3 for x in lst), lst)
    st, b = call("GET", f"/catalog/variants/{beta_v}/suppliers", owner)
    check("L13 variant suppliers for other tenant's variant → 404", st == 404, b)

    # ======================================================== conversions
    print("\n[UoM conversions]")
    st, b = call("GET", f"/catalog/variants/{v1}/uom-conversions", viewer)
    check("U01 viewer reads (empty) conversions", st == 200 and b == [], b)
    st, cv = call("POST", f"/catalog/variants/{v1}/uom-conversions", owner, {"from_uom_id": uoms["Box"], "factor": 12, "is_purchase_default": True})
    check("U02 Box → Nos ×12 created, target is the base unit", st == 201 and cv["to_code"] == "Nos" and cv["from_code"] == "Box" and cv["factor"] == 12.0, cv)
    st, b = call("POST", f"/catalog/variants/{v1}/uom-conversions", owner, {"from_uom_id": uoms["Box"], "factor": 10})
    check("U03 same unit twice → 409", st == 409, b)
    st, b = call("POST", f"/catalog/variants/{v1}/uom-conversions", owner, {"from_uom_id": uoms["Nos"], "factor": 1})
    check("U04 base unit to itself → 422", st == 422, b)
    st, b = call("POST", f"/catalog/variants/{v1}/uom-conversions", owner, {"from_uom_id": uoms["Pack"], "factor": 0})
    check("U05 factor 0 → 400", st == 400, b)
    st, b = call("POST", f"/catalog/variants/{v1}/uom-conversions", owner, {"from_uom_id": uoms["Pack"], "factor": -3})
    check("U06 negative factor → 400", st == 400, b)
    st, b = call("POST", f"/catalog/variants/{v1}/uom-conversions", owner, {"from_uom_id": beta_uom, "factor": 2})
    check("U07 other tenant's unit → 422", st == 422, b)
    st, cv2 = call("POST", f"/catalog/variants/{v1}/uom-conversions", gm, {"from_uom_id": uoms["Pack"], "factor": 6, "is_purchase_default": True})
    st2, lst = call("GET", f"/catalog/variants/{v1}/uom-conversions", owner)
    defaults = [x["from_code"] for x in lst if x["is_purchase_default"]]
    check("U08 new purchase default clears the old one", st == 201 and defaults == ["Pack"], lst)
    st, b = call("POST", f"/catalog/variants/{v1}/uom-conversions", staff, {"from_uom_id": uoms["Bag"], "factor": 2})
    check("U09 staff cannot add conversions → 403", st == 403, b)
    st, b = call("GET", f"/catalog/variants/{v1}/uom-conversions", beta)
    check("U10 other tenant cannot read conversions → 404", st == 404, b)
    st, b = call("DELETE", f"/catalog/uom-conversions/{cv2['id']}", beta)
    check("U11 other tenant cannot delete a conversion → 404", st == 404, b)
    st, po_box = call("POST", "/procurement/purchase-orders", owner, {
        "supplier_id": s1, "delivery_godown_id": gA, "expected_delivery_date": TODAY.isoformat(),
        "items": [{"product_variant_id": v1, "quantity": 2, "uom_id": uoms["Box"], "unit_price": 1200, "gst_rate": 18}]})
    check("U12 a PO line in Box now resolves via the conversion (factor 12)", st == 201 and po_box["items"][0]["conversion_factor"] == 12.0, po_box)
    st, b = call("DELETE", f"/catalog/uom-conversions/{cv2['id']}", owner)
    st2, b2 = call("DELETE", f"/catalog/uom-conversions/{cv2['id']}", owner)
    check("U13 delete → 204, again → 404", st == 204 and st2 == 404, (st, st2))
    st, trail = call("GET", f"/audit-logs/product_variant/{v1}", owner)
    descs = [e.get("description") or "" for e in (trail if isinstance(trail, list) else trail.get("items", []))] if st == 200 else []
    check("U14 conversion changes on the variant's audit trail", any("Unit conversion added" in d for d in descs) and any("Unit conversion removed" in d for d in descs), descs[:5])

    # ============================================================ policies
    print("\n[per-godown reorder levels]")
    st, b = call("GET", f"/catalog/variants/{v2}/godown-policies", viewer)
    check("G01 no levels yet", st == 200 and b == [], b)
    body = {"policies": [{"godown_id": gA, "reorder_point": 10, "reorder_qty": 50, "max_stock": 100},
                         {"godown_id": gB, "reorder_point": 5, "reorder_qty": 20}]}
    st, b = call("PUT", f"/catalog/variants/{v2}/godown-policies", owner, body)
    check("G02 set two godowns", st == 200 and len(b) == 2 and {x["godown_id"] for x in b} == {gA, gB} and b[0]["godown_name"], b)
    st, b = call("PUT", f"/catalog/variants/{v2}/godown-policies", owner, {"policies": [{"godown_id": gA}, {"godown_id": gA}]})
    check("G03 duplicate godown → 422", st == 422, b)
    st, b = call("PUT", f"/catalog/variants/{v2}/godown-policies", owner, {"policies": [{"godown_id": gA, "reorder_point": 50, "max_stock": 10}]})
    check("G04 max below reorder point → 400", st == 400, b)
    st, b = call("PUT", f"/catalog/variants/{v2}/godown-policies", owner, {"policies": [{"godown_id": gA, "reorder_point": -1}]})
    check("G05 negative level → 400", st == 400, b)
    st, b = call("PUT", f"/catalog/variants/{v2}/godown-policies", owner, {"policies": [{"godown_id": beta_godown, "reorder_point": 1}]})
    check("G06 other tenant's godown → 422", st == 422, b)
    st, b = call("PUT", f"/catalog/variants/{v2}/godown-policies", gm, {"policies": [
        {"godown_id": gA, "reorder_point": 12, "reorder_qty": 50, "max_stock": 100},
        {"godown_id": gB, "reorder_point": 5, "reorder_qty": 20}]})
    check("G07 scoped manager edits own godown, leaves other unchanged → 200", st == 200 and [x for x in b if x["godown_id"] == gA][0]["reorder_point"] == 12, b)
    st, b = call("PUT", f"/catalog/variants/{v2}/godown-policies", gm, {"policies": [
        {"godown_id": gA, "reorder_point": 12, "reorder_qty": 50, "max_stock": 100},
        {"godown_id": gB, "reorder_point": 99, "reorder_qty": 20}]})
    check("G08 scoped manager changing another godown → 403 GODOWN_OUT_OF_SCOPE", st == 403 and b.get("code") == "GODOWN_OUT_OF_SCOPE", b)
    st, b = call("PUT", f"/catalog/variants/{v2}/godown-policies", gm, {"policies": [
        {"godown_id": gA, "reorder_point": 12, "reorder_qty": 50, "max_stock": 100}]})
    check("G09 scoped manager removing another godown's level → 403", st == 403, b)
    st, b = call("GET", f"/catalog/variants/{v2}/godown-policies", owner)
    check("G10 refused writes changed nothing", st == 200 and len(b) == 2 and [x for x in b if x["godown_id"] == gB][0]["reorder_point"] == 5, b)
    st, b = call("PUT", f"/catalog/variants/{v2}/godown-policies", staff, {"policies": []})
    check("G11 staff cannot set levels → 403", st == 403, b)
    st, b = call("PUT", f"/catalog/variants/{v2}/godown-policies", beta, {"policies": []})
    check("G12 other tenant → 404", st == 404, b)
    st, b = call("PUT", f"/catalog/variants/{v2}/godown-policies", owner, {"policies": [{"godown_id": gB, "reorder_point": 7, "reorder_qty": 20}]})
    check("G13 PUT a subset removes the rest", st == 200 and len(b) == 1 and b[0]["reorder_point"] == 7, b)
    st, b = call("PUT", f"/catalog/variants/{v2}/godown-policies", owner, {"policies": []})
    check("G14 PUT empty clears all", st == 200 and b == [], b)

    # ============================================ performance / history
    print("\n[performance, PO history, price history]")
    def po(expected: date, po_date: date, qty: float, price: float, disc: float, variant: str = v1) -> dict:
        body = ok(*call("POST", "/procurement/purchase-orders", owner, {
            "supplier_id": s1, "delivery_godown_id": gA, "po_date": po_date.isoformat(), "expected_delivery_date": expected.isoformat(),
            "items": [{"product_variant_id": variant, "quantity": qty, "uom_id": uoms["Nos"], "unit_price": price, "discount_pct": disc, "gst_rate": 18}]}), 201)
        ok(*call("POST", f"/procurement/purchase-orders/{body['id']}/submit", owner))
        st, appr = call("POST", f"/procurement/purchase-orders/{body['id']}/approve", owner)
        if st != 200:
            st, appr = call("POST", f"/procurement/purchase-orders/{body['id']}/approve", pm)
        assert st == 200, appr
        return ok(*call("GET", f"/procurement/purchase-orders/{body['id']}", owner))

    def grn(p: dict, received: float, accepted: float) -> None:
        line = p["items"][0]
        g = ok(*call("POST", "/procurement/goods-receipts", owner, {
            "supplier_id": s1, "purchase_order_id": p["id"], "godown_id": gA, "grn_date": TODAY.isoformat(),
            "vehicle_number": f"MH12{SFX}", "items": [{"purchase_order_item_id": line["id"], "product_variant_id": line["product_variant_id"],
            "received_quantity": received, "accepted_quantity": accepted, "uom_id": uoms["Nos"],
            "issue_type": "damaged" if accepted < received else "none",
            "rejection_reason": "Damaged in transit" if accepted < received else None,
            "remarks": "Two cartons crushed" if accepted < received else None}]}), 201)
        st, b = call("POST", f"/procurement/goods-receipts/{g['id']}/confirm", owner)
        assert st == 200, b

    draft = ok(*call("POST", "/procurement/purchase-orders", owner, {
        "supplier_id": s1, "delivery_godown_id": gA, "expected_delivery_date": TODAY.isoformat(),
        "items": [{"product_variant_id": v3, "quantity": 1, "uom_id": uoms["Nos"], "unit_price": 10, "gst_rate": 18}]}), 201)
    st, lst = call("GET", f"/catalog/suppliers/{s1}/products", owner)
    check("P01 a draft PO does not count as buying from the supplier", st == 200 and all(x["product_variant_id"] != v3 for x in lst), lst)

    po_a = po(TODAY, TODAY, 10, 100, 10)                                   # on time
    grn(po_a, 10, 8)
    po_b = po(TODAY - timedelta(days=3), TODAY - timedelta(days=5), 5, 120, 0)   # late
    grn(po_b, 5, 5)
    po_c = po(TODAY, TODAY, 3, 50, 0, variant=v2)                           # bought, not received

    st, perf = call("GET", f"/catalog/suppliers/{s1}/performance", staff)
    check("P02 staff may read performance", st == 200, perf)
    check("P03 on-time = 1 of 2 due orders = 50%", perf.get("on_time_delivery_pct") == 50, perf)
    check("P04 quality = accepted/received = 13/15 = 87%", perf.get("quality_score_pct") == 87, perf)
    check("P05 spend = accepted × net PO rate (8×90 + 5×120 = 1320)", perf.get("total_purchases") == 1320.0, perf)
    check("P06 open orders excludes drafts & fully received (a partial + c approved = 2)", perf.get("open_orders") == 2, perf)
    check("P07 products supplied = linked ∪ bought (v1, v2)", perf.get("products_supplied") == 2, perf)
    check("P08 open variances is a number", isinstance(perf.get("open_variances"), int), perf)
    st, allp = call("GET", "/catalog/supplier-performance", viewer)
    mine = {x["supplier_id"]: x for x in allp} if st == 200 else {}
    check("P09 bulk performance covers every live supplier, zeros for new ones", s1 in mine and s2 in mine and mine[s2]["total_purchases"] == 0 and s3 not in mine, st)
    st, b = call("GET", "/catalog/supplier-performance", beta)
    check("P10 bulk performance never leaks across tenants", st == 200 and all(x["supplier_id"] not in (s1, s2) for x in b), st)

    st, lst = call("GET", f"/catalog/suppliers/{s1}/products", owner)
    derived = [x for x in lst if x["product_variant_id"] == v2] if st == 200 else []
    check("P11 SKU bought without a recorded code shows as purchase_history, no id", len(derived) == 1 and derived[0]["id"] is None and derived[0]["match_source"] == "purchase_history", derived)
    linked = [x for x in lst if x["product_variant_id"] == v1]
    check("P12 last purchase price = latest PO net rate (120 from PO b, dated later? no: PO a is newer → 90)", linked and linked[0]["last_purchase_price"] == 90.0, linked)

    st, orders = call("GET", f"/catalog/suppliers/{s1}/purchase-orders", owner)
    check("P13 PO history newest first, drafts included", st == 200 and len(orders) >= 4 and orders[-1]["id"] == po_b["id"], [o["po_number"] for o in orders] if st == 200 else orders)
    st, b = call("GET", f"/catalog/suppliers/{s1}/purchase-orders", staff)
    check("P14 staff (no po.view) cannot see PO history → 403", st == 403, b)
    st, b = call("GET", f"/catalog/suppliers/{s1}/purchase-orders?limit=1000", owner)
    check("P15 limit is capped → 400", st == 400, b)
    st, hist = call("GET", f"/catalog/suppliers/{s1}/price-history?product_variant_id={v1}", owner)
    check("P16 price history newest first with change %", st == 200 and [h["unit_price"] for h in hist] == [90.0, 120.0] and hist[0]["change_pct"] == -25.0 and hist[1]["change_pct"] == 0, hist)
    st, b = call("GET", f"/catalog/suppliers/{s1}/price-history?product_variant_id={v1}", staff)
    check("P17 staff cannot read price history → 403", st == 403, b)
    st, b = call("GET", f"/catalog/suppliers/{s1}/price-history", owner)
    check("P18 price history needs product_variant_id → 400", st == 400, b)
    st, b = call("GET", f"/catalog/suppliers/{s1}/performance", beta)
    check("P19 other tenant cannot read performance → 404", st == 404, b)

    # ============================================================== in use
    print("\n[in-use guards]")
    st, u = call("GET", f"/catalog/suppliers/{s1}/usage", viewer)
    check("I01 supplier with open POs is in use", st == 200 and u["in_use"] and "Open purchase order" in u["reason"], u)
    st, b = call("PATCH", f"/catalog/suppliers/{s1}", owner, {"status": "inactive"})
    check("I02 deactivating it → 409 RECORD_IN_USE", st == 409 and b.get("code") == "RECORD_IN_USE", b)
    st, b = call("DELETE", f"/catalog/suppliers/{s1}", owner)
    check("I03 deleting it → 409", st == 409, b)
    st, b = call("PATCH", f"/catalog/suppliers/{s1}", owner, {"city": "Thane"})
    check("I04 ordinary edits still work while in use", st == 200 and b["city"] == "Thane", b)
    st, u = call("GET", f"/catalog/suppliers/{s2}/usage", owner)
    st2, b = call("PATCH", f"/catalog/suppliers/{s2}", owner, {"status": "inactive"})
    check("I05 unused supplier can be deactivated", st == 200 and not u["in_use"] and st2 == 200 and b["status"] == "inactive", (u, b))
    call("PATCH", f"/catalog/suppliers/{s2}", owner, {"status": "active"})
    st, u = call("GET", f"/catalog/variants/{v1}/usage", owner)
    check("I06 variant holding stock is in use", st == 200 and u["in_use"] and "in stock" in u["reason"], u)
    st, b = call("DELETE", f"/catalog/variants/{v1}", owner)
    check("I07 deleting a stocked variant → 409", st == 409 and b.get("code") == "RECORD_IN_USE", b)
    st, b = call("PATCH", f"/catalog/variants/{v1}", owner, {"is_active": False})
    check("I08 deactivating a stocked variant → 409", st == 409, b)
    st, u = call("GET", f"/catalog/variants/{v2}/usage", owner)
    check("I09 variant on an open PO line is in use", st == 200 and u["in_use"] and "open purchase order" in u["reason"], u)
    st, u = call("GET", f"/catalog/variants/{v3}/usage", owner)
    check("I10 variant only on a draft PO is still in use (draft is open)", st == 200 and u["in_use"], u)
    fresh = product("Spare")
    st, b = call("DELETE", f"/catalog/variants/{fresh}", owner)
    check("I11 unused variant can be deleted", st == 204, b)
    st, b = call("GET", f"/catalog/variants/{fresh}/usage", owner)
    check("I12 deleted variant → 404 on detail endpoints", st == 404, b)
    st, b = call("GET", f"/catalog/variants/{v1}/usage", beta)
    check("I13 other tenant cannot probe usage → 404", st == 404, b)

    print(f"\n{passed} passed, {len(failed)} failed")
    for f in failed:
        print("  -", f)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
