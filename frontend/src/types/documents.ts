/**
 * Document storage and the AI pipeline.
 *
 * AI never writes to a business table — it writes here, and a human approval
 * promotes the result (BR-AI-01). Every structure below exists so that
 * decision is auditable.
 */

import type {
  DateOnly,
  Id,
  MatchMethod,
  Money,
  Percent,
  Provenance,
  Quantity,
  Timestamp,
} from "./common";

export type DocumentProcessingStatus =
  | "uploaded"
  | "queued"
  | "processing"
  | "extracted"
  | "review_required"
  | "approved"
  | "rejected"
  | "failed"
  | "duplicate";

export type BusinessDocumentType =
  | "supplier_quotation"
  | "proforma_invoice"
  | "tax_invoice"
  | "delivery_challan"
  | "rate_list"
  | "price_revision"
  | "purchase_order"
  | "other"
  | "unrecognised";

export type FileExtension = "xlsx" | "xls" | "csv" | "pdf" | "docx" | "jpg" | "jpeg" | "png" | "webp";

export interface StoredDocument {
  id: Id;
  originalFilename: string;
  storageKey: string;
  mimeType: string;
  fileExtension: FileExtension;
  fileSizeBytes: number;
  /** Duplicate detection, per tenant (BR-DOC-02). */
  sha256Hash: string;
  pageCount?: number;
  documentType: BusinessDocumentType;
  documentTypeConfidence?: Percent;
  supplierId: Id | null;
  supplierConfidence?: Percent;
  processingStatus: DocumentProcessingStatus;
  processingStage?: string;
  processingProgress?: number;
  extractionConfidence?: Percent | null;
  itemsFound?: number | null;
  errorCode?: string | null;
  errorMessage?: string | null;
  source: "upload" | "email" | "api" | "whatsapp";
  uploadedBy: Id;
  uploadedByName: string;
  uploadedAt: Timestamp;
  duplicateOfDocumentId?: Id | null;
}

export type DocumentLinkedType =
  | "rfq"
  | "supplier_quotation"
  | "purchase_order"
  | "proforma_invoice"
  | "goods_receipt"
  | "supplier_invoice"
  | "purchase_return"
  | "product"
  | "supplier"
  | "company";

export interface DocumentLink {
  id: Id;
  documentId: Id;
  linkedType: DocumentLinkedType;
  linkedId: Id;
  linkRole: "source" | "attachment" | "signed_copy" | "supporting" | "logo";
  linkedBy: Id;
  linkedAt: Timestamp;
}

/* ---------------------------------------------------------- AI pipeline */

export type AiJobType =
  | "extraction"
  | "classification"
  | "schema_mapping"
  | "sku_match"
  | "embedding"
  | "assistant";

export type AiJobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "dead_letter";

export interface AiProcessingJob {
  id: Id;
  documentId: Id | null;
  jobType: AiJobType;
  status: AiJobStatus;
  stage?: string;
  progress: number;
  provider?: string;
  modelId?: string;
  modelTier?: "small" | "large";
  promptName?: string;
  promptVersion?: string;
  inputTokens?: number;
  outputTokens?: number;
  costUsd?: number;
  startedAt?: Timestamp | null;
  finishedAt?: Timestamp | null;
  durationMs?: number;
  attempt: number;
  errorCode?: string | null;
  errorMessage?: string | null;
  triggeredBy?: Id | null;
}

export type ExtractionReviewStatus = "pending" | "in_review" | "approved" | "rejected";

export interface AiExtractionResult {
  id: Id;
  documentId: Id;
  jobId: Id;
  schemaMappingId: Id | null;
  documentType: BusinessDocumentType;
  supplierId: Id | null;
  supplierConfidence?: Percent;
  overallConfidence: Percent;
  pageCount: number;
  lineCount: number;
  pipelineTrace: { step: string; result: string; state: "done" | "current" | "pending" }[];
  validationErrors?: { field: string; code: string; message: string }[];
  reviewStatus: ExtractionReviewStatus;
  reviewedBy?: Id | null;
  reviewedAt?: Timestamp | null;
  rejectionReason?: string;
  promotedToType?: "supplier_quotation" | "proforma_invoice" | "supplier_invoice" | null;
  promotedToId?: Id | null;
  createdAt: Timestamp;
}

export interface AiExtractedField {
  id: Id;
  extractionResultId: Id;
  fieldKey: string;
  fieldLabel: string;
  rawValue: string;
  normalisedValue?: string;
  valueType: "string" | "number" | "date" | "currency" | "gstin";
  confidence: Percent | null;
  provenance: Provenance;
  sourcePage?: number;
  sourceCell?: string;
  correctedValue?: string | null;
  correctedBy?: Id | null;
  correctedAt?: Timestamp | null;
  validationError?: string | null;
}

export interface AiExtractedLine {
  id: Id;
  extractionResultId: Id;
  lineNo: number;
  /** The supplier's own words — never modified. */
  rawDescription: string;
  normalisedDescription?: string;
  supplierSku?: string;
  quantity: Quantity;
  uomId: Id | null;
  rawUom?: string;
  unitPrice: Money;
  discountPct?: Percent;
  gstRate: Percent;
  hsnCode?: string;
  /** Cross-check only — never stored as the authoritative total (BR-AI-02). */
  lineTotalAsPrinted?: Money;
  matchedVariantId: Id | null;
  matchMethod?: MatchMethod;
  matchScore?: number;
  confidence: Percent;
  provenance: Provenance;
  suggestionText?: string;
  finalVariantId?: Id | null;
  finalDecision?: "accepted_ai" | "changed" | "new_product" | "skipped" | null;
  decidedBy?: Id | null;
  decidedAt?: Timestamp | null;
  aliasSaved: boolean;
}

export interface AiMatchCandidate {
  id: Id;
  extractedLineId: Id | null;
  queryText: string;
  normalisedQuery: string;
  supplierId?: Id | null;
  rank: number;
  productVariantId: Id;
  sku: string;
  productName: string;
  matchMethod: MatchMethod;
  score: number;
  confidence: Percent;
  reasons: string[];
  isSelected: boolean;
}

export interface AiReviewAction {
  id: Id;
  extractionResultId: Id;
  targetType: "field" | "line" | "document" | "mapping";
  targetId: Id;
  action:
    | "accept" | "edit" | "match" | "unmatch" | "reject_line"
    | "approve_document" | "reject_document" | "save_alias" | "confirm_mapping";
  beforeValue: unknown;
  afterValue: unknown;
  reason?: string;
  reviewerId: Id;
  reviewerName: string;
  reviewedAt: Timestamp;
}

/** A whole extraction assembled for the review screen. */
export interface ExtractionView {
  extraction: AiExtractionResult;
  document: StoredDocument;
  job: AiProcessingJob | null;
  fields: AiExtractedField[];
  lines: (AiExtractedLine & { candidates: AiMatchCandidate[] })[];
  totals: { subtotal: Money; tax: Money; total: Money };
  unresolvedCount: number;
  fieldsNeedingReview: number;
  canApprove: boolean;
}

/* ------------------------------------------------------ Schema mapping */

export type SchemaMappingStatus = "proposed" | "confirmed" | "deprecated";

export interface CanonicalField {
  id: Id;
  code: string;
  label: string;
  fieldGroup: "header" | "line";
  dataType: "string" | "number" | "date" | "currency" | "percent" | "uom";
  appliesToDocTypes: BusinessDocumentType[];
  isRequired: boolean;
  synonyms: string[];
  description?: string;
}

export type MappingTransform =
  | "none"
  | "trim"
  | "upper"
  | "strip_currency"
  | "parse_indian_number"
  | "percent_to_decimal"
  | "date_ddmmyyyy"
  | "multiply";

export interface DocumentSchemaMappingField {
  id: Id;
  mappingId: Id;
  sourceColumn: string;
  sourceColumnIndex: number;
  canonicalFieldCode: string;
  transform: MappingTransform;
  transformArg?: string;
  isRequired: boolean;
  confidence: Percent;
  confirmedBy?: Id | null;
  confirmedAt?: Timestamp | null;
  /** Sample values read from the file, shown in the confirmation UI. */
  sampleValues?: string[];
}

export interface DocumentSchemaMapping {
  id: Id;
  supplierId: Id | null;
  supplierName?: string;
  documentType: BusinessDocumentType;
  fileFormat: "xlsx" | "csv" | "pdf_table" | "docx";
  mappingName: string;
  columnSignature: string;
  headerRowIndex: number;
  dataStartRow: number;
  sheetName?: string;
  sampleDocumentId?: Id | null;
  status: SchemaMappingStatus;
  confidence: Percent;
  confirmedBy?: Id | null;
  confirmedAt?: Timestamp | null;
  usageCount: number;
  lastUsedAt?: Timestamp | null;
  successRate: Percent;
  version: number;
  createdAt: Timestamp;
}

/* --------------------------------------------------------- Assistant */

export interface AssistantAnswer {
  intent: string;
  source: string;
  answer: string;
  breakdown?: { label: string; value: string; muted?: boolean }[];
  table?: { columns: string[]; rows: string[][] };
  link?: { label: string; href: string };
  confidence?: number;
}

/* ----------------------------------------------------- Upload payloads */

export interface UploadDocumentInput {
  fileName: string;
  fileSizeBytes: number;
  fileExtension: FileExtension;
  mimeType: string;
  documentType?: BusinessDocumentType;
  supplierId?: Id | null;
  link?: { linkedType: DocumentLinkedType; linkedId: Id };
}

export interface UploadDocumentResult {
  document: StoredDocument;
  jobId: Id | null;
  duplicateOf: StoredDocument | null;
}

export interface DocumentJobStatus {
  documentId: Id;
  processingStatus: DocumentProcessingStatus;
  processingStage?: string;
  processingProgress: number;
  extractionConfidence?: Percent | null;
  itemsFound?: number | null;
  extractionResultId?: Id | null;
  error?: { code: string; message: string } | null;
}

/** Expiry/batch aware view for GRN batch capture (I9). */
export interface BatchInput {
  batchNumber: string;
  manufacturedOn?: DateOnly | null;
  expiresOn?: DateOnly | null;
}
