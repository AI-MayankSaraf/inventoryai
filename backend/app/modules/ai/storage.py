"""
Moved to `app.core.storage`.

Uploaded bytes stopped being an AI-pipeline concern the moment the same
`documents` table started holding purchase orders and proformas that no
model ever reads. The implementation now lives in `app/core/storage.py`
(private S3, random keys, server-side encryption, pre-signed downloads).

This module stays as a re-export so nothing that imported it breaks, and
because a file whose contents silently changed meaning is worse than a
file that says where the meaning went. New code should import
`app.core.storage`.
"""

from __future__ import annotations

from app.core.storage import (  # noqa: F401
    StorageError,
    StorageNotConfigured,
    adelete,
    adelete_quietly,
    aexists,
    aget,
    apresigned_get_url,
    aput,
    assert_ready,
    bucket,
    build_key,
    delete,
    exists,
    get,
    iter_keys,
    presigned_get_url,
    put,
    reset_client,
)
