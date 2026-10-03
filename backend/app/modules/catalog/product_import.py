"""
Products / SKUs from an Excel or CSV file — the "Import Excel" button on
the Products screen (`POST /catalog/products/import`, 04_API_SPECIFICATION
§2.5).

One row is one product with one SKU, the same shape the Add Product form
creates. The flow is preview first, then import:

  * `preview` reads the file, finds the heading row (a letterhead above it
    is skipped), maps the columns by their headings and checks every row.
    It writes nothing.
  * `import_file` runs exactly the same checks and, only when no row has an
    error, creates everything in one transaction. A file is imported whole
    or not at all — a half-imported catalogue is worse than none, because
    the person cannot tell which rows made it.

Brands and categories named in the file are matched to existing ones by
name, ignoring case; ones that do not exist yet are created, but only for
someone allowed to manage masters (`master.manage`). Without it those rows
are errors, so a Staff user cannot grow the master lists by accident.

Opening stock is not imported: it is a ledger posting with a godown, and
goes through Inventory → New Transaction like any other movement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID, uuid4

from fastapi import Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.errors import CODE_VALIDATION, ApiError
from app.core.security import AccessTokenClaims
from app.modules.procurement.rfq_import import _parse_number, header_key, read_sheets

MAX_ROWS = 5000

#: field -> (label, required, heading synonyms after `header_key`).
FIELDS: dict[str, tuple[str, bool, tuple[str, ...]]] = {
    "sku": ("SKU", True, ("sku", "sku code", "item code", "product code", "code", "part no", "part number", "article code")),
    "name": ("Product Name", True, ("product name", "name", "item name", "product", "item", "item description", "description")),
    "unit": ("Unit", True, ("unit", "uom", "unit of measure", "units")),
    "brand": ("Brand", False, ("brand", "make", "brand name", "manufacturer")),
    "category": ("Category", False, ("category", "category name", "group", "item group", "product category")),
    "hsn": ("HSN Code", False, ("hsn", "hsn code", "hsn sac", "hsn sac code", "sac")),
    "gst": ("GST %", False, ("gst", "gst rate", "gst percent", "tax", "tax rate", "igst")),
    "purchase_price": ("Purchase Price", False, ("purchase price", "cost", "cost price", "buying price", "purchase rate")),
    "sale_price": ("Sale Price", False, ("sale price", "selling price", "sales price", "sale rate", "price", "rate")),
    "mrp": ("MRP", False, ("mrp", "max retail price")),
    "reorder_point": ("Reorder Point", False, ("reorder point", "reorder level", "min stock", "minimum stock", "rol")),
    "reorder_qty": ("Reorder Qty", False, ("reorder qty", "reorder quantity", "order qty", "roq")),
    "barcode": ("Barcode", False, ("barcode", "ean", "upc", "bar code")),
    "tracking": ("Tracking", False, ("tracking", "tracking type", "batch serial")),
    "lead_time_days": ("Lead Time (days)", False, ("lead time", "lead time days", "lead days")),
}

TEMPLATE_HEADERS = [label for label, _req, _syn in FIELDS.values()]
TEMPLATE_EXAMPLE = [
    "PC-FR-1.5-RD", "Polycab FR PVC Wire 1.5 sq mm Red (90 m)", "Nos", "Polycab", "Wires & Cables",
    "85444999", "18", "1310", "1450", "1600", "20", "50", "", "none", "7",
]

_TRACKING = {"": "none", "none": "none", "no": "none", "batch": "batch", "lot": "batch", "serial": "serial"}


@dataclass
class ImportRow:
    source_row: int
    values: dict
    errors: list[str] = field(default_factory=list)


@dataclass
class ImportCheck:
    rows: list[ImportRow]
    columns: dict[str, Optional[str]]  # field -> heading it was read from
    header_row: Optional[int]
    file_errors: list[str]
    new_brands: list[str]
    new_categories: list[str]

    @property
    def error_count(self) -> int:
        return len(self.file_errors) + sum(1 for r in self.rows if r.errors)

    def as_dict(self) -> dict:
        return {
            "header_row": self.header_row,
            "columns": [
                {"field": f, "label": FIELDS[f][0], "required": FIELDS[f][1], "header": self.columns.get(f)}
                for f in FIELDS
            ],
            "row_count": len(self.rows),
            "valid_count": sum(1 for r in self.rows if not r.errors),
            "error_count": self.error_count,
            "file_errors": self.file_errors,
            "row_errors": [{"row": r.source_row, "sku": r.values.get("sku", ""), "errors": r.errors} for r in self.rows if r.errors][:200],
            "sample": [
                {"row": r.source_row, **{k: r.values.get(k) for k in ("sku", "name", "unit", "brand", "category", "gst", "purchase_price", "sale_price")}}
                for r in self.rows[:20]
            ],
            "new_brands": self.new_brands,
            "new_categories": self.new_categories,
        }


def _find_header(grid: list[list[str]]) -> Optional[tuple[int, dict[str, int]]]:
    """The first row (of the top 15) that names at least two known columns."""
    for index, row in enumerate(grid[:15]):
        found: dict[str, int] = {}
        for col, cell in enumerate(row):
            key = header_key(cell)
            if not key:
                continue
            for fld, (_label, _req, synonyms) in FIELDS.items():
                if fld not in found and key in synonyms:
                    found[fld] = col
                    break
        if len(found) >= 2:
            return index, found
    return None


async def check(session: AsyncSession, *, claims: AccessTokenClaims, filename: str, content: bytes) -> ImportCheck:
    c = claims.company_id
    sheets = read_sheets(filename, content)
    sheet = next(((name, grid) for name, grid in sheets if _find_header(grid)), None)
    if sheet is None:
        return ImportCheck([], {}, None, [
            "No heading row was found. The first rows must include column headings such as "
            "SKU, Product Name and Unit — download the template to see the layout."
        ], [], [])
    _sheet_name, grid = sheet
    header_index, mapping = _find_header(grid)  # type: ignore[misc]
    headings = grid[header_index]
    columns = {f: headings[i] for f, i in mapping.items()}
    missing = [FIELDS[f][0] for f, (_l, required, _s) in FIELDS.items() if required and f not in mapping]
    if missing:
        return ImportCheck([], columns, header_index + 1, [f"Missing required column(s): {', '.join(missing)}"], [], [])

    units = {
        r["key"]: r["id"]
        for r in (
            await session.execute(
                text(
                    "SELECT id, lower(code) AS key FROM uoms WHERE (company_id = :c OR company_id IS NULL) AND is_active "
                    "UNION SELECT id, lower(name) FROM uoms WHERE (company_id = :c OR company_id IS NULL) AND is_active"
                ),
                {"c": c},
            )
        ).mappings()
    }
    brands = {r["key"]: r["id"] for r in (await session.execute(
        text("SELECT id, lower(btrim(name)) AS key FROM brands WHERE company_id = :c AND deleted_at IS NULL"), {"c": c}
    )).mappings()}
    categories = {r["key"]: r["id"] for r in (await session.execute(
        text("SELECT id, lower(btrim(name)) AS key FROM categories WHERE company_id = :c AND deleted_at IS NULL"), {"c": c}
    )).mappings()}
    taken_skus = {r[0] for r in (await session.execute(
        text("SELECT upper(sku) FROM product_variants WHERE company_id = :c AND deleted_at IS NULL"), {"c": c}
    )).all()}

    can_add_masters = "master.manage" in claims.permissions
    new_brands: dict[str, str] = {}
    new_categories: dict[str, str] = {}
    seen: dict[str, int] = {}
    rows: list[ImportRow] = []

    for offset, raw in enumerate(grid[header_index + 1:], start=header_index + 2):
        cell = lambda f: (raw[mapping[f]].strip() if f in mapping and mapping[f] < len(raw) else "")  # noqa: E731
        if not any(cell(f) for f in mapping):
            continue  # blank line
        if len(rows) >= MAX_ROWS:
            return ImportCheck(rows, columns, header_index + 1, [f"The file has more than {MAX_ROWS} rows; split it."], [], [])
        row = ImportRow(offset, {})
        v = row.values
        v["sku"] = cell("sku").upper()
        v["name"] = cell("name")
        v["unit"] = cell("unit")
        for f in ("brand", "category", "hsn", "barcode"):
            v[f] = cell(f) or None

        if not v["sku"]:
            row.errors.append("SKU is missing")
        elif v["sku"] in taken_skus:
            row.errors.append(f"SKU {v['sku']} already exists in your catalogue")
        elif v["sku"] in seen:
            row.errors.append(f"SKU {v['sku']} is repeated (also on row {seen[v['sku']]})")
        else:
            seen[v["sku"]] = offset
        if not v["name"]:
            row.errors.append("Product Name is missing")
        elif len(v["name"]) > 500:
            row.errors.append("Product Name is longer than 500 characters")
        if not v["unit"]:
            row.errors.append("Unit is missing")
        elif v["unit"].lower() not in units:
            row.errors.append(f"Unit '{v['unit']}' is not one of your units (Settings → Units)")
        else:
            v["uom_id"] = units[v["unit"].lower()]

        for f, default in (("gst", 18.0), ("purchase_price", 0.0), ("sale_price", 0.0), ("mrp", 0.0),
                           ("reorder_point", 0.0), ("reorder_qty", 0.0), ("lead_time_days", None)):
            raw_value = cell(f).rstrip("%").strip()
            if not raw_value:
                v[f] = default
                continue
            number = _parse_number(raw_value)
            if number is None or number < 0:
                row.errors.append(f"{FIELDS[f][0]} '{cell(f)}' is not a valid number")
                v[f] = default
            else:
                v[f] = number
        if v["gst"] is not None and v["gst"] > 28:
            row.errors.append(f"GST % {v['gst']:g} is above 28")
        if v["lead_time_days"] is not None:
            v["lead_time_days"] = int(v["lead_time_days"])

        tracking = _TRACKING.get(cell("tracking").lower())
        if tracking is None:
            row.errors.append(f"Tracking '{cell('tracking')}' must be none, batch or serial")
        v["tracking"] = tracking or "none"

        for f, known, pending, noun in (("brand", brands, new_brands, "Brand"), ("category", categories, new_categories, "Category")):
            name = v[f]
            if not name:
                continue
            key = name.strip().lower()
            if key in known:
                v[f + "_id"] = known[key]
            elif can_add_masters:
                pending.setdefault(key, name.strip())
            else:
                row.errors.append(f"{noun} '{name}' does not exist, and your role cannot add new ones")
        rows.append(row)

    file_errors = [] if rows else ["The file has no product rows under the headings."]
    return ImportCheck(rows, columns, header_index + 1, file_errors, sorted(new_brands.values()), sorted(new_categories.values()))


async def import_file(
    session: AsyncSession, *, claims: AccessTokenClaims, filename: str, content: bytes, request: Request
) -> dict:
    result = await check(session, claims=claims, filename=filename, content=content)
    if result.error_count:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_VALIDATION,
            f"Nothing was imported: {result.error_count} problem(s) in the file. Preview it to see them.",
        )
    c = claims.company_id

    created_masters: dict[str, dict[str, UUID]] = {"brand": {}, "category": {}}
    for kind, table, names in (("brand", "brands", result.new_brands), ("category", "categories", result.new_categories)):
        for name in names:
            new_id = uuid4()
            await session.execute(
                text(f"INSERT INTO {table} (id, company_id, name, is_active) VALUES (:id, :c, :name, true)"),
                {"id": new_id, "c": c, "name": name},
            )
            created_masters[kind][name.lower()] = new_id
            await audit.record(
                session, entity_type=kind, action="created", claims=claims, entity_id=new_id,
                entity_label=name, description=f"Created by product import ({filename})", request=request,
            )

    for row in result.rows:
        v = row.values
        brand_id = v.get("brand_id") or (created_masters["brand"].get(v["brand"].strip().lower()) if v["brand"] else None)
        category_id = v.get("category_id") or (created_masters["category"].get(v["category"].strip().lower()) if v["category"] else None)
        product_id, variant_id = uuid4(), uuid4()
        await session.execute(
            text(
                "INSERT INTO products (id, company_id, name, brand_id, category_id, hsn_code, gst_rate, cess_rate, "
                " tracking_type, base_uom_id, is_active) "
                "VALUES (:id, :c, :name, :brand, :category, :hsn, :gst, 0, :tracking, :uom, true)"
            ),
            {"id": product_id, "c": c, "name": v["name"], "brand": brand_id, "category": category_id,
             "hsn": v["hsn"], "gst": v["gst"], "tracking": v["tracking"], "uom": v["uom_id"]},
        )
        await session.execute(
            text(
                "INSERT INTO product_variants (id, company_id, product_id, sku, uom_id, barcode, hsn_code, gst_rate, "
                " purchase_price, sale_price, mrp, reorder_point, reorder_qty, lead_time_days, is_active) "
                "VALUES (:id, :c, :p, :sku, :uom, :barcode, :hsn, :gst, :pp, :sp, :mrp, :rp, :rq, :lead, true)"
            ),
            {"id": variant_id, "c": c, "p": product_id, "sku": v["sku"], "uom": v["uom_id"], "barcode": v["barcode"],
             "hsn": v["hsn"], "gst": v["gst"], "pp": v["purchase_price"], "sp": v["sale_price"], "mrp": v["mrp"],
             "rp": v["reorder_point"], "rq": v["reorder_qty"], "lead": v["lead_time_days"]},
        )
        await audit.record(
            session, entity_type="product", action="created", claims=claims, entity_id=product_id,
            entity_label=v["name"], description=f"Imported from {filename} (row {row.source_row}, SKU {v['sku']})",
            request=request,
        )

    # One transaction: every row, or — if anything above failed — none.
    await session.commit()
    return {
        "imported": len(result.rows),
        "new_brands": result.new_brands,
        "new_categories": result.new_categories,
    }


def template_csv() -> str:
    def cell(s: str) -> str:
        return f'"{s}"' if "," in s else s
    return "\r\n".join([",".join(map(cell, TEMPLATE_HEADERS)), ",".join(map(cell, TEMPLATE_EXAMPLE))]) + "\r\n"
