"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, Ban, Check, Lock, PackageCheck, Send } from "lucide-react";

import { AsyncBoundary, FormError, LoadingCard } from "@/components/common/async-state";
import { AuditTrail } from "@/components/common/audit-trail";
import { ConfirmButton } from "@/components/common/confirm-dialog";
import { DetailGrid, DetailRow } from "@/components/common/detail-row";
import { PageHeader } from "@/components/common/page-header";
import { PermissionGate } from "@/components/common/permission-gate";
import { PrintButton } from "@/components/common/print-button";
import { PrintHeader } from "@/components/common/print-header";
import { SectionCard } from "@/components/common/section-card";
import { StatusBadge } from "@/components/common/status-badge";
import { TaxSummary } from "@/components/procurement/tax-summary";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useCompanySettings } from "@/hooks/use-admin";
import { usePurchaseOrder, useSetPurchaseOrderStatus } from "@/hooks/use-procurement";
import { usePermissions } from "@/hooks/use-session";
import { formatCurrency, formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Id, PurchaseOrderStatus } from "@/types";

export function PoDetailScreen({ id }: { id: Id }) {
  const state = usePurchaseOrder(id);
  const permissions = usePermissions();
  const settingsState = useCompanySettings();
  // Approve/send/cancel/close all stay on this same page (no navigation
  // like RFQ's send does), so without an explicit refresh the screen keeps
  // showing the pre-transition status and button set after a successful
  // mutation — the established fix elsewhere in this codebase
  // (rfq-detail-screen.tsx, quotations/[id]/page.tsx) is exactly this.
  const setStatus = useSetPurchaseOrderStatus(() => state.refresh());
  const [cancelOpen, setCancelOpen] = React.useState(false);
  const [cancelReason, setCancelReason] = React.useState("");

  return (
    <div className="space-y-5">
      <Button variant="ghost" size="sm" asChild className="-ml-2 text-muted-foreground">
        <Link href="/procurement/purchase-orders">
          <ArrowLeft />
          All Purchase Orders
        </Link>
      </Button>

      <AsyncBoundary state={state} loading={<LoadingCard />}>
        {(detail) => {
          const po = detail.purchaseOrder;
          const allowed = new Set<PurchaseOrderStatus>(detail.allowedActions);
          const threshold = settingsState.data?.settings.requirePoApprovalAbove ?? Infinity;
          const canApprove = permissions.canApprovePo(po.totalAmount, threshold);

          async function transition(status: PurchaseOrderStatus) {
            await setStatus.run({ purchaseOrderId: po.id, status });
          }

          return (
            <div className="space-y-5">
              <PageHeader
                title={po.poNumber}
                description={`${detail.supplierName} · ${formatDate(po.poDate)}`}
                actions={
                  <>
                    <PrintButton />
                    {allowed.has("pending_approval") && (
                      <PermissionGate permission="po.submit">
                        <ConfirmButton
                          title="Submit for approval?"
                          description={`${po.poNumber} will move to pending approval.`}
                          confirmLabel="Submit"
                          onConfirm={() => transition("pending_approval")}
                        >
                          <Send />
                          Submit for Approval
                        </ConfirmButton>
                      </PermissionGate>
                    )}
                    {allowed.has("approved") && (
                      <PermissionGate permission="po.approve">
                        {canApprove ? (
                          <ConfirmButton
                            title="Approve this Purchase Order?"
                            description="Once approved, it's ready to send to the supplier."
                            confirmLabel="Approve"
                            tone="success"
                            onConfirm={() => transition("approved")}
                          >
                            <Check />
                            Approve
                          </ConfirmButton>
                        ) : (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span className="inline-flex">
                                <Button variant="outline" disabled className="pointer-events-none">
                                  <Lock className="size-3.5" />
                                  Approve
                                </Button>
                              </span>
                            </TooltipTrigger>
                            <TooltipContent>
                              Above {formatCurrency(threshold)} — needs the high-value approval
                              permission (po.approve_high_value).
                            </TooltipContent>
                          </Tooltip>
                        )}
                      </PermissionGate>
                    )}
                    {allowed.has("sent") && (
                      <PermissionGate permission="po.send">
                        <ConfirmButton
                          title="Send this Purchase Order to the supplier?"
                          description={`${detail.supplierName} will be emailed a copy of ${po.poNumber}.`}
                          confirmLabel="Send"
                          onConfirm={() => transition("sent")}
                        >
                          <Send />
                          Send to Supplier
                        </ConfirmButton>
                      </PermissionGate>
                    )}
                    {allowed.has("closed") && (
                      <PermissionGate permission="po.close">
                        <ConfirmButton
                          title="Close this Purchase Order?"
                          description="Short-closes the order — no further receipts are expected against it."
                          confirmLabel="Close"
                          onConfirm={() => transition("closed")}
                        >
                          <PackageCheck />
                          Close Order
                        </ConfirmButton>
                      </PermissionGate>
                    )}
                    {allowed.has("cancelled") && (
                      <PermissionGate permission="po.cancel">
                        <Button
                          variant="outline"
                          className="text-destructive hover:text-destructive"
                          onClick={() => setCancelOpen(true)}
                        >
                          <Ban />
                          Cancel
                        </Button>
                      </PermissionGate>
                    )}
                  </>
                }
              />

              {setStatus.error && !cancelOpen && <FormError message={setStatus.error} />}

              <PrintHeader
                company={settingsState.data?.company.name ?? ""}
                gstin={settingsState.data?.company.gstin}
                address={settingsState.data?.company.addressLine1}
                email={settingsState.data?.company.email}
                phone={settingsState.data?.company.phone}
                docLabel={`Purchase Order — ${po.poNumber}`}
              />

              <SectionCard title="Order Details">
                <DetailGrid className="p-4" columns={3}>
                  <DetailRow label="Supplier" value={detail.supplierName} />
                  <DetailRow label="Supplier GSTIN" value={detail.supplierGstin} mono />
                  <DetailRow label="Status" value={<StatusBadge status={po.status} />} />
                  <DetailRow label="PO Date" value={formatDate(po.poDate)} />
                  <DetailRow
                    label="Expected Delivery"
                    value={po.expectedDeliveryDate ? formatDate(po.expectedDeliveryDate) : "—"}
                  />
                  <DetailRow label="Received" value={`${po.receivedPct}%`} />
                  <DetailRow label="Payment Terms" value={po.paymentTerms} />
                  <DetailRow label="Delivery Terms" value={po.deliveryTerms} />
                  <DetailRow label="Deliver To" value={detail.godownName} />
                  <DetailRow label="Linked RFQ" value={detail.rfqNumber ?? "—"} />
                  <DetailRow label="Linked Quotation" value={detail.quotationNumber ?? "—"} />
                  <DetailRow
                    label="Tax Treatment"
                    value={po.isInterState ? "IGST (inter-state)" : "CGST + SGST (intra-state)"}
                  />
                </DetailGrid>
              </SectionCard>

              <SectionCard title={`Items (${detail.items.length})`}>
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="pl-4">Product</TableHead>
                      <TableHead className="text-right">Ordered</TableHead>
                      <TableHead className="text-right">Received</TableHead>
                      <TableHead className="text-right">Pending</TableHead>
                      <TableHead className="text-right">Rate</TableHead>
                      <TableHead className="text-right">GST %</TableHead>
                      <TableHead>Line Status</TableHead>
                      <TableHead className="pr-4 text-right">Total</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {detail.items.map((line) => (
                      <TableRow key={line.id}>
                        <TableCell className="pl-4">
                          <span className="block font-medium text-foreground">{line.productName}</span>
                          <span className="block text-caption text-muted-foreground">{line.sku}</span>
                        </TableCell>
                        <TableCell className="text-right tabular">
                          {line.quantity} {line.uomCode}
                        </TableCell>
                        <TableCell className="text-right tabular">
                          {line.receivedQuantity} {line.uomCode}
                        </TableCell>
                        <TableCell
                          className={cn(
                            "text-right tabular",
                            line.pendingQuantity > 0 ? "font-medium text-foreground" : "text-muted-foreground",
                          )}
                        >
                          {line.pendingQuantity} {line.uomCode}
                        </TableCell>
                        <TableCell className="text-right tabular">{formatCurrency(line.unitPrice)}</TableCell>
                        <TableCell className="text-right tabular">{line.gstRate}%</TableCell>
                        <TableCell>
                          <StatusBadge status={line.lineStatus} />
                        </TableCell>
                        <TableCell className="pr-4 text-right font-medium tabular">
                          {formatCurrency(line.lineTotal)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </SectionCard>

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
                <div className="lg:col-span-5">
                  <SectionCard title="Totals">
                    <div className="p-4">
                      <TaxSummary money={po} taxRows={detail.taxRows} />
                    </div>
                  </SectionCard>
                </div>

                <div className="lg:col-span-7">
                  <SectionCard title="Linked Documents">
                    <div className="divide-y divide-border">
                      <LinkedDocGroup title="Goods Receipts" emptyLabel="No receipts recorded yet.">
                        {detail.receipts.map((r) => (
                          <Link
                            key={r.id}
                            href={`/goods-receipt/${r.id}`}
                            className="flex items-center justify-between px-4 py-2 hover:bg-muted/50"
                          >
                            <span className="font-mono text-[12.5px] text-foreground">{r.grnNumber}</span>
                            <span className="flex items-center gap-2">
                              <span className="text-caption text-muted-foreground">{formatDate(r.grnDate)}</span>
                              <StatusBadge status={r.status} />
                            </span>
                          </Link>
                        ))}
                      </LinkedDocGroup>
                      <LinkedDocGroup title="Proforma Invoices" emptyLabel="No proforma invoices linked yet.">
                        {detail.proformas.map((p) => (
                          <Link
                            key={p.id}
                            href={`/procurement/proforma/${p.id}`}
                            className="flex items-center justify-between px-4 py-2 hover:bg-muted/50"
                          >
                            <span className="font-mono text-[12.5px] text-foreground">{p.proformaNumber}</span>
                            <span className="flex items-center gap-2">
                              {Math.abs(p.varianceAmount) > 0.5 && (
                                <span className="text-caption text-warning-subtle-foreground">
                                  {formatCurrency(p.varianceAmount, true)} variance
                                </span>
                              )}
                              <StatusBadge status={p.status} />
                            </span>
                          </Link>
                        ))}
                      </LinkedDocGroup>
                      <LinkedDocGroup title="Supplier Invoices" emptyLabel="No supplier invoices linked yet.">
                        {detail.invoices.map((inv) => (
                          <Link
                            key={inv.id}
                            href={`/supplier-invoices/${inv.id}`}
                            className="flex items-center justify-between px-4 py-2 hover:bg-muted/50"
                          >
                            <span className="font-mono text-[12.5px] text-foreground">{inv.invoiceNumber}</span>
                            <span className="flex items-center gap-2">
                              <span className="text-caption text-muted-foreground tabular">
                                {formatCurrency(inv.totalAmount)}
                              </span>
                              <StatusBadge status={inv.status} />
                            </span>
                          </Link>
                        ))}
                      </LinkedDocGroup>
                      <div className="flex items-center justify-between px-4 py-2.5">
                        <span className="text-[13px] text-muted-foreground">Open variances</span>
                        <span
                          className={cn(
                            "text-[13px] font-medium tabular",
                            detail.variances > 0 ? "text-warning-subtle-foreground" : "text-foreground",
                          )}
                        >
                          {detail.variances}
                        </span>
                      </div>
                    </div>
                  </SectionCard>
                </div>
              </div>

              <AuditTrail entityType="purchase_order" entityId={po.id} />

              <Dialog
                open={cancelOpen}
                onOpenChange={(open) => {
                  setCancelOpen(open);
                  if (!open) {
                    setCancelReason("");
                    setStatus.reset();
                  }
                }}
              >
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Cancel this Purchase Order?</DialogTitle>
                    <DialogDescription>
                      Give a reason for cancelling {po.poNumber}. This can&apos;t be undone.
                    </DialogDescription>
                  </DialogHeader>
                  <DialogBody>
                    <div className="space-y-1.5">
                      <Label htmlFor="po-cancel-reason">Reason</Label>
                      <Textarea
                        id="po-cancel-reason"
                        value={cancelReason}
                        onChange={(e) => setCancelReason(e.target.value)}
                        placeholder="Why is this purchase order being cancelled?"
                      />
                    </div>
                    <FormError message={setStatus.error} className="mt-3" />
                  </DialogBody>
                  <DialogFooter>
                    <Button variant="outline" disabled={setStatus.isPending} onClick={() => setCancelOpen(false)}>
                      Keep Order
                    </Button>
                    <Button
                      variant="destructive"
                      disabled={setStatus.isPending || !cancelReason.trim()}
                      onClick={async () => {
                        const result = await setStatus.run({
                          purchaseOrderId: po.id,
                          status: "cancelled",
                          reason: cancelReason.trim(),
                        });
                        if (result) {
                          setCancelOpen(false);
                          setCancelReason("");
                        }
                      }}
                    >
                      Cancel Purchase Order
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            </div>
          );
        }}
      </AsyncBoundary>
    </div>
  );
}

function LinkedDocGroup({
  title,
  emptyLabel,
  children,
}: {
  title: string;
  emptyLabel: string;
  children: React.ReactNode;
}) {
  const hasChildren = React.Children.count(children) > 0;
  return (
    <div>
      <p className="px-4 pt-3 pb-1 text-[12px] font-semibold tracking-wide text-muted-foreground uppercase">
        {title}
      </p>
      {hasChildren ? (
        <div className="pb-1">{children}</div>
      ) : (
        <p className="px-4 pb-3 text-[13px] text-muted-foreground">{emptyLabel}</p>
      )}
    </div>
  );
}
