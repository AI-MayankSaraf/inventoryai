/**
 * Generic table access over the mock database.
 *
 * This is the layer that pretends to be PostgreSQL: it understands
 * `ListParams` (search, filters, sort, keyset cursor, date range) and returns
 * `ListResponse<T>`, exactly like the real collection endpoints will. Screens
 * therefore build a query object instead of filtering arrays in render, and
 * moving the work to the server later changes nothing above this line.
 */

import type { Id, ListParams, ListResponse } from "@/types";
import { getDb, mutate, type MockDatabase } from "./db";

type TableName = {
  [K in keyof MockDatabase]: MockDatabase[K] extends unknown[] ? K : never;
}[keyof MockDatabase];

export type Row<K extends TableName> = MockDatabase[K][number];

export function table<K extends TableName>(name: K): MockDatabase[K] {
  return getDb()[name];
}

/* -------------------------------------------------------------- Reading */

export function all<K extends TableName>(name: K): Row<K>[] {
  return table(name).slice() as Row<K>[];
}

export function byId<K extends TableName>(name: K, id: Id): Row<K> | undefined {
  return (table(name) as { id: Id }[]).find((r) => r.id === id) as Row<K> | undefined;
}

export function where<K extends TableName>(
  name: K,
  predicate: (row: Row<K>) => boolean,
): Row<K>[] {
  return (table(name) as Row<K>[]).filter(predicate);
}

export function first<K extends TableName>(
  name: K,
  predicate: (row: Row<K>) => boolean,
): Row<K> | undefined {
  return (table(name) as Row<K>[]).find(predicate);
}

/** Index a table by id for O(1) joins inside a service. */
export function indexById<T extends { id: Id }>(rows: T[]): Map<Id, T> {
  return new Map(rows.map((r) => [r.id, r]));
}

/* -------------------------------------------------------------- Writing */

export function insert<K extends TableName>(name: K, row: Row<K>): Row<K> {
  mutate((db) => {
    (db[name] as unknown[]).push(row);
  });
  return row;
}

export function insertMany<K extends TableName>(name: K, rows: Row<K>[]): Row<K>[] {
  mutate((db) => {
    (db[name] as unknown[]).push(...rows);
  });
  return rows;
}

export function update<K extends TableName>(
  name: K,
  id: Id,
  patch: Partial<Row<K>>,
): Row<K> | undefined {
  return mutate((db) => {
    const rows = db[name] as unknown as { id: Id }[];
    const index = rows.findIndex((r) => r.id === id);
    if (index === -1) return undefined;
    rows[index] = { ...rows[index], ...patch };
    return rows[index] as Row<K>;
  });
}

/** Apply a function to every row matching a predicate. */
export function updateWhere<K extends TableName>(
  name: K,
  predicate: (row: Row<K>) => boolean,
  patch: (row: Row<K>) => Partial<Row<K>>,
): Row<K>[] {
  return mutate((db) => {
    const rows = db[name] as unknown as Row<K>[];
    const touched: Row<K>[] = [];
    rows.forEach((row, index) => {
      if (!predicate(row)) return;
      rows[index] = { ...row, ...patch(row) };
      touched.push(rows[index]);
    });
    return touched;
  });
}

export function remove<K extends TableName>(name: K, id: Id): boolean {
  return mutate((db) => {
    const rows = db[name] as unknown as { id: Id }[];
    const index = rows.findIndex((r) => r.id === id);
    if (index === -1) return false;
    rows.splice(index, 1);
    return true;
  });
}

export function removeWhere<K extends TableName>(
  name: K,
  predicate: (row: Row<K>) => boolean,
): number {
  return mutate((db) => {
    const rows = db[name] as unknown as Row<K>[];
    let removed = 0;
    for (let i = rows.length - 1; i >= 0; i -= 1) {
      if (predicate(rows[i])) {
        rows.splice(i, 1);
        removed += 1;
      }
    }
    return removed;
  });
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

export const DEFAULT_PAGE_SIZE = 25;

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

/** Convenience for screens that want every matching row, not a page. */
export function queryAll<T extends Record<string, unknown>>(
  rows: T[],
  params: ListParams = {},
  config: QueryConfig<T> = {},
): ListResponse<T> {
  return query(rows, { ...params, limit: Number.MAX_SAFE_INTEGER, cursor: null }, config);
}
