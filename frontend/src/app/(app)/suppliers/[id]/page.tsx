"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft, FileText, Lock, Package, Send } from "lucide-react";

import { AsyncBoundary, LoadingCard } from "@/components/common/async-state";
import { AuditTrail } from "@/components/common/audit-trail";
import { DetailGrid, DetailRow } from "@/components/common/detail-row";
import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/common/page-header";
import { SectionCard } from "@/components/common/section-card";
import { StatusBadge } from "@/components/common/status-badge";
import { SupplierContactsCard } from "@/components/suppliers/supplier-contacts-card";
import { SupplierPortalAccessCard } from "@/components/suppliers/supplier-portal-access-card";
import { SupplierDetailActions } from "@/components/suppliers/supplier-detail-actions";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useSupplier } from "@/hooks/use-suppliers";
import { formatCompactINR, formatCurrency, formatDate } from "@/lib/format";

export default function SupplierDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const state = useSupplier(decodeURIComponent(id));

  return (
    <div className="space-y-5">
      <Button variant="ghost" size="sm" asChild className="-ml-2 text-muted-foreground">
        <Link href="/suppliers">
          <ArrowLeft />
          All Suppliers
        </Link>
      </Button>

      <AsyncBoundary state={state} loading={<LoadingCard />}>
        {(detail) => {
          const { supplier, performance } = detail;
          return (
            <div className="space-y-5">
              <PageHeader
                title={supplier.name}
                description={
                  <span className="flex flex-wrap items-center gap-2">
                    <span>{supplier.supplierType}</span>
                    <span className="text-border">·</span>
                    <span>
                      {supplier.city}, {supplier.stateName}
                    </span>
                    <StatusBadge status={supplier.status} className="ml-1" />
                  </span>
                }
                actions={
                  <>
                    <Button variant="outline" asChild>
                      <Link href="/procurement/rfq">
                        <Send />
                        Send RFQ
                      </Link>
                    </Button>
                    <SupplierDetailActions supplier={supplier} />
                  </>
                }
              />

              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                {[
                  { label: "Total Purchases", value: formatCompactINR(performance.totalPurchases) },
                  { label: "Products Supplied", value: String(performance.productsSupplied) },
                  { label: "Open Orders", value: String(performance.openOrders) },
                  { label: "On-time Delivery", value: `${performance.onTimeDeliveryPct}%` },
                ].map((stat) => (
                  <Card key={stat.label} className="p-4">
                    <p className="text-label text-muted-foreground">{stat.label}</p>
                    <p className="mt-1.5 text-[22px] leading-none font-semibold tracking-[-0.02em] text-foreground tabular">
                      {stat.value}
                    </p>
                  </Card>
                ))}
              </div>

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
                <div className="space-y-4 lg:col-span-8">
                  <SectionCard title="Company Information">
                    <div className="p-4">
                      <DetailGrid columns={2}>
                        <DetailRow label="GSTIN" value={supplier.gstin ?? "Unregistered"} mono />
                        <DetailRow label="PAN" value={supplier.pan} mono />
                        <DetailRow label="Address" value={supplier.address} />
                        <DetailRow label="City / State" value={`${supplier.city}, ${supplier.stateName}`} />
                        <DetailRow
                          label="GST Treatment"
                          value={supplier.gstTreatment.replace(/^\w/, (c) => c.toUpperCase())}
                        />
                        <DetailRow label="Supplier Type" value={supplier.supplierType} />
                        <DetailRow
                          label="Payment Terms"
                          value={
                            supplier.paymentTermsDays
                              ? `${supplier.paymentTerms} (${supplier.paymentTermsDays} days)`
                              : supplier.paymentTerms
                          }
                        />
                        <DetailRow
                          label="Bank"
                          value={
                            supplier.bankName
                              ? [supplier.bankName, supplier.bankIfsc].filter(Boolean).join(" · ")
                              : undefined
                          }
                        />
                        <DetailRow label="Account No." value={supplier.bankAccountNo} mono />
                      </DetailGrid>
                    </div>
                  </SectionCard>

                  <SectionCard
                    title="Linked Products"
                    description="Supplier item codes mapped to our SKUs"
                  >
                    {detail.products.length === 0 ? (
                      <EmptyState
                        icon={Package}
                        title="No products linked yet"
                        description="SKUs appear here once you buy them from this supplier or record their item code."
                        className="py-8"
                      />
                    ) : (
                      <Table>
                        <TableHeader>
                          <TableRow className="hover:bg-transparent">
                            <TableHead className="pl-4">SKU</TableHead>
                            <TableHead>Product</TableHead>
                            <TableHead>Their Code</TableHead>
                            <TableHead className="text-right">Last Price</TableHead>
                            <TableHead className="pr-4">Preferred</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {detail.products.map((p) => (
                            <TableRow key={p.id}>
                              <TableCell className="pl-4">
                                <Link
                                  href={`/products/${p.productVariantId}`}
                                  className="font-mono text-[12.5px] text-foreground hover:text-primary"
                                >
                                  {p.sku}
                                </Link>
                              </TableCell>
                              <TableCell className="text-muted-foreground">{p.productName}</TableCell>
                              <TableCell className="font-mono text-[12.5px] text-muted-foreground">
                                {p.supplierSku ?? (
                                  <span className="font-sans text-caption">
                                    {p.matchSource === "purchase_history" ? "From purchases" : "—"}
                                  </span>
                                )}
                              </TableCell>
                              <TableCell className="text-right text-foreground tabular">
                                {typeof p.lastPurchasePrice === "number" ? formatCurrency(p.lastPurchasePrice) : "—"}
                              </TableCell>
                              <TableCell className="pr-4">
                                {p.isPreferred ? <StatusBadge status="active" label="Preferred" /> : "—"}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    )}
                  </SectionCard>

                  <SectionCard title="Purchase History" description="Orders raised against this supplier">
                    {!detail.canSeeOrders ? (
                      <EmptyState
                        icon={Lock}
                        title="Purchase orders are hidden for your role"
                        description="Ask an Owner or Purchase Manager if you need this supplier's order history."
                        className="py-8"
                      />
                    ) : detail.recentOrders.length === 0 ? (
                      <EmptyState
                        icon={FileText}
                        title="No purchase orders yet"
                        description="Orders you raise for this supplier will be listed here."
                        action={
                          <Button variant="outline" size="sm" asChild>
                            <Link href="/procurement/rfq">Create your first RFQ</Link>
                          </Button>
                        }
                      />
                    ) : (
                      <Table>
                        <TableHeader>
                          <TableRow className="hover:bg-transparent">
                            <TableHead className="pl-4">PO Number</TableHead>
                            <TableHead>Date</TableHead>
                            <TableHead className="text-right">Received</TableHead>
                            <TableHead className="text-right">Value</TableHead>
                            <TableHead className="pr-4">Status</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {detail.recentOrders.map((po) => (
                            <TableRow key={po.id}>
                              <TableCell className="pl-4">
                                <Link
                                  href={`/procurement/purchase-orders/${po.id}`}
                                  className="font-mono text-[12.5px] text-foreground hover:text-primary"
                                >
                                  {po.poNumber}
                                </Link>
                              </TableCell>
                              <TableCell className="text-muted-foreground">{formatDate(po.poDate)}</TableCell>
                              <TableCell className="text-right text-muted-foreground tabular">
                                {po.receivedPct}%
                              </TableCell>
                              <TableCell className="text-right font-medium text-foreground tabular">
                                {formatCurrency(po.totalAmount)}
                              </TableCell>
                              <TableCell className="pr-4">
                                <StatusBadge status={po.status} />
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    )}
                  </SectionCard>

                  <AuditTrail entityType="supplier" entityId={supplier.id} />
                </div>

                <div className="space-y-4 lg:col-span-4">
                  <SupplierContactsCard
                    supplierId={supplier.id}
                    contacts={detail.contacts}
                    onChanged={state.refresh}
                  />

                  <SupplierPortalAccessCard supplierId={supplier.id} contacts={detail.contacts} />

                  <SectionCard title="Performance" description="Derived from purchase orders and receipts">
                    <div className="space-y-4 p-4">
                      {[
                        { label: "On-time delivery", value: performance.onTimeDeliveryPct },
                        { label: "Quality score", value: performance.qualityScorePct },
                      ].map((metric) => (
                        <div key={metric.label}>
                          <div className="mb-1.5 flex items-center justify-between text-[13px]">
                            <span className="text-muted-foreground">{metric.label}</span>
                            <span className="font-medium text-foreground tabular">{metric.value}%</span>
                          </div>
                          <Progress
                            value={metric.value}
                            indicatorClassName={
                              metric.value >= 90
                                ? "bg-success"
                                : metric.value >= 75
                                  ? "bg-warning"
                                  : "bg-destructive"
                            }
                          />
                        </div>
                      ))}
                      <div className="flex items-center justify-between border-t border-border pt-3 text-[13px]">
                        <span className="text-muted-foreground">Open variances</span>
                        <StatusBadge
                          status={detail.openVariances > 0 ? "variance" : "matched"}
                          label={String(detail.openVariances)}
                        />
                      </div>
                    </div>
                  </SectionCard>

                  <SectionCard title="Documents">
                    <EmptyState
                      icon={FileText}
                      title="No documents"
                      description="GST certificate, agreements and rate lists will appear here."
                      action={
                        <Button variant="outline" size="sm">
                          Upload document
                        </Button>
                      }
                      className="py-8"
                    />
                  </SectionCard>
                </div>
              </div>
            </div>
          );
        }}
      </AsyncBoundary>
    </div>
  );
}
