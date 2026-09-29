/**
 * Document numbering, as the forms preview it.
 *
 * A document number is issued by the server from a per-tenant, per-financial-
 * year sequence when the document is saved (`app/core/numbering.py`) — never
 * by the browser, and never by scanning a list for the highest number, which
 * produces duplicates the moment two people save at once (C11).
 *
 * What a form can do is *show* the number the next document would get, read
 * from the real sequence (`GET /company/document-sequences`). It is a
 * preview: someone else may save first, and a consumed number is gone even
 * if its document isn't saved, so gaps are normal.
 */

import type { DocSequenceType, DocumentSequence } from "@/types";

export const PREVIEW_NUMBER_NOTE =
  "Assigned when the document is saved — the final number may differ.";

/** The number the next document of this type would get, formatted exactly
 * as the server formats it (`PO-2026-27-00012`), or null when this type has
 * no sequence yet this year — the server starts one on the first save. */
export function previewNumber(
  sequences: DocumentSequence[] | undefined,
  docType: DocSequenceType,
): string | null {
  const current = (sequences ?? [])
    .filter((s) => s.docType === docType)
    .sort((a, b) => b.financialYear.localeCompare(a.financialYear))[0];
  if (!current) return null;
  return `${current.prefix}${String(current.nextNumber).padStart(current.padding, "0")}`;
}
