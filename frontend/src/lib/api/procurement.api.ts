/**
 * RFQ → Quotation → Comparison → Purchase Order → Proforma.
 *
 * Every step talks to the real FastAPI backend (`/procurement/rfqs`,
 * `/procurement/quotations`, `/procurement/comparisons`,
 * `/procurement/purchase-orders`, `/proforma-invoices`).
 *
 * Three corrections from the original prototype still apply throughout:
 *
 *  - Documents are addressed by id. `getPurchaseOrder(id)` takes the PO's id,
 *    not its number, and every link between documents is an id column (C12).
 *  - Totals come from the money engine, and inter-state is derived from the
 *    supplier's state versus the place of supply (C13, C14). The backend
 *    computes the saved figures; this file only previews them in forms.
 *  - Status changes are checked against that document's own transition
 *    table where a state machine still runs client-side (quotations,
 *    proforma); RFQ/PO status changes are now specific backend action
 *    endpoints instead (C7).
 */

import { round2, taxBreakdown } from "@/lib/domain/money";
import {
  allowedTransitions,
  proformaTransitions,
  purchaseOrderTransitions,
  rfqTransitions,
} from "@/lib/domain/state-machines";
// `query` filters, sorts and pages rows already fetched from the API.
import { indexById, query } from "./list-query";
import type {
  ComparisonCell,
  ComparisonRowView,
  ComparisonView,
  DocumentVariance,
  Id,
  ListParams,
  ListResponse,
  PoLineStatus,
  Percent,
  ProformaInvoice,
  ProformaInvoiceItem,
  PurchaseOrder,
  PurchaseOrderItem,
  PurchaseOrderStatus,
  Quantity,
  QuotationComparison,
  QuotationComparisonLine,
  Rfq,
  RfqItem,
  RfqStatus,
  RfqSupplier,
  RfqSupplierStatus,
  SupplierQuotation,
  SupplierQuotationItem,
} from "@/types";
import {
  httpDelete,
  httpGet,
  httpPatch,
  httpPost,
  httpUpload,
  notFound,
  reject,
  validationFailed,
} from "./client";

/* ------------------------------------------------------------- Utilities */

// Every section of this file now talks to the real backend — RFQ, Purchase
// Order, Quotation, Comparison, Proforma and Variances. The mock-reading
// name helpers that used to live here went with the Proforma rewrite: the
// API returns supplier and product names alongside the ids, so there is
// nothing left to look up locally, and mock ids never matched real ones
// anyway.

export interface LineInput {
  productVariantId: Id;
  description?: string;
  quantity: Quantity;
  uomId: Id;
  unitPrice: number;
  discountPct?: Percent;
  gstRate?: Percent;
  rfqItemId?: Id | null;
  quotationItemId?: Id | null;
  expectedDeliveryDate?: string | null;
}

/* --------------------------------------------------- Real master-data maps */

/** Minimal shapes read off the (now real) catalog/supplier endpoints, just
 * enough to label RFQ/PO lines for display. */
interface VariantLite {
  id: string;
  product_id: string;
  sku: string;
  hsn_code: string | null;
  gst_rate: number | null;
}
interface ProductLite {
  id: string;
  name: string;
  hsn_code: string;
  gst_rate: number;
}
interface UomLite {
  id: string;
  code: string;
}
interface GodownLite {
  id: string;
  name: string;
  state_code: string;
}
interface SupplierLite {
  id: string;
  name: string;
  gstin: string | null;
}
interface GrnLite {
  id: string;
  grn_number: string;
  grn_date: string;
  status: string;
  purchase_order_id: string | null;
}

/** Fetches the master-data lookups RFQ/PO detail screens need to label
 * lines — variant/product/uom/godown/supplier are all real now (Assignment
 * A), so these are real HTTP calls, not mock table reads. */
async function fetchMasterMaps() {
  const [variants, products, uoms, godowns, suppliers] = await Promise.all([
    httpGet<VariantLite[]>("/catalog/variants", { limit: 500 }),
    httpGet<ProductLite[]>("/catalog/products", { limit: 500 }),
    // `/catalog/uoms-available`, not the tenant-scoped `/catalog/uoms` —
    // line items almost always reference one of the 9 shared system units
    // (company_id IS NULL), which the tenant-scoped list never returns.
    httpGet<UomLite[]>("/catalog/uoms-available"),
    httpGet<GodownLite[]>("/catalog/godowns", { limit: 500 }),
    httpGet<SupplierLite[]>("/catalog/suppliers", { limit: 500 }),
  ]);
  return {
    variantsById: indexById(variants),
    productsById: indexById(products),
    uomsById: indexById(uoms),
    godownsById: indexById(godowns),
    suppliersById: indexById(suppliers),
  };
}

/* ------------------------------------------------------------------ RFQ */

/** `/procurement/rfqs` — see the wiring brief's RFQ section. */
interface RfqItemOut {
  id: string;
  line_no: number;
  product_variant_id: string | null;
  description: string | null;
  quantity: number;
  uom_id: string;
  expected_price: number;
  target_delivery_date: string | null;
  remarks: string | null;
}
interface RfqSupplierOut {
  id: string;
  supplier_id: string;
  status: string;
  sent_at: string | null;
  responded_at: string | null;
}
interface RfqOut {
  id: string;
  rfq_number: string;
  rfq_date: string;
  expected_delivery_date: string | null;
  subject: string | null;
  delivery_godown_id: string | null;
  notes: string | null;
  status: string;
  sent_at: string | null;
  closed_at: string | null;
  estimated_value: number;
  created_from: string | null;
  row_version: number;
  external_source_name: string | null;
  external_reference_number: string | null;
  source_file_name: string | null;
  items: RfqItemOut[];
  suppliers: RfqSupplierOut[];
  created_at: string;
  updated_at: string;
}

function toRfqItem(rfqId: Id, i: RfqItemOut): RfqItem {
  return {
    id: i.id,
    rfqId,
    lineNo: i.line_no,
    productVariantId: i.product_variant_id,
    description: i.description ?? "",
    quantity: i.quantity,
    uomId: i.uom_id,
    expectedPrice: i.expected_price,
    remarks: i.remarks ?? undefined,
  };
}

function toRfqSupplier(rfqId: Id, s: RfqSupplierOut): RfqSupplier {
  return {
    id: s.id,
    rfqId,
    supplierId: s.supplier_id,
    status: s.status as RfqSupplierStatus,
    sentAt: s.sent_at,
    respondedAt: s.responded_at,
  };
}

function toRfq(r: RfqOut): Rfq {
  return {
    id: r.id,
    rfqNumber: r.rfq_number,
    rfqDate: r.rfq_date,
    expectedDeliveryDate: r.expected_delivery_date,
    subject: r.subject ?? "",
    deliveryGodownId: r.delivery_godown_id,
    notes: r.notes ?? "",
    // This backend only ever reaches draft/sent/cancelled (no quotation
    // intake) — the wider `RfqStatus` type is still a safe superset cast.
    status: r.status as RfqStatus,
    sentAt: r.sent_at,
    closedAt: r.closed_at,
    estimatedValue: r.estimated_value,
    createdFrom: (r.created_from as Rfq["createdFrom"]) ?? "manual",
    // No `created_at` timestamp on `RfqOut` — not read anywhere in the
    // current UI, so this is a safe simplification (same gap
    // catalog.api.ts documents for products/variants/godowns).
    createdAt: r.created_at,
    updatedAt: r.updated_at,
    rowVersion: r.row_version,
    externalSourceName: r.external_source_name,
    externalReferenceNumber: r.external_reference_number,
    sourceFileName: r.source_file_name,
  };
}

export interface RfqListRow extends Rfq {
  supplierCount: number;
  quotesReceived: number;
  itemCount: number;
  godownName: string;
}

export async function listRfqs(params: ListParams = {}): Promise<ListResponse<RfqListRow>> {
  // No free-text search/sort on the backend (rule 7) — fetch a generously
  // large page and let `query()` do the rest client-side.
  const [rfqsOut, godowns] = await Promise.all([
    httpGet<RfqOut[]>("/procurement/rfqs", { limit: 500 }),
    httpGet<GodownLite[]>("/catalog/godowns", { limit: 500 }),
  ]);
  const godownsById = indexById(godowns);
  const rows: RfqListRow[] = rfqsOut.map((r) => {
    const rfq = toRfq(r);
    return {
      ...rfq,
      supplierCount: r.suppliers.length,
      quotesReceived: r.suppliers.filter((s) => s.status === "quoted").length,
      itemCount: r.items.length,
      godownName: rfq.deliveryGodownId ? godownsById.get(rfq.deliveryGodownId)?.name ?? "" : "",
    };
  });
  return query(rows as unknown as Record<string, unknown>[], params, {
    searchFields: ["rfqNumber", "subject", "notes"],
    dateField: "rfqDate",
    facetFields: ["status"],
    defaultSort: "-rfqDate",
  }) as unknown as ListResponse<RfqListRow>;
}

export interface RfqDetail {
  rfq: Rfq;
  items: (RfqItem & { sku: string; productName: string; uomCode: string })[];
  suppliers: (RfqSupplier & { supplierName: string; quotationId: Id | null; quotationNumber: string | null })[];
  quotations: SupplierQuotation[];
  godownName: string;
  allowedActions: RfqStatus[];
}

export async function getRfq(rfqId: Id): Promise<RfqDetail> {
  // `httpGet` throws a 404 `ApiError` on a missing id automatically.
  const r = await httpGet<RfqOut>(`/procurement/rfqs/${rfqId}`);
  const maps = await fetchMasterMaps();
  // Quotations recorded against this RFQ. This used to read the mock
  // repository with a comment saying quotation intake had no backend — it
  // has had one since the quotation phase, and the endpoint takes an
  // `rfq_id` filter, so the panel was quietly showing nothing on every
  // real RFQ.
  const quotations = (
    await httpGet<QuotationOut[]>("/procurement/quotations", { rfq_id: rfqId, limit: 200 })
  ).map(toQuotation);

  return {
    rfq: toRfq(r),
    items: r.items.map((i) => {
      const variant = i.product_variant_id ? maps.variantsById.get(i.product_variant_id) : undefined;
      return {
        ...toRfqItem(rfqId, i),
        sku: variant?.sku ?? "",
        productName: variant ? maps.productsById.get(variant.product_id)?.name ?? "" : i.description ?? "",
        uomCode: maps.uomsById.get(i.uom_id)?.code ?? "",
      };
    }),
    suppliers: r.suppliers.map((s) => {
      const quote = quotations.find((q) => q.supplierId === s.supplier_id);
      return {
        ...toRfqSupplier(rfqId, s),
        supplierName: maps.suppliersById.get(s.supplier_id)?.name ?? "",
        quotationId: quote?.id ?? null,
        quotationNumber: quote?.quotationNumber ?? null,
      };
    }),
    quotations,
    godownName: r.delivery_godown_id ? maps.godownsById.get(r.delivery_godown_id)?.name ?? "" : "",
    allowedActions: allowedTransitions(rfqTransitions, r.status as RfqStatus),
  };
}

export interface RfqInput {
  subject: string;
  rfqDate: string;
  expectedDeliveryDate: string | null;
  deliveryGodownId: Id | null;
  notes: string;
  supplierIds: Id[];
  items: { productVariantId: Id; quantity: Quantity; uomId: Id; expectedPrice: number; remarks?: string }[];
  createdFrom?: Rfq["createdFrom"];
}

export async function createRfq(input: RfqInput, sendNow = false): Promise<Rfq> {
  const errors: { field: string; message: string }[] = [];
  if (!input.subject.trim()) errors.push({ field: "subject", message: "Give the RFQ a subject." });
  if (!input.items.length) errors.push({ field: "items", message: "Add at least one item." });
  if (sendNow && !input.supplierIds.length) {
    errors.push({ field: "suppliers", message: "Choose at least one supplier to send to." });
  }
  input.items.forEach((line, i) => {
    if (!line.quantity || line.quantity <= 0) {
      errors.push({ field: `items.${i}.quantity`, message: "Quantity must be greater than zero." });
    }
  });
  if (errors.length) validationFailed(errors);

  const created = await httpPost<RfqOut>("/procurement/rfqs", {
    rfq_date: input.rfqDate,
    expected_delivery_date: input.expectedDeliveryDate ?? undefined,
    subject: input.subject.trim(),
    delivery_godown_id: input.deliveryGodownId ?? undefined,
    notes: input.notes,
    items: input.items.map((l) => ({
      product_variant_id: l.productVariantId,
      quantity: l.quantity,
      uom_id: l.uomId,
      expected_price: l.expectedPrice,
      remarks: l.remarks,
    })),
  });

  if (sendNow) {
    // The backend only attaches suppliers to an RFQ at send time — there is
    // no separate "create with these suppliers pre-attached" field on
    // `RfqCreate`.
    const sent = await httpPost<RfqOut>(`/procurement/rfqs/${created.id}/send`, {
      supplier_ids: input.supplierIds,
    });
    return toRfq(sent);
  }
  // Judgment call / known gap: when saving as a draft, any suppliers the
  // buyer pre-selected have nowhere to persist — the backend has no
  // "attach suppliers to a draft" endpoint, only "send to these suppliers
  // now". `input.supplierIds` is therefore simply not recorded until the
  // RFQ is actually sent. See `sendRfq` below for the consequence.
  return toRfq(created);
}

/* -------------------------------------------------------------- Import */

export type RfqImportField =
  | "description"
  | "quantity"
  | "uom"
  | "price"
  | "item_code"
  | "make"
  | "hsn"
  | "remarks";

export interface RfqImportPreviewRow {
  sourceRow: number;
  description: string;
  quantity: number;
  uomId: Id;
  uomCode: string;
  expectedPrice: number;
  remarks?: string | null;
}

/** One RFQ field and the column of the file that feeds it. */
export interface RfqImportColumn {
  field: RfqImportField;
  label: string;
  required: boolean;
  columnIndex: number | null;
  header: string | null;
  /** 0-100; 100 for a saved or hand-picked mapping. */
  confidence: number;
  /** How it was matched: heading synonyms (exact/contains/similar), the
   *  column's values, AI reading the heading, the language model (checked
   *  against the values), a saved layout, or the person. */
  match: "exact" | "contains" | "similar" | "values" | "ai" | "llm" | "saved" | "manual" | null;
  /** Why, for values/ai/llm matches. */
  reason: string | null;
}

export interface RfqImportPreview {
  rows: RfqImportPreviewRow[];
  errors: string[];
  warnings: string[];
  rowCount: number;
  sheetNames: string[];
  sheetIndex: number;
  /** 1-based row the column headings were read from. */
  headerRow: number | null;
  headers: string[];
  sampleRows: string[][];
  columns: RfqImportColumn[];
  missingRequired: RfqImportField[];
  /** `saved`: a layout imported before was recognised. */
  layoutSource: "auto" | "saved" | "manual";
  columnMap: Partial<Record<RfqImportField, number>>;
}

/** The person's overrides from the mapping step. Anything left out is
 *  detected server-side. */
export interface RfqImportOptions {
  columnMap?: Partial<Record<RfqImportField, number>> | null;
  headerRow?: number | null;
  sheetIndex?: number | null;
  defaultUomId?: Id | null;
}

interface RfqImportPreviewOut {
  rows: {
    source_row: number;
    description: string;
    quantity: number;
    uom_id: string;
    uom_code: string;
    expected_price: number;
    remarks: string | null;
  }[];
  errors: string[];
  warnings: string[];
  row_count: number;
  sheet_names: string[];
  sheet_index: number;
  header_row: number | null;
  headers: string[];
  sample_rows: string[][];
  columns: {
    field: RfqImportField;
    label: string;
    required: boolean;
    column_index: number | null;
    header: string | null;
    confidence: number;
    match: RfqImportColumn["match"];
    reason?: string | null;
  }[];
  missing_required: RfqImportField[];
  layout_source: RfqImportPreview["layoutSource"];
  column_map: Partial<Record<RfqImportField, number>>;
}

function importFields(options: RfqImportOptions = {}): Record<string, string | undefined> {
  return {
    column_map: options.columnMap ? JSON.stringify(options.columnMap) : undefined,
    header_row: options.headerRow ? String(options.headerRow) : undefined,
    sheet_index: options.sheetIndex != null ? String(options.sheetIndex) : undefined,
    default_uom_id: options.defaultUomId ?? undefined,
  };
}

/**
 * Parses the file and reports what it found, how it mapped the columns, and
 * what's wrong — writes nothing. Call again with `options` after the person
 * changes the mapping; `importRfq` must then be given the same options.
 */
export async function previewRfqImport(file: File, options: RfqImportOptions = {}): Promise<RfqImportPreview> {
  const out = await httpUpload<RfqImportPreviewOut>(
    "/procurement/rfqs/import/preview",
    file,
    importFields(options),
  );
  return {
    rows: out.rows.map((r) => ({
      sourceRow: r.source_row,
      description: r.description,
      quantity: r.quantity,
      uomId: r.uom_id,
      uomCode: r.uom_code,
      expectedPrice: r.expected_price,
      remarks: r.remarks,
    })),
    errors: out.errors,
    warnings: out.warnings ?? [],
    rowCount: out.row_count,
    sheetNames: out.sheet_names ?? [],
    sheetIndex: out.sheet_index ?? 0,
    headerRow: out.header_row,
    headers: out.headers ?? [],
    sampleRows: out.sample_rows ?? [],
    columns: (out.columns ?? []).map((c) => ({
      field: c.field,
      label: c.label,
      required: c.required,
      columnIndex: c.column_index,
      header: c.header,
      confidence: c.confidence,
      match: c.match,
      reason: c.reason ?? null,
    })),
    missingRequired: out.missing_required ?? [],
    layoutSource: out.layout_source ?? "auto",
    columnMap: out.column_map ?? {},
  };
}

export interface RfqImportInput extends RfqImportOptions {
  externalSourceName: string;
  externalReferenceNumber?: string;
  subject?: string;
  deliveryGodownId?: Id;
}

/**
 * Re-parses the same file server-side with the same mapping and, if it's
 * still clean, creates the RFQ from it (`created_from: 'imported'`). The
 * mapping is saved, so the next file with this header row maps itself.
 * Every line is free-text sourced (BR-RFQ-02) rather than matched to a
 * catalogue SKU at import time — the result is a normal draft RFQ, editable
 * like any other, so linking lines to SKUs is a follow-up edit.
 */
export async function importRfq(file: File, input: RfqImportInput): Promise<Rfq> {
  if (!input.externalSourceName.trim()) {
    validationFailed([{ field: "externalSourceName", message: "Say where this RFQ came from." }]);
  }
  const created = await httpUpload<RfqOut>("/procurement/rfqs/import", file, {
    external_source_name: input.externalSourceName.trim(),
    external_reference_number: input.externalReferenceNumber?.trim(),
    subject: input.subject?.trim(),
    delivery_godown_id: input.deliveryGodownId,
    ...importFields(input),
  });
  return toRfq(created);
}

export async function sendRfq(rfqId: Id): Promise<Rfq> {
  // Flagged judgment call: this function's signature (inherited from the
  // mock version) takes no supplier list, because the mock kept a
  // "pending" supplier roster attached to every RFQ from the moment it was
  // created. The real backend has no such roster — suppliers are attached
  // only inside this same `/send` call. So a genuine draft created via
  // `createRfq(..., false)` has zero suppliers recorded server-side, and
  // there is nothing here to send to. The best this function can do
  // without a signature change is re-send to whichever suppliers the RFQ
  // *already* has recorded (e.g. retrying a previous send); if it has
  // none, it fails with a clear, catchable error rather than silently
  // sending to nobody.
  const current = await httpGet<RfqOut>(`/procurement/rfqs/${rfqId}`);
  if (!current.suppliers.length) {
    reject(
      "This RFQ has no suppliers recorded yet. Choose suppliers and send from the RFQ form — sending a draft later isn't supported yet.",
      "BR-RFQ-02",
    );
  }
  const sent = await httpPost<RfqOut>(`/procurement/rfqs/${rfqId}/send`, {
    supplier_ids: current.suppliers.map((s) => s.supplier_id),
  });
  return toRfq(sent);
}

export async function cancelRfq(rfqId: Id, reason: string): Promise<Rfq> {
  const out = await httpPost<RfqOut>(`/procurement/rfqs/${rfqId}/cancel`, { reason });
  return toRfq(out);
}

export async function deleteRfqDraft(rfqId: Id): Promise<void> {
  // Draft-only is server-enforced (404/409 on anything else).
  await httpDelete(`/procurement/rfqs/${rfqId}`);
}

/* ----------------------------------------------------------- Quotations */

/** `/procurement/quotations` — see the wiring brief's Quotation section. */
interface QuotationItemOut {
  id: string;
  line_no: number;
  rfq_item_id: string | null;
  product_variant_id: string | null;
  raw_description: string | null;
  supplier_sku: string | null;
  quantity: number;
  uom_id: string;
  unit_price: number;
  discount_pct: number;
  gst_rate: number;
  cess_rate: number;
  line_net: number;
  line_tax: number;
  line_total: number;
  is_available: boolean;
  availability_note: string | null;
  lead_time_days: number | null;
  provenance: string;
}
interface QuotationOut {
  id: string;
  quotation_number: string;
  supplier_id: string;
  rfq_id: string | null;
  quotation_date: string;
  valid_until: string | null;
  currency_code: string;
  subtotal: number;
  discount_amount: number;
  taxable_value: number;
  tax_amount: number;
  freight_amount: number;
  other_charges: number;
  round_off: number;
  total_amount: number;
  payment_terms: string | null;
  delivery_terms: string | null;
  delivery_period_days: number | null;
  warranty_terms: string | null;
  freight_terms: string | null;
  source: string;
  status: string;
  approved_by: string | null;
  approved_at: string | null;
  rejected_reason: string | null;
  row_version: number;
  items: QuotationItemOut[];
  is_expired: boolean;
  item_count: number;
  created_at: string;
  updated_at: string;
}

function toQuotationItem(quotationId: Id, i: QuotationItemOut): SupplierQuotationItem {
  return {
    id: i.id,
    quotationId,
    lineNo: i.line_no,
    rfqItemId: i.rfq_item_id,
    productVariantId: i.product_variant_id,
    rawDescription: i.raw_description ?? "",
    supplierSku: i.supplier_sku ?? undefined,
    quantity: i.quantity,
    uomId: i.uom_id,
    unitPrice: i.unit_price,
    discountPct: i.discount_pct,
    gstRate: i.gst_rate,
    cessRate: i.cess_rate,
    lineNet: i.line_net,
    lineTax: i.line_tax,
    lineTotal: i.line_total,
    isAvailable: i.is_available,
    availabilityNote: i.availability_note ?? undefined,
    leadTimeDays: i.lead_time_days ?? undefined,
    // The backend doesn't run any matching for a manually-entered line — the
    // buyer picked the product themselves — so there's no confidence/method
    // to report (both stay unset rather than a fabricated "100%/manual").
    matchConfidence: undefined,
    matchMethod: undefined,
    provenance: i.provenance as SupplierQuotationItem["provenance"],
  };
}

function toQuotation(q: QuotationOut): SupplierQuotation {
  return {
    id: q.id,
    quotationNumber: q.quotation_number,
    supplierId: q.supplier_id,
    rfqId: q.rfq_id,
    quotationDate: q.quotation_date,
    validUntil: q.valid_until,
    currencyCode: q.currency_code,
    subtotal: q.subtotal,
    discountAmount: q.discount_amount,
    taxableValue: q.taxable_value,
    taxAmount: q.tax_amount,
    freightAmount: q.freight_amount,
    otherCharges: q.other_charges,
    roundOff: q.round_off,
    totalAmount: q.total_amount,
    paymentTerms: q.payment_terms ?? "",
    deliveryTerms: q.delivery_terms ?? "",
    deliveryPeriodDays: q.delivery_period_days,
    warrantyTerms: q.warranty_terms ?? "",
    freightTerms: q.freight_terms ?? "",
    // This backend only ever writes 'manual' (no AI-extraction pipeline
    // yet) — the wider `QuotationSource` type is still a safe superset cast.
    source: q.source as SupplierQuotation["source"],
    documentId: null,
    aiExtractionResultId: null,
    extractionConfidence: null,
    status: q.status as SupplierQuotation["status"],
    approvedBy: q.approved_by,
    approvedAt: q.approved_at,
    rejectedReason: q.rejected_reason ?? undefined,
    createdAt: q.created_at,
    updatedAt: q.updated_at,
    rowVersion: q.row_version,
  };
}

/** Only these two are reachable as direct backend actions from `draft`/
 * `under_review` (approve/reject) — `expired`/`superseded`/`converted` are
 * either computed on read or reached through the comparison-convert flow,
 * never set directly on the quotation itself. */
function quotationAllowedActions(status: string): SupplierQuotation["status"][] {
  return status === "draft" || status === "under_review" ? ["approved", "rejected"] : [];
}

export interface QuotationListRow extends SupplierQuotation {
  supplierName: string;
  rfqNumber: string | null;
  itemCount: number;
  isExpired: boolean;
}

export async function listQuotations(params: ListParams = {}): Promise<ListResponse<QuotationListRow>> {
  // No free-text search/sort on the backend (rule 7) — fetch a generously
  // large page and let `query()` do the rest client-side, same as RFQ/PO.
  const [quotationsOut, suppliers, rfqs] = await Promise.all([
    httpGet<QuotationOut[]>("/procurement/quotations", { limit: 500 }),
    httpGet<SupplierLite[]>("/catalog/suppliers", { limit: 500 }),
    httpGet<RfqOut[]>("/procurement/rfqs", { limit: 500 }),
  ]);
  const suppliersById = indexById(suppliers);
  const rfqsById = indexById(rfqs);
  const rows: QuotationListRow[] = quotationsOut.map((q) => {
    const quotation = toQuotation(q);
    return {
      ...quotation,
      supplierName: suppliersById.get(q.supplier_id)?.name ?? "",
      rfqNumber: q.rfq_id ? rfqsById.get(q.rfq_id)?.rfq_number ?? null : null,
      itemCount: q.item_count,
      isExpired: q.is_expired,
    };
  });
  return query(rows as unknown as Record<string, unknown>[], params, {
    searchFields: ["quotationNumber", "supplierName", "rfqNumber"],
    dateField: "quotationDate",
    facetFields: ["status", "source", "supplierId"],
    defaultSort: "-quotationDate",
  }) as unknown as ListResponse<QuotationListRow>;
}

export interface QuotationDetail {
  quotation: SupplierQuotation;
  supplierName: string;
  rfqNumber: string | null;
  items: (SupplierQuotationItem & { sku: string; productName: string; uomCode: string })[];
  taxRows: ReturnType<typeof taxBreakdown>;
  isExpired: boolean;
  allowedActions: SupplierQuotation["status"][];
}

export async function getQuotation(quotationId: Id): Promise<QuotationDetail> {
  const q = await httpGet<QuotationOut>(`/procurement/quotations/${quotationId}`);
  const [maps, rfqNumber] = await Promise.all([
    fetchMasterMaps(),
    q.rfq_id
      ? httpGet<{ rfq_number: string }>(`/procurement/rfqs/${q.rfq_id}`)
          .then((r) => r.rfq_number)
          .catch(() => null)
      : Promise.resolve(null),
  ]);

  return {
    quotation: toQuotation(q),
    supplierName: maps.suppliersById.get(q.supplier_id)?.name ?? "",
    rfqNumber,
    items: q.items.map((i) => {
      const variant = i.product_variant_id ? maps.variantsById.get(i.product_variant_id) : undefined;
      return {
        ...toQuotationItem(quotationId, i),
        sku: variant?.sku ?? "",
        productName: variant ? maps.productsById.get(variant.product_id)?.name ?? "" : i.raw_description ?? "",
        uomCode: maps.uomsById.get(i.uom_id)?.code ?? "",
      };
    }),
    // Quotation totals have no CGST/SGST/IGST split server-side either
    // (there's no delivery godown yet to derive inter-state from) — one
    // combined `tax_amount`, same as the backend. `false` here only picks
    // which GST columns `taxBreakdown` renders, not a claim about the
    // supplier's actual state.
    taxRows: taxBreakdown(
      q.items
        .filter((i) => i.is_available)
        .map((i) => ({
          quantity: i.quantity,
          unitPrice: i.unit_price,
          discountPct: i.discount_pct,
          gstRate: i.gst_rate,
          cessRate: i.cess_rate,
        })),
      false,
    ),
    isExpired: q.is_expired,
    allowedActions: quotationAllowedActions(q.status),
  };
}

export interface QuotationInput {
  quotationNumber: string;
  supplierId: Id;
  rfqId: Id | null;
  quotationDate: string;
  validUntil: string | null;
  paymentTerms: string;
  deliveryTerms: string;
  deliveryPeriodDays: number | null;
  warrantyTerms: string;
  freightTerms: string;
  freightAmount?: number;
  otherCharges?: number;
  lines: (LineInput & { isAvailable?: boolean; availabilityNote?: string; supplierSku?: string })[];
  source?: SupplierQuotation["source"];
  documentId?: Id | null;
}

/** Manual quotation entry — the path for a quote that arrived by phone (I3). */
export async function createQuotation(input: QuotationInput): Promise<SupplierQuotation> {
  const errors: { field: string; message: string }[] = [];
  if (!input.quotationNumber.trim()) {
    errors.push({ field: "quotationNumber", message: "Enter the supplier's own quotation number." });
  }
  if (!input.supplierId) errors.push({ field: "supplierId", message: "Choose a supplier." });
  if (!input.lines.length) errors.push({ field: "lines", message: "Add at least one line." });
  if (input.validUntil && input.validUntil < input.quotationDate) {
    errors.push({ field: "validUntil", message: "Validity cannot be before the quotation date." });
  }
  input.lines.forEach((line, i) => {
    if (line.isAvailable === false) return;
    if (!line.quantity || line.quantity <= 0) {
      errors.push({ field: `lines.${i}.quantity`, message: "Quantity must be greater than zero." });
    }
    if (line.unitPrice < 0) {
      errors.push({ field: `lines.${i}.unitPrice`, message: "Rate cannot be negative." });
    }
  });
  if (errors.length) validationFailed(errors);

  const created = await httpPost<QuotationOut>("/procurement/quotations", {
    supplier_id: input.supplierId,
    rfq_id: input.rfqId ?? undefined,
    quotation_number: input.quotationNumber.trim(),
    quotation_date: input.quotationDate,
    valid_until: input.validUntil ?? undefined,
    payment_terms: input.paymentTerms,
    delivery_terms: input.deliveryTerms,
    delivery_period_days: input.deliveryPeriodDays ?? undefined,
    warranty_terms: input.warrantyTerms,
    freight_terms: input.freightTerms,
    freight_amount: input.freightAmount ?? 0,
    other_charges: input.otherCharges ?? 0,
    items: input.lines.map((l) => ({
      rfq_item_id: l.rfqItemId ?? undefined,
      product_variant_id: l.productVariantId,
      raw_description: l.description,
      supplier_sku: l.supplierSku,
      quantity: l.quantity,
      uom_id: l.uomId,
      unit_price: l.unitPrice,
      discount_pct: l.discountPct ?? 0,
      // `gstRate` is set on every line by the quotation form (from the
      // product's own rate, or its 18% default) — a caller that omits it
      // gets 0% rather than a guessed rate.
      gst_rate: l.gstRate ?? 0,
      is_available: l.isAvailable !== false,
      availability_note: l.isAvailable === false ? l.availabilityNote : undefined,
    })),
  });
  // The RFQ's `sent → partially_quoted/quoted` derivation (BR-RFQ-06) runs
  // server-side now (`_sync_rfq_status_on_quotation`) — nothing to do here.
  return toQuotation(created);
}

export async function setQuotationStatus(
  quotationId: Id,
  status: SupplierQuotation["status"],
  reason?: string,
): Promise<SupplierQuotation> {
  if (status === "approved") {
    const out = await httpPost<QuotationOut>(`/procurement/quotations/${quotationId}/approve`);
    return toQuotation(out);
  }
  if (status === "rejected") {
    if (!reason?.trim()) reject("Give a reason so the supplier can be told why.", "BR-QT-04");
    const out = await httpPost<QuotationOut>(`/procurement/quotations/${quotationId}/reject`, { reason });
    return toQuotation(out);
  }
  // Every call site in this app only ever passes "approved" or "rejected"
  // (see `quotation-form.tsx`'s detail page and `delete-quotation-button.tsx`).
  // The backend has no generic status-setter — `under_review`/`expired`/
  // `superseded`/`converted` are each reached a different way (computed on
  // read, or via the comparison-convert flow) — so anything else is a
  // programming error at the call site, not a business-rule failure.
  reject(`Setting a quotation directly to "${status}" isn't supported by this backend.`, "NOT_SUPPORTED");
}

/* ----------------------------------------------------------- Comparison */

/** `/procurement/comparisons` — see the wiring brief's Comparison section. */
interface ComparisonCellOut {
  supplier_id: string;
  quotation_id: string;
  quotation_item_id: string;
  unit_price: number;
  landed_unit_cost: number;
  line_total: number;
  gst_rate: number;
  is_available: boolean;
  availability_note: string | null;
  is_lowest: boolean;
}
interface ComparisonRowOut {
  line_id: string | null;
  rfq_item_id: string;
  product_variant_id: string | null;
  quantity: number;
  cells: ComparisonCellOut[];
  recommended_quotation_item_id: string | null;
  recommended_supplier_id: string | null;
  recommendation_reason: string | null;
  recommendation_score: number | null;
  price_spread_pct: number | null;
  selected_quotation_item_id: string | null;
  selected_supplier_id: string | null;
  override_reason: string | null;
}
interface ComparisonSupplierOut {
  supplier_id: string;
  name: string;
  quotation_id: string;
  quotation_number: string;
  valid_until: string | null;
  is_expired: boolean;
  total_amount: number;
  missing_lines: number;
}
interface ComparisonWarningOut {
  code: string;
  rfq_item_id?: string;
  supplier_id?: string;
  spread_pct?: number;
  valid_until?: string;
}
interface ComparisonOut {
  id: string;
  rfq_id: string;
  name: string | null;
  strategy: string;
  status: string;
  single_supplier_best_total: number | null;
  split_total: number | null;
  projected_savings: number | null;
  notes: string | null;
  suppliers: ComparisonSupplierOut[];
  rows: ComparisonRowOut[];
  warnings: ComparisonWarningOut[];
  created_at: string;
  updated_at: string;
}

/** Build the human-readable message the mock used to bake into the row
 * itself — the real backend returns only the code + raw context (I5: never
 * stored prose), so the message is assembled here from data already on the
 * comparison. */
function comparisonWarningMessage(
  w: ComparisonWarningOut,
  rowsByRfqItem: Map<Id, ComparisonRowView>,
  suppliersById: Map<Id, { name: string }>,
): string {
  if (w.code === "PRICE_SPREAD_HIGH") {
    const row = w.rfq_item_id ? rowsByRfqItem.get(w.rfq_item_id) : undefined;
    return `${(w.spread_pct ?? 0).toFixed(1)}% spread on ${row?.productName ?? "this line"} — check the specification matches.`;
  }
  if (w.code === "QUOTATION_EXPIRING") {
    const supplier = w.supplier_id ? suppliersById.get(w.supplier_id) : undefined;
    return `${supplier?.name ?? "A supplier"}'s quote expires on ${w.valid_until}.`;
  }
  return w.code;
}

/** Assemble the screen-ready `ComparisonView` from the backend's
 * `ComparisonOut` plus the RFQ items (for uom/description) and master-data
 * labels the response doesn't carry. */
async function assembleComparisonView(c: ComparisonOut): Promise<ComparisonView> {
  const [rfq, maps, quotationsForRfq] = await Promise.all([
    httpGet<RfqOut>(`/procurement/rfqs/${c.rfq_id}`),
    fetchMasterMaps(),
    httpGet<QuotationOut[]>("/procurement/quotations", { rfq_id: c.rfq_id, limit: 500 }),
  ]);
  const rfqItemsById = indexById(rfq.items);
  const quotationIds = new Set(c.suppliers.map((s) => s.quotation_id));

  const suppliers = c.suppliers.map((s) => ({
    supplierId: s.supplier_id,
    name: s.name,
    quotationId: s.quotation_id,
    quotationNumber: s.quotation_number,
    validUntil: s.valid_until,
    isExpired: s.is_expired,
    total: s.total_amount,
    missingLines: s.missing_lines,
  }));
  const suppliersById = indexById(suppliers.map((s) => ({ id: s.supplierId, ...s })));

  const rows: ComparisonRowView[] = c.rows.map((row) => {
    const rfqItem = rfqItemsById.get(row.rfq_item_id);
    const variant = row.product_variant_id ? maps.variantsById.get(row.product_variant_id) : undefined;
    const productName = variant
      ? maps.productsById.get(variant.product_id)?.name ?? ""
      : rfqItem?.description ?? "";
    const cellsBySupplier = indexById(row.cells.map((cell) => ({ id: cell.supplier_id, ...cell })));
    // The backend only emits a cell for a supplier that actually quoted this
    // line (`_gather_matrix` builds cells from matching quotation items, not
    // from every compared supplier) — synthesize a "not quoted" cell for any
    // supplier missing one, so every row has exactly one cell per supplier
    // column, in the same order, the way the comparison table assumes.
    const cells: ComparisonCell[] = suppliers.map((s) => {
      const cell = cellsBySupplier.get(s.supplierId);
      if (!cell) {
        return {
          supplierId: s.supplierId,
          supplierName: s.name,
          quotationId: s.quotationId,
          quotationItemId: "",
          unitPrice: 0,
          lineTotal: 0,
          gstRate: 0,
          isAvailable: false,
          note: "Not quoted",
          isLowest: false,
        };
      }
      return {
        supplierId: cell.supplier_id,
        supplierName: s.name,
        quotationId: cell.quotation_id,
        quotationItemId: cell.quotation_item_id,
        unitPrice: cell.unit_price,
        lineTotal: cell.line_total,
        gstRate: cell.gst_rate,
        isAvailable: cell.is_available,
        note: cell.availability_note ?? undefined,
        isLowest: cell.is_lowest,
      };
    });

    return {
      rfqItemId: row.rfq_item_id,
      productVariantId: row.product_variant_id,
      sku: variant?.sku ?? "",
      productName,
      quantity: row.quantity,
      uomCode: rfqItem ? maps.uomsById.get(rfqItem.uom_id)?.code ?? "" : "",
      cells,
      recommendedSupplierId: row.recommended_supplier_id,
      // Computed server-side from the quotes on the table, not stored
      // prose (I5) — see `comparison_service._gather_matrix`.
      recommendationReason: row.recommendation_reason ?? "No supplier quoted this line",
      recommendationScore: row.recommendation_score ?? 0,
      priceSpreadPct: row.price_spread_pct ?? 0,
    };
  });
  const rowsByRfqItem = indexById(rows.map((r) => ({ id: r.rfqItemId, ...r })));

  const lines: QuotationComparisonLine[] = c.rows.map((row) => {
    const rfqItem = rfqItemsById.get(row.rfq_item_id);
    const rowView = rowsByRfqItem.get(row.rfq_item_id);
    return {
      id: row.line_id ?? `${c.id}_${row.rfq_item_id}`,
      comparisonId: c.id,
      rfqItemId: row.rfq_item_id,
      productVariantId: row.product_variant_id,
      description: rowView?.productName ?? "",
      quantity: row.quantity,
      uomId: rfqItem?.uom_id ?? "",
      selectedQuotationItemId: row.selected_quotation_item_id,
      selectedSupplierId: row.selected_supplier_id,
      recommendedQuotationItemId: row.recommended_quotation_item_id,
      recommendedSupplierId: row.recommended_supplier_id,
      recommendationReason: row.recommendation_reason ?? "",
      recommendationScore: row.recommendation_score ?? 0,
      priceSpreadPct: row.price_spread_pct ?? 0,
      overrideReason: row.override_reason ?? undefined,
    };
  });

  // Backend gives only the single-supplier-baseline *total* — match it back
  // to the (necessarily unique among full-coverage suppliers) supplier it
  // belongs to, so the screen can name them.
  const bestSupplier =
    c.single_supplier_best_total != null
      ? suppliers.find((s) => s.missingLines === 0 && Math.abs(s.total - c.single_supplier_best_total!) < 0.005)
      : undefined;
  const splitTotal = c.split_total ?? 0;
  const singleBestTotal = c.single_supplier_best_total ?? 0;
  const projectedSavings =
    c.single_supplier_best_total != null ? round2(singleBestTotal - splitTotal) : c.projected_savings ?? 0;

  const comparison: QuotationComparison = {
    id: c.id,
    rfqId: c.rfq_id,
    name: c.name ?? rfq.subject ?? "",
    comparedSupplierIds: suppliers.map((s) => s.supplierId),
    strategy: c.strategy as QuotationComparison["strategy"],
    singleSupplierBestSupplierId: bestSupplier?.supplierId ?? null,
    singleSupplierBestTotal: singleBestTotal,
    splitTotal,
    projectedSavings,
    status: c.status as QuotationComparison["status"],
    notes: c.notes ?? undefined,
    createdAt: c.created_at,
  };

  const relevantQuotations = quotationsForRfq.filter((q) => quotationIds.has(q.id)).map(toQuotation);

  return {
    comparison,
    suppliers,
    rows,
    lines,
    terms: buildTerms(relevantQuotations),
    totals: {
      lowestSingleSupplierId: bestSupplier?.supplierId ?? null,
      lowestSingleSupplierTotal: singleBestTotal,
      splitTotal,
      projectedSavings,
    },
    warnings: c.warnings.map((w) => ({
      code: w.code,
      message: comparisonWarningMessage(w, rowsByRfqItem, suppliersById),
      rfqItemId: w.rfq_item_id,
      supplierId: w.supplier_id,
    })),
  };
}

export async function getComparison(comparisonId: Id): Promise<ComparisonView> {
  const c = await httpGet<ComparisonOut>(`/procurement/comparisons/${comparisonId}`);
  return assembleComparisonView(c);
}

/** Get (or build) the comparison for an RFQ from the quotes received. */
export async function getComparisonForRfq(rfqId: Id): Promise<ComparisonView> {
  const existing = await httpGet<ComparisonOut[]>("/procurement/comparisons", { rfq_id: rfqId, limit: 1 });
  const c = existing[0] ?? (await httpPost<ComparisonOut>("/procurement/comparisons", { rfq_id: rfqId }));
  return assembleComparisonView(c);
}

function buildTerms(quotations: SupplierQuotation[]): ComparisonView["terms"] {
  const value = (pick: (q: SupplierQuotation) => string) =>
    Object.fromEntries(quotations.map((q) => [q.supplierId, pick(q)]));
  const shortestDelivery = quotations.reduce(
    (best, q) => (q.deliveryPeriodDays !== null && (best === null || q.deliveryPeriodDays < (best.deliveryPeriodDays ?? Infinity)) ? q : best),
    null as SupplierQuotation | null,
  );
  const longestValidity = quotations.reduce(
    (best, q) => (q.validUntil && (best === null || (best.validUntil ?? "") < q.validUntil) ? q : best),
    null as SupplierQuotation | null,
  );
  return [
    { label: "Payment terms", values: value((q) => q.paymentTerms || "—") },
    { label: "Delivery terms", values: value((q) => q.deliveryTerms || "—") },
    {
      label: "Delivery period",
      values: value((q) => (q.deliveryPeriodDays !== null ? `${q.deliveryPeriodDays} days` : "—")),
      bestSupplierId: shortestDelivery?.supplierId,
    },
    { label: "Freight", values: value((q) => q.freightTerms || "—") },
    { label: "Warranty", values: value((q) => q.warrantyTerms || "—") },
    {
      label: "Valid until",
      values: value((q) => q.validUntil ?? "—"),
      bestSupplierId: longestValidity?.supplierId,
    },
  ];
}

/** Record a buyer's choice for one line, with a reason when it isn't the recommendation. */
export async function selectComparisonLine(
  comparisonId: Id,
  rfqItemId: Id,
  quotationItemId: Id,
  overrideReason?: string,
): Promise<void> {
  // The PATCH endpoint addresses a comparison *line* (`quotation_comparison_
  // lines.id`), not the RFQ item — this hook's signature predates the real
  // endpoint, so the current comparison is fetched once to resolve one to
  // the other.
  const current = await httpGet<ComparisonOut>(`/procurement/comparisons/${comparisonId}`);
  const row = current.rows.find((r) => r.rfq_item_id === rfqItemId);
  if (!row?.line_id) notFound("Comparison line");
  await httpPatch<ComparisonOut>(`/procurement/comparisons/${comparisonId}/lines/${row.line_id}`, {
    quotation_item_id: quotationItemId,
    reason: overrideReason,
  });
}

/**
 * Convert a decided comparison into one PO per chosen supplier. Lines with no
 * selection fall back to the recommendation — the backend does that same
 * fallback itself when `selections` is omitted.
 */
export async function convertComparisonToPos(comparisonId: Id, deliveryGodownId: Id): Promise<PurchaseOrder[]> {
  const result = await httpPost<{ purchase_orders: PoOut[]; comparison_status: string }>(
    `/procurement/comparisons/${comparisonId}/convert`,
    { delivery_godown_id: deliveryGodownId },
  );
  return result.purchase_orders.map(toPurchaseOrder);
}

/* ------------------------------------------------------- Purchase orders */

/** `/procurement/purchase-orders` — see the wiring brief's PO section. */
interface PoItemOut {
  id: string;
  line_no: number;
  product_variant_id: string;
  quotation_item_id: string | null;
  rfq_item_id: string | null;
  description: string | null;
  hsn_code: string | null;
  quantity: number;
  uom_id: string;
  conversion_factor: number;
  unit_price: number;
  discount_pct: number;
  gst_rate: number;
  cess_rate: number;
  line_net: number;
  line_tax: number;
  line_total: number;
  received_quantity: number;
  returned_quantity: number;
  invoiced_quantity: number;
  pending_quantity: number;
  line_status: string;
}
interface PoOut {
  id: string;
  po_number: string;
  supplier_id: string;
  rfq_id: string | null;
  quotation_id: string | null;
  comparison_id: string | null;
  po_date: string;
  expected_delivery_date: string | null;
  delivery_godown_id: string;
  payment_terms: string | null;
  delivery_terms: string | null;
  place_of_supply_state_code: string;
  is_inter_state: boolean;
  currency_code: string;
  subtotal: number;
  discount_amount: number;
  taxable_value: number;
  cgst_amount: number;
  sgst_amount: number;
  igst_amount: number;
  cess_amount: number;
  freight_amount: number;
  other_charges: number;
  round_off: number;
  total_amount: number;
  status: string;
  approved_by: string | null;
  approved_at: string | null;
  sent_at: string | null;
  cancelled_at: string | null;
  cancelled_by: string | null;
  cancelled_by_name: string | null;
  cancellation_reason: string | null;
  notes: string | null;
  received_pct: number;
  fully_received_at: string | null;
  row_version: number;
  created_at: string;
  updated_at: string;
  items: PoItemOut[];
}

function toPurchaseOrderItem(purchaseOrderId: Id, i: PoItemOut): PurchaseOrderItem {
  return {
    id: i.id,
    purchaseOrderId,
    lineNo: i.line_no,
    productVariantId: i.product_variant_id,
    quotationItemId: i.quotation_item_id,
    rfqItemId: i.rfq_item_id,
    description: i.description ?? "",
    hsnCode: i.hsn_code ?? "",
    quantity: i.quantity,
    uomId: i.uom_id,
    conversionFactor: i.conversion_factor,
    unitPrice: i.unit_price,
    discountPct: i.discount_pct,
    gstRate: i.gst_rate,
    cessRate: i.cess_rate,
    lineNet: i.line_net,
    lineTax: i.line_tax,
    lineTotal: i.line_total,
    receivedQuantity: i.received_quantity,
    returnedQuantity: i.returned_quantity,
    invoicedQuantity: i.invoiced_quantity,
    lineStatus: i.line_status as PoLineStatus,
    // Not echoed back either — known gap.
    expectedDeliveryDate: undefined,
  };
}

function toPurchaseOrder(o: PoOut): PurchaseOrder {
  return {
    id: o.id,
    poNumber: o.po_number,
    supplierId: o.supplier_id,
    rfqId: o.rfq_id,
    quotationId: o.quotation_id,
    comparisonId: o.comparison_id,
    poDate: o.po_date,
    expectedDeliveryDate: o.expected_delivery_date,
    deliveryGodownId: o.delivery_godown_id,
    paymentTerms: o.payment_terms ?? "",
    deliveryTerms: o.delivery_terms ?? "",
    placeOfSupplyStateCode: o.place_of_supply_state_code,
    isInterState: o.is_inter_state,
    currencyCode: o.currency_code,
    subtotal: o.subtotal,
    discountAmount: o.discount_amount,
    taxableValue: o.taxable_value,
    cgstAmount: o.cgst_amount,
    sgstAmount: o.sgst_amount,
    igstAmount: o.igst_amount,
    cessAmount: o.cess_amount,
    freightAmount: o.freight_amount,
    otherCharges: o.other_charges,
    roundOff: o.round_off,
    totalAmount: o.total_amount,
    status: o.status as PurchaseOrderStatus,
    approvedBy: o.approved_by,
    approvedAt: o.approved_at,
    sentAt: o.sent_at,
    cancelledAt: o.cancelled_at,
    cancelledBy: o.cancelled_by,
    cancelledByName: o.cancelled_by_name ?? undefined,
    cancellationReason: o.cancellation_reason ?? undefined,
    receivedPct: o.received_pct,
    fullyReceivedAt: o.fully_received_at,
    notes: o.notes ?? undefined,
    createdAt: o.created_at,
    updatedAt: o.updated_at,
    rowVersion: o.row_version,
  };
}

export interface PurchaseOrderListRow extends PurchaseOrder {
  supplierName: string;
  godownName: string;
  itemCount: number;
  isOverdue: boolean;
}

export async function listPurchaseOrders(params: ListParams = {}): Promise<ListResponse<PurchaseOrderListRow>> {
  const [posOut, godowns, suppliers] = await Promise.all([
    httpGet<PoOut[]>("/procurement/purchase-orders", { limit: 500 }),
    httpGet<GodownLite[]>("/catalog/godowns", { limit: 500 }),
    httpGet<SupplierLite[]>("/catalog/suppliers", { limit: 500 }),
  ]);
  const godownsById = indexById(godowns);
  const suppliersById = indexById(suppliers);
  const today = new Date().toISOString().slice(0, 10);
  const rows: PurchaseOrderListRow[] = posOut.map((po) => {
    const order = toPurchaseOrder(po);
    return {
      ...order,
      supplierName: suppliersById.get(po.supplier_id)?.name ?? "",
      godownName: godownsById.get(po.delivery_godown_id)?.name ?? "",
      itemCount: po.items.length,
      isOverdue:
        !!order.expectedDeliveryDate &&
        order.expectedDeliveryDate < today &&
        order.receivedPct < 100 &&
        !["draft", "cancelled", "closed"].includes(order.status),
    };
  });
  return query(rows as unknown as Record<string, unknown>[], params, {
    searchFields: ["poNumber", "supplierName", "notes"],
    dateField: "poDate",
    facetFields: ["status", "supplierId", "deliveryGodownId"],
    defaultSort: "-poDate",
  }) as unknown as ListResponse<PurchaseOrderListRow>;
}

export interface PurchaseOrderDetail {
  purchaseOrder: PurchaseOrder;
  supplierName: string;
  supplierGstin: string | null;
  godownName: string;
  items: (PurchaseOrderItem & {
    sku: string;
    productName: string;
    uomCode: string;
    pendingQuantity: Quantity;
  })[];
  taxRows: ReturnType<typeof taxBreakdown>;
  rfqNumber: string | null;
  quotationNumber: string | null;
  receipts: { id: Id; grnNumber: string; grnDate: string; status: string }[];
  proformas: { id: Id; proformaNumber: string; status: string; varianceAmount: number }[];
  invoices: { id: Id; invoiceNumber: string; status: string; matchStatus: string; totalAmount: number }[];
  variances: number;
  allowedActions: PurchaseOrder["status"][];
}

/** Only the fields the PO's related-documents panel shows. */
interface InvoiceLite {
  id: string;
  invoice_number: string;
  purchase_order_id: string | null;
  status: PurchaseOrderDetail["invoices"][number]["status"];
  match_status: PurchaseOrderDetail["invoices"][number]["matchStatus"];
  total_amount: number;
}

export async function getPurchaseOrder(purchaseOrderId: Id): Promise<PurchaseOrderDetail> {
  const po = await httpGet<PoOut>(`/procurement/purchase-orders/${purchaseOrderId}`);
  const maps = await fetchMasterMaps();
  const [rfqNumber, grns, quotationNumber, relatedProformas, relatedInvoices, relatedVariances] =
    await Promise.all([
      po.rfq_id
        ? httpGet<{ rfq_number: string }>(`/procurement/rfqs/${po.rfq_id}`)
            .then((r) => r.rfq_number)
            .catch(() => null)
        : Promise.resolve(null),
      // GRNs are wired for real too (this same assignment) — fetch the full
      // list and filter, same rule-7 pattern as everywhere else.
      httpGet<GrnLite[]>("/procurement/goods-receipts", { limit: 500 }).catch(() => [] as GrnLite[]),
      po.quotation_id
        ? httpGet<QuotationOut>(`/procurement/quotations/${po.quotation_id}`)
            .then((q) => q.quotation_number)
            .catch(() => null)
        : Promise.resolve(null),
      // Each of these is a document that points *at* this PO. A failed
      // lookup degrades the related-documents panel to empty rather than
      // failing the whole detail screen — the PO itself is the point.
      httpGet<ProformaOut[]>("/proforma-invoices", { limit: 500 })
        .then((rows) => rows.filter((pf) => pf.purchase_order_id === purchaseOrderId))
        .catch(() => [] as ProformaOut[]),
      httpGet<InvoiceLite[]>("/supplier-invoices", { limit: 500 })
        .then((rows) => rows.filter((inv) => inv.purchase_order_id === purchaseOrderId))
        .catch(() => [] as InvoiceLite[]),
      httpGet<VarianceOut[]>("/variances", { limit: 500 })
        .then((rows) => rows.filter((v) => v.base_doc_id === purchaseOrderId))
        .catch(() => [] as VarianceOut[]),
    ]);
  const order = toPurchaseOrder(po);

  return {
    purchaseOrder: order,
    supplierName: maps.suppliersById.get(po.supplier_id)?.name ?? "",
    supplierGstin: maps.suppliersById.get(po.supplier_id)?.gstin ?? null,
    godownName: maps.godownsById.get(po.delivery_godown_id)?.name ?? "",
    items: po.items.map((i) => {
      const variant = maps.variantsById.get(i.product_variant_id);
      return {
        ...toPurchaseOrderItem(purchaseOrderId, i),
        sku: variant?.sku ?? "",
        productName: variant ? maps.productsById.get(variant.product_id)?.name ?? "" : "",
        uomCode: maps.uomsById.get(i.uom_id)?.code ?? "",
        // The backend already computes this — use it directly rather than
        // re-deriving it from quantity/receivedQuantity.
        pendingQuantity: i.pending_quantity,
      };
    }),
    taxRows: taxBreakdown(
      po.items.map((i) => ({
        quantity: i.quantity,
        unitPrice: i.unit_price,
        discountPct: i.discount_pct,
        gstRate: i.gst_rate,
        cessRate: i.cess_rate,
      })),
      po.is_inter_state,
    ),
    rfqNumber,
    quotationNumber,
    receipts: grns
      .filter((g) => g.purchase_order_id === purchaseOrderId)
      .map((g) => ({ id: g.id, grnNumber: g.grn_number, grnDate: g.grn_date, status: g.status })),
    // These four panels used to read the mock repository and were therefore
    // always empty on a real PO. Proformas, supplier invoices and variances
    // all have backends now, so they show the documents that actually
    // reference this order.
    proformas: relatedProformas.map((pf) => ({
      id: pf.id,
      proformaNumber: pf.proforma_number,
      status: pf.status,
      varianceAmount: pf.variance_amount ?? 0,
    })),
    invoices: relatedInvoices.map((inv) => ({
      id: inv.id,
      invoiceNumber: inv.invoice_number,
      status: inv.status,
      matchStatus: inv.match_status,
      totalAmount: inv.total_amount,
    })),
    variances: relatedVariances.filter((v) => v.status === "open").length,
    allowedActions: allowedTransitions(purchaseOrderTransitions, order.status),
  };
}

export interface PurchaseOrderInput {
  supplierId: Id;
  rfqId?: Id | null;
  quotationId?: Id | null;
  comparisonId?: Id | null;
  poDate: string;
  expectedDeliveryDate: string | null;
  deliveryGodownId: Id;
  paymentTerms: string;
  deliveryTerms: string;
  freightAmount?: number;
  otherCharges?: number;
  notes?: string;
  lines: LineInput[];
  status?: PurchaseOrder["status"];
}

export async function createPurchaseOrder(input: PurchaseOrderInput): Promise<PurchaseOrder> {
  const errors: { field: string; message: string }[] = [];
  if (!input.supplierId) errors.push({ field: "supplierId", message: "Choose a supplier." });
  if (!input.deliveryGodownId) {
    errors.push({ field: "deliveryGodownId", message: "Choose where the goods should be delivered." });
  }
  if (!input.lines.length) errors.push({ field: "lines", message: "Add at least one line." });
  if (input.expectedDeliveryDate && input.expectedDeliveryDate < input.poDate) {
    errors.push({ field: "expectedDeliveryDate", message: "Delivery date cannot be before the PO date." });
  }
  input.lines.forEach((line, i) => {
    if (!line.productVariantId) errors.push({ field: `lines.${i}.productVariantId`, message: "Choose a product." });
    if (!line.quantity || line.quantity <= 0) {
      errors.push({ field: `lines.${i}.quantity`, message: "Quantity must be greater than zero." });
    }
    if (line.unitPrice < 0) errors.push({ field: `lines.${i}.unitPrice`, message: "Rate cannot be negative." });
    if ((line.discountPct ?? 0) < 0 || (line.discountPct ?? 0) > 100) {
      errors.push({ field: `lines.${i}.discountPct`, message: "Discount must be between 0 and 100." });
    }
  });
  if (errors.length) validationFailed(errors);

  // Real variant/product lookups (Assignment A), used only as a fallback
  // when a line doesn't specify its own gst_rate/hsn_code — mirrors the old
  // mock `gstRateFor`/`hsnFor` helpers, but backed by real data.
  const maps = await fetchMasterMaps();

  const out = await httpPost<PoOut>("/procurement/purchase-orders", {
    supplier_id: input.supplierId,
    delivery_godown_id: input.deliveryGodownId,
    po_date: input.poDate,
    expected_delivery_date: input.expectedDeliveryDate ?? undefined,
    payment_terms: input.paymentTerms,
    delivery_terms: input.deliveryTerms,
    rfq_id: input.rfqId ?? undefined,
    freight_amount: input.freightAmount,
    other_charges: input.otherCharges,
    notes: input.notes?.trim() || undefined,
    // `quotationId`/`comparisonId` have no field on `PoCreate`; a PO raised
    // from a comparison goes through the comparison's own convert endpoint,
    // which links them.
    items: input.lines.map((line) => {
      const variant = maps.variantsById.get(line.productVariantId);
      const product = variant ? maps.productsById.get(variant.product_id) : undefined;
      return {
        product_variant_id: line.productVariantId,
        description: line.description,
        hsn_code: variant?.hsn_code ?? product?.hsn_code ?? undefined,
        quantity: line.quantity,
        uom_id: line.uomId,
        unit_price: line.unitPrice,
        discount_pct: line.discountPct ?? 0,
        gst_rate: line.gstRate ?? variant?.gst_rate ?? product?.gst_rate ?? 0,
        cess_rate: 0,
        expected_delivery_date: line.expectedDeliveryDate ?? undefined,
        rfq_item_id: line.rfqItemId ?? undefined,
        quotation_item_id: line.quotationItemId ?? undefined,
      };
    }),
  });

  // `PoCreate` has no `status` field — the backend always creates a PO as
  // "draft" (there's no way to ask the create endpoint for anything else).
  // The PO form's "Save & Submit for Approval" button relies on this
  // function actually doing that: without this follow-up call it silently
  // created a draft and returned it as if the request had been honoured,
  // with no error — the PO then sat in "draft" needing a second, unprompted
  // click on its detail page to actually reach pending_approval.
  if (input.status === "pending_approval") {
    const submitted = await httpPost<PoOut>(`/procurement/purchase-orders/${out.id}/submit`);
    return toPurchaseOrder(submitted);
  }

  return toPurchaseOrder(out);
}

export async function updatePurchaseOrderStatus(
  purchaseOrderId: Id,
  status: PurchaseOrder["status"],
  options: { reason?: string } = {},
): Promise<PurchaseOrder> {
  if (status === "cancelled" && !options.reason?.trim()) reject("Give a reason for cancelling.", "BR-PO-08");

  // Status changes are specific backend action endpoints, not a generic
  // PATCH — map the target status to the right one. The "PO already
  // partially received, short-close instead of cancelling" guard (BR-PO-09)
  // used to run against the mock po's `receivedPct` — dropped, the backend
  // enforces this itself. The current UI only ever requests these five
  // target statuses (see `po-detail-screen.tsx`); the others
  // ("received"/"partially_received"/"acknowledged") are driven server-side
  // by GRN confirmation, never requested directly.
  const base = `/procurement/purchase-orders/${purchaseOrderId}`;
  let out: PoOut;
  switch (status) {
    case "pending_approval":
      out = await httpPost<PoOut>(`${base}/submit`);
      break;
    case "approved":
      out = await httpPost<PoOut>(`${base}/approve`);
      break;
    case "sent":
      out = await httpPost<PoOut>(`${base}/send`);
      break;
    case "cancelled":
      out = await httpPost<PoOut>(`${base}/cancel`, { reason: options.reason });
      break;
    case "closed":
      out = await httpPost<PoOut>(`${base}/close`, options.reason ? { reason: options.reason } : undefined);
      break;
    default:
      reject(`No action can move a purchase order directly to "${status}".`, "UNSUPPORTED_TRANSITION", 400);
  }
  return toPurchaseOrder(out);
}

/* -------------------------------------------------------------- Proforma */

/** `/proforma-invoices` — mirrors `app/modules/documents/schemas.py`. */
interface ProformaItemOut {
  id: string;
  line_no: number;
  purchase_order_item_id: string | null;
  product_variant_id: string | null;
  sku: string;
  description: string;
  hsn_code: string | null;
  quantity: number;
  uom_id: string;
  uom_code: string;
  unit_price: number;
  gst_rate: number;
  cess_rate: number;
  line_net: number;
  line_tax: number;
  line_total: number;
  po_unit_price_snapshot: number | null;
  price_variance_pct: number | null;
}

interface VarianceOut {
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

interface ProformaOut {
  id: string;
  proforma_number: string;
  supplier_id: string;
  supplier_name: string;
  purchase_order_id: string | null;
  po_number: string | null;
  proforma_date: string;
  valid_until: string | null;
  is_inter_state: boolean;
  subtotal: number;
  discount_amount: number;
  taxable_value: number;
  cgst_amount: number;
  sgst_amount: number;
  igst_amount: number;
  cess_amount: number;
  freight_amount: number;
  other_charges: number;
  round_off: number;
  total_amount: number;
  po_total_snapshot: number | null;
  variance_amount: number | null;
  advance_percent: number | null;
  advance_amount: number | null;
  payment_instructions: string | null;
  bank_name: string | null;
  bank_account_no: string | null;
  bank_ifsc: string | null;
  bank_branch: string | null;
  status: ProformaInvoice["status"];
  approved_by: string | null;
  approved_at: string | null;
  query_raised_at: string | null;
  query_note: string | null;
  row_version: number;
  items: ProformaItemOut[];
  item_count: number;
  variances: VarianceOut[];
}

/**
 * The human sentence for a variance row.
 *
 * Built here rather than sent by the backend: it is presentation, it needs
 * this app's own wording, and a translated build would want it in another
 * language entirely. The backend sends the numbers and the vocabulary.
 */
function varianceLabel(v: VarianceOut): string {
  const subject = v.sku || v.product_name || "This document";
  const direction = v.difference > 0 ? "more than" : "less than";
  const amount = Math.abs(v.difference);
  switch (v.variance_type) {
    case "price":
      return `${subject}: billed ₹${amount.toLocaleString("en-IN")} ${direction} the agreed rate`;
    case "quantity":
      return `${subject}: ${amount} ${direction} what was received`;
    case "total":
      return `Document total is ₹${amount.toLocaleString("en-IN")} ${direction} expected`;
    case "tax":
      return `${subject}: tax differs by ₹${amount.toLocaleString("en-IN")}`;
    case "product":
      return `${subject}: a different product than expected`;
    default:
      return `${subject}: differs by ${amount}`;
  }
}

function toVariance(v: VarianceOut): DocumentVariance {
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

function toProforma(p: ProformaOut): ProformaInvoice {
  return {
    id: p.id,
    proformaNumber: p.proforma_number,
    supplierId: p.supplier_id,
    purchaseOrderId: p.purchase_order_id,
    proformaDate: p.proforma_date,
    validUntil: p.valid_until,
    placeOfSupplyStateCode: "",
    isInterState: p.is_inter_state,
    subtotal: p.subtotal,
    discountAmount: p.discount_amount,
    taxableValue: p.taxable_value,
    cgstAmount: p.cgst_amount,
    sgstAmount: p.sgst_amount,
    igstAmount: p.igst_amount,
    cessAmount: p.cess_amount,
    freightAmount: p.freight_amount,
    otherCharges: p.other_charges,
    roundOff: p.round_off,
    totalAmount: p.total_amount,
    poTotalSnapshot: p.po_total_snapshot ?? 0,
    varianceAmount: p.variance_amount ?? 0,
    advancePercent: p.advance_percent,
    advanceAmount: p.advance_amount,
    paymentInstructions: p.payment_instructions ?? "",
    bankName: p.bank_name ?? undefined,
    bankAccountNo: p.bank_account_no ?? undefined,
    bankIfsc: p.bank_ifsc ?? undefined,
    supplierGstinSnapshot: null,
    supplierAddressSnapshot: "",
    documentId: null,
    aiExtractionResultId: null,
    status: p.status,
    approvedBy: p.approved_by,
    approvedAt: p.approved_at,
    queryRaisedAt: p.query_raised_at,
    queryNote: p.query_note ?? undefined,
    // `proforma_invoices` has no created_at column, so the document's own
    // date is the only timestamp available. Listing sorts by it anyway.
    createdAt: p.proforma_date,
  };
}

export interface ProformaListRow extends ProformaInvoice {
  supplierName: string;
  poNumber: string | null;
  hasVariance: boolean;
}

export async function listProformas(params: ListParams = {}): Promise<ListResponse<ProformaListRow>> {
  const out = await httpGet<ProformaOut[]>("/proforma-invoices", { limit: 500 });
  const rows: ProformaListRow[] = out.map((p) => ({
    ...toProforma(p),
    supplierName: p.supplier_name,
    poNumber: p.po_number,
    hasVariance: Math.abs(p.variance_amount ?? 0) > 0.5,
  }));
  return query(rows as unknown as Record<string, unknown>[], params, {
    searchFields: ["proformaNumber", "supplierName", "poNumber"],
    dateField: "proformaDate",
    facetFields: ["status", "supplierId"],
    defaultSort: "-proformaDate",
  }) as unknown as ListResponse<ProformaListRow>;
}

export interface ProformaDetail {
  proforma: ProformaInvoice;
  supplierName: string;
  poNumber: string | null;
  items: (ProformaInvoiceItem & { sku: string; productName: string; uomCode: string })[];
  taxRows: ReturnType<typeof taxBreakdown>;
  variances: DocumentVariance[];
  allowedActions: ProformaInvoice["status"][];
}

export async function getProforma(proformaId: Id): Promise<ProformaDetail> {
  const p = await httpGet<ProformaOut>(`/proforma-invoices/${proformaId}`);
  return {
    proforma: toProforma(p),
    supplierName: p.supplier_name,
    poNumber: p.po_number,
    items: p.items.map((i) => ({
      id: i.id,
      proformaId: p.id,
      lineNo: i.line_no,
      purchaseOrderItemId: i.purchase_order_item_id,
      productVariantId: i.product_variant_id,
      description: i.description,
      hsnCode: i.hsn_code ?? undefined,
      quantity: i.quantity,
      uomId: i.uom_id,
      unitPrice: i.unit_price,
      gstRate: i.gst_rate,
      cessRate: i.cess_rate,
      lineNet: i.line_net,
      lineTax: i.line_tax,
      lineTotal: i.line_total,
      poUnitPriceSnapshot: i.po_unit_price_snapshot,
      priceVariancePct: i.price_variance_pct,
      sku: i.sku,
      productName: i.description,
      uomCode: i.uom_code,
    })) as ProformaDetail["items"],
    taxRows: taxBreakdown(
      p.items.map((i) => ({
        quantity: i.quantity,
        unitPrice: i.unit_price,
        gstRate: i.gst_rate,
        cessRate: i.cess_rate,
      })),
      p.is_inter_state,
    ),
    variances: p.variances.map(toVariance),
    allowedActions: allowedTransitions(proformaTransitions, p.status),
  };
}

export async function setProformaStatus(
  proformaId: Id,
  status: ProformaInvoice["status"],
  note?: string,
): Promise<ProformaInvoice> {
  // `approved` and `rejected` have dedicated endpoints because they do more
  // than set a column (approval runs the BR-PF-03 variance gate and stamps
  // an approver). Everything else goes through the generic one.
  if (status === "approved") {
    return toProforma(await httpPost<ProformaOut>(`/proforma-invoices/${proformaId}/approve`));
  }
  if (status === "rejected") {
    if (!note?.trim()) reject("Give a reason so the supplier can be told why.", "BR-PF-03");
    return toProforma(
      await httpPost<ProformaOut>(`/proforma-invoices/${proformaId}/reject`, { reason: note }),
    );
  }
  return toProforma(
    await httpPost<ProformaOut>(`/proforma-invoices/${proformaId}/status`, { status, note }),
  );
}

export async function raiseProformaQuery(proformaId: Id, note: string): Promise<ProformaInvoice> {
  if (!note.trim()) reject("Write the query you want to send the supplier.", "VALIDATION_FAILED");
  return toProforma(
    await httpPost<ProformaOut>(`/proforma-invoices/${proformaId}/raise-query`, { note: note.trim() }),
  );
}

/* ------------------------------------------------------------ Variances */

export async function listVariances(params: ListParams = {}): Promise<ListResponse<DocumentVariance>> {
  const out = await httpGet<VarianceOut[]>("/variances", { limit: 500 });
  const rows = out.map(toVariance);
  return query(rows as unknown as Record<string, unknown>[], params, {
    searchFields: ["label", "baseDocType", "compareDocType"],
    facetFields: ["severity", "status", "comparisonKind"],
    defaultSort: "-severity",
  }) as unknown as ListResponse<DocumentVariance>;
}

export async function resolveVariance(
  varianceId: Id,
  status: "accepted" | "disputed" | "resolved",
  note: string,
): Promise<DocumentVariance> {
  if (!note.trim()) reject("Say how this variance was resolved.", "BR-VAR-03");
  const out = await httpPost<VarianceOut>(`/variances/${varianceId}/resolve`, {
    status,
    note: note.trim(),
  });
  return toVariance(out);
}
