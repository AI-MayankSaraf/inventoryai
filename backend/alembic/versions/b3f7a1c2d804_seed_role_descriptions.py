"""Seed descriptions for the seven system roles.

`roles.description` has been NULL since the schema was created, so the
Roles screen rendered an empty line under every role name — the prototype
had descriptions, the database never did. These are the prototype's own
wording, which was written for that screen.

Only NULL descriptions are filled, so re-running this never overwrites
text somebody has since edited.

Revision ID: b3f7a1c2d804
Revises: a71c4e0d95b2
"""
from alembic import op

revision = "b3f7a1c2d804"
down_revision = "a71c4e0d95b2"
branch_labels = None
depends_on = None


DESCRIPTIONS = {
    "owner": "Full access to this company.",
    "purchase_manager": "Sourcing, suppliers and purchase orders.",
    "godown_manager": "Receiving, stock movements and godown operations.",
    "accountant": "Proformas, supplier invoices and payables.",
    "staff": "Godown-scoped day-to-day operations.",
    "viewer": "Read-only access for auditors and advisors.",
    "super_admin": "Platform administration across companies.",
}


def upgrade() -> None:
    for code, text in DESCRIPTIONS.items():
        op.execute(
            "UPDATE roles SET description = "
            f"$${text}$$ WHERE code = $${code}$$ AND description IS NULL"
        )


def downgrade() -> None:
    # Clear only the exact strings this migration wrote, so an edit made
    # afterwards survives a downgrade.
    for code, text in DESCRIPTIONS.items():
        op.execute(
            "UPDATE roles SET description = NULL "
            f"WHERE code = $${code}$$ AND description = $${text}$$"
        )
