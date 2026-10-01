"use client";

import * as React from "react";
import {
  ArrowLeft,
  ArrowRight,
  BarChart3,
  Boxes,
  Building2,
  CalendarClock,
  Download,
  FileText,
  Package,
  ReceiptText,
  TrendingUp,
  Truck,
  type LucideIcon,
} from "lucide-react";

import { AsyncBoundary, LoadingRows } from "@/components/common/async-state";
import { FilterSelect } from "@/components/common/filter-select";
import { PageHeader } from "@/components/common/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useCategories, useGodowns } from "@/hooks/use-catalog";
import { useReport, useReports } from "@/hooks/use-ops";
import { useSuppliers } from "@/hooks/use-suppliers";
import { formatCurrency, formatDate, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ReportResult } from "@/types";

/**
 * Reports.
 *
 * The catalogue and every result come from the reporting service, so a report
 * and the screen it summarises always read the same rows. Each definition
 * declares which filters it accepts, and only those are offered — a filter
 * that does nothing is worse than no filter.
 */

const ICONS: Record<string, LucideIcon> = {
  stock_summary: Boxes,
  stock_ledger: FileText,
  low_stock: TrendingUp,
  inventory_valuation: BarChart3,
  batch_expiry: CalendarClock,
  purchase_register: ReceiptText,
  po_status: FileText,
  pending_receipts: Truck,
  supplier_performance: Building2,
  price_variance: TrendingUp,
  gst_purchase: ReceiptText,
  product_master: Package,
  supplier_master: Building2,
};

/** yyyy-mm-dd in the browser's own calendar, not UTC: before 05:30 IST
 * `toISOString()` still says yesterday. */
function isoDay(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function lastDays(days: number) {
  const to = new Date();
  const from = new Date(to);
  from.setDate(to.getDate() - (days - 1));
  return { dateFrom: isoDay(from), dateTo: isoDay(to) };
}

const DATE_RANGES: Record<string, () => { dateFrom?: string; dateTo?: string }> = {
  "Today": () => lastDays(1),
  "Last 7 days": () => lastDays(7),
  "Last 30 days": () => lastDays(30),
  "This month": () => {
    const now = new Date();
    return { dateFrom: isoDay(new Date(now.getFullYear(), now.getMonth(), 1)), dateTo: isoDay(now) };
  },
  // Calendar quarters line up with the Indian financial year's (Apr–Jun is Q1).
  "This quarter": () => {
    const now = new Date();
    const start = new Date(now.getFullYear(), Math.floor(now.getMonth() / 3) * 3, 1);
    return { dateFrom: isoDay(start), dateTo: isoDay(now) };
  },
  "This financial year": () => {
    const now = new Date();
    const year = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
    return { dateFrom: isoDay(new Date(year, 3, 1)), dateTo: isoDay(now) };
  },
};

type Column = ReportResult["columns"][number];

/** Long free-text columns are truncated so the numbers stay on screen. */
const LONG_TEXT = new Set(["product", "supplier", "godown", "category"]);
/** Status-like codes ("partially_received", "SALES_ISSUE") read as words. */
const CODED = new Set(["status", "txn_type"]);

function humanize(code: string) {
  const words = code.replace(/_/g, " ").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function display(column: Column, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (column.format === "currency") return formatCurrency(Number(value) || 0);
  if (column.format === "date") return formatDate(String(value));
  if (column.format === "number") {
    const n = formatNumber(Number(value) || 0);
    return column.key.endsWith("_pct") ? `${n}%` : n;
  }
  if (CODED.has(column.key)) return humanize(String(value));
  return String(value);
}

/** CSV of exactly what is on screen (filters applied), totals last. */
function downloadCsv(report: ReportResult, name: string) {
  const cell = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [report.columns.map((c) => cell(c.label)).join(",")];
  for (const row of report.rows) {
    lines.push(report.columns.map((c) => cell(CODED.has(c.key) && row[c.key] ? humanize(String(row[c.key])) : row[c.key])).join(","));
  }
  if (report.totals) {
    lines.push(report.columns.map((c, i) => cell(i === 0 ? "Total" : report.totals?.[c.key])).join(","));
  }
  const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-${isoDay(new Date())}.csv`;
  // Firefox ignores clicks on a detached anchor, and revoking the URL in the
  // same tick can cancel the download before the browser has read the blob.
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function ReportsPage() {
  const definitions = useReports();
  const godowns = useGodowns();
  const categories = useCategories();
  const suppliers = useSuppliers({ limit: 200, sort: "name" });

  const [selected, setSelected] = React.useState<string | undefined>(undefined);
  const [range, setRange] = React.useState<string | undefined>(undefined);
  const [godownName, setGodownName] = React.useState<string | undefined>(undefined);
  const [categoryName, setCategoryName] = React.useState<string | undefined>(undefined);
  const [supplierName, setSupplierName] = React.useState<string | undefined>(undefined);

  const definition = definitions.data?.find((d) => d.key === selected);

  /**
   * Opening a different report clears the filter bar.
   *
   * Filters are per-report — each definition declares which it accepts — so
   * a godown left over from Stock Summary would silently narrow Pending
   * Receipts while the bar that set it is no longer on screen.
   */
  const openReport = React.useCallback((key: string | undefined) => {
    setSelected(key);
    setRange(undefined);
    setGodownName(undefined);
    setCategoryName(undefined);
    setSupplierName(undefined);
  }, []);

  const params = React.useMemo(() => {
    const dates = range ? DATE_RANGES[range]?.() ?? {} : {};
    return {
      ...dates,
      godownId: godowns.data?.find((g) => g.name === godownName)?.id,
      categoryId: categories.data?.find((c) => c.name === categoryName)?.id,
      supplierId: suppliers.data?.items.find((s) => s.name === supplierName)?.id,
    };
  }, [range, godownName, categoryName, supplierName, godowns.data, categories.data, suppliers.data]);

  const result = useReport(selected, params);

  const accepts = (param: string) => definition?.params.includes(param as never) ?? false;

  const definitionList = definitions.data;
  const groups = React.useMemo(() => {
    const byGroup = new Map<string, NonNullable<typeof definitionList>>();
    for (const definition of definitionList ?? []) {
      const list = byGroup.get(definition.group) ?? [];
      list.push(definition);
      byGroup.set(definition.group, list);
    }
    return [...byGroup.entries()];
  }, [definitionList]);

  if (definition) {
    return (
      <div className="space-y-4">
        <Card className="overflow-hidden">
          <div className="flex flex-col gap-2.5 border-b border-border px-3 py-2.5 lg:flex-row lg:items-center">
            <div className="flex min-w-0 items-center gap-2">
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => openReport(undefined)}
                aria-label="Back to all reports"
                title="Back to all reports"
              >
                <ArrowLeft />
              </Button>
              <div className="min-w-0">
                <h1 className="text-section text-foreground">{definition.name}</h1>
                <p className="truncate text-caption text-muted-foreground">{definition.description}</p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2 lg:ml-auto">
              {accepts("dateRange") && (
                <FilterSelect
                  placeholder="All dates"
                  options={Object.keys(DATE_RANGES)}
                  className="w-[170px]"
                  value={range}
                  onValueChange={setRange}
                />
              )}
              {accepts("godown") && (
                <FilterSelect
                  placeholder="All Godowns"
                  options={(godowns.data ?? []).map((g) => g.name)}
                  value={godownName}
                  onValueChange={setGodownName}
                />
              )}
              {/* Several reports declare a `category` filter. Until now the bar
                  offered none, so that parameter was unreachable from the UI. */}
              {accepts("category") && (
                <FilterSelect
                  placeholder="All Categories"
                  options={(categories.data ?? []).map((c) => c.name)}
                  className="w-[170px]"
                  value={categoryName}
                  onValueChange={setCategoryName}
                />
              )}
              {accepts("supplier") && (
                <FilterSelect
                  placeholder="All Suppliers"
                  options={(suppliers.data?.items ?? []).map((s) => s.name)}
                  className="w-[190px]"
                  value={supplierName}
                  onValueChange={setSupplierName}
                />
              )}
              <Button
                variant="outline"
                size="sm"
                disabled={!result.data || result.data.rows.length === 0}
                onClick={() => result.data && downloadCsv(result.data, definition.name)}
              >
                <Download />
                Export CSV
              </Button>
            </div>
          </div>

          <AsyncBoundary state={result} loading={<LoadingRows rows={8} columns={5} />}>
            {(report) => (
              // The card scrolls, not the page: the header row stays in view
              // and wide reports keep their right-hand figures reachable.
              <div
                className={cn(
                  "max-h-[calc(100dvh-13rem)] overflow-auto",
                  "[&_[data-slot=table-container]]:overflow-visible",
                )}
              >
                <Table className="text-[13px]">
                  <TableHeader className="sticky top-0 z-10 bg-card shadow-[inset_0_-1px_0_var(--border)]">
                    <TableRow className="hover:bg-transparent">
                      {report.columns.map((column, i) => (
                        <TableHead
                          key={column.key}
                          className={cn("h-8", i === 0 && "pl-4", column.align === "right" && "text-right")}
                        >
                          {column.label}
                        </TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {report.rows.map((row, rowIndex) => (
                      <TableRow key={rowIndex}>
                        {report.columns.map((column, i) => {
                          const text = display(column, row[column.key]);
                          return (
                            <TableCell
                              key={column.key}
                              title={LONG_TEXT.has(column.key) ? text : undefined}
                              className={cn(
                                "py-1.5",
                                i === 0 && "pl-4 font-medium text-foreground",
                                i > 0 && "text-muted-foreground",
                                column.align === "right" && "text-right tabular",
                                LONG_TEXT.has(column.key) && "max-w-[240px] truncate",
                              )}
                            >
                              {text}
                            </TableCell>
                          );
                        })}
                      </TableRow>
                    ))}

                    {report.totals && (
                      <TableRow className="sticky bottom-0 bg-muted hover:bg-muted">
                        {report.columns.map((column, i) => (
                          <TableCell
                            key={column.key}
                            className={cn(
                              "py-1.5",
                              i === 0 && "pl-4 font-medium text-foreground",
                              column.align === "right" && "text-right font-semibold tabular",
                            )}
                          >
                            {i === 0
                              ? "Total"
                              : report.totals?.[column.key] !== undefined
                                ? column.format === "currency"
                                  ? formatCurrency(report.totals[column.key])
                                  : formatNumber(report.totals[column.key])
                                : ""}
                          </TableCell>
                        ))}
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
                {report.rows.length === 0 && (
                  <p className="px-4 py-8 text-center text-[13px] text-muted-foreground">
                    Nothing matches these filters.
                  </p>
                )}
              </div>
            )}
          </AsyncBoundary>

          {result.data && (
            <div className="border-t border-border px-4 py-2 text-caption text-muted-foreground">
              {result.data.rows.length} row{result.data.rows.length === 1 ? "" : "s"} · generated{" "}
              {formatDate(result.data.generatedAt)}
            </div>
          )}
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Reports"
        description="Pull any view of your stock and procurement, then export it"
      />

      <AsyncBoundary state={definitions}>
        {() => (
          <Card className="divide-y divide-border">
            {groups.map(([group, reports]) => (
              <section key={group} className="px-2 py-2.5">
                <h2 className="px-2 pb-1 text-[11px] font-medium tracking-[0.06em] text-muted-foreground uppercase">
                  {group}
                </h2>
                <ul className="grid grid-cols-1 gap-0.5 sm:grid-cols-2 lg:grid-cols-3">
                  {(reports ?? []).map((report) => {
                    const Icon = ICONS[report.key] ?? FileText;
                    return (
                      <li key={report.key}>
                        <button
                          type="button"
                          onClick={() => openReport(report.key)}
                          className="group flex w-full items-start gap-2.5 rounded-lg px-2 py-2 text-left transition-colors hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none"
                        >
                          <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground transition-colors group-hover:bg-primary-subtle group-hover:text-primary-subtle-foreground">
                            <Icon className="size-3.5" strokeWidth={1.9} />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center gap-1.5 text-[13px] font-medium text-foreground">
                              {report.name}
                              <ArrowRight className="size-3.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                            </span>
                            <span className="block text-caption text-muted-foreground">{report.description}</span>
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))}
          </Card>
        )}
      </AsyncBoundary>
    </div>
  );
}
