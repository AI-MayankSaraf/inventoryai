"""created_at/updated_at on business records, PO notes, updated_at trigger

Revision ID: a8c4e1f7d2b6
Revises: f3c6a8e2b4d7
Create Date: 2026-09-30

Products, variants, godowns, suppliers, RFQs, quotations, comparisons, POs
and GRNs had no record of when they were created or last changed, so the
screens showed nothing. Each gets `created_at`/`updated_at`.

Existing rows are backfilled from the audit trail — the earliest entry for
the row is when it was created, the latest when it last changed — falling
back to the document's own date, and only then to now.

`updated_at` is maintained by one trigger function, `set_updated_at()`,
attached to every table that has the column (including the ones that had
it already but nothing kept it current: companies, users, ...). A trigger
rather than application code so a raw SQL `UPDATE` keeps it right too.

Also adds `purchase_orders.notes` for free-text notes on a PO.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a8c4e1f7d2b6"
down_revision: Union[str, Sequence[str], None] = "f3c6a8e2b4d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# table -> the document's own date, used when the audit trail has no entry
NEW_TIMESTAMPS = {
    "products": None,
    "product_variants": None,
    "godowns": None,
    "suppliers": None,
    "rfqs": "rfq_date",
    "supplier_quotations": "quotation_date",
    "quotation_comparisons": None,
    "purchase_orders": "po_date",
    "goods_receipts": "grn_date",
}


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            -- Leave an explicit change of updated_at alone (backfills, imports).
            IF NEW.updated_at IS NOT DISTINCT FROM OLD.updated_at THEN
                NEW.updated_at := now();
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )

    for table, doc_date in NEW_TIMESTAMPS.items():
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN created_at timestamptz, ADD COLUMN updated_at timestamptz"
        )
        fallback = f"{doc_date}::timestamptz" if doc_date else "NULL"
        op.execute(
            f"""
            UPDATE {table} t SET
                created_at = COALESCE(a.first_at, {fallback}, now()),
                updated_at = COALESCE(a.last_at, a.first_at, {fallback}, now())
            FROM (SELECT x.id, min(l.created_at) AS first_at, max(l.created_at) AS last_at
                  FROM {table} x LEFT JOIN audit_logs l ON l.entity_id = x.id
                  GROUP BY x.id) a
            WHERE a.id = t.id
            """
        )
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN created_at SET DEFAULT now(), ALTER COLUMN created_at SET NOT NULL, "
            f"ALTER COLUMN updated_at SET DEFAULT now(), ALTER COLUMN updated_at SET NOT NULL"
        )

    op.execute("ALTER TABLE purchase_orders ADD COLUMN notes text")

    # One trigger per table that has updated_at, new and old alike.
    op.execute(
        """
        DO $$
        DECLARE t text;
        BEGIN
            FOR t IN SELECT c.table_name FROM information_schema.columns c
                     JOIN information_schema.tables tb ON tb.table_name = c.table_name
                          AND tb.table_schema = c.table_schema AND tb.table_type = 'BASE TABLE'
                     WHERE c.table_schema = 'public' AND c.column_name = 'updated_at'
            LOOP
                EXECUTE format('DROP TRIGGER IF EXISTS trg_%s_updated_at ON %I', t, t);
                EXECUTE format(
                    'CREATE TRIGGER trg_%s_updated_at BEFORE UPDATE ON %I '
                    'FOR EACH ROW EXECUTE FUNCTION set_updated_at()', t, t);
            END LOOP;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE r record;
        BEGIN
            FOR r IN SELECT tgname, tgrelid::regclass AS tbl FROM pg_trigger
                     WHERE tgname LIKE 'trg\\_%\\_updated\\_at' AND NOT tgisinternal
            LOOP
                EXECUTE format('DROP TRIGGER %I ON %s', r.tgname, r.tbl);
            END LOOP;
        END
        $$
        """
    )
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    op.execute("ALTER TABLE purchase_orders DROP COLUMN IF EXISTS notes")
    for table in NEW_TIMESTAMPS:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS created_at, DROP COLUMN IF EXISTS updated_at")
