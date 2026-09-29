"""rfq import

Revision ID: a3f6c92e0d17
Revises: e42a7c1b95d0
Create Date: 2026-09-23

Closes the gap the audit found: BR-RFQ-09, `07_RBAC_MATRIX.md`'s already-
documented `rfq.import` permission, and `02_DATABASE_DESIGN.md`'s import
columns were all designed and never built. `rfqs.created_from`'s CHECK only
allowed `'manual'`/`'low_stock'`, so the database would have rejected an
imported row even if application code had tried to write one.

Three new nullable columns on `rfqs`, all `NULL` for every existing row and
for every manually-created one going forward:

  * `external_source_name` — where it came from ("Flipkart"), free text
    rather than an enum: the source is a label for people, not a value
    anything branches on.
  * `external_reference_number` — the marketplace's own RFQ number,
    preserved verbatim (BR-RFQ-09). Deliberately a *second* column rather
    than overloading `rfq_number`: our own numbering series
    (`document_sequences`/`allocate()`) is what every other screen assumes
    is present, sequential and ours — an imported RFQ still gets a real
    allocated `rfq_number`, and carries the supplier's number alongside it.
  * `source_file_name` — the uploaded file's original name, for the
    person reviewing later ("where did this come from"). Not a foreign key
    into a document store: RFQ import does not depend on the AI pipeline's
    S3-backed document table, on purpose (see the RFQ-import phase-state
    note) — the raw file is not retained server-side, only its name.

`rfq.import` is added to `permissions` and granted to the same three system
roles that already hold `rfq.create` (Owner, Purchase Manager, Godown
Manager) — those roles are single global rows (`roles.company_id IS NULL`),
so this applies to every tenant immediately, matching how `rfq.create`
itself already covers every tenant without a backfill.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a3f6c92e0d17"
down_revision: Union[str, Sequence[str], None] = "e42a7c1b95d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("rfqs", sa.Column("external_source_name", sa.Text(), nullable=True))
    op.add_column("rfqs", sa.Column("external_reference_number", sa.Text(), nullable=True))
    op.add_column("rfqs", sa.Column("source_file_name", sa.Text(), nullable=True))

    # Raw SQL rather than op.drop_constraint/create_check_constraint: the
    # metadata naming convention would prefix the name a second time
    # ("ck_rfqs_ck_rfqs_...") and the drop would miss the real constraint.
    op.execute("ALTER TABLE rfqs DROP CONSTRAINT ck_rfqs_created_from_valid")
    op.execute(
        "ALTER TABLE rfqs ADD CONSTRAINT ck_rfqs_created_from_valid "
        "CHECK (created_from IN ('manual', 'low_stock', 'imported'))"
    )

    op.execute(
        "INSERT INTO permissions (code, module, description) "
        "VALUES ('rfq.import', 'RFQ', 'Import an RFQ from an uploaded file') "
        "ON CONFLICT (code) DO NOTHING"
    )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT r.id, p.id FROM roles r, permissions p "
        "WHERE r.company_id IS NULL AND r.code IN ('owner', 'purchase_manager', 'godown_manager') "
        "AND p.code = 'rfq.import' "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id = "
        "(SELECT id FROM permissions WHERE code = 'rfq.import')"
    )
    op.execute("DELETE FROM permissions WHERE code = 'rfq.import'")

    # Keep imported RFQs, just stop calling them imported.
    op.execute("UPDATE rfqs SET created_from = 'manual' WHERE created_from = 'imported'")
    op.execute("ALTER TABLE rfqs DROP CONSTRAINT ck_rfqs_created_from_valid")
    op.execute(
        "ALTER TABLE rfqs ADD CONSTRAINT ck_rfqs_created_from_valid "
        "CHECK (created_from IN ('manual', 'low_stock'))"
    )

    op.drop_column("rfqs", "source_file_name")
    op.drop_column("rfqs", "external_reference_number")
    op.drop_column("rfqs", "external_source_name")
