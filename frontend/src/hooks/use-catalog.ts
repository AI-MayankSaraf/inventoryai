"use client";

/** Feature hooks for products and master data. */

import { useCallback } from "react";
import { catalogApi } from "@/lib/api";
import type { Id, ListParams } from "@/types";
import { useApiMutation, useApiQuery } from "./use-api";

export function useProducts(params: ListParams) {
  return useApiQuery(["products", params], () => catalogApi.listProducts(params));
}

export function useProduct(productVariantId: Id | undefined) {
  return useApiQuery(
    ["product", productVariantId],
    () => catalogApi.getProduct(productVariantId!),
    { enabled: !!productVariantId },
  );
}

export function useProductStock(productVariantId: Id | undefined) {
  return useApiQuery(
    ["product-stock", productVariantId],
    () => catalogApi.getVariantStock(productVariantId!),
    { enabled: !!productVariantId },
  );
}

export function useProductUsage(productVariantId: Id | undefined) {
  return useApiQuery(
    ["product-usage", productVariantId],
    () => catalogApi.getProductUsage(productVariantId!),
    { enabled: !!productVariantId },
  );
}

export function useCategories() {
  return useApiQuery(["categories"], () => catalogApi.listCategories());
}

export function useBrands() {
  return useApiQuery(["brands"], () => catalogApi.listBrands());
}

export function useUoms() {
  return useApiQuery(["uoms"], () => catalogApi.listUoms());
}

export function useGodowns() {
  return useApiQuery(["godowns"], () => catalogApi.listGodowns());
}

export function useUomConversions(productVariantId: Id | undefined) {
  return useApiQuery(
    ["uom-conversions", productVariantId],
    () => catalogApi.listUomConversions(productVariantId!),
    { enabled: !!productVariantId },
  );
}

export function useCreateProduct(onSuccess?: (detail: catalogApi.ProductDetail) => void) {
  return useApiMutation(catalogApi.createProduct, { onSuccess });
}

export function useUpdateProduct(
  productVariantId: Id,
  onSuccess?: (detail: catalogApi.ProductDetail) => void,
) {
  const action = useCallback(
    (input: catalogApi.ProductInput) => catalogApi.updateProduct(productVariantId, input),
    [productVariantId],
  );
  return useApiMutation(action, { onSuccess });
}

export function useDeactivateProduct(onSuccess?: () => void) {
  return useApiMutation(catalogApi.deactivateProduct, { onSuccess });
}

export function useAddUomConversion(productVariantId: Id, onSuccess?: () => void) {
  const action = useCallback(
    (input: catalogApi.UomConversionInput) => catalogApi.addUomConversion(productVariantId, input),
    [productVariantId],
  );
  return useApiMutation(action, { onSuccess: () => onSuccess?.() });
}

export function useProductFiles(productVariantId: Id) {
  return useApiQuery(["product-files", productVariantId], () =>
    catalogApi.listProductFiles(productVariantId),
  );
}

export function useUploadProductFile(productVariantId: Id, onSuccess?: () => void) {
  const action = useCallback(
    (file: File) => catalogApi.uploadProductFile(productVariantId, file),
    [productVariantId],
  );
  return useApiMutation(action, { onSuccess: () => onSuccess?.() });
}

export function useRemoveProductFile(onSuccess?: () => void) {
  return useApiMutation(catalogApi.removeProductFile, { onSuccess: () => onSuccess?.() });
}

export function useDeleteUomConversion(onSuccess?: () => void) {
  return useApiMutation(catalogApi.deleteUomConversion, { onSuccess: () => onSuccess?.() });
}

export function useSaveGodownPolicies(productVariantId: Id, onSuccess?: () => void) {
  const action = useCallback(
    (policies: catalogApi.GodownPolicyInput[]) => catalogApi.saveGodownPolicies(productVariantId, policies),
    [productVariantId],
  );
  return useApiMutation(action, { onSuccess: () => onSuccess?.() });
}
