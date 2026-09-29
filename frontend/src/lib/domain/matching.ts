/**
 * The SKU match ladder.
 *
 * A supplier writes "PIGEON PRESSURE COOKER 5 LTR FAVOURITE"; we have to
 * decide it means SKU001. The real system climbs a ladder, stopping at the
 * first rung that clears its threshold, and escalates to a human when none
 * does. The rungs, in order:
 *
 *   exact_sku → supplier_alias → barcode → normalised_rule → trigram
 *   → embedding → llm → manual
 *
 * This module implements the rungs that are computable in the browser. The
 * embedding and llm rungs are backend-only: here they are represented, not
 * simulated, so the UI can render "matched by embedding" for seeded data
 * without pretending the browser ran a model (C8).
 */

import type { MatchMethod, Percent, ProductVariant, SupplierProduct } from "@/types";

/** Confidence at or above which a rung is accepted without human review. */
export const MATCH_THRESHOLDS: Record<MatchMethod, Percent> = {
  exact_sku: 100,
  supplier_alias: 95,
  barcode: 99,
  normalised_rule: 90,
  trigram: 85,
  embedding: 88,
  llm: 92,
  manual: 100,
};

export const MATCH_METHOD_LABELS: Record<MatchMethod, string> = {
  exact_sku: "Exact SKU",
  supplier_alias: "Supplier code",
  barcode: "Barcode",
  normalised_rule: "Normalisation rule",
  trigram: "Text similarity",
  embedding: "Semantic similarity",
  llm: "Language model",
  manual: "Chosen by a person",
};

/** Rungs that run in this prototype. The rest are backend-only. */
export const BROWSER_RUNGS: MatchMethod[] = [
  "exact_sku",
  "supplier_alias",
  "barcode",
  "normalised_rule",
  "trigram",
];

export const BACKEND_ONLY_RUNGS: MatchMethod[] = ["embedding", "llm"];

/* --------------------------------------------------------- Normalisation */

const UNIT_ALIASES: [RegExp, string][] = [
  [/\bltr\b|\blitre\b|\bliter\b|\bl\b/g, "l"],
  [/\bkgs?\b|\bkilo(gram)?s?\b/g, "kg"],
  [/\bgms?\b|\bgrams?\b/g, "g"],
  [/\bmtrs?\b|\bmeters?\b|\bmetres?\b/g, "m"],
  [/\bmms?\b/g, "mm"],
  [/\bwatts?\b|\bwtt\b/g, "w"],
  [/\bnos?\b|\bpcs?\b|\bpieces?\b/g, "nos"],
  [/\bdbl\b/g, "double"],
  [/\bss\b/g, "stainless steel"],
  [/\bms\b/g, "mild steel"],
];

export function normalise(text: string): string {
  let out = text.toLowerCase();
  out = out.replace(/[₹,]/g, " ");
  out = out.replace(/[^a-z0-9.\-/ ]+/g, " ");
  for (const [pattern, replacement] of UNIT_ALIASES) out = out.replace(pattern, replacement);
  return out.replace(/\s+/g, " ").trim();
}

/** Trigram set of a normalised string. */
function trigrams(text: string): Set<string> {
  const padded = `  ${text} `;
  const set = new Set<string>();
  for (let i = 0; i < padded.length - 2; i += 1) set.add(padded.slice(i, i + 3));
  return set;
}

/** Jaccard similarity over trigrams — the same metric `pg_trgm` uses. */
export function trigramSimilarity(a: string, b: string): number {
  const A = trigrams(normalise(a));
  const B = trigrams(normalise(b));
  if (A.size === 0 || B.size === 0) return 0;
  let shared = 0;
  for (const t of A) if (B.has(t)) shared += 1;
  return shared / (A.size + B.size - shared);
}

/* ------------------------------------------------------------- Matching */

export interface MatchInput {
  rawDescription: string;
  supplierSku?: string;
  barcode?: string;
  supplierId?: string | null;
}

export interface MatchCandidateResult {
  productVariantId: string;
  sku: string;
  productName: string;
  method: MatchMethod;
  score: number;
  confidence: Percent;
  reasons: string[];
}

export interface MatchOutcome {
  best: MatchCandidateResult | null;
  candidates: MatchCandidateResult[];
  /** True when the best candidate cleared its rung's threshold. */
  autoMatched: boolean;
  /** The rung that produced `best`, or the last rung tried. */
  rungReached: MatchMethod;
  /** Set when the browser rungs are exhausted — the backend continues. */
  escalatedToBackend: boolean;
}

export interface MatchContext {
  variants: ProductVariant[];
  productNameOf: (variantId: string) => string;
  supplierProducts: SupplierProduct[];
}

/**
 * Climb the ladder. Returns every candidate found so a review screen can show
 * the alternatives, not just the winner.
 */
export function matchLine(input: MatchInput, ctx: MatchContext): MatchOutcome {
  const candidates: MatchCandidateResult[] = [];
  const make = (
    variant: ProductVariant,
    method: MatchMethod,
    score: number,
    reasons: string[],
  ): MatchCandidateResult => ({
    productVariantId: variant.id,
    sku: variant.sku,
    productName: ctx.productNameOf(variant.id),
    method,
    score,
    confidence: Math.round(score * 100),
    reasons,
  });

  // 1. exact SKU — the supplier quoted our own code
  const query = (input.supplierSku ?? "").trim();
  if (query) {
    const exact = ctx.variants.find((v) => v.sku.toLowerCase() === query.toLowerCase());
    if (exact) {
      const hit = make(exact, "exact_sku", 1, ["Supplier quoted our SKU code"]);
      return { best: hit, candidates: [hit], autoMatched: true, rungReached: "exact_sku", escalatedToBackend: false };
    }
  }

  // 2. supplier alias — a code we have confirmed for this supplier before
  if (query && input.supplierId) {
    const alias = ctx.supplierProducts.find(
      (sp) =>
        sp.supplierId === input.supplierId &&
        sp.supplierSku?.toLowerCase() === query.toLowerCase(),
    );
    const variant = alias && ctx.variants.find((v) => v.id === alias.productVariantId);
    if (variant) {
      const hit = make(variant, "supplier_alias", 0.99, [
        `Supplier code ${alias!.supplierSku} is mapped to this SKU`,
        alias!.matchSource === "ai_confirmed" ? "Mapping confirmed by a person earlier" : "Mapping entered manually",
      ]);
      return { best: hit, candidates: [hit], autoMatched: true, rungReached: "supplier_alias", escalatedToBackend: false };
    }
  }

  // 3. barcode / EAN
  const barcode = (input.barcode ?? "").trim();
  if (barcode) {
    const byBarcode = ctx.variants.find((v) => v.barcode === barcode || v.ean === barcode);
    if (byBarcode) {
      const hit = make(byBarcode, "barcode", 0.99, ["Barcode matched exactly"]);
      return { best: hit, candidates: [hit], autoMatched: true, rungReached: "barcode", escalatedToBackend: false };
    }
  }

  // 4. normalisation rule — model or MPN appearing inside the description
  const normalisedQuery = normalise(input.rawDescription);
  for (const variant of ctx.variants) {
    const tokens = [variant.mpn, variant.modelCode].filter(Boolean).map((t) => normalise(String(t)));
    const hitToken = tokens.find((t) => t.length >= 4 && normalisedQuery.includes(t));
    if (hitToken) {
      candidates.push(make(variant, "normalised_rule", 0.93, [`Model code "${hitToken}" found in the description`]));
    }
  }
  const ruleBest = bestOf(candidates);
  if (ruleBest && ruleBest.confidence >= MATCH_THRESHOLDS.normalised_rule) {
    return { best: ruleBest, candidates: rank(candidates), autoMatched: true, rungReached: "normalised_rule", escalatedToBackend: false };
  }

  // 5. trigram similarity over the searchable text
  for (const variant of ctx.variants) {
    const score = Math.max(
      trigramSimilarity(input.rawDescription, variant.searchText ?? ""),
      trigramSimilarity(input.rawDescription, ctx.productNameOf(variant.id)),
    );
    if (score < 0.2) continue;
    candidates.push(
      make(variant, "trigram", score, [
        `${Math.round(score * 100)}% text similarity to "${ctx.productNameOf(variant.id)}"`,
      ]),
    );
  }

  const ranked = rank(candidates);
  const best = ranked[0] ?? null;
  const autoMatched = !!best && best.confidence >= MATCH_THRESHOLDS[best.method];

  return {
    best,
    candidates: ranked.slice(0, 5),
    autoMatched,
    rungReached: best?.method ?? "trigram",
    // Below the trigram threshold the real pipeline would try embeddings and
    // then an LLM. The browser stops here and says so.
    escalatedToBackend: !autoMatched,
  };
}

function bestOf(list: MatchCandidateResult[]): MatchCandidateResult | null {
  return list.reduce(
    (best, c) => (best === null || c.score > best.score ? c : best),
    null as MatchCandidateResult | null,
  );
}

function rank(list: MatchCandidateResult[]): MatchCandidateResult[] {
  const byVariant = new Map<string, MatchCandidateResult>();
  for (const c of list) {
    const existing = byVariant.get(c.productVariantId);
    if (!existing || c.score > existing.score) byVariant.set(c.productVariantId, c);
  }
  return [...byVariant.values()].sort((a, b) => b.score - a.score);
}
