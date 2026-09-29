"""
Mapping the columns that header synonyms could not.

Called by RFQ import (`procurement/rfq_import.py`) and by the document
pipeline's mapper (`mapping_service.py`) after their own synonym pass, with
only the fields and columns still unmatched. Three signals, cheapest and
most reliable first:

1. **What is in the column.** A column of "Pair, Nos, Box" is a unit column
   whatever its heading says; 1, 2, 3, 4 is a serial number; "20 Nos" is a
   quantity; long free text is a description. Deterministic, instant, and —
   measured on real RFQs — right far more often than either model.
2. **What the heading means**, by embedding similarity. Only used to choose
   between fields the values already allow: it tells "Count" (quantity)
   from "Budget" (price) when both columns hold numbers. On its own it is
   a weak signal (nomic-embed-text separates these headings by 0.01-0.07
   cosine), which is why it never overrides the values.
3. **A language model**, only while a *required* field is still missing,
   and every answer it gives is checked against the column's values before
   it is kept. A 3B local model swaps quantity and price, or picks the
   serial-number column as a rate; the check is what makes it usable.

Everything returned is a suggestion with its reason, shown to a person who
confirms it (BR-AI-09). No signal failing — Ollama stopped, a timeout, a
nonsense answer — ever fails the import; it just leaves the column for the
person, exactly as before this module existed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import statistics
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

from app.modules.ai import providers

log = logging.getLogger(__name__)

# ------------------------------------------------------------ value kinds

SERIAL = "serial"
NUMBER = "number"
QTY_WITH_UNIT = "qty_with_unit"
UNIT = "unit"
CODE = "code"
HSN = "hsn"
TEXT = "text"
DATE = "date"
EMPTY = "empty"

#: Unit spellings common on Indian paperwork. Callers with a tenant's own
#: unit list add theirs on top.
DEFAULT_UNIT_WORDS = frozenset(
    """nos no nr number numbers pc pcs piece pieces each ea unit units set sets pair pairs prs
    kg kgs kilo kilogram kilograms g gm gms gram grams mg ton tons tonne tonnes mt quintal qtl
    l ltr ltrs litre litres liter liters ml kl
    m mtr mtrs metre metres meter meters rmt cm mm ft feet rft inch inches km
    sqft sqm sq.ft sq.m sft cft cum
    box boxes bx pack packs pk pkt pkts packet packets bag bags roll rolls coil coils bundle bundles
    bottle bottles can cans drum drums carton cartons ctn jar jars tube tubes sheet sheets ream reams
    dozen doz dz lot lots job lumpsum ls kit kits""".split()
)

_NUMBER = re.compile(r"^[\s₹]*(?:rs\.?|inr)?\s*-?[0-9][0-9,]*(?:\.[0-9]+)?\s*(?:/-)?\s*$", re.IGNORECASE)
_QTY_UNIT = re.compile(r"^\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*([A-Za-z][A-Za-z .]{0,12})\s*$")
_DATE = re.compile(r"^\s*(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{4}-\d{2}-\d{2})\b")
_CODE = re.compile(r"^(?=.*\d)[A-Za-z0-9][A-Za-z0-9\-/._]{2,24}$")


def _num(value: str) -> Optional[float]:
    cleaned = re.sub(r"(?i)rs\.?|inr|₹|/-|,", "", value).strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


@dataclass
class Profile:
    kind: str
    avg_len: float = 0.0
    median: float = 0.0
    has_decimals: bool = False
    distinct_ratio: float = 0.0
    examples: list[str] = field(default_factory=list)
    #: Share of rows with anything in this column. Remarks are usually
    #: sparse; descriptions and quantities almost never are.
    fill: float = 1.0


def _is_unit_word(value: str, unit_words: frozenset[str]) -> bool:
    """`Nos`, `Kgs.`, `sq.ft` — but never `M-1001` or `1000 Nos`: a
    unit is letters only, so a digit anywhere rules it out."""
    v = value.strip().lower().rstrip('.')
    return bool(v) and not re.search(r'[0-9]', v) and v in unit_words


def profile(values: list[str], unit_words: frozenset[str]) -> Profile:
    fill = sum(1 for v in values if v is not None and str(v).strip()) / len(values) if values else 0.0
    p = _profile([str(v).strip() for v in values if v is not None and str(v).strip()], unit_words)
    p.fill = fill
    return p


def _profile(vals: list[str], unit_words: frozenset[str]) -> Profile:
    if not vals:
        return Profile(EMPTY)
    n = len(vals)
    examples = list(dict.fromkeys(vals))[:3]
    distinct = len(set(v.lower() for v in vals)) / n
    avg_len = sum(len(v) for v in vals) / n

    def share(pred) -> float:
        return sum(1 for v in vals if pred(v)) / n

    if share(lambda v: _DATE.match(v) is not None) >= 0.6:
        return Profile(DATE, avg_len, examples=examples)

    def is_unit(v: str) -> bool:
        return _is_unit_word(v, unit_words)

    if share(is_unit) >= 0.6 and avg_len <= 10:
        return Profile(UNIT, avg_len, distinct_ratio=distinct, examples=examples)

    if share(lambda v: bool(_QTY_UNIT.match(v)) and is_unit(_QTY_UNIT.match(v).group(2))) >= 0.6:
        return Profile(QTY_WITH_UNIT, avg_len, examples=examples)

    if share(lambda v: _NUMBER.match(v) is not None) >= 0.8:
        numbers = [x for x in (_num(v) for v in vals) if x is not None]
        ints = [x for x in numbers if float(x).is_integer()]
        has_decimals = len(ints) < len(numbers)
        if len(ints) == len(numbers) and len(numbers) >= 2:
            seq = [int(x) for x in numbers]
            if seq == list(range(seq[0], seq[0] + len(seq))) and seq[0] in (0, 1):
                return Profile(SERIAL, avg_len, examples=examples)
            if all(len(str(abs(x))) in (4, 6, 8) for x in seq) and all(
                v.replace(",", "").strip().isdigit() for v in vals
            ):
                return Profile(HSN, avg_len, median=statistics.median(numbers), examples=examples)
        return Profile(
            NUMBER,
            avg_len,
            median=statistics.median(numbers) if numbers else 0.0,
            has_decimals=has_decimals,
            distinct_ratio=distinct,
            examples=examples,
        )

    if share(lambda v: _CODE.match(v) is not None and " " not in v) >= 0.6:
        return Profile(CODE, avg_len, distinct_ratio=distinct, examples=examples)
    return Profile(TEXT, avg_len, distinct_ratio=distinct, examples=examples)


# --------------------------------------------------------------- fields


@dataclass(frozen=True)
class FieldSpec:
    """One target the caller still needs a column for.

    `role` is the generic meaning the value rules know about — the RFQ
    importer and the quotation pipeline name their fields differently
    (`description` / `product_description`) but mean the same thing."""

    key: str
    label: str
    role: str
    required: bool = False
    description: str = ""
    synonyms: tuple[str, ...] = ()


#: role -> value kinds a column may hold to be that role.
_COMPATIBLE: dict[str, set[str]] = {
    "description": {TEXT},
    "quantity": {NUMBER, QTY_WITH_UNIT},
    "uom": {UNIT},
    "price": {NUMBER},
    "amount": {NUMBER},
    "percent": {NUMBER},
    "item_code": {CODE, TEXT},
    "make": {TEXT},
    "hsn": {HSN, NUMBER, CODE},
    "remarks": {TEXT},
    "date": {DATE},
    "batch": {CODE, TEXT},
    "pack": {TEXT, NUMBER, QTY_WITH_UNIT},
}

#: role -> plain-language meaning, for embeddings and the LLM prompt.
_ROLE_TEXT = {
    "description": "the name or specification of the goods",
    "quantity": "how many units are required, a number",
    "uom": "the unit of measure the quantity is counted in, like Nos, Kg, Metre, Box",
    "price": "the rate or unit price in rupees",
    "amount": "a line total in rupees",
    "percent": "a percentage such as a GST or discount rate",
    "item_code": "a part number, SKU or material code",
    "make": "the preferred brand or manufacturer",
    "hsn": "the HSN/SAC GST tariff code",
    "remarks": "free-text notes or instructions",
    "date": "a date",
    "batch": "a batch or lot number",
    "pack": "the pack size",
}


@dataclass
class Suggestion:
    key: str
    column_index: int
    confidence: int  # 0-100
    source: str  # values | ai | llm
    reason: str


@dataclass
class AssistResult:
    suggestions: dict[str, Suggestion] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


_cache: "OrderedDict[str, AssistResult]" = OrderedDict()
_CACHE_MAX = 256
_field_vectors: dict[str, list[float]] = {}


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _field_text(spec: FieldSpec) -> str:
    also = f" Also written as {', '.join(spec.synonyms[:8])}." if spec.synonyms else ""
    return f"{spec.label}: {spec.description or _ROLE_TEXT.get(spec.role, '')}.{also}"


async def suggest(
    headers: list[str],
    rows: list[list[str]],
    specs: list[FieldSpec],
    *,
    taken_columns: set[int],
    unit_words: frozenset[str] = DEFAULT_UNIT_WORDS,
    use_models: bool = True,
) -> AssistResult:
    """Suggest a column for each of `specs` from the columns not in
    `taken_columns`. Never raises for a provider problem."""
    free = [i for i in range(len(headers)) if i not in taken_columns]
    if not specs or not free:
        return AssistResult()

    key = hashlib.sha256(
        json.dumps(
            [headers, rows[:8], [s.key for s in specs], sorted(taken_columns), use_models,
             providers.embeddings.configured, providers.llm.configured],
            default=str,
        ).encode()
    ).hexdigest()
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]

    result = AssistResult()
    # Every column is profiled, matched or not: "the numbers just before
    # the unit column" needs to know where the unit column is even when a
    # heading synonym already claimed it.
    column_values = {i: [r[i] if i < len(r) else "" for r in rows[:30]] for i in range(len(headers))}
    profiles = {i: profile(column_values[i], unit_words) for i in range(len(headers))}
    usable = [i for i in free if profiles[i].kind not in (EMPTY, SERIAL)]
    if not usable:
        return result

    # --- 1. value rules: a prior per (column, field)
    scores: dict[tuple[int, str], float] = {}
    reasons: dict[tuple[int, str], str] = {}
    #: (column, field) pairs whose win came from the heading's meaning.
    ai_boosted: set[tuple[int, str]] = set()
    text_cols = [i for i in usable if profiles[i].kind == TEXT]
    longest_text = max(text_cols, key=lambda i: (profiles[i].avg_len, profiles[i].distinct_ratio), default=None)
    unit_cols = [i for i in profiles if profiles[i].kind == UNIT]
    numeric = [i for i in usable if profiles[i].kind == NUMBER]
    # With a line-total field in play, the column of biggest numbers is the
    # total, not the rate.
    has_amount = any(sp.role == "amount" for sp in specs)

    for i in usable:
        p = profiles[i]
        eg = ", ".join(p.examples)
        for spec in specs:
            if p.kind not in _COMPATIBLE.get(spec.role, set()):
                continue
            s, why = 0.0, ""
            if spec.role == "uom" and p.kind == UNIT:
                s, why = 0.92, f"values are units ({eg})"
            elif spec.role == "quantity" and p.kind == QTY_WITH_UNIT:
                s, why = 0.92, f"values are quantities with units ({eg})"
            elif spec.role == "hsn" and p.kind == HSN:
                s, why = 0.85, f"values look like HSN codes ({eg})"
            elif spec.role == "description" and p.kind == TEXT:
                s = 0.5 + (0.35 if i == longest_text and p.avg_len >= 6 else 0.0)
                why = f"values are item names ({eg})"
            elif spec.role == "item_code" and p.kind == CODE:
                s, why = 0.72, f"values look like codes ({eg})"
            elif spec.role in ("quantity", "price", "amount", "percent") and p.kind == NUMBER:
                s, why = 0.45, f"values are numbers ({eg})"
                just_before_unit = any(u == i + 1 for u in unit_cols)
                just_after_unit = any(u == i - 1 for u in unit_cols)
                others = [profiles[j].median for j in numeric if j != i]
                if spec.role == "quantity":
                    if just_before_unit:
                        s, why = s + 0.3, f"numbers next to the unit column ({eg})"
                    if not p.has_decimals:
                        s += 0.05
                    if others and p.median < min(others):
                        s += 0.08
                elif spec.role == "price":
                    if just_after_unit:
                        s, why = s + 0.22, f"amounts after the unit column ({eg})"
                    if p.has_decimals:
                        s += 0.06
                    if others and p.median > max(others) and not has_amount:
                        s += 0.08
                elif spec.role == "amount":
                    if numeric and i == max(numeric):
                        s, why = s + 0.12, f"the last column of amounts ({eg})"
                    if others and p.median > max(others):
                        s += 0.08
                elif spec.role == "percent" and 0 <= p.median <= 100 and p.distinct_ratio < 0.6:
                    s += 0.1
            elif spec.role == "remarks" and p.kind == TEXT:
                s, why = 0.35 + (0.15 if p.fill < 0.85 else 0.0), f"notes such as {eg}"
            elif spec.role == "make" and p.kind == TEXT:
                s, why = 0.35 + (0.05 if p.avg_len <= 15 else 0.0), f"names such as {eg}"
            elif spec.role in ("batch", "pack") and p.kind in (TEXT, CODE, NUMBER, QTY_WITH_UNIT):
                s, why = 0.3, f"values: {eg}"
            if s:
                scores[(i, spec.key)] = s
                reasons[(i, spec.key)] = why

    # --- 2. heading meaning, as a tie-breaker between compatible fields
    if use_models and providers.embeddings.configured and scores:
        try:
            missing = [s for s in specs if _field_text(s) not in _field_vectors]
            if missing:
                vectors = await providers.embeddings.embed([_field_text(s) for s in missing], role="document")
                for s, v in zip(missing, vectors):
                    _field_vectors[_field_text(s)] = v
            cols = sorted({i for i, _k in scores})
            col_vectors = await providers.embeddings.embed(
                [f"spreadsheet column '{headers[i]}'" for i in cols], role="query"
            )
            by_key = {s.key: s for s in specs}
            for i, vec in zip(cols, col_vectors):
                compatible = [k for (c, k) in scores if c == i]
                sims = {k: _cos(vec, _field_vectors[_field_text(by_key[k])]) for k in compatible}
                if len(sims) < 2 and not headers[i].strip():
                    continue
                mean = sum(sims.values()) / len(sims)
                for k, sim in sims.items():
                    bonus = max(-0.2, min(0.25, 4.0 * (sim - mean) + (0.1 if sim >= 0.6 else 0.0)))
                    if abs(bonus) >= 0.02:
                        scores[(i, k)] += bonus
                        if bonus > 0.05:
                            reasons[(i, k)] = f"heading “{headers[i]}” reads like {by_key[k].label}"
                            ai_boosted.add((i, k))
        except (providers.ProviderError, providers.ProviderNotConfigured) as exc:
            log.warning("column assist: embeddings skipped: %s", exc)
            result.notes.append("The embedding model could not be reached, so headings were not read by meaning.")

    # --- assign, strongest first
    floor = {s.key: (0.55 if s.required or s.role in ("uom", "quantity", "price", "hsn", "item_code") else 0.62)
             for s in specs}
    used_cols: set[int] = set()
    for (i, k), s in sorted(scores.items(), key=lambda kv: -kv[1]):
        if k in result.suggestions or i in used_cols or s < floor[k]:
            continue
        used_cols.add(i)
        result.suggestions[k] = Suggestion(
            key=k,
            column_index=i,
            confidence=int(min(95, round(s * 100))),
            source="ai" if (i, k) in ai_boosted else "values",
            reason=reasons[(i, k)],
        )

    # --- 3. language model, only for required fields still missing
    still = [s for s in specs if s.required and s.key not in result.suggestions]
    remaining = [i for i in usable if i not in used_cols]
    if use_models and still and remaining and providers.llm.configured:
        await _ask_llm(headers, rows, still, remaining, profiles, result)

    _cache[key] = result
    if len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)
    return result


async def _ask_llm(
    headers: list[str],
    rows: list[list[str]],
    specs: list[FieldSpec],
    columns: list[int],
    profiles: dict[int, Profile],
    result: AssistResult,
) -> None:
    listing = "\n".join(
        f"{n + 1}. heading “{headers[i] or '(blank)'}”, sample values: "
        + ", ".join(v for v in ((r[i] if i < len(r) else "") for r in rows[:4]) if v)
        for n, i in enumerate(columns)
    )
    wanted = "\n".join(f"- {s.key}: {s.description or _ROLE_TEXT.get(s.role, s.label)}" for s in specs)
    user = (
        "These are columns from a purchase spreadsheet (a request for quotation or a supplier quote):\n"
        f"{listing}\n\nFor each field below, answer the number of the column that holds it, or null if none "
        f"does. Use each column at most once.\n{wanted}"
    )
    schema = {
        "type": "object",
        "properties": {s.key: {"type": ["integer", "null"]} for s in specs},
        "required": [s.key for s in specs],
    }
    try:
        answer = await providers.llm.complete_json(
            "You map spreadsheet columns to fields. Answer with JSON only.", user, schema
        )
    except (providers.ProviderError, providers.ProviderNotConfigured) as exc:
        log.warning("column assist: language model skipped: %s", exc)
        result.notes.append("The language model could not be reached; map the remaining columns by hand.")
        return

    taken = {s.column_index for s in result.suggestions.values()}
    for spec in specs:
        pick = answer.get(spec.key)
        if not isinstance(pick, int) or not 1 <= pick <= len(columns):
            continue
        i = columns[pick - 1]
        p = profiles[i]
        # The check that makes a small model usable: its choice must agree
        # with what is actually in the column.
        if i in taken or p.kind not in _COMPATIBLE.get(spec.role, set()):
            result.notes.append(
                f"The language model suggested “{headers[i]}” for {spec.label}, "
                "but its values don't fit — ignored."
            )
            continue
        taken.add(i)
        result.suggestions[spec.key] = Suggestion(
            key=spec.key,
            column_index=i,
            confidence=60,
            source="llm",
            reason=f"suggested by the language model; values: {', '.join(p.examples)}",
        )
