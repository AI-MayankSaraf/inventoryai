/**
 * Supplier invoices and purchase returns.
 *
 * Both talk to the real backend now (`/supplier-invoices`,
 * `/purchase-returns`). Confirming a purchase return posts
 * `PURCHASE_RETURN` transactions server-side, through the same
 * `core/inventory.post_transaction` choke point every other movement goes
 * through — so the stock it removes is the stock every other screen reads,
 * not a parallel copy that drifts.
 *
 * The 3-way match is likewise server-side. It compares the invoice against
 * the PO (price) and the GRN (quantity) and records what it finds in
 * `document_variances`; this file only maps the verdict for display.
 */

import { taxBreakdown } from "@/lib/domain/money";
import { allowedTransitions, purchaseReturnTransitions, supplierInvoiceTransitions } from "@/lib/domain/state-machines";
import { query } from "./list-query";
import type {
  Id,
  ListParams,
  ListResponse,
  Percent,
  PurchaseReturn,
  PurchaseReturnItem,
  Quantity,
  ReturnReason,
  SupplierInvoice,
  SupplierInvoiceItem,
  ThreeWayMatch,
} from "@/types";
import { httpGet, httpPost, reject, validationFailed } from "./client";
import { toVariance, type VarianceOut } from "./variances";

/* ------------------------------------------------ Backend response shapes */

interface InvoiceItemOut {
  id: string;
  line_no: number;
  purchase_order_item_id: string | null;
  goods_receipt_item_id: string | null;
  product_variant_id: string | null;
  sku: string;
  description: string;
  hsn_code: string | null;
  quantity: number;
  uom_id: string;
  uom_code: string;
  unit_price: number;
  discount_pct: number;
  gst_rate: number;
  cess_rate: number;
  line_net: number;
  line_tax: number;
  line_total: number;
  po_unit_price_snapshot: number | null;
  price_variance_pct: number | null;
  qty_variance: number | null;
}

interface InvoiceOut {
  id: string;
  invoice_number: string;
  invoice_date: string;
  supplier_id: string;
  supplier_name: string;
  purchase_order_id: string | null;
  po_number: string | null;
  goods_receipt_id: string | null;
  grn_number: string | null;
  supplier_gstin: string | null;
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
  tds_amount: number;
  due_date: string | null;
  amount_paid: number;
  eway_bill_number: string | null;
  irn: string | null;
  payment_status: SupplierInvoice["paymentStatus"];
  match_status: SupplierInvoice["matchStatus"];
  variance_amount: number | null;
  status: SupplierInvoice["status"];
  approved_by: string | null;
  approved_at: string | null;
  row_version: number;
  items: InvoiceItemOut[];
  item_count: number;
  variances: VarianceOut[];
}

interface ThreeWayMatchOut {
  invoice_id: string;
  match_status: SupplierInvoice["matchStatus"];
  matched_against_po: boolean;
  matched_against_grn: boolean;
  variance_amount: number;
  variances: VarianceOut[];
}

interface ReturnItemOut {
  id: string;
  goods_receipt_item_id: string | null;
  product_variant_id: string;
  sku: string;
  product_name: string;
  batch_id: string | null;
  quantity: number;
  unit_price: number;
  gst_rate: number;
  line_total: number;
  inventory_transaction_id: string | null;
}

interface ReturnOut {
  id: string;
  return_number: string;
  return_date: string;
  supplier_id: string;
  supplier_name: string;
  goods_receipt_id: string | null;
  grn_number: string | null;
  purchase_order_id: string | null;
  godown_id: string;
  godown_name: string;
  reason: string;
  status: PurchaseReturn["status"];
  debit_note_number: string | null;
  eway_bill_number: string | null;
  total_amount: number;
  items: ReturnItemOut[];
  item_count: number;
  stock_posted: boolean;
}

/* ------------------------------------------------------------- Mappers */

function toInvoice(i: InvoiceOut): SupplierInvoice {
  return {
    id: i.id,
    invoiceNumber: i.invoice_number,
    invoiceDate: i.invoice_date,
    supplierId: i.supplier_id,
    purchaseOrderId: i.purchase_order_id,
    goodsReceiptId: i.goods_receipt_id,
    supplierGstin: i.supplier_gstin,
    buyerGstin: null,
    placeOfSupplyStateCode: "",
    isInterState: i.is_inter_state,
    invoiceType: "tax_invoice",
    subtotal: i.subtotal,
    discountAmount: i.discount_amount,
    taxableValue: i.taxable_value,
    cgstAmount: i.cgst_amount,
    sgstAmount: i.sgst_amount,
    igstAmount: i.igst_amount,
    cessAmount: i.cess_amount,
    freightAmount: i.freight_amount,
    otherCharges: i.other_charges,
    roundOff: i.round_off,
    totalAmount: i.total_amount,
    tdsAmount: i.tds_amount,
    ewayBillNumber: i.eway_bill_number ?? "",
    irn: i.irn ?? undefined,
    dueDate: i.due_date,
    amountPaid: i.amount_paid,
    paymentStatus: i.payment_status,
    matchStatus: i.match_status,
    varianceAmount: i.variance_amount ?? 0,
    documentId: null,
    aiExtractionResultId: null,
    status: i.status,
    approvedBy: i.approved_by,
    approvedAt: i.approved_at,
    // `supplier_invoices` has no created_at column; the invoice's own date
    // is the only timestamp there is, and the list sorts by it anyway.
    createdAt: i.invoice_date,
    rowVersion: i.row_version,
  };
}

function toInvoiceItem(invoiceId: Id, i: InvoiceItemOut): SupplierInvoiceItem & {
  sku: string;
  productName: string;
  uomCode: string;
} {
  return {
    id: i.id,
    invoiceId,
    lineNo: i.line_no,
    purchaseOrderItemId: i.purchase_order_item_id,
    goodsReceiptItemId: i.goods_receipt_item_id,
    productVariantId: i.product_variant_id,
    description: i.description,
    hsnCode: i.hsn_code ?? undefined,
    quantity: i.quantity,
    uomId: i.uom_id,
    unitPrice: i.unit_price,
    discountPct: i.discount_pct,
    gstRate: i.gst_rate,
    cessRate: i.cess_rate,
    lineNet: i.line_net,
    lineTax: i.line_tax,
    lineTotal: i.line_total,
    poUnitPriceSnapshot: i.po_unit_price_snapshot,
    priceVariancePct: i.price_variance_pct,
    qtyVariance: i.qty_variance,
    sku: i.sku,
    productName: i.description,
    uomCode: i.uom_code,
  } as SupplierInvoiceItem & { sku: string; productName: string; uomCode: string };
}

function toReturn(r: ReturnOut): PurchaseReturn {
  return {
    id: r.id,
    returnNumber: r.return_number,
    returnDate: r.return_date,
    supplierId: r.supplier_id,
    goodsReceiptId: r.goods_receipt_id ?? "",
    purchaseOrderId: r.purchase_order_id,
    godownId: r.godown_id,
    reason: r.reason as ReturnReason,
    status: r.status,
    debitNoteNumber: r.debit_note_number ?? undefined,
    totalAmount: r.total_amount,
    ewayBillNumber: r.eway_bill_number ?? undefined,
    // `stock_posted` is the honest answer to "did this actually move
    // stock", derived server-side from the lines' own transaction ids.
    confirmedAt: r.stock_posted ? r.return_date : null,
    createdAt: r.return_date,
  } as PurchaseReturn;
}

/* ------------------------------------------------------ Supplier invoices */

export interface SupplierInvoiceListRow extends SupplierInvoice {
  supplierName: string;
  poNumber: string | null;
  grnNumber: string | null;
  itemCount: number;
  isOverdue: boolean;
}

export async function listSupplierInvoices(
  params: ListParams = {},
): Promise<ListResponse<SupplierInvoiceListRow>> {
  const out = await httpGet<InvoiceOut[]>("/supplier-invoices", { limit: 500 });
  const today = new Date().toISOString().slice(0, 10);
  const rows: SupplierInvoiceListRow[] = out.map((i) => ({
    ...toInvoice(i),
    supplierName: i.supplier_name,
    poNumber: i.po_number,
    grnNumber: i.grn_number,
    itemCount: i.item_count,
    isOverdue: !!i.due_date && i.due_date < today && i.payment_status !== "paid",
  }));
  return query(rows as unknown as Record<string, unknown>[], params, {
    searchFields: ["invoiceNumber", "supplierName", "poNumber", "grnNumber"],
    dateField: "invoiceDate",
    facetFields: ["status", "matchStatus", "paymentStatus", "supplierId"],
    defaultSort: "-invoiceDate",
  }) as unknown as ListResponse<SupplierInvoiceListRow>;
}

export interface SupplierInvoiceDetail {
  invoice: SupplierInvoice;
  supplierName: string;
  poNumber: string | null;
  grnNumber: string | null;
  items: (SupplierInvoiceItem & { sku: string; productName: string; uomCode: string })[];
  taxRows: ReturnType<typeof taxBreakdown>;
  match: ThreeWayMatch;
  allowedActions: SupplierInvoice["status"][];
}

export async function getSupplierInvoice(invoiceId: Id): Promise<SupplierInvoiceDetail> {
  const i = await httpGet<InvoiceOut>(`/supplier-invoices/${invoiceId}`);
  const variances = i.variances.map(toVariance);
  return {
    invoice: toInvoice(i),
    supplierName: i.supplier_name,
    poNumber: i.po_number,
    grnNumber: i.grn_number,
    items: i.items.map((line) => toInvoiceItem(i.id, line)),
    taxRows: taxBreakdown(
      i.items.map((line) => ({
        quantity: line.quantity,
        unitPrice: line.unit_price,
        gstRate: line.gst_rate,
        cessRate: line.cess_rate,
      })),
      i.is_inter_state,
    ),
    match: {
      invoiceId: i.id,
      matchStatus: i.match_status,
      summary: {
        // The PO and GRN figures are shown as what the variance rows
        // actually compared against, rather than re-fetched and re-derived
        // here — two places computing "the expected value" is how they end
        // up disagreeing.
        poTotal:
          variances.find((v) => v.varianceType === "total" && v.comparisonKind === "invoice_vs_po")?.baseValue ?? 0,
        grnValue:
          variances.find((v) => v.comparisonKind === "invoice_vs_grn")?.baseValue ?? 0,
        invoiceTotal: i.total_amount,
      },
      variances,
    },
    allowedActions: allowedTransitions(supplierInvoiceTransitions, i.status),
  };
}

export interface SupplierInvoiceInput {
  invoiceNumber: string;
  invoiceDate: string;
  dueDate: string | null;
  supplierId: Id;
  purchaseOrderId: Id | null;
  goodsReceiptId: Id | null;
  invoiceType: SupplierInvoice["invoiceType"];
  ewayBillNumber?: string;
  irn?: string;
  freightAmount?: number;
  otherCharges?: number;
  tdsAmount?: number;
  notes?: string;
  documentId?: Id | null;
  lines: {
    productVariantId: Id | null;
    description?: string;
    purchaseOrderItemId?: Id | null;
    goodsReceiptItemId?: Id | null;
    quantity: Quantity;
    uomId: Id;
    unitPrice: number;
    discountPct?: Percent;
    gstRate: Percent;
  }[];
}

export async function createSupplierInvoice(input: SupplierInvoiceInput): Promise<SupplierInvoice> {
  if (!input.lines.length) {
    validationFailed([{ field: "lines", message: "Add at least one line." }]);
  }
  const out = await httpPost<InvoiceOut>("/supplier-invoices", {
    supplier_id: input.supplierId,
    invoice_number: input.invoiceNumber,
    invoice_date: input.invoiceDate,
    purchase_order_id: input.purchaseOrderId,
    goods_receipt_id: input.goodsReceiptId,
    due_date: input.dueDate,
    eway_bill_number: input.ewayBillNumber,
    irn: input.irn,
    freight_amount: input.freightAmount ?? 0,
    other_charges: input.otherCharges ?? 0,
    tds_amount: input.tdsAmount ?? 0,
    items: input.lines.map((l) => ({
      purchase_order_item_id: l.purchaseOrderItemId ?? null,
      goods_receipt_item_id: l.goodsReceiptItemId ?? null,
      product_variant_id: l.productVariantId,
      description: l.description,
      quantity: l.quantity,
      uom_id: l.uomId,
      unit_price: l.unitPrice,
      discount_pct: l.discountPct ?? 0,
      gst_rate: l.gstRate,
    })),
  });
  return toInvoice(out);
}

export async function runThreeWayMatch(invoiceId: Id): Promise<ThreeWayMatch> {
  const out = await httpPost<ThreeWayMatchOut>(`/supplier-invoices/${invoiceId}/match`);
  const variances = out.variances.map(toVariance);
  return {
    invoiceId: out.invoice_id,
    matchStatus: out.match_status,
    summary: {
      poTotal:
        variances.find((v) => v.varianceType === "total" && v.comparisonKind === "invoice_vs_po")?.baseValue ?? 0,
      grnValue: variances.find((v) => v.comparisonKind === "invoice_vs_grn")?.baseValue ?? 0,
      invoiceTotal:
        variances.find((v) => v.varianceType === "total")?.compareValue ?? 0,
    },
    variances,
  };
}

export async function setInvoiceStatus(
  invoiceId: Id,
  status: SupplierInvoice["status"],
  note?: string,
): Promise<SupplierInvoice> {
  // `approved` and `disputed` have their own endpoints — approval runs the
  // match and variance gates, a dispute records why.
  if (status === "approved") {
    return toInvoice(await httpPost<InvoiceOut>(`/supplier-invoices/${invoiceId}/approve`));
  }
  if (status === "disputed") {
    if (!note?.trim()) reject("Say what is being disputed, so the supplier can be told.", "BR-INV-DISPUTE");
    return toInvoice(
      await httpPost<InvoiceOut>(`/supplier-invoices/${invoiceId}/dispute`, { reason: note }),
    );
  }
  return toInvoice(await httpPost<InvoiceOut>(`/supplier-invoices/${invoiceId}/status`, { status, note }));
}

export async function recordPayment(invoiceId: Id, amount: number): Promise<SupplierInvoice> {
  if (!amount || amount <= 0) {
    validationFailed([{ field: "amount", message: "Enter an amount greater than zero." }]);
  }
  return toInvoice(
    await httpPost<InvoiceOut>(`/supplier-invoices/${invoiceId}/payments`, { amount }),
  );
}

/* ------------------------------------------------------- Purchase returns */

export interface PurchaseReturnListRow extends PurchaseReturn {
  supplierName: string;
  grnNumber: string | null;
  poNumber: string | null;
  itemCount: number;
}

export async function listPurchaseReturns(params: ListParams = {}): Promise<ListResponse<PurchaseReturnListRow>> {
  const out = await httpGet<ReturnOut[]>("/purchase-returns", { limit: 500 });
  const rows: PurchaseReturnListRow[] = out.map((r) => ({
    ...toReturn(r),
    supplierName: r.supplier_name,
    grnNumber: r.grn_number,
    poNumber: null,
    itemCount: r.item_count,
  }));
  return query(rows as unknown as Record<string, unknown>[], params, {
    searchFields: ["returnNumber", "supplierName", "grnNumber", "reason"],
    dateField: "returnDate",
    facetFields: ["status", "reason", "supplierId"],
    defaultSort: "-returnDate",
  }) as unknown as ListResponse<PurchaseReturnListRow>;
}

export interface PurchaseReturnDetail {
  purchaseReturn: PurchaseReturn;
  supplierName: string;
  grnNumber: string | null;
  poNumber: string | null;
  godownName: string;
  items: (PurchaseReturnItem & { sku: string; productName: string; uomCode: string; postedQuantity: Quantity | null })[];
  allowedActions: PurchaseReturn["status"][];
}

export async function getPurchaseReturn(returnId: Id): Promise<PurchaseReturnDetail> {
  const r = await httpGet<ReturnOut>(`/purchase-returns/${returnId}`);
  return {
    purchaseReturn: toReturn(r),
    supplierName: r.supplier_name,
    grnNumber: r.grn_number,
    poNumber: null,
    godownName: r.godown_name,
    items: r.items.map((i) => ({
      id: i.id,
      returnId: r.id,
      goodsReceiptItemId: i.goods_receipt_item_id ?? "",
      productVariantId: i.product_variant_id,
      batchId: i.batch_id,
      quantity: i.quantity,
      uomId: "",
      unitPrice: i.unit_price,
      gstRate: i.gst_rate,
      lineTotal: i.line_total,
      reason: r.reason as ReturnReason,
      inventoryTransactionId: i.inventory_transaction_id,
      sku: i.sku,
      productName: i.product_name,
      uomCode: "",
      // A line that carries a transaction id is one whose stock actually
      // left; the quantity posted is the line's own, negated by the ledger.
      postedQuantity: i.inventory_transaction_id ? -i.quantity : null,
    })) as PurchaseReturnDetail["items"],
    allowedActions: allowedTransitions(purchaseReturnTransitions, r.status),
  };
}

export interface PurchaseReturnInput {
  goodsReceiptId: Id;
  returnDate: string;
  reason: ReturnReason;
  remarks?: string;
  ewayBillNumber?: string;
  lines: {
    goodsReceiptItemId: Id;
    quantity: Quantity;
    reason: ReturnReason;
    remarks?: string;
  }[];
}

interface GrnForReturn {
  id: string;
  supplier_id: string;
  godown_id: string;
  purchase_order_id: string | null;
  items: {
    id: string;
    product_variant_id: string | null;
    batch_id: string | null;
    unit_price: number | null;
    gst_rate: number | null;
  }[];
}

/**
 * Creating a confirmed return removes the goods from stock in the same call —
 * a return that does not move stock is the bug this replaces (I2).
 *
 * The form supplies only the GRN and which of its lines are going back, so
 * the GRN is fetched to fill in the supplier, godown, product and rate the
 * API needs. Those come from the receipt rather than from the form on
 * purpose: they are facts about what arrived, not things a user should be
 * able to retype differently on the way out.
 */
export async function createPurchaseReturn(
  input: PurchaseReturnInput,
  confirmNow = true,
): Promise<PurchaseReturn> {
  if (!input.lines.length) {
    validationFailed([{ field: "lines", message: "Pick at least one line to return." }]);
  }
  const grn = await httpGet<GrnForReturn>(`/procurement/goods-receipts/${input.goodsReceiptId}`);
  const linesById = new Map(grn.items.map((i) => [i.id, i]));

  const items = input.lines.map((l) => {
    const source = linesById.get(l.goodsReceiptItemId);
    if (!source?.product_variant_id) {
      validationFailed([
        { field: "lines", message: "One of the selected receipt lines has no matched product." },
      ]);
    }
    return {
      goods_receipt_item_id: l.goodsReceiptItemId,
      product_variant_id: source!.product_variant_id,
      batch_id: source!.batch_id,
      quantity: l.quantity,
      unit_price: source!.unit_price ?? 0,
      gst_rate: source!.gst_rate ?? 18,
    };
  });

  const created = await httpPost<ReturnOut>("/purchase-returns", {
    supplier_id: grn.supplier_id,
    godown_id: grn.godown_id,
    goods_receipt_id: grn.id,
    purchase_order_id: grn.purchase_order_id,
    return_date: input.returnDate,
    reason: input.reason,
    eway_bill_number: input.ewayBillNumber,
    items,
  });

  if (!confirmNow) return toReturn(created);
  return toReturn(await httpPost<ReturnOut>(`/purchase-returns/${created.id}/confirm`));
}

export async function setPurchaseReturnStatus(
  returnId: Id,
  status: PurchaseReturn["status"],
  note?: string,
): Promise<PurchaseReturn> {
  return toReturn(
    await httpPost<ReturnOut>(`/purchase-returns/${returnId}/status`, { status, note }),
  );
}
