/**
 * Client-side list querying: search, filters, facets, sort and paging over
 * rows the API has already returned.
 *
 * Several screens fetch a whole collection from the backend and let the user
 * slice it in the browser. `query()` takes the same `ListParams` a list screen
 * builds and returns a `ListResponse`, so those screens look exactly like the
 * ones whose filtering happens on the server.
 */

import type { Id, ListParams, ListResponse } from "@/types";

/** Rows keyed by id, for joining one list onto another. */
export function indexById<T extends { id: Id }>(rows: T[]): Map<Id, T> {
  return new Map(rows.map((r) => [r.id, r]));
}

/* ------------------------------------------------------------- Querying */

export interface QueryConfig<T> {
  /** Fields concatenated for free-text `q` matching. */
  searchFields?: (keyof T | ((row: T) => string | undefined))[];
  /** Field holding the business date that `dateFrom`/`dateTo` filter on. */
  dateField?: keyof T;
  /** Fields that should be offered as facet counts. */
  facetFields?: (keyof T)[];
  /** Human labels for facet values. */
  facetLabels?: Partial<Record<string, Record<string, string>>>;
  defaultSort?: string;
  defaultLimit?: number;
  /** Applied before everything else — e.g. godown scoping. */
  scope?: (row: T) => boolean;
}

function textOf<T>(row: T, fields: QueryConfig<T>["searchFields"]): string {
  if (!fields?.length) return "";
  return fields
    .map((f) => (typeof f === "function" ? f(row) : (row[f] as unknown)))
    .filter((v) => v !== null && v !== undefined)
    .join(" ")
    .toLowerCase();
}

function compare(a: unknown, b: unknown): number {
  if (a === b) return 0;
  if (a === null || a === undefined) return 1;
  if (b === null || b === undefined) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "boolean" && typeof b === "boolean") return Number(a) - Number(b);
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

/** Cursors are opaque to callers, like the real keyset cursors will be. */
function encodeCursor(offset: number): string {
  return typeof btoa === "function"
    ? btoa(`o:${offset}`)
    : Buffer.from(`o:${offset}`).toString("base64");
}

function decodeCursor(cursor: string | null | undefined): number {
  if (!cursor) return 0;
  try {
    const raw = typeof atob === "function" ? atob(cursor) : Buffer.from(cursor, "base64").toString();
    const parsed = Number.parseInt(raw.replace("o:", ""), 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
  } catch {
    return 0;
  }
}

const DEFAULT_PAGE_SIZE = 25;

/** Run a `ListParams` query over an array of rows. */
export function query<T extends Record<string, unknown>>(
  rows: T[],
  params: ListParams = {},
  config: QueryConfig<T> = {},
): ListResponse<T> {
  let items = config.scope ? rows.filter(config.scope) : rows.slice();

  const filters = params.filters ?? {};
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === "" || value === "all") continue;
    items = items.filter((row) => {
      const field = row[key as keyof T];
      if (Array.isArray(field)) return (field as unknown[]).map(String).includes(value);
      return String(field ?? "") === value;
    });
  }

  if (params.q?.trim()) {
    const needles = params.q.trim().toLowerCase().split(/\s+/);
    items = items.filter((row) => {
      const haystack = textOf(row, config.searchFields);
      return needles.every((n) => haystack.includes(n));
    });
  }

  if (config.dateField && (params.dateFrom || params.dateTo)) {
    items = items.filter((row) => {
      const value = String(row[config.dateField!] ?? "").slice(0, 10);
      if (!value) return false;
      if (params.dateFrom && value < params.dateFrom) return false;
      if (params.dateTo && value > params.dateTo) return false;
      return true;
    });
  }

  // Facets are counted after filtering but before pagination, so a list screen
  // can show how many rows each status would return on this page of results.
  let facets: ListResponse<T>["facets"];
  if (config.facetFields?.length) {
    facets = {};
    for (const field of config.facetFields) {
      const counts = new Map<string, number>();
      for (const row of items) {
        const value = String(row[field] ?? "");
        if (!value) continue;
        counts.set(value, (counts.get(value) ?? 0) + 1);
      }
      facets[String(field)] = [...counts.entries()]
        .sort((a, b) => b[1] - a[1])
        .map(([value, count]) => ({
          value,
          label: config.facetLabels?.[String(field)]?.[value] ?? value,
          count,
        }));
    }
  }

  const sort = params.sort ?? config.defaultSort;
  if (sort) {
    const desc = sort.startsWith("-");
    const field = (desc ? sort.slice(1) : sort) as keyof T;
    items.sort((a, b) => (desc ? compare(b[field], a[field]) : compare(a[field], b[field])));
  }

  const total = items.length;
  const limit = params.limit ?? config.defaultLimit ?? DEFAULT_PAGE_SIZE;
  const offset = decodeCursor(params.cursor);
  const page = items.slice(offset, offset + limit);
  const nextOffset = offset + page.length;

  return {
    items: page,
    nextCursor: nextOffset < total ? encodeCursor(nextOffset) : null,
    total,
    facets,
  };
}
