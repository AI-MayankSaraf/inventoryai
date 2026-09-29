"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertTriangle, PackageX, Send, Users, X } from "lucide-react";

import { AsyncBoundary } from "@/components/common/async-state";
import { KpiCard } from "@/components/common/kpi-card";
import { DataToolbar } from "@/components/common/data-toolbar";
import { FilterSelect } from "@/components/common/filter-select";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useGodowns } from "@/hooks/use-catalog";
import { useListControls } from "@/hooks/use-api";
import { useLowStock } from "@/hooks/use-inventory";
import { formatCurrency, formatNumber } from "@/lib/format";
import { handoff, HANDOFF_KEYS } from "@/lib/handoff";
import { cn } from "@/lib/utils";
import type { LowStockRow } from "@/types";

const STATUS_OPTIONS: { value: LowStockRow["status"]; label: string }[] = [
  { value: "low_stock", label: "Low Stock" },
  { value: "out_of_stock", label: "Out of Stock" },
];

export function LowStockScreen() {
  const router = useRouter();
  const [selected, setSelected] = React.useState<Set<string>>(new Set());

  // A generous limit so the KPI tiles and "select all" reflect the whole
  // filtered result, not just the first page of it.
  const controls = useListControls({ sort: "currentStock", limit: 200 });
  const godownsState = useGodowns();
  const godowns = godownsState.data ?? [];
  const state = useLowStock(controls.params);

  const items = React.useMemo(() => state.data?.items ?? [], [state.data]);
  const outOfStock = items.filter((i) => i.status === "out_of_stock").length;
  const supplierCount = new Set(items.map((i) => i.preferredSupplierName).filter(Boolean)).size;
  const selectedItems = items.filter((i) => selected.has(i.id));
  const selectedSupplierCount = new Set(selectedItems.map((i) => i.preferredSupplierName)).size;

  const supplierOptions = React.useMemo(
    () => [...new Set(items.map((i) => i.preferredSupplierName).filter(Boolean))],
    [items],
  );

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected((prev) => (prev.size === items.length ? new Set() : new Set(items.map((i) => i.id))));
  }

  /**
   * An RFQ can go to several suppliers at once for the same items — it's not
   * split per supplier like a PO. So we hand off every selected item plus the
   * union of their usual suppliers as suggested recipients.
   */
  function createRfq(ids: string[]) {
    const picked = items.filter((i) => ids.includes(i.id));
    if (picked.length === 0) return;
    handoff.write(HANDOFF_KEYS.rfqDraft, {
      items: picked.map((i) => ({
        description: i.productName,
        matchedSku: i.sku,
        qty: i.suggestedQty,
        unit: i.uomCode,
        expectedPrice: i.lastPurchasePrice,
      })),
      suppliers: [...new Set(picked.map((i) => i.preferredSupplierName).filter(Boolean))],
    });
    router.push("/procurement/rfq/new");
  }

  return (
    <div className="space-y-5 pb-14">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <KpiCard
          label="Below Reorder Point"
          value={formatNumber(state.data?.total ?? items.length)}
          icon={AlertTriangle}
          tone="warning"
          hint="Matching your current filters"
        />
        <KpiCard
          label="Out of Stock"
          value={formatNumber(outOfStock)}
          icon={PackageX}
          tone="destructive"
          hint="Zero units available"
        />
        <KpiCard
          label="Suppliers to Contact"
          value={formatNumber(supplierCount)}
          icon={Users}
          hint="Preferred suppliers across these items"
        />
      </div>

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
                placeholder="All Status"
                options={STATUS_OPTIONS.map((o) => o.label)}
                value={STATUS_OPTIONS.find((o) => o.value === controls.filters.status)?.label}
                onValueChange={(label) =>
                  controls.setFilter("status", STATUS_OPTIONS.find((o) => o.label === label)?.value)
                }
              />
              <FilterSelect
                placeholder="All Suppliers"
                options={supplierOptions}
                className="w-[190px]"
                value={controls.filters.preferredSupplierName}
                onValueChange={(v) => controls.setFilter("preferredSupplierName", v)}
              />
            </>
          }
          trailing={
            <Button onClick={() => createRfq(items.map((i) => i.id))} disabled={items.length === 0}>
              <Send />
              Create RFQ for All
            </Button>
          }
        />

        <AsyncBoundary
          state={state}
          isEmpty={(d) => d.items.length === 0}
          empty={{ icon: AlertTriangle, title: "No low stock items match your search." }}
        >
          {() => (
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-10 pl-4">
                    <Checkbox
                      checked={items.length > 0 && selected.size === items.length}
                      onCheckedChange={toggleAll}
                      aria-label="Select all low stock items"
                    />
                  </TableHead>
                  <TableHead>Product</TableHead>
                  <TableHead>SKU</TableHead>
                  <TableHead>Godown</TableHead>
                  <TableHead className="text-right">Current</TableHead>
                  <TableHead className="text-right">Reorder At</TableHead>
                  <TableHead className="text-right">Suggested Qty</TableHead>
                  <TableHead>Preferred Supplier</TableHead>
                  <TableHead className="text-right">Last Purchase Price</TableHead>
                  <TableHead className="pr-4 text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((item) => (
                  <TableRow key={item.id} className={cn(selected.has(item.id) && "bg-primary-subtle/30")}>
                    <TableCell className="pl-4">
                      <Checkbox
                        checked={selected.has(item.id)}
                        onCheckedChange={() => toggle(item.id)}
                        aria-label={`Select ${item.productName}`}
                      />
                    </TableCell>
                    <TableCell className="max-w-[200px]">
                      <Link
                        href={`/products/${item.productVariantId}`}
                        className="block truncate font-medium text-foreground hover:text-primary"
                      >
                        {item.productName}
                      </Link>
                      <StatusBadge status={item.status} className="mt-1" />
                    </TableCell>
                    <TableCell className="font-mono text-[12.5px] text-muted-foreground">
                      {item.sku}
                    </TableCell>
                    <TableCell className="text-muted-foreground">{item.godownName}</TableCell>
                    <TableCell
                      className={cn(
                        "text-right font-semibold tabular",
                        item.status === "out_of_stock" ? "text-destructive" : "text-warning-subtle-foreground",
                      )}
                    >
                      {formatNumber(item.currentStock)}
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground tabular">
                      {formatNumber(item.reorderPoint)}
                    </TableCell>
                    <TableCell className="text-right font-semibold text-primary tabular">
                      {formatNumber(item.suggestedQty)}{" "}
                      <span className="text-[11.5px] font-normal text-muted-foreground">
                        {item.uomCode}
                      </span>
                    </TableCell>
                    <TableCell className="max-w-[170px] truncate text-foreground">
                      {item.preferredSupplierName || "—"}
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground tabular">
                      {formatCurrency(item.lastPurchasePrice)}
                    </TableCell>
                    <TableCell className="pr-4 text-right">
                      <Button variant="outline" size="sm" onClick={() => createRfq([item.id])}>
                        Create RFQ
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </AsyncBoundary>
      </Card>

      {selected.size > 0 && (
        <div className="fixed bottom-5 left-1/2 z-20 flex -translate-x-1/2 items-center gap-3 rounded-xl border border-border bg-card/95 px-4 py-2.5 shadow-float backdrop-blur">
          <p className="text-[13px] text-foreground">
            <span className="font-medium tabular">{selected.size}</span> item
            {selected.size === 1 ? "" : "s"} selected
            {selectedSupplierCount > 1 && (
              <span className="text-muted-foreground"> · {selectedSupplierCount} suppliers</span>
            )}
          </p>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Clear selection"
            onClick={() => setSelected(new Set())}
          >
            <X />
          </Button>
          <Button size="sm" onClick={() => createRfq([...selected])}>
            <Send />
            Create RFQ ({selected.size})
          </Button>
        </div>
      )}
    </div>
  );
}
