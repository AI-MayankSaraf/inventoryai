"use client";

/**
 * Feature hooks for inventory.
 *
 * Note what is not here: there is no hook that sets a stock level. Stock moves
 * only by posting a transaction or a transfer.
 */

import { inventoryApi } from "@/lib/api";
import type { Id, ListParams, TransferResult } from "@/types";
import { useApiMutation, useApiQuery } from "./use-api";

export function useStock(params: ListParams) {
  return useApiQuery(["stock", params], () => inventoryApi.listStock(params));
}

export function useInventoryKpis(godownId?: Id) {
  return useApiQuery(["inventory-kpis", godownId], () => inventoryApi.getInventoryKpis(godownId));
}

export function useLowStock(params: ListParams) {
  return useApiQuery(["low-stock", params], () => inventoryApi.listLowStock(params));
}

export function useTransactions(params: ListParams) {
  return useApiQuery(["transactions", params], () => inventoryApi.listTransactions(params));
}

export function useVariantLedger(productVariantId: Id | undefined, godownId?: Id) {
  return useApiQuery(
    ["variant-ledger", productVariantId, godownId],
    () => inventoryApi.getVariantLedger(productVariantId!, godownId),
    { enabled: !!productVariantId },
  );
}

export function useStockByGodown(productVariantId: Id | undefined) {
  return useApiQuery(
    ["stock-by-godown", productVariantId],
    () => inventoryApi.getStockByGodown(productVariantId!),
    { enabled: !!productVariantId },
  );
}

export function useBatchesFor(productVariantId: Id | undefined, godownId?: Id) {
  return useApiQuery(
    ["batches-for", productVariantId, godownId],
    () => inventoryApi.listBatchesFor(productVariantId!, godownId),
    { enabled: !!productVariantId },
  );
}

export function useTransfers(params: ListParams) {
  return useApiQuery(["transfers", params], () => inventoryApi.listTransfers(params));
}

export function useBalanceCheck() {
  return useApiQuery(["balance-check"], () => inventoryApi.verifyBalances());
}

export function useCreateTransaction(onSuccess?: () => void) {
  return useApiMutation(inventoryApi.createTransaction, { onSuccess });
}

export function useCreateTransfer(onSuccess?: (result: TransferResult) => void) {
  return useApiMutation(inventoryApi.createTransfer, { onSuccess });
}
