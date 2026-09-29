"""RFQ import mapping, AI column assist, embeddings index, semantic match, assistant.

Run with the backend venv (needs openpyxl/Pillow):
    backend/.venv/Scripts/python.exe tests/api_ai_features.py
"""
import os
API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")
PLATFORM_DB = os.environ.get(
    "TEST_PLATFORM_DATABASE_URL", "postgresql://inventoryai_platform:inventoryai_platform_dev@localhost/inventoryai"
)
import io, json, random, string, time, urllib.error, urllib.request, uuid
from openpyxl import Workbook

B = API_URL
T = "".join(random.choices(string.ascii_uppercase, k=4))
passed, failed = 0, []


def check(n, c, info=""):
    global passed
    if c:
        passed += 1; print("  ok  ", n)
    else:
        failed.append(n); print("  FAIL", n, "->", str(info)[:500])


def req(m, p, tok=None, body=None, raw=None, ct=None):
    h = {"content-type": ct or "application/json"}
    if tok:
        h["authorization"] = "Bearer " + tok
    r = urllib.request.Request(B + p, data=raw if raw is not None else (json.dumps(body).encode() if body is not None else None), headers=h, method=m)
    try:
        x = urllib.request.urlopen(r, timeout=180); return x.status, json.loads(x.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300].decode(errors="replace")


def upload(path, tok, name, content, fields=None):
    bd = "----x" + uuid.uuid4().hex
    parts = [f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in (fields or {}).items()]
    parts.append(f'--{bd}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + content + b"\r\n")
    parts.append(f"--{bd}--\r\n".encode())
    return req("POST", path, tok, raw=b"".join(parts), ct="multipart/form-data; boundary=" + bd)


tok = req("POST", "/auth/login", body={"email": "owner@acme-demo.test", "password": "Demo@12345"})[1]["access_token"]
wb = Workbook(); ws = wb.active
for r in [["Shree Ganesh Engineering"], ["REQUEST FOR QUOTATION"], [], ["Sr. No.", "Particulars", "Qty.", "Unit", "Rate (Rs.)", "Make"],
          [1, "MCB 32A Double Pole", 25, "Nos", 450, "Havells"], [2, "PVC Conduit Pipe 25mm", 150, "Mtr", 38, ""], ["", "Total", "", "", "", ""]]:
    ws.append(r)
b = io.BytesIO(); wb.save(b)
s, r = upload("/procurement/rfqs/import/preview", tok, "lh.xlsx", b.getvalue())
check("Q1 RFQ import: letterhead file, Indian headings -> 2 lines, units mapped", s == 200 and r["row_count"] == 2 and not r["errors"] and [x["uom_code"] for x in r["rows"]] == ["Nos", "Metre"], r)
odd = f"#,Wanted {T},Count {T},Measure {T},Budget {T}\n1,MCB 32A DP,25,Nos,450.00\n2,PVC pipe 25mm,150,Mtr,38.50\n".encode()
t = time.time()
s, r = upload("/procurement/rfqs/import/preview", tok, "odd.csv", odd)
check(f"Q2 unknown headings mapped from values / AI ({time.time() - t:.1f}s)", s == 200 and r["column_map"] == {"description": 1, "quantity": 2, "uom": 3, "price": 4}, r.get("column_map"))
s, st = req("GET", "/ai/embeddings/status", tok)
check("Q3 embedding index available", s == 200 and st["configured"] and st["dimensions"] == 768, st)
s, rb = req("POST", "/ai/embeddings/rebuild", tok)
for _ in range(60):
    time.sleep(1)
    s, st = req("GET", "/ai/embeddings/status", tok)
    if not st["rebuilding"]:
        break
check("Q4 index catches up with products added since (incl. today's)", st["pending"] == 0 and not st["last_error"], st)
sup = req("GET", "/catalog/suppliers?limit=1", tok)[1]
sup = (sup.get("items", sup) if isinstance(sup, dict) else sup)[0]
csv = f"{sup['name']}\nQUOTATION\nQuotation No: QK-{T}\n\nS.No,Description,Qty,Unit,Rate\n1,Circuit breaker 32 amp 2 pole,10,Nos,410\n".encode()
s, up = upload("/ai/documents", tok, f"qk-{T}.csv", csv)
check("Q5 quotation upload (S3) works", s == 201, up)
docs = req("GET", "/ai/documents?limit=1", tok)[1]
doc = (docs.get("items", docs) if isinstance(docs, dict) else docs)[0]
s, ex = req("GET", f"/ai/documents/{doc['id']}/extraction", tok)
line = ex["lines"][0]
s, sug = req("GET", f"/ai/lines/{line['id']}/candidates", tok)
c = (sug.get("candidates") or [])
check("Q6 semantic match: 'circuit breaker 32 amp 2 pole' -> Havells MCB 32A", c and c[0].get("sku") == "CAL-MCB32", c[:2])
s, a = req("POST", "/ai/assistant", tok, {"question": "what is out of stock?"})
check("Q7 assistant answers from the database", s == 200 and a.get("intent") not in (None, "unknown"), a)
print(f"\n{passed} passed, {len(failed)} failed", failed)
