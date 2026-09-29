"""rfq import: remarks field in the mapping vocabulary

Revision ID: c1d8e5a7f3b2
Revises: b7e1d4a90c52
Create Date: 2026-09-26

RFQ import now learns spreadsheet layouts the same way the AI pipeline does
(`document_schema_mappings`, `document_type = 'rfq_import'`), and a saved
mapping can only point at a `canonical_fields` row. Every RFQ column the
import reads already has one (description, quantity, uom, unit price,
supplier code, brand, HSN) except free-text remarks, which quotations never
needed. Data only; idempotent, so it is safe on a database where the row
was added by hand.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c1d8e5a7f3b2"
down_revision: Union[str, Sequence[str], None] = "b7e1d4a90c52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO canonical_fields (code, label, field_group, data_type, is_required, synonyms, "
        " applies_to_doc_types, description) "
        "VALUES ('remarks', 'Remarks', 'line', 'string', false, "
        " ARRAY['remarks', 'remark', 'notes', 'note', 'comment', 'comments', 'instructions']::text[], "
        " ARRAY['rfq_import']::text[], 'Free-text note against a line') "
        "ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM canonical_fields WHERE code = 'remarks' "
        "AND NOT EXISTS (SELECT 1 FROM document_schema_mapping_fields f "
        "                WHERE f.canonical_field_id = canonical_fields.id)"
    )
