/**
 * The API client shim.
 *
 * Every screen in this app talks to `src/lib/api/*`. Those modules are written
 * as if they were HTTP calls: they are async, they can fail, they return the
 * shapes in `04_API_SPECIFICATION.md`, and they never expose the mock database
 * to the caller. Today `request()` runs a function against the in-memory
 * database; when the backend exists it becomes `fetch`, and nothing above this
 * file changes.
 *
 * Errors are thrown as `ApiError`, the way a real client would surface a
 * non-2xx response. Business-rule failures carry the rule id from
 * `06_BUSINESS_RULES.md` so the UI can explain *why* rather than just "failed".
 */

import type { ApiResult, ListParams } from "@/types";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly fieldErrors?: { field: string; message: string }[];

  constructor(
    message: string,
    options: { code?: string; status?: number; fieldErrors?: { field: string; message: string }[] } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.code = options.code ?? "REQUEST_FAILED";
    this.status = options.status ?? 400;
    this.fieldErrors = options.fieldErrors;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

/** Latency so loading states are exercised rather than skipped. */
const READ_LATENCY_MS = 90;
const WRITE_LATENCY_MS = 260;

const shouldDelay = typeof window !== "undefined" && process.env.NODE_ENV !== "test";

function sleep(ms: number): Promise<void> {
  if (!shouldDelay || ms <= 0) return Promise.resolve();
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** A read. Fast, and never mutates. */
export async function get<T>(fn: () => T): Promise<T> {
  await sleep(READ_LATENCY_MS);
  return fn();
}

/** A write. Slower, and may reject with an `ApiError`. */
export async function send<T>(fn: () => T): Promise<T> {
  await sleep(WRITE_LATENCY_MS);
  return fn();
}

/** Build the `ApiResult` envelope the real endpoints return. */
export function ok<T>(data: T): ApiResult<T> {
  return { ok: true, data };
}

export function fail(
  error: string,
  code?: string,
  fieldErrors?: { field: string; message: string }[],
): ApiResult<never> {
  return { ok: false, error, code, fieldErrors };
}

/** Unwrap an envelope, throwing the way a fetch client would. */
export function unwrap<T>(result: ApiResult<T>): T {
  if (!result.ok || result.data === undefined) {
    throw new ApiError(result.error ?? "Request failed", {
      code: result.code,
      fieldErrors: result.fieldErrors,
    });
  }
  return result.data;
}

/** Throw a business-rule failure. `code` is the rule id, e.g. `BR-GRN-06`. */
export function reject(message: string, code: string, status = 422): never {
  throw new ApiError(message, { code, status });
}

export function notFound(what: string): never {
  throw new ApiError(`${what} not found`, { code: "NOT_FOUND", status: 404 });
}

export function invalidTransition(from: string, to: string, allowed: string[]): never {
  throw new ApiError(
    allowed.length
      ? `Cannot go from ${from} to ${to}. Allowed: ${allowed.join(", ")}.`
      : `${from} is a final state — no further changes are possible.`,
    { code: "INVALID_STATE_TRANSITION", status: 409 },
  );
}

export function validationFailed(fieldErrors: { field: string; message: string }[]): never {
  throw new ApiError("Please correct the highlighted fields.", {
    code: "VALIDATION_FAILED",
    status: 422,
    fieldErrors,
  });
}

/** Normalise a list query so every endpoint treats params the same way. */
export function listParams(params: ListParams = {}): ListParams {
  return {
    q: params.q?.trim() || undefined,
    filters: params.filters,
    sort: params.sort,
    limit: params.limit,
    cursor: params.cursor ?? null,
    dateFrom: params.dateFrom,
    dateTo: params.dateTo,
  };
}

/** Human-readable message for any thrown value. */
export function errorMessage(error: unknown, fallback = "Something went wrong."): string {
  if (isApiError(error)) return error.message;
  if (error instanceof Error) return error.message;
  return fallback;
}

/* ======================================================================
 * Real HTTP — the backend wiring.
 *
 * Everything above this line is the mock-database shim the frontend
 * correction phase built (`get`/`send`/`reject`/`notFound`/...), and it is
 * still what `inventory.api.ts`, `documents.api.ts`, `invoices.api.ts` and
 * `ops.api.ts` use — those areas have no backend yet (AI matching, alerts,
 * reports, supplier invoices, purchase returns), so they deliberately stay
 * on the mock. `ApiError` and `errorMessage` above are shared by both
 * worlds so a screen never needs to know which one it's talking to.
 *
 * Everything below is for the areas that *do* have a real FastAPI backend
 * now: auth, catalog masters, company/users, and RFQ → PO → GRN. It talks
 * real fetch to that backend and parses its RFC 9457 `problem+json` error
 * envelope into the same `ApiError` shape above.
 * ==================================================================== */

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

const ACCESS_TOKEN_KEY = "inventoryai.access_token.v1";
const REFRESH_TOKEN_KEY = "inventoryai.refresh_token.v1";

const isBrowser = typeof window !== "undefined";

export interface StoredTokens {
  accessToken: string;
  refreshToken: string;
}

/** Read the current tokens. Synchronous — used by `currentSession()`-style guards. */
export function getStoredTokens(): StoredTokens | null {
  if (!isBrowser) return null;
  try {
    const accessToken = window.localStorage.getItem(ACCESS_TOKEN_KEY);
    const refreshToken = window.localStorage.getItem(REFRESH_TOKEN_KEY);
    if (!accessToken || !refreshToken) return null;
    return { accessToken, refreshToken };
  } catch {
    return null;
  }
}

/** Persist (or, with `null`, clear) the token pair. */
export function storeTokens(tokens: StoredTokens | null): void {
  if (!isBrowser) return;
  try {
    if (tokens) {
      window.localStorage.setItem(ACCESS_TOKEN_KEY, tokens.accessToken);
      window.localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refreshToken);
    } else {
      window.localStorage.removeItem(ACCESS_TOKEN_KEY);
      window.localStorage.removeItem(REFRESH_TOKEN_KEY);
    }
  } catch {
    /* storage unavailable — the session simply does not survive a reload */
  }
}

/** RFC 9457 `problem+json`, per `04_API_SPECIFICATION.md` §1. */
interface ProblemDetails {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  code?: string;
  errors?: { field: string; message: string }[];
  request_id?: string;
}

export type HttpQuery = Record<string, string | number | boolean | undefined | null>;

interface HttpOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: HttpQuery;
  /** Attach the bearer token and retry once via refresh on a 401. Default true. */
  auth?: boolean;
}

function buildUrl(path: string, query?: HttpQuery): string {
  const url = new URL(path.startsWith("http") ? path : `${API_BASE_URL}${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === "") continue;
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

let refreshInFlight: Promise<string | null> | null = null;

/** Exchange the stored refresh token for a new pair. One attempt at a time —
 * concurrent 401s from a burst of requests share the same refresh call rather
 * than each racing `/auth/refresh` and invalidating each other's result. */
async function refreshAccessToken(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    const tokens = getStoredTokens();
    if (!tokens) return null;
    try {
      const res = await fetch(buildUrl("/auth/refresh"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: tokens.refreshToken }),
      });
      if (!res.ok) {
        storeTokens(null);
        return null;
      }
      const data = (await res.json()) as { access_token: string; refresh_token: string };
      storeTokens({ accessToken: data.access_token, refreshToken: data.refresh_token });
      return data.access_token;
    } catch {
      return null;
    }
  })();
  try {
    return await refreshInFlight;
  } finally {
    refreshInFlight = null;
  }
}

async function performFetch(url: string, method: string, body: unknown, token: string | null): Promise<Response> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  return fetch(url, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

/** The real HTTP call. Throws `ApiError` on any non-2xx response, exactly
 * the way the mock's `reject`/`notFound`/`validationFailed` do, so a screen
 * that catches `ApiError` cannot tell which backend it was talking to. */
async function http<T>(path: string, options: HttpOptions = {}): Promise<T> {
  const { method = "GET", body, query, auth = true } = options;
  const url = buildUrl(path, query);
  const tokens = auth ? getStoredTokens() : null;

  let res: Response;
  try {
    res = await performFetch(url, method, body, tokens?.accessToken ?? null);
  } catch {
    throw new ApiError("Could not reach the server. Check that it's running and try again.", {
      code: "NETWORK_ERROR",
      status: 0,
    });
  }

  if (res.status === 401 && auth && tokens) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      try {
        res = await performFetch(url, method, body, newToken);
      } catch {
        throw new ApiError("Could not reach the server. Check that it's running and try again.", {
          code: "NETWORK_ERROR",
          status: 0,
        });
      }
    }
  }

  if (res.status === 204) return undefined as T;

  const raw = await res.text();
  let payload: unknown = null;
  if (raw) {
    try {
      payload = JSON.parse(raw);
    } catch {
      payload = null;
    }
  }

  if (!res.ok) {
    const problem = (payload ?? {}) as ProblemDetails;
    throw new ApiError(problem.detail ?? problem.title ?? `Request failed (${res.status})`, {
      code: problem.code ?? "REQUEST_FAILED",
      status: res.status,
      fieldErrors: problem.errors?.length ? problem.errors : undefined,
    });
  }

  return payload as T;
}

/**
 * In-flight GET dedup, keyed by the resolved URL.
 *
 * TanStack Query dedupes by *query key*, which only helps when two callers
 * share one. It doesn't help here: `listUsers()` and `listGodownsWithUsage()`
 * are different queries that each independently call `GET /catalog/godowns`
 * to build their own response — two unrelated cache keys hitting the same
 * URL, so the query-key cache can't see the overlap. This catches it one
 * layer down, at the actual network call, regardless of which feature (or
 * how many) asked for the same GET at the same moment.
 */
const inFlightGets = new Map<string, Promise<unknown>>();

export function httpGet<T>(path: string, query?: HttpQuery): Promise<T> {
  const url = buildUrl(path, query);
  const existing = inFlightGets.get(url);
  if (existing) return existing as Promise<T>;

  const request = http<T>(path, { method: "GET", query }).finally(() => {
    inFlightGets.delete(url);
  });
  inFlightGets.set(url, request);
  return request;
}

export function httpPost<T>(path: string, body?: unknown, options: { auth?: boolean } = {}): Promise<T> {
  return http<T>(path, { method: "POST", body, auth: options.auth ?? true });
}

export function httpPatch<T>(path: string, body?: unknown): Promise<T> {
  return http<T>(path, { method: "PATCH", body });
}

export function httpPut<T>(path: string, body?: unknown): Promise<T> {
  return http<T>(path, { method: "PUT", body });
}

export function httpDelete<T = void>(path: string): Promise<T> {
  return http<T>(path, { method: "DELETE" });
}

/**
 * Upload a file as multipart/form-data.
 *
 * Deliberately not routed through `http()`: that helper sets a JSON
 * content type, and a multipart body needs the browser to set its own
 * header *including the boundary*. Setting `Content-Type` by hand here
 * would produce a body the server cannot split.
 */
export async function httpUpload<T>(
  path: string,
  file: File,
  fields: Record<string, string | undefined> = {},
): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  for (const [key, value] of Object.entries(fields)) {
    if (value !== undefined && value !== null && value !== "") form.append(key, value);
  }

  const tokens = getStoredTokens();
  let res: Response;
  try {
    res = await fetch(buildUrl(path), {
      method: "POST",
      headers: tokens ? { Authorization: `Bearer ${tokens.accessToken}` } : undefined,
      body: form,
    });
  } catch {
    throw new ApiError("Could not reach the server. Check that it's running and try again.", {
      code: "NETWORK_ERROR",
      status: 0,
    });
  }

  const raw = await res.text();
  let payload: unknown = null;
  if (raw) {
    try {
      payload = JSON.parse(raw);
    } catch {
      payload = null;
    }
  }
  if (!res.ok) {
    const problem = (payload ?? {}) as ProblemDetails;
    throw new ApiError(problem.detail ?? problem.title ?? `Upload failed (${res.status})`, {
      code: problem.code ?? "REQUEST_FAILED",
      status: res.status,
      fieldErrors: problem.errors?.length ? problem.errors : undefined,
    });
  }
  return payload as T;
}
