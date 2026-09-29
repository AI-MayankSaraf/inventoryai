/**
 * The single money and tax engine.
 *
 * Every rupee shown anywhere in the app is produced here. Components must not
 * multiply quantity by price, apply a GST rate, or split CGST/SGST themselves
 * — that was the duplicated-tax-logic defect (C13). When the backend exists it
 * returns these same fields and this module becomes a display-only formatter;
 * the shapes do not change.
 *
 * Order of operations (BR-FIN-01), matching the backend spec:
 *   1. line net      = round2(quantity × unitPrice) − discount
 *   2. line tax      = round2(lineNet × gstRate / 100)
 *   3. line cess     = round2(lineNet × cessRate / 100)
 *   4. document tax  = Σ line tax, then split by place of supply
 *   5. round off     = nearest rupee on the grand total
 *
 * Tax is computed per line and summed. Never on the document subtotal — a
 * document may mix 5%, 12%, 18% and 28% lines.
 */

import type {
  LineTotals,
  Money,
  MoneyTotals,
  Percent,
  RoundingMode,
  TaxableLine,
} from "@/types";

/** Currency arithmetic is done on 2-decimal values, half-up like the backend. */
export function round2(value: number): number {
  if (!Number.isFinite(value)) return 0;
  const scaled = Math.round((Math.abs(value) + Number.EPSILON) * 100) / 100;
  return value < 0 ? -scaled : scaled;
}

export function round3(value: number): number {
  if (!Number.isFinite(value)) return 0;
  const scaled = Math.round((Math.abs(value) + Number.EPSILON) * 1000) / 1000;
  return value < 0 ? -scaled : scaled;
}

/** Totals for one document line. */
export function computeLine(line: TaxableLine): LineTotals {
  const gross = round2((line.quantity || 0) * (line.unitPrice || 0));
  const discount = round2((gross * (line.discountPct || 0)) / 100);
  const lineNet = round2(gross - discount);
  const lineTax = round2((lineNet * (line.gstRate || 0)) / 100);
  const lineCess = round2((lineNet * (line.cessRate || 0)) / 100);
  return {
    lineNet,
    lineTax,
    lineCess,
    lineTotal: round2(lineNet + lineTax + lineCess),
  };
}

/**
 * Inter-state is a fact about two state codes, never a stored flag someone
 * typed (C14). Supplier state ≠ place of supply → IGST.
 */
export function isInterState(
  supplierStateCode: string | null | undefined,
  placeOfSupplyStateCode: string | null | undefined,
): boolean {
  if (!supplierStateCode || !placeOfSupplyStateCode) return false;
  return supplierStateCode.padStart(2, "0") !== placeOfSupplyStateCode.padStart(2, "0");
}

export interface DocumentChargeInput {
  freightAmount?: Money;
  otherCharges?: Money;
  /** Header-level discount applied after line discounts. */
  documentDiscount?: Money;
  rounding?: RoundingMode;
}

export interface DocumentTotalsInput extends DocumentChargeInput {
  lines: TaxableLine[];
  supplierStateCode?: string | null;
  placeOfSupplyStateCode?: string | null;
  /** Overrides the derived value only where the law does (exports, SEZ). */
  forceInterState?: boolean;
}

/**
 * Document totals. `isInterState` decides whether the summed tax lands in
 * IGST or is split equally into CGST and SGST.
 */
export function computeDocumentTotals(input: DocumentTotalsInput): MoneyTotals {
  const inter =
    input.forceInterState ??
    isInterState(input.supplierStateCode, input.placeOfSupplyStateCode);

  let subtotal = 0;
  let lineDiscount = 0;
  let taxableValue = 0;
  let tax = 0;
  let cess = 0;

  for (const line of input.lines) {
    const gross = round2((line.quantity || 0) * (line.unitPrice || 0));
    const totals = computeLine(line);
    subtotal = round2(subtotal + gross);
    lineDiscount = round2(lineDiscount + (gross - totals.lineNet));
    taxableValue = round2(taxableValue + totals.lineNet);
    tax = round2(tax + totals.lineTax);
    cess = round2(cess + totals.lineCess);
  }

  const documentDiscount = round2(input.documentDiscount || 0);
  const discountAmount = round2(lineDiscount + documentDiscount);
  taxableValue = round2(taxableValue - documentDiscount);

  const freightAmount = round2(input.freightAmount || 0);
  const otherCharges = round2(input.otherCharges || 0);

  const cgstAmount = inter ? 0 : round2(tax / 2);
  const sgstAmount = inter ? 0 : round2(tax - round2(tax / 2));
  const igstAmount = inter ? tax : 0;

  const beforeRounding = round2(
    taxableValue + cgstAmount + sgstAmount + igstAmount + cess + freightAmount + otherCharges,
  );
  const { roundOff, totalAmount } = applyRounding(beforeRounding, input.rounding ?? "nearest");

  return {
    subtotal,
    discountAmount,
    taxableValue,
    cgstAmount,
    sgstAmount,
    igstAmount,
    cessAmount: cess,
    freightAmount,
    otherCharges,
    roundOff,
    totalAmount,
    isInterState: inter,
  };
}

export function applyRounding(
  amount: Money,
  mode: RoundingMode,
): { roundOff: Money; totalAmount: Money } {
  if (mode === "none") return { roundOff: 0, totalAmount: round2(amount) };
  const target = mode === "up" ? Math.ceil(amount) : Math.round(amount);
  return { roundOff: round2(target - amount), totalAmount: round2(target) };
}

/** The GST breakdown table shown on document detail screens. */
export interface TaxBreakdownRow {
  gstRate: Percent;
  taxableValue: Money;
  cgstAmount: Money;
  sgstAmount: Money;
  igstAmount: Money;
  cessAmount: Money;
  totalTax: Money;
}

export function taxBreakdown(lines: TaxableLine[], inter: boolean): TaxBreakdownRow[] {
  const byRate = new Map<number, { taxable: number; tax: number; cess: number }>();
  for (const line of lines) {
    const totals = computeLine(line);
    const key = line.gstRate || 0;
    const bucket = byRate.get(key) ?? { taxable: 0, tax: 0, cess: 0 };
    bucket.taxable = round2(bucket.taxable + totals.lineNet);
    bucket.tax = round2(bucket.tax + totals.lineTax);
    bucket.cess = round2(bucket.cess + totals.lineCess);
    byRate.set(key, bucket);
  }
  return [...byRate.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([gstRate, b]) => ({
      gstRate,
      taxableValue: b.taxable,
      cgstAmount: inter ? 0 : round2(b.tax / 2),
      sgstAmount: inter ? 0 : round2(b.tax - round2(b.tax / 2)),
      igstAmount: inter ? b.tax : 0,
      cessAmount: b.cess,
      totalTax: round2(b.tax + b.cess),
    }));
}

/* ------------------------------------------------------------ Formatting */

const INR = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

const INR_PAISE = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatMoney(value: Money | null | undefined, showPaise = false): string {
  const n = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return showPaise ? INR_PAISE.format(n) : INR.format(n);
}

/** Compact form for KPI tiles: ₹48.2L, ₹1.2Cr. */
export function formatMoneyCompact(value: Money | null | undefined): string {
  const n = typeof value === "number" && Number.isFinite(value) ? value : 0;
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1e7) return `${sign}₹${round2(abs / 1e7)}Cr`;
  if (abs >= 1e5) return `${sign}₹${round2(abs / 1e5)}L`;
  if (abs >= 1e3) return `${sign}₹${round2(abs / 1e3)}K`;
  return `${sign}₹${round2(abs)}`;
}

export function formatQuantity(value: number | null | undefined, decimals = 0): string {
  const n = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return n.toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatPercent(value: Percent | null | undefined, decimals = 0): string {
  const n = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return `${n.toFixed(decimals)}%`;
}

/** Signed variance, e.g. `+4.2%`. */
export function formatVariancePct(value: Percent | null | undefined, decimals = 1): string {
  const n = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return `${n > 0 ? "+" : ""}${n.toFixed(decimals)}%`;
}

export function variancePct(base: number, compare: number): Percent {
  if (!base) return compare ? 100 : 0;
  return round2(((compare - base) / base) * 100);
}
