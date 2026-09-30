"""Background extraction: queue columns on ai_processing_jobs

Revision ID: d5a1e8c3f604
Revises: c7e2a9f4b1d3
Create Date: 2026-09-30

Document reading moves out of the upload request into a worker
(app/modules/ai/worker.py), which claims queued jobs with
`FOR UPDATE SKIP LOCKED`. Two columns make that robust:

* `available_at` — a job is not claimed before this. A job whose worker
  died is put back with a delay rather than retried in a tight loop.
* `retry_count` — how many times a job was put back after its worker
  died. After the limit it is dead-lettered and the document marked
  failed, so one poisonous file cannot occupy the worker forever.
  (`attempt` stays what it was: how many times a person asked for the
  document to be read.)

The partial index serves the worker's claim query, which runs across
tenants and only ever looks at queued jobs.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5a1e8c3f604"
down_revision: Union[str, Sequence[str], None] = "c7e2a9f4b1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_processing_jobs",
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.add_column(
        "ai_processing_jobs",
        sa.Column("retry_count", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.create_index(
        "ix_ai_jobs_claim",
        "ai_processing_jobs",
        ["available_at", "created_at"],
        postgresql_where=sa.text("status = 'queued'"),
    )
    # Any job left 'running' by the old in-request pipeline was finished or
    # abandoned with its request; none is waiting for a worker.


def downgrade() -> None:
    op.drop_index("ix_ai_jobs_claim", table_name="ai_processing_jobs")
    op.drop_column("ai_processing_jobs", "retry_count")
    op.drop_column("ai_processing_jobs", "available_at")
