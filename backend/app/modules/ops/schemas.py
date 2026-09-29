"""
Cross-cutting read models: the dashboard roll-up and the audit feed.

Deliberately absent from every shape here: colours, labels-for-display and
URLs. The dashboard's slices carry a `key` and a count; the procurement
tiles carry a `key` and a count; the activity feed carries the entity type
and id. Which colour a slice is drawn in, and which route an entity lives
at, are the frontend's own business -- baking its routes into API responses
would mean a frontend re-route becomes a backend deploy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ----------------------------------------------------------------- audit

class AuditLogOut(BaseModel):
    id: UUID
    entity_type: str
    entity_id: Optional[UUID] = None
    entity_label: str = ""
    action: str
    description: Optional[str] = None
    actor_user_id: Optional[UUID] = None
    actor_name: str = ""
    actor_role: Optional[str] = None
    impersonated_by: Optional[UUID] = None
    before_data: Optional[dict[str, Any]] = None
    after_data: Optional[dict[str, Any]] = None
    changed_fields: Optional[list[str]] = None
    created_at: datetime


# ------------------------------------------------------------- dashboard

class DashboardKpisOut(BaseModel):
    total_skus: int
    low_stock_items: int
    out_of_stock: int
    inventory_value: float
    pending_pos: int
    po_value_pending: float
    godown_count: int
    skus_added_this_month: int


class StockStatusSliceOut(BaseModel):
    key: Literal["in_stock", "low_stock", "out_of_stock"]
    value: int


class DashboardLowStockOut(BaseModel):
    product_variant_id: UUID
    sku: str
    product_name: str
    godown_name: str
    current_stock: float
    reorder_point: float
    uom_code: str
    status: Literal["low_stock", "out_of_stock"]


class ActivityItemOut(BaseModel):
    id: UUID
    entity_type: str
    entity_id: Optional[UUID] = None
    action: str
    title: str
    detail: str
    created_at: datetime


class ProcurementStatOut(BaseModel):
    key: Literal["open_rfqs", "quotations", "approvals", "deliveries"]
    value: int


class DashboardSummaryOut(BaseModel):
    kpis: DashboardKpisOut
    stock_status: list[StockStatusSliceOut] = Field(default_factory=list)
    low_stock: list[DashboardLowStockOut] = Field(default_factory=list)
    activity: list[ActivityItemOut] = Field(default_factory=list)
    procurement: list[ProcurementStatOut] = Field(default_factory=list)


# ---------------------------------------------------------------- alerts

class AlertOut(BaseModel):
    id: UUID
    rule_code: str
    severity: Literal["critical", "high", "medium", "low"]
    category: str
    title: str
    description: str
    reference_type: Optional[str] = None
    reference_id: Optional[UUID] = None
    reference_label: Optional[str] = None
    deep_link: Optional[str] = None
    godown_id: Optional[UUID] = None
    variance_id: Optional[UUID] = None
    status: Literal["new", "acknowledged", "resolved", "dismissed"]
    occurrence_count: int
    last_occurred_at: datetime
    created_at: datetime
    resolved_at: Optional[datetime] = None
    dismissed_at: Optional[datetime] = None
    # True when the condition cleared on its own (BR-ALT-04) rather than a
    # person closing it — a distinction that matters when reading history.
    auto_resolved: bool = False
    payload: Optional[dict[str, Any]] = None
    # Resolved per caller from `alert_reads` (BR-ALT-03).
    is_read: bool = False


class AlertSummaryOut(BaseModel):
    total: int
    unread: int
    by_severity: dict[str, int]


class AlertStatusRequest(BaseModel):
    status: Literal["acknowledged", "resolved", "dismissed"]


class AlertRuleOut(BaseModel):
    code: str
    label: str
    description: str
    severity: str
    category: str
    reference_type: Optional[str] = None
    is_enabled: bool = True
    notify_email: bool = True
    notify_in_app: bool = True
    thresholds: dict[str, Any] = Field(default_factory=dict)
    last_run_at: Optional[datetime] = None
    last_run_status: Optional[str] = None


class AlertRuleUpdate(BaseModel):
    is_enabled: Optional[bool] = None
    severity_override: Optional[Literal["critical", "high", "medium", "low"]] = None
    thresholds: Optional[dict[str, Any]] = None
    notify_email: Optional[bool] = None
    notify_in_app: Optional[bool] = None


class AlertEvaluateOut(BaseModel):
    """What one evaluation pass did, per rule — so a caller can see the
    engine worked rather than only that it ran."""

    raised: int
    updated: int
    resolved: int
    rules: dict[str, Any]


# --------------------------------------------------------------- reports

class ReportDefinitionOut(BaseModel):
    key: str
    name: str
    description: str
    group: str
    params: list[str]


class ReportColumnOut(BaseModel):
    key: str
    label: str
    align: Optional[str] = None
    format: Optional[str] = None


class ReportResultOut(BaseModel):
    key: str
    title: str
    generated_at: datetime
    columns: list[ReportColumnOut]
    rows: list[dict[str, Any]]
    totals: Optional[dict[str, float]] = None
    row_count: int = 0
