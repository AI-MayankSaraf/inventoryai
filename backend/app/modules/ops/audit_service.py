"""
Reading the audit log.

`core/audit.py` has been writing to this table since the first phase; there
has simply never been a way to read it back, which is why the Audit Trail
screen still showed mock rows. Nothing here writes.

One deliberate asymmetry with the rest of the codebase: audit rows are not
godown-scoped. `audit.view` is held by Owner, Purchase Manager, Godown
Manager and Accountant, and an audit trail that quietly omitted the rows a
reader is not scoped to would be worse than no audit trail -- a reviewer
would draw conclusions from a record they cannot tell is partial. RLS still
confines every row to the caller's own tenant.
"""

from __future__ import annotations

from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SELECT = """
    SELECT id, entity_type, entity_id, COALESCE(entity_label, '') AS entity_label, action,
           description, actor_user_id, COALESCE(actor_name, '') AS actor_name, actor_role,
           impersonated_by, before_data, after_data, changed_fields, created_at
    FROM audit_logs
"""


async def list_audit_logs(
    session: AsyncSession,
    *,
    company_id: UUID,
    entity_type: Optional[str] = None,
    action: Optional[str] = None,
    actor_user_id: Optional[UUID] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    q: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    where = ["company_id = :c"]
    params: dict = {"c": company_id}

    if entity_type:
        where.append("entity_type = :entity_type")
        params["entity_type"] = entity_type
    if action:
        where.append("action = :action")
        params["action"] = action
    if actor_user_id:
        where.append("actor_user_id = :actor")
        params["actor"] = actor_user_id
    if date_from:
        where.append("created_at >= :date_from")
        params["date_from"] = date_from
    if date_to:
        where.append("created_at < (CAST(:date_to AS date) + 1)")
        params["date_to"] = date_to
    if q:
        where.append("(entity_label ILIKE :q OR description ILIKE :q OR actor_name ILIKE :q)")
        params["q"] = f"%{q}%"

    rows = (
        await session.execute(
            text(f"{_SELECT} WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": limit, "offset": offset},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def entity_trail(
    session: AsyncSession, *, company_id: UUID, entity_type: str, entity_id: UUID
) -> list[dict]:
    """One record's history, oldest first -- the order it actually happened
    in, which is how the detail screens render it."""
    rows = (
        await session.execute(
            text(
                f"{_SELECT} WHERE company_id = :c AND entity_type = :entity_type AND entity_id = :entity_id "
                "ORDER BY created_at ASC"
            ),
            {"c": company_id, "entity_type": entity_type, "entity_id": entity_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]
