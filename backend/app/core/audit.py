"""
Audit trail — 06_BUSINESS_RULES.md §15.

The rule that shapes this module: *"written in the same transaction as the
change (no lost audit on rollback)"*. That single sentence rules out the
obvious implementations. Middleware that logs after the response has been
sent will happily record changes that were rolled back, and miss changes
that succeeded but crashed on the way out. A background task or queue has
the same problem with worse timing. So `record()` takes the caller's own
session and writes through it — the audit row and the change it describes
commit together or not at all.

§15 also requires that audit rows are immutable and that `before`/`after`
never carry passwords or tokens; `_redact()` handles the latter, and the
former is a grant-level concern (no UPDATE/DELETE on `audit_logs` for the
app role) flagged in the phase notes rather than enforced here.

The spec's list of what must be audited is long and explicit — "every
permission denial" included — so `record()` is deliberately cheap to call
and forgiving about optional fields.
"""

from __future__ import annotations

import json
from typing import Any, Optional
from uuid import UUID

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AccessTokenClaims

# Field names whose values never reach the audit trail, per §15's
# "before/after redacted for passwords and tokens".
_REDACTED_FIELDS = {
    "password",
    "password_hash",
    "new_password",
    "current_password",
    "token",
    "token_hash",
    "access_token",
    "refresh_token",
    "secret",
    "api_key",
}

_REDACTED_PLACEHOLDER = "[redacted]"


def _redact(data: Optional[dict]) -> Optional[dict]:
    if data is None:
        return None
    return {
        key: (_REDACTED_PLACEHOLDER if key.lower() in _REDACTED_FIELDS else value)
        for key, value in data.items()
    }


def _changed_fields(before: Optional[dict], after: Optional[dict]) -> Optional[list[str]]:
    """Which keys actually differ. Stored alongside before/after so the
    Audit Trail screen can show "changed X and Y" without diffing two JSON
    blobs in the browser."""
    if before is None or after is None:
        return None
    keys = set(before) | set(after)
    return sorted(k for k in keys if before.get(k) != after.get(k))


def _json_safe(value: Any) -> Any:
    """UUIDs, dates and Decimals are routine in these payloads and none of
    them are JSON-serialisable by default."""
    return json.loads(json.dumps(value, default=str))


async def get_actor(
    session: AsyncSession, *, entity_type: str, entity_id: UUID, action: str = "created"
) -> Optional[UUID]:
    """Who performed a given action on a given entity, read back from its
    own audit trail rather than a `created_by` column.

    `purchase_orders` (and the rest of the procurement documents) carry no
    `created_by` — `AuditMixin` is deliberately not applied to them, per
    `base.py`'s own convention that it's for master data. BR-PO-03's
    maker-checker rule ("the approver may not be the creator") still needs
    to know who created a PO, though, and since every creation is already
    audited without exception (§15), that audit row *is* the record of who
    made it — asking a second question the schema doesn't otherwise answer.
    """
    return (
        await session.execute(
            text(
                "SELECT actor_user_id FROM audit_logs WHERE entity_type = :entity_type AND entity_id = :entity_id "
                "AND action = :action ORDER BY created_at ASC LIMIT 1"
            ),
            {"entity_type": entity_type, "entity_id": entity_id, "action": action},
        )
    ).scalar_one_or_none()


async def record(
    session: AsyncSession,
    *,
    entity_type: str,
    action: str,
    claims: Optional[AccessTokenClaims] = None,
    entity_id: Optional[UUID] = None,
    entity_label: Optional[str] = None,
    description: Optional[str] = None,
    before: Optional[dict] = None,
    after: Optional[dict] = None,
    request: Optional[Request] = None,
    company_id: Optional[UUID] = None,
    actor_user_id: Optional[UUID] = None,
    actor_name: Optional[str] = None,
    actor_role: Optional[str] = None,
) -> None:
    """Write one audit row through the caller's session.

    Not committed here: the caller commits, so the audit row shares the
    fate of the change it records. `claims` fills in actor/company when a
    request is authenticated; the explicit `company_id`/`actor_*` arguments
    exist for the paths where there is no token yet — a failed login has no
    claims to read, and is exactly the kind of event §15 insists on
    capturing.
    """
    resolved_company = company_id or (UUID(claims.company_id) if claims and claims.company_id else None)
    resolved_actor = actor_user_id or (UUID(claims.user_id) if claims else None)
    resolved_role = actor_role or (claims.role_code if claims else None)
    # BR-AUTH-07: "stamp `impersonated_by` on every audit row". Taken from
    # the token, so nothing a handler forgets to pass can hide it.
    impersonated_by = (
        UUID(claims.impersonated_by) if claims and getattr(claims, "impersonated_by", None) else None
    )

    before_data = _redact(before)
    after_data = _redact(after)

    await session.execute(
        text(
            "INSERT INTO audit_logs "
            "(company_id, entity_type, entity_id, entity_label, action, description, "
            " actor_user_id, actor_name, actor_role, impersonated_by, before_data, after_data, changed_fields, "
            " ip_address, user_agent, source) "
            "VALUES (:company_id, :entity_type, :entity_id, :entity_label, :action, :description, "
            " :actor_user_id, :actor_name, :actor_role, :impersonated_by, "
            " CAST(:before_data AS jsonb), CAST(:after_data AS jsonb), CAST(:changed_fields AS jsonb), "
            " CAST(:ip_address AS inet), :user_agent, 'api')"
        ),
        {
            "company_id": resolved_company,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "entity_label": entity_label,
            "action": action,
            "description": description,
            "actor_user_id": resolved_actor,
            "actor_name": actor_name,
            "actor_role": resolved_role,
            "impersonated_by": impersonated_by,
            "before_data": json.dumps(_json_safe(before_data)) if before_data is not None else None,
            "after_data": json.dumps(_json_safe(after_data)) if after_data is not None else None,
            "changed_fields": json.dumps(_changed_fields(before_data, after_data))
            if _changed_fields(before_data, after_data) is not None
            else None,
            "ip_address": request.client.host if request and request.client else None,
            "user_agent": request.headers.get("user-agent") if request else None,
        },
    )
