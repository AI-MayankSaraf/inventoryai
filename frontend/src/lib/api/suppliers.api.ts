/**
 * Suppliers, their contacts, and the supplier ⇄ SKU link table.
 *
 * Everything here is real now (`/catalog/suppliers*`, `/catalog/supplier-*`):
 * the supplier record, contacts, linked products, performance, PO history,
 * price history and the in-use check. Performance is derived server-side
 * from POs and GRNs (never stored), and a SKU the supplier has been bought
 * from but never had its item code recorded still shows as a linked product
 * with `matchSource: "purchase_history"`.
 */

import type {
  Id,
  ListParams,
  ListResponse,
  Supplier,
  SupplierContact,
  SupplierPerformance,
  SupplierProduct,
} from "@/types";
import { query } from "@/mock/repository";
import {
  httpDelete,
  httpGet,
  httpPatch,
  httpPost,
  isApiError,
  validationFailed,
} from "./client";

/* --------------------------------------------------------- Backend shapes */

/** `/catalog/suppliers` — mirrors `SupplierOut` in `catalog/schemas.py`. */
interface SupplierOut {
  id: string;
  name: string;
  supplier_code: string | null;
  supplier_type: string;
  gstin: string | null;
  pan: string | null;
  gst_treatment: string;
  city: string | null;
  state_code: string | null;
  state_name: string | null;
  address: string | null;
  pincode: string | null;
  primary_contact_name: string | null;
  phone: string | null;
  email: string | null;
  payment_terms: string | null;
  payment_terms_days: number | null;
  credit_limit: number | null;
  status: string;
  bank_name: string | null;
  bank_account_no: string | null;
  bank_ifsc: string | null;
  notes: string | null;
}

/** `catalog/detail_schemas.py` shapes. */
interface ContactOut {
  id: string;
  supplier_id: string;
  name: string;
  designation: string | null;
  phone: string | null;
  email: string | null;
  is_primary: boolean;
}

export interface SupplierProductOut {
  /** Null for a pair derived purely from purchase history. */
  id: string | null;
  supplier_id: string;
  supplier_name: string;
  product_variant_id: string;
  sku: string;
  product_name: string;
  supplier_sku: string | null;
  supplier_description: string | null;
  supplier_uom_id: string | null;
  conversion_to_base: number;
  last_quoted_price: number | null;
  last_quoted_at: string | null;
  last_purchase_price: number | null;
  last_purchase_at: string | null;
  lead_time_days: number | null;
  is_preferred: boolean;
  match_source: SupplierProduct["matchSource"];
  confirmed_at: string | null;
}

interface PerformanceOut {
  supplier_id: string;
  products_supplied: number;
  total_purchases: number;
  open_orders: number;
  on_time_delivery_pct: number;
  quality_score_pct: number;
  open_variances: number;
}

interface SupplierOrderOut {
  id: string;
  po_number: string;
  po_date: string;
  status: string;
  total_amount: number;
  received_pct: number;
}

interface UsageOut {
  in_use: boolean;
  reason: string | null;
}

/* -------------------------------------------------- snake_case -> camelCase */

function toSupplier(s: SupplierOut): Supplier {
  return {
    id: s.id,
    name: s.name,
    supplierCode: s.supplier_code ?? undefined,
    gstin: s.gstin,
    pan: s.pan,
    gstTreatment: s.gst_treatment as Supplier["gstTreatment"],
    supplierType: s.supplier_type as Supplier["supplierType"],
    city: s.city ?? "",
    stateCode: s.state_code ?? "",
    stateName: s.state_name ?? "",
    address: s.address ?? "",
    pincode: s.pincode ?? undefined,
    primaryContactName: s.primary_contact_name ?? "",
    phone: s.phone ?? "",
    email: s.email ?? "",
    paymentTerms: s.payment_terms ?? "",
    paymentTermsDays: s.payment_terms_days ?? undefined,
    bankName: s.bank_name ?? undefined,
    bankAccountNo: s.bank_account_no ?? undefined,
    bankIfsc: s.bank_ifsc ?? undefined,
    notes: s.notes ?? undefined,
    status: s.status as Supplier["status"],
    isActive: s.status === "active",
    deletedAt: null,
    createdAt: "",
    updatedAt: "",
  };
}

function toContact(c: ContactOut): SupplierContact {
  return {
    id: c.id,
    supplierId: c.supplier_id,
    name: c.name,
    designation: c.designation ?? "",
    phone: c.phone ?? "",
    email: c.email ?? "",
    isPrimary: c.is_primary,
  };
}

export type LinkedProduct = SupplierProduct & { sku: string; productName: string; supplierName: string };

/** A derived (purchase-history) row has no id of its own; the pair is
 * unique per supplier, so a stable synthetic key is safe for React. */
export function toLinkedProduct(r: SupplierProductOut): LinkedProduct {
  return {
    id: r.id ?? `history:${r.supplier_id}:${r.product_variant_id}`,
    supplierId: r.supplier_id,
    supplierName: r.supplier_name,
    productVariantId: r.product_variant_id,
    sku: r.sku,
    productName: r.product_name,
    supplierSku: r.supplier_sku ?? undefined,
    supplierDescription: r.supplier_description ?? undefined,
    supplierUomId: r.supplier_uom_id ?? undefined,
    conversionToBase: r.conversion_to_base,
    lastQuotedPrice: r.last_quoted_price ?? undefined,
    lastQuotedAt: r.last_quoted_at ?? undefined,
    lastPurchasePrice: r.last_purchase_price ?? undefined,
    lastPurchaseAt: r.last_purchase_at ?? undefined,
    leadTimeDays: r.lead_time_days ?? undefined,
    isPreferred: r.is_preferred,
    matchSource: r.match_source,
    confirmedAt: r.confirmed_at ?? undefined,
  };
}

function toPerformance(p: PerformanceOut): SupplierPerformance {
  return {
    supplierId: p.supplier_id,
    productsSupplied: p.products_supplied,
    totalPurchases: p.total_purchases,
    openOrders: p.open_orders,
    onTimeDeliveryPct: p.on_time_delivery_pct,
    qualityScorePct: p.quality_score_pct,
    openVariances: p.open_variances,
  };
}

/* ------------------------------------------------------------ Read models */

export interface SupplierListRow extends Supplier {
  productsSupplied: number;
  openOrders: number;
  totalPurchases: number;
  onTimeDeliveryPct: number;
}

/** No free-text search on the backend (rule 7 of the wiring brief), so this
 * pulls a generously large page and `query()` does search/sort/paging
 * client-side. Performance comes from one bulk call, not one per row. */
async function fetchSupplierListRows(): Promise<SupplierListRow[]> {
  const [suppliersOut, perfOut] = await Promise.all([
    httpGet<SupplierOut[]>("/catalog/suppliers", { limit: 500 }),
    httpGet<PerformanceOut[]>("/catalog/supplier-performance"),
  ]);
  const perfById = new Map(perfOut.map((p) => [p.supplier_id, p]));
  return suppliersOut.map((s) => {
    const perf = perfById.get(s.id);
    return {
      ...toSupplier(s),
      productsSupplied: perf?.products_supplied ?? 0,
      openOrders: perf?.open_orders ?? 0,
      totalPurchases: perf?.total_purchases ?? 0,
      onTimeDeliveryPct: perf?.on_time_delivery_pct ?? 0,
    };
  });
}

export async function listSuppliers(params: ListParams = {}): Promise<ListResponse<SupplierListRow>> {
  const rows = await fetchSupplierListRows();
  return query(rows as unknown as Record<string, unknown>[], params, {
    searchFields: ["name", "city", "stateName", "gstin", "primaryContactName", "email", "supplierCode"],
    facetFields: ["status", "supplierType", "stateName"],
    defaultSort: "name",
    defaultLimit: 50,
  }) as unknown as ListResponse<SupplierListRow>;
}

export interface SupplierDetail {
  supplier: Supplier;
  contacts: SupplierContact[];
  performance: SupplierPerformance;
  products: LinkedProduct[];
  recentOrders: { id: Id; poNumber: string; poDate: string; status: string; totalAmount: number; receivedPct: number }[];
  /** False when the user lacks `po.view` — the PO history panel says so
   * rather than pretending there are no orders. */
  canSeeOrders: boolean;
  openVariances: number;
}

/** PO history needs `po.view` on top of `supplier.view`; a 403 there is an
 * expected answer for Staff, not a page failure. */
async function fetchRecentOrders(supplierId: Id): Promise<SupplierDetail["recentOrders"] | null> {
  try {
    const rows = await httpGet<SupplierOrderOut[]>(`/catalog/suppliers/${supplierId}/purchase-orders`, { limit: 8 });
    return rows.map((po) => ({
      id: po.id,
      poNumber: po.po_number,
      poDate: po.po_date,
      status: po.status,
      totalAmount: po.total_amount,
      receivedPct: Math.round(po.received_pct),
    }));
  } catch (error) {
    if (isApiError(error) && error.status === 403) return null;
    throw error;
  }
}

export async function getSupplier(supplierId: Id): Promise<SupplierDetail> {
  // `httpGet` throws a 404 `ApiError` on a missing id.
  const [supplierOut, contacts, perf, links, orders] = await Promise.all([
    httpGet<SupplierOut>(`/catalog/suppliers/${supplierId}`),
    httpGet<ContactOut[]>(`/catalog/suppliers/${supplierId}/contacts`),
    httpGet<PerformanceOut>(`/catalog/suppliers/${supplierId}/performance`),
    httpGet<SupplierProductOut[]>(`/catalog/suppliers/${supplierId}/products`),
    fetchRecentOrders(supplierId),
  ]);
  const performance = toPerformance(perf);
  return {
    supplier: toSupplier(supplierOut),
    contacts: contacts.map(toContact),
    performance,
    products: links.map(toLinkedProduct),
    recentOrders: orders ?? [],
    canSeeOrders: orders !== null,
    openVariances: performance.openVariances,
  };
}

/* -------------------------------------------------------------- Commands */

export interface SupplierInput {
  name: string;
  gstin: string | null;
  pan: string | null;
  gstTreatment: Supplier["gstTreatment"];
  supplierType: Supplier["supplierType"];
  city: string;
  stateCode: string;
  stateName: string;
  address: string;
  pincode?: string;
  primaryContactName: string;
  phone: string;
  email: string;
  paymentTerms: string;
  paymentTermsDays?: number;
  bankName?: string;
  bankAccountNo?: string;
  bankIfsc?: string;
  status: Supplier["status"];
  notes?: string;
}

const GSTIN_PATTERN = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}$/;
const IFSC_PATTERN = /^[A-Z]{4}0[A-Z0-9]{6}$/;
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function validateSupplier(input: SupplierInput): void {
  const errors: { field: string; message: string }[] = [];
  if (!input.name.trim()) errors.push({ field: "name", message: "Enter the supplier's name." });
  if (!input.stateCode) errors.push({ field: "stateCode", message: "Choose a state — it decides CGST/SGST or IGST." });

  if (input.gstTreatment === "regular" || input.gstTreatment === "composition") {
    if (!input.gstin) {
      errors.push({ field: "gstin", message: "A GSTIN is required for a registered supplier." });
    } else if (!GSTIN_PATTERN.test(input.gstin.toUpperCase())) {
      errors.push({ field: "gstin", message: "That does not look like a valid 15-character GSTIN." });
    } else if (input.gstin.slice(0, 2) !== input.stateCode) {
      errors.push({
        field: "gstin",
        message: `The GSTIN starts with ${input.gstin.slice(0, 2)} but the state code is ${input.stateCode}.`,
      });
    }
  }
  if (input.email && !EMAIL_PATTERN.test(input.email)) {
    errors.push({ field: "email", message: "Enter a valid email address." });
  }
  if (input.bankIfsc && !IFSC_PATTERN.test(input.bankIfsc.toUpperCase())) {
    errors.push({ field: "bankIfsc", message: "An IFSC is 11 characters, like HDFC0001234." });
  }
  // GSTIN/name uniqueness is enforced by the backend (409), which the form
  // renders via `fieldErrors`.
  if (errors.length) validationFailed(errors);
}

/** Request body shared by create/update. Empty optional fields go as
 * `null` so an edit can actually clear them (PATCH skips omitted keys). */
function supplierBody(input: SupplierInput) {
  return {
    name: input.name.trim(),
    supplier_type: input.supplierType,
    gstin: input.gstin ? input.gstin.toUpperCase() : null,
    pan: input.pan,
    gst_treatment: input.gstTreatment,
    city: input.city,
    state_code: input.stateCode,
    state_name: input.stateName,
    address: input.address,
    pincode: input.pincode,
    primary_contact_name: input.primaryContactName,
    phone: input.phone,
    email: input.email,
    payment_terms: input.paymentTerms,
    payment_terms_days: input.paymentTermsDays,
    bank_name: input.bankName?.trim() || null,
    bank_account_no: input.bankAccountNo?.trim() || null,
    bank_ifsc: input.bankIfsc ? input.bankIfsc.trim().toUpperCase() : null,
    notes: input.notes?.trim() || null,
    status: input.status,
  };
}

export async function createSupplier(input: SupplierInput): Promise<Supplier> {
  validateSupplier(input);
  const created = await httpPost<SupplierOut>("/catalog/suppliers", supplierBody(input));
  const supplier = toSupplier(created);

  // The primary contact typed on the form also becomes the first entry on
  // the Contacts card. The supplier row already carries the same details,
  // so a failure here must not make the whole create look failed.
  if (input.primaryContactName.trim()) {
    try {
      await httpPost<ContactOut>(`/catalog/suppliers/${supplier.id}/contacts`, {
        name: input.primaryContactName.trim(),
        designation: "Primary contact",
        phone: input.phone || null,
        email: input.email || null,
        is_primary: true,
      });
    } catch {
      /* the contact can be added from the detail screen */
    }
  }
  return supplier;
}

export async function updateSupplier(supplierId: Id, input: SupplierInput): Promise<Supplier> {
  validateSupplier(input);
  const updated = await httpPatch<SupplierOut>(`/catalog/suppliers/${supplierId}`, supplierBody(input));
  return toSupplier(updated);
}

/** Pre-check for the Deactivate button. The server enforces the same rule
 * on the PATCH itself (409 RECORD_IN_USE). */
export async function getSupplierUsage(supplierId: Id): Promise<{ inUse: boolean; reason?: string }> {
  const u = await httpGet<UsageOut>(`/catalog/suppliers/${supplierId}/usage`);
  return { inUse: u.in_use, reason: u.reason ?? undefined };
}

export async function deactivateSupplier(supplierId: Id, reason?: string): Promise<void> {
  const body: Record<string, unknown> = { status: "inactive" };
  if (reason?.trim()) {
    // The reason lands in the supplier's notes, where the next person to
    // reactivate it will see why it was switched off.
    const current = await httpGet<SupplierOut>(`/catalog/suppliers/${supplierId}`);
    const stamp = new Date().toISOString().slice(0, 10);
    body.notes = [current.notes, `Deactivated ${stamp}: ${reason.trim()}`].filter(Boolean).join("\n");
  }
  await httpPatch<SupplierOut>(`/catalog/suppliers/${supplierId}`, body);
}

/* -------------------------------------------------------------- Contacts */

export async function listSupplierContacts(supplierId: Id): Promise<SupplierContact[]> {
  const rows = await httpGet<ContactOut[]>(`/catalog/suppliers/${supplierId}/contacts`);
  return rows.map(toContact);
}

export interface ContactInput {
  name: string;
  designation?: string;
  phone?: string;
  email?: string;
  isPrimary?: boolean;
}

function validateContact(input: ContactInput): void {
  const errors: { field: string; message: string }[] = [];
  if (!input.name.trim()) errors.push({ field: "name", message: "Enter the contact's name." });
  if (input.email && !EMAIL_PATTERN.test(input.email.trim())) {
    errors.push({ field: "email", message: "Enter a valid email address." });
  }
  if (errors.length) validationFailed(errors);
}

function contactBody(input: ContactInput) {
  return {
    name: input.name.trim(),
    designation: input.designation?.trim() || null,
    phone: input.phone?.trim() || null,
    email: input.email?.trim() || null,
    is_primary: !!input.isPrimary,
  };
}

export async function createContact(supplierId: Id, input: ContactInput): Promise<SupplierContact> {
  validateContact(input);
  return toContact(await httpPost<ContactOut>(`/catalog/suppliers/${supplierId}/contacts`, contactBody(input)));
}

export async function updateContact(contactId: Id, input: ContactInput): Promise<SupplierContact> {
  validateContact(input);
  return toContact(await httpPatch<ContactOut>(`/catalog/supplier-contacts/${contactId}`, contactBody(input)));
}

export async function deleteContact(contactId: Id): Promise<void> {
  await httpDelete(`/catalog/supplier-contacts/${contactId}`);
}

/* --------------------------------------------------------------- Aliases */

/** Confirming a match writes the supplier's code for our SKU (BR-AI-06).
 * Upserts on (supplier, SKU). */
export async function saveSupplierAlias(input: {
  supplierId: Id;
  productVariantId: Id;
  supplierSku?: string;
  supplierDescription?: string;
  source?: "manual" | "ai_confirmed" | "imported";
  isPreferred?: boolean;
}): Promise<LinkedProduct> {
  const row = await httpPost<SupplierProductOut>(`/catalog/suppliers/${input.supplierId}/products`, {
    product_variant_id: input.productVariantId,
    supplier_sku: input.supplierSku || null,
    supplier_description: input.supplierDescription || null,
    match_source: input.source ?? "manual",
    is_preferred: !!input.isPreferred,
  });
  return toLinkedProduct(row);
}

/** Price history for one supplier/SKU pair, newest first. Needs `po.view`. */
export async function getPriceHistory(supplierId: Id, productVariantId: Id) {
  const rows = await httpGet<{ po_id: string; po_number: string; po_date: string; unit_price: number; change_pct: number }[]>(
    `/catalog/suppliers/${supplierId}/price-history`,
    { product_variant_id: productVariantId },
  );
  return rows.map((r) => ({
    poId: r.po_id,
    poNumber: r.po_number,
    poDate: r.po_date,
    unitPrice: r.unit_price,
    changePct: r.change_pct,
  }));
}
