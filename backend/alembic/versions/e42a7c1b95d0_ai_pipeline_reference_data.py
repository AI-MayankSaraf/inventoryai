"""AI pipeline: canonical field vocabulary + the match ladder's index

Revision ID: e42a7c1b95d0
Revises: d81b6c4e9f27
Create Date: 2026-09-23

Two things the pipeline cannot run without, neither of which the earlier
migrations had a reason to create.

**`canonical_fields`** is the controlled vocabulary that learned column
mappings point at (08_AI_DATA_MODEL.md §3). The table existed and was
empty, which meant a mapping had nothing to map *to*. The rows are global
reference data, like `permissions` and `uoms` — not tenant-scoped — and
they are deliberately decoupled from physical column names, so renaming
`supplier_quotation_items.unit_price` one day cannot break a single learned
mapping. `synonyms` is what a proposal matches a supplier's header text
against ("Rate", "Basic Rate", "Rate/Unit" all mean `unit_price`), so it is
part of the data, not documentation.

**`ix_product_variants_search_trgm`** is rung 5 of the match ladder. Without
a GIN trigram index, `similarity(search_text, :q)` is a sequential scan of
every variant in the tenant on every extracted line — fine for the 117 rows
in a demo, not for a real catalogue.

**`product_variants.search_text` was never populated.** The column has
existed since the first migration and nothing ever wrote to it, so rung 5
was matching every line against an empty string and silently finding
nothing. It is filled by a trigger rather than by service code on purpose:
variants are written by the catalogue API, by the seed, by the import path
and now by this pipeline's "new product" action, and a rule that lives in
four places is a rule that is wrong in one of them. A second trigger keeps
it current when a product is renamed, because the text includes the product
and brand names.

Downgrade removes both. Deleting the vocabulary would orphan any learned
mapping field, so the downgrade deletes those first and says so, rather
than failing on a foreign key halfway through.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e42a7c1b95d0"
down_revision: Union[str, Sequence[str], None] = "d81b6c4e9f27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (code, label, group, data_type, required, synonyms)
#
# `applies_to_doc_types` is left NULL for everything that is meaningful on
# any purchase document; only the fields that genuinely belong to one kind
# of document name their types.
_HEADER: list[tuple[str, str, str, bool, list[str]]] = [
    ("supplier_name", "Supplier Name", "string", True, ["supplier", "vendor", "seller", "from", "company name", "m/s"]),
    ("supplier_gstin", "Supplier GSTIN", "gstin_like", False, ["gstin", "gst no", "gst number", "gstin/uin", "tax id"]),
    ("document_number", "Document Number", "string", True, ["invoice no", "quotation no", "quote no", "bill no", "ref no", "document no", "pi no"]),
    ("document_date", "Document Date", "date", True, ["date", "invoice date", "quotation date", "bill date", "dated"]),
    ("valid_until", "Valid Until", "date", False, ["valid till", "validity", "quote valid", "expiry", "valid upto"]),
    ("payment_terms", "Payment Terms", "string", False, ["payment", "terms of payment", "payment term", "credit days"]),
    ("delivery_terms", "Delivery Terms", "string", False, ["delivery", "delivery term", "despatch", "dispatch terms", "lead time"]),
    ("freight_amount", "Freight", "currency", False, ["freight", "transport", "shipping", "carriage", "packing & forwarding"]),
    ("other_charges", "Other Charges", "currency", False, ["other charges", "misc charges", "handling", "loading"]),
    ("subtotal", "Subtotal", "currency", False, ["sub total", "subtotal", "taxable value", "basic amount", "gross amount"]),
    ("tax_amount", "Tax Amount", "currency", False, ["tax", "gst amount", "total gst", "cgst+sgst", "igst"]),
    ("total_amount", "Total Amount", "currency", False, ["total", "grand total", "net amount", "amount payable", "invoice value"]),
    ("against_rfq", "Against RFQ", "string", False, ["rfq", "enquiry no", "against enquiry", "your ref"]),
    ("po_reference", "PO Reference", "string", False, ["po no", "purchase order", "order no", "your order"]),
    ("place_of_supply", "Place of Supply", "string", False, ["place of supply", "pos", "state of supply"]),
    ("bank_account_no", "Bank Account", "string", False, ["a/c no", "account no", "bank account", "account number"]),
    ("bank_ifsc", "IFSC", "string", False, ["ifsc", "ifs code", "rtgs/neft"]),
    ("eway_bill_number", "E-Way Bill", "string", False, ["eway bill", "e-way bill no", "ewb no"]),
    ("vehicle_number", "Vehicle Number", "string", False, ["vehicle no", "truck no", "lorry no", "vehicle"]),
]

_LINE: list[tuple[str, str, str, bool, list[str]]] = [
    ("product_description", "Description", "string", True, ["description", "particulars", "item", "product", "item name", "goods description", "material"]),
    ("supplier_sku", "Supplier Code", "string", False, ["code", "item code", "part no", "sku", "catalogue no", "model no", "article"]),
    ("hsn_code", "HSN Code", "string", False, ["hsn", "hsn/sac", "sac", "hsn code", "tariff"]),
    ("quantity", "Quantity", "number", True, ["qty", "quantity", "nos", "pcs", "no of units"]),
    ("uom", "Unit", "uom", False, ["uom", "unit", "units", "per", "u.o.m"]),
    ("unit_price", "Unit Price", "currency", True, ["rate", "basic rate", "price", "unit rate", "rate/unit", "rate per unit", "unit price"]),
    ("discount_pct", "Discount %", "percent", False, ["disc %", "discount %", "disc", "discount percent"]),
    ("discount_amount", "Discount", "currency", False, ["discount", "disc amount", "less"]),
    ("gst_rate", "GST %", "percent", False, ["gst %", "gst rate", "tax %", "igst %", "cgst %"]),
    ("cess_rate", "Cess %", "percent", False, ["cess", "cess %", "cess rate"]),
    ("line_total", "Line Total", "currency", False, ["amount", "value", "total", "line total", "taxable value"]),
    ("brand", "Brand", "string", False, ["brand", "make", "manufacturer"]),
    ("model", "Model", "string", False, ["model", "model code", "variant"]),
    ("pack_size", "Pack Size", "string", False, ["pack", "pack size", "packing", "std pack"]),
    ("batch_number", "Batch", "string", False, ["batch", "batch no", "lot no", "lot"]),
    ("expiry_date", "Expiry", "date", False, ["expiry", "exp date", "best before", "use by"]),
]

# `canonical_fields.data_type` is CHECKed against this list; `gstin_like`
# above is a note to the reader, not a stored value.
_DATA_TYPE = {"gstin_like": "string"}


def _rows() -> list[tuple[str, str, str, str, bool, list[str]]]:
    out = []
    for group, rows in (("header", _HEADER), ("line", _LINE)):
        for code, label, data_type, required, synonyms in rows:
            out.append((code, label, group, _DATA_TYPE.get(data_type, data_type), required, synonyms))
    return out


def upgrade() -> None:
    for code, label, group, data_type, required, synonyms in _rows():
        op.execute(
            "INSERT INTO canonical_fields (code, label, field_group, data_type, is_required, synonyms) "
            "VALUES ("
            f"  {_lit(code)}, {_lit(label)}, {_lit(group)}, {_lit(data_type)}, {'true' if required else 'false'}, "
            f"  ARRAY[{', '.join(_lit(s) for s in synonyms)}]::text[]"
            ") ON CONFLICT (code) DO NOTHING"
        )

    # `search_text` is the text both sides of the match ladder compare, so
    # it is built the same way for every variant however the row was
    # written. Product and brand names are included because a supplier
    # writes "Pigeon 5L cooker", not the SKU.
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION variant_search_text() RETURNS trigger AS $$
        DECLARE
            product_name text := '';
            brand_name   text := '';
        BEGIN
            SELECT p.name, COALESCE(b.name, p.manufacturer_name, '')
              INTO product_name, brand_name
              FROM products p
              LEFT JOIN brands b ON b.id = p.brand_id
             WHERE p.id = NEW.product_id;

            NEW.search_text := lower(btrim(regexp_replace(
                concat_ws(' ',
                    brand_name, product_name, NEW.variant_name, NEW.sku,
                    NEW.model_code, NEW.mpn, NEW.pack_size),
                '\s+', ' ', 'g')));
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_variant_search_text BEFORE INSERT OR UPDATE ON product_variants "
        "FOR EACH ROW EXECUTE FUNCTION variant_search_text()"
    )
    # Renaming a product has to reach its variants, or the text goes stale
    # in exactly the place a supplier's wording is most likely to match.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION refresh_product_variant_search_text() RETURNS trigger AS $$
        BEGIN
            UPDATE product_variants SET search_text = search_text
             WHERE product_id = NEW.id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_products_search_text AFTER UPDATE OF name, brand_id, manufacturer_name "
        "ON products FOR EACH ROW EXECUTE FUNCTION refresh_product_variant_search_text()"
    )
    # Backfill every existing variant through the same trigger.
    op.execute("UPDATE product_variants SET search_text = NULL")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_product_variants_search_trgm "
        "ON product_variants USING gin (search_text gin_trgm_ops)"
    )
    # Supplier aliases are looked up by *description* as well as by code
    # when a document quotes no code at all.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_supplier_products_desc_trgm "
        "ON supplier_products USING gin (supplier_description gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_products_search_text ON products")
    op.execute("DROP TRIGGER IF EXISTS trg_variant_search_text ON product_variants")
    op.execute("DROP FUNCTION IF EXISTS refresh_product_variant_search_text()")
    op.execute("DROP FUNCTION IF EXISTS variant_search_text()")
    op.execute("DROP INDEX IF EXISTS ix_supplier_products_desc_trgm")
    op.execute("DROP INDEX IF EXISTS ix_product_variants_search_trgm")
    # A mapping field points at a canonical field; removing the vocabulary
    # under a learned mapping would leave it meaningless, so the mappings go
    # first. This is destructive and deliberate — see the module docstring.
    op.execute("DELETE FROM document_schema_mapping_fields")
    op.execute("DELETE FROM canonical_fields")


def _lit(value: str) -> str:
    """Single-quoted SQL literal. These are compile-time constants in this
    file, never user input, but doubling quotes keeps `M/s` and friends from
    breaking the statement."""
    return "'" + value.replace("'", "''") + "'"
