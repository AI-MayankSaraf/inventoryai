/**
 * Inventory is transaction-based. `InventoryTransaction` is the only thing
 * that changes stock; `StockBalance` is a derived cache the backend maintains
 * in the same transaction as the ledger write (BR-INV-01, BR-INV-02).
 *
 * Nothing in the UI may write a balance directly.
 */

import type { DateOnly, Id, Money, Quantity, Timestamp } from "./common";

export type InventoryTxnType =
  | "OPENING_STOCK"
  | "GOODS_RECEIPT"
  | "PURCHASE_RETURN"
  | "TRANSFER_IN"
  | "TRANSFER_OUT"
  | "SALES_ISSUE"
  | "SALES_RETURN"
  | "DAMAGE"
  | "EXPIRY_WRITE_OFF"
  | "STOCK_CORRECTION";

/** Which business document caused the movement. */
export type InventorySourceType =
  | "goods_receipt"
  | "purchase_return"
  | "stock_transfer"
  | "adjustment"
  | "sales_issue"
  | "opening";

export interface InventoryTransaction {
  id: Id;
  txnNumber: string;
  txnType: InventoryTxnType;
  txnDate: Timestamp;
  productVariantId: Id;
  godownId: Id;
  batchId: Id | null;
  /** Signed, always in the variant's base UoM. The server applies the sign. */
  quantity: Quantity;
  uomId: Id;
  /** What the user actually typed, before conversion. */
  enteredQuantity?: Quantity;
  enteredUomId?: Id;
  conversionFactor?: number;
  unitCost?: Money;
  sourceType?: InventorySourceType;
  sourceId?: Id;
  sourceLineId?: Id;
  /** TRANSFER_OUT ↔ TRANSFER_IN. */
  counterpartTxnId?: Id | null;
  /** Set on a correcting entry; the ledger is append-only (BR-INV-03). */
  reversesTxnId?: Id | null;
  reasonCode?: string;
  remarks?: string;
  performedBy: Id;
  performedByName: string;
  postedAt: Timestamp;
}

/** Derived cache of `SUM(quantity)` per variant × godown × batch. */
export interface StockBalance {
  id: Id;
  productVariantId: Id;
  godownId: Id;
  batchId: Id | null;
  quantity: Quantity;
  /**
   * Always 0 until Sales Orders exist — nothing in this product can create a
   * reservation, so the UI must not imply otherwise (I6).
   */
  reservedQuantity: Quantity;
  lastTxnAt?: Timestamp;
}

export type StockState = "in_stock" | "low_stock" | "out_of_stock";

/** A row of the Current Stock grid, assembled by the inventory service. */
export interface StockRow {
  id: Id;
  productId: Id;
  productVariantId: Id;
  sku: string;
  productName: string;
  brandName: string;
  categoryName: string;
  godownId: Id;
  godownName: string;
  quantity: Quantity;
  reservedQuantity: Quantity;
  uomCode: string;
  status: StockState;
  /** quantity × variant.purchasePrice — standard costing for Phase 1. */
  value: Money;
}

export interface InventoryKpis {
  totalSkus: number;
  inventoryValue: Money;
  lowStock: number;
  outOfStock: number;
}

export interface LowStockRow {
  id: Id;
  productVariantId: Id;
  sku: string;
  productName: string;
  brandName: string;
  godownId: Id;
  godownName: string;
  currentStock: Quantity;
  reorderPoint: Quantity;
  suggestedQty: Quantity;
  uomCode: string;
  preferredSupplierId: Id | null;
  preferredSupplierName: string;
  lastPurchasePrice: Money;
  status: Extract<StockState, "low_stock" | "out_of_stock">;
}

export interface Batch {
  id: Id;
  productVariantId: Id;
  batchNumber: string;
  supplierBatchNumber?: string;
  manufacturedOn?: DateOnly | null;
  expiresOn?: DateOnly | null;
  mrp?: Money;
  receivedOn?: DateOnly;
  goodsReceiptItemId?: Id;
  isQuarantined: boolean;
}

/* ------------------------------------------------------- Stock transfer */

export type StockTransferStatus = "draft" | "in_transit" | "received" | "cancelled";

export interface StockTransfer {
  id: Id;
  transferNumber: string;
  transferDate: DateOnly;
  fromGodownId: Id;
  toGodownId: Id;
  status: StockTransferStatus;
  dispatchedBy?: Id;
  receivedBy?: Id;
  vehicleNumber?: string;
  lrNumber?: string;
  ewayBillNumber?: string;
  remarks?: string;
  createdAt: Timestamp;
}

export interface StockTransferItem {
  id: Id;
  transferId: Id;
  productVariantId: Id;
  batchId: Id | null;
  quantity: Quantity;
  uomId: Id;
}

/* --------------------------------------------------- Service payloads */

export interface CreateTransactionInput {
  txnType: Extract<InventoryTxnType, "DAMAGE" | "SALES_ISSUE" | "STOCK_CORRECTION" | "EXPIRY_WRITE_OFF">;
  productVariantId: Id;
  godownId: Id;
  batchId?: Id | null;
  /** Unsigned magnitude — the service applies the sign from `txnType`. */
  quantity: Quantity;
  uomId: Id;
  /** Only meaningful for STOCK_CORRECTION. */
  direction?: "increase" | "decrease";
  txnDate?: Timestamp;
  reference?: string;
  reasonCode?: string;
  /** Required for DAMAGE and STOCK_CORRECTION (BR-INV-07). */
  remarks?: string;
}

export interface CreateTransferInput {
  fromGodownId: Id;
  toGodownId: Id;
  transferDate?: DateOnly;
  productVariantId: Id;
  batchId?: Id | null;
  quantity: Quantity;
  uomId: Id;
  vehicleNumber?: string;
  lrNumber?: string;
  ewayBillNumber?: string;
  remarks?: string;
}

export interface TransferResult {
  transfer: StockTransfer;
  transactions: InventoryTransaction[];
}
