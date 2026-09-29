"""
Inventory endpoints -- `04_API_SPECIFICATION.md` §2.7.

Permission codes come straight from `07_RBAC_MATRIX.md` (`inventory.*`) and
are already seeded by `app/db/seed.py`, so this module needed no seed
changes. Note the split the matrix insists on: `inventory.view` is the read
gate and `inventory.view_all` only widens *which godowns* a reader sees
(handled inside the services via `scoped_godown_filter`), while writing
takes `inventory.adjust` or `inventory.transfer` and is scope-checked
separately against the specific godown being touched.
"""

from __future__ import annotations

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_tenant_session, require_permission
from app.core.security import AccessTokenClaims
from app.modules.inventory import schemas, stock_service, transfer_service, txn_service

router = APIRouter(prefix="/inventory", tags=["inventory"])


# =================================================================== stock

@router.get("/stock", response_model=schemas.StockListOut)
async def list_stock(
    godown_id: Optional[UUID] = Query(default=None),
    category_id: Optional[UUID] = Query(default=None),
    brand_id: Optional[UUID] = Query(default=None),
    q: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=200, le=1000),
    offset: int = Query(default=0, ge=0),
    claims: AccessTokenClaims = Depends(require_permission("inventory.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await stock_service.list_stock(
        session,
        claims=claims,
        godown_id=godown_id,
        category_id=category_id,
        brand_id=brand_id,
        q=q,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get("/stock/by-variant/{product_variant_id}", response_model=list[schemas.StockRowOut])
async def stock_by_variant(
    product_variant_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("inventory.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await stock_service.stock_by_variant(session, claims=claims, product_variant_id=product_variant_id)


@router.get("/low-stock", response_model=list[schemas.LowStockRowOut])
async def list_low_stock(
    godown_id: Optional[UUID] = Query(default=None),
    limit: int = Query(default=200, le=1000),
    offset: int = Query(default=0, ge=0),
    claims: AccessTokenClaims = Depends(require_permission("inventory.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await stock_service.list_low_stock(
        session, claims=claims, godown_id=godown_id, limit=limit, offset=offset
    )


@router.get("/batches", response_model=list[schemas.BatchOut])
async def list_batches(
    product_variant_id: UUID = Query(...),
    godown_id: Optional[UUID] = Query(default=None),
    claims: AccessTokenClaims = Depends(require_permission("inventory.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await stock_service.list_batches(
        session, claims=claims, product_variant_id=product_variant_id, godown_id=godown_id
    )


@router.get("/verify-balances", response_model=schemas.VerifyBalancesOut)
async def verify_balances(
    claims: AccessTokenClaims = Depends(require_permission("inventory.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """BR-INV-02 on demand. Reports drift, never silently repairs it."""
    return await stock_service.verify_balances(session, claims=claims)


# ============================================================ transactions

@router.get("/transactions", response_model=list[schemas.TransactionOut])
async def list_transactions(
    txn_type: Optional[str] = Query(default=None, alias="type"),
    godown_id: Optional[UUID] = Query(default=None),
    product_variant_id: Optional[UUID] = Query(default=None),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    claims: AccessTokenClaims = Depends(require_permission("inventory.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await txn_service.list_transactions(
        session,
        claims=claims,
        txn_type=txn_type,
        godown_id=godown_id,
        product_variant_id=product_variant_id,
        date_from=date_from,
        date_to=date_to,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get("/transactions/ledger/{product_variant_id}", response_model=list[schemas.TransactionOut])
async def variant_ledger(
    product_variant_id: UUID,
    godown_id: Optional[UUID] = Query(default=None),
    limit: int = Query(default=200, le=500),
    claims: AccessTokenClaims = Depends(require_permission("inventory.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await txn_service.variant_ledger(
        session, claims=claims, product_variant_id=product_variant_id, godown_id=godown_id, limit=limit
    )


@router.post("/transactions", response_model=schemas.TransactionOut, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    body: schemas.TransactionCreate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("inventory.adjust")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await txn_service.create_transaction(session, claims=claims, body=body, request=request)


@router.post("/transactions/{txn_id}/reverse", response_model=schemas.TransactionOut)
async def reverse_transaction(
    txn_id: UUID,
    body: schemas.TransactionReverseRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("inventory.adjust")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await txn_service.reverse_transaction(
        session, claims=claims, txn_id=txn_id, reason=body.reason, request=request
    )


# =============================================================== transfers

@router.get("/transfers", response_model=list[schemas.TransferOut])
async def list_transfers(
    godown_id: Optional[UUID] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    claims: AccessTokenClaims = Depends(require_permission("inventory.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await transfer_service.list_transfers(
        session, claims=claims, godown_id=godown_id, status_filter=status_filter, limit=limit, offset=offset
    )


@router.get("/transfers/{transfer_id}", response_model=schemas.TransferOut)
async def get_transfer(
    transfer_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("inventory.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await transfer_service.get_transfer(session, claims=claims, transfer_id=transfer_id)


@router.post("/transfers", response_model=schemas.TransferOut, status_code=status.HTTP_201_CREATED)
async def create_transfer(
    body: schemas.TransferCreate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("inventory.transfer")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await transfer_service.create_transfer(session, claims=claims, body=body, request=request)
