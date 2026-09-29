/** Alerts, audit log, dashboard aggregates and reports. */

import type { Id, Money, Percent, Timestamp } from "./common";

/* ---------------------------------------------------------------- Alerts */

export type AlertSeverity = "critical" | "high" | "medium" | "low";
export type AlertCategory = "Inventory" | "Procurement" | "Goods Receipt" | "AI Documents" | "System";
export type AlertStatus = "new" | "acknowledged" | "resolved" | "dismissed";

/** Named server-side rules — the browser never invents an alert (BR-ALT-01). */
export type AlertRuleCode =
  | "LOW_STOCK_BELOW_REORDER"
  | "OUT_OF_STOCK"
  | "GRN_QTY_MISMATCH"
  | "GRN_WRONG_PRODUCT"
  | "PROFORMA_VARIANCE"
  | "INVOICE_VARIANCE"
  | "PO_DELIVERY_DELAYED"
  | "QUOTATION_EXPIRING"
  | "AI_LOW_CONFIDENCE"
  | "DOCUMENT_UNREADABLE"
  | "BATCH_EXPIRING"
  | "STOCK_BALANCE_DRIFT";

export interface Alert {
  id: Id;
  ruleCode: AlertRuleCode;
  severity: AlertSeverity;
  category: AlertCategory;
  title: string;
  description: string;
  referenceType?: string;
  referenceId?: Id;
  referenceLabel?: string;
  deepLink?: string;
  godownId?: Id | null;
  varianceId?: Id | null;
  status: AlertStatus;
  occurrenceCount: number;
  lastOccurredAt: Timestamp;
  createdAt: Timestamp;
  resolvedAt?: Timestamp | null;
  dismissedAt?: Timestamp | null;
  payload?: Record<string, unknown>;
  /** Per-user, resolved by the service for the caller (BR-ALT-03). */
  isRead: boolean;
}

export interface AlertSummary {
  unread: number;
  total: number;
  bySeverity: Record<AlertSeverity, number>;
}

export interface AlertRule {
  ruleCode: AlertRuleCode;
  label: string;
  description: string;
  isEnabled: boolean;
  severity: AlertSeverity;
  notifyEmail: boolean;
  notifyInApp: boolean;
  thresholdConfig?: Record<string, number | string>;
}

/* ------------------------------------------------------------- Audit log */

export type AuditAction =
  | "created" | "updated" | "deleted" | "status_changed"
  | "approved" | "rejected" | "sent" | "confirmed" | "reversed" | "cancelled"
  | "logged_in" | "logged_out" | "impersonated" | "exported"
  | "invited" | "invitation_resent" | "invitation_revoked" | "invitation_accepted"
  | "removed" | "suspended" | "reactivated"
  | "draft_saved" | "matched" | "deactivated";

export interface AuditLog {
  id: Id;
  entityType: string;
  entityId: Id;
  entityLabel: string;
  action: AuditAction;
  description?: string;
  actorUserId: Id | null;
  actorName: string;
  actorRole?: string;
  impersonatedBy?: Id | null;
  beforeData?: Record<string, unknown> | null;
  afterData?: Record<string, unknown> | null;
  changedFields?: string[];
  createdAt: Timestamp;
}

/* ------------------------------------------------------------ Dashboard */

export interface DashboardKpis {
  totalSkus: number;
  lowStockItems: number;
  outOfStock: number;
  inventoryValue: Money;
  pendingPos: number;
  poValuePending: Money;
  godownCount: number;
  skusAddedThisMonth: number;
}

export interface StockStatusSlice {
  key: "in_stock" | "low_stock" | "out_of_stock";
  label: string;
  value: number;
  color: string;
}

export interface ActivityItem {
  id: Id;
  /** `transfer` arrived with the inventory module — godown-to-godown moves
   *  are activity a buyer cares about, and the feed is audit-derived, so
   *  they show up whether or not this union lists them. */
  type: "po" | "grn" | "rfq" | "quotation" | "alert" | "invoice" | "return" | "transfer";
  title: string;
  detail: string;
  time: string;
  href?: string;
}

export interface ProcurementStat {
  key: "open_rfqs" | "quotations" | "approvals" | "deliveries";
  label: string;
  value: number;
  hint: string;
  href: string;
}

export interface DashboardSummary {
  kpis: DashboardKpis;
  stockStatus: StockStatusSlice[];
  lowStock: {
    productVariantId: Id;
    sku: string;
    productName: string;
    godownName: string;
    currentStock: number;
    reorderPoint: number;
    uomCode: string;
    status: "low_stock" | "out_of_stock";
  }[];
  activity: ActivityItem[];
  procurement: ProcurementStat[];
}

/* -------------------------------------------------------------- Reports */

export interface ReportDefinition {
  key: string;
  name: string;
  description: string;
  group: "Inventory" | "Procurement" | "Master Data";
  href: string;
  /** Which filters this report accepts — drives the Reports filter bar. */
  params: ("dateRange" | "godown" | "category" | "supplier" | "status")[];
}

export interface ReportResult {
  key: string;
  title: string;
  generatedAt: Timestamp;
  columns: { key: string; label: string; align?: "left" | "right"; format?: "currency" | "number" | "date" }[];
  rows: Record<string, string | number>[];
  totals?: Record<string, number>;
}

/* ---------------------------------------------------------- Job envelope */

export interface AsyncJob<T = unknown> {
  id: Id;
  type: string;
  status: "queued" | "running" | "succeeded" | "failed";
  progress: number;
  stage?: string;
  result?: T;
  error?: { code: string; message: string } | null;
  createdAt: Timestamp;
  finishedAt?: Timestamp | null;
}

/** Supplier-facing message record — proves what was actually sent. */
export interface OutboundMessage {
  id: Id;
  channel: "email" | "whatsapp" | "sms";
  messageType: "rfq" | "purchase_order" | "proforma_query" | "invitation" | "alert_digest" | "purchase_return";
  relatedType?: string;
  relatedId?: Id;
  supplierId?: Id | null;
  toAddress: string;
  subject: string;
  status: "queued" | "sent" | "delivered" | "bounced" | "failed";
  sentAt?: Timestamp | null;
  errorMessage?: string;
}

export interface Percentage {
  value: Percent;
}
