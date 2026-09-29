/**
 * Small helpers for passing a one-time draft between screens in this
 * prototype — e.g. a quotation comparison's supplier split → the PO form,
 * or selected Low Stock items → the RFQ form. In the real backend this
 * would just be server state; sessionStorage keeps it scoped to the
 * current tab and each key is cleared the moment it's read.
 */

export const HANDOFF_KEYS = {
  poDraftGroups: "inventoryai:po-draft-groups",
  rfqDraft: "inventoryai:rfq-draft",
  comparisonSuppliers: "inventoryai:comparison-suppliers",
} as const;

function readOnce<T>(key: string): T | null {
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return null;
    window.sessionStorage.removeItem(key);
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function write<T>(key: string, value: T) {
  try {
    window.sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable — the destination screen just falls back to its default */
  }
}

export const handoff = { readOnce, write };
