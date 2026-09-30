"""End-to-end business flow through the real API.

RFQ -> 2 quotations -> comparison -> PO -> proforma -> GRN -> stock ->
3-way-matched invoice (+ a mismatched one) -> payment -> purchase return ->
transfer -> adjustment + reversal -> negative-stock guard -> low stock alert
-> reports -> dashboard -> audit trail.
"""
import os
API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")
PLATFORM_DB = os.environ.get(
    "TEST_PLATFORM_DATABASE_URL", "postgresql://inventoryai_platform:inventoryai_platform_dev@localhost/inventoryai"
)
import json, random, string, sys, urllib.error, urllib.request
from datetime import date, timedelta

B = API_URL
T = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
TODAY = date.today().isoformat()
passed, failed = 0, []


def check(name, cond, info=""):
    global passed
    if cond:
        passed += 1
        print("  ok  ", name)
    else:
        failed.append(name)
        print("  FAIL", name, "->", json.dumps(info, default=str)[:600] if not isinstance(info, str) else info[:600])
    return cond


def api(m, p, body=None, tok=None):
    h = {"content-type": "application/json"}
    if tok or TOK:
        h["authorization"] = "Bearer " + (tok or TOK)
    r = urllib.request.Request(B + p, data=json.dumps(body).encode() if body is not None else None, headers=h, method=m)
    try:
        x = urllib.request.urlopen(r, timeout=120)
        raw = x.read()
        return x.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw[:300].decode(errors="replace")


TOK = None


def items(x):
    """Lists come back bare or as {"items": [...]}."""
    return x.get("items", []) if isinstance(x, dict) else (x or [])
s, auth = api("POST", "/auth/login", {"email": "owner@acme-demo.test", "password": "Demo@12345"})
TOK = auth["access_token"]


def stock(variant_id, godown_id=None):
    s, rows = api("GET", f"/inventory/stock?limit=500&q=FLW-{T}")
    total = 0.0
    for r in items(rows):
        if r.get("product_variant_id") == variant_id and (godown_id is None or r.get("godown_id") == godown_id):
            total += float(r.get("quantity") or r.get("on_hand") or r.get("current_quantity") or 0)
    return total


print("\n== setup")
uoms = {u["code"]: u["id"] for u in api("GET", "/catalog/uoms-available")[1]}
NOS = uoms["Nos"]
godowns = items(api("GET", "/catalog/godowns?limit=50")[1])
GA = next(g for g in godowns if g["is_default"])["id"]
s, gb = api("POST", "/catalog/godowns", {"name": f"Flow Store {T}", "code": f"F{T}", "city": "Indore", "state_code": "23"})
check("S1 second godown created", s == 201, gb)
GB = gb["id"]
sup = []
for i in (1, 2):
    s, sp = api("POST", "/catalog/suppliers", {"name": f"Flow Supplier {i} {T}", "supplier_type": "Distributor",
                                               "gst_treatment": "unregistered", "city": "Indore", "state_code": "23",
                                               "state_name": "Madhya Pradesh", "email": f"s{i}.{T.lower()}@example.com"})
    check(f"S2 supplier {i} created", s == 201, sp)
    sup.append(sp["id"])
s, prod = api("POST", "/catalog/products", {"name": f"Flow Widget {T}", "base_uom_id": NOS, "hsn_code": "8536", "gst_rate": 18})
s, var = api("POST", "/catalog/variants", {"product_id": prod["id"], "sku": f"FLW-{T}", "uom_id": NOS,
                                           "purchase_price": 100, "sale_price": 140, "mrp": 160})
check("S3 product + variant created", s == 201, var)
V = var["id"]
check("S4 new product starts with zero stock", stock(V) == 0, stock(V))

print("\n== RFQ -> quotations -> comparison")
s, rfq = api("POST", "/procurement/rfqs", {"subject": f"Flow RFQ {T}", "delivery_godown_id": GA,
                                           "expected_delivery_date": (date.today() + timedelta(days=7)).isoformat(),
                                           "items": [{"product_variant_id": V, "quantity": 100, "uom_id": NOS, "expected_price": 100}]})
check("R1 RFQ created as draft", s == 201 and rfq["status"] == "draft", rfq)
s, sent = api("POST", f"/procurement/rfqs/{rfq['id']}/send", {"supplier_ids": sup})
check("R2 RFQ sent to 2 suppliers", s == 200 and sent["status"] == "sent", sent)
rfq_item = rfq["items"][0]["id"]
quotes = []
for i, price in ((0, 100), (1, 90)):
    s, q = api("POST", "/procurement/quotations", {
        "supplier_id": sup[i], "rfq_id": rfq["id"], "quotation_number": f"Q{i}-{T}", "quotation_date": TODAY,
        "valid_until": (date.today() + timedelta(days=30)).isoformat(),
        "items": [{"rfq_item_id": rfq_item, "product_variant_id": V, "quantity": 100, "uom_id": NOS, "unit_price": price, "gst_rate": 18}]})
    check(f"R3 quotation {i + 1} recorded ({price}/unit)", s == 201, q)
    quotes.append(q)
    s, a = api("POST", f"/procurement/quotations/{q['id']}/approve")
    check(f"R4 quotation {i + 1} approved", s == 200, a)
s, r2 = api("GET", f"/procurement/rfqs/{rfq['id']}")
check("R5 RFQ now shows as quoted", r2["status"] in ("quoted", "partially_quoted"), r2.get("status"))
s, cmp_ = api("POST", "/procurement/comparisons", {"rfq_id": rfq["id"]})
check("R6 comparison built", s in (200, 201), cmp_)
rows = cmp_.get("rows") or []
cheap_item = quotes[1]["items"][0]["id"]
check("R7 comparison picks the cheaper supplier (90)", rows and all(r.get("selected_quotation_item_id") == cheap_item for r in rows), rows[:1])
check("R8 comparison has both suppliers side by side", len(cmp_.get("suppliers") or []) == 2, cmp_.get("suppliers"))

print("\n== PO")
s, pos = api("POST", f"/procurement/comparisons/{cmp_['id']}/convert", {"delivery_godown_id": GA})
check("P1 comparison converted to a PO", s in (200, 201) and pos, pos)
po = (pos if isinstance(pos, list) else pos.get("purchase_orders", [pos]))[0]
check("P2b converted PO inherits the RFQ's delivery date", po.get("expected_delivery_date") == (date.today() + timedelta(days=7)).isoformat(), po.get("expected_delivery_date"))
check("P2 PO is for the cheaper supplier at 90", po["supplier_id"] == sup[1] and float(po["items"][0]["unit_price"]) == 90, po)
for step in ("submit", "approve", "send"):
    s, r = api("POST", f"/procurement/purchase-orders/{po['id']}/{step}")
    check(f"P3 PO {step}", s == 200, r)
s, po = api("GET", f"/procurement/purchase-orders/{po['id']}")
check("P4 PO total = 100 x 90 + 18% GST = 10620", abs(float(po.get("grand_total") or po.get("total_amount") or 0) - 10620) < 1, {k: po.get(k) for k in ("grand_total", "total_amount", "status")})
poi = po["items"][0]["id"]

print("\n== proforma")
s, pf = api("POST", "/proforma-invoices", {"supplier_id": sup[1], "purchase_order_id": po["id"], "proforma_number": f"PI-{T}",
                                            "proforma_date": TODAY, "items": [{"purchase_order_item_id": poi, "product_variant_id": V,
                                                                               "quantity": 100, "uom_id": NOS, "unit_price": 90, "gst_rate": 18}]})
check("F1 proforma recorded against the PO", s == 201, pf)
s, r = api("POST", f"/proforma-invoices/{pf['id']}/approve")
check("F2 proforma approved (no variance)", s == 200, r)

print("\n== GRN -> stock")
s, grn = api("POST", "/procurement/goods-receipts", {"supplier_id": sup[1], "purchase_order_id": po["id"], "godown_id": GA, "grn_date": TODAY,
                                                     "items": [{"purchase_order_item_id": poi, "product_variant_id": V, "received_quantity": 60,
                                                                "accepted_quantity": 60, "uom_id": NOS, "unit_price": 90}]})
check("G1 GRN drafted", s == 201, grn)
s, c = api("POST", f"/procurement/goods-receipts/{grn['id']}/confirm")
check("G2 GRN confirmed", s == 200, c)
check("G3 stock at main godown = 60", stock(V, GA) == 60, stock(V, GA))
s, po2 = api("GET", f"/procurement/purchase-orders/{po['id']}")
check("G4 PO is partially received", po2["status"] in ("partially_received", "partial"), po2["status"])
s, grn = api("GET", f"/procurement/goods-receipts/{grn['id']}")
grni = grn["items"][0]["id"]

print("\n== supplier invoices (3-way match)")
s, inv = api("POST", "/supplier-invoices", {"supplier_id": sup[1], "invoice_number": f"INV-{T}", "invoice_date": TODAY,
                                            "purchase_order_id": po["id"], "goods_receipt_id": grn["id"],
                                            "items": [{"purchase_order_item_id": poi, "goods_receipt_item_id": grni, "product_variant_id": V,
                                                       "quantity": 60, "uom_id": NOS, "unit_price": 90, "gst_rate": 18}]})
check("I1 invoice recorded", s == 201, inv)
s, m = api("POST", f"/supplier-invoices/{inv['id']}/match")
check("I2 3-way match: invoice = PO = GRN -> matched", s == 200 and "matched" in json.dumps(m) and "variance" != (m.get("match_status") if isinstance(m, dict) else ""), m)
s, bad = api("POST", "/supplier-invoices", {"supplier_id": sup[1], "invoice_number": f"INV-BAD-{T}", "invoice_date": TODAY,
                                            "purchase_order_id": po["id"], "goods_receipt_id": grn["id"],
                                            "items": [{"purchase_order_item_id": poi, "goods_receipt_item_id": grni, "product_variant_id": V,
                                                       "quantity": 60, "uom_id": NOS, "unit_price": 99, "gst_rate": 18}]})
s, m2 = api("POST", f"/supplier-invoices/{bad['id']}/match")
check("I3 overcharged invoice (99 vs 90) flagged as a variance", s == 200 and "variance" in json.dumps(m2).lower(), m2)
s, rv_ = api("POST", f"/supplier-invoices/{inv['id']}/status", {"status": "under_review"})
check("I3b invoice sent for review", s == 200, rv_)
s, early = api("POST", f"/supplier-invoices/{bad['id']}/approve")
check("I3c a draft invoice cannot be approved directly", s == 409, early)
s, ap = api("POST", f"/supplier-invoices/{inv['id']}/approve")
check("I4 matched invoice approved", s == 200, ap)
s, pay = api("POST", f"/supplier-invoices/{inv['id']}/payments", {"amount": 3000})
check("I5 part payment -> partially paid", s == 200 and pay.get("payment_status") == "partially_paid", pay)
s, vs = api("GET", "/variances?limit=100")
check("I6 the price variance is listed", s == 200 and any(bad["id"] in json.dumps(v) or f"INV-BAD-{T}" in json.dumps(v) for v in items(vs)), len(items(vs)))

print("\n== purchase return")
s, ret = api("POST", "/purchase-returns", {"supplier_id": sup[1], "godown_id": GA, "goods_receipt_id": grn["id"], "purchase_order_id": po["id"],
                                           "return_date": TODAY, "reason": "Damaged in transit",
                                           "items": [{"goods_receipt_item_id": grni, "product_variant_id": V, "quantity": 10, "unit_price": 90, "gst_rate": 18}]})
check("T1 return drafted", s == 201, ret)
s, c = api("POST", f"/purchase-returns/{ret['id']}/confirm")
check("T2 return confirmed", s == 200, c)
check("T3 stock drops to 50", stock(V, GA) == 50, stock(V, GA))

print("\n== transfer, adjustment, guards")
s, tr = api("POST", "/inventory/transfers", {"from_godown_id": GA, "to_godown_id": GB, "transfer_date": TODAY,
                                             "items": [{"product_variant_id": V, "quantity": 20, "uom_id": NOS}]})
check("X1 transfer 20 to the second godown", s in (200, 201), tr)
check("X2 main = 30, second = 20", (stock(V, GA), stock(V, GB)) == (30, 20), (stock(V, GA), stock(V, GB)))
s, dmg = api("POST", "/inventory/transactions", {"txn_type": "DAMAGE", "product_variant_id": V, "godown_id": GB, "quantity": 5, "uom_id": NOS,
                                                 "txn_date": TODAY, "remarks": "Broken on shelf"})
check("X3 damage write-off of 5", s in (200, 201) and stock(V, GB) == 15, (s, dmg, stock(V, GB)))
s, rv = api("POST", f"/inventory/transactions/{dmg['id']}/reverse", {"reason": "Found intact"})
check("X4 reversing it restores 20", s in (200, 201) and stock(V, GB) == 20, (s, rv, stock(V, GB)))
s, neg = api("POST", "/inventory/transactions", {"txn_type": "DAMAGE", "product_variant_id": V, "godown_id": GB, "quantity": 1000, "uom_id": NOS, "txn_date": TODAY})
check("X5 cannot write off more than is in stock", 400 <= s < 500 and stock(V, GB) == 20, (s, neg))
s, tr2 = api("POST", "/inventory/transfers", {"from_godown_id": GA, "to_godown_id": GA, "items": [{"product_variant_id": V, "quantity": 1, "uom_id": NOS}]})
check("X6 cannot transfer a godown to itself", 400 <= s < 500, (s, tr2))
s, grn_over = api("POST", "/procurement/goods-receipts", {"supplier_id": sup[1], "purchase_order_id": po["id"], "godown_id": GA, "grn_date": TODAY,
                                                          "items": [{"purchase_order_item_id": poi, "product_variant_id": V, "received_quantity": 500,
                                                                     "accepted_quantity": 500, "uom_id": NOS}]})
over_blocked = 400 <= s < 500
if not over_blocked and s == 201:
    s2, c2 = api("POST", f"/procurement/goods-receipts/{grn_over['id']}/confirm")
    over_blocked = 400 <= s2 < 500
    api("POST", f"/procurement/goods-receipts/{grn_over['id']}/cancel")
check("X7 receiving 500 against 40 still pending is refused", over_blocked, (s, grn_over))
s, vb = api("GET", "/inventory/verify-balances")
check("X8 ledger and balances agree", s == 200 and not vb.get("mismatches") and vb.get("ok", True) is not False, vb)
s, txns = api("GET", f"/inventory/transactions?limit=200")
mine = [t for t in items(txns) if t.get("product_variant_id") == V]
check("X9 ledger has every movement (GRN, return, 2x transfer, damage, reversal)", len(mine) >= 6, len(mine))

print("\n== low stock + alerts")
s, up = api("PATCH", f"/catalog/variants/{V}", {"reorder_point": 100, "reorder_qty": 200})
check("A1 reorder point set to 100", s == 200, up)
s, ls = api("GET", "/inventory/low-stock?limit=500")
check("A2 product appears in low stock (50 < 100)", any(r.get("product_variant_id") == V for r in items(ls)), len(items(ls)))
s, ev = api("POST", "/alerts/evaluate")
check("A3 alert evaluation runs", s == 200, ev)
s, al = api("GET", "/alerts?limit=200")
mine = [a for a in items(al) if f"FLW-{T}" in json.dumps(a) or f"Flow Widget {T}" in json.dumps(a)]
check("A4 a low-stock alert was raised for it", len(mine) >= 1, [a.get("title") for a in items(al)[:5]])
if mine:
    s, rd = api("POST", f"/alerts/{mine[0]['id']}/read")
    check("A5 alert can be marked read", s == 200, rd)

print("\n== reports, dashboard, audit")
s, reps = api("GET", "/reports")
for rep in reps:
    s, r = api("GET", f"/reports/{rep['key']}")
    if s != 200:
        check(f"B1 report {rep['key']} runs", False, r)
check("B1 all 13 reports run", all(api("GET", f"/reports/{r['key']}")[0] == 200 for r in reps))
s, ss = api("GET", "/reports/stock_summary")
mine_rows = [r for r in ss.get("rows", []) if r.get("sku") == f"FLW-{T}"]
check("B2 stock summary shows 30 + 20 = 50 across the two godowns", sum(float(r["quantity"]) for r in mine_rows) == 50, mine_rows)
s, pr = api("GET", "/reports/purchase_register")
check("B3 purchase register includes the GRN", grn["grn_number"] in json.dumps(pr), "")
s, db = api("GET", "/dashboard/summary")
check("B4 dashboard summary loads", s == 200 and isinstance(db, dict), db)
s, aud = api("GET", f"/audit-logs/purchase_order/{po['id']}")
check("B5 PO has an audit trail (created/submitted/approved/sent)", s == 200 and len(aud) >= 3, [a.get("action") for a in aud] if isinstance(aud, list) else aud)
s, cl = api("POST", f"/procurement/purchase-orders/{po['id']}/close", {"reason": "Balance not needed"})
check("B6 PO can be short-closed", s == 200 and cl.get("status") in ("closed", "short_closed"), cl)

print(f"\n{passed} passed, {len(failed)} failed")
for f in failed:
    print("  -", f)
sys.exit(1 if failed else 0)
