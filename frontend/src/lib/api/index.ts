/**
 * The API surface.
 *
 * Screens import from here and nowhere else. They must never import
 * `@/mock/*` directly — the mock database is an implementation detail of this
 * layer, and the whole point of the layering (UI → hooks → API → repository)
 * is that replacing it with HTTP touches only these files.
 */

export * as adminApi from "./admin.api";
export * as authApi from "./auth.api";
export * as catalogApi from "./catalog.api";
export * as documentsApi from "./documents.api";
export * as inventoryApi from "./inventory.api";
export * as invoicesApi from "./invoices.api";
export * as opsApi from "./ops.api";
export * as procurementApi from "./procurement.api";
export * as receivingApi from "./receiving.api";
export * as suppliersApi from "./suppliers.api";

export { ApiError, errorMessage, isApiError } from "./client";
export { recordAudit } from "./audit";
