"""extend audit_logs action and entity_type vocabularies

Revision ID: efc6b3fb9fdb
Revises: 746390963b46
Create Date: 2026-09-16

Closes a gap between two of the architecture documents, found while
implementing the audit write path.

06_BUSINESS_RULES.md §15 lists what must be audited "without exception",
and that list includes three things the schema in 02_DATABASE_DESIGN.md
had no vocabulary for:

  * "login success **and failure**" — `logged_in` existed, nothing for a
    failed attempt. Recording failures as `logged_in` with a note in the
    description would have made "show me failed logins for this account"
    an unindexed text search over a 7-year table, and would have quietly
    inflated every successful-login count.
  * "**every permission denial**" — no action value at all, and §6 of
    07_RBAC_MATRIX.md builds on these ("repeated denials raise a security
    alert"), so they need to be first-class and countable.
  * "password change/reset" — no action value.

And `entity_type` was missing the master-data tables §15 requires audited
("master-data create/update/delete"): godowns, categories, brands and
UoMs. `permission` is added for denial rows, which describe an attempted
action rather than a row in any table.

Both constraints are widened, never narrowed, so no existing audit row can
become invalid.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'efc6b3fb9fdb'
down_revision: Union[str, Sequence[str], None] = '746390963b46'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ACTIONS_BEFORE = [
    'created', 'updated', 'deleted', 'status_changed', 'approved', 'rejected',
    'sent', 'confirmed', 'cancelled', 'logged_in', 'logged_out', 'impersonated',
    'exported', 'invited', 'invitation_resent', 'invitation_revoked',
    'invitation_accepted', 'removed', 'suspended', 'reactivated',
]
_ACTIONS_ADDED = ['login_failed', 'permission_denied', 'password_changed', 'password_reset']

_ENTITY_TYPES_BEFORE = [
    'purchase_order', 'rfq', 'goods_receipt', 'supplier_quotation',
    'proforma_invoice', 'supplier_invoice', 'product', 'product_variant',
    'supplier', 'inventory_transaction', 'user', 'invitation', 'company',
    'document', 'ai_extraction', 'alert', 'settings',
]
_ENTITY_TYPES_ADDED = [
    'godown', 'category', 'brand', 'uom', 'permission', 'purchase_return',
    'stock_transfer', 'role',
]


def _in_list(values: list[str]) -> str:
    joined = ", ".join(f"'{v}'" for v in values)
    return f"({joined})"


def upgrade() -> None:
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT ck_audit_logs_action_valid")
    op.execute(
        "ALTER TABLE audit_logs ADD CONSTRAINT ck_audit_logs_action_valid "
        f"CHECK (action IN {_in_list(_ACTIONS_BEFORE + _ACTIONS_ADDED)})"
    )
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT ck_audit_logs_entity_type_valid")
    op.execute(
        "ALTER TABLE audit_logs ADD CONSTRAINT ck_audit_logs_entity_type_valid "
        f"CHECK (entity_type IN {_in_list(_ENTITY_TYPES_BEFORE + _ENTITY_TYPES_ADDED)})"
    )


def downgrade() -> None:
    # Narrowing back would fail on any row written with a new value, so
    # remove those rows first — they are, by definition, rows the older
    # schema had no way to represent.
    op.execute(f"DELETE FROM audit_logs WHERE action IN {_in_list(_ACTIONS_ADDED)}")
    op.execute(f"DELETE FROM audit_logs WHERE entity_type IN {_in_list(_ENTITY_TYPES_ADDED)}")

    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT ck_audit_logs_action_valid")
    op.execute(
        "ALTER TABLE audit_logs ADD CONSTRAINT ck_audit_logs_action_valid "
        f"CHECK (action IN {_in_list(_ACTIONS_BEFORE)})"
    )
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT ck_audit_logs_entity_type_valid")
    op.execute(
        "ALTER TABLE audit_logs ADD CONSTRAINT ck_audit_logs_entity_type_valid "
        f"CHECK (entity_type IN {_in_list(_ENTITY_TYPES_BEFORE)})"
    )
