"use client";

import Link from "next/link";
import { ArrowLeftRight, Package, Warehouse } from "lucide-react";

import { AsyncBoundary } from "@/components/common/async-state";
import { PageHeader } from "@/components/common/page-header";
import { PermissionGate } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { StatusBadge } from "@/components/common/status-badge";
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
import { useStock } from "@/hooks/use-inventory";
import { usePermissions } from "@/hooks/use-session";
import { formatCurrency, formatNumber } from "@/lib/format";
import type { StockRow } from "@/types";

export default function StockByGodownPage() {
  const permissions = usePermissions();
  const godownsState = useGodowns();
  const stockState = useStock({ limit: Number.MAX_SAFE_INTEGER });

  return (
    <div className="space-y-5">
      <PageHeader
        title="Stock by Godown"
        description="How your inventory is spread across locations"
        actions={
          <PermissionGate permission="inventory.transfer">
            <Button variant="outline" asChild>
              <Link href="/inventory/transfers">
                <ArrowLeftRight />
                Transfer Stock
              </Link>
            </Button>
          </PermissionGate>
        }
      />

      <AsyncBoundary
        state={godownsState}
        isEmpty={(d) => d.length === 0}
        empty={{ icon: Warehouse, title: "No godowns yet" }}
      >
        {(allGodowns) => {
          const visible = new Set(permissions.visibleGodowns(allGodowns.map((g) => g.id)));
          const godowns = allGodowns.filter((g) => visible.has(g.id));

          return (
            <AsyncBoundary
              state={stockState}
              isEmpty={() => false}
              empty={{ icon: Package, title: "No stock yet" }}
            >
              {(stock) => (
                <>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    {godowns.map((godown) => {
                      const rows = stock.items.filter((r: StockRow) => r.godownId === godown.id);
                      const stockValue = rows.reduce((sum, r) => sum + r.value, 0);
                      return (
                        <Card key={godown.id} className="p-4">
                          <div className="flex items-start gap-3">
                            <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary-subtle text-primary-subtle-foreground">
                              <Warehouse className="size-4.5" strokeWidth={1.9} />
                            </span>
                            <div className="min-w-0 flex-1">
                              <p className="text-section text-foreground">{godown.name}</p>
                              <p className="text-caption text-muted-foreground">
                                {godown.city} · In-charge {godown.inchargeName || "Unassigned"}
                              </p>
                            </div>
                          </div>

                          <div className="mt-4 grid grid-cols-3 gap-4">
                            <div>
                              <p className="text-caption text-muted-foreground">SKUs stored</p>
                              <p className="text-[20px] leading-none font-semibold text-foreground tabular">
                                {formatNumber(rows.length)}
                              </p>
                            </div>
                            <div>
                              <p className="text-caption text-muted-foreground">Stock value</p>
                              <p className="text-[20px] leading-none font-semibold text-foreground tabular">
                                {formatCurrency(stockValue)}
                              </p>
                            </div>
                            <div>
                              <p className="text-caption text-muted-foreground">Low / Out</p>
                              <p className="text-[20px] leading-none font-semibold text-foreground tabular">
                                {formatNumber(rows.filter((r) => r.status === "low_stock").length)} /{" "}
                                {formatNumber(rows.filter((r) => r.status === "out_of_stock").length)}
                              </p>
                            </div>
                          </div>
                        </Card>
                      );
                    })}
                  </div>

                  {godowns.map((godown) => {
                    const godownRows = stock.items.filter((r: StockRow) => r.godownId === godown.id);
                    return (
                      <SectionCard
                        key={godown.id}
                        title={godown.name}
                        description={`${godownRows.length} product line${godownRows.length === 1 ? "" : "s"} in this godown`}
                        action={
                          <Button variant="ghost" size="sm" asChild>
                            <Link href="/inventory/current-stock">View all stock</Link>
                          </Button>
                        }
                      >
                        <Table>
                          <TableHeader>
                            <TableRow className="hover:bg-transparent">
                              <TableHead className="pl-4">Product</TableHead>
                              <TableHead>SKU</TableHead>
                              <TableHead>Category</TableHead>
                              <TableHead className="text-right">Qty</TableHead>
                              <TableHead className="text-right">Value</TableHead>
                              <TableHead className="pr-4">Status</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {godownRows.map((row) => (
                              <TableRow key={row.id}>
                                <TableCell className="max-w-[230px] truncate pl-4 font-medium text-foreground">
                                  <Link
                                    href={`/products/${row.productVariantId}`}
                                    className="hover:text-primary"
                                  >
                                    {row.productName}
                                  </Link>
                                </TableCell>
                                <TableCell className="font-mono text-[12.5px] text-muted-foreground">
                                  {row.sku}
                                </TableCell>
                                <TableCell className="text-muted-foreground">{row.categoryName}</TableCell>
                                <TableCell className="text-right font-semibold text-foreground tabular">
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
                            {godownRows.length === 0 && (
                              <TableRow>
                                <TableCell colSpan={6} className="py-8 text-center text-muted-foreground">
                                  No stock in this godown.
                                </TableCell>
                              </TableRow>
                            )}
                          </TableBody>
                        </Table>
                      </SectionCard>
                    );
                  })}
                </>
              )}
            </AsyncBoundary>
          );
        }}
      </AsyncBoundary>
    </div>
  );
}
