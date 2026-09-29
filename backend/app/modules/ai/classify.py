"""
What kind of document is this, and whose is it?

Deterministic, and deliberately modest. Document type comes from the words
a document uses about itself — a tax invoice says "tax invoice" somewhere
near the top, a quotation says "quotation" — and the supplier comes from
the strongest available identifier: a GSTIN matches exactly, a name matches
by trigram.

Both answers carry a confidence, and both are *proposals*: they land on the
review screen as editable fields, because a wrong supplier on an approved
invoice is a payment to the wrong company.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.normalise import normalise

#: Ordered: the first pattern that matches wins, so "proforma invoice" is
#: tested before the bare "invoice" that it contains.
_TYPE_PATTERNS: list[tuple[str, str, float]] = [
    (r"proforma\s*invoice|pro[- ]?forma", "proforma_invoice", 92.0),
    (r"tax\s*invoice|gst\s*invoice", "tax_invoice", 94.0),
    (r"delivery\s*challan|challan|e-?way\s*bill", "delivery_challan", 90.0),
    (r"purchase\s*order\b|\bp\.?o\.?\s*no", "purchase_order", 88.0),
    (r"price\s*revision|revised\s*(price|rate)", "price_revision", 88.0),
    (r"rate\s*(list|card)|price\s*list", "rate_list", 88.0),
    (r"quotation|quote\s*no|budgetary\s*offer|\boffer\b", "supplier_quotation", 90.0),
]

GSTIN = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z][0-9A-Z]\b")


@dataclass
class Classification:
    document_type: str
    type_confidence: float
    supplier_id: Optional[UUID]
    supplier_confidence: Optional[float]
    reasons: list[str]


def classify_type(text_body: str, headers: list[str]) -> tuple[str, float]:
    """The document's own words first, then the shape of its table.

    Only the first 1500 characters are searched for a self-description: a
    supplier's footer often says "this is not a tax invoice", and a match
    down there would mean the opposite of what it says.
    """
    head = (text_body or "")[:1500].lower()
    for pattern, doc_type, confidence in _TYPE_PATTERNS:
        if re.search(pattern, head):
            return doc_type, confidence

    # No self-description. A priced table is still recognisably an offer.
    normalised_headers = {normalise(h) for h in headers}
    priced = any(h in normalised_headers for h in ("rate", "unit price", "price", "basic rate"))
    quantified = any(h in normalised_headers for h in ("quantity", "qty", "nos"))
    if priced and quantified:
        return "supplier_quotation", 55.0
    if priced:
        return "rate_list", 50.0
    return "unrecognised", 20.0


async def identify_supplier(
    session: AsyncSession, *, company_id: str, text_body: str, hint_supplier_id: Optional[UUID] = None
) -> tuple[Optional[UUID], Optional[float], list[str]]:
    """A GSTIN in the text is proof; a name in the text is evidence."""
    if hint_supplier_id is not None:
        return hint_supplier_id, 100.0, ["Supplier chosen by the person uploading"]

    head = (text_body or "")[:4000]
    reasons: list[str] = []

    for gstin in {m.group(0) for m in GSTIN.finditer(head.upper())}:
        row = (
            await session.execute(
                text(
                    "SELECT id, name FROM suppliers "
                    "WHERE company_id = :c AND deleted_at IS NULL AND upper(gstin) = :g LIMIT 1"
                ),
                {"c": company_id, "g": gstin},
            )
        ).mappings().first()
        if row:
            return row["id"], 99.0, [f"GSTIN {gstin} belongs to {row['name']}"]
        reasons.append(f"GSTIN {gstin} is not a supplier on file")

    # Fall back to the name. `similarity` is indexed and bounded, and the
    # document's opening lines are where a letterhead lives.
    row = (
        await session.execute(
            text(
                "SELECT id, name, similarity(lower(name), lower(:t)) AS score FROM suppliers "
                "WHERE company_id = :c AND deleted_at IS NULL "
                "  AND lower(:t) LIKE '%' || lower(name) || '%' "
                "ORDER BY length(name) DESC LIMIT 1"
            ),
            {"c": company_id, "t": head[:600]},
        )
    ).mappings().first()
    if row:
        return row["id"], 85.0, reasons + [f"\"{row['name']}\" appears in the document"]

    return None, None, reasons + ["No supplier could be identified from the document"]
