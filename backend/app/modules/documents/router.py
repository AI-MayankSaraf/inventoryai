"""
Proforma, supplier invoice, purchase return and variance endpoints --
`04_API_SPECIFICATION.md` §2.12, §2.14, §2.15.

Every permission code used here (`proforma.*`, `invoice.*`, `return.*`) was
already seeded by `app/db/seed.py`, so this module needed no seed changes.

Variances have no permission of their own in the matrix: they are read
under `proforma.view` and resolved under `proforma.approve`, because a
variance is only ever a property of the document it was found on, and the
people who may act on the document are exactly the people who may act on
its differences.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_tenant_session, require_permission
from app.core.errors import ApiError, CODE_NOT_FOUND
from app.core.money import D
from app.core.security import AccessTokenClaims
from app.modules.documents import (
    invoice_service,
    proforma_service,
    return_service,
    schemas,
    variance_service,
)

router = APIRouter(tags=["documents"])


# ================================================================ proforma

@router.get("/proforma-invoices", response_model=list[schemas.ProformaOut])
async def list_proformas(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    supplier_id: Optional[UUID] = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    claims: AccessTokenClaims = Depends(require_permission("proforma.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await proforma_service.list_proformas(
        session,
        company_id=claims.company_id,
        status_filter=status_filter,
        supplier_id=supplier_id,
        limit=limit,
        offset=offset,
    )


@router.post("/proforma-invoices", response_model=schemas.ProformaOut, status_code=status.HTTP_201_CREATED)
async def create_proforma(
    body: schemas.ProformaCreate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("proforma.create")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await proforma_service.create_proforma(session, claims=claims, body=body, request=request)


@router.get("/proforma-invoices/{proforma_id}", response_model=schemas.ProformaOut)
async def get_proforma(
    proforma_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("proforma.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await proforma_service.get_proforma(session, company_id=claims.company_id, proforma_id=proforma_id)


@router.patch("/proforma-invoices/{proforma_id}", response_model=schemas.ProformaOut)
async def update_proforma(
    proforma_id: UUID,
    body: schemas.ProformaUpdate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("proforma.update")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await proforma_service.update_proforma(
        session, claims=claims, proforma_id=proforma_id, body=body, request=request
    )


@router.post("/proforma-invoices/{proforma_id}/approve", response_model=schemas.ProformaOut)
async def approve_proforma(
    proforma_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("proforma.approve")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await proforma_service.set_status(
        session, claims=claims, proforma_id=proforma_id, new_status="approved", request=request
    )


@router.post("/proforma-invoices/{proforma_id}/reject", response_model=schemas.ProformaOut)
async def reject_proforma(
    proforma_id: UUID,
    body: schemas.ProformaRejectRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("proforma.approve")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await proforma_service.set_status(
        session, claims=claims, proforma_id=proforma_id, new_status="rejected", note=body.reason, request=request
    )


@router.post("/proforma-invoices/{proforma_id}/raise-query", response_model=schemas.ProformaOut)
async def raise_proforma_query(
    proforma_id: UUID,
    body: schemas.ProformaQueryRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("proforma.raise_query")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await proforma_service.raise_query(
        session, claims=claims, proforma_id=proforma_id, note=body.note, request=request
    )


@router.post("/proforma-invoices/{proforma_id}/status", response_model=schemas.ProformaOut)
async def set_proforma_status(
    proforma_id: UUID,
    body: schemas.ProformaStatusRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("proforma.approve")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """The remaining transitions the dedicated endpoints don't cover --
    `paid`, `completed`, `cancelled`, `under_review`."""
    return await proforma_service.set_status(
        session, claims=claims, proforma_id=proforma_id, new_status=body.status, note=body.note, request=request
    )


@router.get("/proforma-invoices/{proforma_id}/variance", response_model=list[schemas.VarianceOut])
async def proforma_variance(
    proforma_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("proforma.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await variance_service.list_variances(
        session, company_id=claims.company_id, compare_doc_id=proforma_id
    )


@router.delete("/proforma-invoices/{proforma_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proforma(
    proforma_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("proforma.update")),
    session: AsyncSession = Depends(get_tenant_session),
) -> None:
    await proforma_service.delete_proforma(session, claims=claims, proforma_id=proforma_id, request=request)


# ========================================================= supplier invoice

@router.get("/supplier-invoices", response_model=list[schemas.InvoiceOut])
async def list_invoices(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    match_status: Optional[str] = Query(default=None),
    payment_status: Optional[str] = Query(default=None),
    supplier_id: Optional[UUID] = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    claims: AccessTokenClaims = Depends(require_permission("invoice.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await invoice_service.list_invoices(
        session,
        company_id=claims.company_id,
        status_filter=status_filter,
        match_status=match_status,
        payment_status=payment_status,
        supplier_id=supplier_id,
        limit=limit,
        offset=offset,
    )


@router.post("/supplier-invoices", response_model=schemas.InvoiceOut, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    body: schemas.InvoiceCreate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("invoice.create")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await invoice_service.create_invoice(session, claims=claims, body=body, request=request)


@router.get("/supplier-invoices/{invoice_id}", response_model=schemas.InvoiceOut)
async def get_invoice(
    invoice_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("invoice.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await invoice_service.get_invoice(session, company_id=claims.company_id, invoice_id=invoice_id)


@router.patch("/supplier-invoices/{invoice_id}", response_model=schemas.InvoiceOut)
async def update_invoice(
    invoice_id: UUID,
    body: schemas.InvoiceUpdate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("invoice.update")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await invoice_service.update_invoice(
        session, claims=claims, invoice_id=invoice_id, body=body, request=request
    )


@router.post("/supplier-invoices/{invoice_id}/match", response_model=schemas.ThreeWayMatchOut)
async def match_invoice(
    invoice_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("invoice.match")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await invoice_service.run_match(session, claims=claims, invoice_id=invoice_id, request=request)


@router.post("/supplier-invoices/{invoice_id}/approve", response_model=schemas.InvoiceOut)
async def approve_invoice(
    invoice_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("invoice.approve")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await invoice_service.set_status(
        session, claims=claims, invoice_id=invoice_id, new_status="approved", request=request
    )


@router.post("/supplier-invoices/{invoice_id}/dispute", response_model=schemas.InvoiceOut)
async def dispute_invoice(
    invoice_id: UUID,
    body: schemas.InvoiceDisputeRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("invoice.dispute")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await invoice_service.set_status(
        session, claims=claims, invoice_id=invoice_id, new_status="disputed", note=body.reason, request=request
    )


@router.post("/supplier-invoices/{invoice_id}/status", response_model=schemas.InvoiceOut)
async def set_invoice_status(
    invoice_id: UUID,
    body: schemas.InvoiceStatusRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("invoice.update")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """`under_review` and `cancelled` — the transitions without a dedicated
    verb of their own."""
    return await invoice_service.set_status(
        session, claims=claims, invoice_id=invoice_id, new_status=body.status, note=body.note, request=request
    )


@router.post("/supplier-invoices/{invoice_id}/payments", response_model=schemas.InvoiceOut)
async def record_payment(
    invoice_id: UUID,
    body: schemas.InvoicePaymentRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("invoice.approve")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await invoice_service.record_payment(
        session, claims=claims, invoice_id=invoice_id, amount=D(body.amount), request=request
    )


@router.get("/supplier-invoices/{invoice_id}/variance", response_model=list[schemas.VarianceOut])
async def invoice_variance(
    invoice_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("invoice.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await variance_service.list_variances(
        session, company_id=claims.company_id, compare_doc_id=invoice_id
    )


# ========================================================== purchase return

@router.get("/purchase-returns", response_model=list[schemas.ReturnOut])
async def list_returns(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    supplier_id: Optional[UUID] = Query(default=None),
    goods_receipt_id: Optional[UUID] = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    claims: AccessTokenClaims = Depends(require_permission("return.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await return_service.list_returns(
        session, claims=claims, status_filter=status_filter, supplier_id=supplier_id,
        goods_receipt_id=goods_receipt_id, limit=limit, offset=offset,
    )


@router.post("/purchase-returns", response_model=schemas.ReturnOut, status_code=status.HTTP_201_CREATED)
async def create_return(
    body: schemas.ReturnCreate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("return.create")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await return_service.create_return(session, claims=claims, body=body, request=request)


@router.get("/purchase-returns/{return_id}", response_model=schemas.ReturnOut)
async def get_return(
    return_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("return.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await return_service.get_return(session, company_id=claims.company_id, return_id=return_id)


@router.patch("/purchase-returns/{return_id}", response_model=schemas.ReturnOut)
async def update_return(
    return_id: UUID,
    body: schemas.ReturnUpdate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("return.create")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await return_service.update_return(
        session, claims=claims, return_id=return_id, body=body, request=request
    )


@router.post("/purchase-returns/{return_id}/confirm", response_model=schemas.ReturnOut)
async def confirm_return(
    return_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("return.confirm")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """Posts `PURCHASE_RETURN` transactions — this is where stock leaves."""
    return await return_service.confirm_return(session, claims=claims, return_id=return_id, request=request)


@router.post("/purchase-returns/{return_id}/status", response_model=schemas.ReturnOut)
async def set_return_status(
    return_id: UUID,
    body: schemas.ReturnStatusRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("return.confirm")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await return_service.set_status(
        session, claims=claims, return_id=return_id, new_status=body.status, note=body.note, request=request
    )


# ================================================================ variances

@router.get("/variances", response_model=list[schemas.VarianceOut])
async def list_variances(
    comparison_kind: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=200, le=500),
    offset: int = Query(default=0, ge=0),
    claims: AccessTokenClaims = Depends(require_permission("proforma.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await variance_service.list_variances(
        session,
        company_id=claims.company_id,
        comparison_kind=comparison_kind,
        severity=severity,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )


@router.post("/variances/{variance_id}/resolve", response_model=schemas.VarianceOut)
async def resolve_variance(
    variance_id: UUID,
    body: schemas.VarianceResolveRequest,
    claims: AccessTokenClaims = Depends(require_permission("proforma.approve")),
    session: AsyncSession = Depends(get_tenant_session),
):
    result = await variance_service.resolve_variance(
        session,
        company_id=claims.company_id,
        variance_id=variance_id,
        status=body.status,
        note=body.note,
        resolved_by=UUID(claims.user_id),
    )
    if result is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Variance not found")
    await session.commit()
    return result
