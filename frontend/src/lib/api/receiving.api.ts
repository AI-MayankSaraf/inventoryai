/**
 * Goods receipt.
 *
 * Everything here is real (`/procurement/goods-receipts*`). Confirming does
 * the whole thing server-side in one call — posts inventory, advances the
 * linked PO, records `grn_vs_po` variances, raises the GRN alerts — and
 * returns all of it, which is what the detail screen shows.
 *
 * A confirmed GRN is never edited (BR-GRN-08). A draft can be: `PATCH`
 * replaces its header and lines, guarded by `row_version`. A mistake on a
 * confirmed receipt is corrected by `POST .../reverse`, which posts the
 * offsetting movements against the same receipt (C6) — there is no second
 * "reversing GRN" document, so the detail screen reads who reversed it and
 * why off the receipt itself.
 */

import { round3 } from "@/lib/domain/money";
import { allowedTransitions, goodsReceiptTransitions } from "@/lib/domain/state-machines";
// `query`/`indexById` are pure helpers — no mock *data* is read in this file.
import { indexById, query } from "@/mock/repository";
import type {
  BatchInput,
  DocumentVariance,
  GoodsReceipt,
  GoodsReceiptItem,
  GrnConfirmationResult,
  GrnIssueType,
  Id,
  ListParams,
  ListResponse,
  PoLineStatus,
  PurchaseOrderStatus,
  Quantity,
  ReceiptLine,
} from "@/types";
import { httpGet, httpPatch, httpPost, isApiError, validationFailed } from "./client";
import { toVariance, type VarianceOut } from "./variances";

/* --------------------------------------------------------- Backend shapes */

/** Only what `getReturnableLines` needs off `/purchase-returns`. */
interface ReturnForLines {
  id: string;
  goods_receipt_id: string | null;
  status: string;
  items?: { goods_receipt_item_id: string | null; quantity: number }[];
}

/** The returns panel on the receipt's own screen. */
interface ReturnForGrn {
  id: string;
  return_number: string;
  status: string;
  total_amount: number;
}

/** `/procurement/goods-receipts` — see the wiring brief's GRN section. */
interface GrnItemOut {
  id: string;
  line_no: number;
  purchase_order_item_id: string | null;
  product_variant_id: string;
  batch_id: string | null;
  ordered_quantity: number;
  previously_received_quantity: number;
  received_quantity: number;
  accepted_quantity: number;
  rejected_quantity: number;
  uom_id: string;
  conversion_factor: number;
  unit_price: number;
  issue_type: string;
  expected_variant_id: string | null;
  rejection_reason: string | null;
  remarks: string | null;
  inventory_transaction_id: string | null;
  batch_number: string | null;
  manufactured_on: string | null;
  expires_on: string | null;
  /** What actually reached the ledger — null until the receipt is confirmed. */
  posted_quantity: number | null;
}
interface GrnOut {
  id: string;
  grn_number: string;
  grn_date: string;
  supplier_id: string;
  purchase_order_id: string | null;
  godown_id: string;
  received_by: string;
  vehicle_number: string | null;
  transporter_name: string | null;
  lr_number: string | null;
  eway_bill_number: string | null;
  supplier_challan_number: string | null;
  supplier_challan_date: string | null;
  status: string;
  confirmed_by: string | null;
  confirmed_at: string | null;
  cancelled_at: string | null;
  has_discrepancy: boolean;
  remarks: string | null;
  row_version: number;
  items: GrnItemOut[];
  reversal: GrnReversalOut | null;
}

/** Set once the receipt has been reversed — read off its audit trail. */
interface GrnReversalOut {
  reversed_at: string;
  reversed_by: string | null;
  reversed_by_name: string;
  reason: string | null;
}

/** One ledger row the receipt produced (`.../postings`). */
interface GrnPostingOut {
  inventory_transaction_id: string;
  goods_receipt_item_id: string | null;
  txn_number: string;
  txn_type: string;
  txn_date: string;
  posted_at: string;
  product_variant_id: string;
  sku: string;
  godown_id: string;
  godown_name: string;
  quantity: number;
  uom_id: string;
  balance_now: number | null;
  reverses_txn_id: string | null;
}

/** `POST .../confirm` — 04_API_SPECIFICATION.md §3.18. */
interface GrnConfirmOut {
  goods_receipt: GrnOut;
  inventory_postings: GrnPostingOut[];
  purchase_order: { id: string; po_number: string; received_pct: number; status: string } | null;
  variances: VarianceOut[];
  alerts_raised: string[];
}

/** Real master-data lookups (Assignment A's catalog endpoints), just enough
 * to label GRN lines for display. */
interface VariantLite {
  id: string;
  product_id: string;
  sku: string;
  uom_id: string;
  gst_rate: number | null;
}
interface ProductLite {
  id: string;
  name: string;
  tracking_type: string;
}
interface UomLite {
  id: string;
  code: string;
}
interface GodownLite {
  id: string;
  name: string;
}
interface SupplierLite {
  id: string;
  name: string;
}
interface PoItemLite {
  id: string;
  product_variant_id: string;
  quantity: number;
  uom_id: string;
  unit_price: number;
  gst_rate: number;
  received_quantity: number;
  pending_quantity: number;
  line_status: string;
}
interface PoLite {
  id: string;
  po_number: string;
  received_pct: number;
  status: string;
  items: PoItemLite[];
}
interface UserLite {
  id: string;
  full_name: string;
}

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

function toGoodsReceiptItem(goodsReceiptId: Id, i: GrnItemOut): GoodsReceiptItem & { postedQuantity: Quantity | null } {
  return {
    id: i.id,
    goodsReceiptId,
    lineNo: i.line_no,
    purchaseOrderItemId: i.purchase_order_item_id,
    productVariantId: i.product_variant_id,
    batchId: i.batch_id,
    orderedQuantity: i.ordered_quantity,
    previouslyReceivedQuantity: i.previously_received_quantity,
    receivedQuantity: i.received_quantity,
    acceptedQuantity: i.accepted_quantity,
    rejectedQuantity: i.rejected_quantity,
    uomId: i.uom_id,
    conversionFactor: i.conversion_factor,
    unitPrice: i.unit_price,
    issueType: i.issue_type as GrnIssueType,
    expectedVariantId: i.expected_variant_id,
    rejectionReason: i.rejection_reason ?? undefined,
    remarks: i.remarks ?? "",
    batchNumber: i.batch_number ?? undefined,
    manufacturedOn: i.manufactured_on ?? null,
    expiresOn: i.expires_on ?? null,
    inventoryTransactionId: i.inventory_transaction_id,
    // The real ledger figure, not the accepted quantity re-displayed: if a
    // line posted, this is what posted.
    postedQuantity: i.posted_quantity,
  };
}

function toGoodsReceipt(o: GrnOut): GoodsReceipt {
  return {
    id: o.id,
    grnNumber: o.grn_number,
    grnDate: o.grn_date,
    supplierId: o.supplier_id,
    purchaseOrderId: o.purchase_order_id,
    godownId: o.godown_id,
    receivedByUserId: o.received_by,
    vehicleNumber: o.vehicle_number ?? "",
    transporterName: o.transporter_name ?? "",
    lrNumber: o.lr_number ?? "",
    ewayBillNumber: o.eway_bill_number ?? "",
    supplierChallanNumber: o.supplier_challan_number ?? "",
    supplierChallanDate: o.supplier_challan_date ?? null,
    status: o.status as GoodsReceipt["status"],
    confirmedBy: o.confirmed_by,
    confirmedAt: o.confirmed_at,
    cancelledAt: o.cancelled_at,
    // No backend field for a cancellation reason or for the
    // reversal/reversed-by document link (`GrnOut` doesn't carry either) —
    // known gaps. `getGoodsReceipt` below degrades gracefully: both
    // sections simply show nothing for a real GRN instead of erroring.
    cancellationReason: undefined,
    reversedByGrnId: undefined,
    reversalOfGrnId: undefined,
    hasDiscrepancy: o.has_discrepancy,
    remarks: o.remarks ?? "",
    createdAt: "",
    rowVersion: o.row_version,
  };
}

/* ----------------------------------------------------------------- Lists */

export interface GoodsReceiptListRow extends GoodsReceipt {
  supplierName: string;
  godownName: string;
  poNumber: string | null;
  itemCount: number;
  acceptedTotal: Quantity;
}

export async function listGoodsReceipts(params: ListParams = {}): Promise<ListResponse<GoodsReceiptListRow>> {
  // No free-text search/sort on the backend (rule 7) — fetch a generously
  // large page and let `query()` do the rest client-side.
  const [grnsOut, orders, suppliers, godowns] = await Promise.all([
    httpGet<GrnOut[]>("/procurement/goods-receipts", { limit: 500 }),
    httpGet<{ id: string; po_number: string }[]>("/procurement/purchase-orders", { limit: 500 }),
    httpGet<SupplierLite[]>("/catalog/suppliers", { limit: 500 }),
    httpGet<GodownLite[]>("/catalog/godowns", { limit: 500 }),
  ]);
  const ordersById = indexById(orders);
  const suppliersById = indexById(suppliers);
  const godownsById = indexById(godowns);
  const rows: GoodsReceiptListRow[] = grnsOut.map((g) => {
    const grn = toGoodsReceipt(g);
    return {
      ...grn,
      supplierName: suppliersById.get(g.supplier_id)?.name ?? "",
      godownName: godownsById.get(g.godown_id)?.name ?? "",
      poNumber: g.purchase_order_id ? ordersById.get(g.purchase_order_id)?.po_number ?? null : null,
      itemCount: g.items.length,
      acceptedTotal: round3(g.items.reduce((s, i) => s + i.accepted_quantity, 0)),
    };
  });
  return query(rows as unknown as Record<string, unknown>[], params, {
    searchFields: ["grnNumber", "supplierName", "poNumber", "vehicleNumber", "lrNumber", "supplierChallanNumber"],
    dateField: "grnDate",
    facetFields: ["status", "godownId", "supplierId"],
    defaultSort: "-grnDate",
  }) as unknown as ListResponse<GoodsReceiptListRow>;
}

export interface GoodsReceiptDetail {
  goodsReceipt: GoodsReceipt;
  supplierName: string;
  godownName: string;
  poNumber: string | null;
  receivedByName: string;
  items: (GoodsReceiptItem & {
    sku: string;
    productName: string;
    uomCode: string;
    /** Set once the line has posted — links the GRN row to the ledger row. */
    postedQuantity: Quantity | null;
  })[];
  variances: DocumentVariance[];
  returns: { id: Id; returnNumber: string; status: string; totalAmount: number }[];
  /** Every ledger row this receipt produced, reversals included. */
  postings: GrnPosting[];
  /** Set once the receipt has been reversed — it is corrected in place. */
  reversal: { reversedAt: string; reversedByName: string; reason: string | null } | null;
  allowedActions: GoodsReceipt["status"][];
}

export interface GrnPosting {
  inventoryTransactionId: Id;
  goodsReceiptItemId: Id | null;
  txnNumber: string;
  txnType: string;
  postedAt: string;
  productVariantId: Id;
  sku: string;
  godownId: Id;
  godownName: string;
  quantity: Quantity;
  balanceNow: Quantity | null;
  /** Set on the offsetting rows a reversal posts. */
  reversesTxnId: Id | null;
}

function toPosting(p: GrnPostingOut): GrnPosting {
  return {
    inventoryTransactionId: p.inventory_transaction_id,
    goodsReceiptItemId: p.goods_receipt_item_id,
    txnNumber: p.txn_number,
    txnType: p.txn_type,
    postedAt: p.posted_at,
    productVariantId: p.product_variant_id,
    sku: p.sku,
    godownId: p.godown_id,
    godownName: p.godown_name,
    quantity: Number(p.quantity),
    balanceNow: p.balance_now === null ? null : Number(p.balance_now),
    reversesTxnId: p.reverses_txn_id,
  };
}

/** A panel that a role may not be allowed to see must not fail the page:
 * returns need `return.view`, postings need `inventory.view`. */
async function optional<T>(load: () => Promise<T>, fallback: T): Promise<T> {
  try {
    return await load();
  } catch (error) {
    if (isApiError(error) && (error.status === 403 || error.status === 404)) return fallback;
    throw error;
  }
}

export async function getGoodsReceipt(goodsReceiptId: Id): Promise<GoodsReceiptDetail> {
  // `httpGet` throws a 404 `ApiError` on a missing id automatically.
  const o = await httpGet<GrnOut>(`/procurement/goods-receipts/${goodsReceiptId}`);
  const [maps, users, poNumber, variances, returns, postings] = await Promise.all([
    fetchMasterMaps(),
    // No `GET /users/{id}` — fetch the list and find by id (rule 7's pattern).
    httpGet<UserLite[]>("/users", { limit: 500 }).catch(() => [] as UserLite[]),
    o.purchase_order_id
      ? httpGet<{ po_number: string }>(`/procurement/purchase-orders/${o.purchase_order_id}`)
          .then((po) => po.po_number)
          .catch(() => null)
      : Promise.resolve(null),
    optional(
      () => httpGet<VarianceOut[]>(`/procurement/goods-receipts/${goodsReceiptId}/variances`),
      [] as VarianceOut[],
    ),
    optional(
      () => httpGet<ReturnForGrn[]>("/purchase-returns", { goods_receipt_id: goodsReceiptId, limit: 100 }),
      [] as ReturnForGrn[],
    ),
    optional(
      () => httpGet<GrnPostingOut[]>(`/procurement/goods-receipts/${goodsReceiptId}/postings`),
      [] as GrnPostingOut[],
    ),
  ]);
  const grn = toGoodsReceipt(o);

  return {
    goodsReceipt: grn,
    supplierName: maps.suppliersById.get(o.supplier_id)?.name ?? "",
    godownName: maps.godownsById.get(o.godown_id)?.name ?? "",
    poNumber,
    receivedByName: users.find((u) => u.id === o.received_by)?.full_name ?? "",
    items: o.items.map((i) => {
      const variant = maps.variantsById.get(i.product_variant_id);
      return {
        ...toGoodsReceiptItem(goodsReceiptId, i),
        sku: variant?.sku ?? "",
        productName: variant ? maps.productsById.get(variant.product_id)?.name ?? "" : "",
        uomCode: maps.uomsById.get(i.uom_id)?.code ?? "",
      };
    }),
    variances: variances.map(toVariance),
    returns: returns.map((r) => ({
      id: r.id,
      returnNumber: r.return_number,
      status: r.status,
      totalAmount: r.total_amount,
    })),
    postings: postings.map(toPosting),
    reversal: o.reversal
      ? {
          reversedAt: o.reversal.reversed_at,
          reversedByName: o.reversal.reversed_by_name,
          reason: o.reversal.reason,
        }
      : null,
    allowedActions: allowedTransitions(goodsReceiptTransitions, grn.status),
  };
}

/**
 * The lines a receiving screen should show for a PO: **pending balance**, not
 * the original ordered quantity. Receiving 8 of 10 twice must not be possible
 * (C10, BR-GRN-03).
 */
export async function getReceiptLines(purchaseOrderId: Id): Promise<ReceiptLine[]> {
  // `httpGet` throws a 404 `ApiError` on a missing id automatically.
  const po = await httpGet<PoLite>(`/procurement/purchase-orders/${purchaseOrderId}`);
  const maps = await fetchMasterMaps();

  return po.items
    .filter((li) => li.line_status !== "cancelled")
    .map((li) => {
      const variant = maps.variantsById.get(li.product_variant_id);
      const product = variant ? maps.productsById.get(variant.product_id) : undefined;
      // The backend already computes the pending balance — use it directly.
      const pending = li.pending_quantity;
      return {
        purchaseOrderItemId: li.id,
        productVariantId: li.product_variant_id,
        sku: variant?.sku ?? "",
        productName: product?.name ?? "",
        uomId: li.uom_id,
        uomCode: maps.uomsById.get(li.uom_id)?.code ?? "",
        unitPrice: li.unit_price,
        gstRate: li.gst_rate,
        orderedQuantity: li.quantity,
        previouslyReceivedQuantity: li.received_quantity,
        pendingQuantity: Math.max(0, pending),
        suggestedReceivedQuantity: Math.max(0, pending),
        requiresBatch: (product?.tracking_type ?? "none") !== "none",
        lineStatus: li.line_status as PoLineStatus,
      };
    });
}

/* -------------------------------------------------------------- Commands */

export interface GrnLineInput {
  purchaseOrderItemId: Id | null;
  productVariantId: Id;
  receivedQuantity: Quantity;
  acceptedQuantity: Quantity;
  uomId: Id;
  issueType: GrnIssueType;
  rejectionReason?: string;
  remarks?: string;
  batch?: BatchInput | null;
  /** Only for wrong_product / wrong_variant — what was expected instead. */
  expectedVariantId?: Id | null;
}

export interface GrnInput {
  supplierId: Id;
  purchaseOrderId: Id | null;
  godownId: Id;
  grnDate: string;
  vehicleNumber?: string;
  transporterName?: string;
  lrNumber?: string;
  ewayBillNumber?: string;
  supplierChallanNumber?: string;
  supplierChallanDate?: string | null;
  remarks?: string;
  lines: GrnLineInput[];
}

/** Everything the client-side checks need that only the server knows:
 * the excess-receipt policy, the PO's *current* pending balances, and which
 * variants are batch-tracked. Fetched once per submit — the backend
 * enforces all three itself, this is only to answer before the round trip. */
async function validationContext(input: GrnInput) {
  const [settings, po, variants, products] = await Promise.all([
    httpGet<{ allow_grn_excess_receipt: boolean; grn_excess_tolerance_pct: number; inventory_locked_through: string | null }>(
      "/company/settings",
    ).catch(() => null),
    input.purchaseOrderId
      ? httpGet<PoLite>(`/procurement/purchase-orders/${input.purchaseOrderId}`).catch(() => null)
      : Promise.resolve(null),
    httpGet<VariantLite[]>("/catalog/variants", { limit: 500 }).catch(() => [] as VariantLite[]),
    httpGet<ProductLite[]>("/catalog/products", { limit: 500 }).catch(() => [] as ProductLite[]),
  ]);
  const productsById = indexById(products);
  return {
    allowExcess: settings?.allow_grn_excess_receipt ?? false,
    tolerancePct: settings?.grn_excess_tolerance_pct ?? 0,
    lockedThrough: settings?.inventory_locked_through ?? null,
    poLines: new Map((po?.items ?? []).map((li) => [li.id, li])),
    variantsById: indexById(variants),
    productsById,
  };
}

async function validateGrn(input: GrnInput): Promise<void> {
  const errors: { field: string; message: string }[] = [];
  if (!input.supplierId) errors.push({ field: "supplierId", message: "Choose the supplier." });
  if (!input.godownId) errors.push({ field: "godownId", message: "Choose the receiving godown." });
  if (!input.lines.length) errors.push({ field: "lines", message: "Add at least one line." });

  const ctx = await validationContext(input);
  const { allowExcess, tolerancePct } = ctx;

  // BR-INV-10, from the tenant's real settings rather than a stale copy.
  if (ctx.lockedThrough && input.grnDate.slice(0, 10) <= ctx.lockedThrough) {
    errors.push({
      field: "grnDate",
      message: `The inventory period is closed up to ${ctx.lockedThrough}. Date this receipt later, or reopen the period in Settings.`,
    });
  }

  input.lines.forEach((line, i) => {
    if (line.receivedQuantity < 0) {
      errors.push({ field: `lines.${i}.receivedQuantity`, message: "Received quantity cannot be negative." });
    }
    if (line.acceptedQuantity < 0 || line.acceptedQuantity > line.receivedQuantity) {
      errors.push({
        field: `lines.${i}.acceptedQuantity`,
        message: "Accepted quantity must be between zero and the received quantity.",
      });
    }
    if (line.acceptedQuantity < line.receivedQuantity && !line.rejectionReason?.trim()) {
      errors.push({ field: `lines.${i}.rejectionReason`, message: "Say why the balance was rejected." });
    }
    // The PO's pending balance as the server sees it *now*, which is the
    // point of re-reading it: a draft saved yesterday may be looking at a
    // line someone else has since received against (BR-GRN-02).
    const poLine = line.purchaseOrderItemId ? ctx.poLines.get(line.purchaseOrderItemId) : undefined;
    if (poLine) {
      const pending = round3(poLine.pending_quantity);
      const ceiling = round3(pending * (1 + tolerancePct / 100));
      if (line.receivedQuantity > ceiling && !allowExcess) {
        errors.push({
          field: `lines.${i}.receivedQuantity`,
          message: `Only ${pending} pending on this PO line. Enable excess receipt in Settings to accept more.`,
        });
      }
    }
    const variant = ctx.variantsById.get(line.productVariantId);
    const product = variant ? ctx.productsById.get(variant.product_id) : undefined;
    if (product && product.tracking_type !== "none" && line.acceptedQuantity > 0 && !line.batch?.batchNumber) {
      errors.push({
        field: `lines.${i}.batch`,
        message: `${variant?.sku} is batch-tracked — enter the batch number.`,
      });
    }
    if (line.batch?.expiresOn && line.batch.manufacturedOn && line.batch.expiresOn < line.batch.manufacturedOn) {
      errors.push({ field: `lines.${i}.batch`, message: "Expiry cannot be before the manufacturing date." });
    }
    if (
      (line.issueType === "wrong_product" || line.issueType === "wrong_variant") &&
      line.acceptedQuantity > 0
    ) {
      errors.push({
        field: `lines.${i}.acceptedQuantity`,
        message: "A wrong product cannot be accepted into stock. Set accepted to zero and raise a return.",
      });
    }
  });
  if (errors.length) validationFailed(errors);
}

function grnBody(input: GrnInput) {
  return {
    supplier_id: input.supplierId,
    purchase_order_id: input.purchaseOrderId ?? undefined,
    godown_id: input.godownId,
    grn_date: input.grnDate,
    vehicle_number: input.vehicleNumber,
    transporter_name: input.transporterName,
    lr_number: input.lrNumber,
    eway_bill_number: input.ewayBillNumber,
    supplier_challan_number: input.supplierChallanNumber,
    supplier_challan_date: input.supplierChallanDate ?? undefined,
    remarks: input.remarks,
    items: input.lines.map((line) => ({
      purchase_order_item_id: line.purchaseOrderItemId ?? undefined,
      product_variant_id: line.productVariantId,
      batch_number: line.batch?.batchNumber,
      manufactured_on: line.batch?.manufacturedOn ?? undefined,
      expires_on: line.batch?.expiresOn ?? undefined,
      received_quantity: line.receivedQuantity,
      accepted_quantity: line.acceptedQuantity,
      uom_id: line.uomId,
      issue_type: line.issueType,
      expected_variant_id: line.expectedVariantId ?? undefined,
      rejection_reason: line.rejectionReason,
      remarks: line.remarks,
    })),
  };
}

export async function createGoodsReceipt(input: GrnInput, confirmNow = false): Promise<GoodsReceipt> {
  // The period check now lives inside `validateGrn`, which reads the
  // tenant's real settings rather than a stale local copy (BR-INV-10).
  await validateGrn(input);

  const created = await httpPost<GrnOut>("/procurement/goods-receipts", grnBody(input));
  if (confirmNow) {
    const result = await confirmGoodsReceipt(created.id);
    return result.goodsReceipt;
  }
  return toGoodsReceipt(created);
}

/**
 * Edit a draft receipt — header and the whole set of lines.
 *
 * `rowVersion` is the optimistic-lock token the server checks: pass the
 * version the form was loaded with, and a draft someone else changed in the
 * meantime comes back as `409 STALE_RECORD` rather than silently
 * overwriting their edit. A confirmed receipt is refused (BR-GRN-08).
 */
export async function updateDraftGoodsReceipt(
  goodsReceiptId: Id,
  input: GrnInput,
  rowVersion: number,
): Promise<GoodsReceipt> {
  await validateGrn(input);
  const body = grnBody(input);
  const out = await httpPatch<GrnOut>(`/procurement/goods-receipts/${goodsReceiptId}`, {
    // Supplier and PO are fixed at creation, so they are not sent.
    grn_date: body.grn_date,
    godown_id: body.godown_id,
    vehicle_number: body.vehicle_number,
    transporter_name: body.transporter_name,
    lr_number: body.lr_number,
    eway_bill_number: body.eway_bill_number,
    supplier_challan_number: body.supplier_challan_number,
    supplier_challan_date: body.supplier_challan_date,
    remarks: body.remarks,
    items: body.items,
    row_version: rowVersion,
  });
  return toGoodsReceipt(out);
}

/**
 * Confirm a draft GRN. One server-side call posts the inventory, advances
 * the linked PO, records the `grn_vs_po` variances and raises the GRN
 * alerts — and returns all four, which is what the screen then shows.
 */
export async function confirmGoodsReceipt(goodsReceiptId: Id): Promise<GrnConfirmationResult> {
  const out = await httpPost<GrnConfirmOut>(`/procurement/goods-receipts/${goodsReceiptId}/confirm`);

  return {
    goodsReceipt: toGoodsReceipt(out.goods_receipt),
    postings: out.inventory_postings.map((p) => ({
      goodsReceiptItemId: p.goods_receipt_item_id ?? "",
      inventoryTransactionId: p.inventory_transaction_id,
      productVariantId: p.product_variant_id,
      sku: p.sku,
      godownId: p.godown_id,
      quantity: Number(p.quantity),
      balanceAfter: Number(p.balance_now ?? 0),
    })),
    purchaseOrder: out.purchase_order
      ? {
          id: out.purchase_order.id,
          poNumber: out.purchase_order.po_number,
          receivedPct: out.purchase_order.received_pct,
          status: out.purchase_order.status as PurchaseOrderStatus,
        }
      : null,
    variances: out.variances.map(toVariance),
    alertIds: out.alerts_raised,
  };
}

/**
 * Reverse a confirmed GRN. The backend posts the opposite movements against
 * this same receipt and rolls the linked PO's progress back (C6) — there is
 * no second document to navigate to.
 */
export async function reverseGoodsReceipt(goodsReceiptId: Id, reason: string): Promise<GoodsReceipt> {
  const out = await httpPost<GrnOut>(`/procurement/goods-receipts/${goodsReceiptId}/reverse`, { reason });
  return toGoodsReceipt(out);
}

export async function cancelDraftGoodsReceipt(goodsReceiptId: Id, reason: string): Promise<void> {
  // `reason` has no backend field on this action (cancel takes no body) —
  // kept only for the caller's confirmation dialog, not persisted server
  // side. Known gap.
  void reason;
  await httpPost(`/procurement/goods-receipts/${goodsReceiptId}/cancel`);
}

export const GRN_ISSUE_LABELS: Record<GrnIssueType, string> = {
  none: "No issue",
  short: "Short received",
  excess: "Excess received",
  damaged: "Damaged",
  expired: "Expired / near expiry",
  wrong_product: "Wrong product",
  wrong_variant: "Wrong variant",
  wrong_model: "Wrong model",
  wrong_brand: "Wrong brand",
};

/**
 * Lines eligible to be returned to the supplier.
 *
 * Computed here from two real sources — the GRN itself and every return
 * already raised against it — because no single endpoint answers "what is
 * still returnable". Both halves matter: returning against a receipt twice
 * is the mistake this guard exists to prevent, and the backend refuses it
 * with `RETURN_EXCEEDS_RECEIPT` anyway, so the form should not be offering
 * a quantity that will be rejected on submit.
 *
 */
export async function getReturnableLines(goodsReceiptId: Id) {
  const [grn, returns] = await Promise.all([
    httpGet<GrnOut>(`/procurement/goods-receipts/${goodsReceiptId}`),
    // Server-side filter now, instead of pulling every return and sieving.
    httpGet<ReturnForLines[]>("/purchase-returns", { goods_receipt_id: goodsReceiptId, limit: 100 }),
  ]);

  // The list endpoint does not hydrate line items, so each return that
  // concerns this receipt is fetched in full — usually none or one. Reading
  // the list alone (as this used to) meant nothing was ever subtracted, and
  // the form offered a quantity the backend then refuses with
  // `RETURN_EXCEEDS_RECEIPT`.
  const details = await Promise.all(
    returns
      .filter((r) => r.status !== "cancelled")
      .map((r) => httpGet<ReturnForLines>(`/purchase-returns/${r.id}`)),
  );

  const returnedByLine = new Map<string, number>();
  for (const ret of details) {
    for (const item of ret.items ?? []) {
      if (!item.goods_receipt_item_id) continue;
      returnedByLine.set(
        item.goods_receipt_item_id,
        (returnedByLine.get(item.goods_receipt_item_id) ?? 0) + item.quantity,
      );
    }
  }

  const maps = await fetchMasterMaps();
  return grn.items
    .map((line) => {
      const returned = returnedByLine.get(line.id) ?? 0;
      const variant = maps.variantsById.get(line.product_variant_id);
      const productName = variant ? maps.productsById.get(variant.product_id)?.name : undefined;
      const returnable = round3(
        Math.max(line.rejected_quantity, 0) + line.accepted_quantity - returned,
      );
      return {
        goodsReceiptItemId: line.id,
        productVariantId: line.product_variant_id,
        sku: variant?.sku ?? "",
        productName: productName ?? variant?.sku ?? "",
        batchId: line.batch_id,
        uomId: line.uom_id,
        uomCode: maps.uomsById.get(line.uom_id)?.code ?? "",
        unitPrice: line.unit_price,
        gstRate: variant?.gst_rate ?? 0,
        receivedQuantity: line.received_quantity,
        rejectedQuantity: line.rejected_quantity,
        alreadyReturned: returned,
        returnableQuantity: Math.max(0, returnable),
        issueType: line.issue_type as GrnIssueType,
        // Default to what was rejected: that is the quantity a buyer
        // almost always means to send back, and it is never more than the
        // returnable figure above.
        suggestedQuantity: Math.max(0, round3(line.rejected_quantity - returned)),
      };
    })
    .filter((l) => l.returnableQuantity > 0);
}
