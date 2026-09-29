/**
 * Inventory.
 *
 * The rule this module exists to enforce: **stock is only ever changed by
 * posting an inventory transaction.** There is no `setStock`, no way to edit a
 * balance, and no path by which a screen can write a quantity. That rule now
 * lives where it belongs — in the backend's `core/inventory.py`, inside one
 * database transaction (BR-INV-01, BR-INV-02, C2).
 *
 * The ledger is append-only. A mistake is corrected by posting a compensating
 * row that points at what it reverses — never by editing or deleting history
 * (BR-INV-03).
 *
 * Every screen-facing function below calls the real `/inventory/*` API, and
 * **nothing in this app writes to the mock ledger any more.** The mock
 * writer that used to live here went when purchase returns and opening
 * stock started posting server-side — those were its last two callers.
 *
 * Nothing here reads mock data either. The two helpers that used to —
 * `assertPeriodOpen` and `reorderPointFor` — are gone: the period lock now
 * comes from `/company/settings` where the receipt form needs it, and
 * per-godown reorder levels are served by
 * `/catalog/variants/{id}/godown-policies`.
 */

import { round2, round3 } from "@/lib/domain/money";
// `query` is the shared client-side list filter/sort helper — it reads
// nothing from the mock repository.
import { query } from "@/mock/repository";
import type {
  Batch,
  CreateTransactionInput,
  CreateTransferInput,
  Id,
  InventoryKpis,
  InventoryTransaction,
  ListParams,
  ListResponse,
  LowStockRow,
  Quantity,
  StockRow,
  StockState,
  StockTransfer,
  TransferResult,
} from "@/types";
import { httpGet, httpPost, reject } from "./client";

/* ------------------------------------------------------------- Internals */

/** Sign convention: what a transaction type does to a balance. */
const OUTWARD: InventoryTransaction["txnType"][] = [
  "PURCHASE_RETURN",
  "TRANSFER_OUT",
  "SALES_ISSUE",
  "DAMAGE",
  "EXPIRY_WRITE_OFF",
];

export function signedQuantity(
  txnType: InventoryTransaction["txnType"],
  magnitude: Quantity,
  direction?: "increase" | "decrease",
): Quantity {
  const size = Math.abs(magnitude);
  if (txnType === "STOCK_CORRECTION") return direction === "decrease" ? -size : size;
  return OUTWARD.includes(txnType) ? -size : size;
}

/* ------------------------------------------------ Backend response shapes */

/** `/inventory/stock` — mirrors `app/modules/inventory/schemas.py` exactly. */
interface StockRowOut {
  id: string;
  product_id: string;
  product_variant_id: string;
  sku: string;
  product_name: string;
  brand_name: string;
  category_name: string;
  godown_id: string;
  godown_name: string;
  quantity: number;
  reserved_quantity: number;
  available_quantity: number;
  uom_code: string;
  status: StockState;
  value: number;
}

interface InventoryKpisOut {
  total_skus: number;
  inventory_value: number;
  low_stock: number;
  out_of_stock: number;
}

interface StockListOut {
  items: StockRowOut[];
  kpis: InventoryKpisOut;
  total: number;
}

interface LowStockRowOut {
  id: string;
  product_variant_id: string;
  sku: string;
  product_name: string;
  brand_name: string;
  godown_id: string;
  godown_name: string;
  current_stock: number;
  reorder_point: number;
  suggested_qty: number;
  uom_code: string;
  preferred_supplier_id: string | null;
  preferred_supplier_name: string;
  last_purchase_price: number;
  status: "low_stock" | "out_of_stock";
}

interface TransactionOut {
  id: string;
  txn_number: string;
  txn_type: InventoryTransaction["txnType"];
  txn_date: string;
  product_variant_id: string;
  sku: string;
  product_name: string;
  godown_id: string;
  godown_name: string;
  batch_id: string | null;
  batch_number: string | null;
  quantity: number;
  uom_id: string;
  uom_code: string;
  entered_quantity: number | null;
  entered_uom_id: string | null;
  conversion_factor: number | null;
  unit_cost: number | null;
  source_type: InventoryTransaction["sourceType"] | null;
  source_id: string | null;
  source_line_id: string | null;
  counterpart_txn_id: string | null;
  reverses_txn_id: string | null;
  reason_code: string | null;
  remarks: string | null;
  performed_by: string;
  performed_by_name: string;
  posted_at: string;
  balance_after: number | null;
}

interface BatchOut {
  id: string;
  product_variant_id: string;
  batch_number: string;
  supplier_batch_number: string | null;
  manufactured_on: string | null;
  expires_on: string | null;
  mrp: number | null;
  received_on: string | null;
  is_quarantined: boolean;
  quantity_on_hand: number;
}

interface TransferItemOut {
  id: string;
  product_variant_id: string;
  sku: string;
  product_name: string;
  batch_id: string | null;
  quantity: number;
  uom_id: string;
  dispatched_qty: number | null;
  received_qty: number | null;
}

interface TransferOut {
  id: string;
  transfer_number: string;
  transfer_date: string;
  from_godown_id: string;
  from_godown_name: string;
  to_godown_id: string;
  to_godown_name: string;
  status: StockTransfer["status"];
  dispatched_by: string | null;
  received_by: string | null;
  vehicle_number: string | null;
  lr_number: string | null;
  eway_bill_number: string | null;
  remarks: string | null;
  items: TransferItemOut[];
  transactions: TransactionOut[];
}

interface BalanceDriftOut {
  product_variant_id: string;
  godown_id: string;
  batch_id: string | null;
  balance_quantity: number;
  ledger_quantity: number;
  drift: number;
}

interface VerifyBalancesOut {
  checked: number;
  ok: boolean;
  drifts: BalanceDriftOut[];
}

/* ------------------------------------------------------------- Mappers */

function toStockRow(r: StockRowOut): StockRow {
  return {
    id: r.id,
    productId: r.product_id,
    productVariantId: r.product_variant_id,
    sku: r.sku,
    productName: r.product_name,
    brandName: r.brand_name,
    categoryName: r.category_name,
    godownId: r.godown_id,
    godownName: r.godown_name,
    quantity: r.quantity,
    reservedQuantity: r.reserved_quantity,
    uomCode: r.uom_code,
    status: r.status,
    value: r.value,
  };
}

function toKpis(k: InventoryKpisOut): InventoryKpis {
  return {
    totalSkus: k.total_skus,
    inventoryValue: k.inventory_value,
    lowStock: k.low_stock,
    outOfStock: k.out_of_stock,
  };
}

function toLowStockRow(r: LowStockRowOut): LowStockRow {
  return {
    id: r.id,
    productVariantId: r.product_variant_id,
    sku: r.sku,
    productName: r.product_name,
    brandName: r.brand_name,
    godownId: r.godown_id,
    godownName: r.godown_name,
    currentStock: r.current_stock,
    reorderPoint: r.reorder_point,
    suggestedQty: r.suggested_qty,
    uomCode: r.uom_code,
    preferredSupplierId: r.preferred_supplier_id,
    preferredSupplierName: r.preferred_supplier_name,
    lastPurchasePrice: r.last_purchase_price,
    status: r.status,
  };
}

function toTransaction(t: TransactionOut): InventoryTransaction {
  return {
    id: t.id,
    txnNumber: t.txn_number,
    txnType: t.txn_type,
    txnDate: t.txn_date,
    productVariantId: t.product_variant_id,
    godownId: t.godown_id,
    batchId: t.batch_id,
    quantity: t.quantity,
    uomId: t.uom_id,
    enteredQuantity: t.entered_quantity ?? undefined,
    enteredUomId: t.entered_uom_id ?? undefined,
    conversionFactor: t.conversion_factor ?? undefined,
    unitCost: t.unit_cost ?? undefined,
    sourceType: t.source_type ?? undefined,
    sourceId: t.source_id ?? undefined,
    sourceLineId: t.source_line_id ?? undefined,
    counterpartTxnId: t.counterpart_txn_id,
    reversesTxnId: t.reverses_txn_id,
    reasonCode: t.reason_code ?? undefined,
    remarks: t.remarks ?? undefined,
    performedBy: t.performed_by,
    performedByName: t.performed_by_name,
    postedAt: t.posted_at,
  };
}

function toLedgerRow(t: TransactionOut, balanceAfter: number): LedgerRow {
  return {
    ...toTransaction(t),
    sku: t.sku,
    productName: t.product_name,
    godownName: t.godown_name,
    batchNumber: t.batch_number,
    balanceAfter,
    value: round2(Math.abs(t.quantity) * (t.unit_cost ?? 0)),
  };
}

function toTransfer(t: TransferOut): StockTransfer & { fromGodownName: string; toGodownName: string } {
  return {
    id: t.id,
    transferNumber: t.transfer_number,
    transferDate: t.transfer_date,
    fromGodownId: t.from_godown_id,
    toGodownId: t.to_godown_id,
    status: t.status,
    dispatchedBy: t.dispatched_by ?? undefined,
    receivedBy: t.received_by ?? undefined,
    vehicleNumber: t.vehicle_number ?? undefined,
    lrNumber: t.lr_number ?? undefined,
    ewayBillNumber: t.eway_bill_number ?? undefined,
    remarks: t.remarks ?? undefined,
    // `stock_transfers` has no created_at column, so the transfer's own date
    // is the only timestamp there is. Listing sorts by it anyway.
    createdAt: t.transfer_date,
    fromGodownName: t.from_godown_name,
    toGodownName: t.to_godown_name,
  };
}

/* ---------------------------------------------------------- Stock views */

export async function listStock(params: ListParams = {}): Promise<ListResponse<StockRow>> {
  // The backend filters by godown/category/brand/status/q server-side, but
  // has no free-text sort or cursor paging (rule 7) — so fetch a generous
  // page and let `query()` finish the job client-side, same as every other
  // wired list in this app.
  const out = await httpGet<StockListOut>("/inventory/stock", { limit: 1000 });
  const rows = out.items.map(toStockRow);
  return query(rows as unknown as Record<string, unknown>[], params, {
    searchFields: ["sku", "productName", "brandName", "categoryName", "godownName"],
    facetFields: ["status", "godownId", "categoryName"],
    defaultSort: "productName",
    defaultLimit: 50,
  }) as unknown as ListResponse<StockRow>;
}

export async function getInventoryKpis(godownId?: Id): Promise<InventoryKpis> {
  // Deliberately the same endpoint the grid uses, with the same filter: the
  // KPIs come back computed for that filtered set, so a tile can never
  // disagree with the rows under it (§3.7).
  const out = await httpGet<StockListOut>("/inventory/stock", {
    limit: 1,
    ...(godownId ? { godown_id: godownId } : {}),
  });
  return toKpis(out.kpis);
}

/** Per-godown breakdown for a single variant — the product detail panel. */
export async function getStockByGodown(productVariantId: Id): Promise<StockRow[]> {
  const rows = await httpGet<StockRowOut[]>(`/inventory/stock/by-variant/${productVariantId}`);
  return rows.map(toStockRow);
}

export async function listLowStock(params: ListParams = {}): Promise<ListResponse<LowStockRow>> {
  const rows = (await httpGet<LowStockRowOut[]>("/inventory/low-stock", { limit: 1000 })).map(toLowStockRow);
  return query(rows as unknown as Record<string, unknown>[], params, {
    searchFields: ["sku", "productName", "brandName", "godownName", "preferredSupplierName"],
    facetFields: ["status", "godownId"],
    defaultSort: "currentStock",
    defaultLimit: 50,
  }) as unknown as ListResponse<LowStockRow>;
}

/* --------------------------------------------------------- Ledger views */

export interface LedgerRow extends InventoryTransaction {
  sku: string;
  productName: string;
  godownName: string;
  batchNumber: string | null;
  /** Running balance for this variant × godown after this row. */
  balanceAfter: Quantity;
  value: number;
}

export async function listTransactions(params: ListParams = {}): Promise<ListResponse<LedgerRow>> {
  const out = await httpGet<TransactionOut[]>("/inventory/transactions", { limit: 500 });

  // The backend only computes `balance_after` for the per-variant ledger,
  // where ordering makes it mean something. Here it is derived over the
  // window that was actually fetched, oldest first — which is what the
  // Transactions screen has always shown, and is honest as long as the
  // window covers the variant's whole history. For a definitive running
  // balance on one item, `getVariantLedger` asks the backend instead.
  const oldestFirst = [...out].reverse();
  const running = new Map<string, number>();
  const rows: LedgerRow[] = oldestFirst.map((t) => {
    const key = `${t.product_variant_id}|${t.godown_id}`;
    const balanceAfter = round3((running.get(key) ?? 0) + t.quantity);
    running.set(key, balanceAfter);
    return toLedgerRow(t, balanceAfter);
  });

  return query(rows.reverse() as unknown as Record<string, unknown>[], params, {
    searchFields: ["txnNumber", "sku", "productName", "godownName", "remarks", "performedByName"],
    dateField: "txnDate",
    facetFields: ["txnType", "godownId"],
    defaultSort: "-txnDate",
    defaultLimit: 50,
  }) as unknown as ListResponse<LedgerRow>;
}

/** Every movement for one variant, oldest first, with running balance. */
export async function getVariantLedger(productVariantId: Id, godownId?: Id): Promise<LedgerRow[]> {
  const out = await httpGet<TransactionOut[]>(`/inventory/transactions/ledger/${productVariantId}`, {
    ...(godownId ? { godown_id: godownId } : {}),
  });
  return out.map((t) => toLedgerRow(t, t.balance_after ?? 0));
}

/* ------------------------------------------------------------- Commands */

export async function createTransaction(input: CreateTransactionInput): Promise<InventoryTransaction> {
  const out = await httpPost<TransactionOut>("/inventory/transactions", {
    txn_type: input.txnType,
    product_variant_id: input.productVariantId,
    godown_id: input.godownId,
    batch_id: input.batchId ?? null,
    // Unsigned magnitude — the server applies the sign from txn_type
    // (BR-INV-04). Sending a signed value here would be rejected.
    quantity: Math.abs(input.quantity),
    uom_id: input.uomId,
    direction: input.direction,
    txn_date: input.txnDate,
    reason_code: input.reasonCode,
    remarks: input.remarks,
    reference: input.reference,
  });
  return toTransaction(out);
}

export async function reverseTransaction(txnId: Id, reason: string): Promise<InventoryTransaction> {
  if (!reason?.trim()) {
    reject("Say why this movement is being reversed — it goes on the record.", "BR-INV-03");
  }
  const out = await httpPost<TransactionOut>(`/inventory/transactions/${txnId}/reverse`, {
    reason: reason.trim(),
  });
  return toTransaction(out);
}

export async function createTransfer(input: CreateTransferInput): Promise<TransferResult> {
  const out = await httpPost<TransferOut>("/inventory/transfers", {
    from_godown_id: input.fromGodownId,
    to_godown_id: input.toGodownId,
    transfer_date: input.transferDate,
    vehicle_number: input.vehicleNumber,
    lr_number: input.lrNumber,
    eway_bill_number: input.ewayBillNumber,
    remarks: input.remarks,
    // The form moves one item at a time; the API takes a list, so this is
    // the one-item case of it rather than a different endpoint.
    items: [
      {
        product_variant_id: input.productVariantId,
        batch_id: input.batchId ?? null,
        quantity: input.quantity,
        uom_id: input.uomId,
      },
    ],
  });
  return {
    transfer: toTransfer(out),
    transactions: out.transactions.map(toTransaction),
  };
}

export async function listTransfers(params: ListParams = {}): Promise<ListResponse<StockTransfer>> {
  const rows = (await httpGet<TransferOut[]>("/inventory/transfers", { limit: 500 })).map(toTransfer);
  return query(rows as unknown as Record<string, unknown>[], params, {
    searchFields: ["transferNumber", "vehicleNumber", "lrNumber", "remarks", "fromGodownName", "toGodownName"],
    dateField: "transferDate",
    facetFields: ["status", "fromGodownId", "toGodownId"],
    defaultSort: "-transferDate",
  }) as unknown as ListResponse<StockTransfer>;
}

/* --------------------------------------------------------------- Batches */

export async function listBatchesFor(
  productVariantId: Id,
  godownId?: Id,
): Promise<(Batch & { quantity: Quantity })[]> {
  const rows = await httpGet<BatchOut[]>("/inventory/batches", {
    product_variant_id: productVariantId,
    ...(godownId ? { godown_id: godownId } : {}),
  });
  return rows
    .map((b) => ({
      id: b.id,
      productVariantId: b.product_variant_id,
      batchNumber: b.batch_number,
      supplierBatchNumber: b.supplier_batch_number ?? undefined,
      manufacturedOn: b.manufactured_on,
      expiresOn: b.expires_on,
      mrp: b.mrp ?? undefined,
      receivedOn: b.received_on ?? undefined,
      isQuarantined: b.is_quarantined,
      quantity: b.quantity_on_hand,
    }))
    .filter((b) => b.quantity > 0);
}

/**
 * Integrity check: does every cached balance still agree with the ledger?
 * Surfaced in Settings so drift is visible rather than silently wrong.
 *
 * The backend reports drift and never repairs it from an API call — silently
 * rewriting a balance would hide exactly the bug this is meant to surface
 * (BR-INV-02).
 */
export async function verifyBalances(): Promise<
  { productVariantId: Id; godownId: Id; batchId: Id | null; cached: number; ledger: number }[]
> {
  const out = await httpGet<VerifyBalancesOut>("/inventory/verify-balances");
  return out.drifts.map((d) => ({
    productVariantId: d.product_variant_id,
    godownId: d.godown_id,
    batchId: d.batch_id,
    cached: d.balance_quantity,
    ledger: d.ledger_quantity,
  }));
}
