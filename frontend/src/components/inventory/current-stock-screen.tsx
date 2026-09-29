"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, Download, IndianRupee, Package, PackageX } from "lucide-react";

import { PageHeader } from "@/components/common/page-header";
import { KpiCard } from "@/components/common/kpi-card";
import { AsyncBoundary } from "@/components/common/async-state";
import { DataToolbar, TablePagination } from "@/components/common/data-toolbar";
import { FilterSelect } from "@/components/common/filter-select";
import { StatusBadge } from "@/components/common/status-badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
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
import { useListControls } from "@/hooks/use-api";
import { useInventoryKpis, useStock } from "@/hooks/use-inventory";
import { usePermissions } from "@/hooks/use-session";
import { formatCurrency, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { StockRow, StockState } from "@/types";

const STATUS_OPTIONS: { value: StockState; label: string }[] = [
  { value: "in_stock", label: "In Stock" },
  { value: "low_stock", label: "Low Stock" },
  { value: "out_of_stock", label: "Out of Stock" },
];

export function CurrentStockScreen() {
  const controls = useListControls({ sort: "productName" });
  const permissions = usePermissions();
  const godownsState = useGodowns();
  const categoriesState = useCategories();

  const godowns = React.useMemo(() => {
    const all = godownsState.data ?? [];
    const visible = new Set(permissions.visibleGodowns(all.map((g) => g.id)));
    return all.filter((g) => visible.has(g.id));
  }, [godownsState.data, permissions]);

  const categoryOptions = React.useMemo(
    () => (categoriesState.data ?? []).map((c) => c.name),
    [categoriesState.data],
  );

  const stockState = useStock(controls.params);
  const kpisState = useInventoryKpis(controls.filters.godownId);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Current Stock"
        description="Real-time inventory across all godowns"
        actions={
          <Button variant="outline">
            <Download />
            Export
          </Button>
        }
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard label="Total SKUs" value={formatNumber(kpisState.data?.totalSkus ?? 0)} icon={Package} />
        <KpiCard
          label="Inventory Value"
          value={formatCurrency(kpisState.data?.inventoryValue ?? 0)}
          icon={IndianRupee}
          tone="success"
          hint={`Across ${godowns.length} godown${godowns.length === 1 ? "" : "s"}`}
        />
        <KpiCard
          label="Low Stock"
          value={formatNumber(kpisState.data?.lowStock ?? 0)}
          icon={AlertTriangle}
          tone="warning"
          hint="Below reorder point"
        />
        <KpiCard
          label="Out of Stock"
          value={formatNumber(kpisState.data?.outOfStock ?? 0)}
          icon={PackageX}
          tone="destructive"
          hint="Needs immediate reorder"
        />
      </div>

      <Alert variant="info">
        <Package />
        <AlertDescription>
          Stock shown here is the sum of every inventory transaction. It cannot be typed over —
          corrections are recorded as a transaction so the history stays intact.
        </AlertDescription>
      </Alert>

      <Card className="overflow-hidden">
        <DataToolbar
          searchPlaceholder="Search product or SKU..."
          searchValue={controls.q}
          onSearchChange={controls.setQ}
          filters={
            <>
              <FilterSelect
                placeholder="All Godowns"
                options={godowns.map((g) => g.name)}
                value={godowns.find((g) => g.id === controls.filters.godownId)?.name}
                onValueChange={(name) =>
                  controls.setFilter("godownId", godowns.find((g) => g.name === name)?.id)
                }
              />
              <FilterSelect
                placeholder="All Categories"
                options={categoryOptions}
                value={controls.filters.categoryName}
                onValueChange={(v) => controls.setFilter("categoryName", v)}
              />
              <FilterSelect
                placeholder="All Status"
                options={STATUS_OPTIONS.map((o) => o.label)}
                value={STATUS_OPTIONS.find((o) => o.value === controls.filters.status)?.label}
                onValueChange={(label) =>
                  controls.setFilter("status", STATUS_OPTIONS.find((o) => o.label === label)?.value)
                }
              />
            </>
          }
        />

        <AsyncBoundary
          state={stockState}
          isEmpty={(d) => d.items.length === 0}
          empty={{ icon: Package, title: "No stock rows match your search." }}
        >
          {(data) => (
            <>
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="pl-4">Product</TableHead>
                    <TableHead>SKU</TableHead>
                    <TableHead>Brand</TableHead>
                    <TableHead>Godown</TableHead>
                    <TableHead className="text-right">Stock Qty</TableHead>
                    <TableHead className="text-right">Value</TableHead>
                    <TableHead className="pr-4">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((row: StockRow) => (
                    <TableRow key={row.id}>
                      <TableCell className="max-w-[210px] pl-4">
                        <Link
                          href={`/products/${row.productVariantId}`}
                          className="block truncate font-medium text-foreground hover:text-primary"
                        >
                          {row.productName}
                        </Link>
                        <span className="block text-caption text-muted-foreground">
                          {row.categoryName}
                        </span>
                      </TableCell>
                      <TableCell className="font-mono text-[12.5px] text-muted-foreground">
                        {row.sku}
                      </TableCell>
                      <TableCell className="text-foreground">{row.brandName}</TableCell>
                      <TableCell className="text-muted-foreground">{row.godownName}</TableCell>
                      <TableCell
                        className={cn(
                          "text-right font-semibold tabular",
                          row.status === "out_of_stock"
                            ? "text-destructive"
                            : row.status === "low_stock"
                              ? "text-warning-subtle-foreground"
                              : "text-foreground",
                        )}
                      >
                        {formatNumber(row.quantity)}{" "}
                        <span className="text-[11.5px] font-normal text-muted-foreground">
                          {row.uomCode}
                        </span>
                      </TableCell>
                      <TableCell className="text-right text-muted-foreground tabular">
                        {formatCurrency(row.value)}
                      </TableCell>
                      <TableCell className="pr-4">
                        <StatusBadge status={row.status} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              <TablePagination page={1} pageSize={Math.max(data.items.length, 1)} total={data.total} />
            </>
          )}
        </AsyncBoundary>
      </Card>
    </div>
  );
}
