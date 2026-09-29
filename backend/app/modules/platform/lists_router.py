"""
`/company/lists` — the company's own pick-lists (payment terms, delivery
terms, supplier types), edited in Settings.

Anyone signed in to the company can read them (the PO and supplier forms
need them); changing them takes `company.manage`. Records copy the chosen
text, so renaming or removing a value never rewrites history.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.company_lists import LIST_LABELS
from app.core.deps import get_current_claims, get_tenant_session, require_permission
from app.core.errors import CODE_DUPLICATE, CODE_NOT_FOUND, CODE_VALIDATION, ApiError
from app.core.security import AccessTokenClaims
from app.models.identity import COMPANY_LIST_KEYS

router = APIRouter(prefix="/company/lists", tags=["company"])

_KEY_PATTERN = "^(" + "|".join(COMPANY_LIST_KEYS) + ")$"
_COLUMNS = "id, list_key, value, sort_order, is_active, created_at, updated_at"


class ListItemOut(BaseModel):
    id: UUID
    list_key: str
    value: str
    sort_order: int
    is_active: bool


class CompanyListOut(BaseModel):
    key: str
    label: str
    items: list[ListItemOut]


class ListItemCreate(BaseModel):
    list_key: str = Field(pattern=_KEY_PATTERN)
    value: str = Field(min_length=1, max_length=100)


class ListItemUpdate(BaseModel):
    value: Optional[str] = Field(default=None, min_length=1, max_length=100)
    sort_order: Optional[int] = Field(default=None, ge=0, le=32000)
    is_active: Optional[bool] = None


def _duplicate() -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, CODE_DUPLICATE, "That value is already on the list",
                    errors=[{"field": "value", "message": "Already on the list"}])


def _clean(value: Optional[str]) -> str:
    cleaned = " ".join((value or "").split())
    if not cleaned:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_VALIDATION, "Enter a value",
                       errors=[{"field": "value", "message": "Required"}])
    return cleaned


async def _get(session: AsyncSession, item_id: UUID) -> dict:
    row = (
        await session.execute(text(f"SELECT {_COLUMNS} FROM company_lists WHERE id = :id"), {"id": item_id})
    ).mappings().first()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "List value not found")
    return dict(row)


@router.get("", response_model=list[CompanyListOut])
async def get_lists(
    key: Optional[str] = Query(default=None, pattern=_KEY_PATTERN),
    active_only: bool = Query(default=False),
    claims: AccessTokenClaims = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[dict]:
    where = ["TRUE"]
    params: dict = {}
    if key:
        where.append("list_key = :k")
        params["k"] = key
    if active_only:
        where.append("is_active")
    rows = (
        await session.execute(
            text(f"SELECT {_COLUMNS} FROM company_lists WHERE {' AND '.join(where)} ORDER BY sort_order, lower(value)"),
            params,
        )
    ).mappings().all()
    keys = [key] if key else list(COMPANY_LIST_KEYS)
    return [
        {"key": k, "label": LIST_LABELS[k], "items": [dict(r) for r in rows if r["list_key"] == k]}
        for k in keys
    ]


@router.post("", response_model=ListItemOut, status_code=status.HTTP_201_CREATED)
async def add_item(
    body: ListItemCreate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("company.manage")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict:
    value = _clean(body.value)
    sort_order = (
        await session.execute(
            text("SELECT COALESCE(max(sort_order), 0) + 10 FROM company_lists WHERE list_key = :k"), {"k": body.list_key}
        )
    ).scalar_one()
    try:
        async with session.begin_nested():
            item_id = (
                await session.execute(
                    text(
                        "INSERT INTO company_lists (company_id, list_key, value, sort_order) "
                        "VALUES (:c, :k, :v, :o) RETURNING id"
                    ),
                    {"c": claims.company_id, "k": body.list_key, "v": value, "o": sort_order},
                )
            ).scalar_one()
    except IntegrityError:
        raise _duplicate()
    after = await _get(session, item_id)
    await audit.record(session, entity_type="company_list", action="created", claims=claims, entity_id=item_id,
                       entity_label=f"{LIST_LABELS[body.list_key]}: {value}", after=after, request=request)
    await session.commit()
    return after


@router.patch("/{item_id}", response_model=ListItemOut)
async def update_item(
    item_id: UUID,
    body: ListItemUpdate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("company.manage")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict:
    before = await _get(session, item_id)
    fields = body.model_dump(exclude_unset=True)
    if "value" in fields:
        fields["value"] = _clean(fields["value"])
    if not fields:
        return before
    assignments = ", ".join(f"{k} = :{k}" for k in fields)
    try:
        async with session.begin_nested():
            await session.execute(text(f"UPDATE company_lists SET {assignments} WHERE id = :id"), {**fields, "id": item_id})
    except IntegrityError:
        raise _duplicate()
    after = await _get(session, item_id)
    await audit.record(session, entity_type="company_list", action="updated", claims=claims, entity_id=item_id,
                       entity_label=f"{LIST_LABELS[after['list_key']]}: {after['value']}",
                       before=before, after=after, request=request)
    await session.commit()
    return after


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("company.manage")),
    session: AsyncSession = Depends(get_tenant_session),
) -> None:
    before = await _get(session, item_id)
    await session.execute(text("DELETE FROM company_lists WHERE id = :id"), {"id": item_id})
    await audit.record(session, entity_type="company_list", action="deleted", claims=claims, entity_id=item_id,
                       entity_label=f"{LIST_LABELS[before['list_key']]}: {before['value']}", before=before,
                       request=request)
    await session.commit()
