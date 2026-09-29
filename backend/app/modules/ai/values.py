"""
Reading numbers and dates off an Indian purchase document.

Small, unglamorous, and the source of most silent errors if it is wrong:
`1,20,500.00` is twelve lakh five hundred in the lakh-crore grouping and
one hundred twenty thousand five hundred in the thousands grouping, and
both appear on real invoices. Stripping separators entirely is the only
reading that is right either way.

`parse_date` is deliberately day-first. `03/04/2026` is 3 April on every
Indian document; reading it as 3 March would put a quotation's validity a
month out with nothing on screen to show for it.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

_NUMBER = re.compile(r"-?\d[\d,\s]*(?:\.\d+)?")
_TRAILING_UNIT = re.compile(r"\s*(nos|pcs|kg|kgs|g|ltr|l|ml|mtr|m|mm|box|bag|set|pair|unit|units)\.?$", re.I)

_DATE_FORMATS = (
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
    "%d/%m/%y", "%d-%m-%y",
    "%Y-%m-%d", "%Y/%m/%d",
    "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y",
    "%d-%b-%Y", "%d-%b-%y",
)


def parse_number(raw: Optional[str]) -> Optional[Decimal]:
    """The first number in the text, separators removed.

    Returns `None` rather than 0 when there is no number: a missing
    quantity and a quantity of zero are different facts, and only one of
    them should be allowed through to a purchase line.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    text = text.replace("₹", " ").replace("Rs.", " ").replace("Rs", " ")
    text = _TRAILING_UNIT.sub("", text)
    # `(1,200.00)` is an accounting negative.
    negative = text.startswith("(") and text.endswith(")")
    match = _NUMBER.search(text)
    if not match:
        return None
    cleaned = re.sub(r"[,\s]", "", match.group(0))
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -value if negative else value


def parse_percent(raw: Optional[str]) -> Optional[Decimal]:
    """`18%`, `18`, `0.18` — the last of which is a fraction, not 0.18%."""
    value = parse_number(raw)
    if value is None:
        return None
    if value > 0 and value < 1 and "%" not in str(raw):
        return (value * 100).quantize(Decimal("0.01"))
    return value


def parse_date(raw: Optional[str]) -> Optional[date]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    # Some spreadsheets hand back a real datetime already.
    if isinstance(raw, (datetime, date)):
        return raw.date() if isinstance(raw, datetime) else raw
    candidate = re.search(r"\d{1,4}[\s/.\-][A-Za-z0-9]{1,9}[\s/.\-]\d{2,4}", text)
    token = candidate.group(0) if candidate else text
    token = re.sub(r"\s+", " ", token.strip())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue
    return None


def is_blank(raw: Optional[str]) -> bool:
    return raw is None or not str(raw).strip()


def clean(raw: Optional[str]) -> str:
    return re.sub(r"\s+", " ", str(raw or "")).strip()
