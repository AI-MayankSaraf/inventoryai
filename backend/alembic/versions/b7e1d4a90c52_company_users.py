"""company users: one login, several companies (BR-AUTH-13)

Revision ID: b7e1d4a90c52
Revises: a3f6c92e0d17
Create Date: 2026-09-23

Three changes, all for the multi-company Owner login:

  * `company_users` — the extra companies a login may switch into, each
    with its own role and status.

    One deliberate divergence from `02_DATABASE_DESIGN.md §3`: the design
    has this table hold *every* membership, the home one included (flagged
    `is_default`). Here it holds only the *additional* ones. The home
    company already lives on `users.company_id` / `users.role_id`, and every
    existing write path (invites, role edits, onboarding, deletes) keeps
    those current. A second copy of the same fact would need a trigger or a
    change to each of those paths to stay in step, and the day it drifted a
    user's role in their own company would depend on which table a query
    happened to read. So: home membership = the `users` row, as today;
    anything beyond it = a row here. `is_default` is not needed because the
    home company is by definition the default.

  * `refresh_tokens.company_id` — which company a refresh token was issued
    for. Without it, `/auth/refresh` rebuilds claims from the `users` row
    and would silently drop a switched session back into the home company
    every 15 minutes, while the screen still shows the other one. NULL means
    "the home company", which is what every existing row already is.

  * A second, SELECT-only RLS policy on `users` (`member_read`) so a
    tenant session in company B can read the row of a person whose home is
    company A but who is a member of B. That is what makes "created by" and
    similar names resolve when that person works in B. It grants SELECT
    only: the existing `tenant_isolation` policy still governs UPDATE and
    DELETE, so B can never edit or remove A's user, and every tenant-side
    user-management query already filters on `company_id` explicitly, so
    B's Users screen does not start listing them either.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7e1d4a90c52"
down_revision: Union[str, Sequence[str], None] = "a3f6c92e0d17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _grant(table: str) -> None:
    """Same guarded grant as `c5d9e2f47a13` — see there for why."""
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'inventoryai_app') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO inventoryai_app';
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'inventoryai_platform') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO inventoryai_platform';
          END IF;
        END $$;
        """
    )


def upgrade() -> None:
    op.create_table(
        "company_users",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("added_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.PrimaryKeyConstraint("user_id", "company_id", name="pk_company_users"),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="ck_company_users_status_valid"),
    )
    op.create_index("ix_company_users_company_id", "company_users", ["company_id"])

    # Strict tenant: a tenant session sees the external members of its own
    # company, nothing else. Login and switching read it through the
    # BYPASSRLS platform role, before any tenant is set.
    op.execute("ALTER TABLE company_users ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON company_users "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )
    _grant("company_users")

    op.add_column(
        "refresh_tokens",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=True),
    )

    op.execute(
        "CREATE POLICY member_read ON users FOR SELECT "
        "USING (EXISTS (SELECT 1 FROM company_users cu WHERE cu.user_id = users.id "
        "AND cu.company_id = current_setting('app.current_company_id', true)::uuid "
        "AND cu.status = 'active'))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS member_read ON users")
    op.drop_column("refresh_tokens", "company_id")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON company_users")
    op.drop_index("ix_company_users_company_id", table_name="company_users")
    op.drop_table("company_users")
