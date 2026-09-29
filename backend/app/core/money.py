"""
Money and tax — 06_BUSINESS_RULES.md §10, "the canonical formula".

    BR-TAX-10: "A client-supplied total is ignored; the server recomputes
    and returns its own."

So every document that carries money (RFQ estimated_value, PO, GRN costing,
and later proforma/invoice) computes through the functions here rather than
trusting whatever arrived in the request body. One place, one formula, per
BR-PO-01's complaint about the prototype: "two divergent formulas exist".

BR-TAX-08 is the reason every amount in this module is `Decimal`, never
`float`: floats cannot represent 0.1 exactly, and a purchase order is a
legal, GST-relevant document. All arithmetic here mirrors what Postgres's
`NUMERIC` columns store, so a value written by `line_totals()` and a value
read back from `purchase_order_items` are the same Decimal.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Iterable, Optional

TWO_PLACES = Decimal("0.01")


def D(value) -> Decimal:
    """Coerce anything JSON/Pydantic handed us (str, float, int, None) into
    a Decimal, the only type allowed past this module's boundary."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round2(value: Decimal) -> Decimal:
    """BR-TAX-09: rounding happens at line level, always to 2 places
    (Money's own precision), always half-up — the one place a nearest-paisa
    decision gets made, so every line and every total go through it."""
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def round_total(value: Decimal, rounding_mode: str) -> Decimal:
    """BR-TAX-07: the grand total's own rounding, which — unlike line
    rounding — is configurable per tenant (`company_settings.rounding_mode`)
    because invoice-total rounding conventions vary by business."""
    mode = {"up": ROUND_CEILING, "down": ROUND_FLOOR}.get(rounding_mode, ROUND_HALF_UP)
    return value.quantize(Decimal("1"), rounding=mode)


@dataclass
class LineAmounts:
    line_net: Decimal
    line_tax: Decimal
    line_cess: Decimal
    line_total: Decimal


def line_amounts(
    *, quantity: Decimal, unit_price: Decimal, discount_pct: Decimal, gst_rate: Decimal, cess_rate: Decimal
) -> LineAmounts:
    """BR-TAX-01..03 for one line."""
    gross = quantity * unit_price
    discount = round2(gross * discount_pct / Decimal(100))
    line_net = round2(gross) - discount
    line_tax = round2(line_net * gst_rate / Decimal(100))
    line_cess = round2(line_net * cess_rate / Decimal(100))
    line_total = line_net + line_tax + line_cess
    return LineAmounts(line_net=line_net, line_tax=line_tax, line_cess=line_cess, line_total=line_total)


@dataclass
class DocumentTotals:
    subtotal: Decimal
    discount_amount: Decimal
    taxable_value: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    cess_amount: Decimal
    freight_amount: Decimal
    other_charges: Decimal
    round_off: Decimal
    total_amount: Decimal


def document_totals(
    *,
    lines: Iterable[LineAmounts],
    gross_lines: Iterable[Decimal],
    is_inter_state: bool,
    freight_amount: Decimal = Decimal("0"),
    other_charges: Decimal = Decimal("0"),
    rounding_mode: str = "nearest",
) -> DocumentTotals:
    """BR-TAX-04..07 aggregated across every line.

    `gross_lines` (quantity x unit_price, pre-discount, per line) is taken
    separately from `lines` rather than derived, because `subtotal` on the
    document is defined as the pre-discount figure the UI has always shown,
    while `taxable_value` is the post-discount one BR-TAX-04 defines as
    Σ line_net — the two are deliberately different numbers.
    """
    lines = list(lines)
    subtotal = round2(sum(gross_lines, Decimal("0")))
    taxable_value = round2(sum((l.line_net for l in lines), Decimal("0")))
    discount_amount = round2(subtotal - taxable_value)
    tax_total = round2(sum((l.line_tax for l in lines), Decimal("0")))
    cess_amount = round2(sum((l.line_cess for l in lines), Decimal("0")))

    if is_inter_state:
        igst_amount = tax_total
        cgst_amount = Decimal("0")
        sgst_amount = Decimal("0")
    else:
        # BR-TAX-05: split in half, remainder (a stray paisa from an odd
        # total) goes to CGST.
        half = (tax_total / Decimal(2)).quantize(TWO_PLACES, rounding=ROUND_FLOOR)
        cgst_amount = tax_total - half
        sgst_amount = half
        igst_amount = Decimal("0")

    freight_amount = round2(freight_amount)
    other_charges = round2(other_charges)

    total_before_round = taxable_value + tax_total + cess_amount + freight_amount + other_charges
    total_amount = round_total(total_before_round, rounding_mode)
    round_off = round2(total_amount - total_before_round)

    return DocumentTotals(
        subtotal=subtotal,
        discount_amount=discount_amount,
        taxable_value=taxable_value,
        cgst_amount=cgst_amount,
        sgst_amount=sgst_amount,
        igst_amount=igst_amount,
        cess_amount=cess_amount,
        freight_amount=freight_amount,
        other_charges=other_charges,
        round_off=round_off,
        total_amount=total_amount,
    )


def is_inter_state(supplier_state_code: Optional[str], godown_state_code: Optional[str]) -> bool:
    """BR-PO-06: computed from supplier state vs delivery-godown state, and
    frozen on the document at creation. Unknown state on either side is
    treated as intra-state (the conservative default the existing intra-
    state CHECK constraints assume) rather than guessing IGST on missing
    data — callers should require both fields before approval regardless
    (BR-PO-02 already demands the supplier be GST-configured)."""
    if not supplier_state_code or not godown_state_code:
        return False
    return supplier_state_code.strip().upper() != godown_state_code.strip().upper()
