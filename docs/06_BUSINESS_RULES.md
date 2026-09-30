# 06 — BUSINESS RULES, VALIDATION, AUDIT & SECURITY

Every rule below belongs in the **backend**. Rules marked 🔴 are ones the current prototype violates or cannot enforce, and they are the reason the frontend must stop being the system of record.

Enforcement legend: **DB** = constraint/trigger · **SVC** = service layer · **API** = request schema (Pydantic) · **JOB** = scheduled task.

---

## 1. Principles

1. **The database is the source of truth.** The browser displays; it never decides.
2. **Money and tax are computed by backend code only** — never by the client, never by the LLM. Every write endpoint returns the recomputed totals and the UI must render what it receives.
3. **Stock exists only because a transaction says so.** No endpoint may set a quantity directly.
4. **AI proposes, a human disposes** for anything that reaches a business record or a financial value.
5. **Nothing that has legal or audit meaning is ever hard-deleted.**
6. **Every rejection is explainable** — the API returns the rule id and the offending values, so the UI can say what to fix rather than "something went wrong".

---

## 2. Authentication, tenancy and access

| ID | Rule | Enforce | Error |
|---|---|---|---|
| BR-AUTH-01 | Login accepts a username **or** an email; both resolve to a single user. Email is globally unique, username is globally unique when present. | DB, SVC | `401 INVALID_CREDENTIALS` |
| BR-AUTH-02 | Passwords ≥ 8 chars with at least one letter and one digit; Argon2id hashing; never logged. 🔴 *prototype accepts 6 chars and compares plaintext* | API, SVC | `400 PASSWORD_TOO_WEAK` |
| BR-AUTH-03 | 5 failed attempts → 15-minute lock on the account, tracked by `failed_login_count`/`locked_until`. | SVC | `429 RATE_LIMITED` |
| BR-AUTH-04 | A user of a `suspended` company cannot authenticate, and existing tokens stop working within 60 s. 🔴 *prototype suspension is cosmetic* | SVC | `403 COMPANY_SUSPENDED` |
| BR-AUTH-05 | `company_id` is taken **only** from the verified token, never from a header, body or query parameter. | SVC | `403 TENANT_MISMATCH` |
| BR-AUTH-06 | Every tenant-owned query runs with RLS active; a row from another tenant is reported as `404`, never `403`, so ids cannot be probed. | DB, SVC | `404 NOT_FOUND` |
| BR-AUTH-07 | Only a platform admin may impersonate. Impersonation tokens expire in 30 minutes, cannot be refreshed, cannot themselves impersonate, and stamp `impersonated_by` on every audit row. 🔴 *prototype impersonation is unlimited and client-side* | SVC | `403 FORBIDDEN` |
| BR-AUTH-08 | An invitation expires after 7 days and can be accepted exactly once. 🔴 *prototype invites never expire* | DB, SVC | `410 INVITE_EXPIRED`, `409 ALREADY_ACCEPTED` |
| BR-AUTH-09 | A user cannot assign a role with permissions exceeding their own, and cannot change their own role. | SVC | `403 ROLE_ESCALATION` |
| BR-AUTH-10 | The last active Owner of a company cannot be removed, demoted or deactivated. 🔴 *prototype only hides the button* | SVC | `422 LAST_OWNER` |
| BR-AUTH-11 | Changing a user's role or godown scope revokes their refresh tokens, forcing a permission reload. | SVC | — |
| BR-AUTH-12 | Godown-scoped users see and act on stock only in their assigned godowns; `inventory.view_all` overrides for read. 🔴 *not enforced anywhere today* | SVC | `403 GODOWN_OUT_OF_SCOPE` |
| BR-AUTH-13 | A login with more than one active `company_users` row may switch its active company without re-authenticating; the target membership must be `active`, and switching reissues a token scoped to that `company_id` and revokes nothing from the previous one. **NEW (Sept 2026)**. 🔴 *prototype only changes the header display — no other data is re-scoped by company, since none of it is company-partitioned in the mock data* | SVC | `403 NOT_A_MEMBER` |

---

## 3. Master data

| ID | Rule | Enforce | Error |
|---|---|---|---|
| BR-MD-01 | SKU is unique per company, case-insensitive, `^[A-Z0-9._/-]{2,40}$`. | DB (partial unique), API | `409 DUPLICATE_SKU` |
| BR-MD-02 | Barcode/EAN/UPC unique **per company**, not globally — two tenants may stock the same EAN. | DB | `409 DUPLICATE_BARCODE` |
| BR-MD-03 | SKU becomes immutable once any inventory transaction or document line references the variant. | SVC | `409 SKU_LOCKED` |
| BR-MD-04 | Master data is soft-deleted, never removed, and deletion is blocked while stock ≠ 0 or open document lines exist; the API returns the blocking references. 🔴 *prototype hard-deletes from localStorage* | SVC | `409 RECORD_IN_USE` |
| BR-MD-05 | GSTIN: 15 chars, valid pattern, first two digits equal the record's `state_code`, characters 3–12 equal the PAN when both present, checksum verified. | API, SVC | `422 INVALID_GSTIN` |
| BR-MD-06 | A supplier without a GSTIN must be explicitly marked `gst_treatment='unregistered'` — a blank GSTIN is never assumed. | SVC | `422 GST_TREATMENT_REQUIRED` |
| BR-MD-07 | HSN is 4, 6 or 8 digits; required on any variant used in a purchase document. | API, SVC | `422 INVALID_HSN` |
| BR-MD-08 | GST rate must be one of {0, 0.25, 3, 5, 12, 18, 28}; other values are accepted only with `allow_nonstandard_gst` and are flagged. | API | `422 INVALID_GST_RATE` |
| BR-MD-09 | Category cannot be its own ancestor; maximum depth 4. | SVC | `422 INVALID_HIERARCHY` |
| BR-MD-10 | A godown cannot be deactivated while it holds stock. | SVC | `409 RECORD_IN_USE` |
| BR-MD-11 | `reorder_point ≥ 0`, `reorder_qty > 0` when `reorder_point > 0`. | DB | `422` |
| BR-MD-12 | One supplier SKU maps to exactly one variant per supplier; the reverse is many-to-one. | DB | `409 DUPLICATE_SUPPLIER_SKU` |
| BR-MD-13 | A product may be edited only by its owner (`products.created_by = current_user.id`), unless the user also holds `product.update_any`. Row-level, layered on top of the `product.update` permission check — RBAC alone is not sufficient. **NEW (Sept 2026)**. 🔴 *prototype only disables the Edit button client-side; any user could still call a write directly* | SVC | `403 NOT_PRODUCT_OWNER` |

---

## 4. Inventory

| ID | Rule | Enforce | Error |
|---|---|---|---|
| **BR-INV-01** 🔴 | **Stock quantity can never be written directly.** There is no API that sets a balance. Opening stock, corrections and every other change post an `inventory_transaction`. *The prototype's Product form edits `currentStock` — this must be replaced by an `OPENING_STOCK`/`STOCK_CORRECTION` posting.* | SVC, DB | — |
| **BR-INV-02** | `stock_balances.quantity` must equal `SUM(inventory_transactions.quantity)` for the same (company, variant, godown, batch). Verified nightly; drift raises a `System` critical alert and the job re-derives the balance. | JOB | — |
| BR-INV-03 | The ledger is append-only: no UPDATE, no DELETE, enforced by trigger. Corrections are new rows with `reverses_txn_id`. | DB | `409 IMMUTABLE_LEDGER` |
| BR-INV-04 | Quantity sign is derived from `txn_type` by the server; clients send unsigned magnitudes. `quantity <> 0` always. | DB (CHECK), SVC | `422` |
| BR-INV-05 | A movement may not drive a balance below zero unless `allow_negative_stock` is enabled; the error names the available quantity. | SVC | `422 INSUFFICIENT_STOCK` |
| BR-INV-06 | A transfer writes exactly two rows in one transaction (`TRANSFER_OUT` −q, `TRANSFER_IN` +q) with `counterpart_txn_id` set both ways, and `from_godown ≠ to_godown`. | SVC, DB | `422 SAME_GODOWN` |
| BR-INV-07 | `DAMAGE` and `STOCK_CORRECTION` require a non-empty `remarks` and a `reason_code`. 🔴 *the prototype collects remarks and discards them* | API | `422 REMARKS_REQUIRED` |
| BR-INV-08 | Quantities are stored in the variant's base UoM. Any other UoM requires an active conversion for that variant; the factor used is frozen on the transaction. | SVC | `422 NO_UOM_CONVERSION` |
| BR-INV-09 | Batch-tracked variants require a `batch_id` on every movement; batch must belong to the variant and not be expired for an outward movement (override needs `inventory.override_expiry`). | SVC | `422 BATCH_REQUIRED` / `422 BATCH_EXPIRED` |
| BR-INV-10 | `txn_date` may not be in the future, and may not fall on or before `company_settings.inventory_locked_through` (the period-close marker). Moving that date forward requires `company.manage`. | API, SVC | `422 PERIOD_CLOSED` |
| BR-INV-11 | Stock status is derived, never stored: `qty = 0 → out_of_stock`; `available ≤ reorder_point → low_stock`; else `in_stock`. | SVC | — |
| BR-INV-12 | Valuation uses `purchase_price` (standard cost) in Phase 1; `unit_cost` is captured on every inward transaction so weighted-average costing can be enabled later without backfilling. | SVC | — |
| BR-INV-13 | Reserved quantity may only change through a reservation record. Until Sales Orders exist it stays 0 — the UI must not imply otherwise. | SVC | — |

---

## 5. RFQ

| ID | Rule | Enforce | Error |
|---|---|---|---|
| BR-RFQ-01 | An RFQ needs ≥ 1 item with `quantity > 0` before it can be sent. | SVC | `422 NO_ITEMS` |
| BR-RFQ-02 | Every line needs either a `product_variant_id` or a non-empty `description` (free-text sourcing is legitimate). | API | `422` |
| BR-RFQ-03 | Sending requires ≥ 1 active supplier, each with an email address; the error lists suppliers missing one. | SVC | `422 SUPPLIER_EMAIL_MISSING` |
| BR-RFQ-04 | Only `draft` RFQs are editable or deletable; sent RFQs are cancelled instead. | SVC | `409 INVALID_STATE_TRANSITION` |
| BR-RFQ-05 | `expected_delivery_date ≥ rfq_date`. 🔴 *neither date is even persisted today* | DB | `422` |
| BR-RFQ-06 | An RFQ moves to `partially_quoted` on the first quotation and `quoted` when every invited supplier has responded or declined — derived, never set by hand. | SVC | — |
| BR-RFQ-07 | The RFQ number is allocated at creation (the form displays it) and never changes. | SVC | — |
| BR-RFQ-08 | `is_active` is independent of `status` (BR-RFQ-04 still governs delete/cancel). Setting `is_active=false` (Inactivate) is blocked while any `supplier_quotations.rfq_id` or `purchase_orders.rfq_id` references the RFQ; Reactivate has no such check. **NEW (Sept 2026)** | SVC | `409 RFQ_REFERENCED` |
| BR-RFQ-09 | An imported RFQ (`number_source='imported'`) keeps the number found in its source document verbatim — it is never allocated from `document_sequences`, and a duplicate import of the same number is rejected rather than renumbered. **NEW (Sept 2026)** | SVC | `409 DUPLICATE_RFQ_NUMBER` |

---

## 6. Quotations and comparison

| ID | Rule | Enforce | Error |
|---|---|---|---|
| BR-QT-01 | A quotation belongs to exactly one supplier; `(supplier, quotation_number)` is unique per tenant — a repeat is a duplicate upload. | DB | `409 DUPLICATE` |
| BR-QT-02 | Quotation totals are recomputed from lines on every save; the supplier's printed total is stored separately for reference and a mismatch raises a variance. | SVC | — |
| BR-QT-03 | A quotation past `valid_until` is `expired` (daily job) and cannot be converted to a PO without an explicit override. | JOB, SVC | `422 QUOTATION_EXPIRED` |
| BR-QT-04 | AI-extracted quotations must be human-approved before they can be compared or ordered from. | SVC | `422 APPROVAL_REQUIRED` |
| BR-QT-05 | Approval is blocked while any line is unmatched to a SKU — re-validated server-side, never trusting the client's `can_approve`. | SVC | `422 UNRESOLVED_LINES` |
| BR-CMP-01 | The recommendation is **computed** from landed cost, delivery days, on-time %, quality score and warranty, with the weights and the reason returned in the response. 🔴 *hardcoded strings today* | SVC | — |
| BR-CMP-02 | Only quotations against the same RFQ (or an explicitly chosen set) may be compared, and only lines that map to the same `rfq_item_id` are compared against each other. | SVC | `422 INCOMPARABLE` |
| BR-CMP-03 | A cell marked unavailable is excluded from "lowest price" and from single-supplier totals; a supplier missing any line cannot be the single-supplier baseline. | SVC | — |
| BR-CMP-04 | Converting to POs groups selections by supplier, creates one PO each, and freezes the comparison as `converted`. Each PO line records its source quotation line. | SVC | — |

---

## 7. Purchase orders

| ID | Rule | Enforce | Error |
|---|---|---|---|
| BR-PO-01 | Totals are computed server-side from lines using the canonical formula (§10) and returned to the client. 🔴 *two divergent formulas exist in the prototype* | SVC | — |
| BR-PO-02 | Approval requires: ≥1 line, every line with `quantity > 0` and `unit_price ≥ 0`, supplier active with a GST treatment, delivery godown set, expected delivery date set, total > 0. | SVC | `422 BUSINESS_RULE_VIOLATION` |
| BR-PO-03 | A PO above `require_po_approval_above` needs an approver holding `po.approve_high_value`; with maker-checker enabled the approver may not be the creator. | SVC | `403 APPROVAL_LIMIT_EXCEEDED` |
| BR-PO-04 | Only `draft` POs are editable; after `approved` the only changes are cancel, short-close, or a formal amendment that supersedes the document. | SVC | `409 INVALID_STATE_TRANSITION` |
| BR-PO-05 | PO status is **derived** from its lines: all `received` → `received`; any partially received → `partially_received`; all closed/cancelled → `closed`. `received_pct = Σ received ÷ Σ ordered`. 🔴 *never updated by the prototype* | SVC | — |
| BR-PO-06 | `is_inter_state` is computed from supplier `state_code` vs the delivery godown's state, and frozen on the document. 🔴 *hardcoded `true` today, so intra-state purchases are taxed wrongly* | SVC | — |
| BR-PO-07 | A cancelled PO cannot receive goods; a PO with any confirmed receipt cannot be cancelled, only short-closed. | SVC | `422 PO_CANCELLED` / `422 PO_HAS_RECEIPTS` |
| BR-PO-08 | Linking an RFQ only auto-fills lines when the PO has none, and never overwrites a line the user has entered. *(The prototype already gets this right — keep it.)* | SVC | — |
| BR-PO-09 | A PO cannot mix suppliers. A multi-supplier sourcing decision produces multiple POs. | DB | — |
| BR-PO-10 | Deleting is allowed only for drafts; everything else is cancellation with a reason. | SVC | `409` |

---

## 8. Proforma

| ID | Rule | Enforce | Error |
|---|---|---|---|
| BR-PF-01 | A proforma is **not** a tax invoice: it never grants input tax credit and never affects inventory. | design | — |
| BR-PF-02 | When linked to a PO, the PO total and each line's PO rate are snapshotted at link time; variance is computed from the snapshot. | SVC | — |
| BR-PF-03 | Any non-zero variance creates `document_variances` and, above the tolerance, an alert. Approval above tolerance requires `proforma.approve_variance`. | SVC, JOB | `422 VARIANCE_EXCEEDS_TOLERANCE` |
| BR-PF-04 | Advance percentage/amount must not exceed the proforma total. | DB | `422` |
| BR-PF-05 | Several proformas may exist against one PO; their combined value is checked against the PO total and flagged if it exceeds it. | SVC | — |
| BR-PF-06 | The UI never exposes a Reject action for a received proforma — the purchase is already committed by the time one arrives, so there is nothing to undo. A discrepancy goes through `raise-query` instead, which sets `query_raised_at`/`query_note` and (recommended) sends the supplier a message. `rejected` stays a valid `status` value for backend/ops use (e.g. before any advance payment is released), just not a transition the UI drives. **NEW (Sept 2026)** | design, SVC | — |

---

## 9. Goods receipt — the highest-risk area

| ID | Rule | Enforce | Error |
|---|---|---|---|
| BR-GRN-01 | `0 ≤ accepted_quantity ≤ received_quantity`; `rejected_quantity` is generated, never sent by the client. | DB | `422` |
| BR-GRN-02 | `received_quantity` may not exceed the PO line's **pending** quantity (ordered − previously received) unless `allow_grn_excess_receipt` is on and the excess is within `grn_excess_tolerance_pct`. | SVC | `422 EXCESS_RECEIPT_NOT_ALLOWED` |
| BR-GRN-03 | `issue_type` is auto-derived (`short`/`excess`/`none`) but a manually chosen `damaged/expired/wrong_*` is preserved — the logic the UI already implements, moved server-side. | SVC | — |
| BR-GRN-04 | `wrong_product`, `wrong_variant`, `wrong_model` and `wrong_brand` require `expected_variant_id` and force `accepted_quantity = 0` — you cannot accept the wrong item into the ordered item's stock. | SVC | `422 EXPECTED_VARIANT_REQUIRED` |
| BR-GRN-05 | Any line with `rejected_quantity > 0` or `issue_type ≠ none` requires `remarks`. | API | `422 REMARKS_REQUIRED` |
| **BR-GRN-06** 🔴 | **Confirming a GRN posts exactly one `GOODS_RECEIPT` transaction per line with `accepted_quantity > 0`, and nothing else creates purchase stock.** Rejected quantities post nothing. *The prototype's Confirm Receipt posts nothing at all.* | SVC | — |
| BR-GRN-07 | Confirmation is atomic: postings, balance updates, PO line updates, variance records and status changes all commit together or not at all. | SVC (DB txn) | — |
| BR-GRN-08 | A confirmed GRN can never be edited or deleted. Corrections are made by a reversing GRN that posts offsetting transactions. 🔴 *the prototype offers Delete and warns that inventory is not reversed* | SVC | `409 GRN_CONFIRMED` |
| BR-GRN-09 | Confirmation is idempotent: a repeated request with the same `Idempotency-Key` returns the original result and posts nothing twice. | SVC | — |
| BR-GRN-10 | The receiving godown must be within the user's scope; receiving into another godown needs `grn.receive_other_godown`. | SVC | `403 GODOWN_OUT_OF_SCOPE` |
| BR-GRN-11 | Batch-tracked variants require batch number and, where applicable, expiry on receipt; expiry must be in the future. | SVC | `422 BATCH_REQUIRED` |
| BR-GRN-12 | A GRN may only reference an `approved`/`sent`/`partially_received` PO from the same supplier. | SVC | `422 INVALID_PO_STATE` |
| BR-GRN-13 | `grn_date` cannot be in the future. | DB | `422` |

---

## 10. Money and tax (the canonical formula)

| ID | Rule |
|---|---|
| BR-TAX-01 | `line_net = round(quantity × unit_price, 2) − round(quantity × unit_price × discount_pct / 100, 2)` |
| BR-TAX-02 | `line_tax = round(line_net × gst_rate / 100, 2)`; `line_cess = round(line_net × cess_rate / 100, 2)` |
| BR-TAX-03 | `line_total = line_net + line_tax + line_cess` |
| BR-TAX-04 | `taxable_value = Σ line_net`; `tax_total = Σ line_tax` |
| BR-TAX-05 | `is_inter_state ⇒ igst = tax_total, cgst = sgst = 0`. Otherwise `cgst = sgst = round(tax_total / 2, 2)` with any 1-paisa remainder assigned to CGST. |
| BR-TAX-06 | Freight and other charges: Phase 1 treats them as untaxed additions, matching the current UI. **Flagged in `09` — under GST, freight charged by the supplier on a tax invoice is normally taxable at the principal supply's rate.** The column layout supports taxed freight when the rule is corrected. |
| BR-TAX-07 | `total_before_round = taxable_value + tax_total + cess_total + freight + other_charges`; `total = round(total_before_round)` per `rounding_mode`; `round_off = total − total_before_round` and is stored. |
| BR-TAX-08 | All arithmetic uses `Decimal` (Python) / `NUMERIC` (SQL). Floats are forbidden anywhere in the money path. |
| BR-TAX-09 | Rounding is applied at line level then aggregated — never by rounding the grand total of unrounded lines — so printed documents reconcile line by line. |
| BR-TAX-10 | A client-supplied total is ignored; the server recomputes and returns its own. |

---

## 11. Documents and AI

| ID | Rule | Enforce | Error |
|---|---|---|---|
| BR-DOC-01 | Uploads limited to `xlsx, xls, csv, pdf, docx, jpg, jpeg, png`, ≤ 20 MB, verified by content sniffing rather than extension. | API | `422 UNSUPPORTED_FILE` |
| BR-DOC-02 | SHA-256 duplicate detection **per tenant**; a duplicate returns the existing document with its links rather than creating a second row. | DB, SVC | `200` with `duplicate_of` |
| BR-DOC-03 | Files are stored only in S3 with server-side encryption; downloads are pre-signed and expire in 5 minutes. | SVC | — |
| BR-DOC-04 | Deleting a document never deletes the business record it produced. As built (Sep 2026): a document that produced a record (a `source` link in `document_links`, an approved extraction, a product image, logo or profile picture) cannot be deleted — 409 `RECORD_IN_USE` naming the record; any other document can, with its AI results, jobs and S3 object, and the deletion is audited with the file name and hash. (The earlier wording kept the link with a "deleted" marker instead; the stricter rule was chosen so a record never loses its evidence.) | SVC | `DELETE /ai/documents/{id}` |
| BR-AI-01 | AI never writes to a business table. It writes to `ai_*` tables; a human approval promotes the result. | SVC | — |
| BR-AI-02 | **AI never computes a stored financial value.** Totals are recomputed from reviewed quantities and prices. `ai_never_autoapprove_financials` is locked on. | SVC | — |
| BR-AI-03 | Any extraction whose overall or any field confidence is below `ai_review_confidence_threshold` (default 90) is forced to `review_required`. | SVC | — |
| BR-AI-04 | A match is auto-applied only when the method is deterministic (`exact_sku`, `supplier_alias`, `barcode`) and the score ≥ 0.95. Embedding and LLM matches always require confirmation. | SVC | — |
| BR-AI-05 | Every human correction is recorded in `ai_review_actions` with the AI value, the human value, the user and the timestamp — this is the training and audit record. | SVC | — |
| BR-AI-06 | Confirming a match may write a `supplier_products` alias so the same supplier code never needs matching again; the alias records who confirmed it. | SVC | — |
| BR-AI-07 | Document text is **data, never instructions**. Model output is schema-validated before use; prompt-injection attempts are logged and the document is flagged. | SVC | — |
| BR-AI-08 | The assistant never generates or executes SQL. Intents map to hand-written parameterised queries run with the caller's tenant and godown scope on a read-only connection with a statement timeout. | SVC | — |
| BR-AI-09 | A schema mapping is persisted only after human confirmation, keyed by (supplier, document type, column signature), and is cached in Redis with the database remaining authoritative. | SVC | — |
| BR-AI-10 | Every AI call records model, prompt version, tokens, cost and latency for cost control and reproducibility. | SVC | — |

---

## 12. Alerts

| ID | Rule |
|---|---|
| BR-ALT-01 | Alerts are generated server-side by named rules (`rule_code`), never by the browser. |
| BR-ALT-02 | Deduplicate by `(company_id, rule_code, reference_type, reference_id)` while an alert is open — a low-stock item must not produce 24 alerts a day. |
| BR-ALT-03 | Read state is per user (`alert_reads`), because "Mark all as read" means *for me*. 🔴 *prototype keeps it in React state and loses it on reload* |
| BR-ALT-04 | An alert auto-resolves when its condition clears (stock replenished, variance accepted, PO received). |
| BR-ALT-05 | Severity: out-of-stock and wrong-product-received → `critical`; below-reorder, proforma/invoice variance → `high`; delivery delay, quotation expiry, low AI confidence → `medium`; unreadable document → `low`. *(Matches the prototype's data.)* |

---

## 13. Numbering

| ID | Rule |
|---|---|
| BR-NUM-01 | Numbers are allocated from `document_sequences` under a row lock inside the creating transaction — never `max+1` in application code. 🔴 *the prototype's `max+1` over localStorage guarantees collisions with concurrent users* |
| BR-NUM-02 | Format `{prefix}{zero-padded sequence}` with prefix and padding from Settings. The prototype uses 5 digits (`PO-2026-00123`) while the brief shows 6 (`PO-2026-000001`); padding is configurable and defaults to the UI's 5 to avoid breaking existing references. |
| BR-NUM-03 | Sequences reset per financial year (April–March) when the prefix contains a year token. |
| BR-NUM-04 | Allocated numbers are never reused, even if the document is later cancelled — gaps are expected and auditable. |
| BR-NUM-05 | Supplier-issued numbers (quotation, proforma, invoice) are **captured, not generated**, and validated for duplicates per supplier. |

---

## 14. Document state machines

```
RFQ:        draft → sent → partially_quoted → quoted → closed
                 ↘ cancelled (from draft or sent)
            is_active: true ⇄ false — orthogonal flag, not a status transition (BR-RFQ-08, NEW Sept 2026)
QUOTATION:  draft → under_review → approved → converted
                                 ↘ rejected      ↘ expired (time-based)
COMPARISON: draft → decided → converted ↘ discarded
PO:         draft → pending_approval → approved → sent → acknowledged
                                                     → partially_received → received → closed
                 ↘ cancelled (only before any receipt)
PROFORMA:   pending → under_review → approved → paid → completed ↘ rejected ↘ cancelled
            (rejected stays valid server-side/for ops; the UI never drives this transition — BR-PF-06, NEW Sept 2026)
GRN:        draft → confirmed(partially_received | received)
                 ↘ cancelled (draft only)     [confirmed is terminal; correct via reversing GRN]
INVOICE:    draft → under_review → approved ↘ disputed ↘ cancelled
RETURN:     draft → sent → accepted → credited ↘ cancelled
DOCUMENT:   uploaded → queued → processing → extracted(review_required) → approved
                                          ↘ failed        ↘ rejected      ↘ duplicate
```

Illegal transitions return `409 INVALID_STATE_TRANSITION` naming the current and attempted state. Every transition writes an audit row.

---

## 15. Audit requirements

**Audited without exception:** login success and failure, logout, password change/reset, impersonation start/stop, company switch **(NEW, Sept 2026)**, user create/update/remove, role and godown-scope changes, invitation issue/resend/revoke/accept, company create/suspend/reactivate, settings changes, master-data create/update/delete, RFQ create/update/send/cancel/**inactivate/reactivate/import (NEW)**, quotation create/approve/reject/delete, comparison decision and conversion, PO create/update/approve/send/cancel/close, proforma approve/reject/query, **GRN confirm and reverse**, inventory transaction posting, transfer, adjustment, purchase return, invoice approve/dispute, document upload/delete/link, AI extraction approve/reject and every field/line override, alert dismissal, exports, and every permission denial.

**`audit_logs` payload:** `company_id, entity_type, entity_id, entity_label, action, actor_user_id, actor_role, impersonated_by, before_data JSONB, after_data JSONB, changed_fields JSONB, ip_address, user_agent, request_id, created_at`.

Rules: written in the same transaction as the change (no lost audit on rollback); immutable (no update/delete grants); `before/after` redacted for passwords and tokens; retained 7 years for financial documents; queryable per record (the Audit Trail component the frontend already renders) and per user.

---

## 16. Tenant isolation checklist

| Control | Implementation |
|---|---|
| Every tenant table carries `company_id NOT NULL` | migration lint test fails the build otherwise |
| RLS policy on every tenant table | verified by an automated test that enumerates `pg_tables` |
| `SET LOCAL app.current_company_id` per request | FastAPI dependency; connection returned to the pool resets it |
| Composite FKs `(company_id, id)` | prevents a valid-looking id from another tenant being attached |
| Cross-tenant reads return 404 | global exception handler |
| Platform-admin bypass | separate DB role with `BYPASSRLS`, used only by `/platform/*`, every call audited |
| S3 keys namespaced by company | `{company_id}/{yyyy}/{mm}/{uuid}` + bucket policy |
| Redis keys namespaced by company | `co:{company_id}:...`, no shared key space |
| Embedding search | `company_id` filter applied **before** the ANN scan |
| Background jobs | carry `company_id` explicitly; no job may run "for all tenants" without an explicit loop that re-establishes scope |
| Test suite | a negative test per module attempting cross-tenant access, expected to 404 |
