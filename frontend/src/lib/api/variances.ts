/**
 * Document variances — one mapper for every screen that shows them.
 *
 * The backend returns the same `VarianceOut` shape from the proforma, the
 * supplier invoice and (since the receiving phase) the goods receipt, so
 * the wording lives here rather than being written twice with two
 * slightly different sentences.
 */

import type { DocumentVariance } from "@/types";

export interface VarianceOut {
  id: string;
  variance_type: DocumentVariance["varianceType"];
  comparison_kind: DocumentVariance["comparisonKind"];
  base_doc_type: string;
  base_doc_id: string;
  base_line_id: string | null;
  compare_doc_type: string;
  compare_doc_id: string;
  compare_line_id: string | null;
  product_variant_id: string | null;
  sku: string;
  product_name: string;
  base_value: number;
  compare_value: number;
  difference: number;
  difference_pct: number;
  severity: DocumentVariance["severity"];
  status: DocumentVariance["status"];
  resolved_by: string | null;
  resolved_at: string | null;
  resolution_note: string | null;
}

/** What the difference is being measured against — the sentence only reads
 * correctly if it names the right side of the comparison. */
function baseline(kind: DocumentVariance["comparisonKind"]): string {
  switch (kind) {
    case "grn_vs_po":
      return "what was ordered";
    case "proforma_vs_po":
    case "invoice_vs_po":
      return "the purchase order";
    default:
      return "what was received";
  }
}

export function varianceLabel(v: VarianceOut): string {
  const subject = v.sku || v.product_name || "This document";
  const direction = v.difference > 0 ? "more than" : "less than";
  const amount = Math.abs(v.difference);
  switch (v.variance_type) {
    case "price":
      return `${subject}: billed ₹${amount.toLocaleString("en-IN")} ${direction} the agreed rate`;
    case "quantity":
      return `${subject}: ${amount} ${direction} ${baseline(v.comparison_kind)}`;
    case "product":
      return `${subject}: the wrong item was delivered`;
    case "total":
      return `Document total is ₹${amount.toLocaleString("en-IN")} ${direction} expected`;
    default:
      return `${subject}: differs by ${amount}`;
  }
}

export function toVariance(v: VarianceOut): DocumentVariance {
  return {
    id: v.id,
    varianceType: v.variance_type,
    comparisonKind: v.comparison_kind,
    baseDocType: v.base_doc_type,
    baseDocId: v.base_doc_id,
    baseLineId: v.base_line_id,
    compareDocType: v.compare_doc_type,
    compareDocId: v.compare_doc_id,
    compareLineId: v.compare_line_id,
    productVariantId: v.product_variant_id,
    label: varianceLabel(v),
    baseValue: v.base_value,
    compareValue: v.compare_value,
    difference: v.difference,
    differencePct: v.difference_pct,
    severity: v.severity,
    status: v.status,
    resolvedBy: v.resolved_by,
    resolvedAt: v.resolved_at,
    resolutionNote: v.resolution_note ?? undefined,
    alertId: null,
  };
}
