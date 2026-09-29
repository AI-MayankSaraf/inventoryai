"""extend audit_logs action vocabulary for procurement workflow

Revision ID: f2c8a4d19e30
Revises: 8ba3759b0926
Create Date: 2026-09-17

06_BUSINESS_RULES.md §15's audit-without-exception list names three
transitions the RFQ -> PO -> GRN loop needs that `efc6b3fb9fdb` didn't add:
"PO create/update/approve/send/**cancel/close**" (close/short-close had no
action value), a PO moving to `pending_approval` (`po.submit` -- "submitted"
names the transition the way `sent`/`confirmed`/`cancelled` already do
rather than overloading `status_changed`), and "**GRN confirm and
reverse**" (confirm already has an action; reverse did not -- BR-GRN-08's
correction-via-reversing-GRN needs to be distinguishable in the trail from
an ordinary cancel).

Widened, never narrowed, same as `efc6b3fb9fdb` -- no existing row is
invalidated.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'f2c8a4d19e30'
down_revision: Union[str, Sequence[str], None] = '8ba3759b0926'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ACTIONS_BEFORE = [
    'created', 'updated', 'deleted', 'status_changed', 'approved', 'rejected',
    'sent', 'confirmed', 'cancelled', 'logged_in', 'logged_out', 'impersonated',
    'exported', 'invited', 'invitation_resent', 'invitation_revoked',
    'invitation_accepted', 'removed', 'suspended', 'reactivated',
    'login_failed', 'permission_denied', 'password_changed', 'password_reset',
]
_ACTIONS_ADDED = ['submitted', 'closed', 'reversed']


def _in_list(values: list[str]) -> str:
    joined = ", ".join(f"'{v}'" for v in values)
    return f"({joined})"


def upgrade() -> None:
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT ck_audit_logs_action_valid")
    op.execute(
        "ALTER TABLE audit_logs ADD CONSTRAINT ck_audit_logs_action_valid "
        f"CHECK (action IN {_in_list(_ACTIONS_BEFORE + _ACTIONS_ADDED)})"
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM audit_logs WHERE action IN {_in_list(_ACTIONS_ADDED)}")
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT ck_audit_logs_action_valid")
    op.execute(
        "ALTER TABLE audit_logs ADD CONSTRAINT ck_audit_logs_action_valid "
        f"CHECK (action IN {_in_list(_ACTIONS_BEFORE)})"
    )
