"""
Endpoints behind the Supplier detail and Product detail panels.
Logic lives in `detail_service.py`; this file is permissions and shapes.

Permission choices (07_RBAC_MATRIX.md §2):
  * reading a supplier's contacts/links/performance → `supplier.view`
  * a supplier's PO history and price history also need `po.view` — Staff
    can see suppliers but not purchase orders, and PO numbers/values must
    not leak around that gate through the supplier screen
  * editing contacts and item links → `supplier.update`
  * reading conversions/levels → `product.view`; editing → `product.update`
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_tenant_session, require_permission
from app.core.security import AccessTokenClaims
from app.modules.catalog import detail_service as svc
from app.modules.catalog import product_files, product_import
from app.modules.catalog import detail_schemas as s

router = APIRouter(prefix="/catalog", tags=["catalog-detail"])


def _require_also(claims: AccessTokenClaims, code: str) -> None:
    if code not in claims.permissions:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {code}")


# ------------------------------------------------------------ suppliers

@router.get("/supplier-performance", response_model=list[s.SupplierPerformanceOut])
async def all_supplier_performance(
    claims: AccessTokenClaims = Depends(require_permission("supplier.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """Performance for every supplier in one round trip — feeds the
    Suppliers list columns without an N+1."""
    return await svc.performance(session, claims=claims)


@router.get("/suppliers/{supplier_id}/performance", response_model=s.SupplierPerformanceOut)
async def supplier_performance(
    supplier_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("supplier.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return (await svc.performance(session, claims=claims, supplier_id=supplier_id))[0]


@router.get("/suppliers/{supplier_id}/purchase-orders", response_model=list[s.SupplierOrderOut])
async def supplier_purchase_orders(
    supplier_id: UUID,
    limit: int = Query(default=8, ge=1, le=100),
    claims: AccessTokenClaims = Depends(require_permission("supplier.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    _require_also(claims, "po.view")
    return await svc.supplier_orders(session, claims=claims, supplier_id=supplier_id, limit=limit)


@router.get("/suppliers/{supplier_id}/price-history", response_model=list[s.PriceHistoryOut])
async def supplier_price_history(
    supplier_id: UUID,
    product_variant_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("supplier.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    _require_also(claims, "po.view")
    return await svc.price_history(session, claims=claims, supplier_id=supplier_id, variant_id=product_variant_id)


@router.get("/suppliers/{supplier_id}/usage", response_model=s.UsageOut)
async def supplier_usage(
    supplier_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("supplier.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await svc.supplier_usage(session, company_id=claims.company_id, supplier_id=supplier_id)


@router.get("/suppliers/{supplier_id}/contacts", response_model=list[s.ContactOut])
async def list_contacts(
    supplier_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("supplier.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await svc.list_contacts(session, claims=claims, supplier_id=supplier_id)


@router.post("/suppliers/{supplier_id}/contacts", response_model=s.ContactOut, status_code=status.HTTP_201_CREATED)
async def create_contact(
    supplier_id: UUID,
    body: s.ContactCreate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("supplier.update")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await svc.create_contact(session, claims=claims, supplier_id=supplier_id, values=body.model_dump(), request=request)


@router.patch("/supplier-contacts/{contact_id}", response_model=s.ContactOut)
async def update_contact(
    contact_id: UUID,
    body: s.ContactUpdate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("supplier.update")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await svc.update_contact(
        session, claims=claims, contact_id=contact_id, values=body.model_dump(exclude_unset=True), request=request
    )


@router.delete("/supplier-contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("supplier.update")),
    session: AsyncSession = Depends(get_tenant_session),
) -> None:
    await svc.delete_contact(session, claims=claims, contact_id=contact_id, request=request)


@router.get("/suppliers/{supplier_id}/products", response_model=list[s.SupplierProductOut])
async def supplier_products(
    supplier_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("supplier.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await svc.list_links(session, claims=claims, supplier_id=supplier_id)


@router.post("/suppliers/{supplier_id}/products", response_model=s.SupplierProductOut)
async def upsert_supplier_product(
    supplier_id: UUID,
    body: s.SupplierProductUpsert,
    request: Request,
    response: Response,
    claims: AccessTokenClaims = Depends(require_permission("supplier.update")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """Create or update this supplier's code/terms for one SKU — 201 when
    the link is new, 200 when an existing one was updated."""
    row, created = await svc.upsert_link(
        session, claims=claims, supplier_id=supplier_id, values=body.model_dump(), request=request
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return row


@router.delete("/supplier-products/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_supplier_product(
    link_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("supplier.update")),
    session: AsyncSession = Depends(get_tenant_session),
) -> None:
    await svc.delete_link(session, claims=claims, link_id=link_id, request=request)


# ------------------------------------------------------------- variants

@router.get("/variants/{variant_id}/suppliers", response_model=list[s.SupplierProductOut])
async def variant_suppliers(
    variant_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("product.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await svc.list_links(session, claims=claims, variant_id=variant_id)


@router.get("/variants/{variant_id}/usage", response_model=s.UsageOut)
async def variant_usage(
    variant_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("product.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await svc.variant_usage(session, company_id=claims.company_id, variant_id=variant_id)


@router.get("/variants/{variant_id}/uom-conversions", response_model=list[s.ConversionOut])
async def list_conversions(
    variant_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("product.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await svc.list_conversions(session, claims=claims, variant_id=variant_id)


@router.post("/variants/{variant_id}/uom-conversions", response_model=s.ConversionOut, status_code=status.HTTP_201_CREATED)
async def create_conversion(
    variant_id: UUID,
    body: s.ConversionCreate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("product.update")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await svc.create_conversion(session, claims=claims, variant_id=variant_id, values=body.model_dump(), request=request)


@router.delete("/uom-conversions/{conversion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversion(
    conversion_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("product.update")),
    session: AsyncSession = Depends(get_tenant_session),
) -> None:
    await svc.delete_conversion(session, claims=claims, conversion_id=conversion_id, request=request)


@router.get("/variants/{variant_id}/files", response_model=list[s.ProductFileOut])
async def list_product_files(
    variant_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("product.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await product_files.list_files(session, claims=claims, variant_id=variant_id)


@router.post("/variants/{variant_id}/files", response_model=s.ProductFileOut, status_code=status.HTTP_201_CREATED)
async def upload_product_file(
    variant_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    claims: AccessTokenClaims = Depends(require_permission("product.update")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await product_files.upload_file(
        session,
        claims=claims,
        variant_id=variant_id,
        blob=await file.read(),
        filename=file.filename or "file",
        mime_type=file.content_type or "application/octet-stream",
        request=request,
    )


@router.delete("/product-files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_product_file(
    file_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("product.update")),
    session: AsyncSession = Depends(get_tenant_session),
) -> None:
    await product_files.remove_file(session, claims=claims, file_id=file_id, request=request)


@router.get("/variants/{variant_id}/godown-policies", response_model=list[s.GodownPolicyOut])
async def list_policies(
    variant_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("product.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await svc.list_policies(session, claims=claims, variant_id=variant_id)


@router.put("/variants/{variant_id}/godown-policies", response_model=list[s.GodownPolicyOut])
async def replace_policies(
    variant_id: UUID,
    body: s.GodownPoliciesPut,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("product.update")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await svc.replace_policies(
        session, claims=claims, variant_id=variant_id, policies=[p.model_dump() for p in body.policies], request=request
    )


# ------------------------------------------------------- product import
# Under /product-import, not /products/import: the generic
# GET /products/{row_id} route would read "import" as a product id.

_MAX_PRODUCT_IMPORT_BYTES = 10 * 1024 * 1024


async def _read_product_file(file: UploadFile) -> bytes:
    content = await file.read()
    if len(content) > _MAX_PRODUCT_IMPORT_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="The file is over 10 MB")
    return content


@router.get("/product-import/template")
async def product_import_template(
    claims: AccessTokenClaims = Depends(require_permission("product.create")),
):
    """A CSV with every heading the importer reads and one example row."""
    return Response(
        content="﻿" + product_import.template_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="products-import-template.csv"'},
    )


@router.post("/product-import/preview", response_model=s.ProductImportPreviewOut)
async def product_import_preview(
    file: UploadFile = File(...),
    claims: AccessTokenClaims = Depends(require_permission("product.create")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """Reads and checks the file; writes nothing."""
    result = await product_import.check(
        session, claims=claims, filename=file.filename or "upload", content=await _read_product_file(file)
    )
    return result.as_dict()


@router.post("/product-import", response_model=s.ProductImportResultOut, status_code=status.HTTP_201_CREATED)
async def product_import_run(
    request: Request,
    file: UploadFile = File(...),
    claims: AccessTokenClaims = Depends(require_permission("product.create")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """The same checks as the preview; imports every row or none."""
    return await product_import.import_file(
        session, claims=claims, filename=file.filename or "upload",
        content=await _read_product_file(file), request=request,
    )
