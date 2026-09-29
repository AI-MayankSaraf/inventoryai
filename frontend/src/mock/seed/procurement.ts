/**
 * The seeded procurement chain: RFQ → Quotation → Comparison → PO → Proforma
 * → GRN → Supplier Invoice → Purchase Return, plus the variances those
 * comparisons produce.
 *
 * Two rules this file exists to demonstrate:
 *
 *  1. Every link is an id. `grn.purchaseOrderId` and `grnItem.purchaseOrderItemId`
 *     carry the relationship; `po.poNumber` is only ever displayed (C12).
 *  2. No financial total is typed by hand. Line and document money comes from
 *     `lib/domain/money.ts`, the same engine the screens use (C13), and
 *     CGST/SGST vs IGST is derived from the two state codes (C14).
 */

import { computeDocumentTotals, computeLine, round2, variancePct } from "@/lib/domain/money";
import type {
  DocumentVariance,
  GoodsReceipt,
  GoodsReceiptItem,
  ProformaInvoice,
  ProformaInvoiceItem,
  PurchaseOrder,
  PurchaseOrderItem,
  PurchaseReturn,
  PurchaseReturnItem,
  QuotationComparison,
  QuotationComparisonLine,
  Rfq,
  RfqItem,
  RfqSupplier,
  SupplierInvoice,
  SupplierInvoiceItem,
  SupplierQuotation,
  SupplierQuotationItem,
} from "@/types";
import {
  COMPARISON,
  GODOWN,
  GRN,
  PO,
  PROFORMA,
  PURCHASE_RETURN,
  QUOTE,
  RFQ,
  SUPPLIER,
  SUPPLIER_INVOICE,
  UOM,
  USER,
  variantId,
} from "../ids";

/* ------------------------------------------------------------- Reference */

/** Supplier → state code, so inter-state can be derived rather than stored. */
const SUPPLIER_STATE: Record<string, string> = {
  [SUPPLIER.flipkart]: "29",
  [SUPPLIER.reliance]: "27",
  [SUPPLIER.lg]: "07",
  [SUPPLIER.whirlpool]: "06",
  [SUPPLIER.balaji]: "09",
  [SUPPLIER.sundram]: "33",
  [SUPPLIER.indore]: "23",
  [SUPPLIER.ahmedabad]: "24",
  [SUPPLIER.malwa]: "23",
};

const GODOWN_STATE: Record<string, string> = {
  [GODOWN.main]: "23",
  [GODOWN.secondary]: "27",
};

const HSN: Record<string, string> = {
  SKU001: "7615", SKU002: "8509", SKU003: "8418", SKU004: "1101", SKU005: "2106",
  SKU010: "8516", SKU011: "8414", SKU012: "8414", SKU013: "8536", SKU020: "7318",
  SKU028: "7318", SKU031: "8539", SKU035: "8450", SKU041: "8516",
};

const NAME: Record<string, string> = {
  SKU001: "Pigeon Cooker 5L",
  SKU002: "Philips Mixer Grinder 750W",
  SKU003: "LG Refrigerator 260L",
  SKU004: "Aashirvaad Atta 10kg",
  SKU005: "Haldiram Namkeen 200g",
  SKU010: "Prestige Induction Cooktop 1900W",
  SKU011: "Havells Ceiling Fan 1200mm",
  SKU012: "Crompton Ceiling Fan 1200mm",
  SKU013: "Anchor Modular Switch",
  SKU020: "Hex Bolt M8x40",
  SKU028: "SS Hex Bolt M10 × 50mm",
  SKU031: "Havells LED Bulb 9W",
  SKU035: "Whirlpool Washing Machine 7kg",
  SKU041: "Bajaj Water Heater 15L",
};

const GST: Record<string, number> = {
  SKU001: 18, SKU002: 18, SKU003: 28, SKU004: 5, SKU005: 12,
  SKU010: 18, SKU011: 18, SKU012: 18, SKU013: 18, SKU020: 18,
  SKU028: 18, SKU031: 12, SKU035: 28, SKU041: 18,
};

type LineSpec = {
  sku: string;
  qty: number;
  price: number;
  discountPct?: number;
  uomId?: string;
};

const taxable = (l: LineSpec) => ({
  quantity: l.qty,
  unitPrice: l.price,
  discountPct: l.discountPct ?? 0,
  gstRate: GST[l.sku],
  cessRate: 0,
});

/* ------------------------------------------------------------------ RFQ */

type RfqSpec = {
  id: string;
  number: string;
  date: string;
  expected: string | null;
  subject: string;
  godownId: string | null;
  status: Rfq["status"];
  createdFrom: Rfq["createdFrom"];
  notes: string;
  supplierIds: string[];
  supplierStatus: Record<string, RfqSupplier["status"]>;
  lines: LineSpec[];
};

const RFQ_SPECS: RfqSpec[] = [
  {
    id: RFQ.appliances, number: "RFQ-2026-00057", date: "2026-09-10", expected: "2026-09-20",
    subject: "Kitchen and Home Appliances — Sep 2026", godownId: GODOWN.main, status: "quoted",
    createdFrom: "manual", notes: "Festive season build-up. Quote landed price including freight to Indore.",
    supplierIds: [SUPPLIER.flipkart, SUPPLIER.reliance, SUPPLIER.lg],
    supplierStatus: { [SUPPLIER.flipkart]: "quoted", [SUPPLIER.reliance]: "quoted", [SUPPLIER.lg]: "quoted" },
    lines: [
      { sku: "SKU001", qty: 40, price: 1180 },
      { sku: "SKU002", qty: 30, price: 2800 },
      { sku: "SKU003", qty: 10, price: 24000 },
    ],
  },
  {
    id: RFQ.electricals, number: "RFQ-2026-00056", date: "2026-09-08", expected: "2026-09-18",
    subject: "Electricals restock — fans and lighting", godownId: GODOWN.main, status: "partially_quoted",
    createdFrom: "low_stock", notes: "Raised from the low-stock worklist.",
    supplierIds: [SUPPLIER.ahmedabad, SUPPLIER.reliance],
    supplierStatus: { [SUPPLIER.ahmedabad]: "quoted", [SUPPLIER.reliance]: "sent" },
    lines: [
      { sku: "SKU011", qty: 40, price: 1620 },
      { sku: "SKU012", qty: 25, price: 1320 },
      { sku: "SKU013", qty: 150, price: 95 },
      { sku: "SKU031", qty: 200, price: 78 },
    ],
  },
  {
    id: RFQ.fasteners, number: "RFQ-2026-00055", date: "2026-09-01", expected: "2026-09-11",
    subject: "Hardware fasteners — quarterly", godownId: GODOWN.secondary, status: "closed",
    createdFrom: "manual", notes: "Quarterly fastener call-off for the Pune godown.",
    supplierIds: [SUPPLIER.sundram],
    supplierStatus: { [SUPPLIER.sundram]: "quoted" },
    lines: [
      { sku: "SKU020", qty: 5000, price: 2.4 },
      { sku: "SKU028", qty: 1000, price: 12 },
    ],
  },
  {
    id: RFQ.fmcg, number: "RFQ-2026-00054", date: "2026-08-26", expected: "2026-09-05",
    subject: "FMCG staples — monthly replenishment", godownId: GODOWN.main, status: "closed",
    createdFrom: "low_stock", notes: "Batch-tracked items — quote must state manufacturing date.",
    supplierIds: [SUPPLIER.reliance, SUPPLIER.balaji],
    supplierStatus: { [SUPPLIER.reliance]: "declined", [SUPPLIER.balaji]: "quoted" },
    lines: [
      { sku: "SKU004", qty: 120, price: 420, uomId: UOM.bag },
      { sku: "SKU005", qty: 300, price: 42, uomId: UOM.pack },
    ],
  },
  {
    id: RFQ.festive, number: "RFQ-2026-00058", date: "2026-09-12", expected: "2026-09-25",
    subject: "Large appliances — festive stocking", godownId: GODOWN.main, status: "draft",
    createdFrom: "manual", notes: "",
    supplierIds: [],
    supplierStatus: {},
    lines: [
      { sku: "SKU003", qty: 15, price: 24000 },
      { sku: "SKU035", qty: 12, price: 15800 },
    ],
  },
];

export const rfqs: Rfq[] = RFQ_SPECS.map((s) => ({
  id: s.id,
  rfqNumber: s.number,
  rfqDate: s.date,
  expectedDeliveryDate: s.expected,
  subject: s.subject,
  deliveryGodownId: s.godownId,
  notes: s.notes,
  status: s.status,
  sentAt: s.status === "draft" ? null : `${s.date}T11:30:00+05:30`,
  closedAt: s.status === "closed" ? `${s.expected}T18:00:00+05:30` : null,
  estimatedValue: round2(s.lines.reduce((sum, l) => sum + l.qty * l.price, 0)),
  createdFrom: s.createdFrom,
  createdAt: `${s.date}T10:15:00+05:30`,
  rowVersion: 1,
}));

export const rfqItems: RfqItem[] = RFQ_SPECS.flatMap((s) =>
  s.lines.map((l, i) => ({
    id: `${s.id}_li${i + 1}`,
    rfqId: s.id,
    lineNo: i + 1,
    productVariantId: variantId(l.sku),
    description: NAME[l.sku],
    quantity: l.qty,
    uomId: l.uomId ?? UOM.nos,
    expectedPrice: l.price,
  })),
);

export const rfqSuppliers: RfqSupplier[] = RFQ_SPECS.flatMap((s) =>
  s.supplierIds.map((supplierId, i) => ({
    id: `${s.id}_sup${i + 1}`,
    rfqId: s.id,
    supplierId,
    status: s.supplierStatus[supplierId] ?? "sent",
    sentAt: `${s.date}T11:30:00+05:30`,
    respondedAt: s.supplierStatus[supplierId] === "quoted" ? `${s.date}T17:40:00+05:30` : null,
    declineReason:
      s.supplierStatus[supplierId] === "declined" ? "Item not stocked for B2B channel" : undefined,
  })),
);

const rfqItemId = (rfqId: string, sku: string) =>
  rfqItems.find((i) => i.rfqId === rfqId && i.productVariantId === variantId(sku))?.id ?? null;

/* ----------------------------------------------------------- Quotations */

type QuoteLineSpec = LineSpec & {
  available?: boolean;
  note?: string;
  supplierSku?: string;
  matchMethod?: SupplierQuotationItem["matchMethod"];
  matchConfidence?: number;
  provenance?: SupplierQuotationItem["provenance"];
};

type QuoteSpec = {
  id: string;
  number: string;
  supplierId: string;
  rfqId: string;
  date: string;
  validUntil: string | null;
  status: SupplierQuotation["status"];
  source: SupplierQuotation["source"];
  confidence: number | null;
  documentId: string | null;
  freight?: number;
  paymentTerms: string;
  deliveryTerms: string;
  deliveryDays: number | null;
  warrantyTerms: string;
  freightTerms: string;
  lines: QuoteLineSpec[];
};

const QUOTE_SPECS: QuoteSpec[] = [
  {
    id: QUOTE.reliance, number: "QT-RR-3391", supplierId: SUPPLIER.reliance, rfqId: RFQ.appliances,
    date: "2026-09-11", validUntil: "2026-09-25", status: "under_review", source: "ai_extracted",
    confidence: 96, documentId: "doc_qt_rr_3391", freight: 0,
    paymentTerms: "30 Days", deliveryTerms: "FOR Indore", deliveryDays: 7,
    warrantyTerms: "Manufacturer warranty", freightTerms: "Included",
    lines: [
      { sku: "SKU001", qty: 40, price: 1180, supplierSku: "RR-PGN-5L", matchMethod: "supplier_alias", matchConfidence: 99, provenance: "ai_extracted" },
      { sku: "SKU002", qty: 30, price: 2800, supplierSku: "RR-PHL-MG750", matchMethod: "supplier_alias", matchConfidence: 99, provenance: "ai_extracted" },
      { sku: "SKU003", qty: 10, price: 24500, supplierSku: "RR-LG-260", matchMethod: "trigram", matchConfidence: 81, provenance: "needs_review" },
    ],
  },
  {
    id: QUOTE.flipkart, number: "FK/QTN/8821", supplierId: SUPPLIER.flipkart, rfqId: RFQ.appliances,
    date: "2026-09-11", validUntil: "2026-09-21", status: "under_review", source: "ai_extracted",
    confidence: 91, documentId: "doc_qt_fk_8821", freight: 1800,
    paymentTerms: "15 Days", deliveryTerms: "Ex-Bengaluru", deliveryDays: 10,
    warrantyTerms: "Manufacturer warranty", freightTerms: "Extra at actuals",
    lines: [
      { sku: "SKU001", qty: 40, price: 1215, supplierSku: "FK8899001", matchMethod: "supplier_alias", matchConfidence: 98, provenance: "ai_extracted" },
      { sku: "SKU002", qty: 30, price: 2860, supplierSku: "FK8899002", matchMethod: "supplier_alias", matchConfidence: 98, provenance: "ai_extracted" },
      { sku: "SKU003", qty: 10, price: 24900, supplierSku: "FK1120003", matchMethod: "llm", matchConfidence: 72, provenance: "needs_review" },
    ],
  },
  {
    id: QUOTE.lg, number: "LG-Q-556102", supplierId: SUPPLIER.lg, rfqId: RFQ.appliances,
    date: "2026-09-12", validUntil: "2026-09-30", status: "approved", source: "manual",
    confidence: null, documentId: null,
    paymentTerms: "45 Days", deliveryTerms: "FOR Indore", deliveryDays: 12,
    warrantyTerms: "1 yr + 10 yr compressor", freightTerms: "Included",
    lines: [
      { sku: "SKU001", qty: 40, price: 0, available: false, note: "Not in LG range", provenance: "user_approved" },
      { sku: "SKU002", qty: 30, price: 0, available: false, note: "Not in LG range", provenance: "user_approved" },
      { sku: "SKU003", qty: 10, price: 24000, matchMethod: "manual", matchConfidence: 100, provenance: "user_approved" },
    ],
  },
  {
    id: QUOTE.ahmedabad, number: "AEC-2026-441", supplierId: SUPPLIER.ahmedabad, rfqId: RFQ.electricals,
    date: "2026-09-09", validUntil: "2026-09-16", status: "expired", source: "ai_extracted",
    confidence: 78, documentId: "doc_qt_aec_441",
    paymentTerms: "21 Days", deliveryTerms: "FOR Indore", deliveryDays: 5,
    warrantyTerms: "2 years on fans", freightTerms: "Included",
    lines: [
      { sku: "SKU011", qty: 40, price: 1620, supplierSku: "AEC-HAV-1200", matchMethod: "supplier_alias", matchConfidence: 97, provenance: "ai_extracted" },
      { sku: "SKU012", qty: 25, price: 1320, supplierSku: "AEC-CRM-1200", matchMethod: "supplier_alias", matchConfidence: 97, provenance: "ai_extracted" },
      { sku: "SKU013", qty: 150, price: 95, supplierSku: "AEC-SW-6A", matchMethod: "normalised_rule", matchConfidence: 74, provenance: "needs_review" },
      { sku: "SKU031", qty: 200, price: 78, supplierSku: "AEC-LED-9W", matchMethod: "supplier_alias", matchConfidence: 96, provenance: "ai_extracted" },
    ],
  },
  {
    id: QUOTE.sundram, number: "SFL/QT/2291", supplierId: SUPPLIER.sundram, rfqId: RFQ.fasteners,
    date: "2026-09-02", validUntil: "2026-09-26", status: "converted", source: "ai_extracted",
    confidence: 88, documentId: "doc_qt_sfl_2291",
    paymentTerms: "15 Days", deliveryTerms: "FOR Pune", deliveryDays: 8,
    warrantyTerms: "As per IS standard", freightTerms: "Included",
    lines: [
      { sku: "SKU020", qty: 5000, price: 2.4, discountPct: 5, supplierSku: "SF-HB-M8-40", matchMethod: "supplier_alias", matchConfidence: 96, provenance: "ai_extracted" },
      { sku: "SKU028", qty: 1000, price: 12, discountPct: 5, supplierSku: "SF-HB-M10-50-SS", matchMethod: "supplier_alias", matchConfidence: 96, provenance: "ai_extracted" },
    ],
  },
];

export const supplierQuotations: SupplierQuotation[] = QUOTE_SPECS.map((s) => {
  const available = s.lines.filter((l) => l.available !== false);
  const totals = computeDocumentTotals({
    lines: available.map(taxable),
    freightAmount: s.freight,
    forceInterState: false,
  });
  return {
    id: s.id,
    quotationNumber: s.number,
    supplierId: s.supplierId,
    rfqId: s.rfqId,
    quotationDate: s.date,
    validUntil: s.validUntil,
    currencyCode: "INR",
    subtotal: totals.subtotal,
    discountAmount: totals.discountAmount,
    taxableValue: totals.taxableValue,
    taxAmount: round2(totals.cgstAmount + totals.sgstAmount + totals.igstAmount),
    freightAmount: totals.freightAmount,
    otherCharges: totals.otherCharges,
    roundOff: totals.roundOff,
    totalAmount: totals.totalAmount,
    paymentTerms: s.paymentTerms,
    deliveryTerms: s.deliveryTerms,
    deliveryPeriodDays: s.deliveryDays,
    warrantyTerms: s.warrantyTerms,
    freightTerms: s.freightTerms,
    source: s.source,
    documentId: s.documentId,
    aiExtractionResultId: s.documentId ? `aix_${s.id}` : null,
    extractionConfidence: s.confidence,
    status: s.status,
    approvedBy: s.status === "approved" ? USER.purchaseMgr : null,
    approvedAt: s.status === "approved" ? `${s.date}T16:10:00+05:30` : null,
    createdAt: `${s.date}T14:00:00+05:30`,
    rowVersion: 1,
  };
});

export const supplierQuotationItems: SupplierQuotationItem[] = QUOTE_SPECS.flatMap((s) =>
  s.lines.map((l, i) => {
    const totals = computeLine(taxable(l));
    return {
      id: `${s.id}_li${i + 1}`,
      quotationId: s.id,
      lineNo: i + 1,
      rfqItemId: rfqItemId(s.rfqId, l.sku),
      productVariantId: variantId(l.sku),
      rawDescription: l.supplierSku ? `${l.supplierSku} — ${NAME[l.sku].toUpperCase()}` : NAME[l.sku],
      supplierSku: l.supplierSku,
      quantity: l.qty,
      uomId: l.uomId ?? UOM.nos,
      unitPrice: l.price,
      discountPct: l.discountPct ?? 0,
      gstRate: GST[l.sku],
      cessRate: 0,
      lineNet: totals.lineNet,
      lineTax: totals.lineTax,
      lineTotal: totals.lineTotal,
      isAvailable: l.available !== false,
      availabilityNote: l.note,
      leadTimeDays: s.deliveryDays ?? undefined,
      matchConfidence: l.matchConfidence,
      matchMethod: l.matchMethod,
      provenance: l.provenance ?? "ai_extracted",
    };
  }),
);

/* ---------------------------------------------------------- Comparison */

const APPLIANCE_QUOTES = [QUOTE.reliance, QUOTE.flipkart, QUOTE.lg];

const comparisonLineSpecs = RFQ_SPECS[0].lines.map((l) => {
  const candidates = supplierQuotationItems.filter(
    (qi) =>
      APPLIANCE_QUOTES.includes(qi.quotationId as (typeof APPLIANCE_QUOTES)[number]) &&
      qi.productVariantId === variantId(l.sku) &&
      qi.isAvailable,
  );
  const cheapest = candidates.reduce(
    (best, c) => (best === null || c.lineTotal < best.lineTotal ? c : best),
    null as SupplierQuotationItem | null,
  );
  const prices = candidates.map((c) => c.unitPrice);
  const spread = prices.length > 1 ? variancePct(Math.min(...prices), Math.max(...prices)) : 0;
  return { sku: l.sku, qty: l.qty, cheapest, candidates, spread };
});

const splitTotal = round2(
  comparisonLineSpecs.reduce((sum, r) => sum + (r.cheapest?.lineTotal ?? 0), 0),
);

const singleSupplierTotals = APPLIANCE_QUOTES.map((quotationId) => {
  const quote = supplierQuotations.find((q) => q.id === quotationId)!;
  const covers = comparisonLineSpecs.every((r) =>
    r.candidates.some((c) => c.quotationId === quotationId),
  );
  return { quotationId, supplierId: quote.supplierId, total: quote.totalAmount, covers };
});

const bestSingle = singleSupplierTotals
  .filter((s) => s.covers)
  .reduce(
    (best, s) => (best === null || s.total < best.total ? s : best),
    null as (typeof singleSupplierTotals)[number] | null,
  );

export const quotationComparisons: QuotationComparison[] = [
  {
    id: COMPARISON.appliances,
    rfqId: RFQ.appliances,
    name: "Kitchen and Home Appliances — Sep 2026",
    comparedSupplierIds: [SUPPLIER.reliance, SUPPLIER.flipkart, SUPPLIER.lg],
    strategy: "split_optimal",
    singleSupplierBestSupplierId: bestSingle?.supplierId ?? null,
    singleSupplierBestTotal: bestSingle?.total ?? 0,
    splitTotal,
    projectedSavings: round2((bestSingle?.total ?? 0) - splitTotal),
    decidedBy: null,
    decidedAt: null,
    status: "draft",
    notes: "LG quoted only the refrigerator; the other two lines must come from Reliance or Flipkart.",
    createdAt: "2026-09-12T10:05:00+05:30",
  },
];

export const quotationComparisonLines: QuotationComparisonLine[] = comparisonLineSpecs.map((r, i) => ({
  id: `${COMPARISON.appliances}_li${i + 1}`,
  comparisonId: COMPARISON.appliances,
  rfqItemId: rfqItemId(RFQ.appliances, r.sku)!,
  productVariantId: variantId(r.sku),
  description: NAME[r.sku],
  quantity: r.qty,
  uomId: UOM.nos,
  selectedQuotationItemId: null,
  selectedSupplierId: null,
  recommendedQuotationItemId: r.cheapest?.id ?? null,
  recommendedSupplierId: r.cheapest
    ? supplierQuotations.find((q) => q.id === r.cheapest!.quotationId)!.supplierId
    : null,
  recommendationReason: r.cheapest
    ? r.candidates.length > 1
      ? `Lowest landed cost of ${r.candidates.length} quotes (${r.spread.toFixed(1)}% spread)`
      : "Only supplier quoting this line"
    : "No supplier quoted this line",
  recommendationScore: r.cheapest ? (r.candidates.length > 1 ? 92 : 70) : 0,
  priceSpreadPct: r.spread,
}));

/* ------------------------------------------------------ Purchase Orders */

type PoSpec = {
  id: string;
  number: string;
  supplierId: string;
  rfqId: string | null;
  quotationId: string | null;
  comparisonId: string | null;
  date: string;
  expected: string | null;
  godownId: string;
  status: PurchaseOrder["status"];
  paymentTerms: string;
  deliveryTerms: string;
  freight?: number;
  notes?: string;
  lines: LineSpec[];
};

const PO_SPECS: PoSpec[] = [
  {
    id: PO.reliance123, number: "PO-2026-00123", supplierId: SUPPLIER.reliance,
    rfqId: RFQ.appliances, quotationId: QUOTE.reliance, comparisonId: COMPARISON.appliances,
    date: "2026-09-10", expected: "2026-09-25", godownId: GODOWN.main, status: "sent",
    paymentTerms: "30 Days", deliveryTerms: "FOR Indore",
    notes: "Deliver in one lot. Refrigerators to be double-crated.",
    lines: [
      { sku: "SKU002", qty: 30, price: 2800 },
      { sku: "SKU003", qty: 10, price: 24500 },
    ],
  },
  {
    id: PO.lg122, number: "PO-2026-00122", supplierId: SUPPLIER.lg,
    rfqId: RFQ.appliances, quotationId: QUOTE.lg, comparisonId: null,
    date: "2026-09-08", expected: "2026-09-22", godownId: GODOWN.main, status: "partially_received",
    paymentTerms: "45 Days", deliveryTerms: "FOR Indore",
    lines: [{ sku: "SKU003", qty: 10, price: 24000 }],
  },
  {
    id: PO.whirlpool121, number: "PO-2026-00121", supplierId: SUPPLIER.whirlpool,
    rfqId: null, quotationId: null, comparisonId: null,
    date: "2026-09-05", expected: "2026-09-19", godownId: GODOWN.main, status: "approved",
    paymentTerms: "45 Days", deliveryTerms: "FOR Indore",
    lines: [{ sku: "SKU035", qty: 6, price: 15800 }],
  },
  {
    id: PO.sundram120, number: "PO-2026-00120", supplierId: SUPPLIER.sundram,
    rfqId: RFQ.fasteners, quotationId: QUOTE.sundram, comparisonId: null,
    date: "2026-09-03", expected: "2026-09-11", godownId: GODOWN.secondary, status: "closed",
    paymentTerms: "15 Days", deliveryTerms: "FOR Pune",
    lines: [
      { sku: "SKU020", qty: 5000, price: 2.4, discountPct: 5 },
      { sku: "SKU028", qty: 1000, price: 12, discountPct: 5 },
    ],
  },
  {
    id: PO.ahmedabad119, number: "PO-2026-00119", supplierId: SUPPLIER.ahmedabad,
    rfqId: RFQ.electricals, quotationId: QUOTE.ahmedabad, comparisonId: null,
    date: "2026-08-28", expected: "2026-09-08", godownId: GODOWN.main, status: "closed",
    paymentTerms: "21 Days", deliveryTerms: "FOR Indore",
    lines: [
      { sku: "SKU011", qty: 40, price: 1620 },
      { sku: "SKU012", qty: 25, price: 1320 },
      { sku: "SKU013", qty: 150, price: 95 },
      { sku: "SKU031", qty: 200, price: 78 },
    ],
  },
  {
    id: PO.flipkart124, number: "PO-2026-00124", supplierId: SUPPLIER.flipkart,
    rfqId: RFQ.appliances, quotationId: QUOTE.flipkart, comparisonId: COMPARISON.appliances,
    date: "2026-09-12", expected: "2026-09-28", godownId: GODOWN.main, status: "draft",
    paymentTerms: "15 Days", deliveryTerms: "Ex-Bengaluru", freight: 1800,
    lines: [
      { sku: "SKU001", qty: 40, price: 1215 },
      { sku: "SKU002", qty: 20, price: 2860 },
    ],
  },
  {
    // Supplier and place of supply are both Madhya Pradesh, so this PO carries
    // CGST + SGST instead of IGST. Derived, never typed (C14).
    id: PO.malwa125, number: "PO-2026-00125", supplierId: SUPPLIER.malwa,
    rfqId: null, quotationId: null, comparisonId: null,
    date: "2026-09-13", expected: "2026-09-20", godownId: GODOWN.main, status: "approved",
    paymentTerms: "15 Days", deliveryTerms: "Delivered to godown",
    notes: "Local top-up order — collected against a delivery challan.",
    lines: [
      { sku: "SKU010", qty: 10, price: 2150 },
      { sku: "SKU013", qty: 200, price: 95 },
    ],
  },
];

/** Accepted quantity per PO line, sourced from the confirmed GRNs below. */
const RECEIVED: Record<string, number> = {};
/** Returned quantity per PO line, sourced from confirmed purchase returns. */
const RETURNED: Record<string, number> = {};
/** Invoiced quantity per PO line. */
const INVOICED: Record<string, number> = {};

const poLineId = (poId: string, sku: string) => `${poId}_li_${sku.toLowerCase()}`;

export const purchaseOrderItems: PurchaseOrderItem[] = PO_SPECS.flatMap((s) =>
  s.lines.map((l, i) => {
    const totals = computeLine(taxable(l));
    const id = poLineId(s.id, l.sku);
    return {
      id,
      purchaseOrderId: s.id,
      lineNo: i + 1,
      productVariantId: variantId(l.sku),
      quotationItemId:
        s.quotationId
          ? supplierQuotationItems.find(
              (qi) => qi.quotationId === s.quotationId && qi.productVariantId === variantId(l.sku),
            )?.id ?? null
          : null,
      rfqItemId: s.rfqId ? rfqItemId(s.rfqId, l.sku) : null,
      description: NAME[l.sku],
      hsnCode: HSN[l.sku],
      quantity: l.qty,
      uomId: l.uomId ?? UOM.nos,
      conversionFactor: 1,
      unitPrice: l.price,
      discountPct: l.discountPct ?? 0,
      gstRate: GST[l.sku],
      cessRate: 0,
      lineNet: totals.lineNet,
      lineTax: totals.lineTax,
      lineTotal: totals.lineTotal,
      receivedQuantity: 0,
      returnedQuantity: 0,
      invoicedQuantity: 0,
      lineStatus: "open",
      expectedDeliveryDate: s.expected,
    };
  }),
);

export const purchaseOrders: PurchaseOrder[] = PO_SPECS.map((s) => {
  const totals = computeDocumentTotals({
    lines: s.lines.map(taxable),
    freightAmount: s.freight,
    supplierStateCode: SUPPLIER_STATE[s.supplierId],
    placeOfSupplyStateCode: GODOWN_STATE[s.godownId],
  });
  const approved = !["draft", "pending_approval"].includes(s.status);
  const sent = !["draft", "pending_approval", "approved"].includes(s.status);
  return {
    id: s.id,
    poNumber: s.number,
    supplierId: s.supplierId,
    rfqId: s.rfqId,
    quotationId: s.quotationId,
    comparisonId: s.comparisonId,
    poDate: s.date,
    expectedDeliveryDate: s.expected,
    deliveryGodownId: s.godownId,
    paymentTerms: s.paymentTerms,
    deliveryTerms: s.deliveryTerms,
    placeOfSupplyStateCode: GODOWN_STATE[s.godownId],
    isInterState: totals.isInterState,
    currencyCode: "INR",
    subtotal: totals.subtotal,
    discountAmount: totals.discountAmount,
    taxableValue: totals.taxableValue,
    cgstAmount: totals.cgstAmount,
    sgstAmount: totals.sgstAmount,
    igstAmount: totals.igstAmount,
    cessAmount: totals.cessAmount,
    freightAmount: totals.freightAmount,
    otherCharges: totals.otherCharges,
    roundOff: totals.roundOff,
    totalAmount: totals.totalAmount,
    status: s.status,
    approvedBy: approved ? USER.owner : null,
    approvedAt: approved ? `${s.date}T15:20:00+05:30` : null,
    sentAt: sent ? `${s.date}T16:00:00+05:30` : null,
    receivedPct: 0,
    fullyReceivedAt: null,
    notes: s.notes,
    createdAt: `${s.date}T12:00:00+05:30`,
    rowVersion: 1,
  };
});

/* -------------------------------------------------------- Goods Receipts */

type GrnLineSpec = {
  sku: string;
  received: number;
  accepted: number;
  issue: GoodsReceiptItem["issueType"];
  remarks?: string;
  batchNumber?: string;
  manufacturedOn?: string;
  expiresOn?: string;
  rejectionReason?: string;
};

type GrnSpec = {
  id: string;
  number: string;
  date: string;
  poId: string;
  supplierId: string;
  godownId: string;
  status: GoodsReceipt["status"];
  receivedBy: string;
  vehicle: string;
  transporter: string;
  lr: string;
  eway: string;
  challan: string;
  challanDate: string;
  remarks: string;
  lines: GrnLineSpec[];
};

const GRN_SPECS: GrnSpec[] = [
  {
    id: GRN.ahmedabad89, number: "GRN-2026-00089", date: "2026-09-08", poId: PO.ahmedabad119,
    supplierId: SUPPLIER.ahmedabad, godownId: GODOWN.main, status: "received",
    receivedBy: USER.godownMgr, vehicle: "GJ 01 KL 4412", transporter: "Gati KWE",
    lr: "GATI/2026/55210", eway: "381004551190", challan: "AEC/DC/8841", challanDate: "2026-09-06",
    remarks: "Two Havells fans arrived with dented cages — segregated for return.",
    lines: [
      { sku: "SKU011", received: 40, accepted: 38, issue: "damaged", remarks: "2 units dented in transit", rejectionReason: "Transit damage — cage dented" },
      { sku: "SKU012", received: 25, accepted: 25, issue: "none" },
      { sku: "SKU013", received: 150, accepted: 150, issue: "none" },
      { sku: "SKU031", received: 200, accepted: 200, issue: "none" },
    ],
  },
  {
    id: GRN.sundram90, number: "GRN-2026-00090", date: "2026-09-11", poId: PO.sundram120,
    supplierId: SUPPLIER.sundram, godownId: GODOWN.secondary, status: "received",
    receivedBy: USER.godownMgr, vehicle: "TN 09 BX 7781", transporter: "TCI Freight",
    lr: "TCI/2026/11903", eway: "381004551844", challan: "SFL/DC/22910", challanDate: "2026-09-09",
    remarks: "",
    lines: [
      { sku: "SKU020", received: 5000, accepted: 5000, issue: "none" },
      { sku: "SKU028", received: 1000, accepted: 1000, issue: "none" },
    ],
  },
  {
    id: GRN.lg88, number: "GRN-2026-00088", date: "2026-09-15", poId: PO.lg122,
    supplierId: SUPPLIER.lg, godownId: GODOWN.main, status: "received",
    receivedBy: USER.godownMgr, vehicle: "DL 01 CA 9920", transporter: "Safexpress",
    lr: "SFX/2026/77120", eway: "381004552004", challan: "LG/DC/55120", challanDate: "2026-09-13",
    remarks: "Balance 2 units scheduled for the next dispatch.",
    lines: [{ sku: "SKU003", received: 8, accepted: 8, issue: "short", remarks: "2 units short — supplier confirmed balance dispatch" }],
  },
  {
    id: GRN.reliance91, number: "GRN-2026-00091", date: "2026-09-13", poId: PO.reliance123,
    supplierId: SUPPLIER.reliance, godownId: GODOWN.main, status: "draft",
    receivedBy: USER.owner, vehicle: "MH 04 GH 5521", transporter: "VRL Logistics",
    lr: "VRL/2026/88213", eway: "381004552271", challan: "RR/DC/99210", challanDate: "2026-09-12",
    remarks: "",
    lines: [
      { sku: "SKU002", received: 30, accepted: 30, issue: "none" },
      { sku: "SKU003", received: 8, accepted: 8, issue: "short", remarks: "2 units short — supplier confirmed balance dispatch on 18 Sep" },
    ],
  },
];

const grnItemId = (grnId: string, sku: string) => `${grnId}_li_${sku.toLowerCase()}`;

/** A confirmed GRN line posts exactly one inventory transaction with this id. */
export const grnPostingTxnId = (grnItemId: string) => `itxn_${grnItemId}`;

export const goodsReceiptItems: GoodsReceiptItem[] = GRN_SPECS.flatMap((s) => {
  const poLines = purchaseOrderItems.filter((li) => li.purchaseOrderId === s.poId);
  return s.lines.map((l, i) => {
    const poLine = poLines.find((li) => li.productVariantId === variantId(l.sku));
    const id = grnItemId(s.id, l.sku);
    const confirmed = s.status === "received" || s.status === "partially_received";
    if (confirmed && poLine) {
      RECEIVED[poLine.id] = round2((RECEIVED[poLine.id] ?? 0) + l.accepted);
    }
    return {
      id,
      goodsReceiptId: s.id,
      lineNo: i + 1,
      purchaseOrderItemId: poLine?.id ?? null,
      productVariantId: variantId(l.sku),
      batchId: l.batchNumber ? `bat_${id}` : null,
      batchNumber: l.batchNumber,
      manufacturedOn: l.manufacturedOn ?? null,
      expiresOn: l.expiresOn ?? null,
      orderedQuantity: poLine?.quantity ?? l.received,
      previouslyReceivedQuantity: 0,
      receivedQuantity: l.received,
      acceptedQuantity: l.accepted,
      rejectedQuantity: round2(l.received - l.accepted),
      uomId: poLine?.uomId ?? UOM.nos,
      conversionFactor: 1,
      unitPrice: poLine?.unitPrice ?? 0,
      issueType: l.issue,
      expectedVariantId: null,
      rejectionReason: l.rejectionReason,
      remarks: l.remarks ?? "",
      inventoryTransactionId: confirmed ? grnPostingTxnId(id) : null,
    };
  });
});

export const goodsReceipts: GoodsReceipt[] = GRN_SPECS.map((s) => ({
  id: s.id,
  grnNumber: s.number,
  grnDate: s.date,
  supplierId: s.supplierId,
  purchaseOrderId: s.poId,
  godownId: s.godownId,
  receivedByUserId: s.receivedBy,
  vehicleNumber: s.vehicle,
  transporterName: s.transporter,
  lrNumber: s.lr,
  ewayBillNumber: s.eway,
  supplierChallanNumber: s.challan,
  supplierChallanDate: s.challanDate,
  status: s.status,
  confirmedBy: s.status === "received" ? s.receivedBy : null,
  confirmedAt: s.status === "received" ? `${s.date}T17:45:00+05:30` : null,
  cancelledAt: null,
  reversedByGrnId: null,
  reversalOfGrnId: null,
  hasDiscrepancy: s.lines.some((l) => l.issue !== "none"),
  remarks: s.remarks,
  createdAt: `${s.date}T16:30:00+05:30`,
  rowVersion: 1,
}));

/* ------------------------------------------------------ Purchase Returns */

const RETURN_LINES: { sku: string; qty: number; reason: PurchaseReturnItem["reason"]; remarks: string }[] = [
  { sku: "SKU011", qty: 2, reason: "damaged", remarks: "Cage dented in transit — photos shared with supplier" },
];

export const purchaseReturnItems: PurchaseReturnItem[] = RETURN_LINES.map((l, i) => {
  const grnItem = goodsReceiptItems.find(
    (gi) => gi.goodsReceiptId === GRN.ahmedabad89 && gi.productVariantId === variantId(l.sku),
  )!;
  const totals = computeLine({
    quantity: l.qty,
    unitPrice: grnItem.unitPrice,
    gstRate: GST[l.sku],
  });
  const poLineKey = grnItem.purchaseOrderItemId;
  if (poLineKey) RETURNED[poLineKey] = round2((RETURNED[poLineKey] ?? 0) + l.qty);
  return {
    id: `${PURCHASE_RETURN.ahmedabad}_li${i + 1}`,
    returnId: PURCHASE_RETURN.ahmedabad,
    goodsReceiptItemId: grnItem.id,
    productVariantId: variantId(l.sku),
    batchId: null,
    quantity: l.qty,
    uomId: UOM.nos,
    unitPrice: grnItem.unitPrice,
    gstRate: GST[l.sku],
    lineTotal: totals.lineTotal,
    reason: l.reason,
    remarks: l.remarks,
    inventoryTransactionId: `itxn_${PURCHASE_RETURN.ahmedabad}_li${i + 1}`,
  };
});

export const purchaseReturns: PurchaseReturn[] = [
  {
    id: PURCHASE_RETURN.ahmedabad,
    returnNumber: "PR-2026-00007",
    returnDate: "2026-09-10",
    supplierId: SUPPLIER.ahmedabad,
    goodsReceiptId: GRN.ahmedabad89,
    purchaseOrderId: PO.ahmedabad119,
    godownId: GODOWN.main,
    reason: "damaged",
    status: "accepted",
    debitNoteNumber: "DN-2026-00007",
    totalAmount: round2(purchaseReturnItems.reduce((s, i) => s + i.lineTotal, 0)),
    ewayBillNumber: "381004553012",
    remarks: "Supplier acknowledged; credit note expected against the next invoice.",
    confirmedBy: USER.godownMgr,
    confirmedAt: "2026-09-10T12:15:00+05:30",
    createdAt: "2026-09-10T11:40:00+05:30",
  },
];

/* ---------------------------------------------------- Supplier Invoices */

type InvoiceSpec = {
  id: string;
  number: string;
  date: string;
  due: string;
  supplierId: string;
  poId: string;
  grnId: string;
  status: SupplierInvoice["status"];
  paymentStatus: SupplierInvoice["paymentStatus"];
  amountPaid: number;
  eway: string;
  documentId: string | null;
  notes?: string;
  disputeReason?: string;
  /** Quantity and price as the supplier billed them — deliberately not always the PO. */
  lines: { sku: string; qty: number; price: number; discountPct?: number }[];
};

const INVOICE_SPECS: InvoiceSpec[] = [
  {
    id: SUPPLIER_INVOICE.sundram, number: "SFL/INV/4471", date: "2026-09-11", due: "2026-09-26",
    supplierId: SUPPLIER.sundram, poId: PO.sundram120, grnId: GRN.sundram90,
    status: "approved", paymentStatus: "paid", amountPaid: 0, eway: "381004551844",
    documentId: "doc_inv_sfl_4471",
    lines: [
      { sku: "SKU020", qty: 5000, price: 2.4, discountPct: 5 },
      { sku: "SKU028", qty: 1000, price: 12, discountPct: 5 },
    ],
  },
  {
    id: SUPPLIER_INVOICE.ahmedabad, number: "AEC/2026/2210", date: "2026-09-09", due: "2026-09-30",
    supplierId: SUPPLIER.ahmedabad, poId: PO.ahmedabad119, grnId: GRN.ahmedabad89,
    status: "disputed", paymentStatus: "unpaid", amountPaid: 0, eway: "381004551190",
    documentId: "doc_inv_aec_2210",
    disputeReason: "Fan rate billed at ₹1,680 against a PO rate of ₹1,620, and 40 billed against 38 accepted.",
    lines: [
      { sku: "SKU011", qty: 40, price: 1680 },
      { sku: "SKU012", qty: 25, price: 1320 },
      { sku: "SKU013", qty: 150, price: 95 },
      { sku: "SKU031", qty: 200, price: 78 },
    ],
  },
  {
    id: SUPPLIER_INVOICE.lg, number: "LG/INV/90233", date: "2026-09-15", due: "2026-10-30",
    supplierId: SUPPLIER.lg, poId: PO.lg122, grnId: GRN.lg88,
    status: "under_review", paymentStatus: "unpaid", amountPaid: 0, eway: "381004552004",
    documentId: "doc_inv_lg_90233",
    notes: "Billed for the 8 units delivered; balance 2 to be invoiced separately.",
    lines: [{ sku: "SKU003", qty: 8, price: 24000 }],
  },
];

export const supplierInvoiceItems: SupplierInvoiceItem[] = INVOICE_SPECS.flatMap((s) =>
  s.lines.map((l, i) => {
    const totals = computeLine(taxable(l));
    const poLine = purchaseOrderItems.find(
      (li) => li.purchaseOrderId === s.poId && li.productVariantId === variantId(l.sku),
    );
    const grnLine = goodsReceiptItems.find(
      (gi) => gi.goodsReceiptId === s.grnId && gi.productVariantId === variantId(l.sku),
    );
    if (poLine) INVOICED[poLine.id] = round2((INVOICED[poLine.id] ?? 0) + l.qty);
    return {
      id: `${s.id}_li${i + 1}`,
      invoiceId: s.id,
      lineNo: i + 1,
      purchaseOrderItemId: poLine?.id ?? null,
      goodsReceiptItemId: grnLine?.id ?? null,
      productVariantId: variantId(l.sku),
      description: NAME[l.sku],
      hsnCode: HSN[l.sku],
      quantity: l.qty,
      uomId: UOM.nos,
      unitPrice: l.price,
      discountPct: l.discountPct ?? 0,
      gstRate: GST[l.sku],
      cessRate: 0,
      lineNet: totals.lineNet,
      lineTax: totals.lineTax,
      lineTotal: totals.lineTotal,
      poUnitPriceSnapshot: poLine?.unitPrice ?? null,
      grnAcceptedQuantity: grnLine?.acceptedQuantity ?? null,
      priceVariancePct: poLine ? variancePct(poLine.unitPrice, l.price) : null,
      qtyVariance: grnLine ? round2(l.qty - grnLine.acceptedQuantity) : null,
    };
  }),
);

export const supplierInvoices: SupplierInvoice[] = INVOICE_SPECS.map((s) => {
  const po = purchaseOrders.find((p) => p.id === s.poId)!;
  const totals = computeDocumentTotals({
    lines: s.lines.map(taxable),
    supplierStateCode: SUPPLIER_STATE[s.supplierId],
    placeOfSupplyStateCode: po.placeOfSupplyStateCode,
  });
  const items = supplierInvoiceItems.filter((i) => i.invoiceId === s.id);
  const hasVariance = items.some(
    (i) => Math.abs(i.priceVariancePct ?? 0) > 0.5 || Math.abs(i.qtyVariance ?? 0) > 0,
  );
  // What the accepted goods are worth at PO terms — net of the PO's own line
  // discount, so the variance reflects price and quantity, not the discount.
  const grnValue = round2(
    items.reduce((sum, i) => {
      const poLine = purchaseOrderItems.find((li) => li.id === i.purchaseOrderItemId);
      if (!poLine) return sum;
      const netRate = round2(poLine.unitPrice * (1 - poLine.discountPct / 100));
      return sum + (i.grnAcceptedQuantity ?? 0) * netRate;
    }, 0),
  );
  return {
    id: s.id,
    invoiceNumber: s.number,
    invoiceDate: s.date,
    supplierId: s.supplierId,
    purchaseOrderId: s.poId,
    goodsReceiptId: s.grnId,
    supplierGstin: null,
    buyerGstin: "23AACCA1234F1Z5",
    placeOfSupplyStateCode: po.placeOfSupplyStateCode,
    isInterState: totals.isInterState,
    invoiceType: "tax_invoice",
    subtotal: totals.subtotal,
    discountAmount: totals.discountAmount,
    taxableValue: totals.taxableValue,
    cgstAmount: totals.cgstAmount,
    sgstAmount: totals.sgstAmount,
    igstAmount: totals.igstAmount,
    cessAmount: totals.cessAmount,
    freightAmount: totals.freightAmount,
    otherCharges: totals.otherCharges,
    roundOff: totals.roundOff,
    totalAmount: totals.totalAmount,
    tdsAmount: 0,
    ewayBillNumber: s.eway,
    dueDate: s.due,
    amountPaid: s.paymentStatus === "paid" ? totals.totalAmount : s.amountPaid,
    paymentStatus: s.paymentStatus,
    matchStatus: hasVariance ? "variance" : "matched",
    varianceAmount: round2(totals.taxableValue - grnValue),
    documentId: s.documentId,
    aiExtractionResultId: s.documentId ? `aix_${s.id}` : null,
    status: s.status,
    approvedBy: s.status === "approved" ? USER.accountant : null,
    approvedAt: s.status === "approved" ? `${s.date}T18:00:00+05:30` : null,
    disputeReason: s.disputeReason,
    notes: s.notes,
    createdAt: `${s.date}T15:00:00+05:30`,
    rowVersion: 1,
  };
});

/* --------------------------------------------------- Proforma Invoices */

type ProformaSpec = {
  id: string;
  number: string;
  date: string;
  supplierId: string;
  poId: string;
  status: ProformaInvoice["status"];
  advancePct: number | null;
  queryNote?: string;
  documentId: string | null;
  /** Proforma rate as quoted by the supplier — where it differs, a variance exists. */
  lines: { sku: string; qty: number; price: number }[];
};

const PROFORMA_SPECS: ProformaSpec[] = [
  {
    id: PROFORMA.reliance, number: "RR/PI/2026/0413", date: "2026-09-11",
    supplierId: SUPPLIER.reliance, poId: PO.reliance123, status: "under_review", advancePct: 30,
    queryNote: "Refrigerator rate is ₹500 above the PO rate — clarification requested.",
    documentId: "doc_pi_rr_0413",
    lines: [
      { sku: "SKU002", qty: 30, price: 2800 },
      { sku: "SKU003", qty: 10, price: 25000 },
    ],
  },
  {
    id: PROFORMA.lg, number: "LG/PI/2026/1180", date: "2026-09-09",
    supplierId: SUPPLIER.lg, poId: PO.lg122, status: "paid", advancePct: 50,
    documentId: "doc_pi_lg_1180",
    lines: [{ sku: "SKU003", qty: 10, price: 24000 }],
  },
  {
    id: PROFORMA.sundram, number: "SFL/PI/2026/0891", date: "2026-09-04",
    supplierId: SUPPLIER.sundram, poId: PO.sundram120, status: "completed", advancePct: null,
    documentId: null,
    lines: [
      { sku: "SKU020", qty: 5000, price: 2.4 },
      { sku: "SKU028", qty: 1000, price: 12 },
    ],
  },
];

export const proformaInvoiceItems: ProformaInvoiceItem[] = PROFORMA_SPECS.flatMap((s) =>
  s.lines.map((l, i) => {
    const totals = computeLine(taxable(l));
    const poLine = purchaseOrderItems.find(
      (li) => li.purchaseOrderId === s.poId && li.productVariantId === variantId(l.sku),
    );
    return {
      id: `${s.id}_li${i + 1}`,
      proformaId: s.id,
      lineNo: i + 1,
      purchaseOrderItemId: poLine?.id ?? null,
      productVariantId: variantId(l.sku),
      description: NAME[l.sku],
      hsnCode: HSN[l.sku],
      quantity: l.qty,
      uomId: UOM.nos,
      unitPrice: l.price,
      gstRate: GST[l.sku],
      cessRate: 0,
      lineNet: totals.lineNet,
      lineTax: totals.lineTax,
      lineTotal: totals.lineTotal,
      poUnitPriceSnapshot: poLine?.unitPrice ?? null,
      priceVariancePct: poLine ? variancePct(poLine.unitPrice, l.price) : null,
    };
  }),
);

export const proformaInvoices: ProformaInvoice[] = PROFORMA_SPECS.map((s) => {
  const po = purchaseOrders.find((p) => p.id === s.poId)!;
  const totals = computeDocumentTotals({
    lines: s.lines.map(taxable),
    supplierStateCode: SUPPLIER_STATE[s.supplierId],
    placeOfSupplyStateCode: po.placeOfSupplyStateCode,
  });
  return {
    id: s.id,
    proformaNumber: s.number,
    supplierId: s.supplierId,
    purchaseOrderId: s.poId,
    proformaDate: s.date,
    validUntil: null,
    placeOfSupplyStateCode: po.placeOfSupplyStateCode,
    isInterState: totals.isInterState,
    subtotal: totals.subtotal,
    discountAmount: totals.discountAmount,
    taxableValue: totals.taxableValue,
    cgstAmount: totals.cgstAmount,
    sgstAmount: totals.sgstAmount,
    igstAmount: totals.igstAmount,
    cessAmount: totals.cessAmount,
    freightAmount: totals.freightAmount,
    otherCharges: totals.otherCharges,
    roundOff: totals.roundOff,
    totalAmount: totals.totalAmount,
    poTotalSnapshot: po.totalAmount,
    varianceAmount: round2(totals.totalAmount - po.totalAmount),
    advancePercent: s.advancePct,
    advanceAmount: s.advancePct ? round2((totals.totalAmount * s.advancePct) / 100) : null,
    paymentInstructions: "NEFT/RTGS only. Quote the PO number in the remittance narration.",
    bankName: "ICICI Bank",
    bankAccountNo: "000405001234",
    bankIfsc: "ICIC0000004",
    supplierGstinSnapshot: null,
    supplierAddressSnapshot: "",
    documentId: s.documentId,
    aiExtractionResultId: s.documentId ? `aix_${s.id}` : null,
    status: s.status,
    approvedBy: ["approved", "paid", "completed"].includes(s.status) ? USER.owner : null,
    approvedAt: ["approved", "paid", "completed"].includes(s.status) ? `${s.date}T17:00:00+05:30` : null,
    queryRaisedAt: s.queryNote ? `${s.date}T18:20:00+05:30` : null,
    queryNote: s.queryNote,
    createdAt: `${s.date}T14:30:00+05:30`,
  };
});

/* ------------------------- Derive PO line and header receipt progress --- */

for (const line of purchaseOrderItems) {
  line.receivedQuantity = RECEIVED[line.id] ?? 0;
  line.returnedQuantity = RETURNED[line.id] ?? 0;
  line.invoicedQuantity = INVOICED[line.id] ?? 0;
  const net = round2(line.receivedQuantity - line.returnedQuantity);
  line.lineStatus =
    net <= 0 ? "open" : net >= line.quantity ? "received" : "partially_received";
}

/** PO 119 was short-closed after the damaged fans were returned. */
for (const line of purchaseOrderItems) {
  if (line.purchaseOrderId === PO.ahmedabad119 && line.lineStatus === "partially_received") {
    line.lineStatus = "short_closed";
  }
}

for (const po of purchaseOrders) {
  const lines = purchaseOrderItems.filter((li) => li.purchaseOrderId === po.id);
  const ordered = lines.reduce((s, li) => s + li.quantity, 0);
  const received = lines.reduce((s, li) => s + li.receivedQuantity, 0);
  po.receivedPct = ordered ? round2((received / ordered) * 100) : 0;
  po.fullyReceivedAt =
    po.receivedPct >= 100
      ? goodsReceipts.find((g) => g.purchaseOrderId === po.id)?.confirmedAt ?? null
      : null;
}

/* ------------------------------------------------------------ Variances */

export const documentVariances: DocumentVariance[] = [
  {
    id: "var_1",
    varianceType: "price",
    comparisonKind: "proforma_vs_po",
    baseDocType: "purchase_order",
    baseDocId: PO.reliance123,
    baseLineId: poLineId(PO.reliance123, "SKU003"),
    compareDocType: "proforma_invoice",
    compareDocId: PROFORMA.reliance,
    compareLineId: `${PROFORMA.reliance}_li2`,
    productVariantId: variantId("SKU003"),
    label: "LG Refrigerator 260L — unit price",
    baseValue: 24500,
    compareValue: 25000,
    difference: 500,
    differencePct: variancePct(24500, 25000),
    severity: "warning",
    status: "open",
  },
  {
    id: "var_2",
    varianceType: "quantity",
    comparisonKind: "grn_vs_po",
    baseDocType: "purchase_order",
    baseDocId: PO.lg122,
    baseLineId: poLineId(PO.lg122, "SKU003"),
    compareDocType: "goods_receipt",
    compareDocId: GRN.lg88,
    compareLineId: grnItemId(GRN.lg88, "SKU003"),
    productVariantId: variantId("SKU003"),
    label: "LG Refrigerator 260L — short received",
    baseValue: 10,
    compareValue: 8,
    difference: -2,
    differencePct: variancePct(10, 8),
    severity: "warning",
    status: "open",
  },
  {
    id: "var_3",
    varianceType: "price",
    comparisonKind: "invoice_vs_po",
    baseDocType: "purchase_order",
    baseDocId: PO.ahmedabad119,
    baseLineId: poLineId(PO.ahmedabad119, "SKU011"),
    compareDocType: "supplier_invoice",
    compareDocId: SUPPLIER_INVOICE.ahmedabad,
    compareLineId: `${SUPPLIER_INVOICE.ahmedabad}_li1`,
    productVariantId: variantId("SKU011"),
    label: "Havells Ceiling Fan 1200mm — billed above PO rate",
    baseValue: 1620,
    compareValue: 1680,
    difference: 60,
    differencePct: variancePct(1620, 1680),
    severity: "critical",
    status: "disputed",
  },
  {
    id: "var_4",
    varianceType: "quantity",
    comparisonKind: "invoice_vs_grn",
    baseDocType: "goods_receipt",
    baseDocId: GRN.ahmedabad89,
    baseLineId: grnItemId(GRN.ahmedabad89, "SKU011"),
    compareDocType: "supplier_invoice",
    compareDocId: SUPPLIER_INVOICE.ahmedabad,
    compareLineId: `${SUPPLIER_INVOICE.ahmedabad}_li1`,
    productVariantId: variantId("SKU011"),
    label: "Havells Ceiling Fan 1200mm — billed 40 against 38 accepted",
    baseValue: 38,
    compareValue: 40,
    difference: 2,
    differencePct: variancePct(38, 40),
    severity: "critical",
    status: "disputed",
  },
];

/** Exported for the inventory seed, which posts the ledger for these GRNs. */
export const confirmedGrnSpecs = GRN_SPECS.filter((s) => s.status === "received");
