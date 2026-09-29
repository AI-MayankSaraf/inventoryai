# 03 — DATABASE ERD

Mermaid diagrams for the schema defined in `02_DATABASE_DESIGN.md`. Split by domain because a single 60-entity diagram is unreadable; §7 gives the cross-domain overview.

Legend: `||--o{` one-to-many · `||--||` one-to-one · `}o--o{` many-to-many (always via a join table) · `|o--o{` optional one-to-many.

---

## 1. Tenancy, identity and access

```mermaid
erDiagram
    COMPANIES ||--|| COMPANY_SETTINGS : "configured by"
    COMPANIES ||--o{ DOCUMENT_SEQUENCES : "numbers with"
    COMPANIES ||--o{ USERS : "employs"
    COMPANIES ||--o{ INVITATIONS : "issues"
    COMPANIES ||--o{ ROLES : "may define custom"
    ROLES ||--o{ USERS : "assigned to"
    ROLES ||--o{ ROLE_PERMISSIONS : "grants"
    PERMISSIONS ||--o{ ROLE_PERMISSIONS : "granted by"
    USERS ||--o{ USER_GODOWN_ACCESS : "scoped to"
    GODOWNS ||--o{ USER_GODOWN_ACCESS : "accessible by"
    USERS ||--o{ REFRESH_TOKENS : "authenticates with"
    USERS ||--o{ IMPERSONATION_SESSIONS : "performs"
    USERS ||--o{ IMPERSONATION_SESSIONS : "is target of"
    INVITATIONS ||--o| USERS : "becomes"

    COMPANIES {
        uuid id PK
        text name
        text gstin UK
        text pan
        text state_code
        text plan
        text status
        date onboarded_on
    }
    USERS {
        uuid id PK
        uuid company_id FK "NULL = platform admin"
        text email UK "global"
        text username UK
        text password_hash
        uuid role_id FK
        text status
        boolean is_platform_admin
        timestamptz last_active_at
        timestamptz deleted_at
    }
    ROLES {
        uuid id PK
        uuid company_id FK "NULL = system role"
        text code UK
        text name
        boolean is_system
    }
    INVITATIONS {
        uuid id PK
        uuid company_id FK
        text email
        uuid role_id FK
        text token_hash UK
        text status
        smallint resend_count
        timestamptz expires_at
    }
```

---

## 2. Master data — catalogue, suppliers, godowns

```mermaid
erDiagram
    COMPANIES ||--o{ CATEGORIES : "owns"
    COMPANIES ||--o{ BRANDS : "owns"
    COMPANIES ||--o{ PRODUCTS : "owns"
    COMPANIES ||--o{ SUPPLIERS : "owns"
    COMPANIES ||--o{ GODOWNS : "owns"
    CATEGORIES ||--o{ CATEGORIES : "parent of"
    CATEGORIES ||--o{ PRODUCTS : "classifies"
    BRANDS ||--o{ PRODUCTS : "branded as"
    PRODUCTS ||--o{ PRODUCT_VARIANTS : "has SKUs"
    UOMS ||--o{ PRODUCT_VARIANTS : "measured in"
    PRODUCT_VARIANTS ||--o{ PRODUCT_UOM_CONVERSIONS : "converts via"
    PRODUCTS ||--o{ PRODUCT_IMAGES : "illustrated by"
    SUPPLIERS ||--o{ SUPPLIER_CONTACTS : "reached via"
    SUPPLIERS ||--o{ SUPPLIER_PRODUCTS : "supplies"
    PRODUCT_VARIANTS ||--o{ SUPPLIER_PRODUCTS : "sourced from"
    USERS |o--o{ GODOWNS : "in charge of"

    PRODUCTS {
        uuid id PK
        uuid company_id FK
        text name
        uuid brand_id FK
        uuid category_id FK
        text hsn_code
        numeric gst_rate
        text tracking_type "none|batch|serial"
        uuid base_uom_id FK
        timestamptz deleted_at
    }
    PRODUCT_VARIANTS {
        uuid id PK
        uuid company_id FK
        uuid product_id FK
        text sku UK "per company"
        text barcode UK "per company"
        text ean
        text upc
        text mpn
        text model_code
        uuid uom_id FK
        numeric purchase_price
        numeric sale_price
        numeric mrp
        numeric reorder_point
        numeric reorder_qty
        jsonb attributes
        text search_text "trgm indexed"
    }
    SUPPLIERS {
        uuid id PK
        uuid company_id FK
        text name UK "per company"
        text gstin UK "per company"
        text state_code "drives IGST vs CGST/SGST"
        text supplier_type
        text payment_terms
        text status
    }
    SUPPLIER_PRODUCTS {
        uuid id PK
        uuid supplier_id FK
        uuid product_variant_id FK
        text supplier_sku UK
        text supplier_description
        numeric conversion_to_base
        numeric last_purchase_price
        boolean is_preferred
        text match_source
    }
    GODOWNS {
        uuid id PK
        uuid company_id FK
        text name UK
        text city
        text state_code
        uuid incharge_user_id FK
        numeric capacity_value
    }
```

---

## 3. Inventory — the transaction-based core

```mermaid
erDiagram
    PRODUCT_VARIANTS ||--o{ INVENTORY_TRANSACTIONS : "moves"
    GODOWNS ||--o{ INVENTORY_TRANSACTIONS : "located at"
    BATCHES |o--o{ INVENTORY_TRANSACTIONS : "tracked by"
    USERS ||--o{ INVENTORY_TRANSACTIONS : "posted by"
    INVENTORY_TRANSACTIONS ||--o| INVENTORY_TRANSACTIONS : "counterpart of (transfer)"
    INVENTORY_TRANSACTIONS ||--o| INVENTORY_TRANSACTIONS : "reverses"

    PRODUCT_VARIANTS ||--o{ STOCK_BALANCES : "cached in"
    GODOWNS ||--o{ STOCK_BALANCES : "holds"
    BATCHES |o--o{ STOCK_BALANCES : "split by"

    PRODUCT_VARIANTS ||--o{ BATCHES : "produced as"
    GOODS_RECEIPT_ITEMS |o--o{ BATCHES : "creates"

    STOCK_TRANSFERS ||--o{ STOCK_TRANSFER_ITEMS : "contains"
    GODOWNS ||--o{ STOCK_TRANSFERS : "source"
    GODOWNS ||--o{ STOCK_TRANSFERS : "destination"
    STOCK_TRANSFER_ITEMS ||--o{ INVENTORY_TRANSACTIONS : "posts"

    INVENTORY_TRANSACTIONS {
        uuid id PK
        uuid company_id FK
        text txn_number
        text txn_type "10 values, sign-constrained"
        timestamptz txn_date
        uuid product_variant_id FK
        uuid godown_id FK
        uuid batch_id FK
        numeric quantity "SIGNED, base UoM"
        numeric entered_quantity
        uuid entered_uom_id FK
        numeric conversion_factor
        numeric unit_cost
        text source_type "polymorphic"
        uuid source_id
        uuid source_line_id
        uuid counterpart_txn_id FK
        uuid reverses_txn_id FK
        text remarks
        uuid performed_by FK
    }
    STOCK_BALANCES {
        uuid id PK
        uuid company_id FK
        uuid product_variant_id FK
        uuid godown_id FK
        uuid batch_id FK
        numeric quantity "= SUM(ledger)"
        numeric reserved_quantity
        numeric available_quantity "generated"
        timestamptz last_recalculated_at
    }
    BATCHES {
        uuid id PK
        uuid product_variant_id FK
        text batch_number UK
        date manufactured_on
        date expires_on
        numeric mrp
    }
```

**Invariant:** `stock_balances.quantity` must always equal `SUM(inventory_transactions.quantity)` for the same key. The cache is written in the same transaction as the ledger row and re-verified nightly.

---

## 4. Procurement chain (RFQ → Invoice)

```mermaid
erDiagram
    RFQS ||--o{ RFQ_ITEMS : "requests"
    RFQS ||--o{ RFQ_SUPPLIERS : "sent to"
    SUPPLIERS ||--o{ RFQ_SUPPLIERS : "receives"
    RFQS |o--o{ SUPPLIER_QUOTATIONS : "answered by"
    SUPPLIERS ||--o{ SUPPLIER_QUOTATIONS : "quotes"
    SUPPLIER_QUOTATIONS ||--o{ SUPPLIER_QUOTATION_ITEMS : "prices"
    RFQ_ITEMS |o--o{ SUPPLIER_QUOTATION_ITEMS : "quoted as"

    RFQS ||--o{ QUOTATION_COMPARISONS : "compared in"
    QUOTATION_COMPARISONS ||--o{ QUOTATION_COMPARISON_LINES : "decides"
    SUPPLIER_QUOTATION_ITEMS |o--o{ QUOTATION_COMPARISON_LINES : "selected as"

    QUOTATION_COMPARISONS |o--o{ PURCHASE_ORDERS : "produces"
    SUPPLIER_QUOTATIONS |o--o{ PURCHASE_ORDERS : "accepted into"
    RFQS |o--o{ PURCHASE_ORDERS : "linked to"
    SUPPLIERS ||--o{ PURCHASE_ORDERS : "receives"
    GODOWNS ||--o{ PURCHASE_ORDERS : "delivered to"
    PURCHASE_ORDERS ||--o{ PURCHASE_ORDER_ITEMS : "orders"
    PRODUCT_VARIANTS ||--o{ PURCHASE_ORDER_ITEMS : "ordered as"

    PURCHASE_ORDERS |o--o{ PROFORMA_INVOICES : "billed in advance by"
    PROFORMA_INVOICES ||--o{ PROFORMA_INVOICE_ITEMS : "itemises"
    PURCHASE_ORDER_ITEMS |o--o{ PROFORMA_INVOICE_ITEMS : "priced against"

    PURCHASE_ORDERS |o--o{ GOODS_RECEIPTS : "fulfilled by"
    GOODS_RECEIPTS ||--o{ GOODS_RECEIPT_ITEMS : "receives"
    PURCHASE_ORDER_ITEMS |o--o{ GOODS_RECEIPT_ITEMS : "received against"
    GOODS_RECEIPT_ITEMS ||--o| INVENTORY_TRANSACTIONS : "posts on confirm"

    PURCHASE_ORDERS |o--o{ SUPPLIER_INVOICES : "invoiced by"
    GOODS_RECEIPTS |o--o{ SUPPLIER_INVOICES : "evidenced by"
    SUPPLIER_INVOICES ||--o{ SUPPLIER_INVOICE_ITEMS : "charges"
    PURCHASE_ORDER_ITEMS |o--o{ SUPPLIER_INVOICE_ITEMS : "matched to"
    GOODS_RECEIPT_ITEMS |o--o{ SUPPLIER_INVOICE_ITEMS : "matched to"

    GOODS_RECEIPTS |o--o{ PURCHASE_RETURNS : "returns from"
    PURCHASE_RETURNS ||--o{ PURCHASE_RETURN_ITEMS : "returns"
    PURCHASE_RETURN_ITEMS ||--o| INVENTORY_TRANSACTIONS : "posts"

    PURCHASE_ORDER_ITEMS {
        uuid id PK
        uuid purchase_order_id FK
        smallint line_no
        uuid product_variant_id FK
        uuid quotation_item_id FK
        uuid rfq_item_id FK
        numeric quantity
        uuid uom_id FK
        numeric unit_price
        numeric discount_pct
        numeric gst_rate
        numeric line_total
        numeric received_quantity "Σ accepted GRN qty"
        numeric pending_quantity "generated"
        text line_status
    }
    GOODS_RECEIPT_ITEMS {
        uuid id PK
        uuid goods_receipt_id FK
        uuid purchase_order_item_id FK "enables partial receipt"
        uuid product_variant_id FK
        uuid batch_id FK
        numeric ordered_quantity
        numeric previously_received_quantity
        numeric received_quantity
        numeric accepted_quantity
        numeric rejected_quantity "generated"
        text issue_type "9 values"
        uuid expected_variant_id FK
        uuid inventory_transaction_id FK
    }
    SUPPLIER_INVOICES {
        uuid id PK
        text invoice_number UK "per supplier per date"
        date invoice_date
        uuid supplier_id FK
        uuid purchase_order_id FK
        uuid goods_receipt_id FK
        numeric cgst_amount
        numeric sgst_amount
        numeric igst_amount
        numeric cess_amount
        text eway_bill_number
        text irn
        text match_status
        text payment_status
    }
```

### Partial-delivery worked example

```
purchase_order_items (qty 100, received_quantity 0,   line_status open)
   ├── goods_receipt_items  GRN-1  received 60, accepted 60 → +60 ledger
   │        → received_quantity 60,  pending 40,  line_status partially_received
   └── goods_receipt_items  GRN-2  received 40, accepted 38, rejected 2 (damaged) → +38 ledger
            → received_quantity 98,  pending 2,   line_status partially_received
            → purchase_returns for the 2 damaged units (if accepted then returned)
            → buyer may short_close the remaining 2
```

---

## 5. Documents and AI

```mermaid
erDiagram
    COMPANIES ||--o{ DOCUMENTS : "owns"
    USERS ||--o{ DOCUMENTS : "uploads"
    SUPPLIERS |o--o{ DOCUMENTS : "identified as from"
    DOCUMENTS ||--o{ DOCUMENT_LINKS : "linked via"
    DOCUMENTS ||--o{ AI_PROCESSING_JOBS : "processed by"
    AI_PROCESSING_JOBS ||--o| AI_EXTRACTION_RESULTS : "produces"
    AI_EXTRACTION_RESULTS ||--o{ AI_EXTRACTED_FIELDS : "header fields"
    AI_EXTRACTION_RESULTS ||--o{ AI_EXTRACTED_LINES : "line items"
    AI_EXTRACTED_LINES ||--o{ AI_MATCH_CANDIDATES : "candidate SKUs"
    PRODUCT_VARIANTS |o--o{ AI_MATCH_CANDIDATES : "candidate"
    AI_EXTRACTION_RESULTS ||--o{ AI_REVIEW_ACTIONS : "reviewed by"
    USERS ||--o{ AI_REVIEW_ACTIONS : "performs"
    AI_EXTRACTION_RESULTS |o--o| SUPPLIER_QUOTATIONS : "promoted to"
    AI_EXTRACTION_RESULTS |o--o| PROFORMA_INVOICES : "promoted to"
    AI_EXTRACTION_RESULTS |o--o| SUPPLIER_INVOICES : "promoted to"

    SUPPLIERS ||--o{ DOCUMENT_SCHEMA_MAPPINGS : "files formatted as"
    DOCUMENT_SCHEMA_MAPPINGS ||--o{ DOCUMENT_SCHEMA_MAPPING_FIELDS : "maps columns"
    CANONICAL_FIELDS ||--o{ DOCUMENT_SCHEMA_MAPPING_FIELDS : "target of"
    PRODUCT_VARIANTS ||--|| VARIANT_EMBEDDINGS : "embedded as"
    AI_EXTRACTED_LINES |o--o{ SUPPLIER_PRODUCTS : "confirms alias"

    DOCUMENTS {
        uuid id PK
        uuid company_id FK
        text original_filename
        text storage_key UK
        text mime_type
        bigint file_size_bytes
        text sha256_hash UK "per company"
        text document_type
        uuid supplier_id FK
        text processing_status
        text processing_stage
        smallint processing_progress
        numeric extraction_confidence
        uuid uploaded_by FK
    }
    DOCUMENT_LINKS {
        uuid id PK
        uuid document_id FK
        text linked_type "rfq|quotation|po|proforma|grn|invoice|..."
        uuid linked_id "polymorphic"
        text link_role
    }
    AI_EXTRACTED_LINES {
        uuid id PK
        uuid extraction_result_id FK
        text raw_description
        text normalised_description
        text supplier_sku
        uuid matched_variant_id FK
        numeric quantity
        numeric unit_price
        numeric gst_rate
        numeric confidence
        text provenance "5 values"
        text final_decision
    }
```

---

## 6. Alerts, variances and audit

```mermaid
erDiagram
    COMPANIES ||--o{ ALERTS : "raised for"
    ALERTS ||--o{ ALERT_READS : "read by"
    USERS ||--o{ ALERT_READS : "reads"
    ALERT_RULES |o--o{ ALERTS : "generates"
    DOCUMENT_VARIANCES |o--o| ALERTS : "raises"
    COMPANIES ||--o{ AUDIT_LOGS : "records"
    USERS ||--o{ AUDIT_LOGS : "acts in"
    COMPANIES ||--o{ OUTBOUND_MESSAGES : "sends"
    SUPPLIERS |o--o{ OUTBOUND_MESSAGES : "receives"

    ALERTS {
        uuid id PK
        uuid company_id FK
        text severity "critical|high|medium|low"
        text category
        text rule_code
        text title
        text description
        text reference_type
        uuid reference_id
        text deep_link
        text status
        timestamptz resolved_at
    }
    DOCUMENT_VARIANCES {
        uuid id PK
        text comparison_kind "proforma_vs_po|grn_vs_po|invoice_vs_po|invoice_vs_grn"
        text variance_type "price|quantity|tax|total|product|delivery_date"
        text base_doc_type
        uuid base_doc_id
        text compare_doc_type
        uuid compare_doc_id
        numeric base_value
        numeric compare_value
        numeric difference
        numeric difference_pct
        text severity
        text status
    }
    AUDIT_LOGS {
        uuid id PK
        uuid company_id FK
        text entity_type
        uuid entity_id
        text entity_label
        text action
        uuid actor_user_id FK
        text actor_role
        uuid impersonated_by FK
        jsonb before_data
        jsonb after_data
        jsonb changed_fields
        inet ip_address
        text request_id
        timestamptz created_at
    }
```

---

## 7. Cross-domain overview

```mermaid
erDiagram
    COMPANIES ||--o{ USERS : ""
    COMPANIES ||--o{ PRODUCTS : ""
    COMPANIES ||--o{ SUPPLIERS : ""
    COMPANIES ||--o{ GODOWNS : ""
    PRODUCTS ||--o{ PRODUCT_VARIANTS : ""
    SUPPLIERS }o--o{ PRODUCT_VARIANTS : "supplier_products"
    RFQS }o--o{ SUPPLIERS : "rfq_suppliers"
    RFQS ||--o{ SUPPLIER_QUOTATIONS : ""
    SUPPLIER_QUOTATIONS ||--o{ PURCHASE_ORDERS : ""
    PURCHASE_ORDERS ||--o{ PROFORMA_INVOICES : ""
    PURCHASE_ORDERS ||--o{ GOODS_RECEIPTS : ""
    GOODS_RECEIPTS ||--o{ SUPPLIER_INVOICES : ""
    GOODS_RECEIPTS ||--o{ INVENTORY_TRANSACTIONS : ""
    INVENTORY_TRANSACTIONS ||--o{ STOCK_BALANCES : "aggregates into"
    STOCK_BALANCES ||--o{ ALERTS : "triggers low stock"
    DOCUMENTS }o--o{ PURCHASE_ORDERS : "document_links"
    DOCUMENTS ||--o{ AI_EXTRACTION_RESULTS : ""
    AI_EXTRACTION_RESULTS ||--o{ SUPPLIER_QUOTATIONS : "promoted to"
```

---

## 8. Ownership tree

```
COMPANY (tenant)
├── company_settings (1:1)
├── document_sequences
├── users ──── user_godown_access ──── godowns
│     └── invitations, refresh_tokens, impersonation_sessions
├── roles ──── role_permissions ──── permissions
├── categories (self-nesting)
├── brands
├── uoms
├── products
│     └── product_variants  ← the SKU; everything below points here
│           ├── product_uom_conversions
│           ├── variant_embeddings (1:1)
│           ├── batches
│           └── supplier_products ──── suppliers
├── suppliers
│     └── supplier_contacts
├── godowns
│     └── stock_balances ←──────── inventory_transactions (source of truth)
│                                        ▲
├── rfqs                                 │
│     ├── rfq_items                      │
│     └── rfq_suppliers                  │
├── supplier_quotations                  │
│     └── supplier_quotation_items       │
├── quotation_comparisons                │
│     └── quotation_comparison_lines     │
├── purchase_orders                      │
│     └── purchase_order_items           │
├── proforma_invoices                    │
│     └── proforma_invoice_items         │
├── goods_receipts                       │
│     └── goods_receipt_items ───────────┤ posts on confirm
├── purchase_returns                     │
│     └── purchase_return_items ─────────┤ posts on confirm
├── stock_transfers                      │
│     └── stock_transfer_items ──────────┘ posts on dispatch/receipt
├── supplier_invoices
│     └── supplier_invoice_items
├── document_variances
├── documents
│     ├── document_links (→ any business record)
│     └── ai_processing_jobs
│           └── ai_extraction_results
│                 ├── ai_extracted_fields
│                 ├── ai_extracted_lines ──── ai_match_candidates
│                 └── ai_review_actions
├── document_schema_mappings ──── document_schema_mapping_fields ──── canonical_fields
├── alerts ──── alert_reads
├── outbound_messages
└── audit_logs
```

---

## 9. Cardinality reference

| Relationship | Type | Notes |
|---|---|---|
| companies → company_settings | **1:1** | Created with the tenant |
| products → product_variants | 1:N | Minimum one; flat UI products get exactly one |
| product_variants → variant_embeddings | **1:1** | Regenerated when name/attributes change |
| rfqs → rfq_items | 1:N | CASCADE delete while draft |
| rfqs ↔ suppliers | **M:N** | via `rfq_suppliers`, with per-supplier send status |
| rfqs → supplier_quotations | 1:N (optional) | A quotation may exist with no RFQ (rate list) |
| supplier_quotations → items | 1:N | |
| rfq_items → supplier_quotation_items | 1:N (optional) | One requested line, many supplier prices |
| quotation_comparisons → lines | 1:N | One line per RFQ item |
| comparison → purchase_orders | 1:N | **A split decision creates several POs** — the UI already does this with tabs |
| purchase_orders → items | 1:N | |
| purchase_order_items ↔ goods_receipt_items | **M:N in effect** | One PO line receives across many GRNs; modelled as 1:N from the PO line |
| purchase_orders → proforma_invoices | 1:N | Several advance bills against one PO are legal |
| goods_receipt_items → inventory_transactions | **1:1** | One accepted line posts exactly one ledger row (two for a transfer) |
| purchase_order_items → supplier_invoice_items | 1:N | Invoicing may be split |
| suppliers ↔ product_variants | **M:N** | via `supplier_products` — the alias table that makes AI matching converge |
| documents ↔ business records | **M:N** | via `document_links`, polymorphic |
| roles ↔ permissions | **M:N** | |
| users ↔ godowns | **M:N** | via `user_godown_access`; `has_all_godowns` short-circuits |
| alerts ↔ users | **M:N** | via `alert_reads` — read state is per user, not per alert |
| inventory_transactions → inventory_transactions | 1:1 self | `counterpart_txn_id` (transfer pair), `reverses_txn_id` (correction) |
| categories → categories | 1:N self | parent/child = UI category/subcategory |
