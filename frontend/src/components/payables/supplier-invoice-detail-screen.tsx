"use client";

import * as React from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Ban,
  Check,
  IndianRupee,
  RefreshCw,
  Send,
  TriangleAlert,
  Undo2,
} from "lucide-react";

import { AsyncBoundary, FormError, LoadingCard } from "@/components/common/async-state";
import { AuditTrail } from "@/components/common/audit-trail";
import { ConfirmButton } from "@/components/common/confirm-dialog";
import { DetailGrid, DetailRow } from "@/components/common/detail-row";
import { PageHeader } from "@/components/common/page-header";
import { PermissionGate } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { SeverityBadge, StatusBadge } from "@/components/common/status-badge";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useRecordPayment,
  useRunThreeWayMatch,
  useSetInvoiceStatus,
  useSupplierInvoice,
} from "@/hooks/use-invoices";
import { formatCurrency, formatDate, formatQuantity, formatVariancePct } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DocumentVariance, Id, SupplierInvoiceStatus } from "@/types";

/**
 * Supplier invoice detail.
 *
 * The whole reason this screen exists is the block that compares three
 * numbers: what was ordered, what was actually accepted, and what the
 * supplier billed. `detail.match` is the outcome of that comparison — this
 * screen never recomputes it, it only presents what the API found.
 */
export function SupplierInvoiceDetailScreen({ id }: { id: Id }) {
  const state = useSupplierInvoice(id);
  const setStatus = useSetInvoiceStatus();
  const runMatch = useRunThreeWayMatch();
  const recordPayment = useRecordPayment(() => {
    setPaymentOpen(false);
    setPaymentAmount("");
  });

  const [disputeOpen, setDisputeOpen] = React.useState(false);
  const [disputeReason, setDisputeReason] = React.useState("");
  const [cancelOpen, setCancelOpen] = React.useState(false);
  const [cancelReason, setCancelReason] = React.useState("");
  const [paymentOpen, setPaymentOpen] = React.useState(false);
  const [paymentAmount, setPaymentAmount] = React.useState("");

  return (
    <div className="space-y-5">
      <Button variant="ghost" size="sm" asChild className="-ml-2 text-muted-foreground">
        <Link href="/supplier-invoices">
          <ArrowLeft />
          All Supplier Invoices
        </Link>
      </Button>

      <AsyncBoundary state={state} loading={<LoadingCard />}>
        {(detail) => {
          const invoice = detail.invoice;
          const allowed = new Set<SupplierInvoiceStatus>(detail.allowedActions);
          const balanceDue = Math.max(0, invoice.totalAmount - invoice.amountPaid);

          async function transition(status: SupplierInvoiceStatus) {
            await setStatus.run({ invoiceId: invoice.id, status });
          }

          return (
            <div className="space-y-5">
              <PageHeader
                title={invoice.invoiceNumber}
                description={`${detail.supplierName} · ${formatDate(invoice.invoiceDate)}`}
                actions={
                  <>
                    <PermissionGate permission="invoice.match">
                      <Button variant="outline" disabled={runMatch.isPending} onClick={() => runMatch.run(invoice.id)}>
                        <RefreshCw className={runMatch.isPending ? "animate-spin" : undefined} />
                        Re-run Match
                      </Button>
                    </PermissionGate>
                    {balanceDue > 0 && (
                      <PermissionGate permission="invoice.update">
                        <Button variant="outline" onClick={() => setPaymentOpen(true)}>
                          <IndianRupee />
                          Record Payment
                        </Button>
                      </PermissionGate>
                    )}
                    {allowed.has("under_review") && (
                      <PermissionGate permission="invoice.approve">
                        <ConfirmButton
                          title="Send this invoice back for review?"
                          description={`${invoice.invoiceNumber} will move to under review.`}
                          confirmLabel="Send for Review"
                          onConfirm={() => transition("under_review")}
                        >
                          <Undo2 />
                          {invoice.status === "disputed" ? "Reopen for Review" : "Submit for Review"}
                        </ConfirmButton>
                      </PermissionGate>
                    )}
                    {allowed.has("approved") && (
                      <PermissionGate permission="invoice.approve">
                        <ConfirmButton
                          title="Approve this invoice?"
                          description={
                            invoice.matchStatus === "variance"
                              ? "The three-way match still shows differences — approving is recorded against them."
                              : "The invoice will be marked approved and ready for payment."
                          }
                          confirmLabel="Approve"
                          tone="success"
                          onConfirm={() => transition("approved")}
                        >
                          <Check />
                          Approve
                        </ConfirmButton>
                      </PermissionGate>
                    )}
                    {allowed.has("disputed") && (
                      <PermissionGate permission="invoice.dispute">
                        <Button
                          variant="outline"
                          className="text-destructive hover:text-destructive"
                          onClick={() => setDisputeOpen(true)}
                        >
                          <TriangleAlert />
                          Dispute
                        </Button>
                      </PermissionGate>
                    )}
                    {allowed.has("cancelled") && (
                      <PermissionGate permission="invoice.approve">
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

              {setStatus.error && !disputeOpen && !cancelOpen && <FormError message={setStatus.error} />}
              {runMatch.error && <FormError message={runMatch.error} />}

              <SectionCard title="Invoice Details">
                <DetailGrid className="p-4" columns={3}>
                  <DetailRow label="Supplier" value={detail.supplierName} />
                  <DetailRow label="Supplier GSTIN" value={invoice.supplierGstin} mono />
                  <DetailRow label="Status" value={<StatusBadge status={invoice.status} />} />
                  <DetailRow label="Invoice Date" value={formatDate(invoice.invoiceDate)} />
                  <DetailRow label="Due Date" value={invoice.dueDate ? formatDate(invoice.dueDate) : "—"} />
                  <DetailRow label="Invoice Type" value={invoice.invoiceType.replace(/_/g, " ")} />
                  <DetailRow
                    label="Purchase Order"
                    value={
                      invoice.purchaseOrderId ? (
                        <Link
                          href={`/procurement/purchase-orders/${invoice.purchaseOrderId}`}
                          className="font-mono text-primary hover:underline"
                        >
                          {detail.poNumber}
                        </Link>
                      ) : null
                    }
                  />
                  <DetailRow
                    label="Goods Receipt"
                    value={
                      invoice.goodsReceiptId ? (
                        <Link
                          href={`/goods-receipt/${invoice.goodsReceiptId}`}
                          className="font-mono text-primary hover:underline"
                        >
                          {detail.grnNumber}
                        </Link>
                      ) : null
                    }
                  />
                  <DetailRow label="E-way Bill" value={invoice.ewayBillNumber || null} mono />
                  <DetailRow label="IRN" value={invoice.irn || null} mono />
                  <DetailRow
                    label="Tax Treatment"
                    value={invoice.isInterState ? "IGST (inter-state)" : "CGST + SGST (intra-state)"}
                  />
                  {invoice.disputeReason && <DetailRow label="Dispute Reason" value={invoice.disputeReason} />}
                </DetailGrid>
              </SectionCard>

              <SectionCard
                title={`Items (${detail.items.length})`}
                description="What was billed, next to the PO rate and the quantity actually accepted at receiving"
              >
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead className="pl-4">Product</TableHead>
                        <TableHead className="text-right">Billed Qty</TableHead>
                        <TableHead className="text-right">Billed Rate</TableHead>
                        <TableHead className="text-right">PO Rate</TableHead>
                        <TableHead className="text-right">GRN Accepted</TableHead>
                        <TableHead className="text-right">Price Variance</TableHead>
                        <TableHead className="text-right">Qty Variance</TableHead>
                        <TableHead className="text-right">GST %</TableHead>
                        <TableHead className="pr-4 text-right">Line Total</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {detail.items.map((line) => {
                        const hasPriceVariance = !!line.priceVariancePct && Math.abs(line.priceVariancePct) > 0;
                        const hasQtyVariance = !!line.qtyVariance && Math.abs(line.qtyVariance) > 0;
                        const flagged = hasPriceVariance || hasQtyVariance;
                        return (
                          <TableRow key={line.id} className={cn(flagged && "bg-warning-subtle/40")}>
                            <TableCell className="pl-4">
                              <span className="block font-medium text-foreground">{line.productName}</span>
                              <span className="block text-caption text-muted-foreground">{line.sku}</span>
                            </TableCell>
                            <TableCell className="text-right tabular">
                              {formatQuantity(line.quantity, 2)} {line.uomCode}
                            </TableCell>
                            <TableCell className="text-right tabular">{formatCurrency(line.unitPrice)}</TableCell>
                            <TableCell className="text-right text-muted-foreground tabular">
                              {line.poUnitPriceSnapshot != null ? formatCurrency(line.poUnitPriceSnapshot) : "—"}
                            </TableCell>
                            <TableCell className="text-right text-muted-foreground tabular">
                              {line.grnAcceptedQuantity != null ? formatQuantity(line.grnAcceptedQuantity, 2) : "—"}
                            </TableCell>
                            <TableCell
                              className={cn(
                                "text-right tabular",
                                hasPriceVariance ? "font-medium text-warning-subtle-foreground" : "text-muted-foreground",
                              )}
                            >
                              {line.priceVariancePct != null ? formatVariancePct(line.priceVariancePct) : "—"}
                            </TableCell>
                            <TableCell
                              className={cn(
                                "text-right tabular",
                                hasQtyVariance ? "font-medium text-warning-subtle-foreground" : "text-muted-foreground",
                              )}
                            >
                              {line.qtyVariance != null
                                ? `${line.qtyVariance > 0 ? "+" : ""}${formatQuantity(line.qtyVariance, 2)}`
                                : "—"}
                            </TableCell>
                            <TableCell className="text-right tabular">{line.gstRate}%</TableCell>
                            <TableCell className="pr-4 text-right font-medium tabular">
                              {formatCurrency(line.lineTotal)}
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              </SectionCard>

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
                <div className="lg:col-span-5">
                  <SectionCard title="Totals">
                    <div className="p-4">
                      <TaxSummary money={invoice} taxRows={detail.taxRows} />
                      {invoice.amountPaid > 0 && (
                        <div className="mt-3 space-y-1 border-t border-border pt-3 text-[13px]">
                          <div className="flex items-center justify-between">
                            <span className="text-muted-foreground">Paid</span>
                            <span className="font-medium text-success-subtle-foreground tabular">
                              {formatCurrency(invoice.amountPaid)}
                            </span>
                          </div>
                          <div className="flex items-center justify-between">
                            <span className="text-muted-foreground">Balance Due</span>
                            <span className="font-medium text-foreground tabular">
                              {formatCurrency(balanceDue)}
                            </span>
                          </div>
                        </div>
                      )}
                    </div>
                  </SectionCard>
                </div>

                <div className="lg:col-span-7">
                  <ThreeWayMatchPanel
                    matchStatus={detail.match.matchStatus}
                    summary={detail.match.summary}
                    variances={detail.match.variances}
                  />
                </div>
              </div>

              <AuditTrail entityType="supplier_invoice" entityId={invoice.id} />

              {/* Dispute dialog — the API refuses a dispute without a reason. */}
              <Dialog
                open={disputeOpen}
                onOpenChange={(open) => {
                  setDisputeOpen(open);
                  if (!open) {
                    setDisputeReason("");
                    setStatus.reset();
                  }
                }}
              >
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Dispute this invoice?</DialogTitle>
                    <DialogDescription>
                      Say what is being disputed so the supplier can be told. {invoice.invoiceNumber} moves to
                      disputed until it is resolved.
                    </DialogDescription>
                  </DialogHeader>
                  <DialogBody>
                    <div className="space-y-1.5">
                      <Label htmlFor="invoice-dispute-reason">Reason</Label>
                      <Textarea
                        id="invoice-dispute-reason"
                        value={disputeReason}
                        onChange={(e) => setDisputeReason(e.target.value)}
                        placeholder="What is wrong with this invoice?"
                      />
                    </div>
                    <FormError message={setStatus.error} className="mt-3" />
                  </DialogBody>
                  <DialogFooter>
                    <Button variant="outline" disabled={setStatus.isPending} onClick={() => setDisputeOpen(false)}>
                      Keep Invoice
                    </Button>
                    <Button
                      variant="destructive"
                      disabled={setStatus.isPending || !disputeReason.trim()}
                      onClick={async () => {
                        const result = await setStatus.run({
                          invoiceId: invoice.id,
                          status: "disputed",
                          reason: disputeReason.trim(),
                        });
                        if (result) {
                          setDisputeOpen(false);
                          setDisputeReason("");
                        }
                      }}
                    >
                      Dispute Invoice
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>

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
                    <DialogTitle>Cancel this invoice?</DialogTitle>
                    <DialogDescription>
                      {invoice.invoiceNumber} will be marked cancelled. This can&apos;t be undone.
                    </DialogDescription>
                  </DialogHeader>
                  <DialogBody>
                    <div className="space-y-1.5">
                      <Label htmlFor="invoice-cancel-reason">Reason (optional)</Label>
                      <Textarea
                        id="invoice-cancel-reason"
                        value={cancelReason}
                        onChange={(e) => setCancelReason(e.target.value)}
                        placeholder="Why is this invoice being cancelled?"
                      />
                    </div>
                    <FormError message={setStatus.error} className="mt-3" />
                  </DialogBody>
                  <DialogFooter>
                    <Button variant="outline" disabled={setStatus.isPending} onClick={() => setCancelOpen(false)}>
                      Keep Invoice
                    </Button>
                    <Button
                      variant="destructive"
                      disabled={setStatus.isPending}
                      onClick={async () => {
                        const result = await setStatus.run({
                          invoiceId: invoice.id,
                          status: "cancelled",
                          reason: cancelReason.trim() || undefined,
                        });
                        if (result) {
                          setCancelOpen(false);
                          setCancelReason("");
                        }
                      }}
                    >
                      Cancel Invoice
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>

              {/* Record payment — the API refuses paying more than the invoice total. */}
              <Dialog
                open={paymentOpen}
                onOpenChange={(open) => {
                  setPaymentOpen(open);
                  if (!open) {
                    setPaymentAmount("");
                    recordPayment.reset();
                  }
                }}
              >
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Record a payment</DialogTitle>
                    <DialogDescription>
                      {formatCurrency(balanceDue)} is still due on {invoice.invoiceNumber}.
                    </DialogDescription>
                  </DialogHeader>
                  <DialogBody>
                    <div className="space-y-1.5">
                      <Label htmlFor="invoice-payment-amount">Amount</Label>
                      <Input
                        id="invoice-payment-amount"
                        type="number"
                        min={0}
                        value={paymentAmount}
                        onChange={(e) => setPaymentAmount(e.target.value)}
                        className="tabular"
                      />
                    </div>
                    <FormError message={recordPayment.error} className="mt-3" />
                  </DialogBody>
                  <DialogFooter>
                    <Button variant="outline" disabled={recordPayment.isPending} onClick={() => setPaymentOpen(false)}>
                      Cancel
                    </Button>
                    <Button
                      disabled={recordPayment.isPending || !Number(paymentAmount)}
                      onClick={() => recordPayment.run({ invoiceId: invoice.id, amount: Number(paymentAmount) })}
                    >
                      <Send />
                      Record Payment
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

/**
 * The three-way match: the invoice checked against both the purchase order
 * and the goods actually accepted at receiving. This panel is read straight
 * from `ThreeWayMatch` — it never recomputes a variance itself.
 */
function ThreeWayMatchPanel({
  matchStatus,
  summary,
  variances,
}: {
  matchStatus: string;
  summary: { poTotal: number; grnValue: number; invoiceTotal: number };
  variances: DocumentVariance[];
}) {
  return (
    <SectionCard
      title="Three-Way Match"
      description="The invoice is checked against both the purchase order and the goods actually accepted"
      action={<StatusBadge status={matchStatus} />}
      className={matchStatus === "variance" ? "border-destructive/35" : undefined}
    >
      <div className="space-y-4 p-4">
        <div className="grid grid-cols-3 gap-3">
          <MatchFigure label="Purchase Order" value={summary.poTotal} />
          <MatchFigure label="Goods Received" value={summary.grnValue} />
          <MatchFigure label="Invoice" value={summary.invoiceTotal} emphasize />
        </div>

        {variances.length > 0 ? (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="pl-3">Variance</TableHead>
                  <TableHead className="text-right">Base</TableHead>
                  <TableHead className="text-right">Compare</TableHead>
                  <TableHead className="text-right">Difference</TableHead>
                  <TableHead className="text-right">%</TableHead>
                  <TableHead className="pr-3">Severity</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {variances.map((v) => {
                  const isQty = v.varianceType === "quantity";
                  const fmt = (n: number) => (isQty ? formatQuantity(n, 2) : formatCurrency(n));
                  return (
                    <TableRow key={v.id}>
                      <TableCell className="pl-3 max-w-[260px] text-[12.5px] text-foreground">{v.label}</TableCell>
                      <TableCell className="text-right text-muted-foreground tabular">{fmt(v.baseValue)}</TableCell>
                      <TableCell className="text-right text-muted-foreground tabular">{fmt(v.compareValue)}</TableCell>
                      <TableCell className="text-right font-medium tabular">{fmt(v.difference)}</TableCell>
                      <TableCell className="text-right tabular">{formatVariancePct(v.differencePct)}</TableCell>
                      <TableCell className="pr-3">
                        <SeverityBadge severity={v.severity} />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="text-[13px] text-muted-foreground">
            No differences found — the invoice agrees with the PO and the goods received.
          </p>
        )}
      </div>
    </SectionCard>
  );
}

function MatchFigure({ label, value, emphasize }: { label: string; value: number; emphasize?: boolean }) {
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-3 py-2.5">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-0.5 tabular",
          emphasize ? "text-[16px] font-semibold text-foreground" : "text-[14px] font-medium text-foreground",
        )}
      >
        {formatCurrency(value)}
      </p>
    </div>
  );
}
