"use client";

/** Feature hooks for suppliers. */

import { useCallback } from "react";
import { suppliersApi } from "@/lib/api";
import type { Id, ListParams, Supplier } from "@/types";
import { useApiMutation, useApiQuery } from "./use-api";

export function useSuppliers(params: ListParams) {
  return useApiQuery(["suppliers", params], () => suppliersApi.listSuppliers(params));
}

export function useSupplier(supplierId: Id | undefined) {
  return useApiQuery(
    ["supplier", supplierId],
    () => suppliersApi.getSupplier(supplierId!),
    { enabled: !!supplierId },
  );
}

export function useSupplierUsage(supplierId: Id | undefined) {
  return useApiQuery(
    ["supplier-usage", supplierId],
    () => suppliersApi.getSupplierUsage(supplierId!),
    { enabled: !!supplierId },
  );
}

export function usePriceHistory(supplierId: Id | undefined, productVariantId: Id | undefined) {
  return useApiQuery(
    ["price-history", supplierId, productVariantId],
    () => suppliersApi.getPriceHistory(supplierId!, productVariantId!),
    { enabled: !!supplierId && !!productVariantId },
  );
}

export function useCreateSupplier(onSuccess?: (supplier: Supplier) => void) {
  return useApiMutation(suppliersApi.createSupplier, { onSuccess });
}

export function useUpdateSupplier(supplierId: Id, onSuccess?: (supplier: Supplier) => void) {
  const action = useCallback(
    (input: suppliersApi.SupplierInput) => suppliersApi.updateSupplier(supplierId, input),
    [supplierId],
  );
  return useApiMutation(action, { onSuccess });
}

export function useDeactivateSupplier(onSuccess?: () => void) {
  const action = useCallback(
    (input: { supplierId: Id; reason?: string }) =>
      suppliersApi.deactivateSupplier(input.supplierId, input.reason),
    [],
  );
  return useApiMutation(action, { onSuccess });
}

/** Add (no `contactId`) or edit a supplier contact. */
export function useSaveContact(supplierId: Id, contactId: Id | undefined, onSuccess?: () => void) {
  const action = useCallback(
    (input: suppliersApi.ContactInput) =>
      contactId ? suppliersApi.updateContact(contactId, input) : suppliersApi.createContact(supplierId, input),
    [supplierId, contactId],
  );
  return useApiMutation(action, { onSuccess: () => onSuccess?.() });
}

export function useDeleteContact(onSuccess?: () => void) {
  return useApiMutation(suppliersApi.deleteContact, { onSuccess: () => onSuccess?.() });
}
