"use client";

import * as React from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Ban,
  Check,
  CornerUpLeft,
  Pencil,
  Undo2,
  X,
} from "lucide-react";

import { AsyncBoundary, FormError, LoadingCard } from "@/components/common/async-state";
import { AuditTrail } from "@/components/common/audit-trail";
import { AttachmentsCard } from "@/components/documents/attachments";
import { ConfirmButton } from "@/components/common/confirm-dialog";
import { DetailGrid, DetailRow } from "@/components/common/detail-row";
import { PageHeader } from "@/components/common/page-header";
import { PermissionGate } from "@/components/common/permission-gate";
import { PrintButton } from "@/components/common/print-button";
import { PrintHeader } from "@/components/common/print-header";
import { SectionCard } from "@/components/common/section-card";
import { SeverityBadge, StatusBadge } from "@/components/common/status-badge";
import { Badge } from "@/components/ui/badge";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useCompanySettings } from "@/hooks/use-admin";
import {
  useCancelDraftGoodsReceipt,
  useConfirmGoodsReceipt,
  useGoodsReceipt,
  useReturnableLines,
  useReverseGoodsReceipt,
} from "@/hooks/use-receiving";
import { GRN_ISSUE_LABELS } from "@/lib/api/receiving.api";
import { formatCurrency, formatDate, formatDateTime, formatQuantity } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { GoodsReceiptStatus, Id } from "@/types";

/**
 * Goods Receipt detail.
 *
 * The correction that matters here (C1): confirming a GRN is not a status
 * flip. It posts inventory, advances the PO, records variances and raises
 * alerts, and this screen shows every one of those effects — both as
 * standing facts on the record (`postedQuantity` per line) and, right after
 * confirming, as the full `GrnConfirmationResult` the API returned.
 */
export function GrnDetailScreen({ id }: { id: Id }) {
  const state = useGoodsReceipt(id);
  const returnableState = useReturnableLines(id);
  // Set by the GRN form when some chosen files failed to upload after the
  // receipt itself was saved — read once, so a refresh does not repeat it.
  const [attachFailed] = React.useState(() =>
    typeof window === "undefined" ? 0 : Number(new URLSearchParams(window.location.search).get("attach_failed") ?? 0),
  );
  const settingsState = useCompanySettings();

  // The confirmation result panel covers the immediate feedback, but the
  // header's own status badge (still reading `state`) would otherwise stay
  // on "Draft" until a manual reload — same fix as `reverse` below.
  const confirm = useConfirmGoodsReceipt(() => state.refresh());
  // Reversing stays on this same page — without refreshing, the screen
  // would keep showing the pre-reversal state after a successful mutation.
  // Same fix as po-detail-screen.tsx's `setStatus` above.
  const reverse = useReverseGoodsReceipt(() => {
    setReverseOpen(false);
    state.refresh();
  });
  const cancelDraft = useCancelDraftGoodsReceipt(() => {
    setCancelOpen(false);
    state.refresh();
  });

  const [reverseOpen, setReverseOpen] = React.useState(false);
  const [reverseReason, setReverseReason] = React.useState("");
  const [cancelOpen, setCancelOpen] = React.useState(false);
  const [cancelReason, setCancelReason] = React.useState("");

  return (
    <div className="space-y-5">
      <Button variant="ghost" size="sm" asChild className="-ml-2 text-muted-foreground print:hidden">
        <Link href="/goods-receipt">
          <ArrowLeft />
          All Goods Receipts
        </Link>
      </Button>

      <AsyncBoundary state={state} loading={<LoadingCard />}>
        {(detail) => {
          const grn = detail.goodsReceipt;
          const allowed = new Set<GoodsReceiptStatus>(detail.allowedActions);
          const canConfirm = allowed.has("received") || allowed.has("partially_received");
          const canReverse = allowed.has("reversed");
          const canCancel = allowed.has("cancelled");
          const canReturn =
            (grn.status === "received" || grn.status === "partially_received") &&
            (returnableState.data?.length ?? 0) > 0;

          return (
            <div className="space-y-5">
              <PageHeader
                title={grn.grnNumber}
                description={`${detail.supplierName} · ${formatDate(grn.grnDate)}`}
                actions={
                  <>
                    <PrintButton />
                    {canReturn && (
                      <PermissionGate permission="return.create">
                        <Button variant="outline" asChild>
                          <Link href={`/purchase-returns/new?goodsReceiptId=${grn.id}`}>
                            <CornerUpLeft />
                            Raise Return
                          </Link>
                        </Button>
                      </PermissionGate>
                    )}
                    {canConfirm && (
                      <PermissionGate permission="grn.confirm">
                        <ConfirmButton
                          title="Confirm this goods receipt?"
                          description="This posts an inventory transaction for every accepted line, advances the linked purchase order, and cannot be edited afterward."
                          confirmLabel="Confirm Receipt"
                          tone="success"
                          onConfirm={async () => {
                            await confirm.run(grn.id);
                          }}
                        >
                          <Check />
                          Confirm Receipt
                        </ConfirmButton>
                      </PermissionGate>
                    )}
                    {grn.status === "draft" && (
                      <PermissionGate permission="grn.update">
                        <Button variant="outline" asChild>
                          <Link href={`/goods-receipt/${grn.id}/edit`}>
                            <Pencil />
                            Edit Draft
                          </Link>
                        </Button>
                      </PermissionGate>
                    )}
                    {canCancel && (
                      <PermissionGate permission="grn.update">
                        <Button
                          variant="outline"
                          className="text-destructive hover:text-destructive"
                          onClick={() => setCancelOpen(true)}
                        >
                          <Ban />
                          Cancel Draft
                        </Button>
                      </PermissionGate>
                    )}
                    {canReverse && (
                      <PermissionGate permission="grn.reverse">
                        <Button variant="outline" onClick={() => setReverseOpen(true)}>
                          <Undo2 />
                          Reverse
                        </Button>
                      </PermissionGate>
                    )}
                  </>
                }
              />

              {confirm.error && <FormError message={confirm.error} />}

              {confirm.data && (
                <SectionCard
                  title="Receipt confirmed — here's what happened"
                  description="Every posting this confirmation made, straight from the API response"
                  action={
                    <Button variant="ghost" size="icon-sm" aria-label="Dismiss" onClick={() => confirm.reset()}>
                      <X />
                    </Button>
                  }
                  className="border-success/35"
                >
                  <div className="space-y-4 p-4">
                    <div>
                      <p className="mb-2 text-[12px] font-semibold tracking-wide text-muted-foreground uppercase">
                        Inventory postings
                      </p>
                      <div className="overflow-hidden rounded-lg border border-border">
                        <Table>
                          <TableHeader>
                            <TableRow className="hover:bg-transparent">
                              <TableHead className="pl-3">SKU</TableHead>
                              <TableHead className="text-right">Quantity Posted</TableHead>
                              <TableHead className="pr-3 text-right">Balance After</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {confirm.data.postings.map((p) => (
                              <TableRow key={p.goodsReceiptItemId}>
                                <TableCell className="pl-3 font-mono text-[12.5px]">{p.sku}</TableCell>
                                <TableCell className="text-right font-medium text-success-subtle-foreground tabular">
                                  +{formatQuantity(p.quantity, 2)}
                                </TableCell>
                                <TableCell className="pr-3 text-right font-medium tabular">
                                  {formatQuantity(p.balanceAfter, 2)}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    </div>

                    {confirm.data.purchaseOrder && (
                      <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3.5 py-2.5">
                        <span className="text-[13px] text-foreground">
                          Purchase order{" "}
                          <Link
                            href={`/procurement/purchase-orders/${confirm.data.purchaseOrder.id}`}
                            className="font-mono font-medium text-primary hover:underline"
                          >
                            {confirm.data.purchaseOrder.poNumber}
                          </Link>{" "}
                          is now {confirm.data.purchaseOrder.receivedPct}% received
                        </span>
                        <StatusBadge status={confirm.data.purchaseOrder.status} />
                      </div>
                    )}

                    {confirm.data.variances.length > 0 && (
                      <div>
                        <p className="mb-2 text-[12px] font-semibold tracking-wide text-muted-foreground uppercase">
                          Variances recorded against the PO
                        </p>
                        <ul className="divide-y divide-border rounded-lg border border-border">
                          {confirm.data.variances.map((v) => (
                            <li key={v.id} className="flex items-center justify-between gap-3 px-3.5 py-2">
                              <div className="flex items-center gap-2">
                                <SeverityBadge severity={v.severity} />
                                <span className="text-[13px] text-foreground">{v.label}</span>
                              </div>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    <p className="text-caption text-muted-foreground">
                      {confirm.data.alertIds.length > 0
                        ? `${confirm.data.alertIds.length} alert${confirm.data.alertIds.length === 1 ? "" : "s"} raised for the discrepancies above.`
                        : "No discrepancies — nothing else needed alerting."}
                    </p>
                  </div>
                </SectionCard>
              )}

              <PrintHeader
                company={settingsState.data?.company.name ?? ""}
                gstin={settingsState.data?.company.gstin}
                address={settingsState.data?.company.addressLine1}
                email={settingsState.data?.company.email}
                phone={settingsState.data?.company.phone}
                docLabel={`Goods Receipt Note — ${grn.grnNumber} (internal document)`}
              />

              {detail.reversal && (
                <div className="flex items-start gap-2.5 rounded-lg border border-warning/30 bg-warning-subtle/55 px-3.5 py-2.5">
                  <Undo2 className="mt-0.5 size-4 shrink-0 text-warning-subtle-foreground" />
                  <p className="text-[13px] text-warning-subtle-foreground">
                    This receipt was reversed on {formatDate(detail.reversal.reversedAt)}
                    {detail.reversal.reversedByName ? ` by ${detail.reversal.reversedByName}` : ""} — the stock it
                    posted has been taken back out.
                    {detail.reversal.reason && <span className="block">Reason: {detail.reversal.reason}</span>}
                  </p>
                </div>
              )}

              <SectionCard title="Receipt Details">
                <DetailGrid className="p-4" columns={3}>
                  <DetailRow label="Supplier" value={detail.supplierName} />
                  <DetailRow label="Status" value={<StatusBadge status={grn.status} />} />
                  <DetailRow label="GRN Date" value={formatDate(grn.grnDate)} />
                  <DetailRow label="Godown" value={detail.godownName} />
                  <DetailRow
                    label="Related PO"
                    value={
                      grn.purchaseOrderId ? (
                        <Link
                          href={`/procurement/purchase-orders/${grn.purchaseOrderId}`}
                          className="font-mono text-primary hover:underline"
                        >
                          {detail.poNumber}
                        </Link>
                      ) : null
                    }
                  />
                  <DetailRow label="Received By" value={detail.receivedByName} />
                  <DetailRow label="Vehicle Number" value={grn.vehicleNumber || null} />
                  <DetailRow label="Transporter" value={grn.transporterName || null} />
                  <DetailRow label="LR Number" value={grn.lrNumber || null} />
                  <DetailRow label="E-way Bill" value={grn.ewayBillNumber || null} mono />
                  <DetailRow label="Supplier Challan No." value={grn.supplierChallanNumber || null} mono />
                  <DetailRow
                    label="Supplier Challan Date"
                    value={grn.supplierChallanDate ? formatDate(grn.supplierChallanDate) : null}
                  />
                  {grn.remarks && <DetailRow label="Remarks" value={grn.remarks} />}
                  <DetailRow label="Created" value={formatDateTime(grn.createdAt)} />
                  <DetailRow label="Last Updated" value={formatDateTime(grn.updatedAt)} />
                  {grn.status === "cancelled" && (
                    <DetailRow
                      label="Cancelled"
                      value={[
                        grn.cancelledAt ? formatDateTime(grn.cancelledAt) : null,
                        grn.cancelledByName ? `by ${grn.cancelledByName}` : null,
                      ].filter(Boolean).join(" ") || "—"}
                    />
                  )}
                  {grn.status === "cancelled" && grn.cancellationReason && (
                    <DetailRow label="Cancellation Reason" value={grn.cancellationReason} />
                  )}
                </DetailGrid>
              </SectionCard>

              <SectionCard title={`Items (${detail.items.length})`}>
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="pl-4">Product</TableHead>
                      <TableHead className="text-right">Ordered</TableHead>
                      <TableHead className="text-right">Received</TableHead>
                      <TableHead className="text-right">Accepted</TableHead>
                      <TableHead className="text-right">Rejected</TableHead>
                      <TableHead>Issue</TableHead>
                      <TableHead>Batch</TableHead>
                      <TableHead className="text-right">Posted Qty</TableHead>
                      <TableHead className="pr-4">Remarks</TableHead>
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
                          {formatQuantity(line.orderedQuantity, 2)} {line.uomCode}
                        </TableCell>
                        <TableCell className="text-right tabular">
                          {formatQuantity(line.receivedQuantity, 2)} {line.uomCode}
                        </TableCell>
                        <TableCell className="text-right font-medium tabular">
                          {formatQuantity(line.acceptedQuantity, 2)} {line.uomCode}
                        </TableCell>
                        <TableCell
                          className={cn(
                            "text-right tabular",
                            line.rejectedQuantity > 0 ? "font-medium text-destructive" : "text-muted-foreground",
                          )}
                        >
                          {formatQuantity(line.rejectedQuantity, 2)}
                        </TableCell>
                        <TableCell>
                          {line.issueType !== "none" ? (
                            <Badge variant={line.issueType === "short" || line.issueType === "excess" ? "warning" : "destructive"}>
                              {GRN_ISSUE_LABELS[line.issueType]}
                            </Badge>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                          {line.rejectionReason && (
                            <span className="mt-1 block text-caption text-muted-foreground">{line.rejectionReason}</span>
                          )}
                        </TableCell>
                        <TableCell className="font-mono text-[12px] text-muted-foreground">
                          {line.batchNumber || "—"}
                        </TableCell>
                        <TableCell className="text-right tabular">
                          {line.postedQuantity !== null ? (
                            <span className="font-medium text-success-subtle-foreground">
                              {formatQuantity(line.postedQuantity, 2)}
                            </span>
                          ) : (
                            <span className="text-muted-foreground">Not posted</span>
                          )}
                        </TableCell>
                        <TableCell className="pr-4 text-caption text-muted-foreground">
                          {line.remarks || "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </SectionCard>

              {detail.variances.length > 0 && (
                <SectionCard title="Variances" description="Differences flagged against the purchase order">
                  <ul className="divide-y divide-border">
                    {detail.variances.map((v) => (
                      <li key={v.id} className="flex items-start justify-between gap-3 px-4 py-3">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <SeverityBadge severity={v.severity} />
                            <span className="text-[13px] font-medium text-foreground">{v.label}</span>
                          </div>
                          <p className="mt-1 text-caption text-muted-foreground tabular">
                            {formatQuantity(v.baseValue, 2)} → {formatQuantity(v.compareValue, 2)} (
                            {v.differencePct > 0 ? "+" : ""}
                            {v.differencePct.toFixed(1)}%)
                          </p>
                        </div>
                        <StatusBadge status={v.status} />
                      </li>
                    ))}
                  </ul>
                </SectionCard>
              )}

              {detail.returns.length > 0 && (
                <SectionCard title="Purchase Returns" description="Returns raised against this receipt">
                  <ul className="divide-y divide-border">
                    {detail.returns.map((r) => (
                      <li key={r.id}>
                        <Link
                          href={`/purchase-returns/${r.id}`}
                          className="flex items-center justify-between px-4 py-2.5 hover:bg-muted/50"
                        >
                          <span className="font-mono text-[12.5px] text-foreground">{r.returnNumber}</span>
                          <span className="flex items-center gap-2">
                            <span className="text-caption text-muted-foreground tabular">
                              {formatCurrency(r.totalAmount)}
                            </span>
                            <StatusBadge status={r.status} />
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </SectionCard>
              )}

              {detail.postings.length > 0 && (
                <SectionCard
                  title="Stock Postings"
                  description="The ledger rows this receipt produced — a reversal shows up here as the offsetting rows, not as a deletion"
                >
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead className="pl-4">Posted</TableHead>
                        <TableHead>Reference</TableHead>
                        <TableHead>SKU</TableHead>
                        <TableHead>Godown</TableHead>
                        <TableHead className="text-right">Quantity</TableHead>
                        <TableHead className="pr-4 text-right">Balance now</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {detail.postings.map((p) => (
                        <TableRow key={p.inventoryTransactionId}>
                          <TableCell className="pl-4 text-muted-foreground">{formatDate(p.postedAt)}</TableCell>
                          <TableCell className="font-mono text-[12.5px] text-muted-foreground">
                            {p.txnNumber}
                            {p.reversesTxnId && (
                              <Badge variant="warning" className="ml-2">
                                Reversal
                              </Badge>
                            )}
                          </TableCell>
                          <TableCell className="font-mono text-[12.5px] text-foreground">{p.sku}</TableCell>
                          <TableCell className="text-muted-foreground">{p.godownName}</TableCell>
                          <TableCell
                            className={cn(
                              "text-right font-medium tabular",
                              p.quantity < 0 ? "text-destructive" : "text-success-subtle-foreground",
                            )}
                          >
                            {p.quantity > 0 ? "+" : ""}
                            {formatQuantity(p.quantity, 2)}
                          </TableCell>
                          <TableCell className="pr-4 text-right text-muted-foreground tabular">
                            {p.balanceNow === null ? "—" : formatQuantity(p.balanceNow, 2)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </SectionCard>
              )}

              <AttachmentsCard
                linkedType="goods_receipt"
                linkedId={grn.id}
                editPermissions={["grn.create", "grn.update"]}
                description="Delivery challan, invoice or photos"
                dropTitle="Upload delivery challan, invoice or any document"
                notice={
                  attachFailed > 0
                    ? `${attachFailed} file${attachFailed === 1 ? "" : "s"} could not be attached when this receipt was saved. Add ${attachFailed === 1 ? "it" : "them"} again below.`
                    : null
                }
              />

              <AuditTrail entityType="goods_receipt" entityId={grn.id} />

              <Dialog
                open={cancelOpen}
                onOpenChange={(open) => {
                  setCancelOpen(open);
                  if (!open) {
                    setCancelReason("");
                    cancelDraft.reset();
                  }
                }}
              >
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Cancel this draft receipt?</DialogTitle>
                    <DialogDescription>
                      {grn.grnNumber} hasn&apos;t been confirmed, so no inventory has been posted for it yet. This
                      can&apos;t be undone.
                    </DialogDescription>
                  </DialogHeader>
                  <DialogBody>
                    <div className="space-y-1.5">
                      <Label htmlFor="grn-cancel-reason">Reason</Label>
                      <Textarea
                        id="grn-cancel-reason"
                        value={cancelReason}
                        onChange={(e) => setCancelReason(e.target.value)}
                        placeholder="Why is this receipt being cancelled?"
                      />
                    </div>
                    <FormError message={cancelDraft.error} className="mt-3" />
                  </DialogBody>
                  <DialogFooter>
                    <Button variant="outline" disabled={cancelDraft.isPending} onClick={() => setCancelOpen(false)}>
                      Keep Draft
                    </Button>
                    <Button
                      variant="destructive"
                      disabled={cancelDraft.isPending || !cancelReason.trim()}
                      onClick={() => cancelDraft.run({ goodsReceiptId: grn.id, reason: cancelReason.trim() })}
                    >
                      Cancel Draft
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>

              <Dialog
                open={reverseOpen}
                onOpenChange={(open) => {
                  setReverseOpen(open);
                  if (!open) {
                    setReverseReason("");
                    reverse.reset();
                  }
                }}
              >
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Reverse this goods receipt?</DialogTitle>
                    <DialogDescription>
                      This raises a new receipt that posts the opposite inventory movements and points back at{" "}
                      {grn.grnNumber}. The original record and its history stay as they are.
                    </DialogDescription>
                  </DialogHeader>
                  <DialogBody>
                    <div className="space-y-1.5">
                      <Label htmlFor="grn-reverse-reason">Reason</Label>
                      <Textarea
                        id="grn-reverse-reason"
                        value={reverseReason}
                        onChange={(e) => setReverseReason(e.target.value)}
                        placeholder="Why is this receipt being reversed?"
                      />
                    </div>
                    <FormError message={reverse.error} className="mt-3" />
                  </DialogBody>
                  <DialogFooter>
                    <Button variant="outline" disabled={reverse.isPending} onClick={() => setReverseOpen(false)}>
                      Keep Receipt
                    </Button>
                    <Button
                      variant="destructive"
                      disabled={reverse.isPending || !reverseReason.trim()}
                      onClick={() => reverse.run({ goodsReceiptId: grn.id, reason: reverseReason.trim() })}
                    >
                      Reverse Receipt
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
