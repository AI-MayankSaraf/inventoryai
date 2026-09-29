"""
Subscription plans — the platform console's list of plans a company can be
on (`subscription_plans`, migration c7e2a9f4b1d3).

Companies reference a plan by name. Renaming a plan therefore carries
through to every company on it (ON UPDATE CASCADE); a plan in use cannot be
deleted, only deactivated, which keeps it on existing companies but stops it
being offered for new ones.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import Request, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.errors import CODE_DUPLICATE, CODE_NOT_FOUND, CODE_RECORD_IN_USE, CODE_VALIDATION, ApiError
from app.core.security import AccessTokenClaims

_COLUMNS = (
    "p.id, p.name, p.description, p.sort_order, p.is_active, p.created_at, p.updated_at, "
    "(SELECT count(*) FROM companies c WHERE c.plan = p.name AND c.deleted_at IS NULL) AS company_count"
)


async def list_plans(session: AsyncSession, *, active_only: bool = False) -> list[dict]:
    where = "WHERE p.is_active" if active_only else ""
    rows = (
        await session.execute(text(f"SELECT {_COLUMNS} FROM subscription_plans p {where} ORDER BY p.sort_order, p.name"))
    ).mappings().all()
    return [dict(r) for r in rows]


async def _get(session: AsyncSession, plan_id: UUID) -> dict:
    row = (
        await session.execute(text(f"SELECT {_COLUMNS} FROM subscription_plans p WHERE p.id = :id"), {"id": plan_id})
    ).mappings().first()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Plan not found")
    return dict(row)


async def assert_assignable(session: AsyncSession, name: str, *, current: Optional[str] = None) -> None:
    """A company can be put on any active plan, or kept on the one it has."""
    if current is not None and name == current:
        return
    active = (
        await session.execute(text("SELECT is_active FROM subscription_plans WHERE name = :n"), {"n": name})
    ).scalar()
    if not active:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_VALIDATION,
            f"'{name}' is not an active plan",
            errors=[{"field": "plan", "message": "Choose one of the active plans"}],
        )


def _actor(claims: AccessTokenClaims) -> dict:
    return {"actor_user_id": UUID(claims.user_id), "actor_role": "super_admin"}


def _clean_name(name: Optional[str]) -> str:
    value = (name or "").strip()
    if not value:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_VALIDATION, "A plan needs a name",
                       errors=[{"field": "name", "message": "Required"}])
    return value


def _duplicate() -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, CODE_DUPLICATE, "A plan with that name already exists",
                    errors=[{"field": "name", "message": "Already exists"}])


async def create_plan(
    session: AsyncSession, *, claims: AccessTokenClaims, name: str, description: Optional[str],
    sort_order: Optional[int], request: Optional[Request] = None,
) -> dict:
    name = _clean_name(name)
    if sort_order is None:
        sort_order = (
            await session.execute(text("SELECT COALESCE(max(sort_order), 0) + 10 FROM subscription_plans"))
        ).scalar_one()
    try:
        async with session.begin_nested():
            plan_id = (
                await session.execute(
                    text("INSERT INTO subscription_plans (name, description, sort_order) VALUES (:n, :d, :o) RETURNING id"),
                    {"n": name, "d": (description or "").strip() or None, "o": sort_order},
                )
            ).scalar_one()
    except IntegrityError:
        raise _duplicate()
    after = await _get(session, plan_id)
    await audit.record(session, entity_type="subscription_plan", action="created", entity_id=plan_id,
                       entity_label=name, after=after, request=request, **_actor(claims))
    return after


async def update_plan(
    session: AsyncSession, *, claims: AccessTokenClaims, plan_id: UUID, values: dict, request: Optional[Request] = None,
) -> dict:
    before = await _get(session, plan_id)
    fields = {k: v for k, v in values.items() if k in ("name", "description", "sort_order", "is_active")}
    if "name" in fields:
        fields["name"] = _clean_name(fields["name"])
    if "description" in fields:
        fields["description"] = (fields["description"] or "").strip() or None
    if not fields:
        return before
    assignments = ", ".join(f"{k} = :{k}" for k in fields)
    try:
        async with session.begin_nested():
            await session.execute(text(f"UPDATE subscription_plans SET {assignments} WHERE id = :id"), {**fields, "id": plan_id})
    except IntegrityError:
        raise _duplicate()
    after = await _get(session, plan_id)
    await audit.record(session, entity_type="subscription_plan", action="updated", entity_id=plan_id,
                       entity_label=after["name"], before=before, after=after, request=request, **_actor(claims))
    return after


async def delete_plan(
    session: AsyncSession, *, claims: AccessTokenClaims, plan_id: UUID, request: Optional[Request] = None,
) -> None:
    before = await _get(session, plan_id)
    in_use = (
        await session.execute(text("SELECT count(*) FROM companies WHERE plan = :n"), {"n": before["name"]})
    ).scalar_one()
    if in_use:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_RECORD_IN_USE,
            f"{in_use} compan{'y is' if in_use == 1 else 'ies are'} on the {before['name']} plan; "
            "deactivate it instead, or move them to another plan first",
        )
    await session.execute(text("DELETE FROM subscription_plans WHERE id = :id"), {"id": plan_id})
    await audit.record(session, entity_type="subscription_plan", action="deleted", entity_id=plan_id,
                       entity_label=before["name"], before=before, request=request, **_actor(claims))
