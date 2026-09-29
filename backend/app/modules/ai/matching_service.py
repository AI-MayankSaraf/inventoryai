"""
The SKU match ladder — `08_AI_DATA_MODEL.md` §4.3.

A supplier writes `SS BOLT M10 X 50MM`; we have to decide it means SKU001.
The ladder climbs from certain-and-free to expensive-and-uncertain, and
stops at the first rung that clears its bar:

    1 exact_sku       the supplier quoted our own code          free
    2 supplier_alias  a code we confirmed for them before       one index lookup
    3 barcode         EAN/UPC matched                           one index lookup
    4 normalised_rule model/MPN found inside the description    in-process
    5 trigram         pg_trgm similarity on search_text         one query
    6 embedding       pgvector cosine on variant_embeddings     one embed + one query
    7 llm             not run per line (too slow on CPU)        -
    8 manual          a person picks

**Only rungs 1–4 may auto-accept** (BR-AI-04). Everything else produces a
ranked shortlist with reasons and waits for a human, and an extraction with
an unresolved line cannot be approved at all. That is the rule that makes
the whole feature safe to point at purchase commitments.

Structured tokens are a veto, not a score: a trigram can rate "5 litre" and
"3 litre" of the same cooker at 0.94, and they are different SKUs. A
measurement conflict caps confidence and says so in the reasons, per §4.4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.ai.normalise import normalise, tokens

#: Score at or above which a *deterministic* rung is accepted without a
#: human. The non-deterministic rungs have no entry here on purpose.
AUTO_ACCEPT: dict[str, float] = {
    "exact_sku": 0.99,
    "supplier_alias": 0.98,
    "barcode": 0.99,
    "normalised_rule": 0.95,
}

DETERMINISTIC = ("exact_sku", "supplier_alias", "barcode", "normalised_rule")

METHOD_LABELS = {
    "exact_sku": "Exact SKU",
    "supplier_alias": "Supplier code",
    "barcode": "Barcode",
    "normalised_rule": "Normalisation rule",
    "trigram": "Text similarity",
    "embedding": "Semantic similarity",
    "llm": "Language model",
    "manual": "Chosen by a person",
}


@dataclass
class Candidate:
    product_variant_id: UUID
    sku: str
    product_name: str
    method: str
    score: float
    confidence: float
    reasons: list[str] = field(default_factory=list)


@dataclass
class MatchResult:
    best: Optional[Candidate]
    candidates: list[Candidate]
    auto_matched: bool
    rung_reached: str
    #: Rungs that were skipped because no provider is configured. Surfaced
    #: so the reviewer knows the ladder stopped early rather than deciding.
    skipped_rungs: list[str] = field(default_factory=list)


_VARIANT_SELECT = """
    SELECT v.id, v.sku, v.barcode, v.ean, v.upc, v.mpn, v.model_code,
           COALESCE(v.search_text, '') AS search_text,
           COALESCE(p.name, '') AS product_name,
           COALESCE(v.variant_name, '') AS variant_name
      FROM product_variants v
      JOIN products p ON p.id = v.product_id
     WHERE v.company_id = :c AND v.deleted_at IS NULL AND v.is_active
"""


async def match_line(
    session: AsyncSession,
    *,
    company_id: str,
    description: str,
    supplier_sku: Optional[str] = None,
    barcode: Optional[str] = None,
    supplier_id: Optional[UUID] = None,
) -> MatchResult:
    settings = get_settings()
    query_tokens = tokens(description)
    normalised_query = normalise(description)

    # ---------------------------------------------------- 1. exact SKU
    code = (supplier_sku or "").strip()
    if code:
        row = (
            await session.execute(
                text(f"{_VARIANT_SELECT} AND lower(v.sku) = lower(:code) LIMIT 1"),
                {"c": company_id, "code": code},
            )
        ).mappings().first()
        if row:
            hit = _candidate(row, "exact_sku", 1.0, 100.0, ["The supplier quoted our own SKU code"])
            return MatchResult(best=hit, candidates=[hit], auto_matched=True, rung_reached="exact_sku")

    # ------------------------------------------- 2. supplier alias (learned)
    if code and supplier_id:
        row = (
            await session.execute(
                text(
                    f"{_VARIANT_SELECT} AND v.id = ("
                    "  SELECT sp.product_variant_id FROM supplier_products sp "
                    "   WHERE sp.company_id = :c AND sp.supplier_id = :sup "
                    "     AND lower(sp.supplier_sku) = lower(:code) LIMIT 1) "
                    "LIMIT 1"
                ),
                {"c": company_id, "sup": supplier_id, "code": code},
            )
        ).mappings().first()
        if row:
            source = (
                await session.execute(
                    text(
                        "SELECT match_source FROM supplier_products WHERE company_id = :c "
                        "AND supplier_id = :sup AND lower(supplier_sku) = lower(:code) LIMIT 1"
                    ),
                    {"c": company_id, "sup": supplier_id, "code": code},
                )
            ).scalar_one_or_none()
            reasons = [f"Supplier code {code} is already mapped to this SKU"]
            reasons.append(
                "The mapping was confirmed by a person on an earlier document"
                if source == "ai_confirmed"
                else "The mapping was entered manually"
            )
            hit = _candidate(row, "supplier_alias", 0.99, 99.0, reasons)
            return MatchResult(best=hit, candidates=[hit], auto_matched=True, rung_reached="supplier_alias")

    # ------------------------------------------------------- 3. barcode
    ean = (barcode or "").strip()
    if ean:
        row = (
            await session.execute(
                text(f"{_VARIANT_SELECT} AND (v.barcode = :b OR v.ean = :b OR v.upc = :b) LIMIT 1"),
                {"c": company_id, "b": ean},
            )
        ).mappings().first()
        if row:
            hit = _candidate(row, "barcode", 0.99, 99.0, ["Barcode matched exactly"])
            return MatchResult(best=hit, candidates=[hit], auto_matched=True, rung_reached="barcode")

    # --------------------------------------------- 4. normalisation rule
    #
    # A model code or manufacturer part number appearing inside the
    # description is a strong identity signal — but only if it is long
    # enough to be an identifier rather than a fragment of a word.
    if normalised_query:
        rows = (
            await session.execute(
                text(
                    f"{_VARIANT_SELECT} AND ("
                    "   (v.mpn IS NOT NULL AND length(v.mpn) >= 4 AND :q LIKE '%' || lower(v.mpn) || '%') "
                    "OR (v.model_code IS NOT NULL AND length(v.model_code) >= 4 "
                    "     AND :q LIKE '%' || lower(v.model_code) || '%')) "
                    "LIMIT 10"
                ),
                {"c": company_id, "q": normalised_query},
            )
        ).mappings().all()
        rule_hits: list[Candidate] = []
        for row in rows:
            token_hit = (row["mpn"] or row["model_code"] or "").strip()
            candidate = _candidate(
                row, "normalised_rule", 0.96, 96.0, [f'Model code "{token_hit}" appears in the description']
            )
            _apply_token_veto(candidate, query_tokens, row)
            rule_hits.append(candidate)
        rule_hits.sort(key=lambda c: -c.score)
        if rule_hits and rule_hits[0].score >= AUTO_ACCEPT["normalised_rule"]:
            return MatchResult(
                best=rule_hits[0],
                candidates=rule_hits[: settings.ai_candidate_limit],
                auto_matched=True,
                rung_reached="normalised_rule",
            )

    # ------------------------------------------------------- 5. trigram
    candidates: list[Candidate] = []
    if normalised_query:
        rows = (
            await session.execute(
                text(
                    f"{_VARIANT_SELECT} "
                    "   AND (similarity(COALESCE(v.search_text, ''), :q) >= :floor "
                    "        OR similarity(lower(p.name), :q) >= :floor) "
                    " ORDER BY GREATEST(similarity(COALESCE(v.search_text, ''), :q), "
                    "                   similarity(lower(p.name), :q)) DESC "
                    " LIMIT :limit"
                ),
                {
                    "c": company_id,
                    "q": normalised_query,
                    "floor": settings.ai_trigram_floor,
                    "limit": settings.ai_candidate_limit * 3,
                },
            )
        ).mappings().all()
        for row in rows:
            score = max(
                _similarity(normalised_query, normalise(row["search_text"])),
                _similarity(normalised_query, normalise(row["product_name"])),
            )
            label = row["product_name"] or row["sku"]
            candidate = _candidate(
                row,
                "trigram",
                score,
                round(score * 100, 2),
                [f'{round(score * 100)}% text similarity to "{label}"'],
            )
            _apply_token_veto(candidate, query_tokens, row)
            candidates.append(candidate)

    # ---------------------------------------------------- 6. embedding
    #
    # Nearest products by meaning: "circuit breaker 32 amp 2 pole" finds
    # "Havells MCB 32A Double Pole", which shares almost no trigrams with
    # it. Advisory only, like rung 5 — never auto-accepted (BR-AI-04), and
    # the measurement veto applies: 5 litre and 3 litre cookers are close
    # in meaning and are different SKUs.
    from app.modules.ai import embedding_service, providers

    skipped: list[str] = []
    semantic_ran = False
    if providers.embeddings.configured and description.strip():
        rows = await embedding_service.nearest(
            session, company_id, description, k=settings.ai_candidate_limit * 2
        )
        semantic_ran = rows is not None
        by_id = {c.product_variant_id: c for c in candidates}
        for row in rows or []:
            sim = float(row["sim"])
            if sim < settings.ai_embedding_floor:
                continue
            confidence = _semantic_confidence(sim, settings.ai_embedding_floor)
            label = row["product_name"] or row["sku"]
            reason = f'{round(sim * 100)}% similar in meaning to "{label}"'
            existing = by_id.get(row["id"])
            if existing is not None:
                # Found by both rungs: one candidate, the stronger reading,
                # both reasons.
                existing.reasons.append(reason)
                if confidence > existing.confidence and not any("capped" in r for r in existing.reasons):
                    existing.method, existing.score, existing.confidence = "embedding", round(sim, 4), confidence
                continue
            candidate = _candidate(row, "embedding", sim, confidence, [reason])
            _apply_token_veto(candidate, query_tokens, row)
            candidates.append(candidate)
            by_id[row["id"]] = candidate
    if not semantic_ran:
        skipped.append("embedding")

    candidates.sort(key=lambda c: (-c.confidence, -c.score))
    candidates = candidates[: settings.ai_candidate_limit]

    # ---------------------------------------------------------- 7. llm
    #
    # Not run per line: a local model takes 15-30 s per call on a CPU, so a
    # 20-line quotation would take minutes, and in testing a 3B model's
    # choices needed checking anyway. The ranked shortlist above goes to a
    # person instead — where an unconfirmed LLM choice would go regardless.
    skipped.append("llm")

    return MatchResult(
        best=candidates[0] if candidates else None,
        candidates=candidates,
        # Never true here: rungs 5+ are advisory by design.
        auto_matched=False,
        rung_reached=candidates[0].method if candidates else "manual",
        skipped_rungs=skipped,
    )


def _candidate(row, method: str, score: float, confidence: float, reasons: list[str]) -> Candidate:
    name = row["product_name"]
    if row["variant_name"]:
        name = f"{name} — {row['variant_name']}"
    return Candidate(
        product_variant_id=row["id"],
        sku=row["sku"],
        product_name=name,
        method=method,
        score=round(score, 4),
        confidence=round(confidence, 2),
        reasons=list(reasons),
    )


def _semantic_confidence(sim: float, floor: float) -> float:
    """Cosine similarity -> the 0-100 scale the review screen shows. The
    floor maps to 50 and 0.85 (a near-paraphrase) to 85; capped there,
    because a semantic suggestion is never as sure as a code match."""
    span = max(0.85 - floor, 0.01)
    return round(min(85.0, max(50.0, 50.0 + (sim - floor) / span * 35.0)), 2)


def _apply_token_veto(candidate: Candidate, query_tokens, row) -> None:
    """§4.4 — a measurement or thread conflict caps confidence however
    similar the text reads."""
    other = tokens(f"{row['product_name']} {row['variant_name']} {row['search_text']}")
    conflicts = query_tokens.conflicts_with(other)
    if not conflicts:
        return
    candidate.score = min(candidate.score, 0.5)
    candidate.confidence = min(candidate.confidence, 50.0)
    candidate.reasons.extend(conflicts)
    candidate.reasons.append("Confidence capped because a measurement does not agree")


def _similarity(a: str, b: str) -> float:
    """Trigram Jaccard — the same shape `pg_trgm` uses.

    Recomputed here rather than read from the query so the number in the
    reasons and the number used for ranking are provably the same one.
    """
    if not a or not b:
        return 0.0
    tri_a, tri_b = _trigrams(a), _trigrams(b)
    if not tri_a or not tri_b:
        return 0.0
    shared = len(tri_a & tri_b)
    return shared / (len(tri_a) + len(tri_b) - shared)


def _trigrams(value: str) -> set[str]:
    padded = f"  {value} "
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


async def record_candidates(
    session: AsyncSession,
    *,
    company_id: str,
    line_id: UUID,
    supplier_id: Optional[UUID],
    query_text: str,
    result: MatchResult,
    selected_variant_id: Optional[UUID] = None,
) -> None:
    """Write the shortlist behind a line — the evidence for *why*.

    Replaces any previous shortlist for the line, so re-running the ladder
    after a correction does not leave two generations of candidates on the
    review screen.
    """
    await session.execute(
        text("DELETE FROM ai_match_candidates WHERE company_id = :c AND extracted_line_id = :l"),
        {"c": company_id, "l": line_id},
    )
    for rank, candidate in enumerate(result.candidates, start=1):
        await session.execute(
            text(
                "INSERT INTO ai_match_candidates (id, company_id, extracted_line_id, query_text, "
                " normalised_query, supplier_id, rank, product_variant_id, match_method, score, "
                " confidence, reasons, is_selected) "
                "VALUES (:id, :c, :l, :q, :nq, :sup, :rank, :v, :m, :score, :conf, "
                " CAST(:reasons AS jsonb), :sel)"
            ),
            {
                "id": uuid4(),
                "c": company_id,
                "l": line_id,
                "q": query_text,
                "nq": normalise(query_text),
                "sup": supplier_id,
                "rank": rank,
                "v": candidate.product_variant_id,
                "m": candidate.method,
                "score": candidate.score,
                "conf": candidate.confidence,
                "reasons": _json(candidate.reasons),
                "sel": selected_variant_id is not None
                and candidate.product_variant_id == selected_variant_id,
            },
        )


def _json(value) -> str:
    import json

    return json.dumps(value)
