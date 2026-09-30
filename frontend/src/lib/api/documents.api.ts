/**
 * Document storage, the AI review pipeline, schema mappings and the assistant.
 *
 * All of it talks to the real `/ai/*` endpoints. Nothing in this module runs
 * a model, simulates a progress bar, or computes a financial value — and
 * the three facts behind that are worth stating where the calls are made:
 *
 *  - **Extraction happens on the server, in a background worker.**
 *    `uploadDocument` resolves once the file is stored and queued
 *    (`processingStatus: "queued"`); the job endpoint then reports the
 *    worker's real stages and progress until the document is read.
 *  - **An extraction is not a business document.** Approving one promotes
 *    it into a quotation, proforma or invoice, server-side, and records who
 *    did it (BR-AI-01).
 *  - **Totals are never taken from the page.** `view.totals` is a preview
 *    computed from the reviewed lines, and the figures stored on approval
 *    come from the money engine, not from this module and not from the
 *    supplier's printed total (BR-AI-02).
 */

import type {
  AiExtractedField,
  AiExtractedLine,
  AiExtractionResult,
  AiMatchCandidate,
  AiProcessingJob,
  AssistantAnswer,
  BusinessDocumentType,
  CanonicalField,
  DocumentJobStatus,
  DocumentSchemaMapping,
  DocumentSchemaMappingField,
  ExtractionView,
  Id,
  ListParams,
  ListResponse,
  MatchMethod,
  StoredDocument,
  UploadDocumentResult,
} from "@/types";
import { MATCH_METHOD_LABELS } from "@/lib/domain/matching";
import { httpDelete, httpGet, httpPatch, httpPost, httpUpload, validationFailed } from "./client";

/**
 * How each rung of the match ladder is described to a person. The ladder
 * itself now runs on the server; these labels stay client-side because they
 * are wording, not logic.
 */
export const MATCH_LABELS = MATCH_METHOD_LABELS;

/* --------------------------------------------------------- Backend shapes */

interface DocumentOut {
  id: string;
  original_filename: string;
  mime_type: string;
  file_extension: string;
  file_size_bytes: number;
  sha256_hash: string;
  page_count: number | null;
  document_type: string | null;
  document_type_confidence: number | null;
  supplier_id: string | null;
  supplier_name: string;
  supplier_confidence: number | null;
  processing_status: string;
  processing_stage: string | null;
  processing_progress: number;
  extraction_confidence: number | null;
  items_found: number | null;
  error_code: string | null;
  error_message: string | null;
  source: string;
  uploaded_by: string;
  uploaded_by_name: string;
  uploaded_at: string;
  extraction_result_id: string | null;
}

interface FieldOut {
  id: string;
  field_key: string;
  field_label: string;
  raw_value: string | null;
  normalised_value: string | null;
  corrected_value: string | null;
  value_type: string;
  confidence: number | null;
  provenance: string;
  source_cell: string | null;
  corrected_by: string | null;
  corrected_at: string | null;
  validation_error: string | null;
}

interface CandidateOut {
  id: string | null;
  product_variant_id: string | null;
  sku: string;
  product_name: string;
  rank: number;
  match_method: string;
  score: number | null;
  confidence: number | null;
  reasons: string[];
  is_selected: boolean;
}

interface LineOut {
  id: string;
  line_no: number;
  raw_description: string;
  normalised_description: string | null;
  supplier_sku: string | null;
  raw_quantity: string | null;
  quantity: number | null;
  raw_uom: string | null;
  unit_price: number | null;
  discount_pct: number | null;
  gst_rate: number | null;
  hsn_code: string | null;
  line_total_as_printed: number | null;
  matched_variant_id: string | null;
  matched_sku: string;
  matched_product_name: string;
  match_method: string | null;
  match_score: number | null;
  confidence: number | null;
  provenance: string;
  suggestion_text: string | null;
  final_variant_id: string | null;
  final_decision: string | null;
  alias_saved: boolean;
  validation_errors: { field?: string; message: string }[];
  candidates: CandidateOut[];
}

interface ExtractionOut {
  id: string;
  document: DocumentOut;
  job: JobOut | null;
  document_type: string;
  schema_mapping_id: string | null;
  supplier_id: string | null;
  supplier_name: string;
  supplier_confidence: number | null;
  overall_confidence: number | null;
  review_status: string;
  rejection_reason: string | null;
  promoted_to_type: string | null;
  promoted_to_id: string | null;
  fields: FieldOut[];
  lines: LineOut[];
  totals: { subtotal: number; tax: number; total: number };
  unresolved_count: number;
  fields_needing_review: number;
  can_approve: boolean;
  blocking_reason: string | null;
  pipeline_trace: { stage: string; detail: string; at_ms?: number }[];
  validation_errors: { code?: string; message: string }[];
  providers: { kind: string; configured: boolean; provider: string; model_id: string | null; note: string }[];
}

interface JobOut {
  document_id: string;
  job_id: string | null;
  processing_status: string;
  processing_stage: string | null;
  processing_progress: number;
  extraction_confidence: number | null;
  items_found: number | null;
  extraction_result_id: string | null;
  duration_ms: number | null;
  error_code: string | null;
  error_message: string | null;
}

/* ------------------------------------------------------------- Documents */

export interface DocumentListRow extends StoredDocument {
  supplierDisplayName: string;
  extractionResultId: Id | null;
  sizeKb: number;
}

function toDocument(o: DocumentOut): DocumentListRow {
  return {
    id: o.id,
    originalFilename: o.original_filename,
    storageKey: "",
    mimeType: o.mime_type,
    fileExtension: o.file_extension as DocumentListRow["fileExtension"],
    fileSizeBytes: o.file_size_bytes,
    sha256Hash: o.sha256_hash,
    pageCount: o.page_count ?? undefined,
    documentType: (o.document_type ?? "unrecognised") as BusinessDocumentType,
    documentTypeConfidence: o.document_type_confidence ?? undefined,
    supplierId: o.supplier_id,
    supplierConfidence: o.supplier_confidence ?? undefined,
    processingStatus: o.processing_status as DocumentListRow["processingStatus"],
    processingStage: o.processing_stage ?? undefined,
    processingProgress: o.processing_progress,
    extractionConfidence: o.extraction_confidence,
    itemsFound: o.items_found,
    errorCode: o.error_code,
    errorMessage: o.error_message,
    source: o.source as StoredDocument["source"],
    uploadedBy: o.uploaded_by,
    uploadedByName: o.uploaded_by_name,
    uploadedAt: o.uploaded_at,
    supplierDisplayName: o.supplier_name || "Unknown",
    extractionResultId: o.extraction_result_id,
    sizeKb: Math.max(1, Math.round(o.file_size_bytes / 1024)),
  };
}

export async function listDocuments(params: ListParams = {}): Promise<ListResponse<DocumentListRow>> {
  const filters = (params.filters ?? {}) as Record<string, string | undefined>;
  const rows = (
    await httpGet<DocumentOut[]>("/ai/documents", {
      limit: params.limit ?? 200,
      q: params.q?.trim() || undefined,
      status: filters.processingStatus || undefined,
      document_type: filters.documentType || undefined,
      supplier_id: filters.supplierId || undefined,
    })
  ).map(toDocument);
  return { items: rows, total: rows.length, nextCursor: null };
}

export async function getDocument(documentId: Id): Promise<StoredDocument> {
  return toDocument(await httpGet<DocumentOut>(`/ai/documents/${documentId}`));
}

export interface UploadInput {
  file: File;
  documentType?: BusinessDocumentType;
  supplierId?: Id | null;
}

/**
 * Send the actual bytes.
 *
 * Duplicate detection is by SHA-256 of the content, per tenant, computed on
 * the server (BR-DOC-02) — re-sending the same file returns the document
 * that already exists rather than processing it twice.
 */
export async function uploadDocument(input: UploadInput): Promise<UploadDocumentResult> {
  const extension = (input.file.name.split(".").pop() ?? "").toLowerCase();
  if (!["xlsx", "xls", "csv", "pdf", "docx", "jpg", "jpeg", "png"].includes(extension)) {
    validationFailed([
      { field: "file", message: `.${extension || "?"} files can't be read — upload a spreadsheet, CSV or PDF.` },
    ]);
  }

  const out = await httpUpload<{ document: DocumentOut; job_id: string | null; duplicate_of: DocumentOut | null }>(
    "/ai/documents",
    input.file,
    {
      document_type: input.documentType,
      supplier_id: input.supplierId ?? undefined,
    },
  );
  return {
    document: toDocument(out.document),
    jobId: out.job_id,
    duplicateOf: out.duplicate_of ? toDocument(out.duplicate_of) : null,
  };
}

function toJobStatus(o: JobOut): DocumentJobStatus {
  return {
    documentId: o.document_id,
    processingStatus: o.processing_status as DocumentJobStatus["processingStatus"],
    processingStage: o.processing_stage ?? undefined,
    processingProgress: o.processing_progress,
    extractionConfidence: o.extraction_confidence,
    itemsFound: o.items_found,
    extractionResultId: o.extraction_result_id,
    error: o.error_code ? { code: o.error_code, message: o.error_message ?? "" } : null,
  };
}

export async function getDocumentJobStatus(documentId: Id): Promise<DocumentJobStatus> {
  return toJobStatus(await httpGet<JobOut>(`/ai/documents/${documentId}/job`));
}

/** Read the document again, superseding the previous result rather than
 * deleting it — a reviewer's earlier corrections stay readable. */
export async function retryExtraction(documentId: Id): Promise<DocumentJobStatus> {
  return toJobStatus(await httpPost<JobOut>(`/ai/documents/${documentId}/retry`, {}));
}

/** Only a document nothing was made from can be deleted; one behind a
 * quotation, proforma or invoice is refused (409) and kept as its evidence. */
export async function deleteDocument(documentId: Id): Promise<void> {
  await httpDelete(`/ai/documents/${documentId}`);
}

/** A 5-minute signed link to the original file, to open in a new tab. */
export async function getDownloadLink(documentId: Id): Promise<string> {
  return (await httpGet<{ url: string }>(`/ai/documents/${documentId}/download-link`)).url;
}

export type LinkedRecordType = "supplier_quotation" | "proforma_invoice" | "supplier_invoice";

export interface SourceDocument {
  id: Id;
  originalFilename: string;
  mimeType: string | null;
  fileSizeBytes: number | null;
  uploadedAt: string | null;
}

/** The uploaded files a business record was made from. */
export async function getSourceDocuments(linkedType: LinkedRecordType, linkedId: Id): Promise<SourceDocument[]> {
  const rows = await httpGet<
    {
      id: Id;
      original_filename: string;
      mime_type: string | null;
      file_size_bytes: number | null;
      uploaded_at: string | null;
    }[]
  >(`/ai/sources/${linkedType}/${linkedId}`);
  return rows.map((r) => ({
    id: r.id,
    originalFilename: r.original_filename,
    mimeType: r.mime_type,
    fileSizeBytes: r.file_size_bytes,
    uploadedAt: r.uploaded_at,
  }));
}

/* ------------------------------------------------------------ Extraction */

function toField(o: FieldOut): AiExtractedField {
  return {
    id: o.id,
    extractionResultId: "",
    fieldKey: o.field_key,
    fieldLabel: o.field_label,
    rawValue: o.raw_value ?? "",
    normalisedValue: o.normalised_value ?? undefined,
    valueType: o.value_type as AiExtractedField["valueType"],
    confidence: o.confidence,
    provenance: o.provenance as AiExtractedField["provenance"],
    sourceCell: o.source_cell ?? undefined,
    correctedValue: o.corrected_value,
    correctedBy: o.corrected_by,
    correctedAt: o.corrected_at,
    validationError: o.validation_error,
  };
}

function toCandidate(o: CandidateOut, lineId: Id, queryText: string): AiMatchCandidate {
  return {
    id: o.id ?? `${lineId}-${o.rank}`,
    extractedLineId: lineId,
    queryText,
    normalisedQuery: "",
    rank: o.rank,
    productVariantId: o.product_variant_id ?? "",
    sku: o.sku,
    productName: o.product_name,
    matchMethod: o.match_method as MatchMethod,
    score: o.score ?? 0,
    confidence: o.confidence ?? 0,
    reasons: o.reasons ?? [],
    isSelected: o.is_selected,
  };
}

export type ExtractedLineWithCandidates = AiExtractedLine & {
  candidates: AiMatchCandidate[];
  matchedSku: string;
  matchedProductName: string;
  validationErrors: { field?: string; message: string }[];
  rawQuantity?: string | null;
};

function toLine(o: LineOut, resultId: Id): ExtractedLineWithCandidates {
  return {
    id: o.id,
    extractionResultId: resultId,
    lineNo: o.line_no,
    rawDescription: o.raw_description,
    normalisedDescription: o.normalised_description ?? undefined,
    supplierSku: o.supplier_sku ?? undefined,
    quantity: o.quantity ?? 0,
    uomId: null,
    rawUom: o.raw_uom ?? undefined,
    unitPrice: o.unit_price ?? 0,
    discountPct: o.discount_pct ?? undefined,
    gstRate: o.gst_rate ?? 0,
    hsnCode: o.hsn_code ?? undefined,
    lineTotalAsPrinted: o.line_total_as_printed ?? undefined,
    matchedVariantId: o.final_variant_id ?? o.matched_variant_id,
    matchMethod: (o.match_method ?? undefined) as MatchMethod | undefined,
    matchScore: o.match_score ?? undefined,
    confidence: o.confidence ?? 0,
    provenance: o.provenance as AiExtractedLine["provenance"],
    suggestionText: o.suggestion_text ?? undefined,
    finalVariantId: o.final_variant_id,
    finalDecision: o.final_decision as AiExtractedLine["finalDecision"],
    aliasSaved: o.alias_saved,
    matchedSku: o.matched_sku,
    matchedProductName: o.matched_product_name,
    rawQuantity: o.raw_quantity,
    validationErrors: o.validation_errors ?? [],
    candidates: (o.candidates ?? []).map((c) => toCandidate(c, o.id, o.raw_description)),
  };
}

export interface ExtractionViewReal extends Omit<ExtractionView, "lines"> {
  lines: ExtractedLineWithCandidates[];
  blockingReason: string | null;
  /** Which model rungs are actually available on this installation. */
  providers: { kind: string; configured: boolean; provider: string; modelId: string | null; note: string }[];
}

export async function getExtraction(documentId: Id): Promise<ExtractionViewReal> {
  const o = await httpGet<ExtractionOut>(`/ai/documents/${documentId}/extraction`);
  const document = toDocument(o.document);

  const extraction: AiExtractionResult = {
    id: o.id,
    documentId: o.document.id,
    jobId: o.job?.job_id ?? "",
    schemaMappingId: o.schema_mapping_id,
    documentType: o.document_type as BusinessDocumentType,
    supplierId: o.supplier_id,
    supplierConfidence: o.supplier_confidence ?? undefined,
    overallConfidence: o.overall_confidence ?? 0,
    pageCount: o.document.page_count ?? 1,
    lineCount: o.lines.length,
    // The backend's trace is a list of what actually happened, in order, so
    // every step it reports is done — there is no pending stage to render.
    pipelineTrace: o.pipeline_trace.map((step) => ({
      step: step.stage,
      result: step.detail,
      state: "done" as const,
    })),
    validationErrors: o.validation_errors.map((e) => ({
      field: "",
      code: e.code ?? "VALIDATION",
      message: e.message,
    })),
    reviewStatus: o.review_status as AiExtractionResult["reviewStatus"],
    rejectionReason: o.rejection_reason ?? undefined,
    promotedToType: o.promoted_to_type as AiExtractionResult["promotedToType"],
    promotedToId: o.promoted_to_id,
    createdAt: o.document.uploaded_at,
  };

  const job: AiProcessingJob | null = o.job?.job_id
    ? {
        id: o.job.job_id,
        documentId: o.job.document_id,
        jobType: "extraction",
        status: o.job.error_code ? "failed" : "succeeded",
        stage: o.job.processing_stage ?? undefined,
        progress: o.job.processing_progress,
        // Named for what actually read the file. Left undefined rather than
        // filled with a plausible model name — see `providers` for what is
        // and is not configured.
        provider: undefined,
        durationMs: o.job.duration_ms ?? undefined,
        attempt: 1,
        errorCode: o.job.error_code,
        errorMessage: o.job.error_message,
      }
    : null;

  return {
    extraction,
    document,
    job,
    fields: o.fields.map(toField),
    lines: o.lines.map((l) => toLine(l, o.id)),
    totals: o.totals,
    unresolvedCount: o.unresolved_count,
    fieldsNeedingReview: o.fields_needing_review,
    canApprove: o.can_approve,
    blockingReason: o.blocking_reason,
    providers: o.providers.map((p) => ({
      kind: p.kind,
      configured: p.configured,
      provider: p.provider,
      modelId: p.model_id,
      note: p.note,
    })),
  };
}

/* ---------------------------------------------------------------- Review */

export interface SuggestionResult {
  lineId: Id;
  rungReached: MatchMethod;
  autoMatched: boolean;
  /** Rungs the ladder could not attempt because no provider is configured. */
  skippedRungs: string[];
  candidates: AiMatchCandidate[];
}

export async function suggestMatches(extractedLineId: Id): Promise<SuggestionResult> {
  const o = await httpGet<{
    line_id: string;
    rung_reached: string;
    auto_matched: boolean;
    skipped_rungs: string[];
    candidates: CandidateOut[];
  }>(`/ai/lines/${extractedLineId}/candidates`);
  return {
    lineId: o.line_id,
    rungReached: o.rung_reached as MatchMethod,
    autoMatched: o.auto_matched,
    skippedRungs: o.skipped_rungs ?? [],
    candidates: (o.candidates ?? []).map((c) => toCandidate(c, extractedLineId, "")),
  };
}

export async function confirmLineMatch(
  extractedLineId: Id,
  productVariantId: Id,
  options: { saveAlias?: boolean } = {},
): Promise<AiExtractedLine> {
  const o = await httpPost<LineOut>(`/ai/lines/${extractedLineId}/match`, {
    product_variant_id: productVariantId,
    save_alias: options.saveAlias ?? true,
  });
  return toLine(o, "");
}

export async function skipExtractedLine(extractedLineId: Id, reason: string): Promise<AiExtractedLine> {
  if (reason.trim().length < 3) {
    validationFailed([{ field: "reason", message: "Say why this line is being left out." }]);
  }
  return toLine(await httpPost<LineOut>(`/ai/lines/${extractedLineId}/skip`, { reason: reason.trim() }), "");
}

export async function correctExtractedField(fieldId: Id, value: string): Promise<AiExtractedField> {
  return toField(await httpPatch<FieldOut>(`/ai/fields/${fieldId}`, { value }));
}

export async function updateExtractedLine(
  extractedLineId: Id,
  patch: { quantity?: number; unitPrice?: number; discountPct?: number; gstRate?: number; hsnCode?: string },
): Promise<AiExtractedLine> {
  const body: Record<string, unknown> = {};
  if (patch.quantity !== undefined) body.quantity = patch.quantity;
  if (patch.unitPrice !== undefined) body.unit_price = patch.unitPrice;
  if (patch.discountPct !== undefined) body.discount_pct = patch.discountPct;
  if (patch.gstRate !== undefined) body.gst_rate = patch.gstRate;
  if (patch.hsnCode !== undefined) body.hsn_code = patch.hsnCode;
  return toLine(await httpPatch<LineOut>(`/ai/lines/${extractedLineId}`, body), "");
}

export interface ApprovalResult {
  extractionResultId: Id;
  promotedToType: "supplier_quotation" | "proforma_invoice" | "supplier_invoice";
  promotedToId: Id;
  lineCount: number;
}

/** Promote the reviewed extraction. Totals are recomputed server-side from
 * the reviewed lines — nothing printed on the document is carried over. */
export async function approveExtraction(
  documentId: Id,
  options: { rfqId?: Id | null } = {},
): Promise<ApprovalResult> {
  const o = await httpPost<{
    extraction_result_id: string;
    promoted_to_type: string;
    promoted_to_id: string;
    line_count: number;
  }>(`/ai/documents/${documentId}/approve`, { rfq_id: options.rfqId ?? null });
  return {
    extractionResultId: o.extraction_result_id,
    promotedToType: o.promoted_to_type as ApprovalResult["promotedToType"],
    promotedToId: o.promoted_to_id,
    lineCount: o.line_count,
  };
}

export async function rejectExtraction(documentId: Id, reason: string): Promise<{ reviewStatus: string }> {
  if (reason.trim().length < 3) {
    validationFailed([{ field: "reason", message: "Say why this document is being rejected." }]);
  }
  const o = await httpPost<{ extraction_result_id: string; review_status: string }>(
    `/ai/documents/${documentId}/reject`,
    { reason: reason.trim() },
  );
  return { reviewStatus: o.review_status };
}

/* -------------------------------------------------------- Schema mappings */

interface MappingOut {
  id: string;
  supplier_id: string | null;
  supplier_name: string;
  document_type: string;
  file_format: string;
  mapping_name: string | null;
  column_signature: string;
  header_row_index: number | null;
  data_start_row: number | null;
  sheet_name: string | null;
  sample_document_id: string | null;
  status: string;
  confidence: number | null;
  usage_count: number;
  last_used_at: string | null;
  success_rate: number | null;
  version: number;
  confirmed_by: string | null;
  confirmed_at: string | null;
  fields: {
    id: string;
    source_column: string;
    source_column_index: number | null;
    canonical_field_id: string;
    canonical_code: string;
    canonical_label: string;
    transform: string;
    is_required: boolean;
    confidence: number | null;
    confirmed_by: string | null;
    confirmed_at: string | null;
  }[];
  unmapped_columns: string[];
}

function toMapping(o: MappingOut): DocumentSchemaMapping {
  return {
    id: o.id,
    supplierId: o.supplier_id,
    supplierName: o.supplier_name,
    documentType: o.document_type as BusinessDocumentType,
    fileFormat: o.file_format as DocumentSchemaMapping["fileFormat"],
    mappingName: o.mapping_name ?? `${o.sheet_name ?? "Sheet"} layout`,
    columnSignature: o.column_signature,
    headerRowIndex: o.header_row_index ?? 0,
    dataStartRow: o.data_start_row ?? 0,
    sheetName: o.sheet_name ?? undefined,
    sampleDocumentId: o.sample_document_id,
    status: o.status as DocumentSchemaMapping["status"],
    confidence: o.confidence ?? 0,
    usageCount: o.usage_count,
    lastUsedAt: o.last_used_at,
    successRate: o.success_rate ?? 0,
    version: o.version,
    confirmedBy: o.confirmed_by,
    confirmedAt: o.confirmed_at,
    createdAt: o.confirmed_at ?? o.last_used_at ?? new Date().toISOString(),
  };
}

/** The screen keys a column on the canonical *code*, not on its row id —
 * that is the whole point of the vocabulary (BR-AI-09). */
export interface MappingFieldRow extends DocumentSchemaMappingField {
  canonicalFieldId: Id;
  canonicalLabel: string;
}

function toMappingField(o: MappingOut["fields"][number], mappingId: Id): MappingFieldRow {
  return {
    id: o.id,
    mappingId,
    sourceColumn: o.source_column,
    sourceColumnIndex: o.source_column_index ?? 0,
    canonicalFieldCode: o.canonical_code,
    canonicalFieldId: o.canonical_field_id,
    canonicalLabel: o.canonical_label,
    transform: o.transform as DocumentSchemaMappingField["transform"],
    isRequired: o.is_required,
    confidence: o.confidence ?? 0,
    confirmedBy: o.confirmed_by,
    confirmedAt: o.confirmed_at,
  };
}

export async function listSchemaMappings(params: ListParams = {}): Promise<ListResponse<DocumentSchemaMapping>> {
  const filters = (params.filters ?? {}) as Record<string, string | undefined>;
  const rows = (
    await httpGet<MappingOut[]>("/ai/schema-mappings", {
      limit: params.limit ?? 200,
      status: filters.status || undefined,
    })
  ).map(toMapping);
  return { items: rows, total: rows.length, nextCursor: null };
}

export interface SchemaMappingDetail {
  mapping: DocumentSchemaMapping;
  fields: MappingFieldRow[];
  /** Columns in the sample file nothing is mapped to — the worklist. */
  unmappedColumns: string[];
  /** Canonical fields a column can be pointed at. */
  canonicalFields: CanonicalField[];
  /** Required line fields with no column yet — confirming is blocked on
   * these, because a layout that cannot yield a description, a quantity and
   * a price produces lines nobody can approve. */
  unmappedRequired: string[];
  sampleDocument: StoredDocument | null;
}

const REQUIRED_LINE_FIELDS = ["product_description", "quantity", "unit_price"];

async function assembleMapping(o: MappingOut): Promise<SchemaMappingDetail> {
  const fields = o.fields.map((f) => toMappingField(f, o.id));
  const mapped = new Set(fields.map((f) => f.canonicalFieldCode));
  const [canonicalFields, sampleDocument] = await Promise.all([
    listCanonicalFields(),
    o.sample_document_id
      ? getDocument(o.sample_document_id).catch(() => null)
      : Promise.resolve(null),
  ]);
  return {
    mapping: toMapping(o),
    fields,
    unmappedColumns: o.unmapped_columns ?? [],
    canonicalFields,
    unmappedRequired: REQUIRED_LINE_FIELDS.filter((code) => !mapped.has(code)),
    sampleDocument,
  };
}

export async function getSchemaMapping(mappingId: Id): Promise<SchemaMappingDetail> {
  return assembleMapping(await httpGet<MappingOut>(`/ai/schema-mappings/${mappingId}`));
}

/**
 * Point a column at a different canonical field, or change its transform.
 *
 * The screen works in canonical *codes*, which is the vocabulary a person
 * reads; the id is resolved here. That is the same decoupling the schema
 * relies on — a mapping means "this column is the unit price", never "this
 * column is row 4f3a…".
 */
export async function updateMappingField(
  mappingId: Id,
  fieldId: Id,
  patch: { canonicalFieldCode?: string; transform?: string },
): Promise<SchemaMappingDetail> {
  const body: Record<string, unknown> = {};
  if (patch.canonicalFieldCode) {
    const canonical = (await listCanonicalFields()).find((f) => f.code === patch.canonicalFieldCode);
    if (!canonical) {
      validationFailed([{ field: "canonicalFieldCode", message: "That field is not one we recognise." }]);
    }
    body.canonical_field_id = canonical!.id;
  }
  if (patch.transform) body.transform = patch.transform;
  return assembleMapping(await httpPatch<MappingOut>(`/ai/schema-mappings/${mappingId}/fields/${fieldId}`, body));
}

export async function addMappingColumn(
  mappingId: Id,
  input: { sourceColumn: string; sourceColumnIndex?: number; canonicalFieldId: Id },
): Promise<SchemaMappingDetail> {
  return assembleMapping(
    await httpPost<MappingOut>(`/ai/schema-mappings/${mappingId}/fields`, {
      source_column: input.sourceColumn,
      source_column_index: input.sourceColumnIndex ?? null,
      canonical_field_id: input.canonicalFieldId,
    }),
  );
}

/** BR-AI-09 — until this is called, the layout is only a suggestion. */
export async function confirmSchemaMapping(mappingId: Id): Promise<DocumentSchemaMapping> {
  return toMapping(await httpPost<MappingOut>(`/ai/schema-mappings/${mappingId}/confirm`, {}));
}

export async function deprecateSchemaMapping(mappingId: Id): Promise<DocumentSchemaMapping> {
  return toMapping(await httpPost<MappingOut>(`/ai/schema-mappings/${mappingId}/deprecate`, {}));
}

export async function listCanonicalFields(documentType?: BusinessDocumentType): Promise<CanonicalField[]> {
  const rows = await httpGet<
    {
      id: string;
      code: string;
      label: string;
      field_group: string;
      data_type: string;
      is_required: boolean;
      synonyms: string[];
      description: string | null;
    }[]
  >("/ai/canonical-fields");
  return rows.map((f) => ({
    id: f.id,
    code: f.code,
    label: f.label,
    fieldGroup: f.field_group as CanonicalField["fieldGroup"],
    dataType: f.data_type as CanonicalField["dataType"],
    appliesToDocTypes: documentType ? [documentType] : [],
    isRequired: f.is_required,
    synonyms: f.synonyms ?? [],
    description: f.description ?? undefined,
  }));
}

/* ------------------------------------------------------------- Assistant */

/**
 * BR-AI-08: the assistant never generates SQL. The question picks an intent
 * server-side, the intent picks a hand-written parameterised query, and the
 * answer says which one it was.
 */
/** Example questions, one per kind of question the assistant can answer. */
export async function getAssistantSuggestions(): Promise<string[]> {
  return (await httpGet<{ intent: string; question: string }[]>("/ai/assistant/suggestions")).map((s) => s.question);
}

export async function askAssistant(question: string): Promise<AssistantAnswer> {
  const o = await httpPost<{
    intent: string;
    source: string;
    answer: string;
    table: { columns: string[]; rows: string[][] } | null;
    breakdown: { label: string; value: string }[] | null;
    link: { label: string; href: string } | null;
  }>("/ai/assistant", { question });
  return {
    intent: o.intent,
    source: o.source,
    answer: o.answer,
    table: o.table ?? undefined,
    breakdown: o.breakdown ?? undefined,
    link: o.link ?? undefined,
  } as AssistantAnswer;
}

/* ------------------------------------------------ Product embeddings (rung 6) */

interface EmbeddingStatusOut {
  configured: boolean;
  provider: string;
  model: string | null;
  dimensions: number;
  total_products: number;
  embedded: number;
  pending: number;
  last_generated_at: string | null;
  rebuilding: boolean;
  rebuild_embedded: number;
  last_error: string | null;
}

/** How much of the catalogue can be matched by meaning. */
export interface EmbeddingStatus {
  configured: boolean;
  provider: string;
  model: string | null;
  dimensions: number;
  totalProducts: number;
  embedded: number;
  pending: number;
  lastGeneratedAt: string | null;
  rebuilding: boolean;
  rebuildEmbedded: number;
  lastError: string | null;
}

function toEmbeddingStatus(o: EmbeddingStatusOut): EmbeddingStatus {
  return {
    configured: o.configured,
    provider: o.provider,
    model: o.model,
    dimensions: o.dimensions,
    totalProducts: o.total_products,
    embedded: o.embedded,
    pending: o.pending,
    lastGeneratedAt: o.last_generated_at,
    rebuilding: o.rebuilding,
    rebuildEmbedded: o.rebuild_embedded,
    lastError: o.last_error,
  };
}

export async function getEmbeddingStatus(): Promise<EmbeddingStatus> {
  return toEmbeddingStatus(await httpGet<EmbeddingStatusOut>("/ai/embeddings/status"));
}

/** Starts indexing in the background; poll `getEmbeddingStatus` for progress. */
export async function rebuildEmbeddings(everything = false): Promise<EmbeddingStatus> {
  return toEmbeddingStatus(
    await httpPost<EmbeddingStatusOut>(`/ai/embeddings/rebuild${everything ? "?everything=true" : ""}`),
  );
}
