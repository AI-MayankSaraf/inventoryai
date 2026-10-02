"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, Package, PackagePlus, Truck, Warehouse } from "lucide-react";

import { AsyncBoundary, LoadingCard } from "@/components/common/async-state";
import { AuditTrail } from "@/components/common/audit-trail";
import { DetailGrid, DetailRow } from "@/components/common/detail-row";
import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/common/page-header";
import { OwnerOnlyGate } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { StatusBadge } from "@/components/common/status-badge";
import { ProductFormDialog } from "@/components/products/product-form-dialog";
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
import { GodownLevelsCard } from "@/components/products/godown-levels-card";
import { ProductFilesCard } from "@/components/products/product-files-card";
import { UomConversionsCard } from "@/components/products/uom-conversions-card";
import { useProduct } from "@/hooks/use-catalog";
import { useStockByGodown, useVariantLedger } from "@/hooks/use-inventory";
import { formatCurrency, formatDate, formatDateTime, formatNumber } from "@/lib/format";
import type { Id, StockState } from "@/types";
import { cn } from "@/lib/utils";

const TRACKING_LABELS: Record<string, string> = {
  none: "None",
  batch: "Batch tracked",
  serial: "Serial tracked",
};

function stockStatus(totalStock: number, reorderPoint: number): StockState {
  if (totalStock <= 0) return "out_of_stock";
  if (totalStock <= reorderPoint) return "low_stock";
  return "in_stock";
}

export function ProductDetailScreen({ variantId }: { variantId: Id }) {
  const state = useProduct(variantId);
  const stockState = useStockByGodown(variantId);
  const ledgerState = useVariantLedger(variantId);

  return (
    <div className="space-y-5">
      <Button variant="ghost" size="sm" asChild className="-ml-2 text-muted-foreground">
        <Link href="/products">
          <ArrowLeft />
          All Products
        </Link>
      </Button>

      <AsyncBoundary state={state} loading={<LoadingCard />}>
        {(detail) => {
          const totalStock = (stockState.data ?? []).reduce((sum, r) => sum + r.quantity, 0);
          const status = stockStatus(totalStock, detail.variant.reorderPoint);
          const recentLedger = [...(ledgerState.data ?? [])].slice(-10).reverse();

          return (
            <div className="space-y-5">
              <PageHeader
                title={
                  <span className="flex items-center gap-3">
                    <span className="flex size-11 items-center justify-center rounded-lg border border-border bg-card text-muted-foreground">
                      <Package className="size-5" />
                    </span>
                    {detail.product.name}
                  </span>
                }
                description={
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[12.5px]">{detail.variant.sku}</span>
                    <span className="text-border">·</span>
                    <span>{detail.brandName || "No brand"}</span>
                    <span className="text-border">·</span>
                    <span>{detail.categoryName || "Uncategorised"}</span>
                    <StatusBadge status={status} className="ml-1" />
                    {!detail.variant.isActive && <StatusBadge status="inactive" />}
                  </span>
                }
                actions={
                  <>
                    <Button variant="outline" asChild>
                      <Link href="/procurement/rfq">
                        <PackagePlus />
                        Create RFQ
                      </Link>
                    </Button>
                    <OwnerOnlyGate>
                      <ProductFormDialog variantId={detail.variant.id} />
                    </OwnerOnlyGate>
                  </>
                }
              />

              {/* Stock summary — no Reserved/Available cards: reservedQuantity is always
                  0 in this product (I6), so we show only real, query-backed numbers. */}
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                {[
                  { label: "Total Stock", value: formatNumber(totalStock), unit: detail.uomCode },
                  {
                    label: "Reorder Point",
                    value: formatNumber(detail.variant.reorderPoint),
                    unit: detail.uomCode,
                  },
                  {
                    label: "Reorder Quantity",
                    value: formatNumber(detail.variant.reorderQty),
                    unit: detail.uomCode,
                  },
                  {
                    label: "Lead Time",
                    value: formatNumber(detail.variant.leadTimeDays ?? 0),
                    unit: "days",
                  },
                ].map((stat) => (
                  <Card key={stat.label} className="p-4">
                    <p className="text-label text-muted-foreground">{stat.label}</p>
                    <p className="mt-1.5 text-[22px] leading-none font-semibold tracking-[-0.02em] text-foreground tabular">
                      {stat.value}{" "}
                      <span className="text-[12px] font-normal text-muted-foreground">{stat.unit}</span>
                    </p>
                  </Card>
                ))}
              </div>

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
                <div className="space-y-4 lg:col-span-8">
                  <SectionCard title="Basic Information">
                    <div className="p-4">
                      <DetailGrid columns={3}>
                        <DetailRow label="SKU" value={detail.variant.sku} mono />
                        <DetailRow label="Product Name" value={detail.product.name} />
                        <DetailRow label="Brand" value={detail.brandName} />
                        <DetailRow label="Category" value={detail.categoryPath || detail.categoryName} />
                        <DetailRow label="Unit" value={detail.uomCode} />
                        <DetailRow label="Tracking" value={TRACKING_LABELS[detail.product.trackingType]} />
                      </DetailGrid>
                    </div>
                  </SectionCard>

                  <SectionCard title="Product Identification">
                    <div className="p-4">
                      <DetailGrid columns={3}>
                        <DetailRow label="Barcode" value={detail.variant.barcode} mono />
                        <DetailRow label="EAN" value={detail.variant.ean} mono />
                        <DetailRow label="UPC" value={detail.variant.upc} mono />
                        <DetailRow label="MPN" value={detail.variant.mpn} mono />
                        <DetailRow label="HSN Code" value={detail.variant.hsnCode} mono />
                        <DetailRow label="Manufacturer" value={detail.product.manufacturerName} />
                        <DetailRow label="Created" value={detail.variant.createdAt ? formatDateTime(detail.variant.createdAt) : "—"} />
                        <DetailRow label="Last Updated" value={detail.variant.updatedAt ? formatDateTime(detail.variant.updatedAt) : "—"} />
                      </DetailGrid>
                    </div>
                  </SectionCard>

                  {Object.keys(detail.variant.attributes ?? {}).length > 0 && (
                    <SectionCard title="Product Attributes">
                      <div className="p-4">
                        <DetailGrid columns={3}>
                          {Object.entries(detail.variant.attributes).map(([key, value]) => (
                            <DetailRow key={key} label={key} value={value} />
                          ))}
                        </DetailGrid>
                      </div>
                    </SectionCard>
                  )}

                  <SectionCard
                    title="Stock Movement"
                    description="Last 10 ledger entries — stock only ever changes through a posted transaction"
                    action={
                      <Button variant="ghost" size="sm" asChild>
                        <Link href="/inventory/transactions">View all</Link>
                      </Button>
                    }
                  >
                    <AsyncBoundary
                      state={ledgerState}
                      loading={<LoadingCard />}
                      empty={{
                        icon: Warehouse,
                        title: "No stock movements yet",
                        description: "Movements appear here once stock is received, transferred or adjusted.",
                      }}
                      isEmpty={() => recentLedger.length === 0}
                    >
                      {() => (
                        <Table>
                          <TableHeader>
                            <TableRow className="hover:bg-transparent">
                              <TableHead className="pl-4">Date</TableHead>
                              <TableHead>Type</TableHead>
                              <TableHead>Godown</TableHead>
                              <TableHead className="text-right">Qty</TableHead>
                              <TableHead className="text-right">Balance</TableHead>
                              <TableHead className="pr-4">Reference</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {recentLedger.map((t) => (
                              <TableRow key={t.id}>
                                <TableCell className="pl-4 text-muted-foreground">
                                  {formatDate(t.txnDate)}
                                </TableCell>
                                <TableCell className="text-foreground">
                                  {t.txnType.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase())}
                                </TableCell>
                                <TableCell className="text-muted-foreground">{t.godownName}</TableCell>
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
                                <TableCell className="pr-4 font-mono text-[12.5px] text-muted-foreground">
                                  {t.txnNumber}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      )}
                    </AsyncBoundary>
                  </SectionCard>

                  <AuditTrail entityType="product_variant" entityId={detail.variant.id} />
                </div>

                <div className="space-y-4 lg:col-span-4">
                  <SectionCard title="Pricing">
                    <div className="space-y-3 p-4">
                      {[
                        { label: "Purchase Price", value: detail.variant.purchasePrice },
                        { label: "Sale Price", value: detail.variant.salePrice },
                        { label: "MRP", value: detail.variant.mrp },
                      ].map((row) => (
                        <div key={row.label} className="flex items-center justify-between text-[13.5px]">
                          <span className="text-muted-foreground">{row.label}</span>
                          <span className="font-medium text-foreground tabular">
                            {formatCurrency(row.value)}
                          </span>
                        </div>
                      ))}
                      <div className="flex items-center justify-between border-t border-border pt-3 text-[13.5px]">
                        <span className="text-muted-foreground">GST Rate</span>
                        <span className="font-medium text-foreground tabular">
                          {detail.variant.gstRate ?? detail.product.gstRate}%
                        </span>
                      </div>
                    </div>
                  </SectionCard>

                  <SectionCard title="Stock by Godown" description="Where this product sits today">
                    <AsyncBoundary
                      state={stockState}
                      loading={<LoadingCard />}
                      empty={{ icon: Warehouse, title: "No stock yet" }}
                      isEmpty={(rows) => rows.length === 0}
                    >
                      {(rows) => (
                        <ul className="divide-y divide-border">
                          {rows.map((row) => (
                            <li key={row.id} className="flex items-center gap-3 px-4 py-3">
                              <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                                <Warehouse className="size-4" strokeWidth={1.9} />
                              </span>
                              <span className="min-w-0 flex-1">
                                <span className="block text-[13.5px] font-medium text-foreground">
                                  {row.godownName}
                                </span>
                                <span className="block text-caption text-muted-foreground">
                                  {row.uomCode}
                                </span>
                              </span>
                              <span className="text-[15px] font-semibold text-foreground tabular">
                                {formatNumber(row.quantity)}
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </AsyncBoundary>
                  </SectionCard>

                  <UomConversionsCard
                    variantId={detail.variant.id}
                    baseUomId={detail.variant.uomId}
                    baseCode={detail.uomCode}
                    conversions={detail.conversions}
                    onChanged={state.refresh}
                  />

                  <GodownLevelsCard
                    variantId={detail.variant.id}
                    uomCode={detail.uomCode}
                    defaultReorderPoint={detail.variant.reorderPoint}
                    defaultReorderQty={detail.variant.reorderQty}
                    policies={detail.policies}
                    onChanged={state.refresh}
                  />

                  <SectionCard title="Suppliers" description="Who we buy this SKU from">
                    {detail.suppliers.length === 0 ? (
                      <EmptyState
                        icon={Truck}
                        title="No suppliers linked"
                        description="Suppliers appear here once you buy this SKU or record a supplier's code for it."
                        className="py-8"
                      />
                    ) : (
                      <ul className="divide-y divide-border">
                        {detail.suppliers.map((s) => (
                          <li key={s.supplierId} className="flex items-center gap-3 px-4 py-3">
                            <span className="min-w-0 flex-1">
                              <Link
                                href={`/suppliers/${s.supplierId}`}
                                className="block truncate text-[13.5px] font-medium text-foreground hover:text-primary"
                              >
                                {s.supplierName}
                                {s.isPreferred && (
                                  <StatusBadge status="active" label="Preferred" className="ml-2" />
                                )}
                              </Link>
                              <span className="block text-caption text-muted-foreground">
                                {s.supplierSku
                                  ? `Their code: ${s.supplierSku}`
                                  : s.fromHistory
                                    ? "From purchases — no supplier code on file"
                                    : "No supplier code on file"}
                              </span>
                            </span>
                            {typeof s.lastPurchasePrice === "number" && (
                              <span className="text-[13px] font-medium text-foreground tabular">
                                {formatCurrency(s.lastPurchasePrice)}
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </SectionCard>

                  <ProductFilesCard variantId={detail.variant.id} />
                </div>
              </div>
            </div>
          );
        }}
      </AsyncBoundary>
    </div>
  );
}
