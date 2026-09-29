"""
Baseline reference-data seed — 02_DATABASE_DESIGN.md §14:

    "Seed data required for a working tenant: 9 UoMs, 7 system roles with
    permissions, the tenant's own company row, one default godown, and
    `document_sequences` rows for each doc type."

Split into two phases:

  * `seed_global_reference_data()` — platform-wide, tenant-independent rows
    (UoMs, the permission catalogue, the 7 system roles, and the
    role -> permission grants). Idempotent: safe to run against a database
    that already has this data. Every real tenant shares these rows.

  * `seed_demo_company()` — one example tenant (company, settings, default
    godown, an Owner user, and a document_sequences row per doc type) to
    prove the whole chain end-to-end. Not idempotent by design — running it
    twice creates a second demo company — since it stands in for what a
    real "create tenant" flow will do once that endpoint exists.

Permission catalogue and the role -> permission grants are transcribed from
07_RBAC_MATRIX.md §2/§3. Most codes are pinned exactly to an explicit ✓/◐ row
in that matrix; codes with no explicit row (e.g. `master.view`, several
`*.view` companions of a tested `*.manage`/`*.create` action) are filled in
by inference, each marked "(inferred)" below, following the matrix's own
pattern that read access is broader than write access. `◐` (scoped) is
treated as a grant here — the matrix enforces the actual godown-scope
narrowing at the object level (see 07_RBAC_MATRIX.md §4), not via a
different permission code.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# --------------------------------------------------------------------- UoMs

# code, name, uom_type, decimal_places — 02_DATABASE_DESIGN.md §3:
# "Seed: Nos, Pack, Pkt, Box, Bag, Set, Kg, Litre, Metre."
UOMS = [
    ("Nos", "Numbers", "count", 0),
    ("Pack", "Pack", "count", 0),
    ("Pkt", "Packet", "count", 0),
    ("Box", "Box", "count", 0),
    ("Bag", "Bag", "count", 0),
    ("Set", "Set", "count", 0),
    ("Kg", "Kilogram", "weight", 3),
    ("Litre", "Litre", "volume", 3),
    ("Metre", "Metre", "length", 3),
]

# --------------------------------------------------------------------- Roles

# code, display name — roles.code CHECK constraint pins these 7 exact values.
ROLES = [
    ("super_admin", "Super Admin"),
    ("owner", "Owner"),
    ("purchase_manager", "Purchase Manager"),
    ("godown_manager", "Godown Manager"),
    ("accountant", "Accountant"),
    ("staff", "Staff"),
    ("viewer", "Viewer"),
]

# --------------------------------------------------------------- Permissions

# code, module, description — 07_RBAC_MATRIX.md §2.
PERMISSIONS = [
    ("dashboard.view", "Dashboard", "View dashboard"),
    ("product.view", "Products", "View products"),
    ("product.create", "Products", "Create a product"),
    ("product.update", "Products", "Edit a product"),
    ("product.delete", "Products", "Delete a product"),
    ("product.import", "Products", "Bulk import the catalogue"),
    ("product.export", "Products", "Export the catalogue"),
    ("master.view", "Catalogue masters", "View categories, brands, UoMs"),
    ("master.manage", "Catalogue masters", "Manage categories, brands, UoMs"),
    ("supplier.view", "Suppliers", "View suppliers"),
    ("supplier.create", "Suppliers", "Create a supplier"),
    ("supplier.update", "Suppliers", "Edit a supplier"),
    ("supplier.delete", "Suppliers", "Delete a supplier"),
    ("supplier.export", "Suppliers", "Export suppliers"),
    ("godown.view", "Godowns", "View godowns"),
    ("godown.manage", "Godowns", "Create/edit godowns"),
    ("inventory.view", "Inventory", "View stock (own scope)"),
    ("inventory.view_all", "Inventory", "View stock in all godowns"),
    ("inventory.adjust", "Inventory", "Post a stock correction"),
    ("inventory.transfer", "Inventory", "Transfer between godowns in scope"),
    ("inventory.transfer_any", "Inventory", "Transfer involving a godown outside scope"),
    ("inventory.override_expiry", "Inventory", "Override expiry/batch rules"),
    ("inventory.close_period", "Inventory", "Close an inventory period"),
    ("inventory.export", "Inventory", "Export inventory data"),
    ("rfq.view", "RFQ", "View RFQs"),
    ("rfq.create", "RFQ", "Create an RFQ"),
    ("rfq.update", "RFQ", "Edit an RFQ"),
    ("rfq.delete", "RFQ", "Delete an RFQ"),
    ("rfq.send", "RFQ", "Send an RFQ to suppliers"),
    ("rfq.cancel", "RFQ", "Cancel an RFQ"),
    ("rfq.import", "RFQ", "Import an RFQ from an uploaded file"),
    ("quotation.view", "Quotations", "View supplier quotations"),
    ("quotation.create", "Quotations", "Record a quotation"),
    ("quotation.update", "Quotations", "Edit a quotation"),
    ("quotation.delete", "Quotations", "Delete a quotation"),
    ("quotation.approve", "Quotations", "Approve a quotation"),
    ("quotation.reject", "Quotations", "Reject a quotation"),
    ("comparison.view", "Comparison", "View a quotation comparison"),
    ("comparison.create", "Comparison", "Run a quotation comparison"),
    ("comparison.decide", "Comparison", "Decide the comparison outcome"),
    ("comparison.convert", "Comparison", "Convert a comparison to a PO"),
    ("po.view", "Purchase orders", "View purchase orders"),
    ("po.create", "Purchase orders", "Create a PO"),
    ("po.update", "Purchase orders", "Edit a PO"),
    ("po.delete_draft", "Purchase orders", "Delete a draft PO"),
    ("po.submit", "Purchase orders", "Submit a PO for approval"),
    ("po.approve", "Purchase orders", "Approve a PO (within threshold)"),
    ("po.approve_high_value", "Purchase orders", "Approve a PO above threshold"),
    ("po.send", "Purchase orders", "Send a PO to the supplier"),
    ("po.cancel", "Purchase orders", "Cancel a PO"),
    ("po.close", "Purchase orders", "Short-close a PO"),
    ("proforma.view", "Proforma", "View proforma invoices"),
    ("proforma.create", "Proforma", "Record a proforma invoice"),
    ("proforma.update", "Proforma", "Edit a proforma invoice"),
    ("proforma.approve", "Proforma", "Approve a proforma invoice"),
    ("proforma.approve_variance", "Proforma", "Approve a proforma with variance"),
    ("proforma.raise_query", "Proforma", "Raise a query on a proforma"),
    ("grn.view", "Goods receipt", "View goods receipts"),
    ("grn.create", "Goods receipt", "Create a GRN"),
    ("grn.update", "Goods receipt", "Edit a GRN"),
    ("grn.confirm", "Goods receipt", "Confirm a GRN (posts stock)"),
    ("grn.reverse", "Goods receipt", "Reverse a confirmed GRN"),
    ("grn.receive_other_godown", "Goods receipt", "Receive into another godown"),
    ("grn.allow_excess", "Goods receipt", "Allow excess receipt"),
    ("invoice.view", "Supplier invoice", "View supplier invoices"),
    ("invoice.create", "Supplier invoice", "Enter a supplier invoice"),
    ("invoice.update", "Supplier invoice", "Edit a supplier invoice"),
    ("invoice.match", "Supplier invoice", "Match invoice to PO/GRN"),
    ("invoice.approve", "Supplier invoice", "Approve invoice for payment"),
    ("invoice.dispute", "Supplier invoice", "Dispute an invoice"),
    ("return.view", "Purchase return", "View purchase returns"),
    ("return.create", "Purchase return", "Create a purchase return"),
    ("return.confirm", "Purchase return", "Confirm a purchase return"),
    ("document.view", "Documents", "View documents"),
    ("document.upload", "Documents", "Upload a document"),
    ("document.delete", "Documents", "Delete a document"),
    ("document.download", "Documents", "Download a document"),
    ("ai.view", "AI", "View AI processing queue"),
    ("ai.review", "AI", "Review an AI extraction"),
    ("ai.approve_extraction", "AI", "Approve an AI extraction"),
    ("ai.manage_mappings", "AI", "Manage document schema mappings"),
    ("ai.assistant", "AI", "Use the AI assistant"),
    ("alert.view", "Alerts", "View alerts"),
    ("alert.manage", "Alerts", "Dismiss/resolve/configure alerts"),
    ("report.view", "Reports", "View reports"),
    ("report.export", "Reports", "Export reports"),
    ("user.view", "Users", "View users"),
    ("user.manage", "Users", "Invite/remove users, change roles"),
    ("user.manage_owners", "Users", "Manage users with the Owner role"),
    ("company.view", "Company", "View company profile/settings"),
    ("company.manage", "Company", "Edit company settings, GSTIN, numbering"),
    ("audit.view", "Audit", "View the audit log"),
    ("platform.companies.view", "Platform", "View tenant companies"),
    ("platform.companies.manage", "Platform", "Manage tenant companies"),
    ("platform.users.view", "Platform", "View platform users"),
    ("platform.impersonate", "Platform", "Impersonate a tenant user"),
    ("platform.activity.view", "Platform", "View platform activity"),
]

SA, OW, PM, GM, ST, AC, VW = (
    "super_admin",
    "owner",
    "purchase_manager",
    "godown_manager",
    "staff",
    "accountant",
    "viewer",
)

# code -> set of role codes granted that permission. Transcribed from
# 07_RBAC_MATRIX.md §3.1/§3.2; "(inferred)" codes noted inline have no
# explicit matrix row and follow the surrounding view/manage pattern.
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "dashboard.view": {OW, PM, GM, ST, AC, VW},
    "product.view": {OW, PM, GM, ST, AC, VW},
    "product.create": {OW, PM, GM},
    "product.update": {OW, PM, GM},
    "product.delete": {OW},
    "product.import": {OW, PM},
    "product.export": {OW, PM, AC},
    "master.view": {OW, PM, GM, ST, AC, VW},  # (inferred)
    "master.manage": {OW, PM},  # (inferred)
    "supplier.view": {OW, PM, GM, ST, AC, VW},
    "supplier.create": {OW, PM},
    "supplier.update": {OW, PM},
    "supplier.delete": {OW},
    "supplier.export": {OW, PM, AC},
    "godown.view": {OW, PM, GM, ST, AC, VW},  # (inferred)
    "godown.manage": {OW, GM},
    "inventory.view": {OW, PM, GM, ST, AC, VW},
    "inventory.view_all": {OW, PM, GM, AC, VW},
    "inventory.adjust": {OW, GM},
    "inventory.transfer": {OW, GM},
    "inventory.transfer_any": {OW},
    "inventory.override_expiry": {OW, GM},  # (inferred)
    "inventory.close_period": {OW},  # (inferred)
    "inventory.export": {OW, PM, GM, AC},  # (inferred, mirrors report.export)
    "rfq.view": {OW, PM, GM, AC, VW},  # (inferred)
    "rfq.create": {OW, PM, GM},
    "rfq.update": {OW, PM, GM},  # (inferred)
    "rfq.delete": {OW, PM},  # (inferred)
    "rfq.send": {OW, PM},
    "rfq.cancel": {OW, PM},
    "rfq.import": {OW, PM, GM},  # BR-RFQ-09; mirrors rfq.create (migration a3f6c92e0d17)
    "quotation.view": {OW, PM, AC, VW},
    "quotation.create": {OW, PM},  # (inferred)
    "quotation.update": {OW, PM},  # (inferred)
    "quotation.delete": {OW, PM},  # (inferred)
    "quotation.approve": {OW, PM},
    "quotation.reject": {OW, PM},
    "comparison.view": {OW, PM, AC, VW},
    "comparison.create": {OW, PM},
    "comparison.decide": {OW, PM},
    "comparison.convert": {OW, PM},
    "po.view": {OW, PM, GM, AC, VW},  # (inferred)
    "po.create": {OW, PM},
    "po.update": {OW, PM},  # (inferred)
    "po.delete_draft": {OW, PM},  # (inferred)
    "po.submit": {OW, PM},  # (inferred)
    "po.approve": {OW, PM},
    "po.approve_high_value": {OW},
    "po.send": {OW, PM},
    "po.cancel": {OW, PM},
    "po.close": {OW, PM},  # (inferred)
    "proforma.view": {OW, PM, AC, VW},
    "proforma.create": {OW, PM},  # (inferred)
    "proforma.update": {OW, PM},  # (inferred)
    "proforma.approve": {OW, PM, AC},
    "proforma.approve_variance": {OW},
    "proforma.raise_query": {OW, PM, AC},  # (inferred)
    "grn.view": {OW, PM, GM, ST, AC, VW},  # (inferred)
    "grn.create": {OW, GM, ST},
    "grn.update": {OW, GM},  # (inferred)
    "grn.confirm": {OW, GM},
    "grn.reverse": {OW},
    "grn.receive_other_godown": {OW},
    "grn.allow_excess": {OW, GM},
    "invoice.view": {OW, PM, AC, VW},
    "invoice.create": {OW, AC},  # (inferred)
    "invoice.update": {OW, AC},  # (inferred)
    "invoice.match": {OW, AC},
    "invoice.approve": {OW, AC},
    "invoice.dispute": {OW, PM, AC},
    "return.view": {OW, PM, GM, AC, VW},  # (inferred)
    "return.create": {OW, PM, GM},
    "return.confirm": {OW, PM},  # (inferred)
    "document.view": {OW, PM, GM, ST, AC, VW},
    "document.upload": {OW, PM, GM, ST, AC},
    "document.delete": {OW, PM},
    "document.download": {OW, PM, GM, ST, AC, VW},
    "ai.view": {OW, PM, AC},  # (inferred)
    "ai.review": {OW, PM, AC},
    "ai.approve_extraction": {OW, PM, AC},
    "ai.manage_mappings": {OW, PM},
    "ai.assistant": {OW, PM, GM, ST, AC, VW},
    "alert.view": {OW, PM, GM, ST, AC, VW},
    "alert.manage": {OW, PM, GM},
    "report.view": {OW, PM, GM, AC, VW},
    "report.export": {OW, PM, GM, AC},
    "user.view": {OW, PM, GM},
    "user.manage": {OW},
    "user.manage_owners": {OW},
    "company.view": {OW, PM, GM, ST, AC, VW},  # (inferred)
    "company.manage": {OW},
    "audit.view": {OW, PM, GM, AC},
    "platform.companies.view": {SA},  # (inferred, platform-only)
    "platform.companies.manage": {SA},
    "platform.users.view": {SA},  # (inferred, platform-only)
    "platform.impersonate": {SA},
    "platform.activity.view": {SA},
}

# --------------------------------------------------------- document_sequences

DOC_TYPES = ["rfq", "po", "grn", "proforma", "invoice", "transfer", "return", "adjustment"]

DOC_PREFIXES = {
    "rfq": "RFQ-",
    "po": "PO-",
    "grn": "GRN-",
    "proforma": "PI-",
    "invoice": "INV-",
    "transfer": "TRF-",
    "return": "PR-",
    "adjustment": "ADJ-",
}


def _financial_year(for_month_start: int = 4) -> str:
    """India's FY runs Apr-Mar by default (company_settings.financial_year_start_month).
    Returns e.g. "2026-27" the way the docs show it."""
    import datetime as _dt

    today = _dt.date.today()
    if today.month >= for_month_start:
        start_year = today.year
    else:
        start_year = today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


async def seed_global_reference_data(conn: AsyncConnection) -> None:
    """Idempotent. UoMs, permissions, system roles, and role->permission
    grants — shared by every tenant, never company-scoped."""

    for code, name, uom_type, decimal_places in UOMS:
        await conn.execute(
            text(
                "INSERT INTO uoms (company_id, code, name, uom_type, decimal_places) "
                "VALUES (NULL, :code, :name, :uom_type, :decimal_places) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "name": name, "uom_type": uom_type, "decimal_places": decimal_places},
        )

    for code, module, description in PERMISSIONS:
        await conn.execute(
            text(
                "INSERT INTO permissions (code, module, description) "
                "VALUES (:code, :module, :description) "
                "ON CONFLICT (code) DO UPDATE SET module = EXCLUDED.module, description = EXCLUDED.description"
            ),
            {"code": code, "module": module, "description": description},
        )

    role_ids: dict[str, str] = {}
    for code, name in ROLES:
        row = (
            await conn.execute(
                text(
                    "INSERT INTO roles (company_id, code, name, is_system) "
                    "VALUES (NULL, :code, :name, true) "
                    # uq_roles_code is a unique index on the expression
                    # (COALESCE(company_id, <zero-uuid>), code), not a named
                    # constraint, so ON CONFLICT must repeat that exact
                    # expression for Postgres to infer the index.
                    "ON CONFLICT (coalesce(company_id, '00000000-0000-0000-0000-000000000000'::uuid), code) "
                    "DO UPDATE SET name = EXCLUDED.name "
                    "RETURNING id"
                ),
                {"code": code, "name": name},
            )
        ).first()
        role_ids[code] = row[0]

    perm_rows = (await conn.execute(text("SELECT id, code FROM permissions"))).all()
    perm_ids = {code: pid for pid, code in perm_rows}

    for perm_code, role_codes in ROLE_PERMISSIONS.items():
        permission_id = perm_ids[perm_code]
        for role_code in role_codes:
            await conn.execute(
                text(
                    "INSERT INTO role_permissions (role_id, permission_id) "
                    "VALUES (:role_id, :permission_id) ON CONFLICT DO NOTHING"
                ),
                {"role_id": role_ids[role_code], "permission_id": permission_id},
            )


async def seed_demo_company(
    conn: AsyncConnection,
    *,
    name: str = "Acme Trading Co",
    owner_email: str = "owner@acme-demo.test",
    owner_password: str = "Demo@12345",
) -> dict:
    """One example tenant: company, settings, default godown, an active,
    password-set Owner user (so `POST /auth/login` works against it
    immediately), and a document_sequences row per doc type. Returns the
    created ids. Not idempotent — call once per demo/dev database."""

    company_id = (
        await conn.execute(
            text(
                "INSERT INTO companies (name, state_code, state_name) "
                "VALUES (:name, '27', 'Maharashtra') RETURNING id"
            ),
            {"name": name},
        )
    ).scalar_one()

    owner_role_id = (
        await conn.execute(text("SELECT id FROM roles WHERE company_id IS NULL AND code = 'owner'"))
    ).scalar_one()

    # `state_code`/`city` matter, not just cosmetics: every PO/RFQ delivered
    # here needs this godown's state to compute CGST+SGST vs IGST (BR-PO-02
    # via `_assert_approval_ready`), and a null state code 422s at submit
    # time with no obvious cause. Match the company's own state so the
    # demo tenant works out of the box instead of needing a one-time manual
    # edit through the Godowns screen before the first PO can be submitted.
    godown_id = (
        await conn.execute(
            text(
                "INSERT INTO godowns (company_id, name, code, is_default, city, state_code) "
                "VALUES (:c, 'Main Warehouse', 'MAIN', true, 'Mumbai', '27') RETURNING id"
            ),
            {"c": company_id},
        )
    ).scalar_one()

    await conn.execute(
        text("INSERT INTO company_settings (company_id, default_godown_id) VALUES (:c, :g)"),
        {"c": company_id, "g": godown_id},
    )

    from app.core.security import hash_password

    owner_user_id = (
        await conn.execute(
            text(
                "INSERT INTO users (company_id, email, full_name, role_id, is_platform_admin, has_all_godowns, "
                "status, password_hash, password_changed_at) "
                "VALUES (:c, :email, 'Demo Owner', :r, false, true, 'active', :pw, now()) RETURNING id"
            ),
            {"c": company_id, "email": owner_email, "r": owner_role_id, "pw": hash_password(owner_password)},
        )
    ).scalar_one()

    fy = _financial_year()
    for doc_type in DOC_TYPES:
        await conn.execute(
            text(
                "INSERT INTO document_sequences (company_id, doc_type, financial_year, prefix) "
                "VALUES (:c, :doc_type, :fy, :prefix)"
            ),
            {"c": company_id, "doc_type": doc_type, "fy": fy, "prefix": f"{DOC_PREFIXES[doc_type]}{fy}-"},
        )

    return {
        "company_id": company_id,
        "godown_id": godown_id,
        "owner_user_id": owner_user_id,
        "owner_role_id": owner_role_id,
        "financial_year": fy,
    }


async def seed_platform_admin(
    conn: AsyncConnection, *, email: str = "platform-admin@inventoryai.test", password: str = "Platform@12345"
) -> Optional[dict]:
    """The Super Admin account. It belongs to no company (`company_id IS
    NULL`) and carries the `super_admin` system role, which holds no
    tenant-data permissions at all — its only powers are the platform
    endpoints, impersonation among them (BR-AUTH-07).

    Idempotent: re-running leaves an existing platform admin alone rather
    than creating a second one.
    """
    from app.core.security import hash_password

    existing = (
        await conn.execute(text("SELECT id FROM users WHERE lower(email) = lower(:e)"), {"e": email})
    ).scalar_one_or_none()
    if existing:
        return {"user_id": existing, "created": False}

    role_id = (
        await conn.execute(text("SELECT id FROM roles WHERE company_id IS NULL AND code = 'super_admin'"))
    ).scalar_one()
    user_id = (
        await conn.execute(
            text(
                "INSERT INTO users (company_id, email, full_name, role_id, is_platform_admin, has_all_godowns, "
                "status, password_hash, password_changed_at) "
                "VALUES (NULL, :email, 'Platform Admin', :role, true, true, 'active', :pw, now()) RETURNING id"
            ),
            {"email": email, "role": role_id, "pw": hash_password(password)},
        )
    ).scalar_one()
    return {"user_id": user_id, "created": True}


async def run() -> None:
    # Must run as the BYPASSRLS platform role: global reference data inserts
    # system-wide (NULL company_id) rows that the ordinary app role's own
    # RLS policies deliberately forbid it from creating (see
    # alembic/versions/..._rls_policies.py), and creating a company row at
    # all requires bypassing the companies policy's own WITH CHECK (which
    # compares to the tenant already in session context — there is no
    # tenant context yet for a row that doesn't exist).
    from app.core.db import platform_engine

    async with platform_engine.begin() as conn:
        await seed_global_reference_data(conn)
        result = await seed_demo_company(conn)
        admin = await seed_platform_admin(conn)
        print("Seeded global reference data + demo company:", result)
        print("Platform admin:", admin)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
