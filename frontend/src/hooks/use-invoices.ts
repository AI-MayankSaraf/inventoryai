"use client";

/** Feature hooks for supplier invoices and purchase returns. */

import { useCallback } from "react";
import { invoicesApi } from "@/lib/api";
import type { Id, ListParams } from "@/types";
import { useApiMutation, useApiQuery } from "./use-api";

export function useSupplierInvoices(params: ListParams) {
  return useApiQuery(["supplier-invoices", params], () => invoicesApi.listSupplierInvoices(params));
}

export function useSupplierInvoice(invoiceId: Id | undefined) {
  return useApiQuery(
    ["supplier-invoice", invoiceId],
    () => invoicesApi.getSupplierInvoice(invoiceId!),
    { enabled: !!invoiceId },
  );
}

export function useCreateSupplierInvoice(onSuccess?: (invoice: { id: Id; invoiceNumber: string }) => void) {
  return useApiMutation(invoicesApi.createSupplierInvoice, { onSuccess });
}

export function useRunThreeWayMatch(onSuccess?: () => void) {
  return useApiMutation(invoicesApi.runThreeWayMatch, { onSuccess });
}

export function useSetInvoiceStatus(onSuccess?: () => void) {
  const action = useCallback(
    (input: { invoiceId: Id; status: Parameters<typeof invoicesApi.setInvoiceStatus>[1]; reason?: string }) =>
      invoicesApi.setInvoiceStatus(input.invoiceId, input.status, input.reason),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

export function useRecordPayment(onSuccess?: () => void) {
  const action = useCallback(
    (input: { invoiceId: Id; amount: number }) => invoicesApi.recordPayment(input.invoiceId, input.amount),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

export function usePurchaseReturns(params: ListParams) {
  return useApiQuery(["purchase-returns", params], () => invoicesApi.listPurchaseReturns(params));
}

export function usePurchaseReturn(returnId: Id | undefined) {
  return useApiQuery(
    ["purchase-return", returnId],
    () => invoicesApi.getPurchaseReturn(returnId!),
    { enabled: !!returnId },
  );
}

export function useCreatePurchaseReturn(onSuccess?: (ret: { id: Id; returnNumber: string }) => void) {
  const action = useCallback(
    (input: { data: invoicesApi.PurchaseReturnInput; confirmNow?: boolean }) =>
      invoicesApi.createPurchaseReturn(input.data, input.confirmNow),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

export function useSetPurchaseReturnStatus(onSuccess?: () => void) {
  const action = useCallback(
    (input: {
      returnId: Id;
      status: Parameters<typeof invoicesApi.setPurchaseReturnStatus>[1];
      debitNoteNumber?: string;
    }) => invoicesApi.setPurchaseReturnStatus(input.returnId, input.status, input.debitNoteNumber),
    [],
  );
  return useApiMutation(action, { onSuccess });
}
