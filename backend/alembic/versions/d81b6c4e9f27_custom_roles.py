"""custom roles: relax ck_roles_code_valid

Revision ID: d81b6c4e9f27
Revises: c5d9e2f47a13
Create Date: 2026-09-23

`roles.code` was pinned to the seven built-in codes, so a tenant could not
define a role of its own without a schema change. This replaces that list
with a *shape* check — lowercase, starts with a letter, letters/digits/
underscores, 2–40 characters — which is what the code is actually for: a
stable machine-readable handle for a role whose display name people edit.

Two things deliberately stay as they were:

  * `uq_roles_code` still keys on `COALESCE(company_id, <nil uuid>), code`,
    so a tenant's own codes are unique within that tenant and can never
    collide with the system rows (`company_id IS NULL`).
  * `is_system` still marks the built-ins. The API refuses to edit or delete
    those, and refuses to mint a tenant role using one of their codes —
    enforced in the service, because a CHECK constraint cannot look at
    other rows.

Downgrade deletes any custom roles first (and the users on them would block
that with a foreign key, which is the correct outcome: you cannot silently
un-invent a role people are using).
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d81b6c4e9f27"
down_revision: Union[str, Sequence[str], None] = "c5d9e2f47a13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SYSTEM_CODES = "'super_admin', 'owner', 'purchase_manager', 'godown_manager', 'accountant', 'staff', 'viewer'"


def upgrade() -> None:
    op.execute("ALTER TABLE roles DROP CONSTRAINT ck_roles_code_valid")
    op.execute(
        "ALTER TABLE roles ADD CONSTRAINT ck_roles_code_valid "
        "CHECK (code ~ '^[a-z][a-z0-9_]{1,39}$')"
    )
    # A system role belongs to no tenant, and a tenant role is never a
    # system one: the pair only ever appears in those two shapes, and the
    # API's "you cannot edit a built-in" rule reads `is_system` directly.
    op.execute(
        "ALTER TABLE roles ADD CONSTRAINT ck_roles_system_is_global "
        "CHECK ((is_system AND company_id IS NULL) OR (NOT is_system AND company_id IS NOT NULL))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE role_id IN (SELECT id FROM roles WHERE NOT is_system)")
    op.execute("DELETE FROM roles WHERE NOT is_system")
    op.execute("ALTER TABLE roles DROP CONSTRAINT ck_roles_system_is_global")
    op.execute("ALTER TABLE roles DROP CONSTRAINT ck_roles_code_valid")
    op.execute(
        "ALTER TABLE roles ADD CONSTRAINT ck_roles_code_valid "
        f"CHECK (code IN ({_SYSTEM_CODES}))"
    )
