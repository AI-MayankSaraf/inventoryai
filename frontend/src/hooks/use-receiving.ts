"use client";

/** Feature hooks for goods receipt. */

import { useCallback } from "react";
import { receivingApi } from "@/lib/api";
import type { GrnConfirmationResult, Id, ListParams } from "@/types";
import { useApiMutation, useApiQuery } from "./use-api";

export function useGoodsReceipts(params: ListParams) {
  return useApiQuery(["goods-receipts", params], () => receivingApi.listGoodsReceipts(params));
}

export function useGoodsReceipt(goodsReceiptId: Id | undefined) {
  return useApiQuery(
    ["goods-receipt", goodsReceiptId],
    () => receivingApi.getGoodsReceipt(goodsReceiptId!),
    { enabled: !!goodsReceiptId },
  );
}

/** Pending balances for a PO — what a receiving screen must show, not ordered qty. */
export function useReceiptLines(purchaseOrderId: Id | undefined) {
  return useApiQuery(
    ["receipt-lines", purchaseOrderId],
    () => receivingApi.getReceiptLines(purchaseOrderId!),
    { enabled: !!purchaseOrderId },
  );
}

export function useReturnableLines(goodsReceiptId: Id | undefined) {
  return useApiQuery(
    ["returnable-lines", goodsReceiptId],
    () => receivingApi.getReturnableLines(goodsReceiptId!),
    { enabled: !!goodsReceiptId },
  );
}

export function useCreateGoodsReceipt(onSuccess?: (grn: { id: Id; grnNumber: string }) => void) {
  const action = useCallback(
    (input: { data: receivingApi.GrnInput; confirmNow?: boolean }) =>
      receivingApi.createGoodsReceipt(input.data, input.confirmNow),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

/** Save a draft receipt's edits. `rowVersion` is the version the form was
 * loaded with — the server refuses a stale one rather than overwriting
 * someone else's edit. */
export function useUpdateDraftGoodsReceipt(
  goodsReceiptId: Id,
  rowVersion: number,
  onSuccess?: (grn: { id: Id; grnNumber: string }) => void,
) {
  const action = useCallback(
    (data: receivingApi.GrnInput) => receivingApi.updateDraftGoodsReceipt(goodsReceiptId, data, rowVersion),
    [goodsReceiptId, rowVersion],
  );
  return useApiMutation(action, { onSuccess });
}

export function useConfirmGoodsReceipt(onSuccess?: (result: GrnConfirmationResult) => void) {
  return useApiMutation(receivingApi.confirmGoodsReceipt, { onSuccess });
}

export function useReverseGoodsReceipt(onSuccess?: () => void) {
  const action = useCallback(
    (input: { goodsReceiptId: Id; reason: string }) =>
      receivingApi.reverseGoodsReceipt(input.goodsReceiptId, input.reason),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

export function useCancelDraftGoodsReceipt(onSuccess?: () => void) {
  const action = useCallback(
    (input: { goodsReceiptId: Id; reason: string }) =>
      receivingApi.cancelDraftGoodsReceipt(input.goodsReceiptId, input.reason),
    [],
  );
  return useApiMutation(action, { onSuccess });
}
