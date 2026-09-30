"""A dedicated document-reading worker process.

    python -m app.worker

Runs the same loop the API embeds by default (see app/modules/ai/worker.py).
Use it with EXTRACTION_WORKER=external on the API so OCR and parsing never
compete with requests; run as many as you like. Stops cleanly on Ctrl+C or
SIGTERM, finishing the document in hand first.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from app.core import storage
from app.core.config import get_settings
from app.core.db import engine
from app.modules.ai import worker


async def _main() -> int:
    settings = get_settings()
    problems = settings.production_problems()
    if problems:
        print("Refusing to start: " + " ".join(problems), file=sys.stderr)
        return 2
    await asyncio.to_thread(storage.assert_ready)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows: Ctrl+C raises KeyboardInterrupt instead
            pass
    try:
        await worker.run_forever(stop)
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        sys.exit(asyncio.run(_main()))
    except KeyboardInterrupt:
        sys.exit(0)
