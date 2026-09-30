"""Every GET endpoint, list and detail, as the tenant owner and the platform admin."""
import os
API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")
PLATFORM_DB = os.environ.get(
    "TEST_PLATFORM_DATABASE_URL", "postgresql://inventoryai_platform:inventoryai_platform_dev@localhost/inventoryai"
)
import json, re, urllib.error, urllib.request

B = API_URL


def call(p, tok):
    r = urllib.request.Request(B + p, headers={"authorization": "Bearer " + tok})
    try:
        x = urllib.request.urlopen(r, timeout=60)
        raw = x.read()
        return x.status, (json.loads(raw) if raw and x.headers.get("content-type", "").startswith("application/json") else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200].decode(errors="replace")


def login(email, pw):
    r = urllib.request.Request(B + "/auth/login", data=json.dumps({"email": email, "password": pw}).encode(), headers={"content-type": "application/json"})
    return json.load(urllib.request.urlopen(r))["access_token"]


def items(x):
    return x.get("items", []) if isinstance(x, dict) else (x if isinstance(x, list) else [])


spec = json.load(urllib.request.urlopen(B + "/openapi.json"))
gets = sorted(p for p, v in spec["paths"].items() if "get" in v)
owner = login("owner@acme-demo.test", "Demo@12345")
plat = login("platform-admin@inventoryai.test", "Platform@12345")

# list endpoint -> sample id, for filling {param} in detail endpoints
samples = {}
bad = []
for p in gets:
    if "{" in p:
        continue
    for who, tok in (("owner", owner), ("platform", plat)):
        want_platform = p.startswith("/platform")
        if (who == "platform") != want_platform and p not in ("/auth/me", "/auth/me/companies", "/health", "/"):
            continue
        s, body = call(p + ("?limit=5" if p not in ("/health", "/") else ""), tok)
        if s != 200:
            bad.append((who, p, s, body))
        for it in items(body)[:1]:
            if isinstance(it, dict) and it.get("id"):
                samples[p] = it
print(f"list endpoints checked; failures: {len(bad)}")

PARAM_SOURCE = {
    "rfq_id": "/procurement/rfqs", "quotation_id": "/procurement/quotations", "comparison_id": "/procurement/comparisons",
    "po_id": "/procurement/purchase-orders", "grn_id": "/procurement/goods-receipts", "proforma_id": "/proforma-invoices",
    "invoice_id": "/supplier-invoices", "return_id": "/purchase-returns", "supplier_id": "/catalog/suppliers",
    "product_id": "/catalog/products", "variant_id": "/catalog/variants", "product_variant_id": "/catalog/variants",
    "godown_id": "/catalog/godowns", "document_id": "/ai/documents", "mapping_id": "/ai/schema-mappings",
    "user_id": "/users", "role_id": "/roles", "alert_id": "/alerts", "company_id": "/platform/companies",
    "transfer_id": "/inventory/transfers", "txn_id": "/inventory/transactions",
}
# The newest upload may still be queued for the worker, or be a file that
# could not be read — neither has an extraction to fetch. Sample one that
# has been read.
_s, _read = call("/ai/documents?status=review_required&limit=1", owner)
_read = _read.get("items", _read) if isinstance(_read, dict) else _read
if _s == 200 and _read:
    samples["/ai/documents"] = _read[0]

skipped, checked = [], 0
for p in gets:
    params = re.findall(r"{(\w+)}", p)
    if not params:
        continue
    path = p
    ok = True
    for prm in params:
        if prm == "report_key":
            path = path.replace("{report_key}", "stock_summary")
            continue
        if prm == "entity_type":
            path = path.replace("{entity_type}", "purchase_order")
            continue
        if prm == "entity_id":
            src = samples.get("/procurement/purchase-orders")
            path = path.replace("{entity_id}", src["id"]) if src else path
            continue
        src = samples.get(PARAM_SOURCE.get(prm, ""))
        if not src:
            ok = False
            break
        path = path.replace("{" + prm + "}", src["id"])
    if not ok or "{" in path:
        skipped.append(p)
        continue
    tok = plat if p.startswith("/platform") else owner
    s, body = call(path, tok)
    checked += 1
    # 307 = presigned redirect for file download; followed automatically by urllib
    if s not in (200,):
        bad.append(("owner" if tok == owner else "platform", p, s, body))
print(f"detail endpoints checked: {checked}; skipped (no sample / needs a specific id): {len(skipped)}")
# Refusals that are correct behaviour, not failures.
EXPECTED = {
    "/inventory/batches": "needs ?product_variant_id=",
    "/catalog/suppliers/{supplier_id}/price-history": "needs ?product_variant_id=",
    "/supplier-portal/me": "a staff token is refused by the Supplier Portal",
}
real = [b for b in bad if b[1] not in EXPECTED]
for b in bad:
    if b[1] in EXPECTED:
        print(f"  expected {b[2]} {b[1]} ({EXPECTED[b[1]]})")
for b in real:
    print("  FAIL", b)
print("skipped:", skipped)
print(f"\n{len(real)} unexpected failure(s)")

import sys
sys.exit(1 if real else 0)
