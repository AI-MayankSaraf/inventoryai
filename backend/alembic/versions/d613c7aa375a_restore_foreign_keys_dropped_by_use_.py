"""restore foreign keys dropped by use_alter

Revision ID: d613c7aa375a
Revises: efc6b3fb9fdb
Create Date: 2026-09-16

Restores 73 foreign keys that the initial migration declared but
never actually created.

What happened: every FK built by `plain_fk()` in app/models/base.py carries
`use_alter=True`, which exists to break real circular table dependencies
(`companies.created_by -> users.id` while `users.company_id -> companies.id`).
`use_alter` works by deferring the constraint out of CREATE TABLE and
emitting it afterwards as a separate `ALTER TABLE ... ADD CONSTRAINT` —
but only `MetaData.create_all()` knows to do that second step. Alembic's
`op.create_table()` renders a single CREATE TABLE and silently drops any
`use_alter` constraint on the floor. No warning, no error.

The initial migration file therefore *contains* these constraints, and the
database never had them. That gap hid for two phases because the earlier
smoke tests ran against a `create_all()`-built schema (which does emit
them), and the later Alembic verification compared table counts, indexes
and the ledger trigger — but never counted foreign keys.

It surfaced when a product was accepted with a `base_uom_id` pointing at a
UoM that does not exist. 46 of the 73 point at `users.id`, so the practical
effect was that most "who did this" columns across the system had no
referential integrity at all.

Each constraint is added here as an explicit `ALTER TABLE` — the form
`use_alter` was supposed to produce — which is also why the circular
dependencies are not a problem: every table already exists by this point.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd613c7aa375a'
down_revision: Union[str, Sequence[str], None] = 'efc6b3fb9fdb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (constraint_name, table, column, target, on_delete)
FOREIGN_KEYS = [
    ("fk_ai_extracted_fields_corrected_by_users", "ai_extracted_fields", "corrected_by", "users.id", "SET NULL"),
    ("fk_ai_extracted_lines_decided_by_users", "ai_extracted_lines", "decided_by", "users.id", "SET NULL"),
    ("fk_ai_extracted_lines_uom_id_uoms", "ai_extracted_lines", "uom_id", "uoms.id", "RESTRICT"),
    ("fk_ai_extraction_results_reviewed_by_users", "ai_extraction_results", "reviewed_by", "users.id", "SET NULL"),
    ("fk_ai_processing_jobs_created_by_users", "ai_processing_jobs", "created_by", "users.id", "RESTRICT"),
    ("fk_ai_processing_jobs_triggered_by_users", "ai_processing_jobs", "triggered_by", "users.id", "SET NULL"),
    ("fk_ai_processing_jobs_updated_by_users", "ai_processing_jobs", "updated_by", "users.id", "RESTRICT"),
    ("fk_ai_review_actions_reviewer_id_users", "ai_review_actions", "reviewer_id", "users.id", "RESTRICT"),
    ("fk_alert_reads_user_id_users", "alert_reads", "user_id", "users.id", "CASCADE"),
    ("fk_alerts_dismissed_by_users", "alerts", "dismissed_by", "users.id", "SET NULL"),
    ("fk_alerts_resolved_by_users", "alerts", "resolved_by", "users.id", "SET NULL"),
    ("fk_assistant_queries_user_id_users", "assistant_queries", "user_id", "users.id", "RESTRICT"),
    ("fk_audit_logs_actor_user_id_users", "audit_logs", "actor_user_id", "users.id", "SET NULL"),
    ("fk_audit_logs_company_id_companies", "audit_logs", "company_id", "companies.id", "RESTRICT"),
    ("fk_audit_logs_impersonated_by_users", "audit_logs", "impersonated_by", "users.id", "SET NULL"),
    ("fk_companies_created_by_users", "companies", "created_by", "users.id", "RESTRICT"),
    ("fk_companies_logo_document_id_documents", "companies", "logo_document_id", "documents.id", "SET NULL"),
    ("fk_companies_updated_by_users", "companies", "updated_by", "users.id", "RESTRICT"),
    ("fk_document_links_linked_by_users", "document_links", "linked_by", "users.id", "RESTRICT"),
    ("fk_document_schema_mapping_fields_canonical_field_id_c_ee9cae16", "document_schema_mapping_fields", "canonical_field_id", "canonical_fields.id", "RESTRICT"),
    ("fk_document_schema_mapping_fields_confirmed_by_users", "document_schema_mapping_fields", "confirmed_by", "users.id", "SET NULL"),
    ("fk_document_schema_mappings_confirmed_by_users", "document_schema_mappings", "confirmed_by", "users.id", "SET NULL"),
    ("fk_document_sequences_created_by_users", "document_sequences", "created_by", "users.id", "RESTRICT"),
    ("fk_document_sequences_updated_by_users", "document_sequences", "updated_by", "users.id", "RESTRICT"),
    ("fk_document_variances_resolved_by_users", "document_variances", "resolved_by", "users.id", "SET NULL"),
    ("fk_documents_uploaded_by_users", "documents", "uploaded_by", "users.id", "RESTRICT"),
    ("fk_godowns_capacity_uom_id_uoms", "godowns", "capacity_uom_id", "uoms.id", "RESTRICT"),
    ("fk_godowns_incharge_user_id_users", "godowns", "incharge_user_id", "users.id", "SET NULL"),
    ("fk_goods_receipt_items_uom_id_uoms", "goods_receipt_items", "uom_id", "uoms.id", "RESTRICT"),
    ("fk_goods_receipts_cancelled_by_users", "goods_receipts", "cancelled_by", "users.id", "SET NULL"),
    ("fk_goods_receipts_confirmed_by_users", "goods_receipts", "confirmed_by", "users.id", "SET NULL"),
    ("fk_goods_receipts_received_by_users", "goods_receipts", "received_by", "users.id", "RESTRICT"),
    ("fk_impersonation_sessions_platform_user_id_users", "impersonation_sessions", "platform_user_id", "users.id", "RESTRICT"),
    ("fk_impersonation_sessions_target_user_id_users", "impersonation_sessions", "target_user_id", "users.id", "RESTRICT"),
    ("fk_inventory_transactions_entered_uom_id_uoms", "inventory_transactions", "entered_uom_id", "uoms.id", "RESTRICT"),
    ("fk_inventory_transactions_performed_by_users", "inventory_transactions", "performed_by", "users.id", "RESTRICT"),
    ("fk_inventory_transactions_uom_id_uoms", "inventory_transactions", "uom_id", "uoms.id", "RESTRICT"),
    ("fk_invitations_accepted_user_id_users", "invitations", "accepted_user_id", "users.id", "SET NULL"),
    ("fk_invitations_invited_by_users", "invitations", "invited_by", "users.id", "RESTRICT"),
    ("fk_invitations_role_id_roles", "invitations", "role_id", "roles.id", "RESTRICT"),
    ("fk_notification_preferences_user_id_users", "notification_preferences", "user_id", "users.id", "CASCADE"),
    ("fk_outbound_messages_sent_by_users", "outbound_messages", "sent_by", "users.id", "SET NULL"),
    ("fk_product_images_document_id_documents", "product_images", "document_id", "documents.id", "RESTRICT"),
    ("fk_product_uom_conversions_from_uom_id_uoms", "product_uom_conversions", "from_uom_id", "uoms.id", "RESTRICT"),
    ("fk_product_uom_conversions_to_uom_id_uoms", "product_uom_conversions", "to_uom_id", "uoms.id", "RESTRICT"),
    ("fk_product_variants_uom_id_uoms", "product_variants", "uom_id", "uoms.id", "RESTRICT"),
    ("fk_products_base_uom_id_uoms", "products", "base_uom_id", "uoms.id", "RESTRICT"),
    ("fk_proforma_invoice_items_uom_id_uoms", "proforma_invoice_items", "uom_id", "uoms.id", "RESTRICT"),
    ("fk_proforma_invoices_approved_by_users", "proforma_invoices", "approved_by", "users.id", "SET NULL"),
    ("fk_proforma_invoices_document_id_documents", "proforma_invoices", "document_id", "documents.id", "SET NULL"),
    ("fk_purchase_order_items_uom_id_uoms", "purchase_order_items", "uom_id", "uoms.id", "RESTRICT"),
    ("fk_purchase_orders_approved_by_users", "purchase_orders", "approved_by", "users.id", "SET NULL"),
    ("fk_purchase_orders_cancelled_by_users", "purchase_orders", "cancelled_by", "users.id", "SET NULL"),
    ("fk_quotation_comparisons_decided_by_users", "quotation_comparisons", "decided_by", "users.id", "SET NULL"),
    ("fk_refresh_tokens_impersonated_by_users", "refresh_tokens", "impersonated_by", "users.id", "SET NULL"),
    ("fk_refresh_tokens_user_id_users", "refresh_tokens", "user_id", "users.id", "CASCADE"),
    ("fk_rfq_items_uom_id_uoms", "rfq_items", "uom_id", "uoms.id", "RESTRICT"),
    ("fk_rfq_suppliers_outbound_message_id_outbound_messages", "rfq_suppliers", "outbound_message_id", "outbound_messages.id", "SET NULL"),
    ("fk_stock_transfer_items_uom_id_uoms", "stock_transfer_items", "uom_id", "uoms.id", "RESTRICT"),
    ("fk_stock_transfers_dispatched_by_users", "stock_transfers", "dispatched_by", "users.id", "RESTRICT"),
    ("fk_stock_transfers_received_by_users", "stock_transfers", "received_by", "users.id", "RESTRICT"),
    ("fk_supplier_invoice_items_uom_id_uoms", "supplier_invoice_items", "uom_id", "uoms.id", "RESTRICT"),
    ("fk_supplier_invoices_approved_by_users", "supplier_invoices", "approved_by", "users.id", "SET NULL"),
    ("fk_supplier_invoices_document_id_documents", "supplier_invoices", "document_id", "documents.id", "SET NULL"),
    ("fk_supplier_products_confirmed_by_users", "supplier_products", "confirmed_by", "users.id", "SET NULL"),
    ("fk_supplier_products_supplier_uom_id_uoms", "supplier_products", "supplier_uom_id", "uoms.id", "RESTRICT"),
    ("fk_supplier_quotation_items_uom_id_uoms", "supplier_quotation_items", "uom_id", "uoms.id", "RESTRICT"),
    ("fk_supplier_quotations_approved_by_users", "supplier_quotations", "approved_by", "users.id", "SET NULL"),
    ("fk_supplier_quotations_document_id_documents", "supplier_quotations", "document_id", "documents.id", "SET NULL"),
    ("fk_users_avatar_document_id_documents", "users", "avatar_document_id", "documents.id", "SET NULL"),
    ("fk_users_created_by_users", "users", "created_by", "users.id", "RESTRICT"),
    ("fk_users_role_id_roles", "users", "role_id", "roles.id", "RESTRICT"),
    ("fk_users_updated_by_users", "users", "updated_by", "users.id", "RESTRICT"),
]


def upgrade() -> None:
    for name, table, column, target, ondelete in FOREIGN_KEYS:
        target_table, target_column = target.split(".")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} "
            f"FOREIGN KEY ({column}) REFERENCES {target_table} ({target_column}) "
            f"ON DELETE {ondelete}"
        )


def downgrade() -> None:
    for name, table, _column, _target, _ondelete in FOREIGN_KEYS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
