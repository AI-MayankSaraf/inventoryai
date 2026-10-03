"""An imported RFQ's own number is unique per company

Revision ID: a7d41c3e9b58
Revises: f3c8a1d6b902
Create Date: 2026-10-03

`rfqs.external_reference_number` is the number the customer or marketplace
gave the RFQ (GeM, Tata Projects, IndiaMART). Importing the same enquiry
twice made two RFQs for one request, and nothing stopped it. The number is
now required on import, and this index makes it unique within a company:
trimmed and case-insensitive, so "GEM/2026/B/123 " and "gem/2026/b/123"
are the same enquiry.

Cancelled RFQs are left out, so an import that was cancelled — a wrong
file, a bad mapping — can be imported again under the same number.

Two companies may of course hold the same number: the index starts with
company_id. Upgrade fails if duplicates already exist, which is the correct
outcome — they have to be resolved by a person, not silently.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a7d41c3e9b58"
down_revision: Union[str, Sequence[str], None] = "f3c8a1d6b902"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_rfq_external_reference ON rfqs "
        "(company_id, lower(btrim(external_reference_number))) "
        "WHERE external_reference_number IS NOT NULL AND status <> 'cancelled'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_rfq_external_reference")
