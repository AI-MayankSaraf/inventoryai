"""
Learning a supplier's layout once — `08_AI_DATA_MODEL.md` §5.

"This supplier's quotation always looks like this." The signature is a hash
of the normalised header row, so the same template next month is recognised
instantly and for free, and a supplier who changes their template gets a new
signature rather than silently corrupting the old mapping.

Two rules from the design that are easy to lose and are enforced here:

* **A mapping is only applied once a human has confirmed it** (BR-AI-09). A
  proposal is a suggestion on a screen, never a silent transformation of
  someone's purchase data.
* **Mappings target `canonical_fields.code`, never a physical column.**
  Renaming a column in a future migration cannot break a learned mapping.

With no LLM configured, proposals come from the canonical vocabulary's own
synonym lists plus trigram similarity. That resolves the ordinary headers
("Rate", "Qty", "HSN") outright and leaves the unusual ones unmapped for a
person — which is the same place an unconfirmed LLM proposal would land.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.normalise import normalise
from app.modules.ai.parsing import ParsedTable

#: Below this a synonym/trigram guess is not worth showing; the column is
#: left unmapped and the reviewer chooses.
_PROPOSAL_FLOOR = 0.55


@dataclass
class ColumnProposal:
    source_column: str
    source_column_index: int
    canonical_field_id: Optional[UUID]
    canonical_code: Optional[str]
    confidence: float
    reason: str


@dataclass
class MappingOutcome:
    mapping_id: UUID
    status: str
    created: bool
    confidence: float
    #: canonical code → column index, for whichever fields are mapped.
    columns: dict[str, int]
    trace: list[str]


async def load_canonical_fields(session: AsyncSession) -> list[dict]:
    rows = (
        await session.execute(
            text(
                "SELECT id, code, label, field_group, data_type, is_required, "
                "COALESCE(synonyms, ARRAY[]::text[]) AS synonyms "
                "FROM canonical_fields ORDER BY field_group, code"
            )
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def propose_columns(table: ParsedTable, canonical: list[dict]) -> list[ColumnProposal]:
    """Header text → canonical field, by exact code, then synonym, then
    containment. Each canonical field is claimed at most once: two columns
    both called "Amount" cannot both be `line_total`."""
    line_fields = [c for c in canonical if c["field_group"] == "line"]
    taken: set[str] = set()
    proposals: list[ColumnProposal] = []

    scored: list[tuple[float, int, dict, str]] = []
    for index, header in enumerate(table.headers):
        normalised = normalise(header)
        if not normalised:
            continue
        for field in line_fields:
            score, reason = _score(normalised, field)
            if score >= _PROPOSAL_FLOOR:
                scored.append((score, index, field, reason))

    # Best matches claim their column and their field first, so a strong
    # "Rate" → unit_price is not displaced by a weak "Rate" → gst_rate.
    used_columns: set[int] = set()
    for score, index, field, reason in sorted(scored, key=lambda s: -s[0]):
        if index in used_columns or field["code"] in taken:
            continue
        used_columns.add(index)
        taken.add(field["code"])
        proposals.append(
            ColumnProposal(
                source_column=table.headers[index],
                source_column_index=index,
                canonical_field_id=field["id"],
                canonical_code=field["code"],
                confidence=round(score * 100, 2),
                reason=reason,
            )
        )

    for index, header in enumerate(table.headers):
        if index not in used_columns and header.strip():
            proposals.append(
                ColumnProposal(
                    source_column=header,
                    source_column_index=index,
                    canonical_field_id=None,
                    canonical_code=None,
                    confidence=0.0,
                    reason="No canonical field recognised — choose one or leave the column out",
                )
            )
    return sorted(proposals, key=lambda p: p.source_column_index)


#: canonical code -> the generic role `column_assist` reads values for.
_ASSIST_ROLE = {
    "product_description": "description",
    "quantity": "quantity",
    "uom": "uom",
    "unit_price": "price",
    "line_total": "amount",
    "discount_amount": "amount",
    "gst_rate": "percent",
    "discount_pct": "percent",
    "cess_rate": "percent",
    "supplier_sku": "item_code",
    "model": "item_code",
    "brand": "make",
    "hsn_code": "hsn",
    "batch_number": "batch",
    "expiry_date": "date",
    "pack_size": "pack",
    "remarks": "remarks",
}


async def assist_proposals(proposals: list[ColumnProposal], table: ParsedTable, canonical: list[dict]) -> list[str]:
    """Fill the columns the synonym pass left unmapped from their values,
    their headings' meaning and, for a required field still missing, a
    language model (`column_assist.py`). Updates `proposals` in place and
    returns trace notes. A proposal stays a proposal — a person confirms
    it on the review screen (BR-AI-09)."""
    from app.modules.ai import column_assist

    taken_codes = {p.canonical_code for p in proposals if p.canonical_code}
    fields = {
        f["code"]: f
        for f in canonical
        if f["field_group"] == "line" and f["code"] in _ASSIST_ROLE and f["code"] not in taken_codes
    }
    free = [p for p in proposals if p.canonical_field_id is None]
    if not fields or not free:
        return []
    specs = [
        column_assist.FieldSpec(
            key=code,
            label=f["label"],
            role=_ASSIST_ROLE[code],
            required=code in ("product_description", "quantity"),
            synonyms=tuple(f["synonyms"] or ()),
        )
        for code, f in fields.items()
    ]
    taken_columns = {p.source_column_index for p in proposals if p.canonical_field_id}
    try:
        result = await column_assist.suggest(table.headers, table.rows[:30], specs, taken_columns=taken_columns)
    except Exception:  # an optional helper never fails a document
        import logging

        logging.getLogger(__name__).exception("column assist failed")
        return []
    by_index = {p.source_column_index: p for p in free}
    labels = {"values": "Read from the column's values", "ai": "Suggested by AI", "llm": "Suggested by the language model"}
    filled = 0
    for code, sug in result.suggestions.items():
        proposal = by_index.get(sug.column_index)
        if proposal is None:
            continue
        proposal.canonical_field_id = fields[code]["id"]
        proposal.canonical_code = code
        proposal.confidence = float(sug.confidence)
        proposal.reason = f"{labels.get(sug.source, 'Suggested')}: {sug.reason}"
        filled += 1
    notes = list(result.notes)
    if filled:
        notes.insert(0, f"{filled} more column(s) suggested from their values and headings — check them before confirming.")
    return notes


def _score(normalised_header: str, field: dict) -> tuple[float, str]:
    code_words = normalise(field["code"].replace("_", " "))
    label = normalise(field["label"])
    if normalised_header in {code_words, label}:
        return 1.0, f"Header is exactly \"{field['label']}\""
    synonyms = [normalise(s) for s in (field["synonyms"] or [])]
    if normalised_header in synonyms:
        return 0.95, f"\"{normalised_header}\" is a known way of writing {field['label']}"
    for synonym in synonyms:
        if not synonym:
            continue
        if normalised_header.startswith(synonym) or normalised_header.endswith(synonym):
            return 0.8, f"Header starts or ends with \"{synonym}\""
        if synonym in normalised_header.split():
            return 0.72, f"Header contains the word \"{synonym}\""
    if code_words and code_words in normalised_header:
        return 0.7, f"Header contains \"{code_words}\""
    return 0.0, ""


async def resolve_mapping(
    session: AsyncSession,
    *,
    company_id: str,
    supplier_id: Optional[UUID],
    document_type: str,
    table: ParsedTable,
    document_id: UUID,
    canonical: list[dict],
) -> MappingOutcome:
    """Find a confirmed mapping for this layout, or propose one.

    The lookup deliberately tries the supplier-specific mapping first and a
    supplier-agnostic one second: the same rate-card template is often
    resold by several distributors, and a layout learned once should not
    have to be relearned per supplier.
    """
    signature = table.column_signature
    trace: list[str] = []

    existing = (
        await session.execute(
            text(
                "SELECT id, status, confidence, supplier_id FROM document_schema_mappings "
                "WHERE company_id = :c AND document_type = :t AND column_signature = :s "
                "  AND status = 'confirmed' "
                "ORDER BY (supplier_id IS NOT DISTINCT FROM :sup) DESC, version DESC LIMIT 1"
            ),
            {"c": company_id, "t": document_type, "s": signature, "sup": supplier_id},
        )
    ).mappings().first()

    if existing:
        await session.execute(
            text(
                "UPDATE document_schema_mappings SET usage_count = usage_count + 1, last_used_at = now() "
                "WHERE id = :id"
            ),
            {"id": existing["id"]},
        )
        columns = await mapped_columns(session, existing["id"])
        trace.append("Applied a column mapping this supplier's layout already had.")
        return MappingOutcome(
            mapping_id=existing["id"],
            status="confirmed",
            created=False,
            confidence=float(existing["confidence"] or 100),
            columns=columns,
            trace=trace,
        )

    # Is there already a proposal for this exact layout, from a previous
    # upload nobody has confirmed yet? Re-proposing would violate the
    # unique key and give the reviewer two identical screens.
    proposed = (
        await session.execute(
            text(
                "SELECT id, confidence FROM document_schema_mappings "
                "WHERE company_id = :c AND document_type = :t AND column_signature = :s "
                "  AND supplier_id IS NOT DISTINCT FROM :sup AND status = 'proposed' "
                "ORDER BY version DESC LIMIT 1"
            ),
            {"c": company_id, "t": document_type, "s": signature, "sup": supplier_id},
        )
    ).mappings().first()
    if proposed:
        trace.append("This layout is already waiting to be confirmed; reused that proposal.")
        return MappingOutcome(
            mapping_id=proposed["id"],
            status="proposed",
            created=False,
            confidence=float(proposed["confidence"] or 0),
            columns=await mapped_columns(session, proposed["id"]),
            trace=trace,
        )

    proposals = propose_columns(table, canonical)
    trace.extend(await assist_proposals(proposals, table, canonical))
    matched = [p for p in proposals if p.canonical_field_id]
    confidence = round(sum(p.confidence for p in matched) / len(proposals), 2) if proposals else 0.0

    # §5 step 8: a retired mapping is *relearned* as version + 1, not
    # replaced. `uq_schema_mapping` includes the version for exactly this
    # reason, and without the bump a supplier who changes their template and
    # then changes it back collides with their own deprecated layout.
    version = (
        await session.execute(
            text(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM document_schema_mappings "
                "WHERE company_id = :c AND supplier_id IS NOT DISTINCT FROM :sup "
                "  AND document_type = :t AND column_signature = :s"
            ),
            {"c": company_id, "sup": supplier_id, "t": document_type, "s": signature},
        )
    ).scalar_one()
    if version > 1:
        trace.append(f"This layout was seen before and retired; learning it again as version {version}.")

    mapping_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO document_schema_mappings (id, company_id, supplier_id, document_type, file_format, "
            " mapping_name, column_signature, header_row_index, data_start_row, sheet_name, "
            " sample_document_id, status, confidence, version) "
            "VALUES (:id, :c, :sup, :t, :fmt, :name, :sig, :hdr, :start, :sheet, :doc, 'proposed', :conf, :ver)"
        ),
        {
            "id": mapping_id,
            "c": company_id,
            "sup": supplier_id,
            "t": document_type,
            "fmt": _file_format(table),
            "name": f"{table.sheet_name} layout",
            "sig": signature,
            "hdr": table.header_row_index,
            "start": table.data_start_row,
            "sheet": table.sheet_name,
            "doc": document_id,
            "conf": confidence,
            "ver": version,
        },
    )
    for proposal in proposals:
        if proposal.canonical_field_id is None:
            continue
        await session.execute(
            text(
                "INSERT INTO document_schema_mapping_fields (id, mapping_id, source_column, source_column_index, "
                " canonical_field_id, transform, is_required, confidence) "
                "VALUES (:id, :m, :col, :idx, :cf, 'none', false, :conf)"
            ),
            {
                "id": uuid4(),
                "m": mapping_id,
                "col": proposal.source_column,
                "idx": proposal.source_column_index,
                "cf": proposal.canonical_field_id,
                "conf": proposal.confidence,
            },
        )
    trace.append(
        f"New layout: proposed {len(matched)} of {len(proposals)} columns from the field vocabulary. "
        "Confirm the mapping to reuse it automatically next time."
    )
    return MappingOutcome(
        mapping_id=mapping_id,
        status="proposed",
        created=True,
        confidence=confidence,
        columns={p.canonical_code: p.source_column_index for p in matched if p.canonical_code},
        trace=trace,
    )


def _file_format(table: ParsedTable) -> str:
    if table.sheet_name.startswith("page "):
        return "pdf_table"
    if table.sheet_name == "csv":
        return "csv"
    if table.sheet_name.startswith("table "):
        return "docx"
    return "xlsx"


async def mapped_columns(session: AsyncSession, mapping_id: UUID) -> dict[str, int]:
    rows = (
        await session.execute(
            text(
                "SELECT cf.code, f.source_column_index FROM document_schema_mapping_fields f "
                "JOIN canonical_fields cf ON cf.id = f.canonical_field_id "
                "WHERE f.mapping_id = :m AND f.source_column_index IS NOT NULL"
            ),
            {"m": mapping_id},
        )
    ).mappings().all()
    return {r["code"]: r["source_column_index"] for r in rows}
