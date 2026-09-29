"use client";

import * as React from "react";
import {
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
import { SectionCard } from "@/components/common/section-card";
import { Button } from "@/components/ui/button";
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

const DATE_RANGES: Record<string, () => { dateFrom?: string; dateTo?: string }> = {
  "Today": () => {
    const today = new Date().toISOString().slice(0, 10);
    return { dateFrom: today, dateTo: today };
  },
  "Last 7 days": () => shift(7),
  "Last 30 days": () => shift(30),
  "This quarter": () => shift(90),
  "This year": () => shift(365),
};

function shift(days: number) {
  const to = new Date();
  const from = new Date(to.getTime() - days * 24 * 60 * 60 * 1000);
  return { dateFrom: from.toISOString().slice(0, 10), dateTo: to.toISOString().slice(0, 10) };
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

  const groups = React.useMemo(() => {
    const byGroup = new Map<string, typeof definitions.data>();
    for (const definition of definitions.data ?? []) {
      const list = byGroup.get(definition.group) ?? [];
      list.push(definition);
      byGroup.set(definition.group, list as never);
    }
    return [...byGroup.entries()];
  }, [definitions.data]);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Reports"
        description="Pull any view of your stock and procurement, then export it"
      />

      {definition && (
        <div className="flex flex-col gap-2.5 rounded-xl border border-border bg-card px-4 py-3 lg:flex-row lg:items-center">
          <p className="text-[13px] font-medium text-foreground">{definition.name}</p>
          <div className="flex flex-wrap items-center gap-2 lg:ml-auto">
            {accepts("dateRange") && (
              <FilterSelect
                placeholder="All dates"
                options={Object.keys(DATE_RANGES)}
                className="w-[152px]"
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
            <Button variant="outline" size="sm" onClick={() => openReport(undefined)}>
              Back to all reports
            </Button>
          </div>
        </div>
      )}

      {definition ? (
        <SectionCard
          title={definition.name}
          description={definition.description}
          action={
            <Button variant="outline" size="sm" disabled title="Export is a backend capability">
              <Download />
              Export
            </Button>
          }
          footer={
            result.data ? (
              <span>
                {result.data.rows.length} row{result.data.rows.length === 1 ? "" : "s"} · generated{" "}
                {formatDate(result.data.generatedAt)}
              </span>
            ) : undefined
          }
        >
          <AsyncBoundary state={result} loading={<LoadingRows rows={6} columns={5} />}>
            {(report) => (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      {report.columns.map((column, i) => (
                        <TableHead
                          key={column.key}
                          className={cn(i === 0 && "pl-4", column.align === "right" && "text-right")}
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
                          const value = row[column.key];
                          const display =
                            column.format === "currency"
                              ? formatCurrency(Number(value) || 0)
                              : column.format === "number"
                                ? formatNumber(Number(value) || 0)
                                : column.format === "date" && value
                                  ? formatDate(String(value))
                                  : String(value ?? "—");
                          return (
                            <TableCell
                              key={column.key}
                              className={cn(
                                i === 0 && "pl-4 font-medium text-foreground",
                                i > 0 && "text-muted-foreground",
                                column.align === "right" && "text-right tabular",
                              )}
                            >
                              {display}
                            </TableCell>
                          );
                        })}
                      </TableRow>
                    ))}

                    {report.totals && (
                      <TableRow className="bg-muted/45 hover:bg-muted/45">
                        {report.columns.map((column, i) => (
                          <TableCell
                            key={column.key}
                            className={cn(
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
              </div>
            )}
          </AsyncBoundary>
        </SectionCard>
      ) : (
        <AsyncBoundary state={definitions}>
          {() =>
            groups.map(([group, reports]) => (
              <SectionCard key={group} title={group} className="mb-4">
                <ul className="grid grid-cols-1 divide-border sm:grid-cols-2 sm:divide-x lg:grid-cols-3">
                  {(reports ?? []).map((report) => {
                    const Icon = ICONS[report.key] ?? FileText;
                    return (
                      <li key={report.key} className="border-b border-border last:border-b-0">
                        <button
                          type="button"
                          onClick={() => openReport(report.key)}
                          className="group flex h-full w-full items-start gap-3 p-4 text-left transition-colors hover:bg-muted/45"
                        >
                          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground transition-colors group-hover:bg-primary-subtle group-hover:text-primary-subtle-foreground">
                            <Icon className="size-4" strokeWidth={1.9} />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center gap-1.5 text-[13.5px] font-medium text-foreground">
                              {report.name}
                              <ArrowRight className="size-3.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                            </span>
                            <span className="mt-0.5 block text-caption text-muted-foreground">
                              {report.description}
                            </span>
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </SectionCard>
            ))
          }
        </AsyncBoundary>
      )}
    </div>
  );
}
