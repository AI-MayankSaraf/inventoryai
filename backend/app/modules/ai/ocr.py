"""
OCR for scanned quotations, proformas and invoices — Tesseract, run locally.

Reading the words is the easy half. The pipeline downstream wants what a
spreadsheet gives it: a grid of rows and columns, so the same column
mapping and product matching can run on a scan as on an Excel file. This
module rebuilds that grid from where each word sits on the page:

1. Render each page (PDFs via pdfium, no Poppler needed) at 300 dpi.
2. Erase table borders, then ask Tesseract for every word *with its box*
   (`image_to_data`, sparse-text mode).
3. Group words into visual rows by their vertical centre.
4. Split each row into cells wherever the horizontal gap is wider than a
   couple of spaces — that's where one column ends and the next begins.
5. Find the heading row (the parser's own header detection, fed the
   caller's vocabulary hints), take each heading cell's horizontal span as
   a column, and drop every later cell into the column it overlaps — so a
   blank "Make" cell doesn't shift "Remarks" one column left.

What comes out is a best effort, and it is treated as one: an OCR'd
extraction always lands on the review screen, where every value can be
checked against the page before anything is approved.
"""

from __future__ import annotations

import io
import os
import statistics
from dataclasses import dataclass, field
from typing import Optional

from app.core.config import get_settings

_DPI = 300


@dataclass
class OcrPage:
    text: str
    #: Naive grid: each visual row split into cells, not yet aligned.
    rows: list[list[tuple[str, float, float]]] = field(default_factory=list)


class OcrUnavailable(RuntimeError):
    pass


def _tesseract():
    import pytesseract

    s = get_settings()
    if s.ocr_tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = s.ocr_tesseract_cmd
    return pytesseract


def available() -> tuple[bool, str]:
    """(usable, why not). Checked when the provider reports its status, so
    the screen can say "OCR is on" only when it actually works."""
    if get_settings().ocr_provider != "tesseract":
        return False, "OCR_PROVIDER is not 'tesseract'"
    try:
        _tesseract().get_tesseract_version()
    except Exception as exc:  # binary missing, not executable, …
        return False, f"Tesseract is not installed or not found ({exc.__class__.__name__})"
    return True, ""


def _config() -> str:
    s = get_settings()
    if s.ocr_tessdata_dir:
        # Tesseract's own variable, not `--tessdata-dir`: on Windows
        # pytesseract passes quote marks through literally, and a quoted
        # path is then "not found".
        os.environ["TESSDATA_PREFIX"] = s.ocr_tessdata_dir
    # Sparse text: every word with its box, no reading order assumed. Rows
    # and columns are rebuilt here from the boxes, so Tesseract's own layout
    # analysis only gets in the way — `--psm 4` (one column) merged "Sr No"
    # into "Item Description" and read almost nothing from a boxed template.
    return "--psm 11 -c preserve_interword_spaces=1"


def _images(blob: bytes, mime_type: str):
    from PIL import Image

    if mime_type == "application/pdf":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(blob)
        try:
            for index in range(min(len(pdf), get_settings().ocr_max_pages)):
                page = pdf[index]
                yield page.render(scale=_DPI / 72).to_pil()
        finally:
            pdf.close()
        return
    image = Image.open(io.BytesIO(blob))
    image.load()
    # Phone photos are often small; Tesseract wants text ~30px high.
    if image.width < 1600:
        factor = 1600 / image.width
        image = image.resize((int(image.width * factor), int(image.height * factor)))
    yield image


def _erase_rules(gray):
    """Paint table borders white.

    Tesseract reads a bordered table well while the rules are a pixel or
    two wide and falls apart once they are three or more — a boxed
    quotation scanned at 300 dpi went from 30 of 30 cells to 2. Rules are
    found as long unbroken runs of near-black pixels: far longer than any
    letter's stroke, so the text itself survives. Pillow only, scanning
    each row's bytes, so it costs milliseconds, not a NumPy dependency.
    """
    import re

    from PIL import Image, ImageDraw

    dark = gray.point(lambda p: 0 if p < 110 else 255)
    cleaned = gray.copy()
    draw = ImageDraw.Draw(cleaned)
    for transposed in (False, True):
        source = dark.transpose(Image.Transpose.TRANSPOSE) if transposed else dark
        width, height = source.size
        # Horizontal rules span at least a column; vertical ones at least a
        # couple of table rows. Both are far past a letter's height.
        run = re.compile(rb"\x00{%d,}" % max(60, (width // 12) if not transposed else (width // 30)))
        data = source.tobytes()
        for y in range(height):
            for match in run.finditer(data, y * width, (y + 1) * width):
                x0, x1 = match.start() - y * width, match.end() - y * width - 1
                draw.line((y, x0, y, x1) if transposed else (x0, y, x1, y), fill=255)
    return cleaned


def _page(image) -> OcrPage:
    from PIL import ImageFilter, ImageOps

    pytesseract = _tesseract()
    # Stretch contrast and sharpen: a faint or slightly blurred scan loses
    # digits otherwise (a "5" came back as "(3)" in testing without this).
    gray = ImageOps.autocontrast(image.convert("L"))
    gray = _erase_rules(gray).filter(ImageFilter.SHARPEN)
    data = pytesseract.image_to_data(
        gray, lang=get_settings().ocr_languages, config=_config(), output_type=pytesseract.Output.DICT
    )
    words = []
    for i, raw in enumerate(data["text"]):
        text = (raw or "").strip()
        if not text or float(data["conf"][i]) < 0:
            continue
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        words.append({"text": text, "x0": x, "x1": x + w, "yc": y + h / 2, "h": h})
    if not words:
        return OcrPage(text="")

    median_h = statistics.median(w["h"] for w in words) or 10
    # Rows: words whose vertical centres sit within half a line of each other.
    words.sort(key=lambda w: w["yc"])
    lines: list[list[dict]] = []
    for word in words:
        if lines and abs(word["yc"] - statistics.mean(x["yc"] for x in lines[-1])) <= median_h * 0.6:
            lines[-1].append(word)
        else:
            lines.append([word])

    rows: list[list[tuple[str, float, float]]] = []
    text_lines: list[str] = []
    for line in lines:
        line.sort(key=lambda w: w["x0"])
        cells: list[list[dict]] = [[line[0]]]
        for prev, word in zip(line, line[1:]):
            # A normal space is ~0.3 of the text height; a column gap is
            # several times that.
            if word["x0"] - prev["x1"] > median_h * 1.2:
                cells.append([word])
            else:
                cells[-1].append(word)
        row = [(" ".join(w["text"] for w in c), c[0]["x0"], c[-1]["x1"]) for c in cells]
        rows.append(row)
        # One text line per cell: "Quotation No: Q-17" and "Date: 29/09" printed
        # far apart on one line are two facts, and the header-field reader
        # takes a value up to the end of its line.
        text_lines.extend(r[0] for r in row)
    return OcrPage(text="\n".join(text_lines), rows=rows)


def _align(rows: list[list[tuple[str, float, float]]], header_index: int) -> list[list[str]]:
    """Lay the rows from the heading down onto the heading's columns."""
    header = rows[header_index]
    spans = [(x0, x1) for _t, x0, x1 in header]
    grid = [[t for t, _a, _b in header]]
    for row in rows[header_index + 1:]:
        out = [""] * len(spans)
        for text, x0, x1 in row:
            centre = (x0 + x1) / 2

            def score(i: int) -> float:
                a, b = spans[i]
                overlap = max(0.0, min(x1, b) - max(x0, a))
                # Overlap wins; otherwise the nearest column by centre.
                return overlap * 10 - abs(centre - (a + b) / 2)

            best = max(range(len(spans)), key=score)
            out[best] = f"{out[best]} {text}".strip()
        grid.append(out)
    return grid


def read(blob: bytes, mime_type: str, hints: Optional[set[str]] = None) -> tuple[str, list[tuple[str, list[list[str]]]]]:
    """(full text, [(sheet name, grid)]) for every page that has a table."""
    from app.modules.ai.parsing import _find_header_row, _hinted_header_row

    ok, why = available()
    if not ok:
        raise OcrUnavailable(why)
    texts: list[str] = []
    grids: list[tuple[str, list[list[str]]]] = []
    for number, image in enumerate(_images(blob, mime_type), start=1):
        page = _page(image)
        texts.append(page.text)
        naive = [[t for t, _a, _b in r] for r in page.rows]
        if sum(1 for r in naive if len(r) >= 3) < 2:
            continue  # no table on this page
        if hints:
            # A spreadsheet's first wordy row is a fair guess at its heading;
            # on a scan it is as likely to be speckle from a patterned
            # border read as "ee | ee | ee". Only a row that names real
            # columns counts — otherwise the page has no table we trust.
            header_index = _hinted_header_row(naive, hints, limit=len(naive))
            if header_index is None:
                continue
        else:
            header_index = _find_header_row(naive, hints)
        if len(page.rows[header_index]) < 2:
            continue
        grids.append((f"page {number}", _align(page.rows, header_index)))
    return "\n\n".join(texts), grids

