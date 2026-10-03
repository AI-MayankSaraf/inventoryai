"""
E2E HTTP suite — importing an RFQ from a spreadsheet (BR-RFQ-09, `rfq.import`).

  * preview parses and reports, and writes nothing;
  * a file with problems is refused as a whole on import — no half-imported
    RFQ with some lines missing;
  * a clean file becomes a real draft RFQ: our own sequential number, the
    marketplace's number kept alongside it (never renumbered into ours),
    `created_from = 'imported'`, free-text lines with their units resolved;
  * .xlsx and .csv both work, header names are matched loosely;
  * the permission gate is real, and the RFQ lands in the caller's tenant only.

    python -m scripts.e2e_rfq_import [base_url]
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import urllib.error
import urllib.request
import uuid

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
SFX = uuid.uuid4().hex[:6].upper()

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


def _send(req: urllib.request.Request) -> tuple[int, object]:
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


def call(method: str, path: str, token: str | None = None, body: object = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    return _send(req)


def upload(path: str, token: str, filename: str, content: bytes, fields: dict | None = None) -> tuple[int, object]:
    """multipart/form-data by hand — the same shape the frontend's
    `httpUpload` sends: one `file` part plus plain text fields."""
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for key, value in (fields or {}).items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n".encode() + content + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(BASE + path, data=b"".join(parts), method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", f"Bearer {token}")
    return _send(req)


def login(email: str, password: str) -> str:
    st, body = call("POST", "/auth/login", body={"email": email, "password": password})
    assert st == 200, (email, st, body)
    return body["access_token"]


def db(sql: str, params: dict | None = None) -> list[dict]:
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


def xlsx(rows: list[list]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


GOOD_CSV = (
    "Item Description,Qty,Unit,Rate,Notes\r\n"
    "Basmati Rice 25kg,40,Bag,1850,Premium grade\r\n"
    "Sunflower Oil 1L,120,litre,165.5,\r\n"
    ",,,,\r\n"
    "Toor Dal,15,KG,,\r\n"
).encode("utf-8-sig")


def main() -> int:  # noqa: C901
    owner = login("owner@acme-demo.test", "Demo@12345")
    beta = login("owner@beta-demo.test", "Demo@12345")
    admin = login("platform-admin@inventoryai.test", "Platform@12345")
    acme_id = call("GET", "/auth/me", owner)[1]["company_id"]

    rfqs_before = db("SELECT count(*) AS n FROM rfqs WHERE company_id = :c", {"c": acme_id})[0]["n"]

    print("\n[preview]")
    st, b = upload("/procurement/rfqs/import/preview", owner, "flipkart.csv", GOOD_CSV)
    check("V01 a clean CSV previews", st == 200 and b["errors"] == [] and b["row_count"] == 3, (st, b))
    if st == 200 and b["rows"]:
        r0 = b["rows"][0]
        check("V02 loose headers are matched (Item Description / Qty / Unit / Rate / Notes)",
              r0["description"] == "Basmati Rice 25kg" and r0["quantity"] == 40 and r0["expected_price"] == 1850
              and r0["remarks"] == "Premium grade", r0)
        check("V03 units resolve case-insensitively ('litre', 'KG')",
              all(r["uom_id"] for r in b["rows"]), b["rows"])
        check("V04 a blank price becomes 0, not an error", b["rows"][2]["expected_price"] == 0, b["rows"][2])
    check("V05 preview wrote nothing",
          db("SELECT count(*) AS n FROM rfqs WHERE company_id = :c", {"c": acme_id})[0]["n"] == rfqs_before, "rows")

    st, b = upload("/procurement/rfqs/import/preview", owner, "q.xlsx",
                   xlsx([["Product", "Quantity", "UOM", "Price"], ["Steel Rod 12mm", 200, "Nos", 48.25]]))
    check("V06 an .xlsx previews too", st == 200 and b["row_count"] == 1 and b["errors"] == [], (st, b))

    st, b = upload("/procurement/rfqs/import/preview", owner, "bad.csv",
                   b"Description,Quantity\r\nWidget,5\r\n")
    check("V07 a missing required column is reported by name",
          st == 200 and b["row_count"] == 0 and any("unit" in e.lower() for e in b["errors"]), (st, b))
    st, b = upload("/procurement/rfqs/import/preview", owner, "bad.csv",
                   b"Description,Quantity,UOM\r\nWidget,-5,Nos\r\nGadget,3,Barrels\r\nGizmo,2,Nos\r\n")
    check("V08 bad rows are reported with their row numbers",
          st == 200 and len(b["errors"]) == 2 and "Row 2" in b["errors"][0] and "more than zero" in b["errors"][0]
          and "row 3" in b["errors"][1].lower(), (st, b))
    st, b = upload("/procurement/rfqs/import/preview", owner, "notes.pdf", b"hello")
    check("V09 an unsupported file type is a 400", st == 400, (st, b))
    # .txt is read as delimited text; a single-column file must not crash.
    st, b = upload("/procurement/rfqs/import/preview", owner, "notes.txt", b"hello")
    check("V09b a single-column text file is reported, not a crash", st == 200 and b["errors"], (st, b))
    st, b = upload("/procurement/rfqs/import/preview", owner, "empty.csv", b"")
    check("V10 an empty file is refused with a reason, not a crash",
          st == 400 and "empty" in b.get("detail", "").lower(), (st, b))

    print("\n[import]")
    st, b = upload("/procurement/rfqs/import", owner, "bad.csv",
                   b"Description,Quantity,UOM\r\nWidget,-5,Nos\r\nGizmo,2,Nos\r\n",
                   {"external_source_name": "Flipkart", "external_reference_number": f"BAD-{SFX}"})
    check("I01 a file with any bad row is refused whole", st == 422 and "row" in b.get("detail", "").lower(), (st, b))
    check("I02 …and nothing was created",
          db("SELECT count(*) AS n FROM rfqs WHERE company_id = :c", {"c": acme_id})[0]["n"] == rfqs_before, "rows")

    st, b = upload("/procurement/rfqs/import", owner, "flipkart.csv", GOOD_CSV, {"subject": "no source"})
    check("I03 the source name is required", st in (400, 422), (st, b))

    ext = f"FLPKT-RFQ-{SFX}"
    st, rfq = upload("/procurement/rfqs/import", owner, "flipkart.csv", GOOD_CSV,
                     {"external_source_name": "  Flipkart  ", "external_reference_number": ext})
    check("I04 a clean file imports", st == 201, (st, rfq))
    if st == 201:
        check("I05 it is a draft, marked imported",
              rfq["status"] == "draft" and rfq["created_from"] == "imported", rfq)
        check("I06 it gets our own sequential number, not the marketplace's",
              rfq["rfq_number"] != ext and rfq["rfq_number"].startswith("RFQ"), rfq["rfq_number"])
        check("I07 the marketplace number is kept verbatim alongside",
              rfq["external_reference_number"] == ext and rfq["external_source_name"] == "Flipkart", rfq)
        check("I08 the source file name is kept", rfq["source_file_name"] == "flipkart.csv", rfq)
        check("I09 a default subject names the source", rfq["subject"] == "Imported from Flipkart", rfq["subject"])
        check("I10 every usable line became an item", len(rfq["items"]) == 3, rfq["items"])
        check("I11 estimated value is quantity x price",
              abs(float(rfq["estimated_value"]) - (40 * 1850 + 120 * 165.5)) < 0.01, rfq["estimated_value"])
        st, got = call("GET", f"/procurement/rfqs/{rfq['id']}", owner)
        check("I12 it reads back through the normal RFQ endpoint", st == 200 and got["created_from"] == "imported", st)
        st, lst = call("GET", "/procurement/rfqs", owner)
        items = lst["items"] if isinstance(lst, dict) and "items" in lst else lst
        check("I13 …and appears in the RFQ list", st == 200 and any(r["id"] == rfq["id"] for r in items), st)
        st, other = call("GET", f"/procurement/rfqs/{rfq['id']}", beta)
        check("I14 another tenant cannot see it", st == 404, (st, other))
        st, upd = call("PATCH", f"/procurement/rfqs/{rfq['id']}", owner,
                       {"subject": "Flipkart order — edited", "row_version": rfq["row_version"]})
        check("I15 the imported draft stays editable", st == 200, (st, upd))
        audit = db("SELECT description FROM audit_logs WHERE entity_type = 'rfq' AND entity_id = :id",
                   {"id": rfq["id"]})
        check("I16 the import is audited", any("Imported 3 item" in (a["description"] or "") for a in audit), audit)

        print("\n[enquiry number]")
        st, b = upload("/procurement/rfqs/import", owner, "flipkart.csv", GOOD_CSV, {"external_source_name": "Flipkart"})
        check("I17 the RFQ / enquiry number is required", st == 422 and any(
            e.get("field") == "externalReferenceNumber" for e in b.get("errors", [])), (st, b))
        st, b = upload("/procurement/rfqs/import", owner, "flipkart.csv", GOOD_CSV,
                       {"external_source_name": "Flipkart", "external_reference_number": f"  {ext.lower()} "})
        check("I18 the same number again (any case, spaces) is refused, naming the RFQ",
              st == 409 and rfq["rfq_number"] in b.get("detail", ""), (st, b))
        st, chk = call("GET", f"/procurement/rfqs/reference-check?reference={ext.lower()}", owner)
        check("I19 the as-you-type check finds it", st == 200 and chk["exists"] and chk["rfq_number"] == rfq["rfq_number"], (st, chk))
        st, other_co = upload("/procurement/rfqs/import", beta, "flipkart.csv", GOOD_CSV,
                              {"external_source_name": "Flipkart", "external_reference_number": ext})
        check("I20 another company may use the same number", st == 201, (st, other_co))
        st, _ = call("POST", f"/procurement/rfqs/{rfq['id']}/cancel", owner, {"reason": "wrong file"})
        st, again = upload("/procurement/rfqs/import", owner, "flipkart.csv", GOOD_CSV,
                           {"external_source_name": "Flipkart", "external_reference_number": ext})
        check("I21 once cancelled, the enquiry can be imported again", st == 201, (st, again))

    print("\n[who may import]")
    st, b = upload("/procurement/rfqs/import/preview", admin, "flipkart.csv", GOOD_CSV)
    check("P01 a platform-admin token is refused (no tenant)", st == 403, (st, b))
    perms = {r["code"] for r in db(
        "SELECT r.code FROM role_permissions rp JOIN roles r ON r.id = rp.role_id "
        "JOIN permissions p ON p.id = rp.permission_id WHERE p.code = 'rfq.import' AND r.company_id IS NULL")}
    check("P02 rfq.import is granted to exactly Owner / Purchase Manager / Godown Manager",
          perms == {"owner", "purchase_manager", "godown_manager"}, perms)

    print(f"\n{passed} passed, {len(failed)} failed")
    if failed:
        print("Failed:", *failed, sep="\n  ")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
