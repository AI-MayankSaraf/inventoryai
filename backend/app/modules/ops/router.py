"""
Dashboard and audit-trail endpoints -- `04_API_SPECIFICATION.md` §2.18.

Both permission codes (`inventory.view` for the dashboard, `audit.view` for
the trail) are already seeded. The dashboard sits behind `inventory.view`
rather than a gate of its own because it is mostly stock: every role that
holds it (all six, including Viewer) is meant to see the landing screen.
"""

from __future__ import annotations

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_tenant_session, require_permission
from app.core.errors import ApiError, CODE_NOT_FOUND
from app.core.security import AccessTokenClaims
from app.modules.ops import alert_service, audit_service, dashboard_service, report_service, schemas

router = APIRouter(tags=["ops"])


@router.get("/dashboard/summary", response_model=schemas.DashboardSummaryOut)
async def dashboard_summary(
    godown_id: Optional[UUID] = Query(default=None),
    claims: AccessTokenClaims = Depends(require_permission("inventory.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await dashboard_service.dashboard_summary(session, claims=claims, godown_id=godown_id)


@router.get("/audit-logs", response_model=list[schemas.AuditLogOut])
async def list_audit_logs(
    entity_type: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    actor_user_id: Optional[UUID] = Query(default=None),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    claims: AccessTokenClaims = Depends(require_permission("audit.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await audit_service.list_audit_logs(
        session,
        company_id=claims.company_id,
        entity_type=entity_type,
        action=action,
        actor_user_id=actor_user_id,
        date_from=date_from,
        date_to=date_to,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get("/audit-logs/{entity_type}/{entity_id}", response_model=list[schemas.AuditLogOut])
async def entity_trail(
    entity_type: str,
    entity_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("audit.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await audit_service.entity_trail(
        session, company_id=claims.company_id, entity_type=entity_type, entity_id=entity_id
    )


# ================================================================= alerts

@router.get("/alerts", response_model=list[schemas.AlertOut])
async def list_alerts(
    severity: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    unread_only: bool = Query(default=False),
    limit: int = Query(default=200, le=500),
    offset: int = Query(default=0, ge=0),
    claims: AccessTokenClaims = Depends(require_permission("alert.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await alert_service.list_alerts(
        session,
        claims=claims,
        severity=severity,
        category=category,
        status_filter=status_filter,
        unread_only=unread_only,
        limit=limit,
        offset=offset,
    )


@router.get("/alerts/summary", response_model=schemas.AlertSummaryOut)
async def alert_summary(
    claims: AccessTokenClaims = Depends(require_permission("alert.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await alert_service.summary(session, claims=claims)


@router.post("/alerts/evaluate", response_model=schemas.AlertEvaluateOut)
async def evaluate_alerts(
    rule_code: Optional[str] = Query(default=None),
    claims: AccessTokenClaims = Depends(require_permission("alert.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """Run the rules now.

    Behind `alert.view` rather than `alert.manage` deliberately: this
    changes no business data, it only re-reads the world and reconciles the
    feed against it. Anyone who may see alerts may ask for a fresh set —
    and when a scheduler exists, it calls exactly this.
    """
    return await alert_service.evaluate(
        session, company_id=claims.company_id, only_rule=rule_code
    )


@router.post("/alerts/read-all")
async def mark_all_alerts_read(
    claims: AccessTokenClaims = Depends(require_permission("alert.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    marked = await alert_service.mark_all_read(session, claims=claims)
    return {"marked": marked}


@router.post("/alerts/{alert_id}/read", response_model=schemas.AlertOut)
async def mark_alert_read(
    alert_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("alert.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    result = await alert_service.mark_read(session, claims=claims, alert_id=alert_id)
    if result is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Alert not found")
    return result


@router.post("/alerts/{alert_id}/status", response_model=schemas.AlertOut)
async def set_alert_status(
    alert_id: UUID,
    body: schemas.AlertStatusRequest,
    claims: AccessTokenClaims = Depends(require_permission("alert.manage")),
    session: AsyncSession = Depends(get_tenant_session),
):
    result = await alert_service.set_status(
        session, claims=claims, alert_id=alert_id, new_status=body.status
    )
    if result is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Alert not found")
    return result


@router.get("/alert-rules", response_model=list[schemas.AlertRuleOut])
async def list_alert_rules(
    claims: AccessTokenClaims = Depends(require_permission("alert.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await alert_service.list_rules(session, company_id=claims.company_id)


@router.patch("/alert-rules/{rule_code}", response_model=schemas.AlertRuleOut)
async def update_alert_rule(
    rule_code: str,
    body: schemas.AlertRuleUpdate,
    claims: AccessTokenClaims = Depends(require_permission("alert.manage")),
    session: AsyncSession = Depends(get_tenant_session),
):
    result = await alert_service.set_rule(
        session,
        company_id=claims.company_id,
        rule_code=rule_code,
        is_enabled=body.is_enabled,
        severity_override=body.severity_override,
        threshold_config=body.thresholds,
        notify_email=body.notify_email,
        notify_in_app=body.notify_in_app,
    )
    if result is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Unknown alert rule")
    return result


# ================================================================ reports

@router.get("/reports", response_model=list[schemas.ReportDefinitionOut])
async def list_reports(
    claims: AccessTokenClaims = Depends(require_permission("report.view")),
):
    return report_service.list_reports()


@router.get("/reports/{report_key}", response_model=schemas.ReportResultOut)
async def run_report(
    report_key: str,
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    godown_id: Optional[UUID] = Query(default=None),
    category_id: Optional[UUID] = Query(default=None),
    supplier_id: Optional[UUID] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    claims: AccessTokenClaims = Depends(require_permission("report.view")),
    session: AsyncSession = Depends(get_tenant_session),
):
    result = await report_service.run_report(
        session,
        claims=claims,
        key=report_key,
        date_from=date_from,
        date_to=date_to,
        godown_id=godown_id,
        category_id=category_id,
        supplier_id=supplier_id,
        status_filter=status_filter,
    )
    if result is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Unknown report")
    return result
