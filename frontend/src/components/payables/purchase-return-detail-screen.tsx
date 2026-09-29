"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, Ban, Check, PackageX, Send } from "lucide-react";

import { AsyncBoundary, FormError, LoadingCard } from "@/components/common/async-state";
import { AuditTrail } from "@/components/common/audit-trail";
import { ConfirmButton } from "@/components/common/confirm-dialog";
import { DetailGrid, DetailRow } from "@/components/common/detail-row";
import { PageHeader } from "@/components/common/page-header";
import { PermissionGate } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { StatusBadge } from "@/components/common/status-badge";
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
import { RETURN_REASON_LABELS } from "@/components/payables/purchase-return-list-screen";
import { usePurchaseReturn, useSetPurchaseReturnStatus } from "@/hooks/use-invoices";
import { formatCurrency, formatDate, formatQuantity } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Id, PurchaseReturnStatus } from "@/types";

/**
 * Purchase return detail.
 *
 * The correction this screen exists to show (I2): a confirmed return does not
 * just sit as a record — it posts a negative inventory transaction. Every
 * line's `postedQuantity` is the proof that the stock actually left; a line
 * shows "Not posted" only while the return is still a draft.
 */
export function PurchaseReturnDetailScreen({ id }: { id: Id }) {
  const state = usePurchaseReturn(id);
  const setStatus = useSetPurchaseReturnStatus();

  const [cancelOpen, setCancelOpen] = React.useState(false);
  const [cancelReason, setCancelReason] = React.useState("");
  const [creditOpen, setCreditOpen] = React.useState(false);
  const [debitNoteNumber, setDebitNoteNumber] = React.useState("");

  return (
    <div className="space-y-5">
      <Button variant="ghost" size="sm" asChild className="-ml-2 text-muted-foreground">
        <Link href="/purchase-returns">
          <ArrowLeft />
          All Purchase Returns
        </Link>
      </Button>

      <AsyncBoundary state={state} loading={<LoadingCard />}>
        {(detail) => {
          const ret = detail.purchaseReturn;
          const allowed = new Set<PurchaseReturnStatus>(detail.allowedActions);

          async function transition(status: PurchaseReturnStatus) {
            await setStatus.run({ returnId: ret.id, status });
          }

          return (
            <div className="space-y-5">
              <PageHeader
                title={ret.returnNumber}
                description={`${detail.supplierName} · ${formatDate(ret.returnDate)}`}
                actions={
                  <>
                    {allowed.has("sent") && (
                      <PermissionGate permission="return.confirm">
                        <ConfirmButton
                          title="Send this return to the supplier?"
                          description="This posts the negative inventory transaction for every accepted line and removes the goods from stock."
                          confirmLabel="Send Return"
                          tone="success"
                          onConfirm={() => transition("sent")}
                        >
                          <Send />
                          Send Return
                        </ConfirmButton>
                      </PermissionGate>
                    )}
                    {allowed.has("accepted") && (
                      <PermissionGate permission="return.confirm">
                        <ConfirmButton
                          title="Mark this return accepted?"
                          description={`${detail.supplierName} has acknowledged and accepted ${ret.returnNumber}.`}
                          confirmLabel="Mark Accepted"
                          tone="success"
                          onConfirm={() => transition("accepted")}
                        >
                          <Check />
                          Mark Accepted
                        </ConfirmButton>
                      </PermissionGate>
                    )}
                    {allowed.has("credited") && (
                      <PermissionGate permission="return.confirm">
                        <Button onClick={() => setCreditOpen(true)}>
                          <Check />
                          Mark Credited
                        </Button>
                      </PermissionGate>
                    )}
                    {allowed.has("cancelled") && (
                      <PermissionGate permission="return.confirm">
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

              {setStatus.error && !cancelOpen && !creditOpen && <FormError message={setStatus.error} />}

              <SectionCard title="Return Details">
                <DetailGrid className="p-4" columns={3}>
                  <DetailRow label="Supplier" value={detail.supplierName} />
                  <DetailRow label="Status" value={<StatusBadge status={ret.status} />} />
                  <DetailRow label="Return Date" value={formatDate(ret.returnDate)} />
                  <DetailRow label="Godown" value={detail.godownName} />
                  <DetailRow
                    label="Goods Receipt"
                    value={
                      <Link href={`/goods-receipt/${ret.goodsReceiptId}`} className="font-mono text-primary hover:underline">
                        {detail.grnNumber}
                      </Link>
                    }
                  />
                  <DetailRow
                    label="Purchase Order"
                    value={
                      ret.purchaseOrderId ? (
                        <Link
                          href={`/procurement/purchase-orders/${ret.purchaseOrderId}`}
                          className="font-mono text-primary hover:underline"
                        >
                          {detail.poNumber}
                        </Link>
                      ) : null
                    }
                  />
                  <DetailRow label="Reason" value={RETURN_REASON_LABELS[ret.reason]} />
                  <DetailRow label="Debit Note Number" value={ret.debitNoteNumber || null} mono />
                  <DetailRow label="E-way Bill" value={ret.ewayBillNumber || null} mono />
                  {ret.remarks && <DetailRow label="Remarks" value={ret.remarks} />}
                </DetailGrid>
              </SectionCard>

              <SectionCard title={`Items (${detail.items.length})`}>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead className="pl-4">Product</TableHead>
                        <TableHead className="text-right">Quantity</TableHead>
                        <TableHead className="text-right">Rate</TableHead>
                        <TableHead className="text-right">Line Total</TableHead>
                        <TableHead>Reason</TableHead>
                        <TableHead className="pr-4 text-right">Posted Qty</TableHead>
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
                            {formatQuantity(line.quantity, 2)} {line.uomCode}
                          </TableCell>
                          <TableCell className="text-right tabular">{formatCurrency(line.unitPrice)}</TableCell>
                          <TableCell className="text-right font-medium tabular">
                            {formatCurrency(line.lineTotal)}
                          </TableCell>
                          <TableCell className="text-muted-foreground">
                            {RETURN_REASON_LABELS[line.reason]}
                            {line.remarks && (
                              <span className="block text-caption text-muted-foreground">{line.remarks}</span>
                            )}
                          </TableCell>
                          <TableCell className="pr-4 text-right tabular">
                            {line.postedQuantity !== null ? (
                              <span className="font-medium text-success-subtle-foreground">
                                −{formatQuantity(line.postedQuantity, 2)}
                              </span>
                            ) : (
                              <span className="text-muted-foreground">Not posted</span>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </SectionCard>

              <div
                className={cn(
                  "flex items-center gap-2.5 rounded-lg border px-3.5 py-2.5 text-[13px]",
                  detail.items.some((l) => l.postedQuantity !== null)
                    ? "border-success/30 bg-success-subtle/55 text-success-subtle-foreground"
                    : "border-border bg-muted/40 text-muted-foreground",
                )}
              >
                <PackageX className="size-4 shrink-0" />
                {detail.items.some((l) => l.postedQuantity !== null)
                  ? "Stock has been posted out for this return — the negative transaction is on the ledger."
                  : "No inventory has been posted yet. Nothing leaves stock until the return is sent."}
              </div>

              <AuditTrail entityType="purchase_return" entityId={ret.id} />

              <Dialog
                open={cancelOpen}
                onOpenChange={(open) => {
                  setCancelOpen(open);
                  if (!open) setStatus.reset();
                }}
              >
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Cancel this return?</DialogTitle>
                    <DialogDescription>
                      {ret.returnNumber} will be marked cancelled. This can&apos;t be undone.
                    </DialogDescription>
                  </DialogHeader>
                  <DialogBody>
                    <div className="space-y-1.5">
                      <Label htmlFor="return-cancel-reason">Reason</Label>
                      <Textarea
                        id="return-cancel-reason"
                        value={cancelReason}
                        onChange={(e) => setCancelReason(e.target.value)}
                        placeholder="Why is this return being cancelled?"
                      />
                    </div>
                    <FormError message={setStatus.error} className="mt-3" />
                  </DialogBody>
                  <DialogFooter>
                    <Button variant="outline" disabled={setStatus.isPending} onClick={() => setCancelOpen(false)}>
                      Keep Return
                    </Button>
                    <Button
                      variant="destructive"
                      disabled={setStatus.isPending}
                      onClick={async () => {
                        const result = await setStatus.run({ returnId: ret.id, status: "cancelled" });
                        if (result) setCancelOpen(false);
                      }}
                    >
                      Cancel Return
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>

              {/* Marking credited requires a debit note number — the API enforces it. */}
              <Dialog
                open={creditOpen}
                onOpenChange={(open) => {
                  setCreditOpen(open);
                  if (!open) {
                    setDebitNoteNumber("");
                    setStatus.reset();
                  }
                }}
              >
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Mark this return credited?</DialogTitle>
                    <DialogDescription>
                      Enter the debit note number the supplier credited against {ret.returnNumber}.
                    </DialogDescription>
                  </DialogHeader>
                  <DialogBody>
                    <div className="space-y-1.5">
                      <Label htmlFor="return-debit-note">Debit Note Number</Label>
                      <Input
                        id="return-debit-note"
                        value={debitNoteNumber}
                        onChange={(e) => setDebitNoteNumber(e.target.value)}
                      />
                    </div>
                    <FormError message={setStatus.error} className="mt-3" />
                  </DialogBody>
                  <DialogFooter>
                    <Button variant="outline" disabled={setStatus.isPending} onClick={() => setCreditOpen(false)}>
                      Cancel
                    </Button>
                    <Button
                      disabled={setStatus.isPending || !debitNoteNumber.trim()}
                      onClick={async () => {
                        const result = await setStatus.run({
                          returnId: ret.id,
                          status: "credited",
                          debitNoteNumber: debitNoteNumber.trim(),
                        });
                        if (result) {
                          setCreditOpen(false);
                          setDebitNoteNumber("");
                        }
                      }}
                    >
                      Mark Credited
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
