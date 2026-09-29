"""
Reconcile the bucket against the `documents` table.

Two stores, one truth, and exactly one window in which they can disagree:
an upload whose object landed and whose transaction then failed to commit.
The upload handler already compensates for that by deleting the object, so
this script normally finds nothing — which is the point. It exists for the
case where the compensating delete itself failed (the process died, S3 was
unreachable for both calls), and for the periodic proof that no such case
is sitting unnoticed.

Two kinds of disagreement, and they are not equally serious:

  * **Orphan object** — bytes in the bucket that no row references. Nothing
    can reach them: every read path starts from a `documents` row, so an
    orphan is never served to anyone. It is a storage bill and a data
    retention problem (a customer's document outliving the record of it),
    not a correctness one. Safe to delete once it is older than the grace
    period.

  * **Dangling row** — a row whose object is gone. This one is visible:
    the document shows in the list and its download 404s. Never deleted
    automatically. It means the bytes were lost, and someone has to decide
    whether to restore from a bucket version or tell the user to re-upload.

    python -m scripts.s3_orphans              # report only
    python -m scripts.s3_orphans --delete     # delete orphan objects

Dry-run by default, and `--delete` skips anything newer than
`--grace-hours` (default 24), because an object written seconds ago may
belong to a request that has not committed yet. Deleting that would turn a
healthy upload into a dangling row — the worse of the two problems.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core import storage
from app.core.config import get_settings
from app.core.db import PlatformSessionLocal


async def _known_keys() -> dict[str, str]:
    """Every storage key the database knows about, mapped to its document
    id. Read with the platform (BYPASSRLS) role: reconciliation is
    cross-tenant by nature, and this is exactly the "handful of things that
    legitimately need to see across tenants" that role exists for."""
    async with PlatformSessionLocal() as session:
        rows = (
            await session.execute(text("SELECT id, storage_key, storage_bucket FROM documents"))
        ).mappings().all()
    return {r["storage_key"]: str(r["id"]) for r in rows}


def _bucket_keys() -> dict[str, tuple[int, datetime]]:
    return {key: (size, modified) for key, size, modified in storage.iter_keys()}


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delete", action="store_true", help="delete orphan objects (default: report only)")
    parser.add_argument("--grace-hours", type=int, default=24,
                        help="never delete objects younger than this (default 24)")
    args = parser.parse_args()

    settings = get_settings()
    storage.assert_ready()
    print(f"Bucket : {settings.s3_bucket}")
    print(f"Mode   : {'DELETE orphan objects' if args.delete else 'report only'}")
    print()

    known = await _known_keys()
    present = _bucket_keys()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.grace_hours)

    orphans = sorted(set(present) - set(known))
    dangling = sorted(set(known) - set(present))

    print(f"documents rows      : {len(known)}")
    print(f"objects in bucket   : {len(present)}")
    print(f"orphan objects      : {len(orphans)}")
    print(f"rows missing bytes  : {len(dangling)}")
    print()

    deleted = skipped = 0
    for key in orphans:
        size, modified = present[key]
        recent = modified > cutoff
        if args.delete and not recent:
            storage.delete(key)
            deleted += 1
            print(f"  deleted  {key}  ({size} bytes, {modified:%Y-%m-%d %H:%M})")
        else:
            skipped += 1
            why = "younger than the grace period" if recent else "dry run"
            print(f"  orphan   {key}  ({size} bytes, {modified:%Y-%m-%d %H:%M}) — {why}")

    for key in dangling:
        # Never touched automatically. A row with no bytes is a data-loss
        # incident, and the right response is a human deciding between a
        # versioned restore and a re-upload — not a script tidying away the
        # evidence.
        print(f"  MISSING BYTES  document {known[key]}  key {key}")

    print()
    print(f"deleted {deleted}, left alone {skipped}, rows needing attention {len(dangling)}")
    # Non-zero when a row has lost its bytes, so a cron job can alert on it.
    return 1 if dangling else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
