"""rls policies

Revision ID: 746390963b46
Revises: b16098bff981
Create Date: 2026-09-16

Row-Level Security, 02_DATABASE_DESIGN.md §3 / §13:

    ALTER TABLE purchase_orders ENABLE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON purchase_orders
      USING (company_id = current_setting('app.current_company_id')::uuid);

Applied here to all 64 tables that carry tenant meaning (66 tables total,
minus `permissions` and `canonical_fields`, which are genuinely global with
no company_id column at all — no policy needed).

`current_setting(..., true)` (missing_ok=true) is used everywhere instead of
the doc's bare form: if a connection queries a tenant table before
`SET LOCAL app.current_company_id` has been issued for that transaction,
this returns NULL rather than raising, and `company_id = NULL` is never
true — so the failure mode is "see nothing" (fail closed), never an error
that could be caught and worked around, and never "see everything".

Five categories, matched to how each table actually carries tenant scope:

  * strict tenant (53 tables + `company_settings`) — `company_id` is
    NOT NULL; straightforward `company_id = current tenant`.
  * `companies` itself — the tenant root has no `company_id` column, it
    IS the tenant; policy compares `id` instead.
  * nullable-hidden (`users`, `audit_logs`) — `company_id` is nullable for
    platform-level rows (a platform admin user, a platform-level audit
    entry). Same comparison as strict tenant: a NULL row simply never
    matches a real tenant's `current_setting`, so it is invisible to every
    tenant-scoped connection and visible only to the BYPASSRLS platform
    role — exactly the intended behaviour, with no extra clause needed.
  * system-shared-if-null (`roles`, `uoms`) — `company_id IS NULL` means a
    system-wide row every tenant must see (the 7 system roles, the 9
    seeded UoMs), so `USING` allows NULL-or-own; `WITH CHECK` only allows
    a tenant's own connection to insert its OWN rows, never a new NULL
    (system-wide) row — only the BYPASSRLS platform/seed role can create
    those, by design.
  * join-derived (`document_schema_mapping_fields`, `role_permissions`,
    `user_godown_access`, `notification_preferences`) — no `company_id`
    column of their own; tenant scope is derived via `EXISTS` against the
    parent row that does carry it.
  * platform-only / deny-all (`refresh_tokens`, `impersonation_sessions`)
    — RLS enabled with zero policies. Postgres's default for row security
    with no matching policy is deny-all, so these become invisible to
    every ordinary (non-BYPASSRLS) connection. This is deliberate: refresh
    tokens are looked up by the auth service before any tenant context
    exists yet (you don't know which tenant a bearer token belongs to
    until you've already found and decoded it), and impersonation
    sessions are inherently a platform-admin concern — both are reached
    only through the `inventoryai_platform` (BYPASSRLS) role, never
    through ordinary per-request tenant sessions.

None of this replaces the composite tenant-FK guard from the initial
migration — RLS is the second, independent layer the design calls the
guard against a bug in the service layer, not a substitute for the first.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '746390963b46'
down_revision: Union[str, Sequence[str], None] = 'b16098bff981'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ai_extracted_fields — strict tenant
    op.execute("ALTER TABLE ai_extracted_fields ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON ai_extracted_fields "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # ai_extracted_lines — strict tenant
    op.execute("ALTER TABLE ai_extracted_lines ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON ai_extracted_lines "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # ai_extraction_results — strict tenant
    op.execute("ALTER TABLE ai_extraction_results ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON ai_extraction_results "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # ai_match_candidates — strict tenant
    op.execute("ALTER TABLE ai_match_candidates ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON ai_match_candidates "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # ai_processing_jobs — strict tenant
    op.execute("ALTER TABLE ai_processing_jobs ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON ai_processing_jobs "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # ai_review_actions — strict tenant
    op.execute("ALTER TABLE ai_review_actions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON ai_review_actions "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # alert_reads — strict tenant
    op.execute("ALTER TABLE alert_reads ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON alert_reads "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # alert_rules — strict tenant
    op.execute("ALTER TABLE alert_rules ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON alert_rules "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # alerts — strict tenant
    op.execute("ALTER TABLE alerts ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON alerts "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # assistant_queries — strict tenant
    op.execute("ALTER TABLE assistant_queries ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON assistant_queries "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # audit_logs — nullable-hidden
    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON audit_logs "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # batches — strict tenant
    op.execute("ALTER TABLE batches ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON batches "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # brands — strict tenant
    op.execute("ALTER TABLE brands ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON brands "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # categories — strict tenant
    op.execute("ALTER TABLE categories ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON categories "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # companies — tenant root
    op.execute("ALTER TABLE companies ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON companies "
        "USING (id = current_setting('app.current_company_id', true)::uuid)"
    )

    # company_settings — strict tenant
    op.execute("ALTER TABLE company_settings ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON company_settings "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # document_links — strict tenant
    op.execute("ALTER TABLE document_links ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON document_links "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # document_schema_mapping_fields — join-derived
    op.execute("ALTER TABLE document_schema_mapping_fields ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON document_schema_mapping_fields "
        "USING (EXISTS (SELECT 1 FROM document_schema_mappings m WHERE m.id = mapping_id AND m.company_id = current_setting('app.current_company_id', true)::uuid)) "
        "WITH CHECK (EXISTS (SELECT 1 FROM document_schema_mappings m WHERE m.id = mapping_id AND m.company_id = current_setting('app.current_company_id', true)::uuid))"
    )

    # document_schema_mappings — strict tenant
    op.execute("ALTER TABLE document_schema_mappings ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON document_schema_mappings "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # document_sequences — strict tenant
    op.execute("ALTER TABLE document_sequences ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON document_sequences "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # document_variances — strict tenant
    op.execute("ALTER TABLE document_variances ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON document_variances "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # documents — strict tenant
    op.execute("ALTER TABLE documents ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON documents "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # godowns — strict tenant
    op.execute("ALTER TABLE godowns ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON godowns "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # goods_receipt_items — strict tenant
    op.execute("ALTER TABLE goods_receipt_items ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON goods_receipt_items "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # goods_receipts — strict tenant
    op.execute("ALTER TABLE goods_receipts ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON goods_receipts "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # impersonation_sessions — platform-only, deny-all for app role
    op.execute("ALTER TABLE impersonation_sessions ENABLE ROW LEVEL SECURITY")

    # inventory_reservations — strict tenant
    op.execute("ALTER TABLE inventory_reservations ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON inventory_reservations "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # inventory_transactions — strict tenant
    op.execute("ALTER TABLE inventory_transactions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON inventory_transactions "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # invitations — strict tenant
    op.execute("ALTER TABLE invitations ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON invitations "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # notification_preferences — join-derived
    op.execute("ALTER TABLE notification_preferences ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON notification_preferences "
        "USING (EXISTS (SELECT 1 FROM users u WHERE u.id = user_id AND u.company_id = current_setting('app.current_company_id', true)::uuid)) "
        "WITH CHECK (EXISTS (SELECT 1 FROM users u WHERE u.id = user_id AND u.company_id = current_setting('app.current_company_id', true)::uuid))"
    )

    # outbound_messages — strict tenant
    op.execute("ALTER TABLE outbound_messages ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON outbound_messages "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # product_images — strict tenant
    op.execute("ALTER TABLE product_images ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON product_images "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # product_uom_conversions — strict tenant
    op.execute("ALTER TABLE product_uom_conversions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON product_uom_conversions "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # product_variants — strict tenant
    op.execute("ALTER TABLE product_variants ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON product_variants "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # products — strict tenant
    op.execute("ALTER TABLE products ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON products "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # proforma_invoice_items — strict tenant
    op.execute("ALTER TABLE proforma_invoice_items ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON proforma_invoice_items "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # proforma_invoices — strict tenant
    op.execute("ALTER TABLE proforma_invoices ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON proforma_invoices "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # purchase_order_items — strict tenant
    op.execute("ALTER TABLE purchase_order_items ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON purchase_order_items "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # purchase_orders — strict tenant
    op.execute("ALTER TABLE purchase_orders ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON purchase_orders "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # purchase_return_items — strict tenant
    op.execute("ALTER TABLE purchase_return_items ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON purchase_return_items "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # purchase_returns — strict tenant
    op.execute("ALTER TABLE purchase_returns ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON purchase_returns "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # quotation_comparison_lines — strict tenant
    op.execute("ALTER TABLE quotation_comparison_lines ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON quotation_comparison_lines "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # quotation_comparisons — strict tenant
    op.execute("ALTER TABLE quotation_comparisons ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON quotation_comparisons "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # refresh_tokens — platform-only, deny-all for app role
    op.execute("ALTER TABLE refresh_tokens ENABLE ROW LEVEL SECURITY")

    # rfq_items — strict tenant
    op.execute("ALTER TABLE rfq_items ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON rfq_items "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # rfq_suppliers — strict tenant
    op.execute("ALTER TABLE rfq_suppliers ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON rfq_suppliers "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # rfqs — strict tenant
    op.execute("ALTER TABLE rfqs ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON rfqs "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # role_permissions — join-derived
    op.execute("ALTER TABLE role_permissions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON role_permissions "
        "USING (EXISTS (SELECT 1 FROM roles r WHERE r.id = role_id AND (r.company_id IS NULL OR r.company_id = current_setting('app.current_company_id', true)::uuid))) "
        "WITH CHECK (EXISTS (SELECT 1 FROM roles r WHERE r.id = role_id AND r.company_id = current_setting('app.current_company_id', true)::uuid))"
    )

    # roles — system-shared-if-null
    op.execute("ALTER TABLE roles ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON roles "
        "USING (company_id IS NULL OR company_id = current_setting('app.current_company_id', true)::uuid) "
        "WITH CHECK (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # stock_balances — strict tenant
    op.execute("ALTER TABLE stock_balances ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON stock_balances "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # stock_transfer_items — strict tenant
    op.execute("ALTER TABLE stock_transfer_items ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON stock_transfer_items "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # stock_transfers — strict tenant
    op.execute("ALTER TABLE stock_transfers ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON stock_transfers "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # supplier_contacts — strict tenant
    op.execute("ALTER TABLE supplier_contacts ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON supplier_contacts "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # supplier_invoice_items — strict tenant
    op.execute("ALTER TABLE supplier_invoice_items ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON supplier_invoice_items "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # supplier_invoices — strict tenant
    op.execute("ALTER TABLE supplier_invoices ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON supplier_invoices "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # supplier_products — strict tenant
    op.execute("ALTER TABLE supplier_products ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON supplier_products "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # supplier_quotation_items — strict tenant
    op.execute("ALTER TABLE supplier_quotation_items ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON supplier_quotation_items "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # supplier_quotations — strict tenant
    op.execute("ALTER TABLE supplier_quotations ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON supplier_quotations "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # suppliers — strict tenant
    op.execute("ALTER TABLE suppliers ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON suppliers "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # uoms — system-shared-if-null
    op.execute("ALTER TABLE uoms ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON uoms "
        "USING (company_id IS NULL OR company_id = current_setting('app.current_company_id', true)::uuid) "
        "WITH CHECK (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # user_godown_access — join-derived
    op.execute("ALTER TABLE user_godown_access ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON user_godown_access "
        "USING (EXISTS (SELECT 1 FROM users u WHERE u.id = user_id AND u.company_id = current_setting('app.current_company_id', true)::uuid)) "
        "WITH CHECK (EXISTS (SELECT 1 FROM users u WHERE u.id = user_id AND u.company_id = current_setting('app.current_company_id', true)::uuid))"
    )

    # users — nullable-hidden
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON users "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # variant_embeddings — strict tenant
    op.execute("ALTER TABLE variant_embeddings ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON variant_embeddings "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )

    # variant_godown_policies — strict tenant
    op.execute("ALTER TABLE variant_godown_policies ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON variant_godown_policies "
        "USING (company_id = current_setting('app.current_company_id', true)::uuid)"
    )



def downgrade() -> None:
    # variant_godown_policies
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON variant_godown_policies")
    op.execute("ALTER TABLE variant_godown_policies DISABLE ROW LEVEL SECURITY")

    # variant_embeddings
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON variant_embeddings")
    op.execute("ALTER TABLE variant_embeddings DISABLE ROW LEVEL SECURITY")

    # users
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON users")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")

    # user_godown_access
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON user_godown_access")
    op.execute("ALTER TABLE user_godown_access DISABLE ROW LEVEL SECURITY")

    # uoms
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON uoms")
    op.execute("ALTER TABLE uoms DISABLE ROW LEVEL SECURITY")

    # suppliers
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON suppliers")
    op.execute("ALTER TABLE suppliers DISABLE ROW LEVEL SECURITY")

    # supplier_quotations
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON supplier_quotations")
    op.execute("ALTER TABLE supplier_quotations DISABLE ROW LEVEL SECURITY")

    # supplier_quotation_items
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON supplier_quotation_items")
    op.execute("ALTER TABLE supplier_quotation_items DISABLE ROW LEVEL SECURITY")

    # supplier_products
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON supplier_products")
    op.execute("ALTER TABLE supplier_products DISABLE ROW LEVEL SECURITY")

    # supplier_invoices
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON supplier_invoices")
    op.execute("ALTER TABLE supplier_invoices DISABLE ROW LEVEL SECURITY")

    # supplier_invoice_items
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON supplier_invoice_items")
    op.execute("ALTER TABLE supplier_invoice_items DISABLE ROW LEVEL SECURITY")

    # supplier_contacts
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON supplier_contacts")
    op.execute("ALTER TABLE supplier_contacts DISABLE ROW LEVEL SECURITY")

    # stock_transfers
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON stock_transfers")
    op.execute("ALTER TABLE stock_transfers DISABLE ROW LEVEL SECURITY")

    # stock_transfer_items
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON stock_transfer_items")
    op.execute("ALTER TABLE stock_transfer_items DISABLE ROW LEVEL SECURITY")

    # stock_balances
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON stock_balances")
    op.execute("ALTER TABLE stock_balances DISABLE ROW LEVEL SECURITY")

    # roles
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON roles")
    op.execute("ALTER TABLE roles DISABLE ROW LEVEL SECURITY")

    # role_permissions
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON role_permissions")
    op.execute("ALTER TABLE role_permissions DISABLE ROW LEVEL SECURITY")

    # rfqs
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON rfqs")
    op.execute("ALTER TABLE rfqs DISABLE ROW LEVEL SECURITY")

    # rfq_suppliers
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON rfq_suppliers")
    op.execute("ALTER TABLE rfq_suppliers DISABLE ROW LEVEL SECURITY")

    # rfq_items
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON rfq_items")
    op.execute("ALTER TABLE rfq_items DISABLE ROW LEVEL SECURITY")

    # refresh_tokens
    op.execute("ALTER TABLE refresh_tokens DISABLE ROW LEVEL SECURITY")

    # quotation_comparisons
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON quotation_comparisons")
    op.execute("ALTER TABLE quotation_comparisons DISABLE ROW LEVEL SECURITY")

    # quotation_comparison_lines
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON quotation_comparison_lines")
    op.execute("ALTER TABLE quotation_comparison_lines DISABLE ROW LEVEL SECURITY")

    # purchase_returns
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON purchase_returns")
    op.execute("ALTER TABLE purchase_returns DISABLE ROW LEVEL SECURITY")

    # purchase_return_items
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON purchase_return_items")
    op.execute("ALTER TABLE purchase_return_items DISABLE ROW LEVEL SECURITY")

    # purchase_orders
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON purchase_orders")
    op.execute("ALTER TABLE purchase_orders DISABLE ROW LEVEL SECURITY")

    # purchase_order_items
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON purchase_order_items")
    op.execute("ALTER TABLE purchase_order_items DISABLE ROW LEVEL SECURITY")

    # proforma_invoices
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON proforma_invoices")
    op.execute("ALTER TABLE proforma_invoices DISABLE ROW LEVEL SECURITY")

    # proforma_invoice_items
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON proforma_invoice_items")
    op.execute("ALTER TABLE proforma_invoice_items DISABLE ROW LEVEL SECURITY")

    # products
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON products")
    op.execute("ALTER TABLE products DISABLE ROW LEVEL SECURITY")

    # product_variants
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON product_variants")
    op.execute("ALTER TABLE product_variants DISABLE ROW LEVEL SECURITY")

    # product_uom_conversions
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON product_uom_conversions")
    op.execute("ALTER TABLE product_uom_conversions DISABLE ROW LEVEL SECURITY")

    # product_images
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON product_images")
    op.execute("ALTER TABLE product_images DISABLE ROW LEVEL SECURITY")

    # outbound_messages
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON outbound_messages")
    op.execute("ALTER TABLE outbound_messages DISABLE ROW LEVEL SECURITY")

    # notification_preferences
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON notification_preferences")
    op.execute("ALTER TABLE notification_preferences DISABLE ROW LEVEL SECURITY")

    # invitations
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON invitations")
    op.execute("ALTER TABLE invitations DISABLE ROW LEVEL SECURITY")

    # inventory_transactions
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON inventory_transactions")
    op.execute("ALTER TABLE inventory_transactions DISABLE ROW LEVEL SECURITY")

    # inventory_reservations
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON inventory_reservations")
    op.execute("ALTER TABLE inventory_reservations DISABLE ROW LEVEL SECURITY")

    # impersonation_sessions
    op.execute("ALTER TABLE impersonation_sessions DISABLE ROW LEVEL SECURITY")

    # goods_receipts
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON goods_receipts")
    op.execute("ALTER TABLE goods_receipts DISABLE ROW LEVEL SECURITY")

    # goods_receipt_items
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON goods_receipt_items")
    op.execute("ALTER TABLE goods_receipt_items DISABLE ROW LEVEL SECURITY")

    # godowns
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON godowns")
    op.execute("ALTER TABLE godowns DISABLE ROW LEVEL SECURITY")

    # documents
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON documents")
    op.execute("ALTER TABLE documents DISABLE ROW LEVEL SECURITY")

    # document_variances
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON document_variances")
    op.execute("ALTER TABLE document_variances DISABLE ROW LEVEL SECURITY")

    # document_sequences
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON document_sequences")
    op.execute("ALTER TABLE document_sequences DISABLE ROW LEVEL SECURITY")

    # document_schema_mappings
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON document_schema_mappings")
    op.execute("ALTER TABLE document_schema_mappings DISABLE ROW LEVEL SECURITY")

    # document_schema_mapping_fields
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON document_schema_mapping_fields")
    op.execute("ALTER TABLE document_schema_mapping_fields DISABLE ROW LEVEL SECURITY")

    # document_links
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON document_links")
    op.execute("ALTER TABLE document_links DISABLE ROW LEVEL SECURITY")

    # company_settings
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON company_settings")
    op.execute("ALTER TABLE company_settings DISABLE ROW LEVEL SECURITY")

    # companies
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON companies")
    op.execute("ALTER TABLE companies DISABLE ROW LEVEL SECURITY")

    # categories
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON categories")
    op.execute("ALTER TABLE categories DISABLE ROW LEVEL SECURITY")

    # brands
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON brands")
    op.execute("ALTER TABLE brands DISABLE ROW LEVEL SECURITY")

    # batches
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON batches")
    op.execute("ALTER TABLE batches DISABLE ROW LEVEL SECURITY")

    # audit_logs
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON audit_logs")
    op.execute("ALTER TABLE audit_logs DISABLE ROW LEVEL SECURITY")

    # assistant_queries
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON assistant_queries")
    op.execute("ALTER TABLE assistant_queries DISABLE ROW LEVEL SECURITY")

    # alerts
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON alerts")
    op.execute("ALTER TABLE alerts DISABLE ROW LEVEL SECURITY")

    # alert_rules
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON alert_rules")
    op.execute("ALTER TABLE alert_rules DISABLE ROW LEVEL SECURITY")

    # alert_reads
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON alert_reads")
    op.execute("ALTER TABLE alert_reads DISABLE ROW LEVEL SECURITY")

    # ai_review_actions
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ai_review_actions")
    op.execute("ALTER TABLE ai_review_actions DISABLE ROW LEVEL SECURITY")

    # ai_processing_jobs
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ai_processing_jobs")
    op.execute("ALTER TABLE ai_processing_jobs DISABLE ROW LEVEL SECURITY")

    # ai_match_candidates
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ai_match_candidates")
    op.execute("ALTER TABLE ai_match_candidates DISABLE ROW LEVEL SECURITY")

    # ai_extraction_results
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ai_extraction_results")
    op.execute("ALTER TABLE ai_extraction_results DISABLE ROW LEVEL SECURITY")

    # ai_extracted_lines
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ai_extracted_lines")
    op.execute("ALTER TABLE ai_extracted_lines DISABLE ROW LEVEL SECURITY")

    # ai_extracted_fields
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ai_extracted_fields")
    op.execute("ALTER TABLE ai_extracted_fields DISABLE ROW LEVEL SECURITY")

