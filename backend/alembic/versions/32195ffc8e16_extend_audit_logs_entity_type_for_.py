"""extend audit_logs entity_type for quotation comparisons

Revision ID: 32195ffc8e16
Revises: f2c8a4d19e30
Create Date: 2026-09-17 16:26:15.586310

Quotation comparisons (`06_BUSINESS_RULES.md` §6, BR-CMP-01..04) is the one
entity this phase audits that neither `b16098bff981` nor `efc6b3fb9fdb`
gave a vocabulary entry to — `supplier_quotation` already existed, but a
comparison (build/override/reset/convert) is a distinct entity from the
quotation rows it draws on. Widened, never narrowed, same as the two prior
extensions of this constraint — no existing row is invalidated.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '32195ffc8e16'
down_revision: Union[str, Sequence[str], None] = 'f2c8a4d19e30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ENTITY_TYPES_BEFORE = [
    'purchase_order', 'rfq', 'goods_receipt', 'supplier_quotation',
    'proforma_invoice', 'supplier_invoice', 'product', 'product_variant',
    'supplier', 'inventory_transaction', 'user', 'invitation', 'company',
    'document', 'ai_extraction', 'alert', 'settings',
    'godown', 'category', 'brand', 'uom', 'permission', 'purchase_return',
    'stock_transfer', 'role',
]
_ENTITY_TYPES_ADDED = ['quotation_comparison']


def _in_list(values: list[str]) -> str:
    joined = ", ".join(f"'{v}'" for v in values)
    return f"({joined})"


def upgrade() -> None:
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT ck_audit_logs_entity_type_valid")
    op.execute(
        "ALTER TABLE audit_logs ADD CONSTRAINT ck_audit_logs_entity_type_valid "
        f"CHECK (entity_type IN {_in_list(_ENTITY_TYPES_BEFORE + _ENTITY_TYPES_ADDED)})"
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM audit_logs WHERE entity_type IN {_in_list(_ENTITY_TYPES_ADDED)}")
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT ck_audit_logs_entity_type_valid")
    op.execute(
        "ALTER TABLE audit_logs ADD CONSTRAINT ck_audit_logs_entity_type_valid "
        f"CHECK (entity_type IN {_in_list(_ENTITY_TYPES_BEFORE)})"
    )
