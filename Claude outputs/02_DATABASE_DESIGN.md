# 02 — DATABASE DESIGN (PostgreSQL)

**Target stack:** PostgreSQL 16 + pgvector · SQLAlchemy 2.x · Alembic · FastAPI · Redis · Celery · S3
**Scope:** Everything the current UI needs, plus the minimum required to close the RFQ → Invoice → Inventory loop correctly.
**Companion documents:** `03_DATABASE_ERD.md` (visual), `08_AI_DATA_MODEL.md` (AI tables in depth), `09_GAPS_AND_RECOMMENDATIONS.md` (what the UI gets wrong).

---

## 1. Global conventions

These apply to **every** table unless a table explicitly says otherwise. They are not repeated in each column list.

| Convention | Rule |
|---|---|
| Primary key | `id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY`. Never expose sequential integers. |
| Tenant key | `company_id UUID NOT NULL REFERENCES companies(id) ON DELETE RESTRICT` on every tenant-owned table, always the **first column of every composite index**. |
| Audit columns | `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()` (trigger-maintained), `created_by UUID NULL REFERENCES users(id)`, `updated_by UUID NULL REFERENCES users(id)`. |
| Soft delete | `deleted_at TIMESTAMPTZ NULL` **only** on master-data tables (§10). Transactional documents are cancelled, never deleted. |
| Optimistic locking | `row_version INTEGER NOT NULL DEFAULT 1` on all editable business documents (RFQ, PO, GRN, quotation, proforma, invoice). |
| Money | `NUMERIC(18,2)` for amounts/totals. `NUMERIC(18,4)` for unit prices and rates (the fastener PO in the mock data uses ₹0.60 and ₹2.40 — per-piece rates need 4 dp). Never `FLOAT`. |
| Quantity | `NUMERIC(18,3)` — supports Kg/Litre/Metre, which the UI already lists as units. |
| Percent | `NUMERIC(5,2)` (discount %, GST %, on-time %). |
| Status / enum columns | `TEXT NOT NULL` + `CHECK (col IN (...))`, **not** native PG ENUM types. Rationale: Alembic migrations for CHECK constraints are trivial and reversible; PG enum value removal is not possible and reordering is painful. Values are listed in §11. |
| Timestamps | `TIMESTAMPTZ` everywhere. Business **dates** (PO date, invoice date) are `DATE` — they are legal/document dates, not instants. |
| Text | `TEXT` (Postgres has no performance benefit for `VARCHAR(n)`); length enforced with CHECK where it is a real business rule (e.g. GSTIN = 15). |
| JSONB | Allowed only where the shape is genuinely open: `product_variants.attributes`, AI payloads, audit diffs, settings blobs, webhook payloads. Never for anything that is filtered, joined or aggregated in a hot path. |
| Naming | `snake_case`, plural tables, `<singular>_id` FKs, index prefix `ix_`, unique `uq_`, check `ck_`, FK `fk_`. |
| Deletion policy on FKs | `ON DELETE RESTRICT` by default; `ON DELETE CASCADE` only for child line-item tables owned wholly by their parent. |

### 1.1 Multi-tenancy model

**Chosen approach: single database, shared schema, `company_id` column + PostgreSQL Row-Level Security.**

```sql
ALTER TABLE purchase_orders ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON purchase_orders
  USING (company_id = current_setting('app.current_company_id')::uuid);
```

FastAPI sets `SET LOCAL app.current_company_id = :id` at the start of every request transaction, derived from the JWT — never from a request parameter. Platform-admin queries run as a role that bypasses RLS (`BYPASSRLS`) and are always written to `audit_logs`.

Why not schema-per-tenant: an Indian wholesaler SaaS at this stage will have hundreds-to-thousands of tenants with small datasets; per-schema migrations become an operational burden with no security gain that RLS does not already provide. Revisit only if a customer contractually demands physical isolation.

---

## 2. Entity inventory and priority

| # | Entity / table | Priority | Justified by (UI evidence) |
|---|---|---|---|
| 1 | `companies` | **MUST** | System Admin tenant list; `Company` type |
| 2 | `company_settings` | **MUST** | `/settings` page (5 sections, all currently inert) |
| 3 | `document_sequences` | **MUST** | Settings numbering prefixes; `nextPoNumber()` etc. |
| 4 | `users` | **MUST** | Login, Users page, impersonation |
| 5 | `roles` | **MUST** | 6 role strings; invite dialog |
| 6 | `permissions` | **MUST** | Role-gated System Admin; Owner-exempt delete |
| 7 | `role_permissions` | **MUST** | RBAC matrix (`07`) |
| 8 | `user_godown_access` | **MUST** | `Member.godown` scope ("All godowns" / named godown) |
| 9 | `invitations` | **MUST** | Pending Invitations panel + accept-invite flow |
| 10 | `refresh_tokens` | RECOMMENDED | "Keep me signed in" |
| 11 | `impersonation_sessions` | RECOMMENDED | Super Admin impersonate + return |
| 12 | `categories` | **MUST** | `CATEGORIES`, product.category/subcategory, filters |
| 13 | `brands` | **MUST** | `BRANDS`, brand filters |
| 14 | `uoms` | **MUST** | 9 unit strings across PO/RFQ/GRN/stock |
| 15 | `products` | **MUST** | Product catalogue |
| 16 | `product_variants` | **MUST** | SKU, barcode/EAN/UPC/MPN, `attributes`, and `wrong_variant`/`wrong_model` GRN issues |
| 17 | `product_uom_conversions` | RECOMMENDED | Units `Box`/`Pack`/`Bag` vs stock in `Nos` |
| 18 | `product_images` | RECOMMENDED | "Images & Documents" panel on product detail |
| 19 | `godowns` | **MUST** | Godowns page, per-godown stock, godown filters |
| 20 | `suppliers` | **MUST** | Supplier directory |
| 21 | `supplier_contacts` | **MUST** | `supplier.contacts[]` |
| 22 | `supplier_products` | **MUST** | `supplierSku` in extraction; low-stock "supplier + lastPrice" |
| 23 | `inventory_transactions` | **MUST** | Transactions ledger — the source of truth |
| 24 | `stock_balances` | **MUST** | Current stock, by-godown, low-stock, dashboard (performance) |
| 25 | `batches` | RECOMMENDED | `GrnIssue = expired`; FMCG/grocery catalogue |
| 26 | `stock_transfers` | RECOMMENDED | Transfer dialog emits 2 rows + `TRF-` reference; "Transfer Stock" button |
| 27 | `inventory_reservations` | FUTURE | `reserved` is displayed everywhere but nothing can create it |
| 28 | `variant_godown_policies` | OPTIONAL | Per-godown reorder points (UI has product-level only) |
| 29 | `rfqs` | **MUST** | RFQ module |
| 30 | `rfq_items` | **MUST** | RFQ line items |
| 31 | `rfq_suppliers` | **MUST** | `suppliers[]` + `quotesReceived` |
| 32 | `supplier_quotations` | **MUST** | Quotations module |
| 33 | `supplier_quotation_items` | **MUST** | Comparison rows, PO seeding |
| 34 | `quotation_comparisons` | RECOMMENDED | The sourcing decision is currently lost in sessionStorage |
| 35 | `quotation_comparison_lines` | RECOMMENDED | Per-line supplier choice + reason |
| 36 | `purchase_orders` | **MUST** | PO module |
| 37 | `purchase_order_items` | **MUST** | PO lines |
| 38 | `proforma_invoices` | **MUST** | Proforma module |
| 39 | `proforma_invoice_items` | **MUST** | Line-level `poPrice` variance |
| 40 | `goods_receipts` | **MUST** | GRN module |
| 41 | `goods_receipt_items` | **MUST** | ordered/received/accepted/rejected/issue |
| 42 | `supplier_invoices` | **MUST** | Workflow step 7 — **no UI exists yet** |
| 43 | `supplier_invoice_items` | **MUST** | 3-way match |
| 44 | `purchase_returns` / `_items` | RECOMMENDED | GRN rejects goods with nowhere to go |
| 45 | `document_variances` | RECOMMENDED | Proforma-vs-PO card, GRN mismatch panel, 4 alert types |
| 46 | `documents` | **MUST** | AI upload module |
| 47 | `document_links` | **MUST** | One file may back a quotation *and* a proforma |
| 48 | `ai_processing_jobs` | **MUST** | `state/stage/progress` on document rows |
| 49 | `ai_extraction_results` | **MUST** | Extraction review screen |
| 50 | `ai_extracted_fields` | **MUST** | Per-field confidence + provenance |
| 51 | `ai_extracted_lines` | **MUST** | Per-line raw text, match, confidence |
| 52 | `ai_match_candidates` | **MUST** | "Suggestion" + match method/score |
| 53 | `ai_review_actions` | **MUST** | Human approve/reject/override audit |
| 54 | `canonical_fields` | **MUST** | Target vocabulary for schema mapping |
| 55 | `document_schema_mappings` | **MUST** | Requirement STEP 11 (no UI yet) |
| 56 | `document_schema_mapping_fields` | **MUST** | Column → canonical field |
| 57 | `variant_embeddings` | **MUST** | pgvector SKU matching |
| 58 | `assistant_queries` | OPTIONAL | NL assistant logging/eval |
| 59 | `alerts` | **MUST** | Alerts centre |
| 60 | `alert_reads` | RECOMMENDED | "Mark all as read" is per-user |
| 61 | `alert_rules` | OPTIONAL | Settings thresholds drive generation |
| 62 | `audit_logs` | **MUST** | Audit Trail already built client-side |
| 63 | `outbound_messages` | RECOMMENDED | "Send RFQ"/"Send to Supplier" claim an email was sent |
| 64 | `notification_preferences` | OPTIONAL | Settings alert toggles (currently company-level) |

**Explicitly rejected:** a `quotation_comparison` *result* table holding computed totals (compute on read), a generic `entities` EAV table, per-tenant schemas, a separate `sku` table distinct from `product_variants`, and a "current_stock" editable column as the source of truth.

---

## 3. Tenancy and identity tables

### TABLE: `companies`
**Purpose:** A tenant. Owns every other row in the system.

| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes | | Yes | Yes | Tenant id | `0f8c…` |
| name | TEXT | No | | | | | Yes | Legal/business name | `Acme Traders` |
| legal_name | TEXT | Yes | | | | | | Name as on GST registration | `Acme Traders Pvt Ltd` |
| gstin | TEXT | Yes | | | | Yes¹ | Yes | 15-char GSTIN; NULL = unregistered | `23AACCA1234F1Z5` |
| pan | TEXT | Yes | | | | | | 10-char PAN | `AACCA1234F` |
| state_code | TEXT | No | | | | | Yes | 2-digit GST state code; drives IGST vs CGST/SGST | `23` |
| state_name | TEXT | No | | | | | | | `Madhya Pradesh` |
| city | TEXT | Yes | | | | | | | `Indore` |
| address_line1 | TEXT | Yes | | | | | | Registered address | `Plot 14, Scheme 78` |
| address_line2 | TEXT | Yes | | | | | | | `Vijay Nagar` |
| pincode | TEXT | Yes | | | | | | | `452010` |
| email | TEXT | Yes | | | | | | Printed on documents | `orders@acmetraders.in` |
| phone | TEXT | Yes | | | | | | | `+91 731 456 7890` |
| logo_document_id | UUID | Yes | | | documents.id | | | Letterhead logo | |
| plan | TEXT | No | `'Trial'` | | | | Yes | `Trial\|Starter\|Growth\|Enterprise` | `Growth` |
| status | TEXT | No | `'active'` | | | | Yes | `active\|suspended` | `active` |
| suspended_at | TIMESTAMPTZ | Yes | | | | | | Set by Super Admin | |
| suspended_reason | TEXT | Yes | | | | | | | `Non-payment` |
| onboarded_on | DATE | No | CURRENT_DATE | | | | | UI `createdOn` | `2025-01-14` |

¹ `uq_companies_gstin` is a partial unique index `WHERE gstin IS NOT NULL AND deleted_at IS NULL` — one GSTIN cannot register twice as a tenant.
**Note:** `usersCount` shown in the UI is **computed**, not stored.

### TABLE: `company_settings`
**Purpose:** 1:1 configuration for a tenant — every field on `/settings`.

| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|---|
| company_id | UUID | No | | Yes | companies.id | Yes | Yes | 1:1 with tenant | |
| currency_code | TEXT | No | `'INR'` | | | | | ISO-4217 | `INR` |
| default_gst_rate | NUMERIC(5,2) | No | 18.00 | | | | | Settings → Tax | `18.00` |
| rounding_mode | TEXT | No | `'nearest'` | | | | | `nearest\|up\|none` | `nearest` |
| financial_year_start_month | SMALLINT | No | 4 | | | | | India = April | `4` |
| default_godown_id | UUID | Yes | | | godowns.id | | | Pre-selected on forms | |
| ai_auto_process | BOOLEAN | No | true | | | | | "Auto-process uploaded documents" | |
| ai_review_confidence_threshold | NUMERIC(5,2) | No | 90.00 | | | | | "Require review below 90%" | `90.00` |
| ai_suggest_while_typing | BOOLEAN | No | true | | | | | RFQ line AI suggestions | |
| ai_never_autoapprove_financials | BOOLEAN | No | true | | | | | **Locked in UI — enforce server-side too** | `true` |
| low_stock_threshold_mode | TEXT | No | `'reorder'` | | | | | `reorder\|110\|125` (% of reorder point) | `reorder` |
| alert_email_critical | BOOLEAN | No | true | | | | | | |
| alert_daily_low_stock_digest | BOOLEAN | No | true | | | | | | |
| alert_po_delay_notify | BOOLEAN | No | false | | | | | | |
| po_delay_grace_days | SMALLINT | No | 0 | | | | | Days past `expected_delivery_date` before alerting | `2` |
| allow_grn_excess_receipt | BOOLEAN | No | false | | | | | **New:** governs over-receipt (see `06`) | |
| grn_excess_tolerance_pct | NUMERIC(5,2) | No | 0.00 | | | | | | `5.00` |
| require_po_approval_above | NUMERIC(18,2) | Yes | | | | | | Approval threshold; NULL = always require | `100000.00` |
| require_maker_checker | BOOLEAN | No | false | | | | | Approver may not be the creator (BR-PO-03) | `false` |
| allow_negative_stock | BOOLEAN | No | false | | | | | Permits a movement to drive a balance below zero (BR-INV-05) | `false` |
| allow_nonstandard_gst | BOOLEAN | No | false | | | | | Accepts GST rates outside the statutory set, with a warning (BR-MD-08) | `false` |
| inventory_locked_through | DATE | Yes | | | | | | No transaction may be posted or back-dated on or before this date (BR-INV-10). Moved forward when a period is closed | `2026-08-31` |
| variance_price_tolerance_pct | NUMERIC(5,2) | No | 0.00 | | | | | Proforma/invoice price variance allowed without escalation (BR-PF-03) | `1.00` |
| variance_amount_tolerance | NUMERIC(18,2) | No | 0.00 | | | | | Absolute variance allowed | `500.00` |
| comparison_weights | JSONB | No | see `06` | | | | | Recommendation weights for landed cost / delivery / on-time / quality / warranty (BR-CMP-01) | `{"cost":0.5,"delivery":0.2,…}` |

### TABLE: `document_sequences`
**Purpose:** Safe, per-tenant, per-document-type, per-financial-year numbering. Replaces client-side `max+1`.

| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes | | | | | |
| company_id | UUID | No | | | companies.id | | Yes | | |
| doc_type | TEXT | No | | | | | | `rfq\|po\|grn\|proforma\|invoice\|transfer\|return\|adjustment` | `po` |
| financial_year | TEXT | No | | | | | | `2026-27` | `2026-27` |
| prefix | TEXT | No | | | | | | From Settings | `PO-2026-` |
| padding | SMALLINT | No | 5 | | | | | UI uses 5 digits; brief asks 6 — configurable | `5` |
| next_number | BIGINT | No | 1 | | | | | Allocated under `SELECT … FOR UPDATE` | `125` |
| **Unique** | | | | | | `uq_docseq (company_id, doc_type, financial_year)` | | | |

Allocation: `SELECT … FOR UPDATE` inside the same transaction as the insert, or a Postgres advisory lock keyed on `hashtext(company_id||doc_type)`. Never generate numbers in application memory.

### TABLE: `users`
**Purpose:** A person who can sign in. Email is globally unique because the login form has no tenant selector.

| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes | | Yes | Yes | | |
| company_id | UUID | Yes | | | companies.id | | Yes | **NULL ⇒ platform (Super) admin** | |
| email | TEXT | No | | | | Yes | Yes | `uq_users_email` on `lower(email)` | `useradmin@acmetraders.in` |
| username | TEXT | Yes | | | | Yes | Yes | Short login (`superadmin`, `useradmin`) | `useradmin` |
| password_hash | TEXT | Yes | | | | | | Argon2id; NULL until invite accepted | |
| full_name | TEXT | No | | | | | Yes | | `Sharad` |
| phone | TEXT | Yes | | | | | | | |
| role_id | UUID | No | | | roles.id | | Yes | | |
| avatar_document_id | UUID | Yes | | | documents.id | | | | |
| status | TEXT | No | `'invited'` | | | | Yes | `active\|inactive\|invited\|suspended` | `active` |
| is_platform_admin | BOOLEAN | No | false | | | | Yes | Mirrors `company_id IS NULL`; enforced by CHECK | `false` |
| last_login_at | TIMESTAMPTZ | Yes | | | | | | | |
| last_active_at | TIMESTAMPTZ | Yes | | | | | Yes | UI "Last Active" column | |
| failed_login_count | SMALLINT | No | 0 | | | | | Lockout support | |
| locked_until | TIMESTAMPTZ | Yes | | | | | | | |
| password_changed_at | TIMESTAMPTZ | Yes | | | | | | | |
| deleted_at | TIMESTAMPTZ | Yes | | | | | Yes | Soft delete ("Remove user") | |

`CHECK (is_platform_admin = (company_id IS NULL))`.

### TABLE: `roles`
| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes | | | | | |
| company_id | UUID | Yes | | | companies.id | | Yes | NULL = built-in system role shared by all tenants | |
| code | TEXT | No | | | | Yes¹ | Yes | `super_admin\|owner\|purchase_manager\|godown_manager\|accountant\|staff\|viewer` | `purchase_manager` |
| name | TEXT | No | | | | | | Display name | `Purchase Manager` |
| description | TEXT | Yes | | | | | | | |
| is_system | BOOLEAN | No | true | | | | | System roles are not editable | `true` |

¹ `uq_roles_code` = `(COALESCE(company_id,'00000000-…'), code)` — lets a tenant later define a custom role without colliding with system codes.

### TABLE: `permissions` / `role_permissions`
`permissions(id, code UNIQUE, module, description)` — e.g. `po.approve`, `grn.confirm`, `inventory.adjust`, `ai.approve_extraction`, `company.manage_users`. Full list in `07_RBAC_MATRIX.md`.
`role_permissions(role_id, permission_id)` — composite PK, no surrogate key.

### TABLE: `user_godown_access`
**Purpose:** Implements `Member.godown` ("All godowns" vs a named godown). Absence of rows + `has_all_godowns=false` means no stock visibility.

| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description |
|---|---|---|---|---|---|---|---|---|
| user_id | UUID | No | | Yes¹ | users.id | | Yes | |
| godown_id | UUID | No | | Yes¹ | godowns.id | | Yes | |
| can_receive | BOOLEAN | No | true | | | | | Allowed to confirm GRNs here |
| can_adjust | BOOLEAN | No | false | | | | | Allowed to post corrections here |

¹ Composite PK `(user_id, godown_id)`. A convenience flag `users.has_all_godowns BOOLEAN NOT NULL DEFAULT false` avoids fan-out rows for Owners.

### TABLE: `invitations`
| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes | | | | Used in `/accept-invite/{id}` | |
| company_id | UUID | No | | | companies.id | | Yes | | |
| email | TEXT | No | | | | Yes¹ | Yes | | `priya@acmetraders.in` |
| full_name | TEXT | No | | | | | | | `Priya Nair` |
| role_id | UUID | No | | | roles.id | | | | |
| godown_scope | TEXT | No | `'all'` | | | | | `all\|specific` | |
| godown_ids | UUID[] | Yes | | | | | | When scope = specific | |
| token_hash | TEXT | No | | | | Yes | Yes | **Never store the raw token**; the URL id is public, the token is the secret | |
| invited_by | UUID | No | | | users.id | | | | |
| invited_at | TIMESTAMPTZ | No | now() | | | | | | |
| expires_at | TIMESTAMPTZ | No | now()+7d | | | | Yes | **Missing in UI — invites never expire today** | |
| resend_count | SMALLINT | No | 0 | | | | | Shown as "resent 2x" | `2` |
| last_sent_at | TIMESTAMPTZ | Yes | | | | | | | |
| status | TEXT | No | `'pending'` | | | | Yes | `pending\|accepted\|revoked\|expired` | `pending` |
| accepted_at | TIMESTAMPTZ | Yes | | | | | | | |
| accepted_user_id | UUID | Yes | | | users.id | | | | |

¹ Partial unique: one **pending** invite per email per company.

### TABLE: `refresh_tokens` (RECOMMENDED)
`id, user_id, token_hash UNIQUE, issued_at, expires_at, revoked_at, user_agent, ip_address, impersonated_by UUID NULL`. Supports "Keep me signed in" and forced logout on role change/suspension.

### TABLE: `impersonation_sessions` (RECOMMENDED)
**Purpose:** The UI lets a Super Admin *become* a tenant user. That must be provable after the fact.

`id, platform_user_id → users.id, target_user_id → users.id, target_company_id, started_at, ended_at, reason TEXT, ip_address, actions_count`. Every write made while impersonating carries `audit_logs.impersonated_by`.

---

## 4. Master data tables

### TABLE: `categories`
Self-referencing to model the UI's `category` + `subcategory` (e.g. Home Appliances → Cookware).

| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes | | | | | |
| company_id | UUID | No | | | companies.id | | Yes | | |
| parent_id | UUID | Yes | | | categories.id | | Yes | NULL = top level | |
| name | TEXT | No | | | | Yes¹ | Yes | | `Home Appliances` |
| code | TEXT | Yes | | | | | | | `HA` |
| path | TEXT | Yes | | | | | Yes (GiST/`ltree` optional) | Denormalised breadcrumb for fast display | `Home Appliances/Cookware` |
| is_active | BOOLEAN | No | true | | | | | | |
| deleted_at | TIMESTAMPTZ | Yes | | | | | Yes | | |

¹ `uq_categories_name (company_id, parent_id, lower(name)) WHERE deleted_at IS NULL`.

### TABLE: `brands`
`id, company_id, name, code, manufacturer_name, is_active, deleted_at`. Unique `(company_id, lower(name))`.
Note: the mock data treats `manufacturer` (`Stovekraft Ltd`) as separate from `brand` (`Pigeon`) — correct and preserved.

### TABLE: `uoms`
| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes | | | | | |
| company_id | UUID | Yes | | | companies.id | | Yes | NULL = system UoM available to all | |
| code | TEXT | No | | | | Yes | Yes | | `NOS` |
| name | TEXT | No | | | | | | UI strings | `Nos` |
| uom_type | TEXT | No | `'count'` | | | | | `count\|weight\|volume\|length` | `count` |
| decimal_places | SMALLINT | No | 0 | | | | | `Nos` = 0, `Kg` = 3 | `0` |
| is_active | BOOLEAN | No | true | | | | | | |

Seed: Nos, Pack, Pkt, Box, Bag, Set, Kg, Litre, Metre.

### TABLE: `products`
**Purpose:** The catalogue item — the thing a buyer talks about. Stock never attaches here.

| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes | | | | | |
| company_id | UUID | No | | | companies.id | | Yes | | |
| name | TEXT | No | | | | | Yes (trgm) | | `Pigeon Cooker 5L` |
| slug | TEXT | Yes | | | | Yes | | URL-safe | `pigeon-cooker-5l` |
| brand_id | UUID | Yes | | | brands.id | | Yes | | |
| category_id | UUID | Yes | | | categories.id | | Yes | Leaf category = UI subcategory | |
| manufacturer_name | TEXT | Yes | | | | | | | `Stovekraft Ltd` |
| description | TEXT | Yes | | | | | | | |
| hsn_code | TEXT | Yes | | | | | Yes | GST classification; may be overridden per variant | `7615` |
| gst_rate | NUMERIC(5,2) | No | 18.00 | | | | | Default for variants | `18.00` |
| cess_rate | NUMERIC(5,2) | No | 0.00 | | | | | Applies to some appliances/autos | `0.00` |
| tracking_type | TEXT | No | `'none'` | | | | | `none\|batch\|serial` — drives batch capture on GRN | `batch` |
| base_uom_id | UUID | No | | | uoms.id | | | Stock-keeping unit of measure | |
| display_emoji | TEXT | Yes | | | | | | UI `emoji` field | `🍲` |
| is_active | BOOLEAN | No | true | | | | Yes | | |
| deleted_at | TIMESTAMPTZ | Yes | | | | | Yes | Soft delete | |

### TABLE: `product_variants`
**Purpose:** The stockable, orderable, priced unit. **This is the SKU.** Everything in inventory and procurement references `product_variant_id`, never `product_id`.

> **Why split product/variant when the UI is flat?** Three pieces of evidence from the UI itself: (1) `GrnIssue` includes `wrong_variant`, `wrong_model` and `wrong_brand` — the system is expected to tell near-identical items apart; (2) `attributes` (Capacity, Material, Model, Colour, Pack Size) are exactly variant axes; (3) supplier descriptions such as *"SS BOLT M10 X 50MM"* vs *"SS Hex Bolt M10 x 40"* must resolve to different stock rows or the AI matcher will silently merge them. Today's flat products map to one variant each — the UI needs no change on day one.

| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes | | | | | |
| company_id | UUID | No | | | companies.id | | Yes | | |
| product_id | UUID | No | | | products.id ON DELETE RESTRICT | | Yes | | |
| sku | TEXT | No | | | | Yes¹ | Yes | Tenant-scoped SKU | `SKU001` |
| variant_name | TEXT | Yes | | | | | | Distinguishing suffix | `5 Litre / Silver` |
| barcode | TEXT | Yes | | | | Yes¹ | Yes | Scan code | `8901234500011` |
| ean | TEXT | Yes | | | | | Yes | | `8901234500011` |
| upc | TEXT | Yes | | | | | Yes | | |
| mpn | TEXT | Yes | | | | | Yes | Manufacturer part no. | `PGN-PC-5L` |
| model_code | TEXT | Yes | | | | | Yes | Matching-critical | `Favourite 5L` |
| hsn_code | TEXT | Yes | | | | | Yes | Overrides product | `7615` |
| gst_rate | NUMERIC(5,2) | Yes | | | | | | Overrides product | `18.00` |
| uom_id | UUID | No | | | uoms.id | | | Stock UoM | |
| pack_size | NUMERIC(18,3) | Yes | | | | | | e.g. 12 per Box | `1` |
| purchase_price | NUMERIC(18,4) | No | 0 | | | | | Last/standard cost — used for valuation | `1180.0000` |
| sale_price | NUMERIC(18,4) | No | 0 | | | | | | `1490.0000` |
| mrp | NUMERIC(18,4) | No | 0 | | | | | | `1795.0000` |
| reorder_point | NUMERIC(18,3) | No | 0 | | | | Yes | Low-stock trigger | `20` |
| reorder_qty | NUMERIC(18,3) | No | 0 | | | | | Suggested order qty | `50` |
| lead_time_days | SMALLINT | Yes | | | | | | For reorder timing | `7` |
| attributes | JSONB | No | `'{}'` | | | | Yes (GIN) | Free-form axes from UI | `{"Capacity":"5 Litre","Material":"Aluminium"}` |
| search_text | TEXT | Yes | | | | | Yes (trgm) | Generated: name + sku + brand + model + attrs, normalised — feeds fuzzy matching | |
| is_active | BOOLEAN | No | true | | | | Yes | | |
| deleted_at | TIMESTAMPTZ | Yes | | | | | Yes | | |

¹ `uq_variant_sku (company_id, upper(sku)) WHERE deleted_at IS NULL`; `uq_variant_barcode (company_id, barcode) WHERE barcode IS NOT NULL AND deleted_at IS NULL`. **Barcode is unique per tenant, not globally** — two tenants legitimately stock the same EAN. A global barcode registry, if ever wanted, is a separate reference table.

**Removed from the UI model:** `currentStock`, `reserved`, `status`, `godowns[]` are **not columns here**. They are read from `stock_balances` (§5). Keeping them on the variant is what makes the current prototype's inventory fictional.

### TABLE: `product_uom_conversions` (RECOMMENDED)
`id, company_id, product_variant_id, from_uom_id, to_uom_id, factor NUMERIC(18,6), is_purchase_default`. Unique `(product_variant_id, from_uom_id, to_uom_id)`, `CHECK (factor > 0)`.
Needed the first time a supplier quotes "1 Box = 12 Nos" — the UI already offers Box/Bag/Pack/Set as purchase units while stock is kept in Nos.

### TABLE: `product_images` (RECOMMENDED)
`id, company_id, product_id, product_variant_id NULL, document_id → documents.id, sort_order, is_primary`. Backs the empty "Images & Documents" panel.

### TABLE: `godowns`
| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes | | | | | |
| company_id | UUID | No | | | companies.id | | Yes | | |
| name | TEXT | No | | | | Yes | Yes | | `Main Godown` |
| code | TEXT | Yes | | | | Yes | | For document numbering/labels | `MAIN` |
| city | TEXT | Yes | | | | | | | `Indore` |
| state_code | TEXT | Yes | | | | | | Place of supply for receipts | `23` |
| address | TEXT | Yes | | | | | | | |
| gstin | TEXT | Yes | | | | | | Additional place of business | |
| incharge_user_id | UUID | Yes | | | users.id | | Yes | UI "In-charge" | |
| capacity_value | NUMERIC(18,3) | Yes | | | | | | For `capacityUsed` % | `10000` |
| capacity_uom_id | UUID | Yes | | | uoms.id | | | | |
| is_default | BOOLEAN | No | false | | | | | | |
| is_active | BOOLEAN | No | true | | | | Yes | | |
| deleted_at | TIMESTAMPTZ | Yes | | | | | Yes | | |

`skus`, `value` and `capacityUsed` shown on the Godowns page are **computed** from `stock_balances`.

### TABLE: `suppliers`
| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes | | | | | |
| company_id | UUID | No | | | companies.id | | Yes | | |
| name | TEXT | No | | | | Yes¹ | Yes (trgm) | | `Reliance Retail Ltd` |
| supplier_code | TEXT | Yes | | | | Yes | | Internal code | `SUP-0007` |
| gstin | TEXT | Yes | | | | Yes¹ | Yes | NULL ⇒ unregistered | `27AABCR5678M1ZP` |
| pan | TEXT | Yes | | | | | | | |
| gst_treatment | TEXT | No | `'regular'` | | | | | `regular\|composition\|unregistered\|overseas` | `regular` |
| supplier_type | TEXT | No | | | | | Yes | `Manufacturer\|Distributor\|Online\|Local Supplier\|Importer` | `Distributor` |
| city | TEXT | Yes | | | | | Yes | | `Mumbai` |
| state_code | TEXT | Yes | | | | | Yes | **Drives IGST vs CGST/SGST** | `27` |
| state_name | TEXT | Yes | | | | | | | `Maharashtra` |
| address | TEXT | Yes | | | | | | | |
| pincode | TEXT | Yes | | | | | | | |
| primary_contact_name | TEXT | Yes | | | | | | UI `contactPerson` | `Rajeev Menon` |
| phone | TEXT | Yes | | | | | | | |
| email | TEXT | Yes | | | | | Yes | Where RFQs/POs are sent | |
| payment_terms | TEXT | Yes | | | | | | Free text today; see note | `30 Days` |
| payment_terms_days | SMALLINT | Yes | | | | | | Parsed numeric form for ageing | `30` |
| credit_limit | NUMERIC(18,2) | Yes | | | | | | FUTURE | |
| bank_name / bank_account_no / bank_ifsc | TEXT | Yes | | | | | | From proforma bank block | `HDFC0000060` |
| status | TEXT | No | `'active'` | | | | Yes | `active\|inactive` | `active` |
| notes | TEXT | Yes | | | | | | | |
| deleted_at | TIMESTAMPTZ | Yes | | | | | Yes | | |

¹ `uq_supplier_name (company_id, lower(name)) WHERE deleted_at IS NULL`; `uq_supplier_gstin (company_id, gstin) WHERE gstin IS NOT NULL AND deleted_at IS NULL`.
**Computed, not stored:** `productsSupplied`, `totalPurchases`, `openOrders`, `onTimeDelivery`, `qualityScore`. These are analytics over POs/GRNs — see `supplier_performance` view in §9.

### TABLE: `supplier_contacts`
`id, company_id, supplier_id, name, designation, phone, email, is_primary, is_active`. Unique `(supplier_id, lower(email)) WHERE email IS NOT NULL`.

### TABLE: `supplier_products`
**Purpose:** The supplier's own code and price for one of our SKUs. This is what makes AI matching converge over time — once `RR-PGN-5L` is confirmed as `SKU001`, it never needs the LLM again.

| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes | | | | | |
| company_id | UUID | No | | | companies.id | | Yes | | |
| supplier_id | UUID | No | | | suppliers.id | | Yes | | |
| product_variant_id | UUID | No | | | product_variants.id | | Yes | | |
| supplier_sku | TEXT | Yes | | | | Yes¹ | Yes | Supplier's code | `RR-PGN-5L` |
| supplier_description | TEXT | Yes | | | | | Yes (trgm) | Raw text as the supplier writes it | `PIGEON PRESSURE COOKER 5 LTR FAVOURITE` |
| supplier_uom_id | UUID | Yes | | | uoms.id | | | Supplier sells in Box | |
| conversion_to_base | NUMERIC(18,6) | No | 1 | | | | | Box → Nos | `12` |
| last_quoted_price | NUMERIC(18,4) | Yes | | | | | | Feeds low-stock `lastPrice` | `1100.0000` |
| last_quoted_at | DATE | Yes | | | | | | | |
| last_purchase_price | NUMERIC(18,4) | Yes | | | | | | From most recent PO | |
| last_purchase_at | DATE | Yes | | | | | | | |
| lead_time_days | SMALLINT | Yes | | | | | | | `4` |
| is_preferred | BOOLEAN | No | false | | | | Yes | Drives "Preferred Supplier" on low-stock | `true` |
| match_source | TEXT | No | `'manual'` | | | | | `manual\|ai_confirmed\|imported` — provenance of the mapping itself | `ai_confirmed` |
| confirmed_by | UUID | Yes | | | users.id | | | Who approved the AI match | |
| confirmed_at | TIMESTAMPTZ | Yes | | | | | | | |

¹ `uq_supplier_sku (company_id, supplier_id, upper(supplier_sku)) WHERE supplier_sku IS NOT NULL`. One supplier code maps to exactly one variant; one variant may have many supplier codes (M:N via this table).

---

## 5. Inventory data model — the critical section

### 5.1 Principle

> **`inventory_transactions` is the only source of truth for stock. Nothing else may be written to change a quantity.**

Current stock for any dimension is, by definition:

```sql
SELECT SUM(quantity)
FROM   inventory_transactions
WHERE  company_id = :company
  AND  product_variant_id = :variant
  AND  godown_id = :godown
  AND  (batch_id = :batch OR :batch IS NULL);
```

The prototype violates this in two places that must be corrected before backend work starts: the Product edit dialog writes `currentStock` directly, and confirming a GRN posts nothing. Both are addressed in `06_BUSINESS_RULES.md` (rules BR-INV-01, BR-GRN-06).

### 5.2 TABLE: `inventory_transactions`

**Purpose:** Append-only, signed-quantity stock ledger. Every physical movement, in or out, for any reason.

| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes | | | | | |
| company_id | UUID | No | | | companies.id | | Yes | | |
| txn_number | TEXT | No | | | | Yes¹ | Yes | Human reference (`TRF-2026-00034`) | `GRN-2026-00091` |
| txn_type | TEXT | No | | | | | Yes | See §5.3 | `GOODS_RECEIPT` |
| txn_date | TIMESTAMPTZ | No | now() | | | | Yes | When the movement physically happened (back-dating allowed within an open period) | `2026-09-13T11:20:00+05:30` |
| product_variant_id | UUID | No | | | product_variants.id | | Yes | | |
| godown_id | UUID | No | | | godowns.id | | Yes | | |
| batch_id | UUID | Yes | | | batches.id | | Yes | Required when `products.tracking_type='batch'` | |
| quantity | NUMERIC(18,3) | No | | | | | | **Signed.** Always expressed in the variant's base UoM | `30.000` / `-4.000` |
| uom_id | UUID | No | | | uoms.id | | | Base UoM at time of posting (denormalised for history) | |
| entered_quantity | NUMERIC(18,3) | Yes | | | | | | As typed by the user, before conversion | `2.000` |
| entered_uom_id | UUID | Yes | | | uoms.id | | | e.g. Box | |
| conversion_factor | NUMERIC(18,6) | Yes | | | | | | Applied factor, frozen for audit | `12` |
| unit_cost | NUMERIC(18,4) | Yes | | | | | | Cost at movement — enables valuation and COGS later | `2800.0000` |
| source_type | TEXT | Yes | | | | | Yes | `goods_receipt\|purchase_return\|stock_transfer\|adjustment\|sales_issue\|opening` | `goods_receipt` |
| source_id | UUID | Yes | | | (polymorphic) | | Yes | Id of the source document | |
| source_line_id | UUID | Yes | | | (polymorphic) | | | Id of the source line | |
| counterpart_txn_id | UUID | Yes | | | inventory_transactions.id | | Yes | Links TRANSFER_OUT ↔ TRANSFER_IN | |
| reverses_txn_id | UUID | Yes | | | inventory_transactions.id | | Yes | Reversal entry (corrections never delete) | |
| reason_code | TEXT | Yes | | | | | | `damaged_in_transit\|expired\|count_variance\|theft\|sample` | `count_variance` |
| remarks | TEXT | Yes | | | | | | **UI captures this then throws it away today** | `2 units short` |
| performed_by | UUID | No | | | users.id | | Yes | | |
| posted_at | TIMESTAMPTZ | No | now() | | | | Yes | When the row was written (≠ txn_date) | |

¹ `uq_txn_number (company_id, txn_number, product_variant_id, godown_id, txn_type)` — one reference legitimately covers many lines (a GRN posts one row per accepted line), so the number alone is not unique.

**Immutability:** a `BEFORE UPDATE OR DELETE` trigger raises an exception. Corrections are new rows with `reverses_txn_id` set. This is what makes the ledger auditable.

**`CHECK (quantity <> 0)`** and the sign rule:

```sql
CHECK (
  (txn_type IN ('OPENING_STOCK','GOODS_RECEIPT','TRANSFER_IN','SALES_RETURN')      AND quantity > 0) OR
  (txn_type IN ('TRANSFER_OUT','SALES_ISSUE','DAMAGE','PURCHASE_RETURN','EXPIRY_WRITE_OFF') AND quantity < 0) OR
  (txn_type  =  'STOCK_CORRECTION')
)
```

### 5.3 Transaction types

| Code | Sign | Raised by | In UI today |
|---|---|---|---|
| `OPENING_STOCK` | + | Onboarding import | ✗ new |
| `GOODS_RECEIPT` | + | GRN confirmation (accepted qty only) | ✓ |
| `PURCHASE_RETURN` | − | Purchase return / debit note | ✗ new |
| `TRANSFER_OUT` | − | Stock transfer (source godown) | ✓ |
| `TRANSFER_IN` | + | Stock transfer (destination godown) | ✓ |
| `SALES_ISSUE` | − | Sales/dispatch (external today) | ✓ |
| `SALES_RETURN` | + | Customer return | ✗ new |
| `DAMAGE` | − | Damage write-off | ✓ |
| `EXPIRY_WRITE_OFF` | − | Batch expiry | ✗ new |
| `STOCK_CORRECTION` | ± | Physical count adjustment | ✓ |

**Rejected quantities on a GRN never post a transaction** — rejected goods were never accepted into stock. If they were physically taken in and later sent back, that is `GOODS_RECEIPT` (+) followed by `PURCHASE_RETURN` (−), which is a deliberate, visible sequence rather than a silent adjustment.

### 5.4 TABLE: `stock_balances` — materialised cache

**Is it necessary?** Yes. Six screens (dashboard, current stock, by-godown, low-stock, product detail, PO/GRN forms) read stock on every page load, and the low-stock query needs `balance < reorder_point` across the whole catalogue. Summing an append-only ledger that grows by thousands of rows per day per tenant is an O(n) scan per SKU. The cache is not an optimisation to defer — the low-stock screen is unimplementable without it at realistic data volumes.

| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description |
|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes | | | | |
| company_id | UUID | No | | | companies.id | | Yes | |
| product_variant_id | UUID | No | | | product_variants.id | Yes¹ | Yes | |
| godown_id | UUID | No | | | godowns.id | Yes¹ | Yes | |
| batch_id | UUID | Yes | | | batches.id | Yes¹ | Yes | |
| quantity | NUMERIC(18,3) | No | 0 | | | | Yes | Σ ledger |
| reserved_quantity | NUMERIC(18,3) | No | 0 | | | | | Σ open reservations (0 until Sales Orders exist) |
| available_quantity | NUMERIC(18,3) | — | — | | | | Yes | **Generated column** `quantity - reserved_quantity` |
| avg_cost | NUMERIC(18,4) | Yes | | | | | | Reserved for weighted-average costing (Phase 2) |
| last_txn_at | TIMESTAMPTZ | Yes | | | | | | |
| last_recalculated_at | TIMESTAMPTZ | Yes | | | | | | Set by the reconciliation job |

¹ `uq_stock_balance (company_id, product_variant_id, godown_id, COALESCE(batch_id,'00000000-0000-0000-0000-000000000000'::uuid))`.

**Maintenance:** updated in the *same database transaction* as the ledger insert —

```sql
INSERT INTO stock_balances (company_id, product_variant_id, godown_id, batch_id, quantity, last_txn_at)
VALUES (...)
ON CONFLICT (company_id, product_variant_id, godown_id, COALESCE(batch_id, '000…'))
DO UPDATE SET quantity = stock_balances.quantity + EXCLUDED.quantity,
              last_txn_at = EXCLUDED.last_txn_at;
```

Never via an eventual-consistency queue: a user who confirms a GRN must see the new stock immediately. A nightly Celery job re-derives every balance from the ledger and writes a discrepancy alert if they differ — that job is the proof the cache is honest.

**Valuation:** Phase 1 values stock at `product_variants.purchase_price` (standard cost), exactly as the UI does today (`value = qty × purchasePrice`). `avg_cost` exists so moving-average costing can be switched on without a schema migration.

### 5.5 TABLE: `batches` (RECOMMENDED)

`id, company_id, product_variant_id, batch_number, supplier_batch_number, manufactured_on DATE, expires_on DATE, mrp, received_on, goods_receipt_item_id, is_quarantined BOOLEAN`.
Unique `(company_id, product_variant_id, batch_number)`. Index `(company_id, expires_on) WHERE expires_on IS NOT NULL` for the expiry alert job.

Include this in the first migration even though no UI exists. Retrofitting `batch_id` into a populated ledger later means either rewriting history or accepting that pre-batch stock is untraceable — and the catalogue already contains atta, edible oil, tea and namkeen, where expiry is a legal matter, while `GrnIssue` already includes `expired`.

### 5.6 TABLE: `stock_transfers` (RECOMMENDED) + `stock_transfer_items`

The UI's transfer dialog already emits two ledger rows sharing one `TRF-` reference. A header record makes the movement a first-class document that can be approved, printed as a delivery challan (a legal requirement for inter-state stock movement in India) and tracked in transit.

`stock_transfers(id, company_id, transfer_number, transfer_date, from_godown_id, to_godown_id, status[draft|in_transit|received|cancelled], dispatched_by, received_by, vehicle_number, lr_number, eway_bill_number, remarks)`
`stock_transfer_items(id, transfer_id, product_variant_id, batch_id, quantity, uom_id, dispatched_qty, received_qty)`

`CHECK (from_godown_id <> to_godown_id)` — the dialog already enforces this client-side.

### 5.7 TABLE: `inventory_reservations` (FUTURE)

`id, company_id, product_variant_id, godown_id, batch_id, quantity, reserved_for_type, reserved_for_id, expires_at, status`.

**Honest finding:** `reserved` and "Available = qty − reserved" appear on four screens, but nothing in the application can create a reservation — there are no sales orders. Ship Phase 1 with `reserved_quantity` permanently 0 and this table unbuilt; build it with Sales Orders in Phase 2. Do not invent a reservation source to justify the column.

### 5.8 TABLE: `variant_godown_policies` (OPTIONAL)

`(company_id, product_variant_id, godown_id, reorder_point, reorder_qty, max_stock, is_stocked)`. The UI currently keeps one reorder point per SKU while showing stock per godown — which means a SKU healthy in Indore and empty in Pune reports a single ambiguous status. Adding per-godown policy resolves that; until then the low-stock rule is evaluated per godown against the global reorder point (which is what the mock data does).

### 5.9 Unit of measure and conversion

Stock is **always** stored in the variant's base UoM. Conversion happens once, at entry, and both the entered and converted values are frozen on the transaction row (`entered_quantity`, `entered_uom_id`, `conversion_factor`). Rules: conversion factors are per variant (a "Box" of cookers ≠ a "Box" of bolts); a purchase document may only use a UoM for which a conversion exists; changing a factor never rewrites history because the factor is copied onto each transaction.

---

## 6. Procurement workflow model

### 6.1 Chain of custody

```
rfqs ──< rfq_items
  │            ▲
  │            └──────────────┐ (rfq_item_id)
  └──< rfq_suppliers          │
           │                  │
           ▼                  │
supplier_quotations ──< supplier_quotation_items
           │                          │
           ▼                          │ (quotation_item_id)
quotation_comparisons ──< quotation_comparison_lines
           │
           ▼
purchase_orders ──< purchase_order_items ◄──────┐
           │                   ▲                │
           ├──> proforma_invoices ──< proforma_invoice_items (po_item_id)
           ├──> goods_receipts ──< goods_receipt_items (po_item_id) ──> inventory_transactions
           └──> supplier_invoices ──< supplier_invoice_items (po_item_id, grn_item_id)
```

Every arrow is a real foreign key. The prototype's string-number links (`linkedRfq`, `poNumber`) become FKs; the human-readable number stays as a display column.

### 6.2 TABLE: `rfqs`

| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes | | | | | |
| company_id | UUID | No | | | companies.id | | Yes | | |
| rfq_number | TEXT | No | | | | Yes¹ | Yes | | `RFQ-2026-00057` |
| rfq_date | DATE | No | CURRENT_DATE | | | | Yes | **UI discards user edits to this — fix** | `2026-09-10` |
| expected_delivery_date | DATE | Yes | | | | | | | `2026-09-20` |
| subject | TEXT | Yes | | | | | Yes (trgm) | | `Kitchen and Home Appliances — Sep 2026` |
| delivery_godown_id | UUID | Yes | | | godowns.id | | | UI "Deliver To" | |
| notes | TEXT | Yes | | | | | | Terms sent to suppliers | |
| status | TEXT | No | `'draft'` | | | | Yes | §11 RFQ status | `sent` |
| sent_at | TIMESTAMPTZ | Yes | | | | | | | |
| closed_at | TIMESTAMPTZ | Yes | | | | | | | |
| estimated_value | NUMERIC(18,2) | No | 0 | | | | | Σ qty × expected_price, recomputed on save | `124500.00` |
| created_from | TEXT | Yes | | | | | | `manual\|low_stock` — the low-stock handoff | `low_stock` |
| row_version | INTEGER | No | 1 | | | | | | |

¹ `uq_rfq_number (company_id, rfq_number)`.
**Computed, not stored:** `items` (count), `quotesReceived` (count of quotations).

### 6.3 TABLE: `rfq_items`

`id, company_id, rfq_id → rfqs.id ON DELETE CASCADE, line_no SMALLINT, product_variant_id UUID NULL, description TEXT NOT NULL, quantity NUMERIC(18,3) CHECK (>0), uom_id, expected_price NUMERIC(18,4) DEFAULT 0, target_delivery_date DATE NULL, remarks TEXT`.

`product_variant_id` is **nullable by design**: the RFQ form lets a buyer type a free-text description with an AI suggestion they may ignore. Unique `(rfq_id, line_no)`.

### 6.4 TABLE: `rfq_suppliers`

**Purpose:** M:N between an RFQ and the suppliers it was sent to, plus per-supplier dispatch state. This is what makes `quotesReceived` and "2 of 3 replied" real.

`id, company_id, rfq_id, supplier_id, supplier_contact_id NULL, sent_at, sent_channel[email|whatsapp|manual|portal], outbound_message_id NULL, status[pending|sent|failed|viewed|quoted|declined], responded_at, decline_reason`.
Unique `(rfq_id, supplier_id)`.

### 6.5 TABLE: `supplier_quotations`

| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes | | | | | |
| company_id | UUID | No | | | companies.id | | Yes | | |
| quotation_number | TEXT | No | | | | Yes¹ | Yes | **Supplier's** number, not ours | `QT-RR-3391` |
| supplier_id | UUID | No | | | suppliers.id | | Yes | | |
| rfq_id | UUID | Yes | | | rfqs.id | | Yes | Unsolicited quotes/rate lists have none | |
| quotation_date | DATE | No | | | | | Yes | | `2026-09-11` |
| valid_until | DATE | Yes | | | | | Yes | Drives the expiry alert & `expired` status | `2026-09-25` |
| currency_code | TEXT | No | `'INR'` | | | | | | |
| subtotal / discount_amount / taxable_value / tax_amount / freight_amount / other_charges / round_off / total_amount | NUMERIC(18,2) | No | 0 | | | | | Backend-computed | `124500.00` |
| payment_terms | TEXT | Yes | | | | | | | `30 days credit` |
| delivery_terms | TEXT | Yes | | | | | | | `FOR Indore` |
| delivery_period_days | SMALLINT | Yes | | | | | | Comparison "Delivery period" | `4` |
| warranty_terms | TEXT | Yes | | | | | | Comparison row | `2 years` |
| freight_terms | TEXT | Yes | | | | | | Comparison row | `Free (FOR)` |
| source | TEXT | No | `'manual'` | | | | Yes | `ai_extracted\|manual\|email\|portal` | `ai_extracted` |
| document_id | UUID | Yes | | | documents.id | | Yes | The original file | |
| ai_extraction_result_id | UUID | Yes | | | ai_extraction_results.id | | | Traceability to the AI run | |
| extraction_confidence | NUMERIC(5,2) | Yes | | | | | | Shown as a confidence meter | `96.00` |
| status | TEXT | No | `'draft'` | | | | Yes | §11 | `under_review` |
| approved_by / approved_at | UUID / TIMESTAMPTZ | Yes | | | users.id | | | Human approval of an AI extraction | |
| rejected_reason | TEXT | Yes | | | | | | | |
| row_version | INTEGER | No | 1 | | | | | | |

¹ `uq_quotation (company_id, supplier_id, upper(quotation_number))` — the same number from two suppliers is fine; the same number twice from one supplier is a duplicate upload.

### 6.6 TABLE: `supplier_quotation_items`

`id, company_id, quotation_id ON DELETE CASCADE, line_no, rfq_item_id NULL, product_variant_id NULL, raw_description TEXT, supplier_sku TEXT, quantity, uom_id, unit_price NUMERIC(18,4), discount_pct, gst_rate, cess_rate, line_net, line_tax, line_total, is_available BOOLEAN DEFAULT true, availability_note TEXT, lead_time_days, match_confidence NUMERIC(5,2), match_method TEXT, provenance TEXT`.

`is_available` + `availability_note` come straight from `ComparisonCell.available` / `note` ("Not stocked"). `provenance` carries the UI's `ai_extracted|ai_suggested|needs_review|user_approved|calculated` so the review screen can be rebuilt from the database.

### 6.7 TABLES: `quotation_comparisons`, `quotation_comparison_lines` (RECOMMENDED)

Today the sourcing decision — *"we split this RFQ across Reliance and LG because of price and warranty"* — lives in `sessionStorage` and is destroyed on navigation. That decision is exactly what an auditor or a new purchase manager needs six months later.

`quotation_comparisons(id, company_id, rfq_id, name, compared_supplier_ids UUID[], strategy[lowest_price|split_optimal|manual], single_supplier_best_total, split_total, projected_savings, decided_by, decided_at, status[draft|decided|converted|discarded], notes)`

`quotation_comparison_lines(id, comparison_id, rfq_item_id, product_variant_id, quantity, selected_quotation_item_id, selected_supplier_id, recommended_quotation_item_id, recommendation_reason, recommendation_score NUMERIC(6,3), price_spread_pct, override_reason)`

`recommendation_reason` and `recommendation_score` are **backend-computed** (see `06`, BR-CMP-01) — in the prototype they are hardcoded strings.

### 6.8 TABLE: `purchase_orders`

| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes | | | | | |
| company_id | UUID | No | | | companies.id | | Yes | | |
| po_number | TEXT | No | | | | Yes | Yes | | `PO-2026-00123` |
| supplier_id | UUID | No | | | suppliers.id | | Yes | | |
| rfq_id | UUID | Yes | | | rfqs.id | | Yes | UI `linkedRfq` (string today) | |
| quotation_id | UUID | Yes | | | supplier_quotations.id | | Yes | Accepted quotation | |
| comparison_id | UUID | Yes | | | quotation_comparisons.id | | | Sourcing decision that produced it | |
| po_date | DATE | No | CURRENT_DATE | | | | Yes | | `2026-09-10` |
| expected_delivery_date | DATE | Yes | | | | | Yes | Drives the delay alert | `2026-09-25` |
| delivery_godown_id | UUID | No | | | godowns.id | | Yes | UI "Deliver To" | |
| delivery_address_override | TEXT | Yes | | | | | | Drop-ship | |
| payment_terms | TEXT | Yes | | | | | | `Advance\|15 Days\|30 Days\|45 Days\|Cash on Delivery` | `30 Days` |
| delivery_terms | TEXT | Yes | | | | | | `FOR\|Ex-Works\|Door Delivery\|To Pay` | `FOR` |
| place_of_supply_state_code | TEXT | No | | | | | | Copied from delivery godown at creation | `23` |
| is_inter_state | BOOLEAN | No | | | | | | `supplier.state_code <> place_of_supply` — **UI hardcodes true** | `true` |
| currency_code | TEXT | No | `'INR'` | | | | | | |
| subtotal | NUMERIC(18,2) | No | 0 | | | | | Σ qty × price | `341720.00` |
| discount_amount | NUMERIC(18,2) | No | 0 | | | | | | |
| taxable_value | NUMERIC(18,2) | No | 0 | | | | | subtotal − discount | |
| cgst_amount / sgst_amount / igst_amount / cess_amount | NUMERIC(18,2) | No | 0 | | | | | Mutually exclusive by `is_inter_state` | |
| freight_amount | NUMERIC(18,2) | No | 0 | | | | | Untaxed in current logic — see `09` | `0.00` |
| other_charges | NUMERIC(18,2) | No | 0 | | | | | | |
| round_off | NUMERIC(18,2) | No | 0 | | | | | | `0.20` |
| total_amount | NUMERIC(18,2) | No | 0 | | | | Yes | **Single authoritative total** | `341720.00` |
| status | TEXT | No | `'draft'` | | | | Yes | §11 PO status | `sent` |
| approved_by / approved_at | UUID / TIMESTAMPTZ | Yes | | | users.id | | | | |
| sent_at | TIMESTAMPTZ | Yes | | | | | | | |
| sent_to_email | TEXT | Yes | | | | | | | |
| cancelled_at / cancelled_by / cancellation_reason | | Yes | | | users.id | | | POs are cancelled, never deleted | |
| received_pct | NUMERIC(5,2) | No | 0 | | | | | Denormalised fulfilment % — recomputed on every GRN confirm | `80.00` |
| fully_received_at | TIMESTAMPTZ | Yes | | | | | | | |
| row_version | INTEGER | No | 1 | | | | | | |

### 6.9 TABLE: `purchase_order_items`

| Column | Type | Nullable | Default | Description |
|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | |
| company_id | UUID | No | | |
| purchase_order_id | UUID | No | | FK, `ON DELETE CASCADE` |
| line_no | SMALLINT | No | | Unique with PO |
| product_variant_id | UUID | No | | FK — **not nullable**: you cannot order what is not in the catalogue |
| quotation_item_id | UUID | Yes | | Price provenance |
| rfq_item_id | UUID | Yes | | Demand provenance |
| description | TEXT | Yes | | Printed description (may differ from catalogue name) |
| hsn_code | TEXT | Yes | | Snapshot at order time |
| quantity | NUMERIC(18,3) | No | | `CHECK (> 0)` |
| uom_id | UUID | No | | Ordering UoM |
| conversion_factor | NUMERIC(18,6) | No | 1 | To base UoM |
| unit_price | NUMERIC(18,4) | No | | |
| discount_pct | NUMERIC(5,2) | No | 0 | `CHECK (0–100)` |
| discount_amount | NUMERIC(18,2) | No | 0 | |
| gst_rate | NUMERIC(5,2) | No | | Snapshot |
| cess_rate | NUMERIC(5,2) | No | 0 | |
| line_net | NUMERIC(18,2) | No | | `qty×price − discount` |
| line_tax | NUMERIC(18,2) | No | | |
| line_total | NUMERIC(18,2) | No | | |
| received_quantity | NUMERIC(18,3) | No | 0 | Σ accepted on confirmed GRNs — **maintained by the GRN confirm transaction** |
| returned_quantity | NUMERIC(18,3) | No | 0 | Σ purchase returns |
| invoiced_quantity | NUMERIC(18,3) | No | 0 | Σ invoiced |
| pending_quantity | NUMERIC(18,3) | — | — | Generated: `quantity − received_quantity` |
| line_status | TEXT | No | `'open'` | `open\|partially_received\|received\|short_closed\|cancelled` |
| expected_delivery_date | DATE | Yes | | Per-line schedule |

**Partial delivery** is handled entirely here: `received_quantity` accumulates across GRNs; the PO's status is derived from the aggregate (`06`, BR-PO-05). The example from the brief — PO 100, GRN₁ 60, GRN₂ 40 — produces `received_quantity` 60 → 100 and `line_status` `partially_received` → `received`. **`short_closed`** covers the real-world case where a supplier will never ship the balance and the buyer closes the line deliberately; without it, POs stay open forever, which is exactly what happens in the prototype.

### 6.10 TABLE: `proforma_invoices`

A proforma is **not** a statutory tax invoice — it is an advance-payment request. It is modelled separately from `supplier_invoices` for that reason, and it carries no input-tax-credit meaning.

| Column | Type | Notes |
|---|---|---|
| id, company_id | UUID | |
| proforma_number | TEXT | Supplier's number, e.g. `PI/RR/2026/4471`. Unique `(company_id, supplier_id, upper(proforma_number))` |
| supplier_id | UUID | FK |
| purchase_order_id | UUID NULL | FK — the UI's `poNumber` string |
| proforma_date | DATE | |
| valid_until | DATE NULL | |
| place_of_supply_state_code, is_inter_state | TEXT / BOOLEAN | |
| subtotal … total_amount | NUMERIC(18,2) | Same money block as PO |
| po_total_snapshot | NUMERIC(18,2) | The PO total at comparison time — drives the "Difference" card |
| variance_amount | NUMERIC(18,2) | Generated: `total_amount − po_total_snapshot` |
| advance_percent | NUMERIC(5,2) NULL | "50% advance against proforma" |
| advance_amount | NUMERIC(18,2) NULL | |
| payment_instructions | TEXT | |
| bank_name, bank_account_no, bank_ifsc, bank_branch | TEXT | From the proforma document block |
| supplier_gstin_snapshot, supplier_address_snapshot | TEXT | Frozen as printed on the document |
| document_id | UUID NULL | Original PDF |
| ai_extraction_result_id | UUID NULL | |
| status | TEXT | `pending\|under_review\|approved\|rejected\|paid\|completed\|cancelled` (matches §11) |
| approved_by, approved_at, query_raised_at, query_note | | "Raise query" button becomes real |

`proforma_invoice_items(id, company_id, proforma_id, line_no, purchase_order_item_id NULL, product_variant_id NULL, description, hsn_code, quantity, uom_id, unit_price, gst_rate, cess_rate, line_net, line_tax, line_total, po_unit_price_snapshot, price_variance_pct)`.

`po_unit_price_snapshot` is the UI's `poPrice` — keep it as a snapshot rather than joining live, because the PO may legitimately be revised afterwards and the variance that was reviewed must stay reproducible.

### 6.11 TABLE: `goods_receipts`

| Column | Type | Notes |
|---|---|---|
| id, company_id | UUID | |
| grn_number | TEXT | `GRN-2026-00091`, unique per company |
| grn_date | DATE | **UI discards edits — fix** |
| supplier_id | UUID | FK |
| purchase_order_id | UUID NULL | FK. Nullable for receipts without a PO (walk-in purchases) |
| godown_id | UUID | FK — where stock lands |
| received_by | UUID | FK users.id (UI holds a free-text name) |
| vehicle_number, transporter_name, lr_number, eway_bill_number | TEXT | All four exist in the UI and are all silently discarded today |
| gate_entry_number, gate_entry_at | TEXT / TIMESTAMPTZ | Common in Indian warehouses; optional |
| supplier_challan_number, supplier_challan_date | TEXT / DATE | Delivery challan reference |
| status | TEXT | `draft\|confirmed\|partially_received\|received\|cancelled` |
| confirmed_by, confirmed_at | UUID / TIMESTAMPTZ | **The moment inventory is posted** |
| cancelled_at, cancelled_by, cancellation_reason | | |
| has_discrepancy | BOOLEAN | Generated on confirm; drives the alert |
| remarks | TEXT | |
| row_version | INTEGER | |

### 6.12 TABLE: `goods_receipt_items`

| Column | Type | Notes |
|---|---|---|
| id, company_id, goods_receipt_id | UUID | CASCADE from header |
| line_no | SMALLINT | |
| purchase_order_item_id | UUID NULL | **The link the prototype lacks** — without it, partial receipt across two GRNs cannot be computed |
| product_variant_id | UUID | FK |
| batch_id | UUID NULL | Required when tracking_type = batch |
| ordered_quantity | NUMERIC(18,3) | Snapshot from the PO line at import |
| previously_received_quantity | NUMERIC(18,3) | Snapshot — makes "short by N" correct on the *second* GRN |
| received_quantity | NUMERIC(18,3) | `CHECK (>= 0)` |
| accepted_quantity | NUMERIC(18,3) | `CHECK (>= 0 AND <= received_quantity)` |
| rejected_quantity | NUMERIC(18,3) | Generated: `received_quantity − accepted_quantity` |
| uom_id, conversion_factor | | |
| unit_price | NUMERIC(18,4) | From the PO line — needed for valuation of the receipt |
| issue_type | TEXT | `none\|short\|excess\|damaged\|expired\|wrong_product\|wrong_variant\|wrong_model\|wrong_brand` |
| expected_variant_id | UUID NULL | For `wrong_product/variant/model/brand`: what *should* have come |
| rejection_reason | TEXT | |
| remarks | TEXT | |
| inventory_transaction_id | UUID NULL | Set on confirm — the proof that stock was posted |

Unique `(goods_receipt_id, line_no)`.

### 6.13 TABLE: `supplier_invoices` — **no UI exists; the workflow requires it**

| Column | Type | Notes |
|---|---|---|
| id, company_id | UUID | |
| invoice_number | TEXT | **Supplier's** invoice number |
| invoice_date | DATE | |
| supplier_id | UUID | FK |
| purchase_order_id | UUID NULL | |
| goods_receipt_id | UUID NULL | Primary GRN (many-to-many handled per line) |
| supplier_gstin, buyer_gstin | TEXT | Snapshots as printed |
| place_of_supply_state_code, is_inter_state | | |
| invoice_type | TEXT | `tax_invoice\|bill_of_supply\|debit_note\|credit_note` |
| subtotal, discount_amount, taxable_value, freight_amount, other_charges, round_off, total_amount | NUMERIC(18,2) | Full money block, same shape as `purchase_orders` |
| cgst_amount | NUMERIC(18,2) | Zero when inter-state |
| sgst_amount | NUMERIC(18,2) | Zero when inter-state |
| igst_amount | NUMERIC(18,2) | Zero when intra-state |
| cess_amount | NUMERIC(18,2) | Statutory split — **this** is the ITC-bearing document |
| tds_amount | NUMERIC(18,2) | Withholding, if applicable |
| eway_bill_number | TEXT | |
| irn, ack_number, ack_date | TEXT/DATE | e-Invoice fields; nullable, used only above the turnover threshold |
| due_date | DATE | Derived from payment terms |
| amount_paid, payment_status | NUMERIC / TEXT | `unpaid\|partially_paid\|paid` (payments themselves: Phase 2) |
| match_status | TEXT | `unmatched\|matched\|variance` — the 3-way match result |
| variance_amount | NUMERIC(18,2) | |
| document_id, ai_extraction_result_id | UUID NULL | |
| status | TEXT | `draft\|under_review\|approved\|disputed\|cancelled` |
| approved_by, approved_at | | |

Unique `(company_id, supplier_id, upper(invoice_number), invoice_date)` — a supplier's invoice number is unique within their own financial year, so the date is part of the key defensively rather than assuming global uniqueness.

`supplier_invoice_items(id, company_id, invoice_id, line_no, purchase_order_item_id NULL, goods_receipt_item_id NULL, product_variant_id NULL, description, hsn_code, quantity, uom_id, unit_price, discount_pct, gst_rate, cess_rate, line_net, line_tax, line_total, po_unit_price_snapshot, price_variance_pct, qty_variance)`.

### 6.14 TABLES: `purchase_returns`, `purchase_return_items` (RECOMMENDED)

The GRN captures `rejected_quantity` and `damaged/expired/wrong_*`, and then the prototype does nothing with it. In reality rejected material is either returned to the supplier (debit note) or scrapped, and either way somebody must be able to answer *"where did those 2 refrigerators go?"*.

`purchase_returns(id, company_id, return_number, return_date, supplier_id, goods_receipt_id, purchase_order_id, godown_id, reason, status[draft|sent|accepted|credited|cancelled], debit_note_number, total_amount, eway_bill_number)`
`purchase_return_items(id, return_id, goods_receipt_item_id, product_variant_id, batch_id, quantity, unit_price, gst_rate, line_total, inventory_transaction_id)`

Only goods that were **accepted into stock** and are later returned post `PURCHASE_RETURN` (−) transactions; goods rejected at the gate never entered stock and so post nothing.

### 6.15 TABLE: `document_variances` (RECOMMENDED)

One table behind four different mismatch screens and four alert types — Proforma-vs-PO, GRN-vs-PO, Invoice-vs-PO, Invoice-vs-GRN.

| Column | Type | Notes |
|---|---|---|
| id, company_id | UUID | |
| variance_type | TEXT | `price\|quantity\|tax\|total\|product\|delivery_date` |
| comparison_kind | TEXT | `proforma_vs_po\|grn_vs_po\|invoice_vs_po\|invoice_vs_grn` |
| base_doc_type, base_doc_id, base_line_id | TEXT/UUID | |
| compare_doc_type, compare_doc_id, compare_line_id | TEXT/UUID | |
| product_variant_id | UUID NULL | |
| base_value, compare_value, difference | NUMERIC(18,4) | |
| difference_pct | NUMERIC(9,4) | |
| severity | TEXT | `info\|warning\|critical` — derived from tolerance settings |
| status | TEXT | `open\|accepted\|disputed\|resolved` |
| resolved_by, resolved_at, resolution_note | | e.g. "supplier agreed to credit" |
| alert_id | UUID NULL | The alert raised for it |

Detected server-side at the moment each document is confirmed, never by the browser.

---

## 7. Indian GST and statutory fields

### 7.1 Which documents carry what

| Document | GST fields carried | Statutory status |
|---|---|---|
| RFQ | none (only HSN for clarity) | Not a tax document. **Do not** add CGST/SGST columns. |
| Supplier Quotation | gst_rate per line, tax totals | Commercial offer, not a tax document |
| Quotation Comparison | derived only | Not a document |
| Purchase Order | HSN, gst_rate, cgst/sgst/igst/cess totals, place of supply | Commercial order; tax shown for budgeting, not ITC |
| **Proforma Invoice** | HSN, rates, tax split, bank details, advance % | **Not a tax invoice.** No ITC. Advance payment may attract its own treatment, which Phase 1 does not model. |
| Goods Receipt | e-way bill, vehicle, LR, challan ref | Movement document, not a tax document |
| **Supplier Invoice** | GSTIN both sides, HSN per line, CGST/SGST/IGST/CESS, place of supply, invoice no. & date, e-way bill, IRN/ACK | **The only ITC-bearing document.** |
| Purchase Return / Debit Note | full tax block | Reverses ITC |

The prototype puts GSTIN, place of supply and a bank block on the *proforma* — correct as a **snapshot of what the supplier printed**, which is why those columns are `*_snapshot` in §6.10 rather than live joins.

### 7.2 Inter-state determination

```
is_inter_state = (supplier.state_code <> place_of_supply_state_code)
place_of_supply_state_code = delivery godown's state_code (goods)
```
- `is_inter_state = true` → `igst_amount = tax`, `cgst = sgst = 0`
- `is_inter_state = false` → `cgst = sgst = tax / 2`, `igst = 0`

Stored, not recomputed on read: the supplier's registration can change later and historical documents must not silently re-split their tax. **The UI hardcodes `interState: true` everywhere** — a Madhya Pradesh buyer purchasing from a Madhya Pradesh supplier is currently taxed wrongly. Logged as a CRITICAL finding in `09`.

### 7.3 Validation formats (enforced in the API layer, mirrored as CHECK constraints)

| Field | Rule |
|---|---|
| GSTIN | `^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$`, 15 chars; first 2 digits must be a valid state code and must equal `state_code`; checksum digit verified in the service layer |
| PAN | `^[A-Z]{5}[0-9]{4}[A-Z]$` — and GSTIN chars 3–12 must equal the PAN when both are present |
| HSN | 4, 6 or 8 digits |
| GST rate | one of 0, 0.25, 3, 5, 12, 18, 28 (CHECK allows any 0–28 to survive rate changes; the API warns on non-standard) |
| E-way bill | 12 digits |
| IFSC | `^[A-Z]{4}0[A-Z0-9]{6}$` |
| Pincode | 6 digits, not starting 0 |

### 7.4 Deliberately out of scope

GSTR-1/2B/3B filing, e-invoice IRN generation, ITC reconciliation against GSTR-2B, TDS/TCS computation, and a general ledger. The UI asks for none of it. `irn`/`ack_number` columns exist only so an e-invoicing integration can be added later without a migration.

---

## 8. Document storage and AI tables

### TABLE: `documents`

**Purpose:** One row per uploaded file. Bytes live in S3; Postgres holds metadata, dedupe hash and processing state.

| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes | | | | | |
| company_id | UUID | No | | | companies.id | | Yes | | |
| original_filename | TEXT | No | | | | | Yes (trgm) | As uploaded | `reliance_quotation_sep26.xlsx` |
| storage_bucket | TEXT | No | | | | | | | `inventoryai-docs-prod` |
| storage_key | TEXT | No | | | | Yes | | `{company}/{yyyy}/{mm}/{uuid}.xlsx` | |
| mime_type | TEXT | No | | | | | | | `application/vnd.openxmlformats-…sheet` |
| file_extension | TEXT | No | | | | | Yes | `xlsx\|xls\|csv\|pdf\|docx\|jpg\|png` | `xlsx` |
| file_size_bytes | BIGINT | No | | | | | | ≤ 20 MB enforced in API | `49152` |
| sha256_hash | TEXT | No | | | | Yes¹ | Yes | **Duplicate detection** | `9f86d0…` |
| page_count | SMALLINT | Yes | | | | | | Sheets or pages | `1` |
| document_type | TEXT | Yes | | | | | Yes | `supplier_quotation\|proforma_invoice\|tax_invoice\|delivery_challan\|rate_list\|price_revision\|purchase_order\|other\|unrecognised` | `supplier_quotation` |
| document_type_confidence | NUMERIC(5,2) | Yes | | | | | | AI classification confidence | `96.00` |
| supplier_id | UUID | Yes | | | suppliers.id | | Yes | NULL = "Not identified" | |
| supplier_confidence | NUMERIC(5,2) | Yes | | | | | | | |
| processing_status | TEXT | No | `'uploaded'` | | | | Yes | §11 | `extracted` |
| processing_stage | TEXT | Yes | | | | | | Human-readable step for the progress bar | `Matching products to your SKUs` |
| processing_progress | SMALLINT | Yes | | | | | | 0–100 | `68` |
| extraction_confidence | NUMERIC(5,2) | Yes | | | | | | Document-level confidence | `96.00` |
| items_found | SMALLINT | Yes | | | | | | | `3` |
| error_code / error_message | TEXT | Yes | | | | | | For `failed` | `UNREADABLE_IMAGE` |
| source | TEXT | No | `'upload'` | | | | | `upload\|email\|api\|whatsapp` | `upload` |
| uploaded_by | UUID | No | | | users.id | | Yes | | |
| uploaded_at | TIMESTAMPTZ | No | now() | | | | Yes | | |
| retention_expires_at | TIMESTAMPTZ | Yes | | | | | Yes | Lifecycle/deletion policy | |
| is_archived | BOOLEAN | No | false | | | | | | |

¹ `uq_document_hash (company_id, sha256_hash)` — **per tenant, not global**. Two tenants uploading the same manufacturer rate card is normal and must not collide. On conflict the API returns the existing document with `duplicate_of` rather than erroring, so the user sees "you already uploaded this on 12 Sep".

### TABLE: `document_links`

**Purpose:** A file may back several business records (one PDF containing a proforma that later becomes an invoice; one Excel with three quotations). Polymorphic M:N.

| Column | Type | Notes |
|---|---|---|
| id, company_id | UUID | |
| document_id | UUID | FK → documents |
| linked_type | TEXT | `rfq\|supplier_quotation\|purchase_order\|proforma_invoice\|goods_receipt\|supplier_invoice\|purchase_return\|product\|supplier\|company` |
| linked_id | UUID | The record id (no DB-level FK — validated in the service layer) |
| link_role | TEXT | `source\|attachment\|signed_copy\|supporting\|logo` |
| linked_by | UUID | users.id |
| linked_at | TIMESTAMPTZ | |

Unique `(document_id, linked_type, linked_id, link_role)`. Index `(company_id, linked_type, linked_id)` — that is the lookup every detail screen performs ("show me this PO's attachments").

> **Why polymorphic rather than six FK columns:** the set of linkable record types grows with every module; a nullable-FK-per-type table reaches a dozen mostly-NULL columns and still needs a CHECK to ensure exactly one is set. The trade-off — no referential integrity from the database — is handled by a service-layer validator and a nightly orphan-detection job.

### AI tables — summary

Fully specified in `08_AI_DATA_MODEL.md`; listed here so the schema inventory is complete.

| Table | Purpose |
|---|---|
| `ai_processing_jobs` | One row per async pipeline run: model, prompt version, cost, tokens, timings, retries, status |
| `ai_extraction_results` | Structured output of one extraction (header JSONB + normalised child rows) |
| `ai_extracted_fields` | Per-field value, confidence, provenance, the user's corrected value |
| `ai_extracted_lines` | Per-line raw description, qty/price/tax, matched variant, confidence, provenance |
| `ai_match_candidates` | Ranked SKU candidates per line with method (`exact_sku`/`supplier_alias`/`barcode`/`trigram`/`embedding`/`llm`) and score |
| `ai_review_actions` | Every human accept/reject/edit with before/after — the audit of AI supervision |
| `canonical_fields` | The controlled vocabulary (`product_description`, `quantity`, `unit_price`, …) |
| `document_schema_mappings` / `_fields` | Supplier + document type → column-to-canonical-field mapping, learned once and reused |
| `variant_embeddings` | `vector(1024)` per variant for semantic matching (pgvector, HNSW index) |
| `assistant_queries` | NL question, resolved intent, generated query plan, latency, feedback |

---

## 8.5 Operations tables — alerts, audit and messaging

### TABLE: `alerts`
**Purpose:** Everything on the Alerts screen and the header badge. Generated by named server-side rules, never by the browser.

| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes | | | | | |
| company_id | UUID | No | | | companies.id | | Yes | | |
| rule_code | TEXT | No | | | | Yes¹ | Yes | Which rule raised it | `LOW_STOCK_BELOW_REORDER` |
| severity | TEXT | No | | | | | Yes | `critical\|high\|medium\|low` | `critical` |
| category | TEXT | No | | | | | Yes | `Inventory\|Procurement\|Goods Receipt\|AI Documents\|System` | `Goods Receipt` |
| title | TEXT | No | | | | | | Short line shown in bold | `Received quantity mismatch` |
| description | TEXT | No | | | | | | Sentence with the specifics | `LG Refrigerator 260L — 10 ordered, 8 received.` |
| reference_type | TEXT | Yes | | | | Yes¹ | Yes | `goods_receipt\|purchase_order\|product_variant\|document\|supplier_quotation\|proforma_invoice\|supplier_invoice\|company` | `goods_receipt` |
| reference_id | UUID | Yes | | | (polymorphic) | Yes¹ | Yes | The record it is about | |
| reference_label | TEXT | Yes | | | | | | Denormalised for display | `GRN-2026-00091` |
| deep_link | TEXT | Yes | | | | | | Frontend route — the UI's `href` | `/goods-receipt/GRN-2026-00091` |
| godown_id | UUID | Yes | | | godowns.id | | Yes | Enables godown-scoped alert visibility | |
| variance_id | UUID | Yes | | | document_variances.id | | | When raised by a variance | |
| status | TEXT | No | `'new'` | | | | Yes | `new\|acknowledged\|resolved\|dismissed` | `new` |
| auto_resolved | BOOLEAN | No | false | | | | | Cleared by the rule rather than by a person | |
| resolved_at | TIMESTAMPTZ | Yes | | | | | | | |
| resolved_by | UUID | Yes | | | users.id | | | | |
| dismissed_at / dismissed_by | TIMESTAMPTZ / UUID | Yes | | | users.id | | | | |
| occurrence_count | INTEGER | No | 1 | | | | | Incremented instead of creating a duplicate | `4` |
| last_occurred_at | TIMESTAMPTZ | No | now() | | | | Yes | | |
| payload | JSONB | Yes | | | | | | Rule-specific numbers for rendering | `{"ordered":10,"received":8}` |

¹ Partial unique `uq_alert_open (company_id, rule_code, reference_type, reference_id) WHERE status IN ('new','acknowledged')` — implements the deduplication rule BR-ALT-02 at the database level, so a badly written job cannot spam the user.

### TABLE: `alert_reads`
**Purpose:** "Mark all as read" means *for me*. Read state is per user, which the prototype keeps in React state and loses on reload.

| Column | Type | Nullable | Default | PK | FK | Index | Description |
|---|---|---|---|---|---|---|---|
| alert_id | UUID | No | | Yes¹ | alerts.id ON DELETE CASCADE | Yes | |
| user_id | UUID | No | | Yes¹ | users.id ON DELETE CASCADE | Yes | |
| read_at | TIMESTAMPTZ | No | now() | | | | |

¹ Composite PK `(alert_id, user_id)`. Unread count = alerts visible to the user with no row here.

### TABLE: `alert_rules` (OPTIONAL — configuration)
**Purpose:** Makes thresholds tenant-editable instead of hardcoded, driven by the Settings page.

`id, company_id, rule_code, is_enabled BOOLEAN, severity_override TEXT NULL, threshold_config JSONB, schedule_cron TEXT NULL, notify_email BOOLEAN, notify_in_app BOOLEAN, recipient_role_codes TEXT[], last_run_at, last_run_status, created_at, updated_at`. Unique `(company_id, rule_code)`.

Seeded rule codes: `LOW_STOCK_BELOW_REORDER`, `OUT_OF_STOCK`, `GRN_QTY_MISMATCH`, `GRN_WRONG_PRODUCT`, `PROFORMA_VARIANCE`, `INVOICE_VARIANCE`, `PO_DELIVERY_DELAYED`, `QUOTATION_EXPIRING`, `AI_LOW_CONFIDENCE`, `DOCUMENT_UNREADABLE`, `BATCH_EXPIRING`, `STOCK_BALANCE_DRIFT`, `AI_BUDGET_THRESHOLD`.

### TABLE: `audit_logs`
**Purpose:** The immutable record of who did what. The frontend has already built the UI for this (`AuditTrail`, Team Activity, Platform Activity) — these are the columns it needs.

| Column | Type | Nullable | Default | PK | FK | Unique | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes¹ | | | | | |
| company_id | UUID | Yes | | | companies.id | | Yes | NULL for platform-level events | |
| entity_type | TEXT | No | | | | | Yes | `purchase_order\|rfq\|goods_receipt\|supplier_quotation\|proforma_invoice\|supplier_invoice\|product\|product_variant\|supplier\|inventory_transaction\|user\|invitation\|company\|document\|ai_extraction\|alert\|settings` | `goods_receipt` |
| entity_id | UUID | Yes | | | (polymorphic) | | Yes | | |
| entity_label | TEXT | Yes | | | | | | Human-readable at the time of the event | `GRN-2026-00091` |
| action | TEXT | No | | | | | Yes | See §11 | `confirmed` |
| description | TEXT | Yes | | | | | | Rendered sentence | `Confirmed receipt — 2 lines, 1 short` |
| actor_user_id | UUID | Yes | | | users.id | | Yes | NULL = system/scheduled job | |
| actor_name | TEXT | Yes | | | | | | Denormalised — survives user deletion | `Sharad` |
| actor_role | TEXT | Yes | | | | | | Role at the time | `Owner` |
| impersonated_by | UUID | Yes | | | users.id | | Yes | Set when a platform admin was acting as the user | |
| before_data | JSONB | Yes | | | | | | Redacted previous state | |
| after_data | JSONB | Yes | | | | | | Redacted new state | |
| changed_fields | JSONB | Yes | | | | | | `["status","total_amount"]` | |
| ip_address | INET | Yes | | | | | | | `103.21.58.9` |
| user_agent | TEXT | Yes | | | | | | | |
| request_id | TEXT | Yes | | | | | Yes | Correlates with application logs | `req_01H…` |
| source | TEXT | No | `'api'` | | | | | `api\|job\|system\|import` | `api` |
| created_at | TIMESTAMPTZ | No | now() | Yes¹ | | | Yes (BRIN) | | |

¹ PK is `(id, created_at)` so the table can be range-partitioned monthly later without a rewrite.
**Grants:** `INSERT` and `SELECT` only — no `UPDATE`, no `DELETE`, enforced by role grants as well as by policy. Written in the same transaction as the change it records. Retained 7 years for anything touching a financial document.

### TABLE: `outbound_messages`
**Purpose:** Proof of what was actually sent when the UI says "the supplier has been emailed a copy".

| Column | Type | Nullable | Default | PK | FK | Index | Description | Example |
|---|---|---|---|---|---|---|---|---|
| id | UUID | No | gen_random_uuid() | Yes | | | | |
| company_id | UUID | No | | | companies.id | Yes | | |
| channel | TEXT | No | `'email'` | | | Yes | `email\|whatsapp\|sms` | `email` |
| message_type | TEXT | No | | | | Yes | `rfq\|purchase_order\|proforma_query\|invitation\|alert_digest\|password_reset\|purchase_return` | `rfq` |
| related_type / related_id | TEXT / UUID | Yes | | | (polymorphic) | Yes | The document it carried | `rfq` |
| supplier_id | UUID | Yes | | | suppliers.id | Yes | | |
| to_address | TEXT | No | | | | Yes | | `sales@reliance.example` |
| cc_addresses | TEXT[] | Yes | | | | | | |
| subject | TEXT | Yes | | | | | | `RFQ-2026-00057 from Acme Traders` |
| body_preview | TEXT | Yes | | | | | First 500 chars — full body not retained | |
| attachment_document_ids | UUID[] | Yes | | | | | The generated PDF | |
| provider | TEXT | Yes | | | | | `ses` | |
| provider_message_id | TEXT | Yes | | | | Yes | For webhook correlation | |
| status | TEXT | No | `'queued'` | | | Yes | `queued\|sent\|delivered\|bounced\|complained\|failed` | `delivered` |
| error_message | TEXT | Yes | | | | | | |
| queued_at / sent_at / delivered_at | TIMESTAMPTZ | Yes | | | | | | |
| sent_by | UUID | Yes | | | users.id | | | |

A bounce flips `rfq_suppliers.status` to `failed` and raises an alert — otherwise a buyer waits for a quotation that was never received.

### TABLE: `notification_preferences` (OPTIONAL)
Per-user overrides of the company defaults: `(user_id, notification_type, in_app BOOLEAN, email BOOLEAN, digest_frequency[immediate|daily|weekly|never])`, PK `(user_id, notification_type)`. Until this exists, `company_settings.alert_*` applies to everyone, which is what the Settings page implies today.

---

## 9. Derived data: views, not columns

Everything the UI shows as a stored number but which is actually an aggregate:

| UI field | Source |
|---|---|
| `product.currentStock`, `product.godowns[]`, `product.status` | `stock_balances` (view `v_variant_stock`) |
| `StockRow.value` | `qty × product_variants.purchase_price` |
| `LowStockItem.suggestedQty`, `.supplier`, `.lastPrice` | `reorder_qty`, `supplier_products.is_preferred`, `supplier_products.last_purchase_price` (view `v_low_stock`) |
| `Rfq.items`, `.quotesReceived`, `.value` | counts/sums over `rfq_items`, `supplier_quotations` |
| `PurchaseOrder.items`, `.received` | count of `purchase_order_items`; `SUM(received_quantity)/SUM(quantity)` |
| `Supplier.productsSupplied/.totalPurchases/.openOrders/.onTimeDelivery/.qualityScore` | view `v_supplier_performance` over POs + GRNs (on-time = confirmed GRN date ≤ PO expected date; quality = 1 − rejected/received) |
| `Godown.skus/.value/.capacityUsed` | `stock_balances` + `godowns.capacity_value` |
| `Company.usersCount` | count of `users` |
| Dashboard KPIs | view `v_dashboard_kpis`, refreshed on read (materialised only if measurement shows it is needed) |

**Rule:** if a number can be derived, derive it — except `purchase_order_items.received_quantity`, `purchase_orders.received_pct` and `stock_balances.quantity`, which are deliberately denormalised because they are read constantly and written transactionally with their source.

---

## 10. Soft delete and lifecycle strategy

| Table group | Strategy | Rationale |
|---|---|---|
| `products`, `product_variants`, `suppliers`, `categories`, `brands`, `godowns`, `uoms` | **Soft delete** (`deleted_at`) + `is_active` | Historical documents reference them forever. `is_active` hides an item from pickers while keeping it valid; `deleted_at` removes it from all normal queries. The UI's Delete button maps to `deleted_at`. |
| `users` | Soft delete + `status='inactive'` | "Remove user" must not orphan `created_by` on 3 years of POs |
| `rfqs`, `purchase_orders`, `supplier_quotations`, `proforma_invoices`, `supplier_invoices`, `purchase_returns` | **Never deleted.** `status='cancelled'` + `cancelled_by/at/reason` | Legal and audit requirement |
| `goods_receipts` | **Never deleted.** Draft → `cancelled`; **confirmed → cannot be cancelled**, only reversed by a correction GRN that posts reversing transactions | The prototype's GRN detail page offers Delete and warns "inventory transactions are not reversed" — that is a data-integrity hole, see `09` |
| `inventory_transactions` | **Append-only.** No update, no delete, ever | Ledger integrity |
| `documents` | Soft delete + S3 lifecycle | A deleted document must not break the record it proved |
| `alerts` | `status='dismissed'` | |
| `audit_logs` | **Immutable, no delete.** Partition + archive | |
| `invitations` | Hard delete allowed before acceptance; otherwise `revoked` | No downstream references |

Blocking rule: a master record may only be soft-deleted when it has **no open transactional references** (open PO lines, non-zero stock). Otherwise the API returns `409 RECORD_IN_USE` with the blocking references listed — far better than the prototype's silent hard delete.

Every query goes through a SQLAlchemy base filter adding `deleted_at IS NULL`; the few reports that need deleted rows opt in explicitly.

---

## 11. Complete enum / status catalogue

All values are `TEXT` + CHECK. UI labels differ where noted.

| Domain | Values | Notes vs UI |
|---|---|---|
| `companies.status` | `active`, `suspended` | as UI |
| `companies.plan` | `Trial`, `Starter`, `Growth`, `Enterprise` | as UI |
| `users.status` | `invited`, `active`, `inactive`, `suspended` | as UI |
| `roles.code` | `super_admin`, `owner`, `purchase_manager`, `godown_manager`, `accountant`, `staff`, `viewer` | **`viewer` is new** (see `07`) |
| `invitations.status` | `pending`, `accepted`, `revoked`, `expired` | `expired` is new |
| `rfqs.status` | `draft`, `sent`, `partially_quoted`, `quoted`, `under_review`, `closed`, `cancelled` | UI uses `draft/sent/under_review/completed`; `completed`→`closed`, and `partially_quoted`/`quoted` replace the manual "2 of 3 replied" text |
| `rfq_suppliers.status` | `pending`, `sent`, `failed`, `viewed`, `quoted`, `declined` | new |
| `supplier_quotations.status` | `draft`, `under_review`, `approved`, `rejected`, `expired`, `superseded`, `converted` | UI has the first five; `converted` marks "a PO was raised from this" |
| `supplier_quotations.source` | `ai_extracted`, `manual`, `email`, `portal` | UI: "AI Extracted"/"Manual Entry" |
| `quotation_comparisons.status` | `draft`, `decided`, `converted`, `discarded` | new |
| `purchase_orders.status` | `draft`, `pending_approval`, `approved`, `sent`, `acknowledged`, `partially_received`, `received`, `closed`, `cancelled` | UI has draft/approved/sent/partially_received/received/completed; `completed`→`closed`; `pending_approval` and `acknowledged` are new |
| `purchase_order_items.line_status` | `open`, `partially_received`, `received`, `short_closed`, `cancelled` | new |
| `proforma_invoices.status` | `pending`, `under_review`, `approved`, `rejected`, `paid`, `completed`, `cancelled` | UI: pending/approved/completed |
| `goods_receipts.status` | `draft`, `confirmed`, `partially_received`, `received`, `cancelled` | UI: draft/partially_received/received/completed |
| `goods_receipt_items.issue_type` | `none`, `short`, `excess`, `damaged`, `expired`, `wrong_product`, `wrong_variant`, `wrong_model`, `wrong_brand` | **exactly as UI** |
| `supplier_invoices.status` | `draft`, `under_review`, `approved`, `disputed`, `cancelled` | new module |
| `supplier_invoices.match_status` | `unmatched`, `matched`, `variance` | new |
| `supplier_invoices.payment_status` | `unpaid`, `partially_paid`, `paid` | new |
| `purchase_returns.status` | `draft`, `sent`, `accepted`, `credited`, `cancelled` | new |
| `inventory_transactions.txn_type` | `OPENING_STOCK`, `GOODS_RECEIPT`, `PURCHASE_RETURN`, `TRANSFER_IN`, `TRANSFER_OUT`, `SALES_ISSUE`, `SALES_RETURN`, `DAMAGE`, `EXPIRY_WRITE_OFF`, `STOCK_CORRECTION` | UI has 6; 4 added |
| `stock_transfers.status` | `draft`, `in_transit`, `received`, `cancelled` | new |
| stock state (computed) | `in_stock`, `low_stock`, `out_of_stock` | as UI |
| `documents.processing_status` | `uploaded`, `queued`, `processing`, `extracted`, `review_required`, `approved`, `rejected`, `failed`, `duplicate` | UI: queued/processing/extracted/approved/failed. `extracted` is labelled **"Needs Review"** in the UI — keep the label, keep the value |
| `documents.document_type` | `supplier_quotation`, `proforma_invoice`, `tax_invoice`, `delivery_challan`, `rate_list`, `price_revision`, `purchase_order`, `other`, `unrecognised` | from UI `docType` strings |
| `ai_processing_jobs.status` | `queued`, `running`, `succeeded`, `failed`, `cancelled`, `dead_letter` | new |
| provenance (fields & lines) | `ai_extracted`, `ai_suggested`, `needs_review`, `user_approved`, `calculated` | **exactly as UI** |
| `ai_match_candidates.match_method` | `exact_sku`, `supplier_alias`, `barcode`, `normalised_rule`, `trigram`, `embedding`, `llm`, `manual` | mirrors the UI's pipeline steps |
| `ai_processing_jobs.job_type` | `extraction`, `classification`, `schema_mapping`, `sku_match`, `embedding`, `assistant` | new |
| `ai_processing_jobs.model_tier` | `small`, `large` | records LLM escalation |
| `ai_extraction_results.review_status` | `pending`, `in_review`, `approved`, `rejected` | new |
| `ai_extracted_lines.final_decision` | `accepted_ai`, `changed`, `new_product`, `skipped` | new |
| `ai_review_actions.action` | `accept`, `edit`, `match`, `unmatch`, `reject_line`, `approve_document`, `reject_document`, `save_alias`, `confirm_mapping` | new |
| `document_schema_mappings.status` | `proposed`, `confirmed`, `deprecated` | new — only `confirmed` mappings are applied |
| `supplier_products.match_source` | `manual`, `ai_confirmed`, `imported` | new |
| `documents.source` | `upload`, `email`, `api`, `whatsapp` | UI only uploads |
| `document_links.link_role` | `source`, `attachment`, `signed_copy`, `supporting`, `logo` | new |
| `inventory_transactions.source_type` | `goods_receipt`, `purchase_return`, `stock_transfer`, `adjustment`, `sales_issue`, `opening` | new |
| `outbound_messages.status` | `queued`, `sent`, `delivered`, `bounced`, `complained`, `failed` | new |
| `outbound_messages.message_type` | `rfq`, `purchase_order`, `proforma_query`, `invitation`, `alert_digest`, `password_reset`, `purchase_return` | new |
| `alerts.severity` | `critical`, `high`, `medium`, `low` | as UI |
| `alerts.category` | `Inventory`, `Procurement`, `Goods Receipt`, `AI Documents`, `System` | UI has 4 |
| `alerts.status` | `new`, `acknowledged`, `resolved`, `dismissed` | **Read state is not here** — it is per user in `alert_reads`, because the UI's "Mark all as read" means *for me* |
| `document_variances.status` | `open`, `accepted`, `disputed`, `resolved` | new |
| `audit_logs.action` | `created`, `updated`, `deleted`, `status_changed`, `approved`, `rejected`, `sent`, `confirmed`, `cancelled`, `logged_in`, `logged_out`, `impersonated`, `exported`, `invited`, `invitation_resent`, `invitation_revoked`, `invitation_accepted`, `removed`, `suspended`, `reactivated` | superset of the UI's client-side actions |

---

## 12. Indexing strategy

**Principle:** every tenant-scoped index starts with `company_id`, because RLS injects that predicate into every query. An index on `status` alone is useless here; `(company_id, status)` is not.

### Core indexes by table

| Table | Index | Why |
|---|---|---|
| `product_variants` | `uq (company_id, upper(sku)) WHERE deleted_at IS NULL` | SKU lookup + uniqueness |
| | `uq (company_id, barcode) WHERE barcode IS NOT NULL` | Scanner lookup |
| | `gin (search_text gin_trgm_ops)` | Fuzzy matching of supplier descriptions |
| | `gin (attributes jsonb_path_ops)` | Attribute filters |
| | `(company_id, product_id)`, `(company_id, is_active)` | Listing |
| `stock_balances` | `uq (company_id, product_variant_id, godown_id, COALESCE(batch_id,…))` | The hot path |
| | `(company_id, godown_id) INCLUDE (quantity)` | By-godown screen |
| | `(company_id, quantity) WHERE quantity <= 0` | Out-of-stock |
| `inventory_transactions` | `(company_id, product_variant_id, godown_id, txn_date DESC)` | Ledger & recalculation |
| | `(company_id, txn_date DESC)` | Transactions screen |
| | `(company_id, source_type, source_id)` | "What did this GRN post?" |
| | `(company_id, txn_type, txn_date DESC)` | Filtered ledger |
| `purchase_orders` | `uq (company_id, po_number)`; `(company_id, status, po_date DESC)`; `(company_id, supplier_id, po_date DESC)`; `(company_id, expected_delivery_date) WHERE status IN ('sent','partially_received')` | Lists, supplier history, delay alerts |
| `purchase_order_items` | `(purchase_order_id, line_no)`; `(company_id, product_variant_id)`; `(company_id, line_status) WHERE line_status IN ('open','partially_received')` | GRN import, pending demand |
| `goods_receipts` | `uq (company_id, grn_number)`; `(company_id, purchase_order_id)`; `(company_id, godown_id, grn_date DESC)` | |
| `goods_receipt_items` | `(company_id, purchase_order_item_id)` | Partial-receipt aggregation |
| `supplier_quotations` | `uq (company_id, supplier_id, upper(quotation_number))`; `(company_id, rfq_id)`; `(company_id, valid_until) WHERE status='approved'` | Comparison, expiry job |
| `supplier_invoices` | `uq (company_id, supplier_id, upper(invoice_number), invoice_date)`; `(company_id, due_date) WHERE payment_status <> 'paid'` | Duplicate detection, payables |
| `rfqs` | `uq (company_id, rfq_number)`; `(company_id, status, rfq_date DESC)` | |
| `suppliers` | `uq (company_id, lower(name))`; `uq (company_id, gstin)`; `gin (name gin_trgm_ops)`; `(company_id, status)` | |
| `documents` | `uq (company_id, sha256_hash)`; `(company_id, processing_status, uploaded_at DESC)`; `(company_id, supplier_id)` | Dedupe, queue, supplier filter |
| `document_links` | `(company_id, linked_type, linked_id)`; `(document_id)` | Attachments panel |
| `supplier_products` | `uq (company_id, supplier_id, upper(supplier_sku))`; `(company_id, product_variant_id)`; `gin (supplier_description gin_trgm_ops)` | Alias matching |
| `variant_embeddings` | `hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)` + `(company_id)` | Semantic search. **Filter by company before ANN**, or use partitioned indexes — an unfiltered ANN search leaks across tenants |
| `alerts` | `(company_id, status, severity, created_at DESC)`; `(company_id, category)` | |
| `audit_logs` | `(company_id, entity_type, entity_id, created_at DESC)`; `(company_id, actor_user_id, created_at DESC)`; BRIN on `created_at` | Record history, user activity, range scans |
| `ai_processing_jobs` | `(company_id, status, created_at)`; `(document_id)` | Queue monitoring |

### Extensions required
`pgcrypto` (gen_random_uuid), `pg_trgm` (fuzzy text), `vector` (pgvector), `btree_gin`, optionally `pg_stat_statements`.

### Partitioning
Not on day one. Revisit when `inventory_transactions` passes ~50 M rows or `audit_logs` passes ~20 M: partition both `BY RANGE (created_at)` monthly. Design both tables now with the partition key in the primary key `(id, created_at)` so the migration is mechanical rather than a rewrite.

---

## 13. Constraint catalogue

| Kind | Examples |
|---|---|
| **Primary keys** | UUID surrogate on every table; composite natural PKs only on pure join tables (`role_permissions`, `user_godown_access`) |
| **Foreign keys** | All intra-tenant. Every FK to a tenant table is accompanied by a CHECK that `company_id` matches — enforced by composite FKs: `FOREIGN KEY (company_id, supplier_id) REFERENCES suppliers (company_id, id)`, which requires a `UNIQUE (company_id, id)` on the parent. **This is the single most effective guard against cross-tenant data leakage through a mis-set id.** |
| **Unique** | `(company_id, sku)`, `(company_id, barcode)`, `(company_id, rfq_number)`, `(company_id, po_number)`, `(company_id, grn_number)`, `(company_id, sha256_hash)`, `(company_id, supplier_id, quotation_number)`, `(company_id, supplier_id, invoice_number, invoice_date)`, `lower(email)` on `users` (global), `(company_id, doc_type, financial_year)` on `document_sequences`. All master-data uniques are **partial** on `deleted_at IS NULL` so a deleted SKU frees its code. |
| **Check — quantities** | `quantity > 0` on order/RFQ/quotation lines; `received_quantity >= 0`; `accepted_quantity BETWEEN 0 AND received_quantity`; `quantity <> 0` + the sign rule on `inventory_transactions` |
| **Check — money** | `unit_price >= 0`; `discount_pct BETWEEN 0 AND 100`; `gst_rate BETWEEN 0 AND 28`; `total_amount >= 0` |
| **Check — dates** | `expected_delivery_date >= rfq_date`; `valid_until >= quotation_date`; `expires_on > manufactured_on`; `grn_date <= CURRENT_DATE + 1` (no future receipts) |
| **Check — logic** | `from_godown_id <> to_godown_id`; `is_platform_admin = (company_id IS NULL)`; `NOT (is_inter_state AND (cgst_amount > 0 OR sgst_amount > 0))`; `NOT (NOT is_inter_state AND igst_amount > 0)` |
| **Check — formats** | GSTIN/PAN/HSN/IFSC/e-way regexes from §7.3 |
| **Not null** | Every `company_id`; every document's `number`, `date`, `status`; every line's `quantity` and `uom_id`; `goods_receipt_items.product_variant_id` |
| **Exclusion** | `batches`: no two open batches with the same number for one variant (handled by unique); consider an `EXCLUDE` on overlapping reservation windows when reservations arrive |

**Barcode uniqueness — explicit decision:** unique **per tenant**, not globally. Distributor A and Distributor B legitimately both stock EAN `8901234500011`. A global unique constraint would make the second tenant's onboarding fail with an incomprehensible error. If a shared master catalogue is ever introduced, it belongs in a separate non-tenant `global_products` reference table.

---

## 14. Relationship summary

Full ERD and cardinality discussion in `03_DATABASE_ERD.md`. Headlines:

- **1:1** — `companies` ↔ `company_settings`; `supplier_quotations` ↔ `ai_extraction_results` (per attempt); `goods_receipt_items` ↔ `inventory_transactions` (one accepted line → one posting)
- **1:N** — everything from `companies` down; every document → its items; `products` → `product_variants`; `godowns` → `stock_balances`
- **M:N** — `rfqs` ↔ `suppliers` (via `rfq_suppliers`); `suppliers` ↔ `product_variants` (via `supplier_products`); `documents` ↔ business records (via `document_links`); `roles` ↔ `permissions`; `users` ↔ `godowns`; `purchase_order_items` ↔ `goods_receipt_items` (many GRN lines per PO line, and one GRN may cover many POs in a future consolidation)

---

## 15. Migration and seed order

```
001  extensions (pgcrypto, pg_trgm, vector) + companies + company_settings + document_sequences
002  roles + permissions + role_permissions (seed system roles) + users + user_godown_access + invitations + refresh_tokens
003  uoms (seed) + categories + brands + godowns
004  products + product_variants + product_uom_conversions + product_images
005  suppliers + supplier_contacts + supplier_products
006  inventory_transactions + stock_balances + batches + stock_transfers(+items)
007  rfqs(+items, +suppliers)
008  supplier_quotations(+items) + quotation_comparisons(+lines)
009  purchase_orders(+items)
010  proforma_invoices(+items)
011  goods_receipts(+items) + purchase_returns(+items)
012  supplier_invoices(+items) + document_variances
013  documents + document_links
014  ai_* tables + canonical_fields + document_schema_mappings(+fields) + variant_embeddings
015  alerts + alert_reads + audit_logs + outbound_messages
016  RLS policies on every tenant table + triggers (updated_at, ledger immutability, balance upsert)
```

Seed data required for a working tenant: 9 UoMs, 7 system roles with permissions, the tenant's own company row, one default godown, and `document_sequences` rows for each doc type.

---

## 16. Performance notes

| Concern | Approach |
|---|---|
| Low-stock query across the catalogue | `stock_balances` JOIN `product_variants` with a covering index; cache the count per tenant in Redis for 60 s for the dashboard KPI only |
| Dashboard KPIs | Single SQL function `v_dashboard_kpis(company_id)`; if p95 exceeds 300 ms, promote to a materialised view refreshed every 5 minutes (accepting staleness on a dashboard is fine; accepting it on a stock ledger is not) |
| Comparison across N quotations | One query joining `supplier_quotation_items` to `rfq_items`; N is small (2–6 suppliers) |
| Embedding search | Pre-filter by `company_id` and category before the ANN scan |
| List endpoints | Keyset pagination (`WHERE (created_at, id) < (:cursor)`) rather than OFFSET — the prototype's fake pagination becomes real without slowing down at page 50 |
| Redis usage | Cache only: schema mappings, session/permission lookups, dashboard counters, AI job progress. **Never the source of truth** — every cached value is reconstructible from Postgres |
| Bulk import (Excel catalogue) | `COPY` into a staging table, validate in SQL, then upsert — never row-by-row ORM inserts |


