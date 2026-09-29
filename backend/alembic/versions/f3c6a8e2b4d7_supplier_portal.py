"""supplier portal: accounts, per-company access, set-password links

Revision ID: f3c6a8e2b4d7
Revises: e7b3c9d1f5a2
Create Date: 2026-09-29

The Supplier Portal lets a supplier's contact sign in and see the RFQs sent
to them, their quotations and the purchase orders placed with them — in
every company on the platform that buys from them, with one login.

* `supplier_portal_accounts` — the login. Platform-level (no company_id):
  one person, one password, however many companies they supply. Kept apart
  from `users` on purpose: a supplier is never a member of a tenant and
  must never pass a tenant permission check.
* `supplier_portal_access` — which company granted which account the right
  to act as which of *its* supplier records. Tenant data, RLS-protected; a
  company manages and sees only its own grants.
* `supplier_portal_tokens` — one-time set-password links (hash only).

Accounts and tokens are reached before any tenant is known (sign-in, the
emailed link), so like `refresh_tokens` they are deny-all under RLS and read
only through the BYPASSRLS platform role.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f3c6a8e2b4d7"
down_revision: Union[str, Sequence[str], None] = "e7b3c9d1f5a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MESSAGE_TYPES = ["rfq", "purchase_order", "proforma_query", "invitation", "alert_digest", "password_reset", "purchase_return"]
_RELATED_TYPES = ["rfq", "purchase_order", "proforma_invoice", "supplier_quotation", "invitation", "purchase_return"]
_ENTITY_TYPES = [
    "purchase_order", "rfq", "goods_receipt", "supplier_quotation", "proforma_invoice", "supplier_invoice",
    "product", "product_variant", "supplier", "inventory_transaction", "user", "invitation", "company",
    "document", "ai_extraction", "alert", "settings", "godown", "category", "brand", "uom", "permission",
    "purchase_return", "stock_transfer", "role", "quotation_comparison",
]


def _in(values: list[str]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _grant(table: str) -> None:
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


def _set_check(table: str, name: str, column: str, values: list[str]) -> None:
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({column} IN {_in(values)})")


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    ts = sa.DateTime(timezone=True)

    op.create_table(
        "supplier_portal_accounts",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="invited"),
        sa.Column("failed_login_count", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("locked_until", ts, nullable=True),
        sa.Column("last_login_at", ts, nullable=True),
        sa.Column("password_changed_at", ts, nullable=True),
        sa.Column("created_at", ts, nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('invited', 'active', 'disabled')", name="status_valid"),
    )
    op.create_index("uq_supplier_portal_accounts_email", "supplier_portal_accounts", [sa.text("lower(email)")], unique=True)
    op.execute("ALTER TABLE supplier_portal_accounts ENABLE ROW LEVEL SECURITY")
    _grant("supplier_portal_accounts")

    op.create_table(
        "supplier_portal_access",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", uuid, sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", uuid, sa.ForeignKey("supplier_portal_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("supplier_id", uuid, nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("granted_by", uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("granted_at", ts, nullable=False, server_default=sa.text("now()")),
        sa.Column("revoked_at", ts, nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id", "supplier_id"], ["suppliers.company_id", "suppliers.id"],
            name="fk_supplier_portal_access_supplier_id_suppliers", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("company_id", "account_id", "supplier_id", name="uq_supplier_portal_access_grant"),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="status_valid"),
    )
    op.create_index("ix_supplier_portal_access_account_id", "supplier_portal_access", ["account_id"])
    op.create_index("ix_supplier_portal_access_company_id", "supplier_portal_access", ["company_id"])
    op.execute("ALTER TABLE supplier_portal_access ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON supplier_portal_access "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )
    _grant("supplier_portal_access")

    op.create_table(
        "supplier_portal_tokens",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_id", uuid, sa.ForeignKey("supplier_portal_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", ts, nullable=False),
        sa.Column("used_at", ts, nullable=True),
        sa.Column("created_at", ts, nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("uq_supplier_portal_token_hash", "supplier_portal_tokens", ["token_hash"], unique=True)
    op.create_index("ix_supplier_portal_tokens_account_id", "supplier_portal_tokens", ["account_id"])
    op.execute("ALTER TABLE supplier_portal_tokens ENABLE ROW LEVEL SECURITY")
    _grant("supplier_portal_tokens")

    _set_check("outbound_messages", "ck_outbound_messages_message_type_valid", "message_type",
               _MESSAGE_TYPES + ["supplier_portal_invite"])
    _set_check("outbound_messages", "ck_outbound_messages_related_type_valid", "related_type",
               _RELATED_TYPES + ["supplier"])
    _set_check("audit_logs", "ck_audit_logs_entity_type_valid", "entity_type",
               _ENTITY_TYPES + ["supplier_portal_access"])


def downgrade() -> None:
    op.execute("DELETE FROM audit_logs WHERE entity_type = 'supplier_portal_access'")
    _set_check("audit_logs", "ck_audit_logs_entity_type_valid", "entity_type", _ENTITY_TYPES)
    op.execute("DELETE FROM outbound_messages WHERE message_type = 'supplier_portal_invite' OR related_type = 'supplier'")
    _set_check("outbound_messages", "ck_outbound_messages_related_type_valid", "related_type", _RELATED_TYPES)
    _set_check("outbound_messages", "ck_outbound_messages_message_type_valid", "message_type", _MESSAGE_TYPES)
    op.drop_table("supplier_portal_tokens")
    op.drop_table("supplier_portal_access")
    op.drop_table("supplier_portal_accounts")
