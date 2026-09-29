"""Generate (or refresh) product embeddings for every company.

    python -m scripts.rebuild_embeddings            # new + changed products only
    python -m scripts.rebuild_embeddings --all      # re-embed everything

Run after changing AI_EMBEDDING_MODEL, after a migration that resizes
`variant_embeddings.embedding`, or once after first enabling a provider.
Day to day it isn't needed: matching tops the index up before each document.
Runs on the platform engine (BYPASSRLS) because it walks every tenant; each
company's rows are written with that company's id.
"""

from __future__ import annotations

import asyncio
import sys
import time

from sqlalchemy import text

from app.core.db import PlatformSessionLocal
from app.modules.ai import embedding_service, providers


async def main(everything: bool) -> int:
    if not providers.embeddings.configured:
        print("No embedding model is configured (AI_PROVIDER / AI_EMBEDDING_MODEL). Nothing to do.")
        return 1
    async with PlatformSessionLocal() as session:
        companies = (
            await session.execute(text("SELECT id, name FROM companies WHERE deleted_at IS NULL ORDER BY name"))
        ).all()
        failed = False
        for company_id, name in companies:
            started = time.monotonic()
            if everything:
                await session.execute(text("DELETE FROM variant_embeddings WHERE company_id = :c"), {"c": company_id})
            result = await embedding_service.sync(session, str(company_id))
            await session.commit()
            state = await embedding_service.status(session, str(company_id))
            line = (
                f"{name}: embedded {result['embedded']} in {time.monotonic() - started:.1f}s - "
                f"{state['embedded']}/{state['total_products']} products indexed"
            )
            if result["error"]:
                failed = True
                line += f"  !! {result['error']}"
            print(line)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--all" in sys.argv)))
