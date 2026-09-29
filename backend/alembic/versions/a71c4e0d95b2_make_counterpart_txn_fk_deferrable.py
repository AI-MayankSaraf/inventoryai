"""make inventory_transactions.counterpart_txn_id FK deferrable

Revision ID: a71c4e0d95b2
Revises: 32195ffc8e16
Create Date: 2026-09-17 18:20:00.000000

Two rules in `06_BUSINESS_RULES.md` §4 are in direct tension as the schema
originally stood, and a stock transfer sits exactly where they meet:

* BR-INV-06 -- a transfer writes the `TRANSFER_OUT` / `TRANSFER_IN` pair
  "with `counterpart_txn_id` set both ways".
* BR-INV-03 -- the ledger is append-only, "no UPDATE, no DELETE, enforced
  by trigger". `trg_inventory_transactions_immutable` refuses *every*
  UPDATE, not only one that would change a quantity.

Setting the pointer both ways means each row references the other. With a
self-referencing FK checked immediately, the first INSERT of the pair fails
-- its counterpart does not exist yet -- and the append-only trigger rules
out writing the rows first and linking them afterwards. There is no
ordering that satisfies both rules.

Making the constraint DEFERRABLE INITIALLY IMMEDIATE resolves it without
weakening anything: behaviour is byte-for-byte unchanged for every existing
caller (GRN postings, adjustments, reversals -- none of which defer), and
the transfer path alone issues `SET CONSTRAINTS ... DEFERRED` so its pair is
validated at COMMIT, by which point both rows exist. A dangling pointer is
still impossible; the check simply happens at the end of the transaction
rather than mid-way through it.

`reverses_txn_id` deliberately keeps immediate checking: a reversal points
backwards at a row that already exists, so it has no such ordering problem.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a71c4e0d95b2'
down_revision: Union[str, Sequence[str], None] = '32195ffc8e16'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK = "fk_inventory_transactions_counterpart_txn_id_inventory_ded32bea"


def upgrade() -> None:
    op.execute(f"ALTER TABLE inventory_transactions DROP CONSTRAINT {_FK}")
    op.execute(
        f"ALTER TABLE inventory_transactions ADD CONSTRAINT {_FK} "
        "FOREIGN KEY (company_id, counterpart_txn_id) "
        "REFERENCES inventory_transactions(company_id, id) ON DELETE RESTRICT "
        "DEFERRABLE INITIALLY IMMEDIATE"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE inventory_transactions DROP CONSTRAINT {_FK}")
    op.execute(
        f"ALTER TABLE inventory_transactions ADD CONSTRAINT {_FK} "
        "FOREIGN KEY (company_id, counterpart_txn_id) "
        "REFERENCES inventory_transactions(company_id, id) ON DELETE RESTRICT"
    )
