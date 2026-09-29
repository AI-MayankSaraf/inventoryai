"""Company-editable pick-lists and a subscription plans table

Revision ID: c7e2a9f4b1d3
Revises: a8c4e1f7d2b6
Create Date: 2026-09-30

Payment terms, delivery terms and supplier types were fixed lists in the
frontend, and the plans a company can be on were fixed in both the
frontend and a CHECK constraint. They now live in the database:

* `company_lists` — per company, edited in Settings. Seeded for every
  existing company with the values the app used to hard-code, plus any
  value already recorded on a supplier or PO, so nothing in use goes
  missing from its own pick-list.
* `subscription_plans` — platform-wide, edited in the platform console.
  `companies.plan` becomes a foreign key to `subscription_plans.name`
  (ON UPDATE CASCADE), replacing the CHECK constraint.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7e2a9f4b1d3"
down_revision: Union[str, Sequence[str], None] = "a8c4e1f7d2b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_LISTS = {
    "payment_terms": ["Advance", "15 Days", "30 Days", "45 Days", "Cash on Delivery"],
    "delivery_terms": ["FOR", "Ex-Works", "Door Delivery", "To Pay"],
    "supplier_type": ["Manufacturer", "Distributor", "Online", "Local Supplier", "Importer"],
}
DEFAULT_PLANS = [
    ("Trial", "Evaluation period"),
    ("Starter", None),
    ("Growth", None),
    ("Enterprise", None),
]
_ENTITY_TYPES = [
    "purchase_order", "rfq", "goods_receipt", "supplier_quotation", "proforma_invoice", "supplier_invoice",
    "product", "product_variant", "supplier", "inventory_transaction", "user", "invitation", "company",
    "document", "ai_extraction", "alert", "settings", "godown", "category", "brand", "uom", "permission",
    "purchase_return", "stock_transfer", "role", "quotation_comparison", "supplier_portal_access",
]


def _in(values: list[str]) -> str:
    return "(" + ", ".join("'" + v.replace("'", "''") + "'" for v in values) + ")"


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


def _updated_at_trigger(table: str) -> None:
    op.execute(
        f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def _set_audit_entity_types(values: list[str]) -> None:
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT ck_audit_logs_entity_type_valid")
    op.execute(f"ALTER TABLE audit_logs ADD CONSTRAINT ck_audit_logs_entity_type_valid CHECK (entity_type IN {_in(values)})")


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    ts = sa.DateTime(timezone=True)

    # ------------------------------------------------------------ plans
    op.create_table(
        "subscription_plans",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", ts, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", ts, nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("name", name="uq_subscription_plans_name"),
    )
    _grant("subscription_plans")
    _updated_at_trigger("subscription_plans")
    for i, (name, description) in enumerate(DEFAULT_PLANS):
        op.execute(
            sa.text("INSERT INTO subscription_plans (name, description, sort_order) VALUES (:n, :d, :o)")
            .bindparams(n=name, d=description, o=i * 10)
        )
    # Any plan already on a company that isn't a default (none expected).
    op.execute(
        "INSERT INTO subscription_plans (name, sort_order) "
        "SELECT DISTINCT plan, 100 FROM companies WHERE plan NOT IN (SELECT name FROM subscription_plans)"
    )
    op.execute("ALTER TABLE companies DROP CONSTRAINT IF EXISTS ck_companies_plan_valid")
    op.execute(
        "ALTER TABLE companies ADD CONSTRAINT fk_companies_plan_subscription_plans FOREIGN KEY (plan) "
        "REFERENCES subscription_plans (name) ON UPDATE CASCADE ON DELETE RESTRICT"
    )

    # ------------------------------------------------------------ lists
    op.create_table(
        "company_lists",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", uuid, sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("list_key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", ts, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", ts, nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("company_id", "id", name="uq_company_lists_company_id_id"),
        sa.CheckConstraint(f"list_key IN {_in(list(DEFAULT_LISTS))}", name="ck_company_lists_list_key_valid"),
    )
    op.create_index("ix_company_lists_company_id", "company_lists", ["company_id"])
    op.create_index(
        "uq_company_lists_value", "company_lists", ["company_id", "list_key", sa.text("lower(value)")], unique=True
    )
    op.execute("ALTER TABLE company_lists ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON company_lists "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )
    _grant("company_lists")
    _updated_at_trigger("company_lists")

    # Defaults for every company, in the order the app used to show them.
    for key, values in DEFAULT_LISTS.items():
        for i, value in enumerate(values):
            op.execute(
                sa.text(
                    "INSERT INTO company_lists (company_id, list_key, value, sort_order) "
                    "SELECT id, :k, :v, :o FROM companies"
                ).bindparams(k=key, v=value, o=i * 10)
            )
    # ...plus values already in use, after the defaults.
    for key, source in (
        ("supplier_type", "SELECT company_id, supplier_type AS v FROM suppliers"),
        ("payment_terms", "SELECT company_id, payment_terms AS v FROM suppliers "
                          "UNION SELECT company_id, payment_terms FROM purchase_orders"),
        ("delivery_terms", "SELECT company_id, delivery_terms AS v FROM purchase_orders"),
    ):
        op.execute(
            f"""
            INSERT INTO company_lists (company_id, list_key, value, sort_order)
            SELECT DISTINCT ON (u.company_id, lower(btrim(u.v))) u.company_id, '{key}', btrim(u.v), 100
            FROM ({source}) u
            WHERE u.v IS NOT NULL AND btrim(u.v) <> ''
              AND NOT EXISTS (SELECT 1 FROM company_lists l WHERE l.company_id = u.company_id
                              AND l.list_key = '{key}' AND lower(l.value) = lower(btrim(u.v)))
            """
        )

    _set_audit_entity_types(_ENTITY_TYPES + ["company_list", "subscription_plan"])


def downgrade() -> None:
    op.execute("DELETE FROM audit_logs WHERE entity_type IN ('company_list', 'subscription_plan')")
    _set_audit_entity_types(_ENTITY_TYPES)
    op.drop_table("company_lists")
    op.execute("ALTER TABLE companies DROP CONSTRAINT IF EXISTS fk_companies_plan_subscription_plans")
    op.execute(
        "ALTER TABLE companies ADD CONSTRAINT ck_companies_plan_valid "
        "CHECK (plan IN ('Trial', 'Starter', 'Growth', 'Enterprise'))"
    )
    op.drop_table("subscription_plans")
