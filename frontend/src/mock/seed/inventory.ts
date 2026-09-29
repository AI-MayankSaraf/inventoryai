/**
 * Inventory is a ledger, not a number on a product.
 *
 * Nothing in this file states a stock figure. It states the *movements* —
 * opening stock, goods receipts posted by the confirmed GRNs, a purchase
 * return, a transfer, a damage, an expiry write-off and some sales issues —
 * and `stockBalances` is then folded out of them (C2, BR-INV-01).
 *
 * Change a movement and every balance, KPI, low-stock row and valuation in
 * the app moves with it, because they all read the same derived cache.
 */

import { round2, round3 } from "@/lib/domain/money";
import type { Batch, InventoryTransaction, StockBalance, StockTransfer, StockTransferItem } from "@/types";
import { GODOWN, UOM, USER, variantId } from "../ids";
import { productVariants } from "./catalog";
import { confirmedGrnSpecs, goodsReceiptItems, grnPostingTxnId, purchaseReturnItems, purchaseReturns } from "./procurement";

const USER_NAME: Record<string, string> = {
  [USER.owner]: "Sharad",
  [USER.godownMgr]: "Mahesh Pawar",
  [USER.purchaseMgr]: "Anita Deshpande",
  [USER.accountant]: "Rajesh Kulkarni",
  [USER.staff]: "Vikas Sharma",
};

const uomOf = (sku: string) => productVariants.find((v) => v.sku === sku)?.uomId ?? UOM.nos;
const costOf = (sku: string) => productVariants.find((v) => v.sku === sku)?.purchasePrice ?? 0;

/* ------------------------------------------------------------- Batches */

export const batches: Batch[] = [
  {
    id: "bat_atta_0411",
    productVariantId: variantId("SKU004"),
    batchNumber: "ATTA/26/0411",
    supplierBatchNumber: "ITC-0411-26",
    manufacturedOn: "2026-04-11",
    expiresOn: "2027-01-11",
    mrp: 495,
    receivedOn: "2026-04-18",
    isQuarantined: false,
  },
  {
    id: "bat_nam_0722",
    productVariantId: variantId("SKU005"),
    batchNumber: "HLD/26/0722",
    supplierBatchNumber: "HFI-722",
    manufacturedOn: "2026-07-22",
    expiresOn: "2026-11-22",
    mrp: 60,
    receivedOn: "2026-07-30",
    isQuarantined: false,
  },
  {
    id: "bat_nam_0301",
    productVariantId: variantId("SKU005"),
    batchNumber: "HLD/26/0301",
    supplierBatchNumber: "HFI-301",
    manufacturedOn: "2026-03-01",
    expiresOn: "2026-09-01",
    mrp: 60,
    receivedOn: "2026-03-12",
    isQuarantined: true,
  },
];

/* -------------------------------------------------------- Ledger builder */

let seq = 0;
const txns: InventoryTransaction[] = [];

type MoveInput = {
  id?: string;
  type: InventoryTransaction["txnType"];
  date: string;
  sku: string;
  godownId: string;
  /** Signed. Negative for anything leaving the godown. */
  quantity: number;
  batchId?: string | null;
  sourceType?: InventoryTransaction["sourceType"];
  sourceId?: string;
  sourceLineId?: string;
  unitCost?: number;
  reasonCode?: string;
  remarks?: string;
  by?: string;
  counterpartTxnId?: string;
};

function move(m: MoveInput): InventoryTransaction {
  seq += 1;
  const by = m.by ?? USER.godownMgr;
  const txn: InventoryTransaction = {
    id: m.id ?? `itxn_seed_${String(seq).padStart(4, "0")}`,
    txnNumber: `INV-2026-${String(seq).padStart(5, "0")}`,
    txnType: m.type,
    txnDate: m.date,
    productVariantId: variantId(m.sku),
    godownId: m.godownId,
    batchId: m.batchId ?? null,
    quantity: round3(m.quantity),
    uomId: uomOf(m.sku),
    unitCost: m.unitCost ?? costOf(m.sku),
    sourceType: m.sourceType,
    sourceId: m.sourceId,
    sourceLineId: m.sourceLineId,
    counterpartTxnId: m.counterpartTxnId ?? null,
    reversesTxnId: null,
    reasonCode: m.reasonCode,
    remarks: m.remarks,
    performedBy: by,
    performedByName: USER_NAME[by] ?? "System",
    postedAt: m.date,
  };
  txns.push(txn);
  return txn;
}

/* --------------------------------------------------------- Opening stock */

const OPENING_DATE = "2026-04-01T09:00:00+05:30";

const OPENING: { sku: string; godownId: string; qty: number; batchId?: string }[] = [
  { sku: "SKU001", godownId: GODOWN.main, qty: 30 },
  { sku: "SKU002", godownId: GODOWN.main, qty: 30 },
  { sku: "SKU004", godownId: GODOWN.main, qty: 35, batchId: "bat_atta_0411" },
  { sku: "SKU005", godownId: GODOWN.main, qty: 186, batchId: "bat_nam_0722" },
  { sku: "SKU010", godownId: GODOWN.main, qty: 22 },
  { sku: "SKU013", godownId: GODOWN.main, qty: 60 },
  { sku: "SKU031", godownId: GODOWN.main, qty: 100 },
  { sku: "SKU035", godownId: GODOWN.main, qty: 4 },
  { sku: "SKU041", godownId: GODOWN.main, qty: 6 },
  { sku: "SKU001", godownId: GODOWN.secondary, qty: 8 },
  { sku: "SKU005", godownId: GODOWN.secondary, qty: 48, batchId: "bat_nam_0301" },
  { sku: "SKU012", godownId: GODOWN.secondary, qty: 10 },
  { sku: "SKU020", godownId: GODOWN.secondary, qty: 800 },
  { sku: "SKU028", godownId: GODOWN.secondary, qty: 200 },
  { sku: "SKU031", godownId: GODOWN.secondary, qty: 120 },
];

for (const o of OPENING) {
  move({
    type: "OPENING_STOCK",
    date: OPENING_DATE,
    sku: o.sku,
    godownId: o.godownId,
    quantity: o.qty,
    batchId: o.batchId,
    sourceType: "opening",
    remarks: "Opening balance carried forward — FY 2026-27",
    by: USER.owner,
  });
}

/* ------------------------------------------- Sales issues and write-offs */

move({
  type: "SALES_ISSUE", date: "2026-09-02T11:20:00+05:30", sku: "SKU041",
  godownId: GODOWN.main, quantity: -6, sourceType: "sales_issue",
  remarks: "Counter sale — festive offer", by: USER.staff,
});

move({
  type: "EXPIRY_WRITE_OFF", date: "2026-09-03T10:00:00+05:30", sku: "SKU005",
  godownId: GODOWN.secondary, quantity: -48, batchId: "bat_nam_0301",
  sourceType: "adjustment", reasonCode: "EXPIRED",
  remarks: "Batch HLD/26/0301 expired 01 Sep 2026 — written off after physical segregation",
});

move({
  type: "SALES_ISSUE", date: "2026-09-05T15:40:00+05:30", sku: "SKU001",
  godownId: GODOWN.main, quantity: -12, sourceType: "sales_issue",
  remarks: "Counter sale", by: USER.staff,
});

move({
  type: "STOCK_CORRECTION", date: "2026-09-06T18:10:00+05:30", sku: "SKU010",
  godownId: GODOWN.main, quantity: 2, sourceType: "adjustment", reasonCode: "CYCLE_COUNT",
  remarks: "Cycle count found 2 units mis-binned under Prestige — ledger corrected, not overwritten",
  by: USER.godownMgr,
});

move({
  type: "SALES_ISSUE", date: "2026-09-07T12:05:00+05:30", sku: "SKU002",
  godownId: GODOWN.main, quantity: -18, sourceType: "sales_issue",
  remarks: "Institutional order", by: USER.staff,
});

/* ---------------------------------------- Goods receipts (confirmed GRNs) */

for (const grn of confirmedGrnSpecs) {
  const lines = goodsReceiptItems.filter((gi) => gi.goodsReceiptId === grn.id);
  for (const line of lines) {
    const sku = productVariants.find((v) => v.id === line.productVariantId)!.sku;
    move({
      id: grnPostingTxnId(line.id),
      type: "GOODS_RECEIPT",
      date: `${grn.date}T17:45:00+05:30`,
      sku,
      godownId: grn.godownId,
      quantity: line.acceptedQuantity,
      batchId: line.batchId,
      sourceType: "goods_receipt",
      sourceId: grn.id,
      sourceLineId: line.id,
      unitCost: line.unitPrice,
      remarks: line.remarks || `Received against ${grn.number}`,
      by: grn.receivedBy,
    });
  }
}

/* ------------------------------------------------------ Stock transfer */

export const stockTransfers: StockTransfer[] = [
  {
    id: "stf_00003",
    transferNumber: "TRF-2026-00003",
    transferDate: "2026-09-09",
    fromGodownId: GODOWN.main,
    toGodownId: GODOWN.secondary,
    status: "received",
    dispatchedBy: USER.godownMgr,
    receivedBy: USER.staff,
    vehicleNumber: "MP 09 TR 2210",
    lrNumber: "OWN/2026/0031",
    ewayBillNumber: "381004551999",
    remarks: "Switches moved to Pune for a site order.",
    createdAt: "2026-09-09T09:30:00+05:30",
  },
];

export const stockTransferItems: StockTransferItem[] = [
  {
    id: "stf_00003_li1",
    transferId: "stf_00003",
    productVariantId: variantId("SKU013"),
    batchId: null,
    quantity: 20,
    uomId: UOM.nos,
  },
];

for (const item of stockTransferItems) {
  const transfer = stockTransfers.find((t) => t.id === item.transferId)!;
  const sku = productVariants.find((v) => v.id === item.productVariantId)!.sku;
  const out = move({
    type: "TRANSFER_OUT",
    date: `${transfer.transferDate}T10:00:00+05:30`,
    sku,
    godownId: transfer.fromGodownId,
    quantity: -item.quantity,
    sourceType: "stock_transfer",
    sourceId: transfer.id,
    sourceLineId: item.id,
    remarks: transfer.remarks,
  });
  const into = move({
    type: "TRANSFER_IN",
    date: `${transfer.transferDate}T18:00:00+05:30`,
    sku,
    godownId: transfer.toGodownId,
    quantity: item.quantity,
    sourceType: "stock_transfer",
    sourceId: transfer.id,
    sourceLineId: item.id,
    counterpartTxnId: out.id,
    remarks: transfer.remarks,
    by: USER.staff,
  });
  out.counterpartTxnId = into.id;
}

/* ----------------------------------------------------- Purchase return */

for (const item of purchaseReturnItems) {
  const ret = purchaseReturns.find((r) => r.id === item.returnId)!;
  const sku = productVariants.find((v) => v.id === item.productVariantId)!.sku;
  move({
    id: item.inventoryTransactionId ?? undefined,
    type: "PURCHASE_RETURN",
    date: `${ret.returnDate}T12:15:00+05:30`,
    sku,
    godownId: ret.godownId,
    quantity: -item.quantity,
    batchId: item.batchId,
    sourceType: "purchase_return",
    sourceId: ret.id,
    sourceLineId: item.id,
    unitCost: item.unitPrice,
    reasonCode: item.reason.toUpperCase(),
    remarks: item.remarks,
  });
}

/* ------------------------------------------------- Damage, late movements */

move({
  type: "DAMAGE", date: "2026-09-12T16:25:00+05:30", sku: "SKU005",
  godownId: GODOWN.main, quantity: -6, batchId: "bat_nam_0722",
  sourceType: "adjustment", reasonCode: "PACKAGING_DAMAGE",
  remarks: "Six packs punctured while unloading — photographed and scrapped",
});

move({
  type: "SALES_ISSUE", date: "2026-09-11T14:15:00+05:30", sku: "SKU031",
  godownId: GODOWN.main, quantity: -40, sourceType: "sales_issue",
  remarks: "Contractor supply", by: USER.staff,
});

/* ---------------------------------------------------------------- Export */

/** The ledger, oldest first. Append-only: corrections are new rows (BR-INV-03). */
export const inventoryTransactions: InventoryTransaction[] = txns
  .slice()
  .sort((a, b) => a.txnDate.localeCompare(b.txnDate));

/**
 * `StockBalance` is a fold of the ledger, exactly as the backend maintains it.
 * It is never authored, and nothing in the UI may write it (C2).
 */
export function deriveStockBalances(ledger: InventoryTransaction[]): StockBalance[] {
  const byKey = new Map<string, StockBalance>();
  for (const t of ledger) {
    const key = `${t.productVariantId}|${t.godownId}|${t.batchId ?? ""}`;
    const existing = byKey.get(key);
    if (existing) {
      existing.quantity = round3(existing.quantity + t.quantity);
      if (!existing.lastTxnAt || t.txnDate > existing.lastTxnAt) existing.lastTxnAt = t.txnDate;
    } else {
      byKey.set(key, {
        id: `bal_${key.replace(/\|/g, "_").replace(/_$/, "")}`,
        productVariantId: t.productVariantId,
        godownId: t.godownId,
        batchId: t.batchId,
        quantity: round3(t.quantity),
        reservedQuantity: 0,
        lastTxnAt: t.txnDate,
      });
    }
  }
  return [...byKey.values()].sort((a, b) => a.id.localeCompare(b.id));
}

export const stockBalances: StockBalance[] = deriveStockBalances(inventoryTransactions);

/** Sanity guard: the seed must never produce a negative balance. */
export const seededNegativeBalances = stockBalances.filter((b) => round2(b.quantity) < 0);
