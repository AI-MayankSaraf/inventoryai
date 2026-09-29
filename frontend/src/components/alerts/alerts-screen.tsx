"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, BellOff, CheckCheck, RefreshCw } from "lucide-react";

import { AsyncBoundary } from "@/components/common/async-state";
import { FilterSelect } from "@/components/common/filter-select";
import { PageHeader } from "@/components/common/page-header";
import { PermissionGate } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useListControls } from "@/hooks/use-api";
import {
  useAlertSummary,
  useAlerts,
  useEvaluateAlerts,
  useMarkAlertRead,
  useMarkAllAlertsRead,
  useSetAlertStatus,
} from "@/hooks/use-ops";
import { formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { AlertSeverity } from "@/types";

/**
 * Alerts are rule outputs, not screen decorations.
 *
 * Each row names the server-side rule that produced it and links to the record
 * it is about, so every count on this page is openable and every alert can be
 * traced back to why it fired (I13, BR-ALT-01).
 */

const SEVERITY: Record<
  AlertSeverity,
  { label: string; dot: string; badge: React.ComponentProps<typeof Badge>["variant"]; row: string }
> = {
  critical: { label: "Critical", dot: "bg-destructive", badge: "destructive", row: "border-l-destructive" },
  high: { label: "High", dot: "bg-warning", badge: "warning", row: "border-l-warning" },
  medium: { label: "Medium", dot: "bg-info", badge: "info", row: "border-l-info" },
  low: { label: "Low", dot: "bg-muted-foreground", badge: "neutral", row: "border-l-border" },
};

const SEVERITY_VALUES: Record<string, AlertSeverity> = {
  Critical: "critical",
  High: "high",
  Medium: "medium",
  Low: "low",
};

const STATUS_VALUES: Record<string, string> = {
  New: "new",
  Acknowledged: "acknowledged",
  Resolved: "resolved",
  Dismissed: "dismissed",
};

export function AlertsScreen() {
  const controls = useListControls({ sort: "-lastOccurredAt" });
  const state = useAlerts(controls.params);
  const summary = useAlertSummary();

  // Every mutation here changes both the feed and the counts above it, and
  // neither refreshes on its own now that these are real HTTP calls rather
  // than mock writes the query layer was subscribed to. Refetching both is
  // what keeps "3 unread" and the rows underneath it telling the same story.
  const refreshAll = React.useCallback(() => {
    state.refresh();
    summary.refresh();
  }, [state.refresh, summary.refresh]);

  const markRead = useMarkAlertRead();
  const markAllRead = useMarkAllAlertsRead(refreshAll);
  const setStatus = useSetAlertStatus(refreshAll);
  const evaluate = useEvaluateAlerts(refreshAll);

  const unread = summary.data?.unread ?? 0;
  const total = summary.data?.total ?? 0;

  const labelFor = (map: Record<string, string>, value?: string) =>
    Object.keys(map).find((key) => map[key] === value);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Alerts"
        description={`${unread} unread · ${total} open`}
        actions={
          <div className="flex flex-wrap gap-2">
            {/* Phase 1 has no scheduler, so the feed is exactly as fresh as
                the last evaluation. Without a way to ask, this screen would
                quietly show yesterday's world. */}
            <Button
              variant="outline"
              disabled={evaluate.isPending}
              onClick={() => evaluate.run(undefined)}
            >
              <RefreshCw className={cn(evaluate.isPending && "animate-spin")} />
              Check now
            </Button>
            {/* Not behind `alert.manage`: read state is per user (BR-ALT-03),
                so marking *your own* feed read is not an administrative act.
                The endpoint itself sits behind `alert.view` for the same
                reason, and gating the button harder than the API only hides
                a capability the user actually has. */}
            <Button
              variant="outline"
              disabled={unread === 0 || markAllRead.isPending}
              onClick={() => markAllRead.run(undefined as never)}
            >
              <CheckCheck />
              Mark all as read
            </Button>
          </div>
        }
      />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {(["critical", "high", "medium", "low"] as AlertSeverity[]).map((severity) => {
          const meta = SEVERITY[severity];
          return (
            <Card key={severity} className="p-4">
              <p className="flex items-center gap-2 text-label text-muted-foreground">
                <span className={cn("size-2 rounded-full", meta.dot)} />
                {meta.label}
              </p>
              <p className="mt-2 text-[26px] leading-none font-semibold tracking-[-0.02em] text-foreground tabular">
                {summary.data?.bySeverity[severity] ?? 0}
              </p>
            </Card>
          );
        })}
      </div>

      <SectionCard
        title="All Alerts"
        description="Raised by named rules that run server-side — not by whatever this screen is showing"
        action={
          <div className="flex flex-wrap gap-2">
            <FilterSelect
              placeholder="All Severity"
              options={["Critical", "High", "Medium", "Low"]}
              className="w-[142px]"
              value={labelFor(SEVERITY_VALUES, controls.filters.severity)}
              onValueChange={(v) => controls.setFilter("severity", v ? SEVERITY_VALUES[v] : undefined)}
            />
            <FilterSelect
              placeholder="All Categories"
              options={["Inventory", "Procurement", "Goods Receipt", "AI Documents", "System"]}
              className="w-[168px]"
              value={controls.filters.category}
              onValueChange={(v) => controls.setFilter("category", v)}
            />
            <FilterSelect
              placeholder="All Statuses"
              options={["New", "Acknowledged", "Resolved", "Dismissed"]}
              className="w-[150px]"
              value={labelFor(STATUS_VALUES, controls.filters.status)}
              onValueChange={(v) => controls.setFilter("status", v ? STATUS_VALUES[v] : undefined)}
            />
          </div>
        }
      >
        <AsyncBoundary
          state={state}
          isEmpty={(data) => data.items.length === 0}
          empty={{
            icon: BellOff,
            title: controls.activeFilterCount
              ? "No alerts match your filters"
              : "Nothing needs your attention",
            description:
              "Alerts about stock, deliveries and document mismatches will show up here.",
          }}
        >
          {(data) => (
            <ul className="divide-y divide-border">
              {data.items.map((alert) => {
                const meta = SEVERITY[alert.severity];
                return (
                  <li
                    key={alert.id}
                    className={cn(
                      "border-l-2 px-4 py-3.5 transition-colors hover:bg-muted/40",
                      meta.row,
                      !alert.isRead && "bg-muted/25",
                    )}
                  >
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant={meta.badge}>{meta.label}</Badge>
                          <p className="text-[14px] font-medium text-foreground">{alert.title}</p>
                          {!alert.isRead && (
                            <span className="size-1.5 rounded-full bg-primary" aria-label="Unread" />
                          )}
                          {alert.occurrenceCount > 1 && (
                            <Badge variant="outline">×{alert.occurrenceCount}</Badge>
                          )}
                        </div>
                        <p className="mt-1 text-[13px] text-muted-foreground">{alert.description}</p>
                        <p className="mt-1.5 flex flex-wrap items-center gap-2 text-caption text-muted-foreground">
                          <span>{formatRelativeTime(alert.lastOccurredAt)}</span>
                          <span className="text-border">·</span>
                          <span>{alert.category}</span>
                          {alert.referenceLabel && (
                            <>
                              <span className="text-border">·</span>
                              <span className="font-mono">{alert.referenceLabel}</span>
                            </>
                          )}
                          <span className="text-border">·</span>
                          {/* The rule that fired, so the alert is explicable. */}
                          <span title={`Rule: ${alert.ruleCode}`}>{alert.ruleLabel}</span>
                        </p>
                      </div>

                      <div className="flex shrink-0 items-center gap-2">
                        <PermissionGate permission="alert.manage">
                          {alert.status === "new" ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={setStatus.isPending}
                              onClick={() =>
                                setStatus.run({ alertId: alert.id, status: "acknowledged" })
                              }
                            >
                              Acknowledge
                            </Button>
                          ) : alert.status === "acknowledged" ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={setStatus.isPending}
                              onClick={() => setStatus.run({ alertId: alert.id, status: "resolved" })}
                            >
                              Resolve
                            </Button>
                          ) : null}
                        </PermissionGate>

                        {alert.deepLink && (
                          <Button
                            variant="outline"
                            size="sm"
                            asChild
                            onClick={() => {
                              if (!alert.isRead) markRead.run(alert.id).then(refreshAll);
                            }}
                          >
                            <Link href={alert.deepLink}>
                              Open
                              <ArrowRight />
                            </Link>
                          </Button>
                        )}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </AsyncBoundary>
      </SectionCard>
    </div>
  );
}
