"use client";

/** Feature hooks for alerts, the audit trail, the dashboard and reports. */

import { useCallback } from "react";
import { documentsApi, inventoryApi, opsApi, procurementApi } from "@/lib/api";
import type { Id, ListParams } from "@/types";
import { useApiMutation, useApiQuery } from "./use-api";
import { usePermissions } from "./use-session";

export function useDashboard(godownId?: Id) {
  return useApiQuery(["dashboard", godownId], () => opsApi.getDashboardSummary(godownId));
}

export function useAlerts(params: ListParams) {
  return useApiQuery(["alerts", params], () => opsApi.listAlerts(params));
}

/** `enabled` is false for a platform admin, whose token carries no tenant —
 * `/alerts/summary` would 403 on every screen they open. */
export function useAlertSummary(enabled = true) {
  return useApiQuery(["alert-summary"], () => opsApi.getAlertSummary(), { enabled });
}

export function useAlertRules() {
  return useApiQuery(["alert-rules"], () => opsApi.listAlertRules());
}

export function useSetAlertStatus(onSuccess?: () => void) {
  const action = useCallback(
    (input: { alertId: Id; status: Parameters<typeof opsApi.setAlertStatus>[1] }) =>
      opsApi.setAlertStatus(input.alertId, input.status),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

/**
 * Ask the server to re-run the alert rules.
 *
 * Phase 1 has no scheduler, so the feed is only as fresh as the last
 * evaluation. Without this the Alerts screen shows whatever happened to be
 * generated last — which is how a screen ends up quietly stale.
 */
export function useEvaluateAlerts(onSuccess?: () => void) {
  const action = useCallback((ruleCode?: string) => opsApi.evaluateAlerts(ruleCode), []);
  return useApiMutation(action, { onSuccess });
}

export function useMarkAlertRead() {
  return useApiMutation(opsApi.markAlertRead);
}

export function useMarkAllAlertsRead(onSuccess?: () => void) {
  const action = useCallback(() => opsApi.markAllAlertsRead(), []);
  return useApiMutation(action, { onSuccess });
}

export function useAuditLogs(params: ListParams) {
  return useApiQuery(["audit-logs", params], () => opsApi.listAuditLogs(params));
}

/** The trail shown on a record's detail screen. */
export function useAuditTrail(entityType: string | undefined, entityId: Id | undefined) {
  return useApiQuery(
    ["audit-trail", entityType, entityId],
    () => opsApi.getAuditTrail(entityType!, entityId!),
    { enabled: !!entityType && !!entityId },
  );
}

export function useReports() {
  return useApiQuery(["reports"], () => opsApi.listReports());
}

export function useReport(key: string | undefined, params: opsApi.ReportParams) {
  return useApiQuery(
    ["report", key, params],
    () => opsApi.runReport(key!, params),
    { enabled: !!key },
  );
}

/**
 * Live counts for the sidebar badges.
 *
 * These used to be constants in `nav-config.ts` ("23 low stock") that never
 * changed and never matched the screen behind them (I13). They are now derived
 * from the same queries the screens use.
 *
 * Each count is asked for only when the role may read it: one 403 used to
 * fail the whole Promise.all, so a Godown Manager or Staff user lost every
 * badge (and logged 403s on every page).
 */
export function useNavBadges(enabled = true) {
  const { can } = usePermissions();
  const allowed = {
    quotations: can("quotation.view"),
    orders: can("po.view"),
    lowStock: can("inventory.view"),
    documents: can("document.view"),
    alerts: can("alert.view"),
    variances: can("proforma.view"),
  };
  const none = { items: [], total: 0 };
  return useApiQuery(["nav-badges", allowed], async () => {
    const [quotations, orders, lowStock, documents, alerts, variances] = await Promise.all([
      allowed.quotations ? procurementApi.listQuotations({ filters: { status: "under_review" }, limit: 1 }) : none,
      allowed.orders ? procurementApi.listPurchaseOrders({ limit: Number.MAX_SAFE_INTEGER }) : none,
      allowed.lowStock ? inventoryApi.listLowStock({ limit: 1 }) : none,
      allowed.documents
        ? documentsApi.listDocuments({ filters: { processingStatus: "review_required" }, limit: 1 })
        : none,
      allowed.alerts ? opsApi.getAlertSummary() : { unread: 0 },
      allowed.variances ? procurementApi.listVariances({ filters: { status: "open" }, limit: 1 }) : none,
    ]);
    return {
      quotationsToReview: quotations.total,
      openPurchaseOrders: orders.items.filter(
        (po) => !["draft", "closed", "cancelled"].includes(po.status) && po.receivedPct < 100,
      ).length,
      lowStock: lowStock.total,
      documentsToReview: documents.total,
      unreadAlerts: alerts.unread,
      openVariances: variances.total,
    };
  }, { enabled });
}
