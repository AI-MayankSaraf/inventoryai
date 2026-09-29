"""
Deterministic normalisation — `08_AI_DATA_MODEL.md` §4.2.

Both sides of every comparison go through this: a supplier's line text and
`product_variants.search_text`. That is the whole point — `SS BOLT M10 X
50MM` and `Stainless Steel Hex Bolt M10 x 50 mm` only meet if they are
reduced the same way.

The unit handling is not decoration. The brief's own example is three
phrasings of one SKU where the third says `2 inch` and means 50.8 mm, so a
synonym dictionary alone gets it wrong; `tokens()` converts to a canonical
unit and compares with a tolerance band.

Nothing here calls a model, and nothing here is tenant-specific yet — §4.2
envisages a per-tenant abbreviation dictionary, which is a later
refinement, not a prerequisite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

#: Abbreviation → expansion, applied on word boundaries after punctuation
#: is stripped. Order matters only where one expansion feeds another; these
#: are all independent.
_ABBREVIATIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bss\b"), "stainless steel"),
    (re.compile(r"\bms\b"), "mild steel"),
    (re.compile(r"\bhex\b"), "hexagonal"),
    (re.compile(r"\bdbl\b"), "double"),
    (re.compile(r"\bsgl\b"), "single"),
    (re.compile(r"\bgalv\b|\bgi\b"), "galvanised"),
    (re.compile(r"\bltr\b|\blitres?\b|\bliters?\b"), "l"),
    (re.compile(r"\bkgs?\b|\bkilo(?:gram)?s?\b"), "kg"),
    (re.compile(r"\bgms?\b|\bgrams?\b"), "g"),
    (re.compile(r"\bmtrs?\b|\bmet(?:er|re)s?\b"), "m"),
    (re.compile(r"\bm\.m\.?\b|\bmms?\b"), "mm"),
    (re.compile(r"\bwatts?\b|\bwtt\b"), "w"),
    (re.compile(r"\bnos?\b|\bpcs?\b|\bpiece?s?\b|\bnumbers?\b"), "nos"),
    (re.compile(r"\bqty\b"), "quantity"),
    (re.compile(r"\bw/\b"), "with "),
]

#: Every length in millimetres, every mass in grams, every volume in
#: millilitres, so `2 inch` and `50 mm` land in the same space.
_UNIT_TO_BASE: dict[str, tuple[str, float]] = {
    "mm": ("length_mm", 1.0),
    "cm": ("length_mm", 10.0),
    "m": ("length_mm", 1000.0),
    "inch": ("length_mm", 25.4),
    "in": ("length_mm", 25.4),
    '"': ("length_mm", 25.4),
    "ft": ("length_mm", 304.8),
    "g": ("mass_g", 1.0),
    "kg": ("mass_g", 1000.0),
    "ml": ("volume_ml", 1.0),
    "l": ("volume_ml", 1000.0),
    "w": ("power_w", 1.0),
    "kw": ("power_w", 1000.0),
}

_QUANTITY = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mm|cm|kg|ml|kw|ft|in(?:ch)?|[lgmw])\b",
    re.IGNORECASE,
)
#: `M10`, `M6x1.0` — a thread spec, which is a strong identity signal.
_THREAD = re.compile(r"\bm(\d{1,3}(?:\.\d+)?)\b", re.IGNORECASE)
#: Anything that looks like a part number: letters and digits mixed, ≥4 long.
_IDENTIFIER = re.compile(r"\b(?=[a-z0-9\-/]*\d)(?=[a-z0-9\-/]*[a-z])[a-z0-9][a-z0-9\-/]{3,}\b", re.IGNORECASE)

_TOLERANCE = 0.02  # ±2%, per §4.2 step 3


def normalise(text: Optional[str]) -> str:
    """Lowercase, strip punctuation, expand abbreviations, collapse space.

    `x` between two numbers becomes a space so `M10 X 50MM` and `M10x50mm`
    reduce identically.
    """
    if not text:
        return ""
    out = text.lower()
    out = out.replace("₹", " ").replace(",", " ")
    out = re.sub(r"(\d)\s*[x×]\s*(\d)", r"\1 \2", out)
    out = re.sub(r"[^a-z0-9.\-/\" ]+", " ", out)
    out = re.sub(r"\s+", " ", out).strip()
    for pattern, replacement in _ABBREVIATIONS:
        out = pattern.sub(replacement, out)
    return re.sub(r"\s+", " ", out).strip()


@dataclass
class Tokens:
    """Structured facts pulled out of a description, for cross-checking a
    candidate rather than for scoring it."""

    measures: dict[str, float] = field(default_factory=dict)
    thread: Optional[str] = None
    identifiers: set[str] = field(default_factory=set)

    def conflicts_with(self, other: "Tokens") -> list[str]:
        """Why these two cannot be the same thing.

        A conflict caps confidence regardless of how similar the text is
        (§4.4): "5 litre" and "3 litre" of the same cooker read almost
        identically to a trigram, and are different SKUs.
        """
        reasons: list[str] = []
        for dimension, value in self.measures.items():
            theirs = other.measures.get(dimension)
            if theirs is None:
                continue
            if abs(value - theirs) > max(value, theirs) * _TOLERANCE:
                reasons.append(f"{dimension.replace('_', ' ')} differs ({_pretty(value)} vs {_pretty(theirs)})")
        if self.thread and other.thread and self.thread != other.thread:
            reasons.append(f"thread differs (M{self.thread} vs M{other.thread})")
        return reasons


def tokens(text: Optional[str]) -> Tokens:
    normalised = normalise(text)
    out = Tokens()
    for match in _QUANTITY.finditer(normalised):
        unit = match.group("unit").lower()
        unit = {"inch": "inch", "in": "inch"}.get(unit, unit)
        mapped = _UNIT_TO_BASE.get(unit)
        if mapped is None:
            continue
        dimension, factor = mapped
        value = float(match.group("value")) * factor
        # The largest stated value of a dimension wins: "5 l" in "5 l
        # pressure cooker 2 kg" describes the product, while a stray small
        # number rarely does.
        out.measures[dimension] = max(out.measures.get(dimension, 0.0), value)
    thread = _THREAD.search(normalised)
    if thread:
        out.thread = thread.group(1)
    out.identifiers = {m.group(0) for m in _IDENTIFIER.finditer(normalised)}
    return out


def _pretty(value: float) -> str:
    return f"{value:g}"


def looks_like_injection(text: Optional[str]) -> list[str]:
    """BR-AI-07. Document text is data, never instructions.

    The pipeline reads supplier files; a supplier file can contain a
    sentence aimed at whatever reads it. Nothing here *executes* text, so
    this is not a defence against execution — it is the flag that gets
    raised on the document and shown to the reviewer, so a file trying to
    talk to the machine is treated as suspicious rather than ordinary.
    """
    if not text:
        return []
    low = text.lower()
    hits: list[str] = []
    for pattern, label in (
        (r"ignore (all )?(the )?previous (instructions|prompts?)", "asks the reader to ignore its instructions"),
        (r"disregard (the )?(above|previous|prior)", "asks the reader to disregard earlier instructions"),
        (r"you are (now )?(an?|the) \w+", "tries to reassign the reader's role"),
        (r"system prompt|developer message", "refers to a system prompt"),
        (r"(auto[- ]?)?approve this (invoice|document|quotation)", "instructs that the document be approved"),
        (r"do not (show|tell|report) (this|the) (to )?(the )?(user|human|reviewer)", "asks to hide itself from a reviewer"),
    ):
        if re.search(pattern, low):
            hits.append(label)
    return hits
