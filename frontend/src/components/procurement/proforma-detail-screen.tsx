"use client";

import * as React from "react";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  Ban,
  Building2,
  Check,
  Info,
  Lock,
  MessageCircleQuestion,
  TriangleAlert,
  X,
} from "lucide-react";

import { AsyncBoundary, FormError, LoadingCard } from "@/components/common/async-state";
import { AuditTrail } from "@/components/common/audit-trail";
import { SourceDocumentsCard } from "@/components/documents/source-documents-card";
import { ConfirmButton } from "@/components/common/confirm-dialog";
import { DetailGrid, DetailRow } from "@/components/common/detail-row";
import { PageHeader } from "@/components/common/page-header";
import { PermissionGate } from "@/components/common/permission-gate";
import { PrintButton } from "@/components/common/print-button";
import { SectionCard } from "@/components/common/section-card";
import { SeverityBadge, StatusBadge } from "@/components/common/status-badge";
import { TaxSummary } from "@/components/procurement/tax-summary";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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
import { useProforma, useRaiseProformaQuery, useSetProformaStatus } from "@/hooks/use-procurement";
import { usePermissions } from "@/hooks/use-session";
import { variancePct } from "@/lib/domain/money";
import { formatCurrency, formatDate, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Id, ProformaStatus } from "@/types";

export function ProformaDetailScreen({ id }: { id: Id }) {
  const state = useProforma(id);
  const permissions = usePermissions();
  const settingsState = useCompanySettings();
  const setStatus = useSetProformaStatus();
  const raiseQuery = useRaiseProformaQuery();

  const [queryOpen, setQueryOpen] = React.useState(false);
  const [queryNote, setQueryNote] = React.useState("");
  const [cancelOpen, setCancelOpen] = React.useState(false);

  return (
    <div className="space-y-5">
      <Button variant="ghost" size="sm" asChild className="-ml-2 text-muted-foreground print:hidden">
        <Link href="/procurement/proforma">
          <ArrowLeft />
          All Proforma Invoices
        </Link>
      </Button>

      <AsyncBoundary state={state} loading={<LoadingCard />}>
        {(detail) => {
          const proforma = detail.proforma;
          const allowed = new Set<ProformaStatus>(detail.allowedActions);
          const tolerance = settingsState.data?.settings.variancePriceTolerancePct ?? 2;
          const pct = proforma.poTotalSnapshot > 0 ? variancePct(proforma.poTotalSnapshot, proforma.totalAmount) : 0;
          const withinTolerance = pct <= tolerance;
          const canApprove = withinTolerance || permissions.can("proforma.approve_variance");

          async function transition(status: ProformaStatus) {
            await setStatus.run({ proformaId: proforma.id, status });
          }

          return (
            <div className="space-y-5">
              <PageHeader
                title="Supplier Proforma Invoice"
                description={`${proforma.proformaNumber} · received from ${detail.supplierName}`}
                actions={
                  <>
                    <PrintButton />
                    {allowed.has("under_review") && (
                      <PermissionGate permission="proforma.update">
                        <ConfirmButton
                          title="Send this proforma for review?"
                          confirmLabel="Send"
                          onConfirm={() => transition("under_review")}
                        >
                          <ArrowRight />
                          Send for Review
                        </ConfirmButton>
                      </PermissionGate>
                    )}
                    {allowed.has("approved") && (
                      <PermissionGate permission="proforma.approve">
                        {canApprove ? (
                          <ConfirmButton
                            title="Approve this proforma?"
                            description="The advance can be released once approved."
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
                              {pct.toFixed(1)}% over the PO — above the {tolerance}% tolerance. Needs the
                              variance approval permission (proforma.approve_variance).
                            </TooltipContent>
                          </Tooltip>
                        )}
                      </PermissionGate>
                    )}
                    {allowed.has("rejected") && (
                      <PermissionGate permission="proforma.approve">
                        <ConfirmButton
                          variant="outline"
                          tone="destructive"
                          title="Reject this proforma?"
                          description="The supplier will need to resend a corrected proforma."
                          confirmLabel="Reject"
                          onConfirm={() => transition("rejected")}
                        >
                          <X />
                          Reject
                        </ConfirmButton>
                      </PermissionGate>
                    )}
                    {allowed.has("paid") && (
                      <PermissionGate permission="proforma.update">
                        <ConfirmButton
                          title="Mark this proforma as paid?"
                          description="Record that the advance has been paid to the supplier."
                          confirmLabel="Mark as Paid"
                          onConfirm={() => transition("paid")}
                        >
                          <Check />
                          Mark as Paid
                        </ConfirmButton>
                      </PermissionGate>
                    )}
                    {allowed.has("completed") && (
                      <PermissionGate permission="proforma.update">
                        <ConfirmButton
                          title="Mark this proforma as completed?"
                          confirmLabel="Complete"
                          onConfirm={() => transition("completed")}
                        >
                          <Check />
                          Mark Completed
                        </ConfirmButton>
                      </PermissionGate>
                    )}
                    <PermissionGate permission="proforma.raise_query">
                      <Button variant="outline" onClick={() => setQueryOpen(true)}>
                        <MessageCircleQuestion />
                        Raise Query
                      </Button>
                    </PermissionGate>
                    {allowed.has("cancelled") && (
                      <PermissionGate permission="proforma.update">
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

              {(setStatus.error || raiseQuery.error) && !queryOpen && !cancelOpen && (
                <FormError message={setStatus.error ?? raiseQuery.error} />
              )}

              <Alert variant="info">
                <Info />
                <AlertDescription>
                  A proforma is the supplier&apos;s advance estimate, not a statutory GST tax invoice. The
                  tax invoice is recorded separately at goods receipt.
                </AlertDescription>
              </Alert>

              {proforma.queryRaisedAt && (
                <Alert variant="warning">
                  <MessageCircleQuestion />
                  <AlertDescription>
                    Query raised with the supplier on {formatDate(proforma.queryRaisedAt)}
                    {proforma.queryNote ? `: “${proforma.queryNote}”` : "."}
                  </AlertDescription>
                </Alert>
              )}

              {Math.abs(proforma.varianceAmount) > 0.5 && (
                <div className="flex flex-col gap-3 rounded-xl border border-warning/35 bg-warning-subtle/55 px-4 py-3.5 sm:flex-row sm:items-center">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-warning-subtle text-warning-subtle-foreground">
                    <TriangleAlert className="size-4" strokeWidth={2} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-[13.5px] font-medium text-warning-subtle-foreground">
                      Proforma total differs from {detail.poNumber ?? "the linked PO"} by{" "}
                      {formatCurrency(Math.abs(proforma.varianceAmount))}
                    </p>
                    <p className="text-caption text-warning-subtle-foreground/85">
                      {detail.items.filter((l) => (l.priceVariancePct ?? 0) !== 0).length} line item(s) have a
                      different rate than the purchase order. Confirm with the supplier before paying the
                      advance.
                    </p>
                  </div>
                </div>
              )}

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                {[
                  { label: "PO Total", value: proforma.poTotalSnapshot, note: detail.poNumber ?? "—" },
                  { label: "Proforma Total", value: proforma.totalAmount, note: proforma.proformaNumber },
                  {
                    label: "Variance",
                    value: proforma.varianceAmount,
                    note:
                      proforma.varianceAmount > 0
                        ? "Supplier is charging more"
                        : proforma.varianceAmount < 0
                          ? "Supplier is charging less"
                          : "Matches the purchase order",
                    tone: true,
                  },
                ].map((card) => (
                  <Card
                    key={card.label}
                    className={cn(
                      "p-4",
                      card.tone && proforma.varianceAmount !== 0 && "border-warning/35 bg-warning-subtle/40",
                    )}
                  >
                    <p className="text-label text-muted-foreground">{card.label}</p>
                    <p
                      className={cn(
                        "mt-2 text-[22px] leading-none font-semibold tracking-[-0.02em] tabular",
                        card.tone && proforma.varianceAmount > 0
                          ? "text-warning-subtle-foreground"
                          : "text-foreground",
                      )}
                    >
                      {card.tone && proforma.varianceAmount > 0 ? "+" : ""}
                      {formatCurrency(card.value)}
                    </p>
                    <p className="mt-2 text-caption text-muted-foreground">{card.note}</p>
                  </Card>
                ))}
              </div>

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
                <div className="space-y-4 lg:col-span-8">
                  <SectionCard title="Parties & Supply">
                    <div className="grid grid-cols-1 gap-5 p-4 sm:grid-cols-2">
                      <div>
                        <p className="mb-2 flex items-center gap-1.5 text-[12px] font-semibold tracking-wide text-muted-foreground uppercase">
                          <Building2 className="size-3.5" />
                          Supplier
                        </p>
                        <DetailGrid columns={1}>
                          <DetailRow label="Name" value={detail.supplierName} />
                          <DetailRow label="GSTIN" value={proforma.supplierGstinSnapshot} mono />
                          <DetailRow label="Address" value={proforma.supplierAddressSnapshot} />
                        </DetailGrid>
                      </div>
                      <div>
                        <p className="mb-2 flex items-center gap-1.5 text-[12px] font-semibold tracking-wide text-muted-foreground uppercase">
                          <Building2 className="size-3.5" />
                          Buyer
                        </p>
                        <DetailGrid columns={1}>
                          <DetailRow label="Name" value={settingsState.data?.company.name} />
                          <DetailRow label="GSTIN" value={settingsState.data?.company.gstin} mono />
                          <DetailRow label="Address" value={settingsState.data?.company.addressLine1} />
                        </DetailGrid>
                      </div>
                      <div className="sm:col-span-2">
                        <DetailGrid columns={3}>
                          <DetailRow label="Proforma Number" value={proforma.proformaNumber} mono />
                          <DetailRow label="Proforma Date" value={formatDate(proforma.proformaDate)} />
                          <DetailRow
                            label="PO Reference"
                            value={
                              proforma.purchaseOrderId ? (
                                <Link
                                  href={`/procurement/purchase-orders/${proforma.purchaseOrderId}`}
                                  className="font-mono text-foreground hover:text-primary"
                                >
                                  {detail.poNumber}
                                </Link>
                              ) : (
                                "—"
                              )
                            }
                          />
                          <DetailRow
                            label="Tax Treatment"
                            value={proforma.isInterState ? "IGST (inter-state)" : "CGST + SGST (intra-state)"}
                          />
                        </DetailGrid>
                      </div>
                    </div>
                  </SectionCard>

                  <SectionCard
                    title="Items"
                    description="Proforma rate compared against the rate you ordered at"
                  >
                    <Table>
                      <TableHeader>
                        <TableRow className="hover:bg-transparent">
                          <TableHead className="pl-4">Product</TableHead>
                          <TableHead>HSN</TableHead>
                          <TableHead className="text-right">Qty</TableHead>
                          <TableHead className="text-right">PO Rate</TableHead>
                          <TableHead className="text-right">Proforma Rate</TableHead>
                          <TableHead className="text-right">GST</TableHead>
                          <TableHead className="pr-4 text-right">Total</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {detail.items.map((line) => {
                          const changed = (line.priceVariancePct ?? 0) !== 0;
                          return (
                            <TableRow key={line.id}>
                              <TableCell className="max-w-[220px] pl-4">
                                <span className="block truncate font-medium text-foreground">
                                  {line.productName}
                                </span>
                                <span className="block font-mono text-caption text-muted-foreground">
                                  {line.sku}
                                </span>
                              </TableCell>
                              <TableCell className="font-mono text-[12.5px] text-muted-foreground">
                                {line.hsnCode}
                              </TableCell>
                              <TableCell className="text-right text-muted-foreground tabular">
                                {line.quantity} {line.uomCode}
                              </TableCell>
                              <TableCell className="text-right text-muted-foreground tabular">
                                {line.poUnitPriceSnapshot != null ? formatCurrency(line.poUnitPriceSnapshot) : "—"}
                              </TableCell>
                              <TableCell
                                className={cn(
                                  "text-right font-medium tabular",
                                  changed ? "text-warning-subtle-foreground" : "text-foreground",
                                )}
                              >
                                {formatCurrency(line.unitPrice)}
                                {changed && (
                                  <Badge variant="warning" className="ml-1.5 px-1.5 py-0">
                                    {line.priceVariancePct! > 0 ? "+" : ""}
                                    {line.priceVariancePct!.toFixed(1)}%
                                  </Badge>
                                )}
                              </TableCell>
                              <TableCell className="text-right text-muted-foreground tabular">
                                {line.gstRate}%
                              </TableCell>
                              <TableCell className="pr-4 text-right font-medium text-foreground tabular">
                                {formatCurrency(line.lineTotal)}
                              </TableCell>
                            </TableRow>
                          );
                        })}
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
                                {formatNumber(v.baseValue)} → {formatNumber(v.compareValue)} (
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
                </div>

                <div className="space-y-4 lg:col-span-4">
                  <SectionCard title="Totals">
                    <div className="p-4">
                      <TaxSummary money={proforma} taxRows={detail.taxRows} />
                    </div>
                  </SectionCard>

                  <SectionCard title="Payment Instructions">
                    <div className="space-y-3 p-4">
                      <p className="rounded-md bg-muted/60 px-3 py-2 text-[13px] text-foreground">
                        {proforma.paymentInstructions || "No payment instructions provided."}
                      </p>
                      <DetailGrid columns={1}>
                        <DetailRow label="Bank" value={proforma.bankName} />
                        <DetailRow label="Account Number" value={proforma.bankAccountNo} mono />
                        <DetailRow label="IFSC" value={proforma.bankIfsc} mono />
                      </DetailGrid>
                    </div>
                  </SectionCard>
                </div>
              </div>

              <SourceDocumentsCard linkedType="proforma_invoice" linkedId={proforma.id} />

              <AuditTrail entityType="proforma_invoice" entityId={proforma.id} />

              <Dialog
                open={queryOpen}
                onOpenChange={(open) => {
                  setQueryOpen(open);
                  if (!open) {
                    setQueryNote("");
                    raiseQuery.reset();
                  }
                }}
              >
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Raise a query with {detail.supplierName}</DialogTitle>
                    <DialogDescription>
                      Sent against {proforma.proformaNumber}. The supplier is emailed a copy of your question.
                    </DialogDescription>
                  </DialogHeader>
                  <DialogBody>
                    <div className="space-y-1.5">
                      <Label htmlFor="proforma-query-note">Query</Label>
                      <Textarea
                        id="proforma-query-note"
                        value={queryNote}
                        onChange={(e) => setQueryNote(e.target.value)}
                        placeholder="e.g. Line 2 is priced above the purchase order — please confirm."
                      />
                    </div>
                    <FormError message={raiseQuery.error} className="mt-3" />
                  </DialogBody>
                  <DialogFooter>
                    <Button variant="outline" disabled={raiseQuery.isPending} onClick={() => setQueryOpen(false)}>
                      Cancel
                    </Button>
                    <Button
                      disabled={raiseQuery.isPending || !queryNote.trim()}
                      onClick={async () => {
                        const result = await raiseQuery.run({ proformaId: proforma.id, note: queryNote.trim() });
                        if (result) {
                          setQueryOpen(false);
                          setQueryNote("");
                        }
                      }}
                    >
                      Send Query
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>

              <Dialog
                open={cancelOpen}
                onOpenChange={(open) => {
                  setCancelOpen(open);
                  if (!open) setStatus.reset();
                }}
              >
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Cancel this proforma?</DialogTitle>
                    <DialogDescription>
                      {proforma.proformaNumber} will be marked cancelled. This can&apos;t be undone.
                    </DialogDescription>
                  </DialogHeader>
                  {setStatus.error && (
                    <DialogBody>
                      <FormError message={setStatus.error} />
                    </DialogBody>
                  )}
                  <DialogFooter>
                    <Button variant="outline" disabled={setStatus.isPending} onClick={() => setCancelOpen(false)}>
                      Keep Proforma
                    </Button>
                    <Button
                      variant="destructive"
                      disabled={setStatus.isPending}
                      onClick={async () => {
                        const result = await setStatus.run({ proformaId: proforma.id, status: "cancelled" });
                        if (result) setCancelOpen(false);
                      }}
                    >
                      Cancel Proforma
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
