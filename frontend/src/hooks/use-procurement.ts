"use client";

/** Feature hooks for the RFQ → quotation → comparison → PO → proforma chain. */

import { useCallback, useRef, useState } from "react";
import { errorMessage, procurementApi } from "@/lib/api";
import type { Id, ListParams } from "@/types";
import { useApiMutation, useApiQuery } from "./use-api";

/* RFQ */

export function useRfqs(params: ListParams) {
  return useApiQuery(["rfqs", params], () => procurementApi.listRfqs(params));
}

export function useRfq(rfqId: Id | undefined) {
  return useApiQuery(["rfq", rfqId], () => procurementApi.getRfq(rfqId!), { enabled: !!rfqId });
}

export function useCreateRfq(onSuccess?: (rfq: { id: Id; rfqNumber: string }) => void) {
  const action = useCallback(
    (input: { data: procurementApi.RfqInput; sendNow?: boolean }) =>
      procurementApi.createRfq(input.data, input.sendNow),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

export function useSendRfq(onSuccess?: () => void) {
  return useApiMutation(procurementApi.sendRfq, { onSuccess });
}

export function useAddRfqSuppliers(rfqId: Id, onSuccess?: () => void) {
  const action = useCallback(
    (supplierIds: Id[]) => procurementApi.addRfqSuppliers(rfqId, supplierIds),
    [rfqId],
  );
  return useApiMutation(action, { onSuccess: () => onSuccess?.() });
}

export function useRemoveRfqSupplier(rfqId: Id, onSuccess?: () => void) {
  const action = useCallback(
    (supplierId: Id) => procurementApi.removeRfqSupplier(rfqId, supplierId),
    [rfqId],
  );
  return useApiMutation(action, { onSuccess: () => onSuccess?.() });
}

/**
 * The import preview, re-run whenever the file or the mapping changes.
 * Only the latest request's answer is kept: changing two dropdowns quickly
 * must not let the first, slower response overwrite the second.
 */
export function useRfqImportPreview() {
  const [data, setData] = useState<procurementApi.RfqImportPreview | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);
  const seq = useRef(0);

  const run = useCallback(async (file: File, options: procurementApi.RfqImportOptions = {}) => {
    const mine = ++seq.current;
    setIsPending(true);
    setError(null);
    try {
      const result = await procurementApi.previewRfqImport(file, options);
      if (mine === seq.current) setData(result);
      return result;
    } catch (err) {
      if (mine === seq.current) {
        setError(errorMessage(err));
        setData(undefined);
      }
      return undefined;
    } finally {
      if (mine === seq.current) setIsPending(false);
    }
  }, []);

  const reset = useCallback(() => {
    seq.current++;
    setData(undefined);
    setError(null);
    setIsPending(false);
  }, []);

  return { run, reset, data, error, isPending };
}

export function useImportRfq(onSuccess?: (rfq: { id: Id; rfqNumber: string }) => void) {
  const action = useCallback(
    (input: { file: File; data: procurementApi.RfqImportInput }) =>
      procurementApi.importRfq(input.file, input.data),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

/* Quotations */

export function useQuotations(params: ListParams) {
  return useApiQuery(["quotations", params], () => procurementApi.listQuotations(params));
}

export function useQuotation(quotationId: Id | undefined) {
  return useApiQuery(
    ["quotation", quotationId],
    () => procurementApi.getQuotation(quotationId!),
    { enabled: !!quotationId },
  );
}

export function useCreateQuotation(onSuccess?: (quotation: { id: Id }) => void) {
  return useApiMutation(procurementApi.createQuotation, { onSuccess });
}

export function useSetQuotationStatus(onSuccess?: () => void) {
  const action = useCallback(
    (input: { quotationId: Id; status: Parameters<typeof procurementApi.setQuotationStatus>[1]; reason?: string }) =>
      procurementApi.setQuotationStatus(input.quotationId, input.status, input.reason),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

/* Comparison */

export function useComparisonForRfq(rfqId: Id | undefined) {
  return useApiQuery(
    ["comparison-for-rfq", rfqId],
    () => procurementApi.getComparisonForRfq(rfqId!),
    { enabled: !!rfqId },
  );
}

export function useSelectComparisonLine(onSuccess?: () => void) {
  const action = useCallback(
    (input: { comparisonId: Id; rfqItemId: Id; quotationItemId: Id; overrideReason?: string }) =>
      procurementApi.selectComparisonLine(
        input.comparisonId,
        input.rfqItemId,
        input.quotationItemId,
        input.overrideReason,
      ),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

export function useConvertComparison(onSuccess?: (pos: { id: Id; poNumber: string }[]) => void) {
  const action = useCallback(
    (input: { comparisonId: Id; deliveryGodownId: Id }) =>
      procurementApi.convertComparisonToPos(input.comparisonId, input.deliveryGodownId),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

/* Purchase orders */

export function usePurchaseOrders(params: ListParams) {
  return useApiQuery(["purchase-orders", params], () => procurementApi.listPurchaseOrders(params));
}

export function usePurchaseOrder(purchaseOrderId: Id | undefined) {
  return useApiQuery(
    ["purchase-order", purchaseOrderId],
    () => procurementApi.getPurchaseOrder(purchaseOrderId!),
    { enabled: !!purchaseOrderId },
  );
}

export function useCreatePurchaseOrder(onSuccess?: (po: { id: Id; poNumber: string }) => void) {
  return useApiMutation(procurementApi.createPurchaseOrder, { onSuccess });
}

export function useSetPurchaseOrderStatus(onSuccess?: () => void) {
  const action = useCallback(
    (input: {
      purchaseOrderId: Id;
      status: Parameters<typeof procurementApi.updatePurchaseOrderStatus>[1];
      reason?: string;
    }) => procurementApi.updatePurchaseOrderStatus(input.purchaseOrderId, input.status, { reason: input.reason }),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

/* Proforma */

export function useProformas(params: ListParams) {
  return useApiQuery(["proformas", params], () => procurementApi.listProformas(params));
}

export function useProforma(proformaId: Id | undefined) {
  return useApiQuery(
    ["proforma", proformaId],
    () => procurementApi.getProforma(proformaId!),
    { enabled: !!proformaId },
  );
}

export function useSetProformaStatus(onSuccess?: () => void) {
  const action = useCallback(
    (input: { proformaId: Id; status: Parameters<typeof procurementApi.setProformaStatus>[1]; note?: string }) =>
      procurementApi.setProformaStatus(input.proformaId, input.status, input.note),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

export function useRaiseProformaQuery(onSuccess?: () => void) {
  const action = useCallback(
    (input: { proformaId: Id; note: string }) =>
      procurementApi.raiseProformaQuery(input.proformaId, input.note),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

/* Variances */

export function useVariances(params: ListParams) {
  return useApiQuery(["variances", params], () => procurementApi.listVariances(params));
}

export function useResolveVariance(onSuccess?: () => void) {
  const action = useCallback(
    (input: { varianceId: Id; status: "accepted" | "disputed" | "resolved"; note: string }) =>
      procurementApi.resolveVariance(input.varianceId, input.status, input.note),
    [],
  );
  return useApiMutation(action, { onSuccess });
}
