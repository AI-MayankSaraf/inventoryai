"""
Alert generation, the feed, and per-user read state.

The engine is one pass over every enabled rule. For each, it runs the
rule's query, upserts an alert for everything the query returned, and
resolves any open alert the query *stopped* returning -- which is BR-ALT-04
("an alert auto-resolves when its condition clears") falling straight out
of how the rules are written. Nothing has to notice a replenishment or a
receipt; the condition simply isn't true any more.

BR-ALT-02's deduplication is the database's job, not this module's: a
partial unique index on `(company_id, rule_code, reference_type,
reference_id) WHERE status IN ('new','acknowledged')` already exists, so the
upsert bumps `occurrence_count` and `last_occurred_at` instead of inserting
a second row. A low-stock item produces one alert, not twenty-four a day.

`evaluate()` is deliberately callable on demand. The spec assumes a Celery
beat schedule this project does not have yet; when it does, it calls this
same function and nothing here changes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import commit_and_rescope
from app.core.security import AccessTokenClaims
from app.modules.ops.alert_rules import QUERIES, RULES, RULES_BY_CODE, render


async def _rule_overrides(session: AsyncSession, company_id: UUID) -> dict[str, dict]:
    """Whatever this tenant has customised. Absent means "use the default"."""
    rows = (
        await session.execute(
            text(
                "SELECT rule_code, is_enabled, severity_override, threshold_config, "
                "       notify_email, notify_in_app, last_run_at, last_run_status "
                "FROM alert_rules WHERE company_id = :c"
            ),
            {"c": company_id},
        )
    ).mappings().all()
    return {r["rule_code"]: dict(r) for r in rows}


def _effective(spec, override: Optional[dict]) -> dict:
    """One rule's settings after the tenant's overrides are applied."""
    override = override or {}
    thresholds = dict(spec.thresholds)
    thresholds.update(override.get("threshold_config") or {})
    return {
        "code": spec.code,
        "label": spec.label,
        "description": spec.description,
        "severity": override.get("severity_override") or spec.severity,
        "category": spec.category,
        "reference_type": spec.reference_type,
        "is_enabled": override.get("is_enabled", True),
        "notify_email": override.get("notify_email", True),
        "notify_in_app": override.get("notify_in_app", True),
        "thresholds": thresholds,
        "last_run_at": override.get("last_run_at"),
        "last_run_status": override.get("last_run_status"),
    }


async def list_rules(session: AsyncSession, *, company_id: UUID) -> list[dict]:
    overrides = await _rule_overrides(session, company_id)
    return [_effective(spec, overrides.get(spec.code)) for spec in RULES]


async def set_rule(
    session: AsyncSession,
    *,
    company_id: UUID,
    rule_code: str,
    is_enabled: Optional[bool] = None,
    severity_override: Optional[str] = None,
    threshold_config: Optional[dict] = None,
    notify_email: Optional[bool] = None,
    notify_in_app: Optional[bool] = None,
) -> Optional[dict]:
    """Upsert this tenant's override for one rule."""
    spec = RULES_BY_CODE.get(rule_code)
    if spec is None:
        return None

    existing = (await _rule_overrides(session, company_id)).get(rule_code)
    merged = {
        "is_enabled": existing.get("is_enabled", True) if existing else True,
        "severity_override": existing.get("severity_override") if existing else None,
        "threshold_config": (existing.get("threshold_config") if existing else None) or {},
        "notify_email": existing.get("notify_email", True) if existing else True,
        "notify_in_app": existing.get("notify_in_app", True) if existing else True,
    }
    if is_enabled is not None:
        merged["is_enabled"] = is_enabled
    if severity_override is not None:
        merged["severity_override"] = severity_override
    if threshold_config is not None:
        merged["threshold_config"] = {**merged["threshold_config"], **threshold_config}
    if notify_email is not None:
        merged["notify_email"] = notify_email
    if notify_in_app is not None:
        merged["notify_in_app"] = notify_in_app

    import json

    await session.execute(
        text(
            "INSERT INTO alert_rules (company_id, rule_code, is_enabled, severity_override, "
            " threshold_config, notify_email, notify_in_app) "
            "VALUES (:c, :code, :enabled, :severity, CAST(:thresholds AS jsonb), :email, :in_app) "
            "ON CONFLICT (company_id, rule_code) DO UPDATE SET "
            " is_enabled = EXCLUDED.is_enabled, severity_override = EXCLUDED.severity_override, "
            " threshold_config = EXCLUDED.threshold_config, notify_email = EXCLUDED.notify_email, "
            " notify_in_app = EXCLUDED.notify_in_app, updated_at = now()"
        ),
        {
            "c": company_id,
            "code": rule_code,
            "enabled": merged["is_enabled"],
            "severity": merged["severity_override"],
            "thresholds": json.dumps(merged["threshold_config"]),
            "email": merged["notify_email"],
            "in_app": merged["notify_in_app"],
        },
    )
    await commit_and_rescope(session, company_id)
    overrides = await _rule_overrides(session, company_id)
    return _effective(spec, overrides.get(rule_code))


async def evaluate(
    session: AsyncSession, *, company_id: UUID, only_rule: Optional[str] = None
) -> dict:
    """Run every enabled rule and reconcile the open alerts against it.

    Returns a per-rule tally so a caller (a scheduler, or the Alerts screen's
    refresh) can see what happened rather than just that something did.
    """
    import json

    overrides = await _rule_overrides(session, company_id)
    summary: dict[str, Any] = {"raised": 0, "updated": 0, "resolved": 0, "rules": {}}

    for spec in RULES:
        if only_rule and spec.code != only_rule:
            continue
        settings = _effective(spec, overrides.get(spec.code))
        if not settings["is_enabled"]:
            # A disabled rule must also stop *holding* alerts open, or
            # switching it off would leave its findings on the screen for
            # ever with nothing able to clear them.
            closed = await _resolve_missing(session, company_id, spec.code, keep_ids=[])
            summary["resolved"] += closed
            summary["rules"][spec.code] = {"enabled": False, "raised": 0, "resolved": closed}
            continue

        params: dict[str, Any] = {"c": company_id}
        for key, value in settings["thresholds"].items():
            params[f"threshold_{key}"] = value

        rows = (await session.execute(text(QUERIES[spec.code]), params)).mappings().all()

        raised = updated = 0
        seen_ids: list[UUID] = []
        for row in rows:
            row = dict(row)
            reference_id = row["reference_id"]
            seen_ids.append(reference_id)
            title, description, reference_label, deep_link = render(spec.code, row)

            # The payload keeps the numbers the alert was raised on, so the
            # screen can show them without re-running the rule -- and so a
            # resolved alert still says what it was about.
            payload = {
                k: (str(v) if not isinstance(v, (int, float, str, bool, type(None))) else v)
                for k, v in row.items()
                if k not in ("reference_id", "godown_id")
            }

            result = (
                await session.execute(
                    text(
                        "INSERT INTO alerts (company_id, rule_code, severity, category, title, description, "
                        " reference_type, reference_id, reference_label, deep_link, godown_id, status, "
                        " occurrence_count, last_occurred_at, payload) "
                        "VALUES (:c, :code, :severity, :category, :title, :description, :ref_type, :ref_id, "
                        " :ref_label, :link, :godown, 'new', 1, now(), CAST(:payload AS jsonb)) "
                        "ON CONFLICT (company_id, rule_code, reference_type, reference_id) "
                        " WHERE status IN ('new','acknowledged') "
                        "DO UPDATE SET occurrence_count = alerts.occurrence_count + 1, "
                        " last_occurred_at = now(), title = EXCLUDED.title, "
                        " description = EXCLUDED.description, severity = EXCLUDED.severity, "
                        " payload = EXCLUDED.payload "
                        "RETURNING id, (xmax = 0) AS inserted"
                    ),
                    {
                        "c": company_id,
                        "code": spec.code,
                        "severity": settings["severity"],
                        "category": settings["category"],
                        "title": title,
                        "description": description,
                        "ref_type": spec.reference_type,
                        "ref_id": reference_id,
                        "ref_label": reference_label,
                        "link": deep_link,
                        "godown": row.get("godown_id"),
                        "payload": json.dumps(payload, default=str),
                    },
                )
            ).mappings().first()
            if result and result["inserted"]:
                raised += 1
            else:
                updated += 1

        resolved = await _resolve_missing(session, company_id, spec.code, keep_ids=seen_ids)

        await session.execute(
            text(
                "INSERT INTO alert_rules (company_id, rule_code, last_run_at, last_run_status) "
                "VALUES (:c, :code, now(), 'ok') "
                "ON CONFLICT (company_id, rule_code) DO UPDATE SET "
                " last_run_at = now(), last_run_status = 'ok', updated_at = now()"
            ),
            {"c": company_id, "code": spec.code},
        )

        summary["raised"] += raised
        summary["updated"] += updated
        summary["resolved"] += resolved
        summary["rules"][spec.code] = {
            "enabled": True,
            "raised": raised,
            "updated": updated,
            "resolved": resolved,
        }

    await session.commit()
    return summary


async def _resolve_missing(
    session: AsyncSession, company_id: UUID, rule_code: str, *, keep_ids: list
) -> int:
    """BR-ALT-04. Close every open alert for this rule whose subject the rule
    no longer returns.

    `auto_resolved` is stamped so the trail distinguishes "the problem went
    away" from "a person decided it was fine" -- they mean very different
    things when someone reviews the history later.
    """
    if keep_ids:
        result = await session.execute(
            text(
                "UPDATE alerts SET status = 'resolved', resolved_at = now(), auto_resolved = true "
                "WHERE company_id = :c AND rule_code = :code AND status IN ('new','acknowledged') "
                "AND NOT (reference_id = ANY(CAST(:keep AS uuid[])))"
            ),
            {"c": company_id, "code": rule_code, "keep": list(keep_ids)},
        )
    else:
        result = await session.execute(
            text(
                "UPDATE alerts SET status = 'resolved', resolved_at = now(), auto_resolved = true "
                "WHERE company_id = :c AND rule_code = :code AND status IN ('new','acknowledged')"
            ),
            {"c": company_id, "code": rule_code},
        )
    return result.rowcount or 0


_FEED_SELECT = """
    SELECT a.id, a.rule_code, a.severity, a.category, a.title, a.description,
           a.reference_type, a.reference_id, a.reference_label, a.deep_link,
           a.godown_id, a.variance_id, a.status, a.occurrence_count,
           a.last_occurred_at, a.created_at, a.resolved_at, a.dismissed_at,
           a.auto_resolved, a.payload,
           (ar.user_id IS NOT NULL) AS is_read
    FROM alerts a
    LEFT JOIN alert_reads ar ON ar.alert_id = a.id AND ar.user_id = :viewer
"""


async def list_alerts(
    session: AsyncSession,
    *,
    claims: AccessTokenClaims,
    severity: Optional[str] = None,
    category: Optional[str] = None,
    status_filter: Optional[str] = None,
    unread_only: bool = False,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    where = ["a.company_id = :c"]
    params: dict = {"c": claims.company_id, "viewer": UUID(claims.user_id)}

    if severity:
        where.append("a.severity = :severity")
        params["severity"] = severity
    if category:
        where.append("a.category = :category")
        params["category"] = category
    if status_filter:
        where.append("a.status = :status_filter")
        params["status_filter"] = status_filter
    if unread_only:
        where.append("ar.user_id IS NULL")

    rows = (
        await session.execute(
            text(
                f"{_FEED_SELECT} WHERE {' AND '.join(where)} "
                "ORDER BY CASE a.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
                "              WHEN 'medium' THEN 2 ELSE 3 END, a.last_occurred_at DESC "
                "LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": limit, "offset": offset},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def summary(session: AsyncSession, *, claims: AccessTokenClaims) -> dict:
    """Counts for the header badge and the screen's filter chips.

    Only open alerts count: a resolved one is history, and a badge that
    included it would never go down.
    """
    row = (
        await session.execute(
            text(
                "SELECT COUNT(*) AS total, "
                " COUNT(*) FILTER (WHERE ar.user_id IS NULL) AS unread, "
                " COUNT(*) FILTER (WHERE a.severity = 'critical') AS critical, "
                " COUNT(*) FILTER (WHERE a.severity = 'high') AS high, "
                " COUNT(*) FILTER (WHERE a.severity = 'medium') AS medium, "
                " COUNT(*) FILTER (WHERE a.severity = 'low') AS low "
                "FROM alerts a "
                "LEFT JOIN alert_reads ar ON ar.alert_id = a.id AND ar.user_id = :viewer "
                "WHERE a.company_id = :c AND a.status IN ('new','acknowledged')"
            ),
            {"c": claims.company_id, "viewer": UUID(claims.user_id)},
        )
    ).mappings().first()
    return {
        "total": row["total"] or 0,
        "unread": row["unread"] or 0,
        "by_severity": {
            "critical": row["critical"] or 0,
            "high": row["high"] or 0,
            "medium": row["medium"] or 0,
            "low": row["low"] or 0,
        },
    }


async def mark_read(session: AsyncSession, *, claims: AccessTokenClaims, alert_id: UUID) -> Optional[dict]:
    """BR-ALT-03: read state is per user, in its own table."""
    exists = (
        await session.execute(
            text("SELECT 1 FROM alerts WHERE id = :id AND company_id = :c"),
            {"id": alert_id, "c": claims.company_id},
        )
    ).first()
    if not exists:
        return None

    await session.execute(
        text(
            "INSERT INTO alert_reads (company_id, alert_id, user_id) VALUES (:c, :a, :u) "
            "ON CONFLICT (alert_id, user_id) DO NOTHING"
        ),
        {"c": claims.company_id, "a": alert_id, "u": UUID(claims.user_id)},
    )
    await commit_and_rescope(session, UUID(claims.company_id))
    rows = await list_alerts(session, claims=claims, limit=500)
    return next((r for r in rows if r["id"] == alert_id), None)


async def mark_all_read(session: AsyncSession, *, claims: AccessTokenClaims) -> int:
    """"Mark all as read" means *for me* -- so this writes one row per alert
    for this user, and leaves everyone else's feed alone."""
    result = await session.execute(
        text(
            "INSERT INTO alert_reads (company_id, alert_id, user_id) "
            "SELECT a.company_id, a.id, :u FROM alerts a "
            "WHERE a.company_id = :c AND a.status IN ('new','acknowledged') "
            "ON CONFLICT (alert_id, user_id) DO NOTHING"
        ),
        {"c": claims.company_id, "u": UUID(claims.user_id)},
    )
    await session.commit()
    return result.rowcount or 0


async def set_status(
    session: AsyncSession, *, claims: AccessTokenClaims, alert_id: UUID, new_status: str
) -> Optional[dict]:
    """Acknowledge, dismiss or resolve by hand.

    A person closing an alert is recorded as *not* auto-resolved, which is
    what separates "someone looked at this and decided" from "it stopped
    being true".
    """
    sets = ["status = :status", "auto_resolved = false"]
    params: dict = {"status": new_status, "id": alert_id, "c": claims.company_id}
    if new_status == "resolved":
        sets += ["resolved_at = now()", "resolved_by = :who"]
        params["who"] = UUID(claims.user_id)
    elif new_status == "dismissed":
        sets += ["dismissed_at = now()", "dismissed_by = :who"]
        params["who"] = UUID(claims.user_id)

    result = await session.execute(
        text(f"UPDATE alerts SET {', '.join(sets)} WHERE id = :id AND company_id = :c RETURNING id"),
        params,
    )
    if result.first() is None:
        return None
    await commit_and_rescope(session, UUID(claims.company_id))
    rows = await list_alerts(session, claims=claims, limit=500)
    return next((r for r in rows if r["id"] == alert_id), None)
