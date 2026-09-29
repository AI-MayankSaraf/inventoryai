"""
Master data — products, variants, suppliers, godowns, categories, brands,
UoMs.

Each resource is declared once as a `Resource` (table, columns, permission
codes, audit entity type) and then gets thin endpoints over the shared
mechanics in `crud.py`. Permission codes come straight from
07_RBAC_MATRIX.md §2 — catalogue masters are gated on `master.*`, products
on `product.*`, suppliers on `supplier.*`, godowns on `godown.*`.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_tenant_session, require_permission
from app.core.errors import CODE_VALIDATION, ApiError
from app.core.security import AccessTokenClaims
from app.modules.catalog import crud, detail_service, schemas
from app.modules.catalog.crud import Resource

router = APIRouter(prefix="/catalog", tags=["catalog"])


PRODUCTS = Resource(
    table="products",
    entity_type="product",
    label_column="name",
    columns=[
        "id", "name", "brand_id", "category_id", "manufacturer_name", "description",
        "hsn_code", "gst_rate", "cess_rate", "tracking_type", "base_uom_id", "is_active",
        "created_at", "updated_at",
    ],
    writable=[
        "name", "brand_id", "category_id", "manufacturer_name", "description",
        "hsn_code", "gst_rate", "cess_rate", "tracking_type", "base_uom_id", "is_active",
    ],
    filters={"category_id": "category_id", "brand_id": "brand_id", "is_active": "is_active"},
)

VARIANTS = Resource(
    table="product_variants",
    entity_type="product_variant",
    label_column="sku",
    columns=[
        "id", "product_id", "sku", "variant_name", "barcode", "hsn_code", "gst_rate",
        "uom_id", "pack_size", "purchase_price", "sale_price", "mrp",
        "reorder_point", "reorder_qty", "lead_time_days", "attributes", "is_active",
        "created_at", "updated_at",
    ],
    writable=[
        "product_id", "sku", "variant_name", "barcode", "hsn_code", "gst_rate",
        "uom_id", "pack_size", "purchase_price", "sale_price", "mrp",
        "reorder_point", "reorder_qty", "lead_time_days", "is_active",
    ],
    order_by="sku",
    filters={"product_id": "product_id", "is_active": "is_active"},
)

SUPPLIERS = Resource(
    table="suppliers",
    entity_type="supplier",
    label_column="name",
    columns=[
        "id", "name", "supplier_code", "supplier_type", "gstin", "pan", "gst_treatment",
        "city", "state_code", "state_name", "address", "pincode", "primary_contact_name",
        "phone", "email", "payment_terms", "payment_terms_days", "credit_limit", "status",
        "bank_name", "bank_account_no", "bank_ifsc", "notes", "created_at", "updated_at",
    ],
    writable=[
        "name", "supplier_code", "supplier_type", "gstin", "pan", "gst_treatment",
        "city", "state_code", "state_name", "address", "pincode", "primary_contact_name",
        "phone", "email", "payment_terms", "payment_terms_days", "credit_limit", "status",
        "bank_name", "bank_account_no", "bank_ifsc", "notes",
    ],
    filters={"status": "status", "state_code": "state_code"},
)

GODOWNS = Resource(
    table="godowns",
    entity_type="godown",
    label_column="name",
    columns=[
        "id", "name", "code", "city", "state_code", "address", "gstin",
        "is_default", "is_active", "incharge_user_id", "capacity_value", "capacity_uom_id",
        "created_at", "updated_at",
    ],
    writable=[
        "name", "code", "city", "state_code", "address", "gstin", "is_active",
        "incharge_user_id", "capacity_value", "capacity_uom_id",
    ],
    filters={"is_active": "is_active"},
    # BR-AUTH-12: a godown-scoped user only sees the godowns they are
    # assigned to -- this list feeds the GRN/transfer dropdowns that
    # 07_RBAC_MATRIX.md §7 says must be restricted to the user's scope.
    godown_scope_column="id",
)

CATEGORIES = Resource(
    table="categories",
    entity_type="category",
    label_column="name",
    columns=["id", "name", "code", "parent_id", "is_active"],
    writable=["name", "code", "parent_id", "is_active"],
    filters={"parent_id": "parent_id", "is_active": "is_active"},
)

BRANDS = Resource(
    table="brands",
    entity_type="brand",
    label_column="name",
    columns=["id", "name", "code", "manufacturer_name", "is_active"],
    writable=["name", "code", "manufacturer_name", "is_active"],
    filters={"is_active": "is_active"},
)

# UoMs are the odd one out: rows with company_id IS NULL are the 9 seeded
# system units shared by every tenant. They are visible to all (the RLS
# policy allows NULL-or-own) but `crud` scopes every write with
# `company_id = :company_id`, so a tenant can add its own units and edit
# those, while the system ones are simply never matched by an update or
# delete — a 404 rather than a confusing database error. `soft_delete` is
# off because the table has no `deleted_at`.
UOMS = Resource(
    table="uoms",
    entity_type="uom",
    label_column="code",
    columns=["id", "code", "name", "uom_type", "decimal_places", "is_active"],
    writable=["code", "name", "uom_type", "decimal_places", "is_active"],
    soft_delete=False,
    order_by="code",
)


# BR-MD blocking rule (02_DATABASE_DESIGN.md §10): a master record in use by
# open documents or holding stock can be neither deactivated nor deleted —
# `409 RECORD_IN_USE` naming what blocks it. The UI pre-checks the same
# thing via the `/usage` endpoints; these guards are the real enforcement.

async def _guard_supplier_update(session, claims, row_id, values) -> None:
    if values.get("status") == "inactive":
        usage = await detail_service.supplier_usage(session, company_id=claims.company_id, supplier_id=row_id)
        detail_service.raise_in_use(usage, "supplier")


async def _guard_godown_fields(session, claims, row_id, values) -> None:
    """In-charge and capacity. The foreign keys alone would accept another
    company's user id, so membership is checked here."""

    errors = []
    user_id = values.get("incharge_user_id")
    if user_id is not None:
        member = (
            await session.execute(
                text(
                    "SELECT 1 FROM users u WHERE u.id = :u AND u.deleted_at IS NULL AND u.status = 'active' "
                    "AND (u.company_id = :c OR EXISTS (SELECT 1 FROM company_users cu "
                    "     WHERE cu.user_id = u.id AND cu.company_id = :c AND cu.status = 'active'))"
                ),
                {"u": user_id, "c": claims.company_id},
            )
        ).first()
        if member is None:
            errors.append({"field": "incharge_user_id", "message": "Choose an active user of this company"})
    has_value = values.get("capacity_value") is not None
    uom_id = values.get("capacity_uom_id")
    if has_value != (uom_id is not None) and ("capacity_value" in values or "capacity_uom_id" in values):
        errors.append({"field": "capacity_value", "message": "Give the capacity and its unit together"})
    if uom_id is not None:
        uom = (
            await session.execute(
                text("SELECT 1 FROM uoms WHERE id = :u AND is_active AND (company_id IS NULL OR company_id = :c)"),
                {"u": uom_id, "c": claims.company_id},
            )
        ).first()
        if uom is None:
            errors.append({"field": "capacity_uom_id", "message": "That unit isn't available"})
    if errors:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_VALIDATION, "Check the godown details", errors=errors)


async def _guard_supplier_delete(session, claims, row_id) -> None:
    usage = await detail_service.supplier_usage(session, company_id=claims.company_id, supplier_id=row_id)
    detail_service.raise_in_use(usage, "supplier")


async def _guard_variant_update(session, claims, row_id, values) -> None:
    if values.get("is_active") is False:
        usage = await detail_service.variant_usage(session, company_id=claims.company_id, variant_id=row_id)
        detail_service.raise_in_use(usage, "product")


async def _guard_variant_delete(session, claims, row_id) -> None:
    usage = await detail_service.variant_usage(session, company_id=claims.company_id, variant_id=row_id)
    detail_service.raise_in_use(usage, "product")


def _crud_routes(
    resource: Resource,
    *,
    path: str,
    view_perm: str,
    create_perm: str,
    update_perm: str,
    delete_perm: str,
    out_schema,
    create_schema,
    update_schema,
    summary_noun: str,
    guard_update=None,
    guard_delete=None,
    guard_create=None,
) -> None:
    """Registers the five standard endpoints for one resource. Each closes
    over its own permission codes, so the generated routes are as strictly
    gated as hand-written ones would be — and the OpenAPI docs show the
    real request/response models."""

    @router.get(path, response_model=list[out_schema], name=f"list_{resource.table}", summary=f"List {summary_noun}")
    async def _list(  # noqa: ANN202
        limit: int = Query(default=100, le=500),
        offset: int = Query(default=0, ge=0),
        claims: AccessTokenClaims = Depends(require_permission(view_perm)),
        session: AsyncSession = Depends(get_tenant_session),
        category_id: Optional[UUID] = None,
        brand_id: Optional[UUID] = None,
        product_id: Optional[UUID] = None,
        parent_id: Optional[UUID] = None,
        status_filter: Optional[str] = Query(default=None, alias="status"),
        state_code: Optional[str] = None,
        is_active: Optional[bool] = None,
    ):
        return await crud.list_rows(
            session,
            resource,
            company_id=claims.company_id,
            claims=claims,
            limit=limit,
            offset=offset,
            filters={
                "category_id": category_id,
                "brand_id": brand_id,
                "product_id": product_id,
                "parent_id": parent_id,
                "status": status_filter,
                "state_code": state_code,
                "is_active": is_active,
            },
        )

    @router.post(
        path,
        response_model=out_schema,
        status_code=status.HTTP_201_CREATED,
        name=f"create_{resource.table}",
        summary=f"Create a {summary_noun.rstrip('s')}",
    )
    async def _create(  # noqa: ANN202
        body: create_schema,
        request: Request,
        claims: AccessTokenClaims = Depends(require_permission(create_perm)),
        session: AsyncSession = Depends(get_tenant_session),
    ):
        values = body.model_dump()
        if guard_create is not None:
            await guard_create(session, claims, None, values)
        return await crud.create_row(session, resource, claims=claims, values=values, request=request)

    @router.get(
        path + "/{row_id}",
        response_model=out_schema,
        name=f"get_{resource.table}",
        summary=f"Get one {summary_noun.rstrip('s')}",
    )
    async def _get(  # noqa: ANN202
        row_id: UUID,
        claims: AccessTokenClaims = Depends(require_permission(view_perm)),
        session: AsyncSession = Depends(get_tenant_session),
    ):
        return await crud.get_row(
            session, resource, company_id=claims.company_id, row_id=row_id, claims=claims
        )

    @router.patch(
        path + "/{row_id}",
        response_model=out_schema,
        name=f"update_{resource.table}",
        summary=f"Update a {summary_noun.rstrip('s')}",
    )
    async def _update(  # noqa: ANN202
        row_id: UUID,
        body: update_schema,
        request: Request,
        claims: AccessTokenClaims = Depends(require_permission(update_perm)),
        session: AsyncSession = Depends(get_tenant_session),
    ):
        values = body.model_dump(exclude_unset=True)
        if guard_update is not None:
            await guard_update(session, claims, row_id, values)
        return await crud.update_row(
            session,
            resource,
            claims=claims,
            row_id=row_id,
            # exclude_unset so PATCH means "change these fields", not
            # "replace the row with these fields and null the rest".
            values=values,
            request=request,
        )

    @router.delete(
        path + "/{row_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"delete_{resource.table}",
        summary=f"Delete a {summary_noun.rstrip('s')}",
    )
    async def _delete(  # noqa: ANN202
        row_id: UUID,
        request: Request,
        claims: AccessTokenClaims = Depends(require_permission(delete_perm)),
        session: AsyncSession = Depends(get_tenant_session),
    ) -> None:
        if guard_delete is not None:
            await guard_delete(session, claims, row_id)
        await crud.delete_row(session, resource, claims=claims, row_id=row_id, request=request)


_crud_routes(
    PRODUCTS,
    path="/products",
    view_perm="product.view",
    create_perm="product.create",
    update_perm="product.update",
    delete_perm="product.delete",
    out_schema=schemas.ProductOut,
    create_schema=schemas.ProductCreate,
    update_schema=schemas.ProductUpdate,
    summary_noun="products",
)

_crud_routes(
    VARIANTS,
    path="/variants",
    view_perm="product.view",
    create_perm="product.create",
    update_perm="product.update",
    delete_perm="product.delete",
    out_schema=schemas.VariantOut,
    create_schema=schemas.VariantCreate,
    update_schema=schemas.VariantUpdate,
    summary_noun="product variants",
    guard_update=_guard_variant_update,
    guard_delete=_guard_variant_delete,
)

_crud_routes(
    SUPPLIERS,
    path="/suppliers",
    view_perm="supplier.view",
    create_perm="supplier.create",
    update_perm="supplier.update",
    delete_perm="supplier.delete",
    out_schema=schemas.SupplierOut,
    create_schema=schemas.SupplierCreate,
    update_schema=schemas.SupplierUpdate,
    summary_noun="suppliers",
    guard_update=_guard_supplier_update,
    guard_delete=_guard_supplier_delete,
)

_crud_routes(
    GODOWNS,
    path="/godowns",
    view_perm="godown.view",
    create_perm="godown.manage",
    update_perm="godown.manage",
    delete_perm="godown.manage",
    out_schema=schemas.GodownOut,
    create_schema=schemas.GodownCreate,
    update_schema=schemas.GodownUpdate,
    summary_noun="godowns",
    guard_create=_guard_godown_fields,
    guard_update=_guard_godown_fields,
)

_crud_routes(
    CATEGORIES,
    path="/categories",
    view_perm="master.view",
    create_perm="master.manage",
    update_perm="master.manage",
    delete_perm="master.manage",
    out_schema=schemas.CategoryOut,
    create_schema=schemas.CategoryCreate,
    update_schema=schemas.CategoryUpdate,
    summary_noun="categories",
)

_crud_routes(
    BRANDS,
    path="/brands",
    view_perm="master.view",
    create_perm="master.manage",
    update_perm="master.manage",
    delete_perm="master.manage",
    out_schema=schemas.BrandOut,
    create_schema=schemas.BrandCreate,
    update_schema=schemas.BrandUpdate,
    summary_noun="brands",
)

_crud_routes(
    UOMS,
    path="/uoms",
    view_perm="master.view",
    create_perm="master.manage",
    update_perm="master.manage",
    delete_perm="master.manage",
    out_schema=schemas.UomOut,
    create_schema=schemas.UomCreate,
    update_schema=schemas.UomUpdate,
    summary_noun="units of measure",
)


@router.get("/uoms-available", response_model=list[schemas.UomOut], tags=["catalog"])
async def list_available_uoms(
    claims: AccessTokenClaims = Depends(require_permission("master.view")),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[dict]:
    """Every UoM this tenant can actually use — its own, plus the 9 shared
    system units. The standard `/uoms` list is tenant-scoped like every
    other master, so it deliberately excludes the system rows; forms need
    both, and `Nos`/`Kg` are system rows."""
    rows = (
        await session.execute(
            text(
                "SELECT id, code, name, uom_type, decimal_places, is_active FROM uoms "
                "WHERE company_id = :c OR company_id IS NULL ORDER BY code"
            ),
            {"c": claims.company_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]
