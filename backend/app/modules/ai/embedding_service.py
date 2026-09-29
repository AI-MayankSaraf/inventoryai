"""
Product embeddings — rung 6 of the match ladder (`08_AI_DATA_MODEL.md` §4.3).

Each active variant gets one vector in `variant_embeddings`, built from the
words a supplier might use for it: product and variant name, brand,
category, pack size, model/MPN and SKU. A supplier line is embedded the same
way and the nearest variants by cosine distance become *suggestions* —
never auto-accepted (BR-AI-04), always shown with their similarity.

Freshness without bookkeeping: `content_hash` is md5(model + source text),
computed in SQL from the live catalogue. A variant whose name, brand or pack
changed, or whose vector came from a different model, simply no longer
matches its hash and is re-embedded by the next `sync`. `sync` runs:

* before every document is matched (a capped top-up, so a product added
  this morning is found this afternoon),
* on demand — `POST /ai/embeddings/rebuild`, the Settings screen, or
  `python -m scripts.rebuild_embeddings` for every company at once.

A provider that is down or misconfigured never fails a document: `sync`
reports what it could not do and matching falls back to the text rungs.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.ai import providers

log = logging.getLogger(__name__)

#: What a variant is called, in words — the text that gets embedded. Kept
#: in SQL so the freshness hash is computed from exactly the same string.
SOURCE_SQL = """concat_ws(' | ',
    p.name,
    NULLIF(v.variant_name, ''),
    COALESCE(b.name, NULLIF(p.manufacturer_name, '')),
    c.name,
    CASE WHEN v.pack_size IS NOT NULL AND v.pack_size <> 1 THEN 'pack of ' || trim_scale(v.pack_size)::text END,
    NULLIF(v.model_code, ''),
    NULLIF(v.mpn, ''),
    'SKU ' || v.sku,
    left(NULLIF(p.description, ''), 200)
)"""

_FROM = """
      FROM product_variants v
      JOIN products p ON p.id = v.product_id
      LEFT JOIN brands b ON b.id = p.brand_id
      LEFT JOIN categories c ON c.id = p.category_id
      LEFT JOIN variant_embeddings e ON e.product_variant_id = v.id
     WHERE v.company_id = :c AND v.deleted_at IS NULL AND v.is_active AND p.deleted_at IS NULL
"""

_HASH_SQL = f"md5(:model || '|' || {SOURCE_SQL})"

_db_dimensions: Optional[int] = None
_query_cache: "OrderedDict[str, list[float]]" = OrderedDict()
_QUERY_CACHE_MAX = 1024


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in values) + "]"


async def column_dimensions(session: AsyncSession) -> int:
    """The length `variant_embeddings.embedding` accepts — read from the
    schema, so a migration is the single place it is decided."""
    global _db_dimensions
    if _db_dimensions is None:
        _db_dimensions = (
            await session.execute(
                text(
                    "SELECT atttypmod FROM pg_attribute "
                    "WHERE attrelid = 'variant_embeddings'::regclass AND attname = 'embedding'"
                )
            )
        ).scalar_one()
    return int(_db_dimensions)


async def status(session: AsyncSession, company_id: str) -> dict:
    s = get_settings()
    model = s.ai_embedding_model or ""
    row = (
        await session.execute(
            text(
                "SELECT count(*) AS total, "
                f" count(*) FILTER (WHERE e.product_variant_id IS NOT NULL AND e.content_hash = {_HASH_SQL}) AS fresh, "
                " max(e.generated_at) AS last_generated "
                f"{_FROM}"
            ),
            {"c": company_id, "model": model},
        )
    ).mappings().one()
    return {
        "configured": providers.embeddings.configured,
        "provider": s.ai_provider,
        "model": model or None,
        "dimensions": await column_dimensions(session),
        "total_products": row["total"],
        "embedded": row["fresh"],
        "pending": row["total"] - row["fresh"],
        "last_generated_at": row["last_generated"],
    }


async def sync(session: AsyncSession, company_id: str, *, limit: Optional[int] = None, batch: int = 32) -> dict:
    """Embed every variant that has no vector, or whose vector is stale.
    Writes through the caller's session; the caller commits. Returns what
    happened, including an `error` rather than raising for provider trouble."""
    if not providers.embeddings.configured:
        return {"embedded": 0, "remaining": None, "error": "No embedding model is configured"}
    model = get_settings().ai_embedding_model
    dims = await column_dimensions(session)
    rows = (
        await session.execute(
            text(
                f"SELECT v.id, {SOURCE_SQL} AS source, {_HASH_SQL} AS hash "
                f"{_FROM} AND (e.product_variant_id IS NULL OR e.content_hash IS DISTINCT FROM {_HASH_SQL}) "
                "ORDER BY v.id" + (" LIMIT :limit" if limit else "")
            ),
            {"c": company_id, "model": model, **({"limit": limit} if limit else {})},
        )
    ).mappings().all()
    embedded = 0
    for start in range(0, len(rows), batch):
        chunk = rows[start : start + batch]
        try:
            vectors = await providers.embeddings.embed([r["source"] for r in chunk], role="document")
        except (providers.ProviderError, providers.ProviderNotConfigured) as exc:
            log.warning("embedding sync stopped for %s: %s", company_id, exc)
            return {"embedded": embedded, "remaining": len(rows) - embedded, "error": str(exc)}
        if vectors and len(vectors[0]) != dims:
            message = (
                f"The embedding model returns {len(vectors[0])} dimensions but the database column holds {dims}. "
                "Use a matching model or migrate the column."
            )
            log.error(message)
            return {"embedded": embedded, "remaining": len(rows) - embedded, "error": message}
        for r, vec in zip(chunk, vectors):
            await session.execute(
                text(
                    "INSERT INTO variant_embeddings (product_variant_id, company_id, embedding, model_id, "
                    " source_text, content_hash, generated_at) "
                    "VALUES (:v, :c, CAST(:vec AS vector), :model, :src, :hash, now()) "
                    "ON CONFLICT (product_variant_id) DO UPDATE SET embedding = EXCLUDED.embedding, "
                    " model_id = EXCLUDED.model_id, source_text = EXCLUDED.source_text, "
                    " content_hash = EXCLUDED.content_hash, generated_at = now()"
                ),
                {"v": r["id"], "c": company_id, "vec": _vector_literal(vec), "model": model,
                 "src": r["source"], "hash": r["hash"]},
            )
            embedded += 1
    # Only a capped run can leave work behind; count it rather than guess.
    remaining = (await status(session, company_id))["pending"] if limit and len(rows) == limit else 0
    return {"embedded": embedded, "remaining": remaining, "error": None}


async def nearest(session: AsyncSession, company_id: str, query: str, *, k: int) -> Optional[list[dict]]:
    """Variants nearest to `query` by meaning: rows with `sim` (cosine
    similarity, 0-1). `None` when the model could not be asked (not
    configured, down, wrong size) — as opposed to `[]`, asked and nothing
    in the index."""
    if not providers.embeddings.configured or not query.strip():
        return None
    model = get_settings().ai_embedding_model
    key = f"{model}|{query}"
    vec = _query_cache.get(key)
    if vec is None:
        try:
            vec = (await providers.embeddings.embed([query], role="query"))[0]
        except (providers.ProviderError, providers.ProviderNotConfigured) as exc:
            log.warning("semantic match skipped: %s", exc)
            return None
        _query_cache[key] = vec
        if len(_query_cache) > _QUERY_CACHE_MAX:
            _query_cache.popitem(last=False)
    else:
        _query_cache.move_to_end(key)
    if len(vec) != await column_dimensions(session):
        return None
    literal = _vector_literal(vec)
    rows = (
        await session.execute(
            text(
                "SELECT v.id, v.sku, v.barcode, v.ean, v.upc, v.mpn, v.model_code, "
                "       COALESCE(v.search_text, '') AS search_text, COALESCE(p.name, '') AS product_name, "
                "       COALESCE(v.variant_name, '') AS variant_name, "
                "       1 - (e.embedding <=> CAST(:q AS vector)) AS sim "
                "  FROM variant_embeddings e "
                "  JOIN product_variants v ON v.id = e.product_variant_id AND v.company_id = e.company_id "
                "  JOIN products p ON p.id = v.product_id "
                " WHERE e.company_id = :c AND e.model_id = :model "
                "   AND v.deleted_at IS NULL AND v.is_active "
                " ORDER BY e.embedding <=> CAST(:q AS vector) "
                " LIMIT :k"
            ),
            {"c": company_id, "q": literal, "model": model, "k": k},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


# ------------------------------------------------------ background rebuild

#: company_id -> progress of a rebuild running in this process. One at a
#: time per company; a second request while one runs just reports it.
_running: dict[str, dict] = {}
_tasks: set = set()


def rebuild_progress(company_id: str) -> Optional[dict]:
    return _running.get(company_id)


def start_rebuild(company_id: str, *, everything: bool = False) -> bool:
    """Embed the company's whole catalogue in the background. Returns False
    if one is already running. Uses its own platform session, so the request
    that started it can return straight away."""
    import asyncio

    from app.core.db import PlatformSessionLocal

    if company_id in _running:
        return False
    _running[company_id] = {"embedded": 0, "error": None}

    async def run() -> None:
        try:
            async with PlatformSessionLocal() as session:
                if everything:
                    await session.execute(
                        text("DELETE FROM variant_embeddings WHERE company_id = :c"), {"c": company_id}
                    )
                    await session.commit()
                while True:
                    result = await sync(session, company_id, limit=256)
                    await session.commit()
                    _running[company_id]["embedded"] += result["embedded"]
                    if result["error"]:
                        _running[company_id]["error"] = result["error"]
                        break
                    if not result["remaining"]:
                        break
        except Exception as exc:  # reported, never raised into the loop
            log.exception("embedding rebuild failed for %s", company_id)
            _running[company_id]["error"] = str(exc)
        finally:
            finished = _running.pop(company_id, None)
            if finished and finished["error"]:
                _last_error[company_id] = finished["error"]
            else:
                _last_error.pop(company_id, None)

    task = asyncio.get_running_loop().create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return True


#: The last rebuild's failure, so the Settings card can say why.
_last_error: dict[str, str] = {}


def last_error(company_id: str) -> Optional[str]:
    return _last_error.get(company_id)
