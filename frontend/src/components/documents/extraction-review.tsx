"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  Check,
  CircleCheck,
  FileSpreadsheet,
  Sparkles,
  ThumbsDown,
  TriangleAlert,
} from "lucide-react";

import { AiField, ConfidenceMeter, ProvenanceTag } from "@/components/ai/ai-provenance";
import { AsyncBoundary, FormError } from "@/components/common/async-state";
import { PermissionGate } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { useProducts } from "@/hooks/use-catalog";
import {
  useApproveExtraction,
  useConfirmLineMatch,
  useCorrectExtractedField,
  useExtraction,
  useRejectExtraction,
  useSkipExtractedLine,
} from "@/hooks/use-documents";
import { MATCH_LABELS } from "@/lib/api/documents.api";
import { formatCurrency } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Provenance } from "@/types";

/**
 * Review an AI extraction before it becomes business data.
 *
 * Three things this screen is careful about:
 *
 *  - It says how each line was matched — which rung of the ladder produced the
 *    suggestion and how confident it was — instead of presenting a guess as an
 *    answer (C8).
 *  - The totals shown are the app's own recomputation of the reviewed lines,
 *    not the figures printed on the supplier's document (BR-AI-02).
 *  - Nothing reaches a quotation, invoice or inventory table until Approve is
 *    pressed, and Approve stays disabled while anything is unresolved
 *    (BR-AI-01, BR-AI-04).
 */

export function ExtractionReview({ documentId }: { documentId: string }) {
  const router = useRouter();
  const state = useExtraction(documentId);
  const products = useProducts({ limit: 500, sort: "name" });

  const [saveAlias, setSaveAlias] = React.useState<Record<string, boolean>>({});
  const [fieldDrafts, setFieldDrafts] = React.useState<Record<string, string>>({});

  // Every one of these re-reads the extraction. Against the mock repository
  // the screen re-queried a store it shared with the writer, so this looked
  // unnecessary; against real HTTP it is the difference between confirming
  // a match and watching nothing happen. `canApprove`, the unresolved count
  // and the totals preview are all decided by the server, so the screen has
  // to ask again rather than patch its own copy.
  const refresh = React.useCallback(() => state.refresh(), [state]);
  const correctField = useCorrectExtractedField(refresh);
  const confirmMatch = useConfirmLineMatch(refresh);
  const skipLine = useSkipExtractedLine(refresh);
  const approve = useApproveExtraction((result) => {
    router.push(`/procurement/quotations/${result.promotedToId}`);
  });
  const reject = useRejectExtraction(() => router.push("/ai-documents"));

  return (
    <AsyncBoundary state={state}>
      {(view) => {
        // Locked once a decision has been *made* — not while one is being
        // made. `in_review` means somebody is working on it, which is the
        // state the controls exist for.
        const reviewed =
          view.extraction.reviewStatus === "approved" || view.extraction.reviewStatus === "rejected";
        const blockers = view.unresolvedCount + view.fieldsNeedingReview;

        return (
          <div className="space-y-4">
            <Alert variant="ai">
              <Sparkles />
              <AlertDescription>
                <span className="font-medium">
                  You are reviewing AI-generated information before it becomes official business
                  data.
                </span>{" "}
                Every value below shows where it came from. Edit anything that looks wrong, then
                approve.
              </AlertDescription>
            </Alert>

            <FormError message={approve.error ?? reject.error ?? confirmMatch.error} />

            {reviewed && (
              <Alert variant={view.extraction.reviewStatus === "approved" ? "success" : "destructive"}>
                <CircleCheck />
                <AlertDescription>
                  {view.extraction.reviewStatus === "approved" ? (
                    <>
                      Approved and promoted to{" "}
                      {view.extraction.promotedToType?.replace(/_/g, " ") ?? "a business document"}.
                    </>
                  ) : (
                    <>
                      Rejected. Nothing was written to your records.
                      {view.extraction.rejectionReason && ` — ${view.extraction.rejectionReason}`}
                    </>
                  )}
                </AlertDescription>
              </Alert>
            )}

            <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
              {/* ------------------ Left: source and pipeline ------------------ */}
              <div className="xl:col-span-5">
                <SectionCard
                  title="Original Document"
                  description={view.document.originalFilename}
                  className="xl:sticky xl:top-20"
                >
                  <div className="p-4">
                    <div className="rounded-lg border border-border bg-muted/40 p-3">
                      <div className="mb-3 flex items-center gap-2 border-b border-border pb-2.5">
                        <FileSpreadsheet className="size-4 text-success" />
                        <span className="text-[12.5px] font-medium text-foreground">
                          {view.document.originalFilename}
                        </span>
                        <Badge variant="neutral" className="ml-auto">
                          {view.extraction.pageCount} page
                          {view.extraction.pageCount === 1 ? "" : "s"}
                        </Badge>
                      </div>

                      {/* What the supplier actually wrote, unmodified. */}
                      <div className="overflow-x-auto rounded-md border border-border bg-card">
                        <table className="w-full text-[11.5px]">
                          <tbody className="divide-y divide-border">
                            <tr className="bg-muted/60 font-medium">
                              <td className="px-2 py-1">Item Description (as printed)</td>
                              <td className="px-2 py-1 text-right">Qty</td>
                              <td className="px-2 py-1 text-right">Rate</td>
                              <td className="px-2 py-1 text-right">GST</td>
                            </tr>
                            {view.lines.map((line) => (
                              <tr key={line.id}>
                                <td className="px-2 py-1">{line.rawDescription}</td>
                                <td className="px-2 py-1 text-right tabular">{line.quantity}</td>
                                <td className="px-2 py-1 text-right tabular">{line.unitPrice}</td>
                                <td className="px-2 py-1 text-right tabular">{line.gstRate}%</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>

                    <div className="mt-4">
                      <p className="text-[12px] font-medium text-muted-foreground">
                        How this result was reached
                      </p>
                      <ol className="mt-2 space-y-2">
                        {view.extraction.pipelineTrace.map((step) => (
                          <li key={step.step} className="flex items-start gap-2.5">
                            <span
                              className={cn(
                                "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full text-[9px] font-bold",
                                step.state === "done"
                                  ? "bg-success text-success-foreground"
                                  : "bg-warning text-[oklch(0.26_0.05_70)]",
                              )}
                            >
                              {step.state === "done" ? <Check className="size-2.5" /> : "!"}
                            </span>
                            <span className="min-w-0">
                              <span className="block text-[12.5px] font-medium text-foreground">
                                {step.step}
                              </span>
                              <span className="block text-[11.5px] text-muted-foreground">
                                {step.result}
                              </span>
                            </span>
                          </li>
                        ))}
                      </ol>
                      {/* What actually ran, and what did not. Every
                          provider says so in its own note — configured ones
                          included, because a configured model is still not
                          used for everything (product matching by meaning is
                          not enabled), and the screen must not imply it was. */}
                      {view.providers.length > 0 && (
                        <ul className="mt-3 space-y-1">
                          {view.providers
                            .map((provider) => (
                              <li key={provider.kind} className="text-[11px] text-muted-foreground">
                                {provider.note}
                              </li>
                            ))}
                        </ul>
                      )}
                      {view.job?.durationMs != null && (
                        <p className="mt-2 text-[11px] text-muted-foreground">
                          Read in {view.job.durationMs} ms.
                        </p>
                      )}
                    </div>
                  </div>
                </SectionCard>
              </div>

              {/* ------------------ Right: extracted data ------------------ */}
              <div className="space-y-4 xl:col-span-7">
                <SectionCard
                  title="Extracted Details"
                  description="Edit any value — your edit replaces the AI's and is recorded against your name"
                  action={<ConfidenceMeter value={view.extraction.overallConfidence} />}
                >
                  <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2">
                    {view.fields.map((field) => {
                      const value =
                        fieldDrafts[field.id] ??
                        field.correctedValue ??
                        field.normalisedValue ??
                        field.rawValue;
                      return (
                        <AiField
                          key={field.id}
                          label={field.fieldLabel}
                          provenance={field.provenance as Provenance}
                          hint={
                            field.validationError ??
                            (field.provenance === "needs_review"
                              ? `AI was unsure here — it read "${field.rawValue}"`
                              : undefined)
                          }
                        >
                          <Input
                            value={value}
                            disabled={reviewed}
                            onChange={(e) =>
                              setFieldDrafts((prev) => ({ ...prev, [field.id]: e.target.value }))
                            }
                            onBlur={() => {
                              const draft = fieldDrafts[field.id];
                              if (draft !== undefined && draft !== value) return;
                              if (draft !== undefined) {
                                correctField.run({ fieldId: field.id, value: draft });
                              }
                            }}
                            className="h-8.5"
                          />
                        </AiField>
                      );
                    })}
                  </div>
                </SectionCard>

                <SectionCard
                  title="Line Items"
                  description={
                    view.unresolvedCount > 0
                      ? `${view.unresolvedCount} item${view.unresolvedCount === 1 ? "" : "s"} could not be matched to your catalogue`
                      : "All items matched to your catalogue"
                  }
                >
                  <ul className="divide-y divide-border">
                    {view.lines.map((line) => {
                      // Settled means a *decision* exists — either the
                      // ladder's deterministic rungs made one, or a person
                      // did. A `matchedVariantId` with no decision behind it
                      // is the AI's guess, and BR-AI-04 says a guess from a
                      // non-deterministic rung is shown for confirmation,
                      // never rendered as though it were resolved.
                      const matchedId = line.finalVariantId;
                      const suggestedId = line.matchedVariantId;
                      const matched = matchedId
                        ? { sku: line.matchedSku, name: line.matchedProductName }
                        : undefined;
                      const skipped = line.finalDecision === "skipped";

                      return (
                        <li key={line.id} className="p-4">
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <div className="min-w-0">
                              <p className="text-[12px] text-muted-foreground">Supplier wrote</p>
                              <p className="font-mono text-[12.5px] text-foreground">
                                {line.rawDescription}
                              </p>
                              {line.supplierSku && (
                                <p className="text-[11.5px] text-muted-foreground">
                                  Their code: {line.supplierSku}
                                </p>
                              )}
                            </div>
                            <div className="flex items-center gap-2">
                              <ProvenanceTag provenance={line.provenance as Provenance} />
                              <ConfidenceMeter value={line.confidence} showBar={false} />
                            </div>
                          </div>

                          <div
                            className={cn(
                              "mt-3 rounded-lg border p-3",
                              skipped
                                ? "border-border bg-muted/50"
                                : matchedId
                                  ? "border-border bg-muted/35"
                                  : "border-warning/35 bg-warning-subtle/45",
                            )}
                          >
                            {skipped ? (
                              <p className="text-[13px] text-muted-foreground">
                                Skipped — this line will not be carried into the quotation.
                              </p>
                            ) : matchedId ? (
                              <div className="space-y-1.5">
                                <div className="flex flex-wrap items-center gap-2">
                                  <CircleCheck className="size-4 shrink-0 text-success" />
                                  <span className="text-[13.5px] font-medium text-foreground">
                                    {matched?.name ?? line.normalisedDescription}
                                  </span>
                                  <span className="font-mono text-[12px] text-muted-foreground">
                                    {matched?.sku}
                                  </span>
                                </div>
                                {/* Which rung of the ladder produced this, in plain words. */}
                                <p className="text-[11.5px] text-muted-foreground">
                                  Matched by{" "}
                                  <span className="font-medium text-foreground/80">
                                    {line.matchMethod ? MATCH_LABELS[line.matchMethod] : "a person"}
                                  </span>
                                  {line.matchScore != null &&
                                    ` · ${Math.round(line.matchScore * 100)}% similarity`}
                                  {line.aliasSaved && " · their code is saved against this SKU"}
                                </p>
                              </div>
                            ) : (
                              <div className="space-y-2.5">
                                <p className="flex items-center gap-2 text-[13px] font-medium text-warning-subtle-foreground">
                                  <TriangleAlert className="size-4 shrink-0" />
                                  {suggestedId
                                    ? "Best guess only — confirm it or pick another"
                                    : "No confident match — choose the right product"}
                                </p>
                                {line.suggestionText && (
                                  <p className="text-[11.5px] text-muted-foreground">
                                    {line.suggestionText}
                                  </p>
                                )}

                                {line.candidates.length > 0 && (
                                  <ul className="space-y-1.5">
                                    {line.candidates.slice(0, 3).map((candidate) => (
                                      <li
                                        key={candidate.id}
                                        className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-card px-2.5 py-1.5"
                                      >
                                        <span className="text-[12.5px] font-medium text-foreground">
                                          {candidate.productName}
                                        </span>
                                        <span className="font-mono text-[11.5px] text-muted-foreground">
                                          {candidate.sku}
                                        </span>
                                        <span className="text-[11px] text-muted-foreground">
                                          {MATCH_LABELS[candidate.matchMethod]} ·{" "}
                                          {Math.round(candidate.confidence)}%
                                          {candidate.reasons.length > 0 &&
                                            ` · ${candidate.reasons[0]}`}
                                        </span>
                                        <Button
                                          size="sm"
                                          variant="outline"
                                          className="ml-auto"
                                          data-testid={`use-candidate-${line.lineNo}`}
                                          disabled={reviewed || confirmMatch.isPending}
                                          onClick={() =>
                                            confirmMatch.run({
                                              extractedLineId: line.id,
                                              productVariantId: candidate.productVariantId,
                                              saveAlias: saveAlias[line.id] ?? true,
                                            })
                                          }
                                        >
                                          Use this
                                        </Button>
                                      </li>
                                    ))}
                                  </ul>
                                )}

                                <Select
                                  disabled={reviewed}
                                  onValueChange={(variantId) =>
                                    confirmMatch.run({
                                      extractedLineId: line.id,
                                      productVariantId: variantId,
                                      saveAlias: saveAlias[line.id] ?? true,
                                    })
                                  }
                                >
                                  <SelectTrigger size="sm" className="bg-card sm:max-w-[340px]">
                                    <SelectValue placeholder="Or pick any product..." />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {(products.data?.items ?? []).map((p) => (
                                      <SelectItem key={p.id} value={p.id}>
                                        {p.name} · {p.sku}
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>

                                {line.supplierSku && (
                                  <label className="flex items-center gap-2 text-[12px] text-muted-foreground">
                                    <Checkbox
                                      checked={saveAlias[line.id] ?? true}
                                      onCheckedChange={(checked) =>
                                        setSaveAlias((prev) => ({
                                          ...prev,
                                          [line.id]: checked === true,
                                        }))
                                      }
                                    />
                                    Remember that {line.supplierSku} means this product — next time
                                    this line matches itself.
                                  </label>
                                )}

                                <Button
                                  variant="ghost"
                                  size="sm"
                                  data-testid={`skip-line-${line.lineNo}`}
                                  disabled={reviewed || skipLine.isPending}
                                  onClick={() =>
                                    skipLine.run({
                                      extractedLineId: line.id,
                                      reason: "Not stocked — excluded from the quotation",
                                    })
                                  }
                                >
                                  Skip this line
                                </Button>
                              </div>
                            )}
                          </div>

                          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                            {[
                              { label: "Quantity", value: `${line.quantity} ${line.rawUom ?? ""}`.trim() },
                              { label: "Unit Price", value: formatCurrency(line.unitPrice) },
                              { label: "GST", value: `${line.gstRate}%` },
                              {
                                label: "Printed total",
                                value:
                                  line.lineTotalAsPrinted != null
                                    ? formatCurrency(line.lineTotalAsPrinted)
                                    : "—",
                              },
                            ].map((cell) => (
                              <div key={cell.label}>
                                <p className="text-[11.5px] text-muted-foreground">{cell.label}</p>
                                <p className="text-[13.5px] font-medium text-foreground tabular">
                                  {cell.value}
                                </p>
                              </div>
                            ))}
                          </div>
                        </li>
                      );
                    })}
                  </ul>

                  <div className="space-y-1.5 border-t border-border bg-muted/35 px-4 py-3">
                    <p className="text-[11.5px] text-muted-foreground">
                      Recalculated from the reviewed lines — not the totals printed on the document.
                    </p>
                    <div className="flex items-center justify-between text-[13px]">
                      <span className="text-muted-foreground">Taxable value</span>
                      <span className="font-medium text-foreground tabular">
                        {formatCurrency(view.totals.subtotal)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-[13px]">
                      <span className="text-muted-foreground">GST</span>
                      <span className="font-medium text-foreground tabular">
                        {formatCurrency(view.totals.tax)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between border-t border-border pt-1.5 text-[14px]">
                      <span className="font-medium text-foreground">Total</span>
                      <span className="text-[16px] font-semibold text-foreground tabular">
                        {formatCurrency(view.totals.total)}
                      </span>
                    </div>
                  </div>
                </SectionCard>

                {!reviewed && (
                  <div className="sticky bottom-0 z-20 flex flex-col gap-2 rounded-xl border border-border bg-card/95 px-4 py-3 shadow-elevated backdrop-blur sm:flex-row sm:items-center">
                    <p className="text-[13px] text-muted-foreground">
                      {blockers === 0 ? (
                        <span className="flex items-center gap-1.5 text-success-subtle-foreground">
                          <CircleCheck className="size-4" />
                          Everything reviewed — ready to approve
                        </span>
                      ) : (
                        <span className="flex items-center gap-1.5 text-warning-subtle-foreground">
                          <TriangleAlert className="size-4" />
                          {view.unresolvedCount > 0 &&
                            `${view.unresolvedCount} unmatched line${view.unresolvedCount === 1 ? "" : "s"}`}
                          {view.unresolvedCount > 0 && view.fieldsNeedingReview > 0 && " · "}
                          {view.fieldsNeedingReview > 0 &&
                            `${view.fieldsNeedingReview} field${view.fieldsNeedingReview === 1 ? "" : "s"} to confirm`}
                        </span>
                      )}
                    </p>
                    <div className="flex items-center gap-2 sm:ml-auto">
                      <PermissionGate permission="ai.review">
                        <Button
                          variant="outline"
                          disabled={reject.isPending}
                          onClick={() =>
                            reject.run({
                              documentId,
                              reason: "Rejected during review",
                            })
                          }
                        >
                          <ThumbsDown />
                          Reject
                        </Button>
                      </PermissionGate>
                      <PermissionGate permission="ai.approve_extraction">
                        <Button
                          variant="success"
                          onClick={() => approve.run({ documentId })}
                          data-testid="approve-extraction"
                          disabled={!view.canApprove || approve.isPending}
                        >
                          <Check />
                          {approve.isPending ? "Approving..." : "Approve and create quotation"}
                        </Button>
                      </PermissionGate>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      }}
    </AsyncBoundary>
  );
}
