/**
 * Products, variants and the master data behind them.
 *
 * Everything here talks to the real FastAPI backend (`/catalog/*`,
 * `/inventory/*`): products, variants, masters, UoM conversions, per-godown
 * reorder levels, supplier links, stock totals and the in-use check. Search,
 * sort and paging over the fetched lists use `query()` from `./list-query`.
 *
 * The frontend's `ProductInput`/`ProductDetail` treat "product" as one
 * merged form (name + SKU + prices together), but the backend splits that
 * into two resources: `/catalog/products` (the catalogue item) and
 * `/catalog/variants` (the SKU). `createProduct`/`updateProduct` write both;
 * `getProduct` reads both and merges them back into one `ProductDetail`,
 * so screens keep working with one merged product.
 *
 * The correction that still matters: a product form cannot set stock.
 * `currentStock` does not exist on a variant, and there is no field, payload
 * or code path by which creating or editing a product changes a balance.
 * Opening stock is a posted inventory transaction like any other (C2, C3).
 */

import { indexById, query } from "./list-query";
import type {
  Brand,
  Category,
  Godown,
  Id,
  ListParams,
  ListResponse,
  Product,
  ProductUomConversion,
  ProductVariant,
  Quantity,
  StockPolicy,
  Uom,
} from "@/types";
import { httpDelete, httpGet, httpPatch, httpPost, httpPut, validationFailed } from "./client";
import { toLinkedProduct, type SupplierProductOut } from "./suppliers.api";

/* --------------------------------------------------------- Backend shapes */

/** `/catalog/products` — see `04_API_SPECIFICATION.md` / the wiring brief. */
interface ProductOut {
  id: string;
  name: string;
  brand_id: string | null;
  category_id: string | null;
  manufacturer_name: string | null;
  description: string | null;
  hsn_code: string;
  gst_rate: number;
  cess_rate: number;
  tracking_type: string;
  base_uom_id: string;
  is_active: boolean;
}

/** `/catalog/variants` — this is the SKU. */
interface VariantOut {
  id: string;
  product_id: string;
  sku: string;
  variant_name: string | null;
  barcode: string | null;
  hsn_code: string | null;
  gst_rate: number | null;
  uom_id: string;
  pack_size: number | null;
  purchase_price: number;
  sale_price: number;
  mrp: number;
  reorder_point: number;
  reorder_qty: number;
  lead_time_days: number | null;
  attributes: Record<string, string>;
  is_active: boolean;
}

interface CategoryOut {
  id: string;
  name: string;
  code: string | null;
  parent_id: string | null;
  is_active: boolean;
}

interface BrandOut {
  id: string;
  name: string;
  code: string | null;
  manufacturer_name: string | null;
  is_active: boolean;
}

interface UomOut {
  id: string;
  code: string;
  name: string;
  uom_type: string;
  decimal_places: number;
  is_active: boolean;
}

interface GodownOut {
  id: string;
  name: string;
  code: string | null;
  city: string;
  state_code: string;
  address: string | null;
  gstin: string | null;
  is_default: boolean;
  is_active: boolean;
  incharge_user_id?: string | null;
}

/* -------------------------------------------------- snake_case -> camelCase */

// The backend doesn't carry `createdAt`/`updatedAt`/`deletedAt` on these
// master-data reads yet, so they're defaulted below. Nothing in the current
// UI reads those fields for products/variants/categories/brands/godowns, so
// this is a safe simplification rather than a functional gap.

function toProduct(p: ProductOut): Product {
  return {
    id: p.id,
    name: p.name,
    brandId: p.brand_id,
    categoryId: p.category_id,
    manufacturerName: p.manufacturer_name ?? undefined,
    description: p.description ?? undefined,
    hsnCode: p.hsn_code,
    gstRate: p.gst_rate,
    cessRate: p.cess_rate,
    trackingType: p.tracking_type as Product["trackingType"],
    baseUomId: p.base_uom_id,
    isActive: p.is_active,
    deletedAt: null,
    createdAt: "",
    updatedAt: "",
  };
}

function toVariant(v: VariantOut): ProductVariant {
  return {
    id: v.id,
    productId: v.product_id,
    sku: v.sku,
    variantName: v.variant_name ?? undefined,
    barcode: v.barcode ?? undefined,
    hsnCode: v.hsn_code ?? undefined,
    gstRate: v.gst_rate ?? undefined,
    uomId: v.uom_id,
    packSize: v.pack_size ?? undefined,
    purchasePrice: v.purchase_price,
    salePrice: v.sale_price,
    mrp: v.mrp,
    reorderPoint: v.reorder_point,
    reorderQty: v.reorder_qty,
    leadTimeDays: v.lead_time_days ?? undefined,
    // `attributes` is present on VariantOut but not on the create/update body
    // schema — the backend has nowhere to persist it, so this reflects
    // whatever the server returns (often just `{}`) rather than what the
    // form actually submitted. Known gap.
    attributes: v.attributes ?? {},
    isActive: v.is_active,
    deletedAt: null,
    createdAt: "",
    updatedAt: "",
  };
}

/** Fallback for the denormalised breadcrumb the backend doesn't compute. */
function toCategory(c: CategoryOut): Category {
  return {
    id: c.id,
    parentId: c.parent_id,
    name: c.name,
    code: c.code ?? undefined,
    path: c.code || c.name,
    isActive: c.is_active,
    deletedAt: null,
  };
}

function toBrand(b: BrandOut): Brand {
  return {
    id: b.id,
    name: b.name,
    code: b.code ?? undefined,
    manufacturerName: b.manufacturer_name ?? undefined,
    isActive: b.is_active,
    deletedAt: null,
  };
}

function toUom(u: UomOut): Uom {
  return {
    id: u.id,
    code: u.code,
    name: u.name,
    uomType: u.uom_type as Uom["uomType"],
    decimalPlaces: u.decimal_places,
    isActive: u.is_active,
  };
}

function toGodown(g: GodownOut): Godown {
  return {
    id: g.id,
    name: g.name,
    code: g.code ?? undefined,
    city: g.city,
    stateCode: g.state_code,
    address: g.address ?? undefined,
    gstin: g.gstin,
    inchargeUserId: g.incharge_user_id ?? null,
    isDefault: g.is_default,
    isActive: g.is_active,
    deletedAt: null,
    createdAt: "",
    updatedAt: "",
  };
}

/* ---------------------------------------------------------- Read models */

/** A catalogue row as the products grid needs it — stock arrives separately. */
export interface ProductListRow {
  id: Id;
  productId: Id;
  sku: string;
  name: string;
  brandName: string;
  categoryName: string;
  uomCode: string;
  hsnCode: string;
  gstRate: number;
  purchasePrice: number;
  salePrice: number;
  mrp: number;
  reorderPoint: Quantity;
  trackingType: Product["trackingType"];
  displayEmoji?: string;
  isActive: boolean;
  /** Total across every godown, read from the derived balances (never stored). */
  totalStock: Quantity;
}

/** Real on-hand totals per variant, summed across the godowns the user may
 * see (`/inventory/stock` applies the godown scope). A user without
 * `inventory.view` gets a 403 — the grid then shows 0 rather than failing. */
async function fetchStockTotals(): Promise<Map<Id, number>> {
  const totals = new Map<Id, number>();
  try {
    const out = await httpGet<{ items: { product_variant_id: string; quantity: number | string }[] }>(
      "/inventory/stock",
      { limit: 1000 },
    );
    for (const r of out.items) {
      totals.set(r.product_variant_id, (totals.get(r.product_variant_id) ?? 0) + Number(r.quantity));
    }
  } catch {
    /* no stock visibility — totals stay empty */
  }
  return totals;
}

/** Fetches products + variants + the master lookups needed to label them.
 * There's no free-text search on the backend (rule 7 of the wiring brief),
 * so this pulls a generously large page and `query()` below does the
 * search/sort/filter/pagination client-side. */
async function fetchProductListRows(): Promise<ProductListRow[]> {
  const [products, variants, brands, categories, uoms, stockTotals] = await Promise.all([
    httpGet<ProductOut[]>("/catalog/products", { limit: 500 }),
    httpGet<VariantOut[]>("/catalog/variants", { limit: 500 }),
    httpGet<BrandOut[]>("/catalog/brands", { limit: 500 }),
    httpGet<CategoryOut[]>("/catalog/categories", { limit: 500 }),
    // `/catalog/uoms-available` (own + the 9 shared system units), not the
    // tenant-scoped `/catalog/uoms` — see the comment on `listUoms` below.
    httpGet<UomOut[]>("/catalog/uoms-available"),
    fetchStockTotals(),
  ]);
  const productsById = indexById(products);
  const brandsById = indexById(brands);
  const categoriesById = indexById(categories);
  const uomsById = indexById(uoms);

  const stockByVariant = stockTotals;

  return variants.map((variant) => {
    const product = productsById.get(variant.product_id);
    return {
      id: variant.id,
      productId: variant.product_id,
      sku: variant.sku,
      name: product?.name ?? variant.sku,
      brandName: product?.brand_id ? brandsById.get(product.brand_id)?.name ?? "" : "",
      categoryName: product?.category_id ? categoriesById.get(product.category_id)?.name ?? "" : "",
      uomCode: uomsById.get(variant.uom_id)?.code ?? "",
      hsnCode: variant.hsn_code ?? product?.hsn_code ?? "",
      gstRate: variant.gst_rate ?? product?.gst_rate ?? 0,
      purchasePrice: variant.purchase_price,
      salePrice: variant.sale_price,
      mrp: variant.mrp,
      reorderPoint: variant.reorder_point,
      trackingType: (product?.tracking_type ?? "none") as Product["trackingType"],
      // Not stored by the backend; screens show the default icon.
      displayEmoji: undefined,
      isActive: variant.is_active && (product?.is_active ?? true),
      totalStock: stockByVariant.get(variant.id) ?? 0,
    };
  });
}

export async function listProducts(params: ListParams = {}): Promise<ListResponse<ProductListRow>> {
  const rows = await fetchProductListRows();
  return query(rows as unknown as Record<string, unknown>[], params, {
    searchFields: ["sku", "name", "brandName", "categoryName", "hsnCode"],
    facetFields: ["categoryName", "brandName", "trackingType"],
    defaultSort: "name",
    defaultLimit: 50,
  }) as unknown as ListResponse<ProductListRow>;
}

/** `/catalog/variants/{id}/uom-conversions` */
interface ConversionOut {
  id: string;
  product_variant_id: string;
  from_uom_id: string;
  from_code: string;
  to_uom_id: string;
  to_code: string;
  factor: number;
  is_purchase_default: boolean;
}

/** `/catalog/variants/{id}/godown-policies` */
interface GodownPolicyOut {
  id: string;
  product_variant_id: string;
  godown_id: string;
  godown_name: string;
  reorder_point: number;
  reorder_qty: number;
  max_stock: number | null;
  is_stocked: boolean;
}

export type UomConversionRow = ProductUomConversion & { fromCode: string; toCode: string };
export type GodownPolicyRow = StockPolicy & { godownName: string };

function toConversion(c: ConversionOut): UomConversionRow {
  return {
    id: c.id,
    productVariantId: c.product_variant_id,
    fromUomId: c.from_uom_id,
    toUomId: c.to_uom_id,
    factor: Number(c.factor),
    isPurchaseDefault: c.is_purchase_default,
    fromCode: c.from_code,
    toCode: c.to_code,
  };
}

function toPolicy(p: GodownPolicyOut): GodownPolicyRow {
  return {
    id: p.id,
    productVariantId: p.product_variant_id,
    godownId: p.godown_id,
    godownName: p.godown_name,
    reorderPoint: Number(p.reorder_point),
    reorderQty: Number(p.reorder_qty),
    maxStock: p.max_stock === null ? undefined : Number(p.max_stock),
    isStocked: p.is_stocked,
  };
}

export interface ProductDetail {
  product: Product;
  variant: ProductVariant;
  brandName: string;
  categoryName: string;
  categoryPath: string;
  uomCode: string;
  conversions: UomConversionRow[];
  policies: GodownPolicyRow[];
  suppliers: {
    supplierId: Id;
    supplierName: string;
    supplierSku?: string;
    lastPurchasePrice?: number;
    lastPurchaseAt?: string;
    isPreferred: boolean;
    fromHistory: boolean;
  }[];
}

export async function getProduct(productVariantId: Id): Promise<ProductDetail> {
  // `httpGet` throws a 404 `ApiError` on a missing id.
  const [variantOut, conversions, policies, links] = await Promise.all([
    httpGet<VariantOut>(`/catalog/variants/${productVariantId}`),
    httpGet<ConversionOut[]>(`/catalog/variants/${productVariantId}/uom-conversions`),
    httpGet<GodownPolicyOut[]>(`/catalog/variants/${productVariantId}/godown-policies`),
    httpGet<SupplierProductOut[]>(`/catalog/variants/${productVariantId}/suppliers`),
  ]);
  const productOut = await httpGet<ProductOut>(`/catalog/products/${variantOut.product_id}`);

  const [brandOut, categoryOut, availableUoms] = await Promise.all([
    productOut.brand_id ? httpGet<BrandOut>(`/catalog/brands/${productOut.brand_id}`) : Promise.resolve(null),
    productOut.category_id ? httpGet<CategoryOut>(`/catalog/categories/${productOut.category_id}`) : Promise.resolve(null),
    // A variant's uom_id is almost always one of the 9 shared system units
    // (company_id IS NULL), which `GET /catalog/uoms/{id}` — tenant-scoped —
    // 404s on. `/catalog/uoms-available` includes those.
    httpGet<UomOut[]>("/catalog/uoms-available"),
  ]);
  const uomOut = availableUoms.find((u) => u.id === variantOut.uom_id) ?? null;

  const product = toProduct(productOut);
  const variant = toVariant(variantOut);
  const category = categoryOut ? toCategory(categoryOut) : null;

  return {
    product,
    variant,
    brandName: brandOut?.name ?? "",
    categoryName: category?.name ?? "",
    categoryPath: category?.path ?? "",
    uomCode: uomOut?.code ?? "",
    conversions: conversions.map(toConversion),
    policies: policies.map(toPolicy),
    suppliers: links.map(toLinkedProduct).map((l) => ({
      supplierId: l.supplierId,
      supplierName: l.supplierName,
      supplierSku: l.supplierSku,
      lastPurchasePrice: l.lastPurchasePrice,
      lastPurchaseAt: l.lastPurchaseAt,
      isPreferred: l.isPreferred,
      fromHistory: l.matchSource === "purchase_history",
    })),
  };
}

/* -------------------------------------------------------------- Commands */

/**
 * What a product form may send.
 *
 * Note what is absent: there is no `currentStock`, no `godowns` array and no
 * `status`. Stock is not a property of the catalogue. `openingStock` is
 * offered only when creating, and it posts an OPENING_STOCK transaction
 * rather than setting a number (C3).
 */
export interface ProductInput {
  name: string;
  sku: string;
  brandId: Id | null;
  categoryId: Id | null;
  hsnCode: string;
  gstRate: number;
  uomId: Id;
  trackingType: Product["trackingType"];
  purchasePrice: number;
  salePrice: number;
  mrp: number;
  reorderPoint: Quantity;
  reorderQty: Quantity;
  leadTimeDays?: number;
  barcode?: string;
  mpn?: string;
  modelCode?: string;
  displayEmoji?: string;
  attributes?: Record<string, string>;
  /** Create only. Posts an opening-stock movement into this godown. */
  openingStock?: { godownId: Id; quantity: Quantity } | null;
}

function validate(input: ProductInput): void {
  const errors: { field: string; message: string }[] = [];
  if (!input.name.trim()) errors.push({ field: "name", message: "Enter a product name." });
  if (!input.sku.trim()) errors.push({ field: "sku", message: "Enter a SKU code." });
  if (!input.uomId) errors.push({ field: "uomId", message: "Choose a unit of measure." });
  if (input.purchasePrice < 0) errors.push({ field: "purchasePrice", message: "Purchase price cannot be negative." });
  if (input.salePrice < 0) errors.push({ field: "salePrice", message: "Sale price cannot be negative." });
  if (input.mrp && input.salePrice > input.mrp) {
    errors.push({ field: "salePrice", message: "Sale price cannot exceed the MRP." });
  }
  if (input.reorderPoint < 0) errors.push({ field: "reorderPoint", message: "Reorder point cannot be negative." });

  // The SKU-uniqueness clash check that used to run against the mock
  // `productVariants` table is dropped here (a judgment call): once
  // products are real, that table no longer reflects what actually exists,
  // so a client-side "is this SKU taken" check would be meaningless. The
  // backend enforces uniqueness itself and returns a 422 `VALIDATION_FAILED`
  // (matching the shape `validationFailed()` throws below), which the form
  // already knows how to render via `fieldErrors`.

  if (errors.length) validationFailed(errors);
}

export async function createProduct(input: ProductInput): Promise<ProductDetail> {
  validate(input);

  const product = await httpPost<ProductOut>("/catalog/products", {
    name: input.name.trim(),
    base_uom_id: input.uomId,
    brand_id: input.brandId,
    category_id: input.categoryId,
    hsn_code: input.hsnCode,
    gst_rate: input.gstRate,
    cess_rate: 0,
    tracking_type: input.trackingType,
    is_active: true,
  });

  const variant = await httpPost<VariantOut>("/catalog/variants", {
    product_id: product.id,
    sku: input.sku.trim().toUpperCase(),
    uom_id: input.uomId,
    barcode: input.barcode,
    hsn_code: input.hsnCode,
    gst_rate: input.gstRate,
    purchase_price: input.purchasePrice,
    sale_price: input.salePrice,
    mrp: input.mrp,
    reorder_point: input.reorderPoint,
    reorder_qty: input.reorderQty,
    lead_time_days: input.leadTimeDays,
    is_active: true,
  });

  // Opening stock posts to the real ledger (BR-INV-01: opening stock is a
  // transaction like any other). This used to write into the mock ledger,
  // which meant a product created with an opening quantity showed no stock
  // anywhere — the rest of the app reads the real balances.
  if (input.openingStock && input.openingStock.quantity > 0) {
    await httpPost("/inventory/transactions", {
      txn_type: "OPENING_STOCK",
      product_variant_id: variant.id,
      godown_id: input.openingStock.godownId,
      quantity: input.openingStock.quantity,
      uom_id: input.uomId,
      reason_code: "opening_stock",
      remarks: "Opening stock entered when the product was created",
    });
  }

  return getProduct(variant.id);
}

export async function updateProduct(productVariantId: Id, input: ProductInput): Promise<ProductDetail> {
  validate(input);
  // Need the variant's `product_id` to know which product to PATCH — this
  // also serves as the "does it exist" check (404s automatically).
  const variantOut = await httpGet<VariantOut>(`/catalog/variants/${productVariantId}`);

  await httpPatch<ProductOut>(`/catalog/products/${variantOut.product_id}`, {
    name: input.name.trim(),
    brand_id: input.brandId,
    category_id: input.categoryId,
    hsn_code: input.hsnCode,
    gst_rate: input.gstRate,
    tracking_type: input.trackingType,
    base_uom_id: input.uomId,
  });

  await httpPatch<VariantOut>(`/catalog/variants/${productVariantId}`, {
    sku: input.sku.trim().toUpperCase(),
    barcode: input.barcode,
    hsn_code: input.hsnCode,
    gst_rate: input.gstRate,
    uom_id: input.uomId,
    purchase_price: input.purchasePrice,
    sale_price: input.salePrice,
    mrp: input.mrp,
    reorder_point: input.reorderPoint,
    reorder_qty: input.reorderQty,
    lead_time_days: input.leadTimeDays,
  });

  return getProduct(productVariantId);
}

/**
 * Master data is deactivated, never deleted, once it has been used — otherwise
 * historical documents would lose their references (BR-MD-04).
 */
export async function deactivateProduct(productVariantId: Id): Promise<void> {
  // `DELETE` soft-deletes server-side. The server refuses with
  // 409 RECORD_IN_USE while the SKU still has stock or sits on an open PO
  // line — the same rule `getProductUsage` pre-checks for the button.
  await httpDelete(`/catalog/variants/${productVariantId}`);
}

/** Whether a product can be deactivated, and why not. */
export async function getProductUsage(productVariantId: Id): Promise<{ inUse: boolean; reason?: string }> {
  const u = await httpGet<{ in_use: boolean; reason: string | null }>(`/catalog/variants/${productVariantId}/usage`);
  return { inUse: u.in_use, reason: u.reason ?? undefined };
}

/* ------------------------------------------------------------ Master data */

export async function listCategories(): Promise<Category[]> {
  const rows = await httpGet<CategoryOut[]>("/catalog/categories", { limit: 500 });
  return rows
    .filter((c) => c.is_active)
    .map(toCategory)
    .sort((a, b) => a.path.localeCompare(b.path));
}

export async function listBrands(): Promise<Brand[]> {
  const rows = await httpGet<BrandOut[]>("/catalog/brands", { limit: 500 });
  return rows
    .filter((b) => b.is_active)
    .map(toBrand)
    .sort((a, b) => a.name.localeCompare(b.name));
}

export async function listUoms(): Promise<Uom[]> {
  // `/catalog/uoms` is the standard tenant-scoped master-data list, which
  // deliberately excludes the 9 shared system units (company_id IS NULL) —
  // for a tenant with no custom units of its own it always comes back
  // empty, which breaks every form that needs a unit to pick from.
  // `/catalog/uoms-available` is the one that includes both.
  const rows = await httpGet<UomOut[]>("/catalog/uoms-available");
  return rows.filter((u) => u.is_active).map(toUom);
}

export async function listGodowns() {
  const rows = await httpGet<GodownOut[]>("/catalog/godowns", { limit: 500 });
  return rows.filter((g) => g.is_active).map(toGodown);
}

/** Conversions for a variant, so a PO line can be entered in boxes (I10). */
export async function listUomConversions(productVariantId: Id): Promise<UomConversionRow[]> {
  const rows = await httpGet<ConversionOut[]>(`/catalog/variants/${productVariantId}/uom-conversions`);
  return rows.map(toConversion);
}

export interface UomConversionInput {
  fromUomId: Id;
  factor: number;
  isPurchaseDefault?: boolean;
}

/** Adds "1 <from unit> = factor × base unit". The target is always the
 * variant's own base unit (BR-INV-08), so it is not sent. */
export async function addUomConversion(productVariantId: Id, input: UomConversionInput): Promise<UomConversionRow> {
  const errors: { field: string; message: string }[] = [];
  if (!input.fromUomId) errors.push({ field: "fromUomId", message: "Choose a unit." });
  if (!(input.factor > 0)) errors.push({ field: "factor", message: "Enter how many base units make one of this unit." });
  if (errors.length) validationFailed(errors);
  const row = await httpPost<ConversionOut>(`/catalog/variants/${productVariantId}/uom-conversions`, {
    from_uom_id: input.fromUomId,
    factor: input.factor,
    is_purchase_default: !!input.isPurchaseDefault,
  });
  return toConversion(row);
}

export async function deleteUomConversion(conversionId: Id): Promise<void> {
  await httpDelete(`/catalog/uom-conversions/${conversionId}`);
}

export interface GodownPolicyInput {
  godownId: Id;
  reorderPoint: Quantity;
  reorderQty: Quantity;
  maxStock?: Quantity | null;
  isStocked?: boolean;
}

/** Replaces the whole set of per-godown reorder levels for a variant. A
 * godown left out falls back to the variant's own reorder point. */
export async function saveGodownPolicies(productVariantId: Id, policies: GodownPolicyInput[]): Promise<GodownPolicyRow[]> {
  const errors: { field: string; message: string }[] = [];
  policies.forEach((p, i) => {
    if (p.reorderPoint < 0 || p.reorderQty < 0) {
      errors.push({ field: `policies.${i}`, message: "Levels cannot be negative." });
    }
    if (p.maxStock != null && p.maxStock < p.reorderPoint) {
      errors.push({ field: `policies.${i}`, message: "Max stock cannot be below the reorder point." });
    }
  });
  if (errors.length) validationFailed(errors);
  const rows = await httpPut<GodownPolicyOut[]>(`/catalog/variants/${productVariantId}/godown-policies`, {
    policies: policies.map((p) => ({
      godown_id: p.godownId,
      reorder_point: p.reorderPoint,
      reorder_qty: p.reorderQty,
      max_stock: p.maxStock ?? null,
      is_stocked: p.isStocked ?? true,
    })),
  });
  return rows.map(toPolicy);
}

/** Current stock for a variant — read, never written, by catalogue screens. */
export async function getVariantStock(productVariantId: Id, godownId?: Id): Promise<Quantity> {
  const rows = await httpGet<{ godown_id: string; quantity: number }[]>(
    `/inventory/stock/by-variant/${productVariantId}`,
  );
  const relevant = godownId ? rows.filter((r) => r.godown_id === godownId) : rows;
  return relevant.reduce((sum, r) => sum + r.quantity, 0);
}

