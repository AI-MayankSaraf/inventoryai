"""auth gaps: password reset, per-company email settings, instant revocation

Revision ID: c5d9e2f47a13
Revises: b3f7a1c2d804
Create Date: 2026-09-23

Three additions, all for 06_BUSINESS_RULES.md §1 (BR-AUTH-*):

  * `password_reset_tokens` — the table behind `/auth/forgot-password` and
    `/auth/reset-password`. Only the SHA-256 of each token is stored, the
    same choice `refresh_tokens` makes: a database dump must not hand
    anyone a usable reset link. RLS is enabled with **no policy**
    (deny-all), matching `refresh_tokens`: these rows are looked up before
    any tenant context exists, so only the BYPASSRLS platform role reaches
    them.

  * `users.sessions_revoked_at` — the instant-revocation marker. An access
    token is a self-contained 15-minute JWT, so "existing tokens stop
    working within 60 s" (BR-AUTH-04) cannot be done by deleting anything;
    it needs a marker the request path can compare the token's `iat`
    against. Suspending a company, changing a role or godown scope
    (BR-AUTH-11), resetting or changing a password, and removing a user all
    bump it.

  * `company_email_settings` — per-tenant SMTP, so a company's invitations
    and password-reset mails go out from its own mail server rather than
    one global env-configured relay. The password is stored encrypted with
    pgcrypto (`pgp_sym_encrypt`, key from `APP_SECRET_KEY`) and is never
    returned by the API — reads report only whether one is set.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c5d9e2f47a13"
down_revision: Union[str, Sequence[str], None] = "b3f7a1c2d804"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _grant(table: str) -> None:
    """Grant the runtime roles access if they exist.

    The initial setup's `ALTER DEFAULT PRIVILEGES` does this automatically
    only when the migrating role is the one named there; on a database whose
    tables are owned by `postgres` that was never set up, a new table would
    otherwise be invisible to `inventoryai_app`. Guarded so the migration
    still runs on a database that has no such roles.
    """
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
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ------------------------------------------------ password reset
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("requested_ip", postgresql.INET(), nullable=True),
        sa.Column("requested_user_agent", sa.Text(), nullable=True),
    )
    op.create_index("uq_password_reset_token_hash", "password_reset_tokens", ["token_hash"], unique=True)
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    # Deny-all: reached only through the BYPASSRLS platform role, like
    # `refresh_tokens`. A reset token is looked up before any tenant is known.
    op.execute("ALTER TABLE password_reset_tokens ENABLE ROW LEVEL SECURITY")
    _grant("password_reset_tokens")

    # -------------------------------------------- instant revocation
    op.add_column("users", sa.Column("sessions_revoked_at", sa.DateTime(timezone=True), nullable=True))

    # ------------------------------------------ per-company email/SMTP
    op.create_table(
        "company_email_settings",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False, server_default="console"),
        sa.Column("from_address", sa.Text(), nullable=True),
        sa.Column("from_name", sa.Text(), nullable=True),
        sa.Column("smtp_host", sa.Text(), nullable=True),
        sa.Column("smtp_port", sa.SmallInteger(), nullable=False, server_default="587"),
        sa.Column("smtp_username", sa.Text(), nullable=True),
        sa.Column("smtp_password_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("smtp_use_tls", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        sa.Column("last_test_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("provider IN ('console', 'smtp')", name="ck_company_email_settings_provider_valid"),
        sa.CheckConstraint("smtp_port > 0 AND smtp_port <= 65535", name="ck_company_email_settings_port_valid"),
    )
    op.execute("ALTER TABLE company_email_settings ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON company_email_settings "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )
    _grant("company_email_settings")


def downgrade() -> None:
    op.drop_table("company_email_settings")
    op.drop_column("users", "sessions_revoked_at")
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_index("uq_password_reset_token_hash", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
