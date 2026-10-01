"""One stock posting per document line and batch

Revision ID: f3c8a1d6b902
Revises: e6b2f9d4a715
Create Date: 2026-10-01

`uq_txn_number` was (company, txn_number, variant, godown, txn_type). A GRN
posts one row per accepted line under its own number, so a GRN receiving
two batches of the same product -- the normal case for batch-tracked goods
-- posted two rows with the same key and confirming it failed with a 500.
A transfer moving two batches of one product hit the same wall.

The key now also carries `batch_id` and `source_line_id`, compared with
NULLS NOT DISTINCT so rows without a batch or line still collide exactly as
before. It keeps the original guarantee, one posting per document line,
which is what stops a retried confirm from posting twice.

Downgrade restores the narrower key; it fails if rows exist that only the
wider key allows, which is the correct outcome.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f3c8a1d6b902"
down_revision: Union[str, Sequence[str], None] = "e6b2f9d4a715"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE inventory_transactions DROP CONSTRAINT uq_txn_number")
    op.execute(
        "ALTER TABLE inventory_transactions ADD CONSTRAINT uq_txn_number UNIQUE NULLS NOT DISTINCT "
        "(company_id, txn_number, product_variant_id, godown_id, txn_type, batch_id, source_line_id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE inventory_transactions DROP CONSTRAINT uq_txn_number")
    op.execute(
        "ALTER TABLE inventory_transactions ADD CONSTRAINT uq_txn_number UNIQUE "
        "(company_id, txn_number, product_variant_id, godown_id, txn_type)"
    )
