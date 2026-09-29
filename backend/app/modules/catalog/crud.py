"""
Shared CRUD mechanics for the master-data tables.

Seven master resources (products, variants, suppliers, godowns, categories,
brands, UoMs) each need list/get/create/update/delete, and the mechanics are
identical every time: scope to the tenant, soft-delete rather than destroy,
and write an audit row in the same transaction. Hand-writing all 35 of those
endpoints would mean 35 chances to forget the audit call or the tenant
predicate — and the one you forget is the one that leaks.

So the *mechanics* live here and the *policy* stays in the router: each
resource declares its own table, columns, permission codes and audit entity
type explicitly, so you can read a resource definition and know exactly what
it exposes. Nothing is inferred from the table name.

Two deliberate choices:

  * Every statement carries `company_id = :company_id` even though RLS
    already enforces it. Belt and braces: RLS is the guarantee, the
    predicate is what keeps an accidental platform-engine session (which
    bypasses RLS) from doing damage, and it also makes the intent legible
    in query logs.
  * Delete is soft wherever the table has `deleted_at`. 02_DATABASE_DESIGN
    .md §13 makes the master-data uniques partial on `deleted_at IS NULL`
    specifically so "a deleted SKU frees its code" — hard-deleting would
    throw away that design, along with the audit trail's ability to say
    what the row looked like.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.security import AccessTokenClaims


@dataclass(frozen=True)
class Resource:
    """One master-data table and everything the generic handlers need to
    know about it. Declared in router.py, never derived."""

    table: str
    entity_type: str  # audit_logs.entity_type — must be in that CHECK constraint
    label_column: str  # what identifies the row to a human in the audit trail
    columns: list[str]  # returned by list/get/create/update
    writable: list[str]  # settable on create/update
    soft_delete: bool = True
    order_by: str = "name"
    filters: dict[str, str] = field(default_factory=dict)  # query param -> column
    # When set, reads and writes are additionally narrowed to the caller's
    # godown scope (BR-AUTH-12). `"id"` for the godowns table itself;
    # a `godown_id` column on tables that merely reference one.
    godown_scope_column: str = ""


def _select_list(resource: Resource) -> str:
    return ", ".join(resource.columns)


def _alive(resource: Resource) -> str:
    return " AND deleted_at IS NULL" if resource.soft_delete else ""


async def list_rows(
    session: AsyncSession,
    resource: Resource,
    *,
    company_id: str,
    limit: int = 100,
    offset: int = 0,
    filters: Optional[dict[str, Any]] = None,
    claims: Optional[AccessTokenClaims] = None,
) -> list[dict]:
    where = [f"company_id = :company_id{_alive(resource)}"]
    params: dict[str, Any] = {"company_id": company_id, "limit": limit, "offset": offset}

    if resource.godown_scope_column and claims is not None:
        from app.core.deps import scoped_godown_filter

        fragment, scope_params = scoped_godown_filter(claims, resource.godown_scope_column)
        if fragment:
            where.append(fragment)
            params.update(scope_params)

    for param_name, column in (resource.filters or {}).items():
        value = (filters or {}).get(param_name)
        if value is not None:
            where.append(f"{column} = :{param_name}")
            params[param_name] = value

    rows = (
        await session.execute(
            text(
                f"SELECT {_select_list(resource)} FROM {resource.table} "
                f"WHERE {' AND '.join(where)} "
                f"ORDER BY {resource.order_by} LIMIT :limit OFFSET :offset"
            ),
            params,
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def get_row(
    session: AsyncSession,
    resource: Resource,
    *,
    company_id: str,
    row_id: UUID,
    claims: Optional[AccessTokenClaims] = None,
) -> dict:
    where = f"id = :id AND company_id = :company_id{_alive(resource)}"
    params: dict[str, Any] = {"id": row_id, "company_id": company_id}

    if resource.godown_scope_column and claims is not None:
        from app.core.deps import scoped_godown_filter

        fragment, scope_params = scoped_godown_filter(claims, resource.godown_scope_column)
        if fragment:
            where += f" AND {fragment}"
            params.update(scope_params)

    row = (
        await session.execute(
            text(f"SELECT {_select_list(resource)} FROM {resource.table} WHERE {where}"),
            params,
        )
    ).mappings().first()
    if row is None:
        # A row belonging to another tenant is invisible, so "not yours" and
        # "doesn't exist" are deliberately the same answer.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{resource.entity_type} not found")
    return dict(row)


async def create_row(
    session: AsyncSession,
    resource: Resource,
    *,
    claims: AccessTokenClaims,
    values: dict,
    request: Optional[Request] = None,
) -> dict:
    payload = {k: v for k, v in values.items() if k in resource.writable and v is not None}
    payload["id"] = uuid4()
    payload["company_id"] = claims.company_id

    cols = ", ".join(payload.keys())
    placeholders = ", ".join(f":{k}" for k in payload)

    try:
        row = (
            await session.execute(
                text(
                    f"INSERT INTO {resource.table} ({cols}) VALUES ({placeholders}) "
                    f"RETURNING {_select_list(resource)}"
                ),
                payload,
            )
        ).mappings().first()
    except IntegrityError as exc:
        raise _conflict(resource, exc)

    created = dict(row)
    await audit.record(
        session,
        entity_type=resource.entity_type,
        action="created",
        claims=claims,
        entity_id=created["id"],
        entity_label=str(created.get(resource.label_column, "")),
        after=created,
        request=request,
    )
    await session.commit()
    return created


async def update_row(
    session: AsyncSession,
    resource: Resource,
    *,
    claims: AccessTokenClaims,
    row_id: UUID,
    values: dict,
    request: Optional[Request] = None,
) -> dict:
    # Read first: the audit trail's `before_data` and `changed_fields` are
    # only meaningful if we captured the row inside this same transaction.
    before = await get_row(
        session, resource, company_id=claims.company_id, row_id=row_id, claims=claims
    )
    _assert_writable_in_scope(resource, claims, before)

    payload = {k: v for k, v in values.items() if k in resource.writable}
    if not payload:
        return before

    assignments = ", ".join(f"{k} = :{k}" for k in payload)
    payload["id"] = row_id
    payload["company_id"] = claims.company_id

    try:
        row = (
            await session.execute(
                text(
                    f"UPDATE {resource.table} SET {assignments} "
                    f"WHERE id = :id AND company_id = :company_id{_alive(resource)} "
                    f"RETURNING {_select_list(resource)}"
                ),
                payload,
            )
        ).mappings().first()
    except IntegrityError as exc:
        raise _conflict(resource, exc)

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{resource.entity_type} not found")

    after = dict(row)
    await audit.record(
        session,
        entity_type=resource.entity_type,
        action="updated",
        claims=claims,
        entity_id=row_id,
        entity_label=str(after.get(resource.label_column, "")),
        before=before,
        after=after,
        request=request,
    )
    await session.commit()
    return after


async def delete_row(
    session: AsyncSession,
    resource: Resource,
    *,
    claims: AccessTokenClaims,
    row_id: UUID,
    request: Optional[Request] = None,
) -> None:
    before = await get_row(
        session, resource, company_id=claims.company_id, row_id=row_id, claims=claims
    )
    _assert_writable_in_scope(resource, claims, before)

    if resource.soft_delete:
        statement = (
            f"UPDATE {resource.table} SET deleted_at = now() "
            f"WHERE id = :id AND company_id = :company_id AND deleted_at IS NULL"
        )
    else:
        statement = f"DELETE FROM {resource.table} WHERE id = :id AND company_id = :company_id"

    try:
        await session.execute(text(statement), {"id": row_id, "company_id": claims.company_id})
    except IntegrityError:
        # A hard delete blocked by ON DELETE RESTRICT — the row is still
        # referenced by a document somewhere, which is the FK doing its job.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This {resource.entity_type} is still referenced by other records and cannot be deleted",
        )

    await audit.record(
        session,
        entity_type=resource.entity_type,
        action="deleted",
        claims=claims,
        entity_id=row_id,
        entity_label=str(before.get(resource.label_column, "")),
        before=before,
        request=request,
    )
    await session.commit()


def _assert_writable_in_scope(resource: Resource, claims: AccessTokenClaims, row: dict) -> None:
    """BR-AUTH-12 draws a line the read filter alone does not: godown-scoped
    users "see and act on stock only in their assigned godowns;
    `inventory.view_all` overrides **for read**".

    So the override cannot be reused here. A Godown Manager holds
    `inventory.view_all` and can therefore legitimately *see* every godown,
    but that must not let them edit one they are not assigned to — reusing
    the read filter for writes would have granted exactly that.
    """
    if not resource.godown_scope_column:
        return
    from app.core.deps import assert_godown_in_scope

    godown_value = row.get(resource.godown_scope_column)
    if godown_value is not None:
        assert_godown_in_scope(claims, godown_value)


def _conflict(resource: Resource, exc: IntegrityError) -> HTTPException:
    """Turn an integrity error into a response the UI can act on, rather
    than a 500 — and distinguish the two cases, because they mean opposite
    things to the person filling in the form.

    A unique violation (23505) means "this already exists" → 409. A foreign
    key violation (23503) means "something you referenced does not exist"
    → 400, since the fix is to pick a different category/brand/UoM, not to
    rename anything.
    """
    message = str(getattr(exc, "orig", exc))
    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None) or ""

    is_fk = sqlstate == "23503" or "ForeignKeyViolation" in type(getattr(exc, "orig", exc)).__name__
    if is_fk:
        referenced = "referenced record"
        for column, label in (
            ("base_uom_id", "unit of measure"),
            ("uom_id", "unit of measure"),
            ("category_id", "category"),
            ("brand_id", "brand"),
            ("product_id", "product"),
            ("parent_id", "parent category"),
        ):
            if column in message:
                referenced = label
                break
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The {referenced} you selected does not exist",
        )

    detail = f"A {resource.entity_type} with these details already exists"
    for field_name in ("sku", "code", "name", "gstin", "barcode", "email"):
        if f"_{field_name}" in message:
            detail = f"A {resource.entity_type} with this {field_name} already exists"
            break
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
