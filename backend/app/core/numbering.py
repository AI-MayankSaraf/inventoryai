"""
Document numbering — 06_BUSINESS_RULES.md §BR-NUM-01..05.

    BR-NUM-01: Numbers are allocated from `document_sequences` under a row
    lock inside the creating transaction — never `max+1` in application
    code. (The prototype's `max+1` over localStorage guarantees collisions
    with concurrent users.)

So `allocate()` takes the caller's session and runs inside the caller's
transaction. That placement is the whole design:

  * The `SELECT ... FOR UPDATE` row lock only holds for the life of a
    transaction, so allocating in a separate transaction would release the
    lock before the document row is written — reintroducing exactly the
    race it exists to prevent.
  * If the caller's transaction rolls back, the allocation rolls back with
    it. That deliberately *reuses* the number, which sounds like it
    contradicts BR-NUM-04 ("allocated numbers are never reused") but
    doesn't: BR-NUM-04 is about a document that was successfully created
    and later cancelled. A transaction that never committed created no
    document, so there is no number to burn.

BR-NUM-03 (sequences reset per financial year) is handled by
`financial_year_for()`, which reads the tenant's own
`company_settings.financial_year_start_month` rather than assuming April —
the column is configurable, so the code has no business hardcoding India's
default.
"""

from __future__ import annotations

from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DOC_TYPES = ("rfq", "po", "grn", "proforma", "invoice", "transfer", "return", "adjustment")

_DEFAULT_PREFIXES = {
    "rfq": "RFQ-",
    "po": "PO-",
    "grn": "GRN-",
    "proforma": "PI-",
    "invoice": "INV-",
    "transfer": "TRF-",
    "return": "PR-",
    "adjustment": "ADJ-",
}


class NumberingError(RuntimeError):
    pass


def financial_year_for(on: date, start_month: int) -> str:
    """"2026-27" for a date inside the FY beginning in April 2026, when
    `start_month` is 4. A tenant on a January start gets "2026-27" for
    dates in 2026 instead — the label always names the year the FY opened
    and the two-digit year it closes in."""
    start_year = on.year if on.month >= start_month else on.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


async def allocate(
    session: AsyncSession,
    *,
    company_id: UUID,
    doc_type: str,
    on: Optional[date] = None,
) -> str:
    """Allocate the next number for one document type, e.g. `PO-2026-27-00042`.

    MUST be called inside the same transaction that writes the document
    row. Concurrent callers for the same (company, doc_type, FY) serialise
    on the row lock: the second waits for the first to commit, then reads
    the already-incremented counter. Different tenants, different doc types
    and different financial years all live on different rows, so they never
    block each other.
    """
    if doc_type not in DOC_TYPES:
        raise NumberingError(f"Unknown document type: {doc_type}")

    on = on or date.today()

    start_month = (
        await session.execute(
            text("SELECT financial_year_start_month FROM company_settings WHERE company_id = :c"),
            {"c": company_id},
        )
    ).scalar_one_or_none() or 4
    fy = financial_year_for(on, start_month)

    # The row lock. FOR UPDATE blocks any other transaction trying to
    # allocate the same counter until this one finishes.
    row = (
        await session.execute(
            text(
                "SELECT id, prefix, padding, next_number FROM document_sequences "
                "WHERE company_id = :c AND doc_type = :d AND financial_year = :fy "
                "FOR UPDATE"
            ),
            {"c": company_id, "d": doc_type, "fy": fy},
        )
    ).mappings().first()

    if row is None:
        # First document of this type in a new financial year. ON CONFLICT
        # makes the create itself race-safe: if a concurrent transaction
        # created the row first, we take theirs instead of failing.
        row = (
            await session.execute(
                text(
                    "INSERT INTO document_sequences (company_id, doc_type, financial_year, prefix, next_number) "
                    "VALUES (:c, :d, :fy, :prefix, 1) "
                    "ON CONFLICT ON CONSTRAINT uq_docseq DO UPDATE SET prefix = document_sequences.prefix "
                    "RETURNING id, prefix, padding, next_number"
                ),
                {
                    "c": company_id,
                    "d": doc_type,
                    "fy": fy,
                    "prefix": f"{_DEFAULT_PREFIXES[doc_type]}{fy}-",
                },
            )
        ).mappings().first()

    number = row["next_number"]
    await session.execute(
        text("UPDATE document_sequences SET next_number = next_number + 1 WHERE id = :id"),
        {"id": row["id"]},
    )

    # BR-NUM-02: {prefix}{zero-padded sequence}, padding from settings.
    return f"{row['prefix']}{str(number).zfill(row['padding'])}"
