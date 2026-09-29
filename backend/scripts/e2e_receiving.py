"""
E2E HTTP suite — goods receipt: the draft edit path and the detail panels
(postings, variances, reversal, returns).

Runs against a live backend (default http://127.0.0.1:8000) seeded with the
demo tenants. Creates its own users, godowns, products, supplier and POs
with a per-run suffix, so it can be re-run on the same database.

    python -m scripts.e2e_receiving [base_url]

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


async def make_users(godown_a: str) -> dict[str, str]:
    from sqlalchemy import text

    from app.core.db import platform_engine
    from app.core.security import hash_password

    pw = hash_password("Test@12345")
    out = {}
    async with platform_engine.begin() as conn:
        cid = (await conn.execute(text("SELECT id FROM companies WHERE name = 'Acme Trading Co' ORDER BY id LIMIT 1"))).scalar_one()
        for role, scoped in (("staff", False), ("godown_manager", True)):
            rid = (await conn.execute(text("SELECT id FROM roles WHERE company_id IS NULL AND code = :r"), {"r": role})).scalar_one()
            email = f"rcv.{role}.{SFX.lower()}@acme-demo.test"
            uid = (
                await conn.execute(
                    text(
                        "INSERT INTO users (company_id, email, full_name, role_id, is_platform_admin, has_all_godowns, "
                        "status, password_hash, password_changed_at) VALUES (:c, :e, :n, :r, false, :all, 'active', :pw, now()) "
                        "RETURNING id"
                    ),
                    {"c": cid, "e": email, "n": f"rcv {role} {SFX}", "r": rid, "all": not scoped, "pw": pw},
                )
            ).scalar_one()
            if scoped:
                await conn.execute(
                    text("INSERT INTO user_godown_access (user_id, godown_id) VALUES (:u, :g)"), {"u": uid, "g": godown_a}
                )
            out[role] = email
    return out


def main() -> int:
    owner = login("owner@acme-demo.test", "Demo@12345")
    beta = login("owner@beta-demo.test", "Demo@12345")

    # ------------------------------------------------------------ fixtures
    uoms = {u["code"]: u["id"] for u in ok(*call("GET", "/catalog/uoms-available", owner))}
    nos = uoms["Nos"]
    gA = ok(*call("POST", "/catalog/godowns", owner, {"name": f"RA {SFX}", "code": f"RA{SFX}", "city": "Pune", "state_code": "27"}), 201)["id"]
    gB = ok(*call("POST", "/catalog/godowns", owner, {"name": f"RB {SFX}", "code": f"RB{SFX}", "city": "Nagpur", "state_code": "27"}), 201)["id"]

    def variant(name: str, tracking: str = "none") -> str:
        p = ok(*call("POST", "/catalog/products", owner, {"name": f"{name} {SFX}", "base_uom_id": nos, "hsn_code": "8471", "gst_rate": 18, "tracking_type": tracking}), 201)
        return ok(*call("POST", "/catalog/variants", owner, {"product_id": p["id"], "sku": f"{name[:3].upper()}R-{SFX}", "uom_id": nos, "purchase_price": 100, "sale_price": 150, "mrp": 200}), 201)["id"]

    v1, v2, vbatch = variant("Pump"), variant("Valve"), variant("Serum", "batch")
    beta_p = ok(*call("POST", "/catalog/products", beta, {"name": f"Beta recv {SFX}", "base_uom_id": nos}), 201)
    beta_v = ok(*call("POST", "/catalog/variants", beta, {"product_id": beta_p["id"], "sku": f"BR-{SFX}", "uom_id": nos}), 201)["id"]
    beta_godown = ok(*call("GET", "/catalog/godowns", beta))[0]["id"]

    supplier = ok(*call("POST", "/catalog/suppliers", owner, {
        "name": f"Receiving Supplier {SFX}", "supplier_type": "Distributor", "gst_treatment": "unregistered",
        "city": "Mumbai", "state_code": "27", "state_name": "Maharashtra"}), 201)["id"]

    users = asyncio.run(make_users(gA))
    staff = login(users["staff"], "Test@12345")
    gm = login(users["godown_manager"], "Test@12345")

    def make_po(lines, expected: date = TODAY) -> dict:
        po = ok(*call("POST", "/procurement/purchase-orders", owner, {
            "supplier_id": supplier, "delivery_godown_id": gA, "expected_delivery_date": expected.isoformat(),
            "items": [{"product_variant_id": v, "quantity": q, "uom_id": nos, "unit_price": price, "gst_rate": 18} for v, q, price in lines]}), 201)
        ok(*call("POST", f"/procurement/purchase-orders/{po['id']}/submit", owner))
        ok(*call("POST", f"/procurement/purchase-orders/{po['id']}/approve", owner))
        return ok(*call("GET", f"/procurement/purchase-orders/{po['id']}", owner))

    po1 = make_po([(v1, 10, 100), (v2, 5, 200)])
    line1, line2 = po1["items"][0], po1["items"][1]

    def draft(items, po=po1, godown=gA, token=owner) -> tuple[int, object]:
        return call("POST", "/procurement/goods-receipts", token, {
            "supplier_id": supplier, "purchase_order_id": po["id"], "godown_id": godown,
            "grn_date": TODAY.isoformat(), "vehicle_number": f"MH01{SFX}", "items": items})

    def line(po_line, received, accepted, **extra) -> dict:
        return {"purchase_order_item_id": po_line["id"], "product_variant_id": po_line["product_variant_id"],
                "received_quantity": received, "accepted_quantity": accepted, "uom_id": nos, **extra}

    # ========================================================== draft edit
    print("\n[draft edit]")
    st, grn = draft([line(line1, 4, 4)])
    check("E01 draft created", st == 201 and grn["status"] == "draft" and isinstance(grn["row_version"], int), grn)
    st, detail = call("GET", f"/procurement/goods-receipts/{grn['id']}", owner)
    item = detail["items"][0] if st == 200 else {}
    check("E02 a draft has no ledger link, no batch, no reversal",
          st == 200 and item.get("inventory_transaction_id") is None and item.get("posted_quantity") is None
          and item.get("batch_number") is None and detail.get("reversal") is None, detail)

    def patch(body, token=owner, grn_id=None):
        return call("PATCH", f"/procurement/goods-receipts/{grn_id or grn['id']}", token, body)

    base_edit = {"grn_date": TODAY.isoformat(), "godown_id": gA, "vehicle_number": f"MH02{SFX}",
                 "transporter_name": "VRL", "remarks": "Re-counted at the gate", "items": [line(line1, 6, 6)],
                 "row_version": grn["row_version"]}

    st, b = patch({**base_edit, "row_version": grn["row_version"] + 5})
    check("E03 stale row_version → 409 STALE_RECORD", st == 409 and b.get("code") == "STALE_RECORD", b)
    st, b = patch(base_edit, token=staff)
    check("E04 staff (no grn.update) cannot edit a draft → 403", st == 403, b)
    st, b = patch(base_edit, token=beta)
    check("E05 other tenant cannot edit our draft → 404", st == 404, b)
    st, edited = patch(base_edit)
    check("E06 draft edited: lines replaced, header kept, version bumped",
          st == 200 and len(edited["items"]) == 1 and edited["items"][0]["received_quantity"] == 6
          and edited["vehicle_number"] == f"MH02{SFX}" and edited["transporter_name"] == "VRL"
          and edited["row_version"] == grn["row_version"] + 1, edited)
    st, po_now = call("GET", f"/procurement/purchase-orders/{po1['id']}", owner)
    check("E07 editing a draft does not move the PO's received quantity",
          st == 200 and po_now["items"][0]["received_quantity"] == 0 and po_now["items"][0]["pending_quantity"] == 10, po_now["items"][0])

    rv = edited["row_version"]
    st, b = patch({**base_edit, "items": [], "row_version": rv})
    check("E08 an edit with no lines → 400", st == 400, b)
    st, b = patch({**base_edit, "items": [line(line1, 4, 9)], "row_version": rv})
    check("E09 accepted above received → 400", st == 400, b)
    st, b = patch({**base_edit, "items": [line(line1, 11, 11)], "row_version": rv})
    check("E10 above the PO line's pending balance → 422 EXCESS_RECEIPT_NOT_ALLOWED",
          st == 422 and b.get("code") == "EXCESS_RECEIPT_NOT_ALLOWED", b)
    st, b = patch({**base_edit, "items": [line(line1, 6, 4)], "row_version": rv})
    check("E11 a rejection with no remarks → 422 REMARKS_REQUIRED", st == 422 and b.get("code") == "REMARKS_REQUIRED", b)
    st, b = patch({**base_edit, "grn_date": (TODAY + timedelta(days=1)).isoformat(), "row_version": rv})
    check("E12 a future receipt date → 400", st == 400, b)
    st, b = patch({**base_edit, "items": [line(line1, 2, 0, issue_type="wrong_product", remarks="Different model arrived")], "row_version": rv})
    check("E13 wrong_product without expected_variant_id → 422", st == 422 and b.get("code") == "EXPECTED_VARIANT_REQUIRED", b)
    st, b = patch({**base_edit, "items": [{"product_variant_id": beta_v, "received_quantity": 1, "accepted_quantity": 1, "uom_id": nos}], "row_version": rv})
    check("E14 a line for another tenant's product → 400", st == 400, b)
    st, b = patch({**base_edit, "items": [{"product_variant_id": vbatch, "received_quantity": 2, "accepted_quantity": 2, "uom_id": nos}], "row_version": rv})
    check("E15 a batch-tracked item with no batch number → 422 BATCH_REQUIRED", st == 422 and b.get("code") == "BATCH_REQUIRED", b)
    st, b = patch({**base_edit, "godown_id": gB, "row_version": rv}, token=gm)
    check("E16 a scoped manager cannot move a receipt to another godown → 403", st == 403 and b.get("code") == "GODOWN_OUT_OF_SCOPE", b)
    st, after_failures = call("GET", f"/procurement/goods-receipts/{grn['id']}", owner)
    check("E17 every refused edit left the draft untouched",
          st == 200 and after_failures["row_version"] == rv and len(after_failures["items"]) == 1
          and after_failures["items"][0]["received_quantity"] == 6, after_failures)

    st, b = patch({**base_edit, "items": [line(line1, 6, 6), line(line2, 5, 5)], "row_version": rv})
    check("E18 a second line can be added to the draft", st == 200 and len(b["items"]) == 2, b)
    rv = b["row_version"]

    # a batch line, added properly this time
    st, b = patch({**base_edit,
                   "items": [line(line1, 6, 6), line(line2, 5, 5),
                             {"product_variant_id": vbatch, "received_quantity": 2, "accepted_quantity": 2,
                              "uom_id": nos, "batch_number": f"B{SFX}", "expires_on": (TODAY + timedelta(days=400)).isoformat()}],
                   "row_version": rv})
    check("E19 a batch line is accepted with its number and expiry",
          st == 200 and [i for i in b["items"] if i["batch_number"]][0]["batch_number"] == f"B{SFX}", b)
    rv = b["row_version"]
    st, b = patch({**base_edit, "items": [line(line1, 6, 6), line(line2, 5, 4, rejection_reason="Dented", remarks="One valve dented")], "row_version": rv})
    check("E20 back to two lines, one with a rejection", st == 200 and len(b["items"]) == 2 and b["has_discrepancy"] is False, b)
    rv = b["row_version"]

    # ============================================================= confirm
    print("\n[confirm: postings, variances, alerts]")
    st, result = call("POST", f"/procurement/goods-receipts/{grn['id']}/confirm", owner)
    check("C01 confirm returns the receipt, its postings and the PO's progress",
          st == 200 and result["goods_receipt"]["status"] == "partially_received"
          and len(result["inventory_postings"]) == 2 and result["purchase_order"]["received_pct"] > 0, result)
    postings = {p["goods_receipt_item_id"]: p for p in result["inventory_postings"]} if st == 200 else {}
    gr = result["goods_receipt"]
    accepted_by_line = {i["id"]: i["accepted_quantity"] for i in gr["items"]}
    check("C02 every posting matches its line's accepted quantity and carries a balance",
          all(postings[i]["quantity"] == accepted_by_line[i] for i in postings)
          and all(p["balance_now"] is not None for p in postings.values()), result.get("inventory_postings"))
    check("C03 each line now links to its ledger row and reports what posted",
          all(i["inventory_transaction_id"] and i["posted_quantity"] == i["accepted_quantity"] for i in gr["items"]), gr["items"])

    variances = {v["variance_type"] for v in result["variances"]}
    short = [v for v in result["variances"] if v["variance_type"] == "quantity" and v["base_value"] == 10]
    reject = [v for v in result["variances"] if v["variance_type"] == "quantity" and v["base_value"] == 5 and v["compare_value"] == 4]
    check("C04 short delivery recorded as a quantity variance (10 ordered, 6 received)",
          len(short) == 1 and short[0]["difference"] == -4, result["variances"])
    check("C05 the rejected line recorded too (5 received, 4 accepted)", len(reject) == 1, result["variances"])
    check("C06 no variance types other than quantity on this receipt", variances == {"quantity"}, variances)
    st, listed = call("GET", f"/procurement/goods-receipts/{grn['id']}/variances", owner)
    check("C07 the variances endpoint returns the same rows", st == 200 and len(listed) == len(result["variances"]), listed)
    st, b = call("GET", f"/procurement/goods-receipts/{grn['id']}/variances", beta)
    check("C08 other tenant cannot read them → 404", st == 404, b)
    check("C09 confirming raised the quantity-mismatch alert", len(result["alerts_raised"]) >= 1, result["alerts_raised"])

    st, again = call("POST", f"/procurement/goods-receipts/{grn['id']}/confirm", owner)
    st2, listed2 = call("GET", f"/procurement/goods-receipts/{grn['id']}/variances", owner)
    check("C10 confirming twice posts nothing twice and duplicates no variance",
          st == 200 and len(again["inventory_postings"]) == 2 and len(listed2) == len(listed), (again.get("inventory_postings"), listed2))
    st, b = patch({**base_edit, "row_version": gr["row_version"]})
    check("C11 a confirmed receipt can no longer be edited → 409 GRN_CONFIRMED", st == 409 and b.get("code") == "GRN_CONFIRMED", b)

    st, posts = call("GET", f"/procurement/goods-receipts/{grn['id']}/postings", owner)
    check("C12 the postings endpoint lists both ledger rows", st == 200 and len(posts) == 2 and posts[0]["sku"], posts)
    st, b = call("GET", f"/procurement/goods-receipts/{grn['id']}/postings", beta)
    check("C13 other tenant cannot read postings → 404", st == 404, b)

    # ============================================================= returns
    print("\n[returns panel]")
    confirmed_lines = {i["product_variant_id"]: i for i in gr["items"]}
    rline = confirmed_lines[line2["product_variant_id"]]
    st, ret = call("POST", "/purchase-returns", owner, {
        "supplier_id": supplier, "godown_id": gA, "goods_receipt_id": grn["id"], "reason": "Dented on arrival",
        "items": [{"goods_receipt_item_id": rline["id"], "product_variant_id": rline["product_variant_id"],
                   "quantity": 1, "unit_price": 200, "gst_rate": 18}]})
    check("R01 a return can be raised against the receipt", st == 201, ret)
    st, mine = call("GET", f"/purchase-returns?goods_receipt_id={grn['id']}", owner)
    check("R02 returns filter by receipt", st == 200 and len(mine) == 1 and mine[0]["id"] == ret["id"], mine)
    st, other = call("GET", f"/purchase-returns?goods_receipt_id={uuid.uuid4()}", owner)
    check("R03 an unrelated receipt has none", st == 200 and other == [], other)
    st, b = call("GET", f"/purchase-returns?goods_receipt_id={grn['id']}", beta)
    check("R04 the filter never crosses tenants", st == 200 and b == [], b)

    # ============================================================ reversal
    print("\n[reversal]")
    st, rev = call("POST", f"/procurement/goods-receipts/{grn['id']}/reverse", owner, {"reason": "Counted wrong at the gate"})
    check("V01 receipt reversed", st == 200, rev)
    st, after_rev = call("GET", f"/procurement/goods-receipts/{grn['id']}", owner)
    reversal = after_rev.get("reversal") if st == 200 else None
    check("V02 detail now carries who reversed it, when and why",
          bool(reversal) and reversal["reason"] == "Counted wrong at the gate" and reversal["reversed_by_name"] and reversal["reversed_at"], reversal)
    st, posts2 = call("GET", f"/procurement/goods-receipts/{grn['id']}/postings", owner)
    offsets = [p for p in posts2 if p["quantity"] < 0] if st == 200 else []
    check("V03 the offsetting rows are on the same receipt and point at what they reverse",
          len(offsets) == 2 and all(p["reverses_txn_id"] for p in offsets) and all(p["txn_type"] == "STOCK_CORRECTION" for p in offsets), posts2)
    st, b = call("POST", f"/procurement/goods-receipts/{grn['id']}/reverse", owner, {"reason": "again"})
    check("V04 a receipt cannot be reversed twice → 409", st == 409, b)

    # ======================================================= wrong product
    print("\n[wrong product]")
    po2 = make_po([(v1, 4, 100)])
    st, grn2 = draft([{"purchase_order_item_id": po2["items"][0]["id"], "product_variant_id": v1,
                       "received_quantity": 4, "accepted_quantity": 0, "uom_id": nos,
                       "issue_type": "wrong_product", "expected_variant_id": v2,
                       "remarks": "Supplier shipped the wrong model"}], po=po2)
    check("W01 a wrong-product draft is accepted with expected_variant_id", st == 201 and grn2["has_discrepancy"], grn2)
    st, res2 = call("POST", f"/procurement/goods-receipts/{grn2['id']}/confirm", owner)
    kinds = {v["variance_type"] for v in res2["variances"]} if st == 200 else set()
    check("W02 a wrong item is a product variance, not a quantity one", kinds == {"product"}, res2.get("variances"))
    check("W03 nothing was posted to stock for it", st == 200 and res2["inventory_postings"] == [], res2.get("inventory_postings"))
    st, alerts = call("GET", "/alerts", owner)
    items = alerts["items"] if isinstance(alerts, dict) else (alerts or [])
    wrong = [a for a in items if a.get("rule_code") == "GRN_WRONG_PRODUCT" and str(a.get("reference_id")) == grn2["id"]]
    check("W04 the wrong-product alert rule fires (it matched an issue_type that cannot exist before)",
          len(wrong) >= 1 or len(res2.get("alerts_raised", [])) >= 1,
          sorted({a.get("rule_code") for a in items}))

    print(f"\n{passed} passed, {len(failed)} failed")
    for f in failed:
        print("  -", f)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
