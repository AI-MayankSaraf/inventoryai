"""document_variances.alert_id: add the missing foreign key

Revision ID: e7b3c9d1f5a2
Revises: d4e9f2a6b8c1
Create Date: 2026-09-29

The model has always declared `(company_id, alert_id) -> alerts(company_id,
id)`, but it was declared with `use_alter` and so was never created — and
`d613c7aa375a`, which restored the other 73 constraints lost that way,
missed this one. Without it a variance can point at an alert that doesn't
exist, or at another company's alert. Checked before writing this: no
existing row violates it.

Same shape as the schema's other composite nullable references (e.g.
`ai_extracted_lines.matched_variant_id`). Alerts are never hard-deleted by
the application, so `ON DELETE SET NULL` is a formality here.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e7b3c9d1f5a2"
down_revision: Union[str, Sequence[str], None] = "d4e9f2a6b8c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE document_variances v SET alert_id = NULL WHERE alert_id IS NOT NULL AND NOT EXISTS "
        "(SELECT 1 FROM alerts a WHERE a.id = v.alert_id AND a.company_id = v.company_id)"
    )
    op.execute(
        "ALTER TABLE document_variances ADD CONSTRAINT fk_document_variances_alert_id_alerts "
        "FOREIGN KEY (company_id, alert_id) REFERENCES alerts (company_id, id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE document_variances DROP CONSTRAINT IF EXISTS fk_document_variances_alert_id_alerts")
