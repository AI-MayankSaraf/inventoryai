"""
RFQ -> PO -> GRN endpoints. Permission codes come straight from
07_RBAC_MATRIX.md §4/5/7/9 (`rfq.*`, `po.*`, `grn.*`) -- already seeded by
`app/db/seed.py`, so no seed changes were needed for this module.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_tenant_session, require_permission
from app.core.security import AccessTokenClaims
from app.modules.documents.schemas import VarianceOut as DocVarianceOut
from app.modules.procurement import (
    comparison_service,
    grn_service,
    po_service,
    quotation_service,
    rfq_import,
    rfq_service,
    schemas,
)

router = APIRouter(prefix="/procurement", tags=["procurement"])


# ==================================================================== RFQ

@router.get("/rfqs", response_model=list[schemas.RfqOut])
async def list_rfqs(
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    claims: AccessTokenClaims = Depends(require_permission("rfq.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await rfq_service.list_rfqs(session, company_id=claims.company_id, limit=limit, offset=offset, status_filter=status_filter)


@router.post("/rfqs", response_model=schemas.RfqOut, status_code=status.HTTP_201_CREATED)
async def create_rfq(
    body: schemas.RfqCreate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("rfq.create")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await rfq_service.create_rfq(session, claims=claims, body=body, request=request)


@router.get("/rfqs/{rfq_id}", response_model=schemas.RfqOut)
async def get_rfq(
    rfq_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("rfq.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await rfq_service.get_rfq(session, company_id=claims.company_id, rfq_id=rfq_id)


@router.patch("/rfqs/{rfq_id}", response_model=schemas.RfqOut)
async def update_rfq(
    rfq_id: UUID,
    body: schemas.RfqUpdate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("rfq.update")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await rfq_service.update_rfq(session, claims=claims, rfq_id=rfq_id, body=body, request=request)


@router.post("/rfqs/{rfq_id}/send", response_model=schemas.RfqOut)
async def send_rfq(
    rfq_id: UUID,
    body: schemas.RfqSendRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("rfq.send")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await rfq_service.send_rfq(session, claims=claims, rfq_id=rfq_id, body=body, request=request)


@router.post("/rfqs/{rfq_id}/cancel", response_model=schemas.RfqOut)
async def cancel_rfq(
    rfq_id: UUID,
    body: schemas.RfqCancelRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("rfq.cancel")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await rfq_service.cancel_rfq(session, claims=claims, rfq_id=rfq_id, body=body, request=request)


@router.delete("/rfqs/{rfq_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rfq(
    rfq_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("rfq.delete")),
    session: AsyncSession = Depends(get_tenant_session),
) -> None:
    await rfq_service.delete_rfq(session, claims=claims, rfq_id=rfq_id, request=request)


# ============================================================== RFQ import

_MAX_IMPORT_BYTES = 10 * 1024 * 1024


async def _read_import_file(file: UploadFile) -> bytes:
    content = await file.read()
    if len(content) > _MAX_IMPORT_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="The file is over 10 MB")
    return content


@router.post("/rfqs/import/preview", response_model=schemas.RfqImportPreviewOut)
async def preview_rfq_import(
    file: UploadFile = File(...),
    column_map: Optional[str] = Form(default=None),
    header_row: Optional[int] = Form(default=None, ge=1),
    sheet_index: Optional[int] = Form(default=None, ge=0),
    default_uom_id: Optional[UUID] = Form(default=None),
    claims: AccessTokenClaims = Depends(require_permission("rfq.import")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """Parses the file and reports what it found, how it mapped the columns,
    and what's wrong — writes nothing. The optional form fields are the
    person's overrides from the mapping step (`column_map` is a JSON object
    of field -> 0-based column index). `POST /rfqs/import` re-parses the
    same file with the same overrides, so there is no server-side draft
    state between the two calls."""
    return await rfq_service.preview_import(
        session,
        company_id=claims.company_id,
        filename=file.filename or "upload",
        content=await _read_import_file(file),
        column_map=rfq_import.parse_column_map(column_map),
        header_row=header_row,
        sheet_index=sheet_index,
        default_uom_id=default_uom_id,
    )


@router.post("/rfqs/import", response_model=schemas.RfqOut, status_code=status.HTTP_201_CREATED)
async def import_rfq(
    request: Request,
    file: UploadFile = File(...),
    external_source_name: str = Form(...),
    external_reference_number: Optional[str] = Form(default=None),
    subject: Optional[str] = Form(default=None),
    delivery_godown_id: Optional[UUID] = Form(default=None),
    column_map: Optional[str] = Form(default=None),
    header_row: Optional[int] = Form(default=None, ge=1),
    sheet_index: Optional[int] = Form(default=None, ge=0),
    default_uom_id: Optional[UUID] = Form(default=None),
    claims: AccessTokenClaims = Depends(require_permission("rfq.import")),
    session: AsyncSession = Depends(get_tenant_session),
):
    content = await _read_import_file(file)
    return await rfq_service.import_rfq(
        session,
        claims=claims,
        filename=file.filename or "upload",
        content=content,
        external_source_name=external_source_name,
        external_reference_number=external_reference_number,
        subject=subject,
        delivery_godown_id=delivery_godown_id,
        column_map=rfq_import.parse_column_map(column_map),
        header_row=header_row,
        sheet_index=sheet_index,
        default_uom_id=default_uom_id,
        request=request,
    )


# ===================================================================== PO

@router.get("/purchase-orders", response_model=list[schemas.PoOut])
async def list_pos(
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    supplier_id: Optional[UUID] = None,
    claims: AccessTokenClaims = Depends(require_permission("po.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await po_service.list_pos(session, company_id=claims.company_id, limit=limit, offset=offset, status_filter=status_filter, supplier_id=supplier_id)


@router.post("/purchase-orders", response_model=schemas.PoOut, status_code=status.HTTP_201_CREATED)
async def create_po(
    body: schemas.PoCreate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("po.create")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await po_service.create_po(session, claims=claims, body=body, request=request)


@router.get("/purchase-orders/{po_id}", response_model=schemas.PoOut)
async def get_po(
    po_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("po.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await po_service.get_po(session, company_id=claims.company_id, po_id=po_id)


@router.patch("/purchase-orders/{po_id}", response_model=schemas.PoOut)
async def update_po(
    po_id: UUID,
    body: schemas.PoUpdate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("po.update")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await po_service.update_po(session, claims=claims, po_id=po_id, body=body, request=request)


@router.post("/purchase-orders/{po_id}/submit", response_model=schemas.PoOut)
async def submit_po(
    po_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("po.submit")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await po_service.submit_po(session, claims=claims, po_id=po_id, request=request)


@router.post("/purchase-orders/{po_id}/approve", response_model=schemas.PoOut)
async def approve_po(
    po_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("po.approve")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await po_service.approve_po(session, claims=claims, po_id=po_id, request=request)


@router.post("/purchase-orders/{po_id}/send", response_model=schemas.PoOut)
async def send_po(
    po_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("po.send")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await po_service.send_po(session, claims=claims, po_id=po_id, request=request)


@router.post("/purchase-orders/{po_id}/cancel", response_model=schemas.PoOut)
async def cancel_po(
    po_id: UUID,
    body: schemas.PoCancelRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("po.cancel")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await po_service.cancel_po(session, claims=claims, po_id=po_id, body=body, request=request)


@router.post("/purchase-orders/{po_id}/close", response_model=schemas.PoOut)
async def close_po(
    po_id: UUID,
    body: schemas.PoCloseRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("po.close")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await po_service.close_po(session, claims=claims, po_id=po_id, body=body, request=request)


@router.delete("/purchase-orders/{po_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_po(
    po_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("po.delete_draft")),
    session: AsyncSession = Depends(get_tenant_session),
) -> None:
    await po_service.delete_po(session, claims=claims, po_id=po_id, request=request)


# ==================================================================== GRN

@router.get("/goods-receipts", response_model=list[schemas.GrnOut])
async def list_grns(
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    purchase_order_id: Optional[UUID] = None,
    claims: AccessTokenClaims = Depends(require_permission("grn.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await grn_service.list_grns(session, company_id=claims.company_id, limit=limit, offset=offset, status_filter=status_filter, purchase_order_id=purchase_order_id)


@router.post("/goods-receipts", response_model=schemas.GrnOut, status_code=status.HTTP_201_CREATED)
async def create_grn(
    body: schemas.GrnCreate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("grn.create")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await grn_service.create_grn(session, claims=claims, body=body, request=request)


@router.get("/goods-receipts/{grn_id}", response_model=schemas.GrnOut)
async def get_grn(
    grn_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("grn.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await grn_service.get_grn(session, company_id=claims.company_id, grn_id=grn_id)


@router.patch("/goods-receipts/{grn_id}", response_model=schemas.GrnOut)
async def update_grn(
    grn_id: UUID,
    body: schemas.GrnUpdate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("grn.update")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """Edit a draft receipt. Confirmed receipts are immutable (BR-GRN-08)."""
    return await grn_service.update_draft_grn(session, claims=claims, grn_id=grn_id, body=body, request=request)


@router.get("/goods-receipts/{grn_id}/postings", response_model=list[schemas.GrnPostingOut])
async def grn_postings(
    grn_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("grn.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """The ledger rows this receipt produced — and the offsetting ones if it
    was reversed. Needs `inventory.view` as well: a receipt is visible to
    more roles than the stock ledger behind it."""
    if "inventory.view" not in claims.permissions:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission: inventory.view")
    return await grn_service.list_postings(session, company_id=claims.company_id, grn_id=grn_id)


@router.get("/goods-receipts/{grn_id}/variances", response_model=list[DocVarianceOut])
async def grn_variances(
    grn_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("grn.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """What arrived against what was ordered (`grn_vs_po`), recorded when
    the receipt was confirmed. Gated on `grn.view` like the receipt itself —
    the generic `/variances` list is a payables screen with its own gate."""
    return await grn_service.list_variances(session, company_id=claims.company_id, grn_id=grn_id)


@router.post("/goods-receipts/{grn_id}/confirm", response_model=schemas.GrnConfirmOut)
async def confirm_grn(
    grn_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("grn.confirm")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """Post the receipt. Returns what it did — ledger rows, the PO's new
    progress, the variances recorded and the alerts raised (spec §3.18)."""
    result = await grn_service.confirm_grn(session, claims=claims, grn_id=grn_id, request=request)
    postings = result.pop("postings", [])
    variances = result.pop("variances", [])

    purchase_order = None
    if result["purchase_order_id"]:
        po = await po_service.get_po(session, company_id=claims.company_id, po_id=result["purchase_order_id"])
        purchase_order = {
            "id": po["id"], "po_number": po["po_number"],
            "received_pct": float(po["received_pct"] or 0), "status": po["status"],
        }

    alerts = await grn_service.refresh_grn_alerts(session, claims=claims, grn_id=grn_id)
    return {
        "goods_receipt": result,
        "inventory_postings": postings,
        "purchase_order": purchase_order,
        "variances": variances,
        "alerts_raised": alerts,
    }


@router.post("/goods-receipts/{grn_id}/cancel", response_model=schemas.GrnOut)
async def cancel_grn(
    grn_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("grn.update")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await grn_service.cancel_grn(session, claims=claims, grn_id=grn_id, request=request)


@router.post("/goods-receipts/{grn_id}/reverse", response_model=schemas.GrnOut)
async def reverse_grn(
    grn_id: UUID,
    body: schemas.GrnReverseRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("grn.reverse")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await grn_service.reverse_grn(session, claims=claims, grn_id=grn_id, body=body, request=request)


# ============================================================== Quotations

@router.get("/quotations", response_model=list[schemas.QuotationOut])
async def list_quotations(
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    supplier_id: Optional[UUID] = None,
    rfq_id: Optional[UUID] = None,
    claims: AccessTokenClaims = Depends(require_permission("quotation.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await quotation_service.list_quotations(
        session, company_id=claims.company_id, limit=limit, offset=offset, status_filter=status_filter,
        supplier_id=supplier_id, rfq_id=rfq_id,
    )


@router.post("/quotations", response_model=schemas.QuotationOut, status_code=status.HTTP_201_CREATED)
async def create_quotation(
    body: schemas.QuotationCreate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("quotation.create")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await quotation_service.create_quotation(session, claims=claims, body=body, request=request)


@router.get("/quotations/{quotation_id}", response_model=schemas.QuotationOut)
async def get_quotation(
    quotation_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("quotation.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await quotation_service.get_quotation(session, company_id=claims.company_id, quotation_id=quotation_id)


@router.patch("/quotations/{quotation_id}", response_model=schemas.QuotationOut)
async def update_quotation(
    quotation_id: UUID,
    body: schemas.QuotationUpdate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("quotation.update")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await quotation_service.update_quotation(session, claims=claims, quotation_id=quotation_id, body=body, request=request)


@router.post("/quotations/{quotation_id}/approve", response_model=schemas.QuotationOut)
async def approve_quotation(
    quotation_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("quotation.approve")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await quotation_service.approve_quotation(session, claims=claims, quotation_id=quotation_id, request=request)


@router.post("/quotations/{quotation_id}/reject", response_model=schemas.QuotationOut)
async def reject_quotation(
    quotation_id: UUID,
    body: schemas.QuotationRejectRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("quotation.reject")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await quotation_service.reject_quotation(session, claims=claims, quotation_id=quotation_id, body=body, request=request)


@router.delete("/quotations/{quotation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quotation(
    quotation_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("quotation.delete")),
    session: AsyncSession = Depends(get_tenant_session),
) -> None:
    await quotation_service.delete_quotation(session, claims=claims, quotation_id=quotation_id, request=request)


# ============================================================== Comparison

@router.get("/comparisons", response_model=list[schemas.ComparisonOut])
async def list_comparisons(
    rfq_id: Optional[UUID] = None,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    claims: AccessTokenClaims = Depends(require_permission("comparison.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await comparison_service.list_comparisons(session, company_id=claims.company_id, rfq_id=rfq_id, limit=limit, offset=offset)


@router.post("/comparisons", response_model=schemas.ComparisonOut, status_code=status.HTTP_201_CREATED)
async def build_comparison(
    body: schemas.ComparisonBuildRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("comparison.create")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await comparison_service.build_comparison(session, claims=claims, body=body, request=request)


@router.get("/comparisons/{comparison_id}", response_model=schemas.ComparisonOut)
async def get_comparison(
    comparison_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("comparison.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await comparison_service.get_comparison(session, company_id=claims.company_id, comparison_id=comparison_id)


@router.patch("/comparisons/{comparison_id}/lines/{line_id}", response_model=schemas.ComparisonOut)
async def override_comparison_line(
    comparison_id: UUID,
    line_id: UUID,
    body: schemas.ComparisonOverrideRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("comparison.create")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await comparison_service.override_line(session, claims=claims, comparison_id=comparison_id, line_id=line_id, body=body, request=request)


@router.post("/comparisons/{comparison_id}/reset", response_model=schemas.ComparisonOut)
async def reset_comparison(
    comparison_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("comparison.create")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await comparison_service.reset_comparison(session, claims=claims, comparison_id=comparison_id, request=request)


@router.post("/comparisons/{comparison_id}/convert", response_model=schemas.ComparisonConvertResponse)
async def convert_comparison(
    comparison_id: UUID,
    body: schemas.ComparisonConvertRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("comparison.create")),
    session: AsyncSession = Depends(get_tenant_session),
):
    purchase_orders, comparison_status = await comparison_service.convert_comparison(
        session, claims=claims, comparison_id=comparison_id, body=body, request=request
    )
    return {"purchase_orders": purchase_orders, "comparison_status": comparison_status}
