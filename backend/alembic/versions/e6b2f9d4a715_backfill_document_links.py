"""Backfill document_links for records already made from documents

Revision ID: e6b2f9d4a715
Revises: d5a1e8c3f604
Create Date: 2026-09-30

`document_links` existed but nothing wrote it. Approving an extraction now
records a `source` link from the new quotation, proforma or invoice back to
the file it was read from (review_service.approve). This adds the same
link for every record approved before that, and for business records that
carry a `document_id` of their own, so the "Source document" card and the
delete guard (a document behind a business record cannot be deleted) apply
to old data too.

Downgrade removes only the rows this migration could have written: links
with role `source`, which is all anything writes so far.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e6b2f9d4a715"
down_revision: Union[str, Sequence[str], None] = "d5a1e8c3f604"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO document_links (id, company_id, document_id, linked_type, linked_id, link_role, linked_by, linked_at)
        SELECT gen_random_uuid(), r.company_id, r.document_id, r.promoted_to_type, r.promoted_to_id, 'source',
               COALESCE(r.reviewed_by, d.uploaded_by), COALESCE(r.reviewed_at, now())
        FROM ai_extraction_results r
        JOIN documents d ON d.id = r.document_id
        WHERE r.promoted_to_id IS NOT NULL
          AND r.promoted_to_type IN ('supplier_quotation', 'proforma_invoice', 'supplier_invoice')
          AND COALESCE(r.reviewed_by, d.uploaded_by) IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    for table, linked_type in (
        ("supplier_quotations", "supplier_quotation"),
        ("proforma_invoices", "proforma_invoice"),
        ("supplier_invoices", "supplier_invoice"),
    ):
        op.execute(
            f"""
            INSERT INTO document_links (id, company_id, document_id, linked_type, linked_id, link_role, linked_by)
            SELECT gen_random_uuid(), t.company_id, t.document_id, '{linked_type}', t.id, 'source',
                   COALESCE(t.approved_by, d.uploaded_by)
            FROM {table} t
            JOIN documents d ON d.id = t.document_id
            WHERE t.document_id IS NOT NULL AND COALESCE(t.approved_by, d.uploaded_by) IS NOT NULL
            ON CONFLICT DO NOTHING
            """
        )


def downgrade() -> None:
    op.execute("DELETE FROM document_links WHERE link_role = 'source'")
