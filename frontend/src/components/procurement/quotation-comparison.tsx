"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Check, Crown, FileText, Loader2, Minus, TriangleAlert } from "lucide-react";

import { AsyncBoundary, FormError } from "@/components/common/async-state";
import { PageHeader } from "@/components/common/page-header";
import { PermissionGate } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { StatusBadge } from "@/components/common/status-badge";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useGodowns } from "@/hooks/use-catalog";
import {
  useComparisonForRfq,
  useConvertComparison,
  useRfq,
  useSelectComparisonLine,
} from "@/hooks/use-procurement";
import { usePermissions } from "@/hooks/use-session";
import { formatCurrency, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ComparisonCell, ComparisonRowView, ComparisonView, Id, SupplierQuotation } from "@/types";

function shortName(name: string) {
  return name
    .replace(/ (Pvt |Private )?Ltd\.?$/i, "")
    .replace(/ India$/i, "")
    .trim();
}

function selectedSupplierFor(view: ComparisonView, rfqItemId: Id): Id | null {
  const line = view.lines.find((l) => l.rfqItemId === rfqItemId);
  return line?.selectedSupplierId ?? line?.recommendedSupplierId ?? null;
}

/**
 * Quotes are in but none is approved. Only approved quotations are
 * compared, so say that and link straight to the ones waiting.
 */
function NothingApprovedYet({
  quotations,
  suppliers,
}: {
  quotations: SupplierQuotation[];
  suppliers: { supplierId: Id; supplierName: string }[];
}) {
  const nameOf = (id: Id) => suppliers.find((s) => s.supplierId === id)?.supplierName ?? "Supplier";
  return (
    <SectionCard
      title="No approved quotations yet"
      description="Only approved quotations are compared. Approve the quotations below, then come back here."
    >
      {quotations.length === 0 ? (
        <p className="px-4 py-6 text-[13px] text-muted-foreground">
          No quotations have been recorded against this RFQ.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {quotations.map((q) => (
            <li key={q.id} className="flex items-center gap-3 px-4 py-3">
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13.5px] font-medium text-foreground">{nameOf(q.supplierId)}</span>
                <span className="block font-mono text-[12px] text-muted-foreground">{q.quotationNumber}</span>
              </span>
              <StatusBadge status={q.status} />
              <Button variant="outline" size="sm" asChild>
                <Link href={`/procurement/quotations/${q.id}`}>
                  {q.status === "draft" || q.status === "under_review" ? "Review & approve" : "Open"}
                </Link>
              </Button>
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}

export function QuotationComparison({ rfqId }: { rfqId: Id }) {
  const router = useRouter();
  const { can } = usePermissions();
  const canDecide = can("comparison.decide");
  const rfqState = useRfq(rfqId);
  const state = useComparisonForRfq(rfqId);

  const convert = useConvertComparison((pos) => {
    if (pos.length === 1) router.push(`/procurement/purchase-orders/${pos[0].id}`);
    else router.push("/procurement/purchase-orders");
  });

  const godownsState = useGodowns();
  const godowns = godownsState.data ?? [];
  const [deliveryGodownId, setDeliveryGodownId] = React.useState<Id | "">("");

  const [pendingOverride, setPendingOverride] = React.useState<{
    rfqItemId: Id;
    quotationItemId: Id;
    supplierId: Id;
  } | null>(null);
  const [overrideReason, setOverrideReason] = React.useState("");

  const selectLine = useSelectComparisonLine(() => {
    setPendingOverride(null);
    // Real HTTP now (was mock-repository revision bump) — the mutation
    // doesn't invalidate `useApiQuery`'s cache on its own, same gap fixed
    // for PO/GRN screens in the write-path-testing phase.
    state.refresh();
  });

  function chooseSupplier(view: ComparisonView, row: ComparisonRowView, cell: ComparisonCell) {
    if (!cell.isAvailable || !cell.quotationItemId) return;
    if (cell.supplierId === row.recommendedSupplierId) {
      selectLine.run({ comparisonId: view.comparison.id, rfqItemId: row.rfqItemId, quotationItemId: cell.quotationItemId });
    } else {
      setPendingOverride({ rfqItemId: row.rfqItemId, quotationItemId: cell.quotationItemId, supplierId: cell.supplierId });
      setOverrideReason("");
    }
  }

  function confirmOverride(view: ComparisonView) {
    if (!pendingOverride) return;
    selectLine.run({
      comparisonId: view.comparison.id,
      rfqItemId: pendingOverride.rfqItemId,
      quotationItemId: pendingOverride.quotationItemId,
      overrideReason: overrideReason.trim() || undefined,
    });
  }

  return (
    <div className="space-y-5">
      <div>
        <Button variant="ghost" size="sm" asChild className="-ml-2 mb-2 text-muted-foreground">
          <Link href="/procurement/comparison">
            <ArrowLeft />
            All Comparisons
          </Link>
        </Button>
        <PageHeader
          title="Quotation Comparison"
          description={rfqState.data ? `${rfqState.data.rfq.rfqNumber} — ${rfqState.data.rfq.subject}` : "Compare supplier quotations"}
          actions={
            <Button variant="outline" asChild>
              <Link href={`/procurement/rfq/${rfqId}`}>
                <FileText />
                View RFQ
              </Link>
            </Button>
          }
        />
      </div>

      <AsyncBoundary state={state}>
        {(view) => {
          if (view === null) {
            return <NothingApprovedYet quotations={rfqState.data?.quotations ?? []} suppliers={rfqState.data?.suppliers ?? []} />;
          }
          const suppliers = view.suppliers;
          // Once converted (or discarded) the selections are history: the
          // server refuses changes, so the screen does not offer them.
          const isOpen = view.comparison.status === "draft" || view.comparison.status === "decided";
          const largeDiffs = view.rows.filter((r) => r.priceSpreadPct > 5).length;

          return (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                {[
                  { label: "Suppliers Quoted", value: String(suppliers.length), hint: view.comparison.name },
                  {
                    label: "Items Compared",
                    value: String(view.rows.length),
                    hint: `${largeDiffs} with large price gaps`,
                  },
                  {
                    label: "Best Single Supplier",
                    value: view.totals.lowestSingleSupplierId ? formatCurrency(view.totals.lowestSingleSupplierTotal) : "—",
                    hint: suppliers.find((s) => s.supplierId === view.totals.lowestSingleSupplierId)
                      ? shortName(suppliers.find((s) => s.supplierId === view.totals.lowestSingleSupplierId)!.name)
                      : "No single supplier covers every line",
                  },
                  {
                    label: "Split Across Suppliers",
                    value: formatCurrency(view.totals.splitTotal),
                    hint: !view.totals.lowestSingleSupplierId
                      ? "Your selection per line, incl. GST"
                      : view.totals.projectedSavings > 0
                        ? `Saves ${formatCurrency(view.totals.projectedSavings)} vs best single supplier`
                        : view.totals.projectedSavings < 0
                          ? `${formatCurrency(-view.totals.projectedSavings)} more than best single supplier`
                          : "Same as best single supplier",
                    highlight: true,
                  },
                ].map((card) => (
                  <div
                    key={card.label}
                    className={cn(
                      "rounded-xl border p-4",
                      card.highlight ? "border-primary/35 bg-primary-subtle/55" : "border-border bg-card shadow-card",
                    )}
                  >
                    <p className="text-label text-muted-foreground">{card.label}</p>
                    <p className="mt-2 text-[22px] leading-none font-semibold tracking-[-0.02em] text-foreground tabular">
                      {card.value}
                    </p>
                    <p className="mt-2 truncate text-caption text-muted-foreground">{card.hint}</p>
                  </div>
                ))}
              </div>

              {view.warnings.length > 0 && (
                <div className="space-y-2">
                  {view.warnings.map((w, i) => (
                    <div
                      key={`${w.code}-${i}`}
                      className="flex items-start gap-2.5 rounded-lg border border-warning/35 bg-warning-subtle/55 px-3.5 py-2.5"
                    >
                      <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning-subtle-foreground" />
                      <p className="text-[13px] text-warning-subtle-foreground">{w.message}</p>
                    </div>
                  ))}
                </div>
              )}

              <SectionCard
                title="Item-by-item Comparison"
                description="Lowest valid price is highlighted — pick a supplier per line"
              >
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead className="pl-4">Product</TableHead>
                        <TableHead className="text-right">Qty</TableHead>
                        {suppliers.map((s) => (
                          <TableHead key={s.supplierId} className="min-w-[130px] text-right">
                            <span className="block">{shortName(s.name)}</span>
                            {s.isExpired && (
                              <Badge variant="destructive" className="mt-0.5 px-1.5 py-0">
                                Expired
                              </Badge>
                            )}
                          </TableHead>
                        ))}
                        <TableHead className="pr-4">Recommended</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {view.rows.map((row) => {
                        const selectedSupplierId = selectedSupplierFor(view, row.rfqItemId);
                        return (
                          <TableRow key={row.rfqItemId}>
                            <TableCell className="max-w-[210px] pl-4">
                              <span className="block truncate font-medium text-foreground">{row.productName}</span>
                              <span className="block font-mono text-caption text-muted-foreground">{row.sku}</span>
                            </TableCell>
                            <TableCell className="text-right text-muted-foreground tabular">
                              {row.quantity} {row.uomCode}
                            </TableCell>
                            {row.cells.map((cell) => {
                              const isSelected = selectedSupplierId === cell.supplierId;
                              return (
                                <TableCell
                                  key={cell.supplierId}
                                  className={cn(
                                    "text-right align-top",
                                    cell.isLowest && "bg-success-subtle/50",
                                    isSelected && "ring-1 ring-primary/40 ring-inset",
                                  )}
                                >
                                  {cell.isAvailable ? (
                                    <button
                                      type="button"
                                      disabled={!canDecide}
                                      onClick={() => canDecide && isOpen && chooseSupplier(view, row, cell)}
                                      className="w-full text-right outline-none disabled:cursor-default"
                                    >
                                      <span
                                        className={cn(
                                          "block font-semibold tabular",
                                          cell.isLowest ? "text-success-subtle-foreground" : "text-foreground",
                                        )}
                                      >
                                        {formatCurrency(cell.unitPrice)}
                                      </span>
                                      <span className="block text-caption text-muted-foreground tabular">
                                        {formatCurrency(cell.lineTotal)}
                                      </span>
                                      <span className="block text-[11px] text-muted-foreground tabular">
                                        +{cell.gstRate}% GST
                                      </span>
                                      {cell.note && (
                                        <span className="mt-0.5 block text-[11px] text-muted-foreground">
                                          {cell.note}
                                        </span>
                                      )}
                                      {isSelected && (
                                        <span className="mt-1 inline-flex items-center gap-1 text-[11px] font-medium text-primary">
                                          <Check className="size-3" />
                                          Selected
                                        </span>
                                      )}
                                    </button>
                                  ) : (
                                    <span className="flex flex-col items-end text-muted-foreground">
                                      <Minus className="size-4" />
                                      <span className="text-[11px]">{cell.note ?? "Not quoted"}</span>
                                    </span>
                                  )}
                                </TableCell>
                              );
                            })}
                            <TableCell className="w-[190px] max-w-[190px] pr-4 whitespace-normal">
                              {row.recommendedSupplierId ? (
                                <span className="flex items-center gap-1.5">
                                  <Crown className="size-3.5 shrink-0 text-warning" />
                                  <span className="truncate text-[13px] font-medium text-foreground">
                                    {shortName(
                                      suppliers.find((s) => s.supplierId === row.recommendedSupplierId)?.name ?? "",
                                    )}
                                  </span>
                                </span>
                              ) : (
                                <span className="text-[13px] text-muted-foreground">No recommendation</span>
                              )}
                              <span className="mt-0.5 line-clamp-2 block text-caption text-muted-foreground">
                                {row.recommendationReason}
                              </span>
                              {row.priceSpreadPct > 0 && (
                                <span className="mt-0.5 block text-[11px] text-muted-foreground tabular">
                                  Spread: {formatPercent(row.priceSpreadPct, 1)}
                                </span>
                              )}
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              </SectionCard>

              <SectionCard
                title="Commercial Terms"
                description="Price alone is not the decision — these change the real cost"
              >
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead className="pl-4">Term</TableHead>
                        {suppliers.map((s) => (
                          <TableHead key={s.supplierId} className="min-w-[150px]">
                            {shortName(s.name)}
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {view.terms.map((term) => (
                        <TableRow key={term.label}>
                          <TableCell className="pl-4 font-medium text-foreground">{term.label}</TableCell>
                          {suppliers.map((s) => (
                            <TableCell
                              key={s.supplierId}
                              className={cn(term.bestSupplierId === s.supplierId && "bg-success-subtle/50")}
                            >
                              <span className="flex items-center gap-1.5">
                                <span
                                  className={cn(
                                    term.bestSupplierId === s.supplierId
                                      ? "font-medium text-success-subtle-foreground"
                                      : "text-muted-foreground",
                                  )}
                                >
                                  {term.values[s.supplierId]}
                                </span>
                                {term.bestSupplierId === s.supplierId && (
                                  <Badge variant="success" className="px-1.5 py-0">
                                    Best
                                  </Badge>
                                )}
                              </span>
                            </TableCell>
                          ))}
                        </TableRow>
                      ))}

                      <TableRow className="bg-muted/45 hover:bg-muted/45">
                        <TableCell className="pl-4 font-semibold text-foreground">Total</TableCell>
                        {suppliers.map((s) => (
                          <TableCell key={s.supplierId} className="font-semibold text-foreground tabular">
                            {s.missingLines > 0 ? (
                              <span className="flex flex-col">
                                <span>{formatCurrency(s.total)}</span>
                                <span className="text-[11px] font-normal text-warning-subtle-foreground">
                                  {s.missingLines} item{s.missingLines === 1 ? "" : "s"} not quoted
                                </span>
                              </span>
                            ) : (
                              formatCurrency(s.total)
                            )}
                          </TableCell>
                        ))}
                      </TableRow>
                    </TableBody>
                  </Table>
                </div>
              </SectionCard>

              <FormError message={selectLine.error} fieldErrors={selectLine.fieldErrors} />
              <FormError message={convert.error} fieldErrors={convert.fieldErrors} />

              {!isOpen && (
                <div className="flex flex-col gap-2 rounded-xl border border-border bg-muted/40 px-4 py-3 sm:flex-row sm:items-center">
                  <p className="text-[13.5px] text-foreground">
                    {view.comparison.status === "converted"
                      ? "This comparison has been converted to purchase orders. The selections above are what was ordered."
                      : "This comparison was discarded."}
                  </p>
                  {view.comparison.status === "converted" && (
                    <Button variant="outline" size="sm" asChild className="sm:ml-auto">
                      <Link href="/procurement/purchase-orders">View purchase orders</Link>
                    </Button>
                  )}
                </div>
              )}

              {isOpen && (
              <PermissionGate permission="comparison.convert">
                <div className="sticky bottom-0 z-20 flex flex-col gap-3 rounded-xl border border-border bg-card/95 px-4 py-3 shadow-elevated backdrop-blur lg:flex-row lg:items-center">
                  <div className="min-w-0">
                    <p className="text-[13.5px] font-medium text-foreground">
                      Creates one purchase order per supplier you&apos;ve chosen across these lines
                    </p>
                    <p className="text-caption text-muted-foreground">
                      {view.rows.length} items · {formatCurrency(view.totals.splitTotal)} incl. GST
                      {view.totals.projectedSavings > 0 &&
                        ` · saves ${formatCurrency(view.totals.projectedSavings)}`}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 lg:ml-auto">
                    <Select value={deliveryGodownId} onValueChange={(v) => setDeliveryGodownId(v)}>
                      <SelectTrigger className="w-[200px]">
                        <SelectValue placeholder="Deliver to..." />
                      </SelectTrigger>
                      <SelectContent>
                        {godowns.map((g) => (
                          <SelectItem key={g.id} value={g.id}>
                            {g.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      disabled={!deliveryGodownId || convert.isPending}
                      onClick={() =>
                        convert.run({ comparisonId: view.comparison.id, deliveryGodownId: deliveryGodownId as Id })
                      }
                    >
                      <FileText />
                      {convert.isPending ? "Converting..." : "Convert to Purchase Order(s)"}
                    </Button>
                  </div>
                </div>
              </PermissionGate>
              )}

              <Dialog open={!!pendingOverride} onOpenChange={(next) => !next && setPendingOverride(null)}>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Choose a supplier other than the recommendation?</DialogTitle>
                    <DialogDescription>
                      Say why, so the decision is on record for anyone reviewing this comparison later.
                    </DialogDescription>
                  </DialogHeader>
                  <DialogBody className="space-y-2">
                    <Label htmlFor="override-reason">Reason</Label>
                    <Textarea
                      id="override-reason"
                      value={overrideReason}
                      onChange={(e) => setOverrideReason(e.target.value)}
                      rows={3}
                      placeholder="e.g. Preferred supplier for this category, faster delivery..."
                    />
                  </DialogBody>
                  <DialogFooter>
                    <Button variant="outline" onClick={() => setPendingOverride(null)}>
                      Cancel
                    </Button>
                    <Button disabled={selectLine.isPending} onClick={() => confirmOverride(view)}>
                      {selectLine.isPending && <Loader2 className="animate-spin" />}
                      Confirm Selection
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
