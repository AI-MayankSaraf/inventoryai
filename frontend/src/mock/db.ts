/**
 * The mock database.
 *
 * One in-memory object, shaped like the real schema, persisted to a single
 * localStorage key. This is deliberately the ONLY place that talks to browser
 * storage for business data — screens and components must never touch
 * localStorage themselves (the old per-entity `*-store.ts` files did, which is
 * what made inventory authoritative in the browser).
 *
 * Server-side rendering gets a fresh, read-only copy of the seed so the first
 * paint is deterministic; the client hydrates from storage afterwards.
 */

import { createSeedDatabase, type MockDatabase } from "./seed";

export const STORAGE_KEY = "inventoryai.mockdb.v2";
/** Bump to invalidate a stored database after the seed shape changes. */
export const SCHEMA_VERSION = 2;

interface PersistedShape {
  schemaVersion: number;
  savedAt: string;
  data: MockDatabase;
}

const isBrowser = typeof window !== "undefined";

let cache: MockDatabase | null = null;
let saveHandle: ReturnType<typeof setTimeout> | null = null;

const listeners = new Set<() => void>();

function readStorage(): MockDatabase | null {
  if (!isBrowser) return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PersistedShape;
    if (!parsed || parsed.schemaVersion !== SCHEMA_VERSION || !parsed.data) return null;
    return parsed.data;
  } catch {
    return null;
  }
}

function writeStorage(data: MockDatabase): void {
  if (!isBrowser) return;
  try {
    const payload: PersistedShape = {
      schemaVersion: SCHEMA_VERSION,
      savedAt: new Date().toISOString(),
      data,
    };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch {
    /* Quota or private mode — the session simply stays in memory. */
  }
}

/**
 * The live database.
 *
 * On the server this is a fresh seed every call-site render, which keeps SSR
 * output stable. Never mutate the returned object outside `mutate()`.
 */
export function getDb(): MockDatabase {
  if (!isBrowser) return createSeedDatabase();
  if (!cache) cache = readStorage() ?? createSeedDatabase();
  return cache;
}

/** True once the client has taken over from the SSR copy. */
export function isPersisted(): boolean {
  return isBrowser && cache !== null;
}

function scheduleSave(): void {
  if (!isBrowser || !cache) return;
  if (saveHandle) clearTimeout(saveHandle);
  saveHandle = setTimeout(() => {
    saveHandle = null;
    if (cache) writeStorage(cache);
  }, 120);
}

/**
 * The only way to change data. Everything that writes goes through here, so
 * persistence and change notification happen in exactly one place.
 */
export function mutate<T>(fn: (db: MockDatabase) => T): T {
  const db = getDb();
  const result = fn(db);
  if (isBrowser) {
    scheduleSave();
    emit();
  }
  return result;
}

/** Read without the ability to persist — use for queries. */
export function read<T>(fn: (db: MockDatabase) => T): T {
  return fn(getDb());
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function emit(): void {
  for (const listener of listeners) {
    try {
      listener();
    } catch {
      /* a broken subscriber must not stop the others */
    }
  }
}

/** Wipe the stored database and start again from the seed. */
export function resetDb(): MockDatabase {
  cache = createSeedDatabase();
  if (isBrowser) {
    writeStorage(cache);
    emit();
  }
  return cache;
}

/** Version token bumped on every mutation, for cheap change detection. */
let revision = 0;
subscribe(() => {
  revision += 1;
});
export function getRevision(): number {
  return revision;
}

export type { MockDatabase };
