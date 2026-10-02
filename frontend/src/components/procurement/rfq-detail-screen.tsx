"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, FileQuestion, GitCompareArrows, Loader2, Plus, Send, X } from "lucide-react";

import { AsyncBoundary, FormError } from "@/components/common/async-state";
import { AuditTrail } from "@/components/common/audit-trail";
import { ConfirmButton } from "@/components/common/confirm-dialog";
import { DetailGrid, DetailRow } from "@/components/common/detail-row";
import { EmptyState } from "@/components/common/empty-state";
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
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useApiMutation } from "@/hooks/use-api";
import { useAddRfqSuppliers, useRemoveRfqSupplier, useRfq, useSendRfq } from "@/hooks/use-procurement";
import { useSuppliers } from "@/hooks/use-suppliers";
import { procurementApi } from "@/lib/api";
import { formatCurrency, formatDate, formatDateTime } from "@/lib/format";
import type { Id } from "@/types";

function CancelRfqDialog({ rfqId, onDone }: { rfqId: Id; onDone: () => void }) {
  const [open, setOpen] = React.useState(false);
  const [reason, setReason] = React.useState("");
  const cancel = useApiMutation(
    (input: { rfqId: Id; reason: string }) => procurementApi.cancelRfq(input.rfqId, input.reason),
    {
      onSuccess: () => {
        setOpen(false);
        setReason("");
        onDone();
      },
    },
  );

  return (
    <>
      <Button variant="outline" className="text-destructive hover:text-destructive" onClick={() => setOpen(true)}>
        Cancel RFQ
      </Button>
      <Dialog open={open} onOpenChange={(next) => !cancel.isPending && setOpen(next)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cancel this RFQ?</DialogTitle>
            <DialogDescription>
              Suppliers will no longer be able to quote against it. This can&apos;t be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-2">
            <Label htmlFor="cancel-reason">Reason</Label>
            <Textarea id="cancel-reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={3} />
            <FormError message={cancel.error} fieldErrors={cancel.fieldErrors} />
          </DialogBody>
          <DialogFooter>
            <Button variant="outline" disabled={cancel.isPending} onClick={() => setOpen(false)}>
              Keep RFQ
            </Button>
            <Button
              variant="destructive"
              disabled={cancel.isPending}
              onClick={() => cancel.run({ rfqId, reason })}
            >
              {cancel.isPending && <Loader2 className="animate-spin" />}
              Cancel RFQ
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/**
 * On a draft the supplier simply joins the list and is sent to with
 * everyone else; on a sent RFQ, adding *is* sending — to that supplier only.
 */
function AddSupplierDialog({
  rfqId,
  sent,
  existing,
  onDone,
}: {
  rfqId: Id;
  sent: boolean;
  existing: Id[];
  onDone: () => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [supplierId, setSupplierId] = React.useState("");
  const suppliersState = useSuppliers({ limit: 200 });
  const add = useAddRfqSuppliers(rfqId, () => {
    setOpen(false);
    setSupplierId("");
    onDone();
  });
  const choices = (suppliersState.data?.items ?? []).filter(
    (s) => s.status === "active" && !existing.includes(s.id),
  );

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Plus />
        Add supplier
      </Button>
      <Dialog open={open} onOpenChange={(next) => !add.isPending && setOpen(next)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{sent ? "Send this RFQ to another supplier" : "Add a supplier"}</DialogTitle>
            <DialogDescription>
              {sent
                ? "The supplier is emailed this RFQ now. Suppliers who already have it are not sent it again."
                : "The supplier is sent this RFQ along with the others when you send it."}
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-2">
            <Label>Supplier</Label>
            <Select value={supplierId} onValueChange={setSupplierId}>
              <SelectTrigger data-testid="rfq-add-supplier-select">
                <SelectValue
                  placeholder={
                    suppliersState.isLoading
                      ? "Loading suppliers..."
                      : choices.length
                        ? "Choose a supplier..."
                        : "Every active supplier is already on this RFQ"
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {choices.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name}
                    {s.city ? ` · ${s.city}` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FormError message={add.error} fieldErrors={add.fieldErrors} />
          </DialogBody>
          <DialogFooter>
            <Button variant="outline" disabled={add.isPending} onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button disabled={!supplierId || add.isPending} onClick={() => add.run([supplierId])}>
              {add.isPending && <Loader2 className="animate-spin" />}
              {sent ? "Add and send" : "Add supplier"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

export function RfqDetailScreen({ id }: { id: Id }) {
  const router = useRouter();
  const state = useRfq(id);
  const send = useSendRfq(() => state.refresh());
  const removeSupplier = useRemoveRfqSupplier(id, () => state.refresh());

  return (
    <div className="space-y-5">
      <div>
        <Button variant="ghost" size="sm" asChild className="-ml-2 mb-2 text-muted-foreground">
          <Link href="/procurement/rfq">
            <ArrowLeft />
            All RFQs
          </Link>
        </Button>
      </div>

      <AsyncBoundary state={state}>
        {(detail) => {
          const canSend = detail.allowedActions.includes("sent");
          const canCancel = detail.allowedActions.includes("cancelled");
          const isDraft = detail.rfq.status === "draft";
          const canAddSuppliers = isDraft || detail.rfq.status === "sent";

          return (
            <div className="space-y-5">
              <PageHeader
                title={detail.rfq.rfqNumber}
                description={detail.rfq.subject}
                actions={
                  <>
                    <StatusBadge status={detail.rfq.status} />
                    {detail.quotations.length > 0 && (
                      <Button variant="outline" asChild>
                        <Link href={`/procurement/comparison/${id}`}>
                          <GitCompareArrows />
                          Compare Quotes
                        </Link>
                      </Button>
                    )}
                    {canSend && (
                      <PermissionGate permission="rfq.send">
                        <ConfirmButton
                          title="Send this RFQ to your suppliers?"
                          description={`${detail.suppliers.length} supplier${detail.suppliers.length === 1 ? "" : "s"} will be emailed a request for quotation.`}
                          confirmLabel="Send"
                          disabled={send.isPending || detail.suppliers.length === 0}
                          onConfirm={async () => {
                            await send.run(id);
                          }}
                        >
                          <Send />
                          Send RFQ
                        </ConfirmButton>
                      </PermissionGate>
                    )}
                    {canCancel && (
                      <PermissionGate permission="rfq.cancel">
                        <CancelRfqDialog rfqId={id} onDone={() => state.refresh()} />
                      </PermissionGate>
                    )}
                  </>
                }
              />

              <FormError message={send.error} fieldErrors={send.fieldErrors} />

              <SectionCard title="RFQ Details">
                <DetailGrid className="p-4">
                  <DetailRow label="RFQ Date" value={formatDate(detail.rfq.rfqDate)} />
                  <DetailRow
                    label="Expected Delivery"
                    value={detail.rfq.expectedDeliveryDate ? formatDate(detail.rfq.expectedDeliveryDate) : "—"}
                  />
                  <DetailRow label="Deliver To" value={detail.godownName || "—"} />
                  <DetailRow
                    label="Quotes Received"
                    value={`${detail.suppliers.filter((s) => s.quotationId).length} of ${detail.suppliers.length}`}
                  />
                  <DetailRow label="Estimated Value" value={formatCurrency(detail.rfq.estimatedValue)} />
                  <DetailRow label="Notes" value={detail.rfq.notes || "—"} />
                  <DetailRow label="Created" value={detail.rfq.createdAt ? formatDateTime(detail.rfq.createdAt) : "—"} />
                  <DetailRow label="Last Updated" value={detail.rfq.updatedAt ? formatDateTime(detail.rfq.updatedAt) : "—"} />
                </DetailGrid>
              </SectionCard>

              <SectionCard title={`Items (${detail.items.length})`}>
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="pl-4">Product</TableHead>
                      <TableHead>SKU</TableHead>
                      <TableHead className="text-right">Qty</TableHead>
                      <TableHead>Unit</TableHead>
                      <TableHead className="pr-4 text-right">Expected Value</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {detail.items.map((item) => (
                      <TableRow key={item.id}>
                        <TableCell className="pl-4 font-medium text-foreground">{item.productName}</TableCell>
                        <TableCell className="font-mono text-[12.5px] text-muted-foreground">
                          {item.sku || "—"}
                        </TableCell>
                        <TableCell className="text-right tabular">{item.quantity}</TableCell>
                        <TableCell>{item.uomCode}</TableCell>
                        <TableCell className="pr-4 text-right tabular">
                          {formatCurrency(item.quantity * item.expectedPrice)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <div className="flex justify-end border-t border-border px-4 py-3">
                  <p className="text-[14px] font-semibold text-foreground tabular">
                    Estimated Value: {formatCurrency(detail.rfq.estimatedValue)}
                  </p>
                </div>
              </SectionCard>

              <SectionCard
                title={`Suppliers (${detail.suppliers.length})`}
                action={
                  canAddSuppliers && (
                    <PermissionGate permission="rfq.update">
                      <PermissionGate permission={isDraft ? "rfq.update" : "rfq.send"}>
                        <AddSupplierDialog
                          rfqId={id}
                          sent={!isDraft}
                          existing={detail.suppliers.map((s) => s.supplierId)}
                          onDone={() => state.refresh()}
                        />
                      </PermissionGate>
                    </PermissionGate>
                  )
                }
              >
                {detail.suppliers.length === 0 ? (
                  <EmptyState
                    icon={FileQuestion}
                    title="No suppliers added yet"
                    description={
                      canAddSuppliers ? "Add the suppliers this RFQ should go to, then send it." : undefined
                    }
                    className="py-8"
                  />
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead className="pl-4">Supplier</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Responded</TableHead>
                        <TableHead className="pr-4">Quotation</TableHead>
                        {isDraft && <TableHead className="w-10 pr-4" />}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {detail.suppliers.map((supplier) => (
                        <TableRow key={supplier.id}>
                          <TableCell className="pl-4 font-medium text-foreground">
                            {supplier.supplierName}
                          </TableCell>
                          <TableCell>
                            <StatusBadge status={supplier.status} />
                          </TableCell>
                          <TableCell className="text-muted-foreground">
                            {supplier.respondedAt ? formatDate(supplier.respondedAt) : "—"}
                          </TableCell>
                          <TableCell className="pr-4">
                            {supplier.quotationId ? (
                              <Link
                                href={`/procurement/quotations/${supplier.quotationId}`}
                                className="font-mono text-[12.5px] font-medium text-primary hover:underline"
                              >
                                {supplier.quotationNumber}
                              </Link>
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )}
                          </TableCell>
                          {isDraft && (
                            <TableCell className="pr-4">
                              <PermissionGate permission="rfq.update">
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="size-7"
                                  aria-label={`Remove ${supplier.supplierName}`}
                                  disabled={removeSupplier.isPending}
                                  onClick={() => removeSupplier.run(supplier.supplierId)}
                                >
                                  <X className="size-3.5" />
                                </Button>
                              </PermissionGate>
                            </TableCell>
                          )}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
                <FormError message={removeSupplier.error} className="m-3" />
              </SectionCard>

              {detail.quotations.length > 0 && (
                <SectionCard
                  title={`Quotations Received (${detail.quotations.length})`}
                  action={
                    <Button variant="outline" size="sm" asChild>
                      <Link href={`/procurement/comparison/${id}`}>
                        <GitCompareArrows />
                        Compare
                      </Link>
                    </Button>
                  }
                >
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead className="pl-4">Quotation</TableHead>
                        <TableHead>Date</TableHead>
                        <TableHead className="text-right">Total</TableHead>
                        <TableHead className="pr-4">Status</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {detail.quotations.map((q) => (
                        <TableRow
                          key={q.id}
                          className="cursor-pointer"
                          onClick={() => router.push(`/procurement/quotations/${q.id}`)}
                        >
                          <TableCell className="pl-4 font-mono text-[12.5px] font-medium text-foreground">
                            {q.quotationNumber}
                          </TableCell>
                          <TableCell className="text-muted-foreground">{formatDate(q.quotationDate)}</TableCell>
                          <TableCell className="text-right font-medium text-foreground tabular">
                            {formatCurrency(q.totalAmount)}
                          </TableCell>
                          <TableCell className="pr-4">
                            <StatusBadge status={q.status} />
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </SectionCard>
              )}

              <AuditTrail entityType="rfq" entityId={id} />
            </div>
          );
        }}
      </AsyncBoundary>
    </div>
  );
}
