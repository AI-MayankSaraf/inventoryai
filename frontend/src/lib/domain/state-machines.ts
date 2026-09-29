/**
 * Per-document state machines.
 *
 * The prototype used one 12-value `DocStatus` union for every document, so an
 * RFQ could be "partially_received" and a GRN could be "expired". Each
 * document now has its own status type and its own transition table, and the
 * table is the only thing that decides which action buttons a screen offers
 * (C7).
 *
 * `06_BUSINESS_RULES.md` is the source of these tables; the backend enforces
 * the same transitions and returns `INVALID_STATE_TRANSITION` when a client
 * asks for one that isn't listed here.
 */

import type {
  GoodsReceiptStatus,
  ProformaStatus,
  PurchaseOrderStatus,
  PurchaseReturnStatus,
  QuotationStatus,
  RfqStatus,
  StockTransferStatus,
  SupplierInvoiceStatus,
  TransitionError,
} from "@/types";

export type TransitionMap<S extends string> = Record<S, S[]>;

export const rfqTransitions: TransitionMap<RfqStatus> = {
  draft: ["sent", "cancelled"],
  sent: ["partially_quoted", "quoted", "closed", "cancelled"],
  partially_quoted: ["quoted", "closed", "cancelled"],
  quoted: ["closed", "cancelled"],
  closed: [],
  cancelled: [],
};

export const quotationTransitions: TransitionMap<QuotationStatus> = {
  draft: ["under_review", "rejected"],
  under_review: ["approved", "rejected", "expired", "superseded"],
  approved: ["converted", "superseded", "expired"],
  rejected: [],
  expired: ["superseded"],
  superseded: [],
  converted: [],
};

export const purchaseOrderTransitions: TransitionMap<PurchaseOrderStatus> = {
  draft: ["pending_approval", "approved", "cancelled"],
  pending_approval: ["approved", "draft", "cancelled"],
  approved: ["sent", "cancelled"],
  sent: ["acknowledged", "partially_received", "received", "cancelled"],
  acknowledged: ["partially_received", "received", "cancelled"],
  partially_received: ["received", "closed", "cancelled"],
  received: ["closed"],
  closed: [],
  cancelled: [],
};

export const proformaTransitions: TransitionMap<ProformaStatus> = {
  pending: ["under_review", "cancelled"],
  under_review: ["approved", "rejected", "cancelled"],
  approved: ["paid", "cancelled"],
  rejected: [],
  paid: ["completed"],
  completed: [],
  cancelled: [],
};

export const goodsReceiptTransitions: TransitionMap<GoodsReceiptStatus> = {
  draft: ["partially_received", "received", "cancelled"],
  partially_received: ["received", "reversed"],
  received: ["reversed"],
  cancelled: [],
  reversed: [],
};

export const supplierInvoiceTransitions: TransitionMap<SupplierInvoiceStatus> = {
  draft: ["under_review", "cancelled"],
  under_review: ["approved", "disputed", "cancelled"],
  approved: ["disputed"],
  disputed: ["under_review", "approved", "cancelled"],
  cancelled: [],
};

export const purchaseReturnTransitions: TransitionMap<PurchaseReturnStatus> = {
  draft: ["sent", "cancelled"],
  sent: ["accepted", "cancelled"],
  accepted: ["credited"],
  credited: [],
  cancelled: [],
};

export const stockTransferTransitions: TransitionMap<StockTransferStatus> = {
  draft: ["in_transit", "cancelled"],
  in_transit: ["received", "cancelled"],
  received: [],
  cancelled: [],
};

/* ----------------------------------------------------------- Evaluation */

export function canTransition<S extends string>(map: TransitionMap<S>, from: S, to: S): boolean {
  return (map[from] ?? []).includes(to);
}

export function allowedTransitions<S extends string>(map: TransitionMap<S>, from: S): S[] {
  return map[from] ?? [];
}

export function isTerminal<S extends string>(map: TransitionMap<S>, status: S): boolean {
  return (map[status] ?? []).length === 0;
}

export function transitionError<S extends string>(
  map: TransitionMap<S>,
  from: S,
  to: S,
): TransitionError {
  return {
    code: "INVALID_STATE_TRANSITION",
    from,
    to,
    allowed: allowedTransitions(map, from) as string[],
  };
}

/* -------------------------------------------------------- Presentation */

export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger";

interface StatusMeta {
  label: string;
  tone: StatusTone;
}

const META: Record<string, StatusMeta> = {
  draft: { label: "Draft", tone: "neutral" },
  pending: { label: "Pending", tone: "warning" },
  pending_approval: { label: "Pending approval", tone: "warning" },
  under_review: { label: "Under review", tone: "warning" },
  approved: { label: "Approved", tone: "success" },
  rejected: { label: "Rejected", tone: "danger" },
  sent: { label: "Sent", tone: "info" },
  acknowledged: { label: "Acknowledged", tone: "info" },
  partially_quoted: { label: "Partially quoted", tone: "info" },
  quoted: { label: "Quoted", tone: "info" },
  partially_received: { label: "Partially received", tone: "warning" },
  received: { label: "Received", tone: "success" },
  closed: { label: "Closed", tone: "neutral" },
  completed: { label: "Completed", tone: "success" },
  cancelled: { label: "Cancelled", tone: "neutral" },
  reversed: { label: "Reversed", tone: "danger" },
  expired: { label: "Expired", tone: "danger" },
  superseded: { label: "Superseded", tone: "neutral" },
  converted: { label: "Converted", tone: "success" },
  paid: { label: "Paid", tone: "success" },
  disputed: { label: "Disputed", tone: "danger" },
  accepted: { label: "Accepted", tone: "success" },
  credited: { label: "Credited", tone: "success" },
  in_transit: { label: "In transit", tone: "info" },
  active: { label: "Active", tone: "success" },
  inactive: { label: "Inactive", tone: "neutral" },
  invited: { label: "Invited", tone: "info" },
  suspended: { label: "Suspended", tone: "danger" },
  in_stock: { label: "In stock", tone: "success" },
  low_stock: { label: "Low stock", tone: "warning" },
  out_of_stock: { label: "Out of stock", tone: "danger" },
  open: { label: "Open", tone: "info" },
  short_closed: { label: "Short closed", tone: "warning" },
  matched: { label: "Matched", tone: "success" },
  variance: { label: "Variance", tone: "danger" },
  unmatched: { label: "Unmatched", tone: "neutral" },
  unpaid: { label: "Unpaid", tone: "warning" },
  partially_paid: { label: "Partially paid", tone: "warning" },
};

export function statusLabel(status: string): string {
  return (
    META[status]?.label ??
    status.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase())
  );
}

export function statusTone(status: string): StatusTone {
  return META[status]?.tone ?? "neutral";
}

/** The transition table for a document type, by name. */
export const TRANSITIONS = {
  rfq: rfqTransitions,
  quotation: quotationTransitions,
  purchase_order: purchaseOrderTransitions,
  proforma: proformaTransitions,
  goods_receipt: goodsReceiptTransitions,
  supplier_invoice: supplierInvoiceTransitions,
  purchase_return: purchaseReturnTransitions,
  stock_transfer: stockTransferTransitions,
} as const;

export type DocumentKind = keyof typeof TRANSITIONS;
