"""variant embeddings: 768 dimensions + HNSW cosine index

Revision ID: d4e9f2a6b8c1
Revises: c1d8e5a7f3b2
Create Date: 2026-09-27

`variant_embeddings.embedding` was declared `vector(1024)` before any
embedding model was chosen. The configured model (nomic-embed-text, and the
common open models like it — bge-base, e5-base, gte-base) returns 768, and
pgvector refuses a vector whose length differs from the column's. So the
column is resized, not padded or truncated: a padded vector is a different
vector and would quietly corrupt every similarity score.

Existing rows are deleted rather than converted — an embedding from one
model means nothing in another model's space, so there is nothing to keep.
The table is regenerated from the catalogue by
`app/modules/ai/embedding_service.py` (`python -m scripts.rebuild_embeddings`,
`POST /ai/embeddings/rebuild`, or automatically before matching).

The HNSW index uses cosine distance, the metric the matching rung ranks by.
`company_id` is still filtered first (§12): the index serves the ORDER BY,
RLS and the WHERE clause keep one tenant's catalogue out of another's.

Switching to a model with a different size later is the same migration
again with another number — `AI_EMBEDDING_DIMENSIONS` must match it, and the
embedding service refuses to write a vector of the wrong length.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d4e9f2a6b8c1"
down_revision: Union[str, Sequence[str], None] = "c1d8e5a7f3b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DIMENSIONS = 768


def upgrade() -> None:
    op.execute("DELETE FROM variant_embeddings")
    op.execute(f"ALTER TABLE variant_embeddings ALTER COLUMN embedding TYPE vector({DIMENSIONS})")
    op.execute(
        "CREATE INDEX ix_variant_embeddings_embedding_hnsw ON variant_embeddings "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_variant_embeddings_embedding_hnsw")
    op.execute("DELETE FROM variant_embeddings")
    op.execute("ALTER TABLE variant_embeddings ALTER COLUMN embedding TYPE vector(1024)")
