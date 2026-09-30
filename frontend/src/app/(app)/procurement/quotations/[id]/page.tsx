"use client";

import * as React from "react";
import Link from "next/link";
import { use } from "react";
import { ArrowLeft, Check } from "lucide-react";

import { AsyncBoundary, FormError } from "@/components/common/async-state";
import { AuditTrail } from "@/components/common/audit-trail";
import { ConfirmButton } from "@/components/common/confirm-dialog";
import { DetailGrid, DetailRow } from "@/components/common/detail-row";
import { PageHeader } from "@/components/common/page-header";
import { PermissionGate } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { ProvenanceBadge, StatusBadge } from "@/components/common/status-badge";
import { DeleteQuotationButton } from "@/components/documents/delete-quotation-button";
import { SourceDocumentsCard } from "@/components/documents/source-documents-card";
import { TaxSummary } from "@/components/procurement/tax-summary";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useQuotation, useSetQuotationStatus } from "@/hooks/use-procurement";
import { documentsApi } from "@/lib/api";
import { round2 } from "@/lib/domain/money";
import { formatCurrency, formatDate, formatDateTime } from "@/lib/format";
import type { MoneyTotals } from "@/types";

export default function QuotationDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const state = useQuotation(id);
  const setStatus = useSetQuotationStatus(() => state.refresh());

  return (
    <div className="space-y-5">
      <div>
        <Button variant="ghost" size="sm" asChild className="-ml-2 mb-2 text-muted-foreground">
          <Link href="/procurement/quotations">
            <ArrowLeft />
            All Quotations
          </Link>
        </Button>
      </div>

      <AsyncBoundary state={state}>
        {(detail) => {
          const q = detail.quotation;
          const canApprove = detail.allowedActions.includes("approved");
          const canReject = detail.allowedActions.includes("rejected");

          const money: MoneyTotals = {
            subtotal: q.subtotal,
            discountAmount: q.discountAmount,
            taxableValue: q.taxableValue,
            cgstAmount: round2(detail.taxRows.reduce((s, r) => s + r.cgstAmount, 0)),
            sgstAmount: round2(detail.taxRows.reduce((s, r) => s + r.sgstAmount, 0)),
            igstAmount: round2(detail.taxRows.reduce((s, r) => s + r.igstAmount, 0)),
            cessAmount: round2(detail.taxRows.reduce((s, r) => s + r.cessAmount, 0)),
            freightAmount: q.freightAmount,
            otherCharges: q.otherCharges,
            roundOff: q.roundOff,
            totalAmount: q.totalAmount,
            isInterState: false,
          };

          return (
            <div className="space-y-5">
              <PageHeader
                title={q.quotationNumber}
                description={`${detail.supplierName}${detail.rfqNumber ? ` · against ${detail.rfqNumber}` : ""}`}
                actions={
                  <>
                    <StatusBadge status={q.status} />
                    {q.source === "ai_extracted" ? (
                      <ProvenanceBadge provenance="ai_extracted" confidence={q.extractionConfidence} />
                    ) : (
                      <Badge variant="neutral">Manual Entry</Badge>
                    )}
                    {canApprove && (
                      <PermissionGate permission="quotation.approve">
                        <ConfirmButton
                          title="Approve this quotation?"
                          description="Once approved, it can be used to build a comparison and converted to a purchase order."
                          confirmLabel="Approve"
                          tone="success"
                          disabled={setStatus.isPending}
                          onConfirm={async () => {
                            await setStatus.run({ quotationId: id, status: "approved" });
                          }}
                        >
                          <Check />
                          Approve
                        </ConfirmButton>
                      </PermissionGate>
                    )}
                    {canReject && (
                      <PermissionGate permission="quotation.reject">
                        <DeleteQuotationButton
                          quotationId={id}
                          quotationNumber={q.quotationNumber}
                          supplierName={detail.supplierName}
                          onDone={() => state.refresh()}
                        />
                      </PermissionGate>
                    )}
                  </>
                }
              />

              <FormError message={setStatus.error} fieldErrors={setStatus.fieldErrors} />

              <SectionCard title="Quotation Details">
                <DetailGrid className="p-4">
                  <DetailRow label="Quotation Date" value={formatDate(q.quotationDate)} />
                  <DetailRow
                    label="Valid Until"
                    value={
                      q.validUntil ? (
                        <span className={detail.isExpired ? "text-destructive" : undefined}>
                          {formatDate(q.validUntil)}
                          {detail.isExpired && " · Expired"}
                        </span>
                      ) : (
                        "—"
                      )
                    }
                  />
                  <DetailRow
                    label="Against RFQ"
                    value={
                      detail.rfqNumber ? (
                        <span className="font-mono text-[13px]">{detail.rfqNumber}</span>
                      ) : (
                        "Not linked to an RFQ"
                      )
                    }
                  />
                  <DetailRow label="Payment Terms" value={q.paymentTerms || "—"} />
                  <DetailRow label="Delivery Terms" value={q.deliveryTerms || "—"} />
                  <DetailRow
                    label="Delivery Period"
                    value={q.deliveryPeriodDays !== null ? `${q.deliveryPeriodDays} days` : "—"}
                  />
                  <DetailRow label="Warranty Terms" value={q.warrantyTerms || "—"} />
                  <DetailRow label="Freight Terms" value={q.freightTerms || "—"} />
                  {q.status === "rejected" && (
                    <DetailRow label="Rejection Reason" value={q.rejectedReason || "—"} />
                  )}
                  <DetailRow label="Created" value={q.createdAt ? formatDateTime(q.createdAt) : "—"} />
                  <DetailRow label="Last Updated" value={q.updatedAt ? formatDateTime(q.updatedAt) : "—"} />
                </DetailGrid>
              </SectionCard>

              <SectionCard title={`Items (${detail.items.length})`}>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead className="pl-4">Product</TableHead>
                        <TableHead className="text-right">Qty</TableHead>
                        <TableHead>Unit</TableHead>
                        <TableHead className="text-right">Rate</TableHead>
                        <TableHead className="text-right">Disc %</TableHead>
                        <TableHead className="text-right">GST %</TableHead>
                        <TableHead className="text-right">Total</TableHead>
                        <TableHead className="pr-4">Match</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {detail.items.map((item) => (
                        <TableRow key={item.id}>
                          <TableCell className="max-w-[220px] pl-4">
                            <span className="block truncate font-medium text-foreground">
                              {item.productName}
                            </span>
                            <span className="block font-mono text-caption text-muted-foreground">
                              {item.sku || "—"}
                            </span>
                            {!item.isAvailable && (
                              <span className="mt-0.5 flex items-center gap-1 text-[11px] text-warning-subtle-foreground">
                                Not available{item.availabilityNote ? ` — ${item.availabilityNote}` : ""}
                              </span>
                            )}
                          </TableCell>
                          <TableCell className="text-right tabular">{item.quantity}</TableCell>
                          <TableCell>{item.uomCode}</TableCell>
                          <TableCell className="text-right tabular">{formatCurrency(item.unitPrice)}</TableCell>
                          <TableCell className="text-right tabular">{item.discountPct}%</TableCell>
                          <TableCell className="text-right tabular">{item.gstRate}%</TableCell>
                          <TableCell className="text-right font-medium text-foreground tabular">
                            {formatCurrency(item.lineTotal)}
                          </TableCell>
                          <TableCell className="pr-4">
                            <ProvenanceBadge
                              provenance={item.provenance}
                              confidence={item.matchConfidence}
                            />
                            {item.matchMethod && (
                              <span className="mt-0.5 block text-[11px] text-muted-foreground">
                                {documentsApi.MATCH_LABELS[item.matchMethod]}
                              </span>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </SectionCard>

              <SectionCard title="GST Breakdown & Totals" bodyClassName="p-4">
                <TaxSummary money={money} taxRows={detail.taxRows} />
              </SectionCard>

              <SourceDocumentsCard linkedType="supplier_quotation" linkedId={id} />

              <AuditTrail entityType="supplier_quotation" entityId={id} />
            </div>
          );
        }}
      </AsyncBoundary>
    </div>
  );
}
