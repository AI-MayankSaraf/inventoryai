"use client";

import * as React from "react";
import Link from "next/link";
import {
  ArrowDownLeft,
  ArrowUpRight,
  CalendarOff,
  Download,
  ExternalLink,
  Info,
  Loader2,
  PackageCheck,
  PackagePlus,
  ShieldAlert,
  SlidersHorizontal,
  Truck,
  Undo2,
  type LucideIcon,
} from "lucide-react";

import { AsyncBoundary, FormError } from "@/components/common/async-state";
import { PageHeader } from "@/components/common/page-header";
import { DataToolbar, TablePagination } from "@/components/common/data-toolbar";
import { FilterSelect } from "@/components/common/filter-select";
import { NewTransactionDialog } from "@/components/inventory/new-transaction-dialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
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
import { useGodowns } from "@/hooks/use-catalog";
import { useApiMutation, useListControls } from "@/hooks/use-api";
import { useTransactions } from "@/hooks/use-inventory";
import { inventoryApi } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { formatDate, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Id, InventorySourceType, InventoryTxnType } from "@/types";

const TYPE_META: Record<
  InventoryTxnType,
  { label: string; icon: LucideIcon; variant: React.ComponentProps<typeof Badge>["variant"] }
> = {
  OPENING_STOCK: { label: "Opening Stock", icon: PackagePlus, variant: "neutral" },
  GOODS_RECEIPT: { label: "Goods Receipt", icon: PackageCheck, variant: "success" },
  PURCHASE_RETURN: { label: "Purchase Return", icon: Undo2, variant: "warning" },
  TRANSFER_IN: { label: "Transfer In", icon: ArrowDownLeft, variant: "info" },
  TRANSFER_OUT: { label: "Transfer Out", icon: ArrowUpRight, variant: "info" },
  SALES_ISSUE: { label: "Sales Issue", icon: Truck, variant: "neutral" },
  SALES_RETURN: { label: "Sales Return", icon: Undo2, variant: "success" },
  DAMAGE: { label: "Damage / Write-off", icon: ShieldAlert, variant: "destructive" },
  EXPIRY_WRITE_OFF: { label: "Expiry Write-off", icon: CalendarOff, variant: "destructive" },
  STOCK_CORRECTION: { label: "Stock Correction", icon: SlidersHorizontal, variant: "warning" },
};

const TYPE_OPTIONS = Object.entries(TYPE_META).map(([value, meta]) => ({
  value: value as InventoryTxnType,
  label: meta.label,
}));

/** Where the "Source" column links to — traces a ledger row back to the document that caused it. */
function sourceLink(
  sourceType: InventorySourceType | undefined,
  sourceId: Id | undefined,
): { href: string; label: string } | null {
  switch (sourceType) {
    case "goods_receipt":
      return sourceId ? { href: `/goods-receipt/${sourceId}`, label: "Goods Receipt" } : null;
    case "purchase_return":
      return sourceId ? { href: `/purchase-returns/${sourceId}`, label: "Purchase Return" } : null;
    case "stock_transfer":
      return { href: "/inventory/transfers", label: "Stock Transfer" };
    default:
      return null;
  }
}

const SOURCE_LABELS: Record<InventorySourceType, string> = {
  goods_receipt: "Goods Receipt",
  purchase_return: "Purchase Return",
  stock_transfer: "Stock Transfer",
  adjustment: "Manual Adjustment",
  sales_issue: "Sales Issue",
  opening: "Opening Stock",
};

export function TransactionsScreen() {
  const controls = useListControls({ sort: "-txnDate" });
  const godownsState = useGodowns();
  const godowns = godownsState.data ?? [];
  const state = useTransactions(controls.params);

  // Every row the current search and filters match — not just this page.
  const exportCsv = useApiMutation(async () => {
    const all = await inventoryApi.listTransactions({ ...controls.params, cursor: null, limit: 100_000 });
    downloadCsv(
      "inventory-transactions",
      ["Txn #", "Date", "Time", "Product", "SKU", "Godown", "Type", "Quantity", "Balance After", "Performed By", "Source"],
      all.items.map((t) => {
        const when = new Date(t.txnDate);
        return [
          t.txnNumber,
          when.toLocaleDateString("en-CA"),
          when.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }),
          t.productName,
          t.sku,
          t.godownName,
          TYPE_META[t.txnType]?.label ?? t.txnType,
          t.quantity,
          t.balanceAfter,
          t.performedByName,
          t.sourceType ? SOURCE_LABELS[t.sourceType] : "",
        ];
      }),
    );
  });

  return (
    <div className="space-y-5">
      <PageHeader
        title="Inventory Transactions"
        description="The complete ledger — every change to stock, and what caused it"
        actions={
          <>
            <Button variant="outline" onClick={() => exportCsv.run(undefined)} disabled={exportCsv.isPending}>
              {exportCsv.isPending ? <Loader2 className="animate-spin" /> : <Download />}
              Export
            </Button>
            <NewTransactionDialog />
          </>
        }
      />
      <FormError message={exportCsv.error} />

      <Alert variant="info">
        <Info />
        <AlertDescription>
          Inventory is transaction-based. There is no editable &ldquo;current stock&rdquo; field —
          to change a quantity you record a correction, and it appears here.
        </AlertDescription>
      </Alert>

      <Card className="overflow-hidden">
        <DataToolbar
          searchPlaceholder="Search product, SKU, txn number or remarks..."
          searchValue={controls.q}
          onSearchChange={controls.setQ}
          filters={
            <>
              <FilterSelect
                placeholder="All Types"
                options={TYPE_OPTIONS.map((o) => o.label)}
                className="w-[180px]"
                value={TYPE_OPTIONS.find((o) => o.value === controls.filters.txnType)?.label}
                onValueChange={(label) =>
                  controls.setFilter("txnType", TYPE_OPTIONS.find((o) => o.label === label)?.value)
                }
              />
              <FilterSelect
                placeholder="All Godowns"
                options={godowns.map((g) => g.name)}
                value={godowns.find((g) => g.id === controls.filters.godownId)?.name}
                onValueChange={(name) =>
                  controls.setFilter("godownId", godowns.find((g) => g.name === name)?.id)
                }
              />
            </>
          }
        />

        <AsyncBoundary
          state={state}
          isEmpty={(d) => d.items.length === 0}
          empty={{ icon: Info, title: "No transactions match your search." }}
        >
          {(data) => (
            <>
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="pl-4">Txn #</TableHead>
                    <TableHead>Date</TableHead>
                    <TableHead>Product</TableHead>
                    <TableHead>SKU</TableHead>
                    <TableHead>Godown</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead className="text-right">Quantity</TableHead>
                    <TableHead className="text-right">Balance After</TableHead>
                    <TableHead>Performed By</TableHead>
                    <TableHead className="pr-4">Source</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((t) => {
                    const meta = TYPE_META[t.txnType];
                    const Icon = meta.icon;
                    const link = sourceLink(t.sourceType, t.sourceId);
                    return (
                      <TableRow key={t.id}>
                        <TableCell className="pl-4 font-mono text-[12.5px] text-muted-foreground">
                          {t.txnNumber}
                        </TableCell>
                        <TableCell>
                          <span className="block text-foreground">{formatDate(t.txnDate)}</span>
                          <span className="block text-caption text-muted-foreground tabular">
                            {new Date(t.txnDate).toLocaleTimeString("en-GB", {
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                          </span>
                        </TableCell>
                        <TableCell className="max-w-[200px]">
                          <Link
                            href={`/products/${t.productVariantId}`}
                            className="block truncate font-medium text-foreground hover:text-primary"
                          >
                            {t.productName}
                          </Link>
                        </TableCell>
                        <TableCell className="font-mono text-[12.5px] text-muted-foreground">
                          {t.sku}
                        </TableCell>
                        <TableCell className="text-muted-foreground">{t.godownName}</TableCell>
                        <TableCell>
                          <Badge variant={meta.variant} className="gap-1">
                            <Icon />
                            {meta.label}
                          </Badge>
                        </TableCell>
                        <TableCell
                          className={cn(
                            "text-right font-semibold tabular",
                            t.quantity > 0 ? "text-success" : "text-destructive",
                          )}
                        >
                          {t.quantity > 0 ? "+" : ""}
                          {formatNumber(t.quantity)}
                        </TableCell>
                        <TableCell className="text-right text-muted-foreground tabular">
                          {formatNumber(t.balanceAfter)}
                        </TableCell>
                        <TableCell className="text-muted-foreground">{t.performedByName}</TableCell>
                        <TableCell className="pr-4">
                          {link ? (
                            <Link
                              href={link.href}
                              className="inline-flex items-center gap-1 text-[12.5px] font-medium text-primary hover:underline"
                            >
                              {link.label}
                              <ExternalLink className="size-3" />
                            </Link>
                          ) : (
                            <span className="text-[12.5px] text-muted-foreground">
                              {t.sourceType ? SOURCE_LABELS[t.sourceType] : "—"}
                            </span>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
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
