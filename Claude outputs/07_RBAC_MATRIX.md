# 07 — RBAC MATRIX

Derived from the roles that actually exist in the UI (`Super Admin`, `Owner`, `Purchase Manager`, `Godown Manager`, `Accountant`, `Staff`), reconciled with the roles the business brief asks for.

---

## 1. Role reconciliation

| Brief role | UI role | Decision | Reason |
|---|---|---|---|
| Super Admin | `Super Admin` | Keep — **platform scope only** | Manages tenants, never tenant data directly except by audited impersonation |
| Company Admin / Owner | `Owner` | Keep as `Owner` | The UI already treats Owner as the undeleteable tenant administrator |
| Purchase Manager | `Purchase Manager` | Keep | |
| Inventory Manager | `Godown Manager` | **Keep the UI's name** | "Godown" is the term the product and its Indian users use everywhere; renaming it to "Inventory Manager" would fight the domain language for no gain |
| Warehouse / Godown Staff | `Staff` | Keep as `Staff` | Godown-scoped operator |
| Accountant | `Accountant` | Keep | |
| Viewer | — | **ADD** | Read-only access for auditors, owners' family members, external accountants. Cheap to add, impossible to retrofit safely later |

`roles.code` values: `super_admin`, `owner`, `purchase_manager`, `godown_manager`, `accountant`, `staff`, `viewer`.

> **Critical finding:** the prototype enforces nothing. Role appears in exactly three client-side places — the System Admin route guard, the System Admin menu item, and hiding the Remove button for an Owner. Any user can reach any screen and perform any action by URL. All enforcement below must be server-side, with the UI merely hiding what the token says is unavailable.

---

## 2. Permission catalogue

Permissions are fine-grained codes; roles are bundles. The API checks permissions, never role names — so a custom role can be introduced later without touching endpoint code.

| Module | Codes |
|---|---|
| Dashboard | `dashboard.view` |
| Products | `product.view`, `product.create`, `product.update`, `product.delete`, `product.import`, `product.export` |
| Catalogue masters | `master.view`, `master.manage` (categories, brands, UoMs) |
| Suppliers | `supplier.view`, `supplier.create`, `supplier.update`, `supplier.delete`, `supplier.export` |
| Godowns | `godown.view`, `godown.manage` |
| Inventory | `inventory.view`, `inventory.view_all` (all godowns), `inventory.adjust`, `inventory.transfer`, `inventory.transfer_any` (transfer involving a godown outside the user's scope), `inventory.override_expiry`, `inventory.close_period`, `inventory.export` |
| RFQ | `rfq.view`, `rfq.create`, `rfq.update`, `rfq.delete`, `rfq.send`, `rfq.cancel` |
| Quotations | `quotation.view`, `quotation.create`, `quotation.update`, `quotation.delete`, `quotation.approve`, `quotation.reject` |
| Comparison | `comparison.view`, `comparison.create`, `comparison.decide`, `comparison.convert` |
| Purchase orders | `po.view`, `po.create`, `po.update`, `po.delete_draft`, `po.submit`, `po.approve`, `po.approve_high_value`, `po.send`, `po.cancel`, `po.close` |
| Proforma | `proforma.view`, `proforma.create`, `proforma.update`, `proforma.approve`, `proforma.approve_variance`, `proforma.raise_query` |
| Goods receipt | `grn.view`, `grn.create`, `grn.update`, `grn.confirm`, `grn.reverse`, `grn.receive_other_godown`, `grn.allow_excess` |
| Supplier invoice | `invoice.view`, `invoice.create`, `invoice.update`, `invoice.match`, `invoice.approve`, `invoice.dispute` |
| Purchase return | `return.view`, `return.create`, `return.confirm` |
| Documents | `document.view`, `document.upload`, `document.delete`, `document.download` |
| AI | `ai.view`, `ai.review`, `ai.approve_extraction`, `ai.manage_mappings`, `ai.assistant` |
| Alerts | `alert.view`, `alert.manage` (dismiss/resolve/configure) |
| Reports | `report.view`, `report.export` |
| Users | `user.view`, `user.manage`, `user.manage_owners` |
| Company | `company.view`, `company.manage` (settings, GSTIN, numbering) |
| Audit | `audit.view` |
| Platform | `platform.companies.view`, `platform.companies.manage`, `platform.users.view`, `platform.impersonate`, `platform.activity.view` |

---

## 3. Permission matrix

✓ = allowed · ◐ = allowed within the user's godown scope only · ✗ = denied

### 3.1 Core business actions

| Action | Super Admin¹ | Owner | Purchase Mgr | Godown Mgr | Staff | Accountant | Viewer |
|---|---|---|---|---|---|---|---|
| View dashboard | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| View products | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Create / edit product | ✗ | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ |
| Delete product | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Import / export catalogue | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ (export) | ✗ |
| View suppliers | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Create / edit supplier | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Delete supplier | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Manage godowns | ✗ | ✓ | ✗ | ✓ | ✗ | ✗ | ✗ |
| **View stock** | ✗ | ✓ | ✓ | ✓ | ◐ | ✓ | ✓ |
| View stock in all godowns | ✗ | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ |
| Post stock correction | ✗ | ✓ | ✗ | ◐ | ✗ | ✗ | ✗ |
| Post damage / sales issue | ✗ | ✓ | ✗ | ◐ | ◐ | ✗ | ✗ |
| Transfer between godowns | ✗ | ✓ | ✗ | ◐ | ✗ | ✗ | ✗ |
| **Create RFQ** | ✗ | ✓ | ✓ | ✓² | ✗ | ✗ | ✗ |
| Send RFQ | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Cancel RFQ | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| View quotations | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ | ✓ |
| Approve / reject quotation | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Run comparison | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ (view) | ✓ (view) |
| Decide & convert to PO | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Create / edit PO | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| **Approve PO** | ✗ | ✓ | ✓³ | ✗ | ✗ | ✗ | ✗ |
| Approve PO above threshold | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Send PO to supplier | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Cancel / short-close PO | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| View proforma | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ | ✓ |
| Approve proforma | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ | ✗ |
| Approve proforma with variance | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **Create GRN** | ✗ | ✓ | ✗ | ◐ | ◐ | ✗ | ✗ |
| **Confirm GRN (posts stock)** | ✗ | ✓ | ✗ | ◐ | ✗ | ✗ | ✗ |
| Receive into another godown | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Allow excess receipt | ✗ | ✓ | ✗ | ✓ | ✗ | ✗ | ✗ |
| Reverse a confirmed GRN | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Create purchase return | ✗ | ✓ | ✓ | ◐ | ✗ | ✗ | ✗ |
| View supplier invoice | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ | ✓ |
| Enter / match invoice | ✗ | ✓ | ✗ | ✗ | ✗ | ✓ | ✗ |
| Approve invoice for payment | ✗ | ✓ | ✗ | ✗ | ✗ | ✓ | ✗ |
| Dispute invoice | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ | ✗ |

¹ Super Admin has **no tenant-data permissions**. To act inside a tenant they must impersonate, which is time-boxed and fully audited. This is deliberate: a support engineer should never be able to silently approve a customer's purchase order.
² A Godown Manager raising an RFQ from the Low Stock screen is the product's core loop — they may create a draft, but only Purchase can send it.
³ Purchase Manager approval is capped by `require_po_approval_above`; above it, an Owner must approve.

### 3.2 Documents, AI and administration

| Action | Super Admin | Owner | Purchase Mgr | Godown Mgr | Staff | Accountant | Viewer |
|---|---|---|---|---|---|---|---|
| Upload document | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |
| View / download document | ✗ | ✓ | ✓ | ✓ | ◐ | ✓ | ✓ |
| Delete document | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Review AI extraction | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ | ✗ |
| **Approve AI extraction** | ✗ | ✓ | ✓ | ✗ | ✗ | ✓⁴ | ✗ |
| Manage schema mappings | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Use AI assistant | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| View alerts | ✗ | ✓ | ✓ | ✓ | ◐ | ✓ | ✓ |
| Dismiss / configure alerts | ✗ | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ |
| View reports | ✗ | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ |
| Export reports | ✗ | ✓ | ✓ | ✓ | ✗ | ✓ | ✗ |
| View users | ✗ | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ |
| Invite / remove users | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Change a user's role | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Edit company settings | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Edit GSTIN / numbering | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| View audit log | ✗ | ✓ | ✓⁵ | ✓⁵ | ✗ | ✓⁵ | ✗ |
| **Manage tenants** | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **Impersonate a user** | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| View platform activity | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |

⁴ An Accountant approves extractions of proformas and invoices; quotation extractions belong to Purchase.
⁵ Non-Owners see the audit trail of records they can access, not the company-wide feed.

---

## 4. Godown scoping (◐)

The UI already captures the scope on every member and invitation (`All godowns` / a named godown) and then ignores it entirely. Enforcement:

| Layer | Behaviour |
|---|---|
| Token | `godown_scope: { all: bool, godown_ids: [...] }` |
| Reads | Stock, transactions, GRNs and alerts are filtered to the scope unless the user holds `inventory.view_all` |
| Writes | Any posting into a godown outside the scope is refused with `403 GODOWN_OUT_OF_SCOPE` |
| Cross-godown transfer | Requires access to **both** godowns, or `inventory.transfer_any` |
| PO delivery godown | Must be in scope to create a PO delivering there |
| Reports | Aggregate reports for scoped users cover only their godowns and say so |

A Staff user assigned to Secondary Godown must not see Main Godown's valuation — today they see everything.

---

## 5. Approval limits and separation of duties

| Control | Rule |
|---|---|
| PO approval threshold | `company_settings.require_po_approval_above` (default: always require approval). Above it, `po.approve_high_value` (Owner) |
| Maker-checker | Optional per tenant: the approver may not be the creator of the PO |
| Stock adjustment ceiling | Corrections above a configurable value require Owner approval (recommended; not in the UI yet) |
| Invoice approval | Separated from PO approval by design — the person who orders should not be the person who clears payment |
| GRN confirmation | Separated from PO creation — the person who orders should not be the person who confirms delivery |
| Impersonation | Platform admin only, ≤ 30 minutes, no refresh, cannot nest, every action stamped `impersonated_by` |

---

## 6. Enforcement design

```python
# FastAPI dependency — the only way an endpoint is protected
@router.post("/goods-receipts/{grn_id}/confirm")
async def confirm_grn(
    grn_id: UUID,
    ctx: Context = Depends(require_permission("grn.confirm")),
    _: None = Depends(require_godown_scope(from_grn="grn_id")),
):
    ...
```

Layers, all of which must hold:

1. **Token claims** — permissions and godown scope are baked into a 15-minute access token; role changes revoke refresh tokens so a demotion takes effect within one token lifetime.
2. **Endpoint dependency** — declarative `require_permission(code)`; an endpoint with no permission declaration fails a CI lint check.
3. **Row-level security** — `company_id` isolation is enforced by the database even if the service layer has a bug.
4. **Object-level checks** — godown scope, approval limits and state-machine legality are checked inside the service, not the router.
5. **Audit** — every denial is logged with the attempted action; repeated denials raise a security alert.
6. **UI** — hides what the token forbids. This is convenience only; the server never trusts it.

**Test requirement:** for every endpoint, an automated test proves a user without the permission receives 403, and a user from another tenant receives 404.

---

## 7. What the UI must change (nothing removed, only gated)

| Screen | Change |
|---|---|
| Sidebar / nav | Hide items the token's permissions do not include (System Admin already does this — extend the pattern) |
| Products / Suppliers | Hide Delete for non-Owners; disable Add/Edit for Staff and Viewer |
| PO form | Disable Approve when `po.approve` is absent; show "Requires Owner approval above ₹1,00,000" when the value exceeds the threshold |
| GRN form | Disable Confirm for users without `grn.confirm`; restrict the godown dropdown to the user's scope |
| Users page | Hide Invite/Remove for non-Owners; add role and godown-scope editing (currently impossible after invitation) |
| Settings | Read-only for non-Owners rather than hidden, so the team can see the configuration |
| Alerts / Reports | Scope-filtered results with an explicit note when the view is limited |

None of this removes functionality — it makes the existing functionality safe.
