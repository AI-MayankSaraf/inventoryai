/**
 * Supplier Portal API.
 *
 * Two audiences in one file:
 *
 * * **The supplier** (`signIn`, `getMe`, `getActivity`, `setPassword`) —
 *   authenticated with a portal token kept under its own storage key. It is
 *   deliberately never sent through `client.ts`'s `http()`, which attaches
 *   the *staff* token and refreshes it on a 401: the two identities must
 *   not mix, and a portal token is refused by every staff endpoint anyway.
 * * **The company** (`listPortalAccess`, `grantPortalAccess`,
 *   `resendPortalLink`, `revokePortalAccess`) — ordinary staff calls, made
 *   from the supplier's detail screen.
 */

import type {
  SupplierPortalAccess,
  SupplierPortalCompanyActivity,
  SupplierPortalPrincipal,
} from "@/types/supplier-portal";
import type { Id } from "@/types";
import { ApiError, httpDelete, httpGet, httpPost } from "./client";

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
const TOKEN_KEY = "inventoryai.supplier_portal.token.v1";
const isBrowser = typeof window !== "undefined";

export function getPortalToken(): string | null {
  if (!isBrowser) return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function storePortalToken(token: string | null): void {
  if (!isBrowser) return;
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable — the session just won't survive a reload */
  }
}

async function portalFetch<T>(path: string, init: { method?: string; body?: unknown; auth?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = init.auth === false ? null : getPortalToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(API_BASE_URL + path, {
      method: init.method ?? "GET",
      headers,
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    });
  } catch {
    throw new ApiError("Could not reach the server. Check your connection and try again.", {
      code: "NETWORK_ERROR",
      status: 0,
    });
  }
  const raw = await res.text();
  const payload = raw ? JSON.parse(raw) : null;
  if (!res.ok) {
    const p = (payload ?? {}) as { detail?: string; code?: string };
    if (res.status === 401 && init.auth !== false) storePortalToken(null);
    throw new ApiError(p.detail ?? `Request failed (${res.status})`, { code: p.code ?? "REQUEST_FAILED", status: res.status });
  }
  return payload as T;
}

/* ----------------------------------------------------------- supplier side */

interface PrincipalOut {
  id: string;
  email: string;
  full_name: string;
  companies: {
    access_id: string;
    company_id: string;
    company_name: string;
    city: string;
    state_name: string;
    supplier_id: string;
    supplier_name: string;
  }[];
}

function toPrincipal(o: PrincipalOut): SupplierPortalPrincipal {
  return {
    id: o.id,
    email: o.email,
    contactName: o.full_name,
    companies: o.companies.map((c) => ({
      id: c.access_id,
      companyId: c.company_id,
      name: c.company_name,
      city: c.city,
      stateName: c.state_name,
      supplierId: c.supplier_id,
      supplierName: c.supplier_name,
    })),
  };
}

export async function signIn(email: string, password: string): Promise<SupplierPortalPrincipal> {
  const out = await portalFetch<{ access_token: string; principal: PrincipalOut }>("/supplier-portal/login", {
    method: "POST",
    body: { email: email.trim(), password },
    auth: false,
  });
  storePortalToken(out.access_token);
  return toPrincipal(out.principal);
}

export function signOut(): void {
  storePortalToken(null);
}

/** The signed-in account, or null when there is no valid portal session. */
export async function getMe(): Promise<SupplierPortalPrincipal | null> {
  if (!getPortalToken()) return null;
  try {
    return toPrincipal(await portalFetch<PrincipalOut>("/supplier-portal/me"));
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return null;
    throw err;
  }
}

interface ActivityOut {
  rfqs: {
    id: string; number: string; subject: string; date: string; expected: string | null;
    status: string; invitation_status: string; line_count: number;
  }[];
  quotations: {
    id: string; number: string; rfq_number: string; date: string | null; valid_until: string | null;
    status: string; total_amount: number;
  }[];
  purchase_orders: {
    id: string; number: string; date: string; expected: string | null; status: string;
    total_amount: number; line_count: number;
  }[];
}

export async function getActivity(accessId: string): Promise<SupplierPortalCompanyActivity> {
  const o = await portalFetch<ActivityOut>(`/supplier-portal/access/${accessId}/activity`);
  return {
    rfqs: o.rfqs.map((r) => ({
      id: r.id, number: r.number, subject: r.subject, date: r.date, expected: r.expected,
      status: r.status, invitationStatus: r.invitation_status, lineCount: r.line_count,
    })),
    quotations: o.quotations.map((q) => ({
      id: q.id, number: q.number, rfqNumber: q.rfq_number, date: q.date, validUntil: q.valid_until,
      status: q.status, totalAmount: Number(q.total_amount),
    })),
    purchaseOrders: o.purchase_orders.map((p) => ({
      id: p.id, number: p.number, date: p.date, expected: p.expected, status: p.status,
      totalAmount: Number(p.total_amount), lineCount: p.line_count,
    })),
  };
}

/** Redeem the emailed link. */
export async function setPassword(token: string, password: string): Promise<void> {
  await portalFetch<void>("/supplier-portal/set-password", { method: "POST", body: { token, password }, auth: false });
}

/* ------------------------------------------------------------ company side */

interface AccessOut {
  id: string;
  account_id: string;
  email: string;
  full_name: string;
  status: SupplierPortalAccess["status"];
  account_status: SupplierPortalAccess["accountStatus"];
  granted_at: string;
  last_login_at: string | null;
}

function toAccess(o: AccessOut): SupplierPortalAccess {
  return {
    id: o.id,
    accountId: o.account_id,
    email: o.email,
    fullName: o.full_name,
    status: o.status,
    accountStatus: o.account_status,
    grantedAt: o.granted_at,
    lastLoginAt: o.last_login_at,
  };
}

export async function listPortalAccess(supplierId: Id): Promise<SupplierPortalAccess[]> {
  return (await httpGet<AccessOut[]>(`/catalog/suppliers/${supplierId}/portal-access`)).map(toAccess);
}

export async function grantPortalAccess(
  supplierId: Id,
  input: { email: string; fullName: string },
): Promise<SupplierPortalAccess> {
  return toAccess(
    await httpPost<AccessOut>(`/catalog/suppliers/${supplierId}/portal-access`, {
      email: input.email.trim(),
      full_name: input.fullName.trim(),
    }),
  );
}

export async function resendPortalLink(supplierId: Id, accessId: Id): Promise<void> {
  await httpPost(`/catalog/suppliers/${supplierId}/portal-access/${accessId}/resend`);
}

export async function revokePortalAccess(supplierId: Id, accessId: Id): Promise<void> {
  await httpDelete(`/catalog/suppliers/${supplierId}/portal-access/${accessId}`);
}
