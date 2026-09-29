/**
 * Alerts, audit trail, dashboard aggregates and reports.
 *
 * Dashboard numbers are computed here from the same tables the detail screens
 * read, so a KPI and the list behind it can never disagree — the old screens
 * each derived their own figures from different hardcoded arrays (I12).
 *
 * Alerts carry the rule that produced them and a link to the record they are
 * about, so "5 items low" is always openable rather than decorative (I13).
 */

import { query } from "./list-query";
import type {
  ActivityItem,
  Alert,
  AlertRule,
  AlertSeverity,
  AlertSummary,
  AuditLog,
  DashboardSummary,
  Id,
  ListParams,
  ListResponse,
  ProcurementStat,
  ReportDefinition,
  ReportResult,
  StockStatusSlice,
} from "@/types";
import { formatRelativeTime } from "@/lib/format";
import { httpGet, httpPatch, httpPost } from "./client";

/* ---------------------------------------------------------------- Alerts */

export interface AlertListRow extends Alert {
  ruleLabel: string;
  godownName: string;
  /** True when BR-ALT-04 closed it because the condition cleared, rather
   *  than a person closing it. History reads very differently either way. */
  autoResolved: boolean;
}

/** `/alerts` — mirrors `AlertOut` in `app/modules/ops/schemas.py`. */
interface AlertOut {
  id: string;
  rule_code: string;
  severity: AlertSeverity;
  category: string;
  title: string;
  description: string;
  reference_type: string | null;
  reference_id: string | null;
  reference_label: string | null;
  deep_link: string | null;
  godown_id: string | null;
  variance_id: string | null;
  status: Alert["status"];
  occurrence_count: number;
  last_occurred_at: string;
  created_at: string;
  resolved_at: string | null;
  dismissed_at: string | null;
  auto_resolved: boolean;
  payload: Record<string, unknown> | null;
  is_read: boolean;
}

/** `/alert-rules` — mirrors `AlertRuleOut`. */
interface AlertRuleOut {
  code: string;
  label: string;
  description: string;
  severity: AlertSeverity;
  category: string;
  reference_type: string | null;
  is_enabled: boolean;
  notify_email: boolean;
  notify_in_app: boolean;
  thresholds: Record<string, number | string>;
  last_run_at: string | null;
  last_run_status: string | null;
}

function toAlert(a: AlertOut): Alert {
  return {
    id: a.id,
    ruleCode: a.rule_code as Alert["ruleCode"],
    severity: a.severity,
    category: a.category as Alert["category"],
    title: a.title,
    description: a.description,
    referenceType: a.reference_type ?? undefined,
    referenceId: a.reference_id ?? undefined,
    referenceLabel: a.reference_label ?? undefined,
    deepLink: a.deep_link ?? undefined,
    godownId: a.godown_id,
    varianceId: a.variance_id,
    status: a.status,
    occurrenceCount: a.occurrence_count,
    lastOccurredAt: a.last_occurred_at,
    createdAt: a.created_at,
    resolvedAt: a.resolved_at,
    dismissedAt: a.dismissed_at,
    payload: a.payload ?? undefined,
    isRead: a.is_read,
  };
}

function toAlertRule(r: AlertRuleOut): AlertRule {
  return {
    ruleCode: r.code as AlertRule["ruleCode"],
    label: r.label,
    description: r.description,
    isEnabled: r.is_enabled,
    severity: r.severity,
    notifyEmail: r.notify_email,
    notifyInApp: r.notify_in_app,
    thresholdConfig: r.thresholds,
  };
}

/**
 * Godown names for the rows that name one.
 *
 * Fetched here rather than joined server-side: the alert row carries the
 * godown *id*, and every other list in this app resolves names the same way,
 * so one changed godown name does not need every stored alert rewritten.
 */
let godownNameCache: Promise<Map<string, string>> | null = null;

function listGodownNames(): Promise<Map<string, string>> {
  godownNameCache ??= httpGet<{ id: string; name: string }[]>("/catalog/godowns", { limit: 500 })
    .then((rows) => new Map(rows.map((g) => [g.id, g.name])))
    .catch(() => new Map<string, string>());
  return godownNameCache;
}

/**
 * The rule catalogue is small, fixed and needed to label every row, so it is
 * fetched alongside the feed and cached for the life of the tab rather than
 * re-requested per render. A rule's *label* never changes at runtime — only
 * its enabled flag and thresholds do, and nothing on this path reads those.
 */
let ruleLabelCache: Promise<Map<string, string>> | null = null;

function ruleLabels(): Promise<Map<string, string>> {
  ruleLabelCache ??= httpGet<AlertRuleOut[]>("/alert-rules")
    .then((rules) => new Map(rules.map((r) => [r.code, r.label])))
    // A failure here must not take the alerts feed down with it: without
    // labels the rows still render, showing the rule code instead.
    .catch(() => new Map<string, string>());
  return ruleLabelCache;
}

export async function listAlerts(params: ListParams = {}): Promise<ListResponse<AlertListRow>> {
  // The endpoint filters by severity/category/status server-side, but search,
  // sort and paging are this app's own list contract, so a generous page is
  // fetched and `query()` applies the rest — the same shape every other list
  // in this codebase uses.
  const [out, labels, godowns] = await Promise.all([
    httpGet<AlertOut[]>("/alerts", { limit: 500 }),
    ruleLabels(),
    listGodownNames(),
  ]);

  const rows: AlertListRow[] = out.map((a) => ({
    ...toAlert(a),
    ruleLabel: labels.get(a.rule_code) ?? a.rule_code,
    godownName: a.godown_id ? godowns.get(a.godown_id) ?? "" : "",
    autoResolved: a.auto_resolved,
  }));

  return query(rows as unknown as Record<string, unknown>[], params, {
    searchFields: ["title", "description", "referenceLabel", "ruleLabel"],
    dateField: "lastOccurredAt",
    facetFields: ["severity", "category", "status"],
    defaultSort: "-lastOccurredAt",
    defaultLimit: 50,
  }) as unknown as ListResponse<AlertListRow>;
}

export async function getAlertSummary(): Promise<AlertSummary> {
  const out = await httpGet<{
    total: number;
    unread: number;
    by_severity: Record<string, number>;
  }>("/alerts/summary");
  return {
    unread: out.unread,
    total: out.total,
    bySeverity: {
      critical: out.by_severity.critical ?? 0,
      high: out.by_severity.high ?? 0,
      medium: out.by_severity.medium ?? 0,
      low: out.by_severity.low ?? 0,
    },
  };
}

/**
 * Re-run the rules now.
 *
 * Alerts are generated server-side on demand — there is no scheduler in
 * Phase 1 — so something has to ask, and the screen that shows them is the
 * honest place to ask from. It is a read of the world, not a write to it.
 */
export async function evaluateAlerts(ruleCode?: string): Promise<{
  raised: number;
  updated: number;
  resolved: number;
}> {
  const out = await httpPost<{ raised: number; updated: number; resolved: number }>(
    `/alerts/evaluate${ruleCode ? `?rule_code=${encodeURIComponent(ruleCode)}` : ""}`,
  );
  return { raised: out.raised, updated: out.updated, resolved: out.resolved };
}

export async function markAlertRead(alertId: Id): Promise<Alert> {
  return toAlert(await httpPost<AlertOut>(`/alerts/${alertId}/read`));
}

export async function markAllAlertsRead(): Promise<number> {
  const out = await httpPost<{ marked: number }>("/alerts/read-all");
  return out.marked;
}

export async function setAlertStatus(
  alertId: Id,
  status: Extract<Alert["status"], "acknowledged" | "resolved" | "dismissed">,
): Promise<Alert> {
  // No client-side audit call here: the service writes the audit row inside
  // the same transaction as the status change, so the trail cannot drift
  // from what actually happened.
  return toAlert(await httpPost<AlertOut>(`/alerts/${alertId}/status`, { status }));
}

export async function listAlertRules(): Promise<AlertRule[]> {
  return (await httpGet<AlertRuleOut[]>("/alert-rules")).map(toAlertRule);
}

export async function setAlertRuleEnabled(ruleCode: string, isEnabled: boolean): Promise<AlertRule> {
  const updated = toAlertRule(
    await httpPatch<AlertRuleOut>(`/alert-rules/${ruleCode}`, { is_enabled: isEnabled }),
  );
  // Labels are unaffected by this, but dropping the cache keeps one source
  // of truth rather than two that could diverge after a rule edit.
  ruleLabelCache = null;
  return updated;
}

export async function setAlertRuleThresholds(
  ruleCode: string,
  thresholds: Record<string, number | string>,
): Promise<AlertRule> {
  return toAlertRule(await httpPatch<AlertRuleOut>(`/alert-rules/${ruleCode}`, { thresholds }));
}

/* ------------------------------------------------------------- Audit log */

export interface AuditListRow extends AuditLog {
  impersonated: boolean;
}

/** `/audit-logs` — mirrors `app/modules/ops/schemas.py`. */
interface AuditLogOut {
  id: string;
  entity_type: string;
  entity_id: string | null;
  entity_label: string;
  action: AuditLog["action"];
  description: string | null;
  actor_user_id: string | null;
  actor_name: string;
  actor_role: string | null;
  impersonated_by: string | null;
  before_data: Record<string, unknown> | null;
  after_data: Record<string, unknown> | null;
  changed_fields: string[] | null;
  created_at: string;
}

function toAuditLog(a: AuditLogOut): AuditLog {
  return {
    id: a.id,
    entityType: a.entity_type,
    entityId: a.entity_id ?? "",
    entityLabel: a.entity_label,
    action: a.action,
    description: a.description ?? undefined,
    actorUserId: a.actor_user_id,
    actorName: a.actor_name,
    actorRole: a.actor_role ?? undefined,
    impersonatedBy: a.impersonated_by,
    beforeData: a.before_data,
    afterData: a.after_data,
    changedFields: a.changed_fields ?? undefined,
    createdAt: a.created_at,
  };
}

export async function listAuditLogs(params: ListParams = {}): Promise<ListResponse<AuditListRow>> {
  const rows: AuditListRow[] = (await httpGet<AuditLogOut[]>("/audit-logs", { limit: 500 })).map((a) => ({
    ...toAuditLog(a),
    impersonated: !!a.impersonated_by,
  }));
  return query(rows as unknown as Record<string, unknown>[], params, {
    searchFields: ["entityLabel", "entityType", "actorName", "description"],
    dateField: "createdAt",
    facetFields: ["action", "entityType", "actorName"],
    defaultSort: "-createdAt",
    defaultLimit: 50,
  }) as unknown as ListResponse<AuditListRow>;
}

/** The trail for one record — what the audit panel on a detail screen shows. */
export async function getAuditTrail(entityType: string, entityId: Id): Promise<AuditLog[]> {
  // The backend returns this oldest-first (the order it happened in); the
  // panel has always rendered newest-first, so it is reversed here rather
  // than changing what the endpoint means.
  const rows = await httpGet<AuditLogOut[]>(`/audit-logs/${entityType}/${entityId}`);
  return rows.map(toAuditLog).reverse();
}

/* ------------------------------------------------------------- Dashboard */

/** `/dashboard/summary` — mirrors `app/modules/ops/schemas.py`. */
interface DashboardSummaryOut {
  kpis: {
    total_skus: number;
    low_stock_items: number;
    out_of_stock: number;
    inventory_value: number;
    pending_pos: number;
    po_value_pending: number;
    godown_count: number;
    skus_added_this_month: number;
  };
  stock_status: { key: StockStatusSlice["key"]; value: number }[];
  low_stock: {
    product_variant_id: string;
    sku: string;
    product_name: string;
    godown_name: string;
    current_stock: number;
    reorder_point: number;
    uom_code: string;
    status: "low_stock" | "out_of_stock";
  }[];
  activity: {
    id: string;
    entity_type: string;
    entity_id: string | null;
    action: string;
    title: string;
    detail: string;
    created_at: string;
  }[];
  procurement: { key: ProcurementStat["key"]; value: number }[];
}

// The backend deliberately sends no labels, colours or URLs — those are
// presentation, and baking this app's routes into API responses would turn
// a frontend re-route into a backend deploy. They are supplied here.
const SLICE_PRESENTATION: Record<StockStatusSlice["key"], { label: string; color: string }> = {
  in_stock: { label: "In stock", color: "var(--chart-1)" },
  low_stock: { label: "Low stock", color: "var(--chart-3)" },
  out_of_stock: { label: "Out of stock", color: "var(--chart-4)" },
};

const PROCUREMENT_PRESENTATION: Record<ProcurementStat["key"], { label: string; hint: string; href: string }> = {
  open_rfqs: { label: "Open RFQs", hint: "Awaiting or comparing quotes", href: "/procurement/rfq" },
  quotations: { label: "Quotations to review", hint: "Received and not yet decided", href: "/procurement/quotations" },
  approvals: {
    label: "Awaiting approval",
    hint: "Purchase orders pending sign-off",
    href: "/procurement/purchase-orders?status=pending_approval",
  },
  deliveries: { label: "Deliveries due", hint: "Ordered and not fully received", href: "/goods-receipt" },
};

/** Audit entity types → the feed's own vocabulary and deep links. */
const ACTIVITY_PRESENTATION: Record<string, { type: ActivityItem["type"]; href?: (id: string) => string }> = {
  purchase_order: { type: "po", href: (id) => `/procurement/purchase-orders/${id}` },
  goods_receipt: { type: "grn", href: (id) => `/goods-receipt/${id}` },
  rfq: { type: "rfq", href: (id) => `/procurement/rfq/${id}` },
  supplier_quotation: { type: "quotation", href: (id) => `/procurement/quotations/${id}` },
  quotation_comparison: { type: "quotation" },
  stock_transfer: { type: "transfer", href: () => "/inventory/transfers" },
  supplier_invoice: { type: "invoice", href: (id) => `/supplier-invoices/${id}` },
  purchase_return: { type: "return", href: (id) => `/purchase-returns/${id}` },
};

export async function getDashboardSummary(godownId?: Id): Promise<DashboardSummary> {
  const out = await httpGet<DashboardSummaryOut>("/dashboard/summary", {
    ...(godownId ? { godown_id: godownId } : {}),
  });

  return {
    kpis: {
      totalSkus: out.kpis.total_skus,
      lowStockItems: out.kpis.low_stock_items,
      outOfStock: out.kpis.out_of_stock,
      inventoryValue: out.kpis.inventory_value,
      pendingPos: out.kpis.pending_pos,
      poValuePending: out.kpis.po_value_pending,
      godownCount: out.kpis.godown_count,
      skusAddedThisMonth: out.kpis.skus_added_this_month,
    },
    stockStatus: out.stock_status.map((s) => ({
      key: s.key,
      value: s.value,
      ...SLICE_PRESENTATION[s.key],
    })),
    lowStock: out.low_stock.map((r) => ({
      productVariantId: r.product_variant_id,
      sku: r.sku,
      productName: r.product_name,
      godownName: r.godown_name,
      currentStock: r.current_stock,
      reorderPoint: r.reorder_point,
      uomCode: r.uom_code,
      status: r.status,
    })),
    activity: out.activity.map((a) => {
      const presentation = ACTIVITY_PRESENTATION[a.entity_type];
      return {
        id: a.id,
        type: presentation?.type ?? "alert",
        title: a.title,
        detail: a.detail,
        // `time` is rendered bare in the feed, so it is formatted here
        // rather than passed through as an ISO string (which is what the
        // mock did, and why the feed used to show raw timestamps).
        time: formatRelativeTime(a.created_at),
        href: presentation?.href && a.entity_id ? presentation.href(a.entity_id) : undefined,
      };
    }),
    procurement: out.procurement.map((p) => ({
      key: p.key,
      value: p.value,
      ...PROCUREMENT_PRESENTATION[p.key],
    })),
  };
}

/* --------------------------------------------------------------- Reports */

/** `/reports` — mirrors `ReportDefinitionOut` in `app/modules/ops/schemas.py`. */
interface ReportDefinitionOut {
  key: string;
  name: string;
  description: string;
  group: string;
  params: string[];
}

/** `/reports/{key}` — mirrors `ReportResultOut`. */
interface ReportResultOut {
  key: string;
  title: string;
  generated_at: string;
  columns: { key: string; label: string; align: string | null; format: string | null }[];
  rows: Record<string, string | number | null>[];
  totals: Record<string, number> | null;
  row_count: number;
}

export async function listReports(): Promise<ReportDefinition[]> {
  const out = await httpGet<ReportDefinitionOut[]>("/reports");
  return out.map((d) => ({
    key: d.key,
    name: d.name,
    description: d.description,
    group: d.group as ReportDefinition["group"],
    // The route is this app's business, not the reporting service's.
    href: `/reports?report=${d.key}`,
    params: d.params as ReportDefinition["params"],
  }));
}

export interface ReportParams {
  godownId?: Id;
  categoryId?: Id;
  supplierId?: Id;
  status?: string;
  dateFrom?: string;
  dateTo?: string;
}

export async function runReport(key: string, params: ReportParams = {}): Promise<ReportResult> {
  const out = await httpGet<ReportResultOut>(`/reports/${key}`, {
    date_from: params.dateFrom,
    date_to: params.dateTo,
    godown_id: params.godownId,
    category_id: params.categoryId,
    supplier_id: params.supplierId,
    status: params.status,
  });

  const numericColumns = new Set(
    out.columns.filter((c) => c.format === "currency" || c.format === "number").map((c) => c.key),
  );

  return {
    key: out.key,
    title: out.title,
    generatedAt: out.generated_at,
    columns: out.columns.map((c) => ({
      key: c.key,
      label: c.label,
      align: (c.align as "left" | "right" | undefined) ?? undefined,
      format: (c.format as "currency" | "number" | "date" | undefined) ?? undefined,
    })),
    // Postgres hands NUMERIC back as a *string* over the wire to keep it
    // exact, so a money column arrives as "1234.50" and `formatCurrency`
    // would receive a string. Coercion is driven by the column spec rather
    // than by "does this look like a number": blanket coercion turns an HSN
    // code of "0801" into 801 and a SKU of "1000" into a number.
    rows: out.rows.map((row) => {
      const mapped: Record<string, string | number> = {};
      for (const [k, v] of Object.entries(row)) {
        if (v === null) {
          mapped[k] = "";
        } else if (numericColumns.has(k) && typeof v === "string") {
          mapped[k] = Number(v);
        } else {
          mapped[k] = v;
        }
      }
      return mapped;
    }),
    totals: out.totals ?? undefined,
  };
}
