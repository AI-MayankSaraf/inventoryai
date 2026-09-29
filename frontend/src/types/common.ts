/**
 * Shared primitives for the whole domain model.
 *
 * These types mirror `02_DATABASE_DESIGN.md`. Anything that will be a column
 * in PostgreSQL is represented here the way the backend will return it, so
 * swapping the mock API for the real one is a change of implementation, not
 * of shape.
 */

/** Every entity is keyed by an opaque id. The backend will issue UUIDs. */
export type Id = string;

/**
 * Money and quantities travel as strings in the real API (NUMERIC columns) to
 * avoid float drift. In the prototype we keep `number` for ergonomics but
 * funnel every calculation through `lib/domain/money.ts`, which is the single
 * place that will be swapped for backend-supplied totals.
 */
export type Money = number;
export type Quantity = number;
export type Percent = number;

/** `YYYY-MM-DD` — a business date, not an instant. */
export type DateOnly = string;
/** RFC 3339 instant. */
export type Timestamp = string;

/* ------------------------------------------------------------------ Query */

/**
 * The list-query contract every collection endpoint accepts. Components build
 * one of these instead of filtering arrays, so moving the work to the server
 * later changes nothing in the UI.
 */
export interface ListParams {
  /** Free-text search across the resource's searchable fields. */
  q?: string;
  /** Field-level equality filters, e.g. `{ status: "draft", supplierId: "..." }`. */
  filters?: Record<string, string | undefined>;
  /** `field` or `-field` for descending. */
  sort?: string;
  limit?: number;
  /** Opaque keyset cursor returned by the previous page. */
  cursor?: string | null;
  dateFrom?: DateOnly;
  dateTo?: DateOnly;
}

export interface ListResponse<T> {
  items: T[];
  nextCursor: string | null;
  total: number;
  /** Optional facet counts a list screen can render as filter options. */
  facets?: Record<string, { value: string; label: string; count: number }[]>;
}

export interface ApiResult<T> {
  ok: boolean;
  data?: T;
  error?: string;
  /** Business-rule id from `06_BUSINESS_RULES.md`, e.g. `BR-GRN-06`. */
  code?: string;
  fieldErrors?: { field: string; message: string }[];
}

/** Thrown/returned when a state transition is not allowed. */
export interface TransitionError {
  code: "INVALID_STATE_TRANSITION";
  from: string;
  to: string;
  allowed: string[];
}

/* ------------------------------------------------------- Money primitives */

/**
 * The canonical money block every financial document carries. Produced only by
 * `lib/domain/money.ts` (today) and by the backend (later) — never assembled
 * inside a component.
 */
export interface MoneyTotals {
  subtotal: Money;
  discountAmount: Money;
  taxableValue: Money;
  cgstAmount: Money;
  sgstAmount: Money;
  igstAmount: Money;
  cessAmount: Money;
  freightAmount: Money;
  otherCharges: Money;
  roundOff: Money;
  totalAmount: Money;
  /** True → IGST; false → CGST + SGST. Derived from the two state codes. */
  isInterState: boolean;
}

/** A line as the money engine needs to see it. */
export interface TaxableLine {
  quantity: Quantity;
  unitPrice: Money;
  discountPct?: Percent;
  gstRate: Percent;
  cessRate?: Percent;
}

export interface LineTotals {
  lineNet: Money;
  lineTax: Money;
  lineCess: Money;
  lineTotal: Money;
}

export type RoundingMode = "nearest" | "up" | "none";

/* ------------------------------------------------------------- Provenance */

/**
 * How a value came to be. Drives the AI provenance badges the UI already
 * renders, and records whether a human has taken responsibility for a value.
 */
export type Provenance =
  | "ai_extracted"
  | "ai_suggested"
  | "needs_review"
  | "user_approved"
  | "calculated";

/** Which rung of the matching ladder resolved a line. */
export type MatchMethod =
  | "exact_sku"
  | "supplier_alias"
  | "barcode"
  | "normalised_rule"
  | "trigram"
  | "embedding"
  | "llm"
  | "manual";

/* ------------------------------------------------------ Audit metadata */

export interface AuditFields {
  createdAt: Timestamp;
  updatedAt: Timestamp;
  createdBy?: Id;
  updatedBy?: Id;
}

/** Master data is deactivated or soft-deleted, never removed (BR-MD-04). */
export interface SoftDeletable {
  isActive: boolean;
  deletedAt: Timestamp | null;
}
