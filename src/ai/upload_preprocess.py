"""
upload_preprocess.py

What is sent to the model for one statement PDF (2026-10-12): a small,
testable step in front of ClaudeSonnetClient's request. The ORIGINAL PDF is
never modified -- document_hash, the blob archive and the duplicate check all
stay on the original file; only the bytes sent to the model may differ.

Three paths, logged by name:

  as_is       the original bytes, in one request -- every PDF up to
              MAX_REQUEST_PDF_BYTES and MAX_PAGES_PER_REQUEST (16) pages
              (unchanged behaviour for every file that worked before);
  split       consecutive page ranges copied LOSSLESSLY, each its own
              request, each at most MAX_REQUEST_PDF_BYTES and
              MAX_PAGES_PER_REQUEST pages (an oversized range is halved,
              down to one page). Rows are merged in page order
              (merge_chunk_results); ANY part failing fails the whole
              statement -- never a silent partial;
  compressed  only a single page that is too big on its own is re-rendered
              as a grayscale JPEG (REDUCTION_STEPS), and only if the
              legibility gate passes: Tesseract must still read the
              original page's numeric tokens on the reduced page
              (LEGIBILITY_MIN_RECALL).

Why lossless splitting comes first (measured 2026-10-12 on Fred Beans-
Rockland.pdf, nine 600 dpi page scans): every re-render lost digits -- OCR
numeric-token recall 0.91 at 300 dpi q90, 0.82-0.89 at 200/150/110 dpi --
while two lossless page ranges (12.1 MB + 15.4 MB) fit the limit with
nothing lost. Splitting costs only the repeated prompt per request.

A page that cannot be brought under the limit without losing digits raises
UploadTooLarge: the statement fails visibly instead of being sent as-is and
rejected (2026-10-01: Fred Beans- Rockland.pdf, 27.5 MB, HTTP 400).

Limits come from the repo, not guesses: the request limit noted in
scratchpad/oct1_report/oct1_root_cause_analysis.md (32 MB request; a
27,497,367-byte PDF is ~36.7 MB once base64-encoded) and the 20 MiB raw
ceiling ClaudeSonnetClient already used (base64 of 20 MiB is ~26.7 MB).
"""

import io
import logging
import math
from dataclasses import dataclass, field
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

MAX_REQUEST_PDF_BYTES = 20 * 1024 * 1024
# Largest page count that went through in one request on 2026-10-01: 16
# (9-4-26 NYE.pdf, 165 rows); smallest that did not: 17 (customerinvoice
# (15).pdf, ~416 rows, read timeout). Above this many pages a statement is
# split up front, so nothing that worked before changes path; a response
# that is cut off at any size is re-split anyway (stop_reason max_tokens).
MAX_PAGES_PER_REQUEST = 16
# (dpi, JPEG quality) for the compressed path, tried in order.
REDUCTION_STEPS = ((200, 80), (150, 80))
# Share of the original page's numeric tokens (OCR at LEGIBILITY_DPI) that
# must be read back from the reduced page. Below it the reduction is refused.
LEGIBILITY_MIN_RECALL = 0.98
LEGIBILITY_DPI = 300


class UploadTooLarge(Exception):
    """A page cannot be sent within MAX_REQUEST_PDF_BYTES without losing
    legibility -- the statement fails visibly."""


@dataclass
class UploadPart:
    data: bytes
    first_page: int   # 1-based, inclusive
    last_page: int
    reduced: bool = False


@dataclass
class UploadPlan:
    path: str                              # "as_is" | "compressed" | "split"
    parts: List[UploadPart]
    original_bytes: int
    pages: int
    notes: List[str] = field(default_factory=list)

    def describe(self) -> str:
        sizes = ", ".join(f"p{p.first_page}-{p.last_page} {len(p.data):,} B{' reduced' if p.reduced else ''}"
                          for p in self.parts)
        return f"{self.path}: {self.pages} page(s), original {self.original_bytes:,} B -> {sizes}"


def _fitz():
    try:
        import pymupdf
    except ImportError:  # older PyMuPDF only exposes the fitz name
        import fitz as pymupdf
    return pymupdf


def page_range_bytes(source_bytes: bytes, first_page: int, last_page: int) -> bytes:
    """A lossless copy of pages first_page..last_page (1-based, inclusive)."""
    pymupdf = _fitz()
    with pymupdf.open(stream=source_bytes, filetype="pdf") as src, pymupdf.open() as out:
        out.insert_pdf(src, from_page=first_page - 1, to_page=last_page - 1)
        return out.tobytes(garbage=3, deflate=True)


def reduce_pdf(source_bytes: bytes, dpi: int, quality: int) -> bytes:
    """Every page re-rendered as a grayscale JPEG at `dpi`, same page size."""
    pymupdf = _fitz()
    with pymupdf.open(stream=source_bytes, filetype="pdf") as src, pymupdf.open() as out:
        for page in src:
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
            new_page = out.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(new_page.rect, stream=pix.tobytes("jpeg", jpg_quality=quality))
        return out.tobytes(garbage=3, deflate=True)


def _numeric_tokens(pdf_bytes: bytes) -> List[List[str]]:
    """Per page, the OCR tokens that carry digits (amounts, dates, invoice
    numbers), normalised -- what a reduction must not lose."""
    import re
    import pytesseract
    from PIL import Image
    from src.ai.ocr_extractor import _configure_tesseract_path

    _configure_tesseract_path(pytesseract)
    pymupdf = _fitz()
    pages = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=LEGIBILITY_DPI)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            text = pytesseract.image_to_string(image, config="--psm 6")
            tokens = [re.sub(r"[^0-9.,/\-]", "", t) for t in text.split()]
            pages.append([t for t in tokens if sum(ch.isdigit() for ch in t) >= 2])
    return pages


def legibility_check(original: bytes, reduced: bytes) -> dict:
    """{"ok": bool, "recall": float, "pages": [...]}. Recall is the share of
    the original's numeric tokens (multiset, per page) also read on the
    reduced page. A page with no numeric tokens has nothing to lose. If OCR
    is unavailable the check fails closed (ok False)."""
    from collections import Counter
    try:
        before, after = _numeric_tokens(original), _numeric_tokens(reduced)
    except Exception as e:  # Tesseract missing, unreadable page, ...
        return {"ok": False, "recall": 0.0, "reason": f"legibility gate unavailable ({type(e).__name__}: {e})"}
    if len(before) != len(after):
        return {"ok": False, "recall": 0.0, "reason": "page count changed"}
    pages, kept_total, orig_total = [], 0, 0
    for i, (b, a) in enumerate(zip(before, after), start=1):
        kept = sum((Counter(b) & Counter(a)).values())
        pages.append({"page": i, "original_tokens": len(b), "kept": kept})
        kept_total += kept
        orig_total += len(b)
    recall = kept_total / orig_total if orig_total else 1.0
    return {"ok": recall >= LEGIBILITY_MIN_RECALL, "recall": round(recall, 4), "pages": pages}


def _reduce_with_gate(data: bytes, max_bytes: int, gate: Callable, notes: list, label: str) -> Optional[bytes]:
    for dpi, quality in REDUCTION_STEPS:
        reduced = reduce_pdf(data, dpi, quality)
        if len(reduced) > max_bytes:
            notes.append(f"{label}: {dpi} dpi grayscale JPEG q{quality} is {len(reduced):,} B, still over the limit")
            continue
        verdict = gate(data, reduced)
        if verdict["ok"]:
            notes.append(f"{label}: {dpi} dpi grayscale JPEG q{quality} = {len(reduced):,} B, "
                         f"legibility recall {verdict.get('recall')}")
            return reduced
        notes.append(f"{label}: {dpi} dpi reduction refused -- legibility recall {verdict.get('recall')} "
                     f"< {LEGIBILITY_MIN_RECALL} ({verdict.get('reason', 'digits lost')})")
    return None


def _split(data: bytes, first: int, last: int, max_bytes: int, max_pages: int, gate: Callable,
           notes: list) -> List[UploadPart]:
    """Consecutive ranges of at most max_pages pages, each under max_bytes,
    copied losslessly: an oversized range is halved, down to one page; only
    a single page that is too big on its own is reduced, under the gate,
    and if that is refused UploadTooLarge is raised."""
    count = last - first + 1
    if count > max_pages:
        n = math.ceil(count / max_pages)
        size = math.ceil(count / n)
        parts = []
        for start in range(first, last + 1, size):
            parts += _split(data, start, min(start + size - 1, last), max_bytes, max_pages, gate, notes)
        return parts
    chunk = page_range_bytes(data, first, last)
    if len(chunk) <= max_bytes:
        return [UploadPart(chunk, first, last)]
    if count == 1:
        reduced = _reduce_with_gate(chunk, max_bytes, gate, notes, f"page {first}")
        if reduced is not None:
            return [UploadPart(reduced, first, last, reduced=True)]
        raise UploadTooLarge(f"page {first} is {len(chunk):,} B and cannot be reduced under "
                             f"{max_bytes:,} B without losing digits")
    middle = first + count // 2 - 1
    return (_split(data, first, middle, max_bytes, max_pages, gate, notes)
            + _split(data, middle + 1, last, max_bytes, max_pages, gate, notes))


def plan_upload(pdf_path: str, *, max_bytes: int = MAX_REQUEST_PDF_BYTES, max_pages: int = MAX_PAGES_PER_REQUEST,
                gate: Callable = legibility_check) -> UploadPlan:
    """The parts to send for pdf_path (see the module docstring). Reads the
    file; never writes it."""
    with open(pdf_path, "rb") as f:
        data = f.read()
    pymupdf = _fitz()
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            pages = doc.page_count
    except Exception as e:
        # Not a PDF PyMuPDF can open: within the size limit it is sent as it
        # is (the model's answer decides, as before 2026-10-12); over it,
        # nothing can be done safely.
        if len(data) <= max_bytes:
            return UploadPlan("as_is", [UploadPart(data, 1, 1)], len(data), 1,
                              [f"page count unreadable ({type(e).__name__}); sent as is"])
        raise UploadTooLarge(f"{len(data):,} B and unreadable as a PDF ({type(e).__name__})")
    if len(data) <= max_bytes and pages <= max_pages:
        return UploadPlan("as_is", [UploadPart(data, 1, pages)], len(data), pages)
    notes = []
    parts = _split(data, 1, pages, max_bytes, max_pages, gate, notes)
    if len(parts) == 1:
        return UploadPlan("compressed", parts, len(data), pages, notes)
    return UploadPlan("split", parts, len(data), pages, notes)


# --------------------------------------------------------------------------
# Merging the parsed responses of a split statement
# --------------------------------------------------------------------------

# Statement-level fields: the first part that has a value wins for what a
# statement prints at the top; the LAST part wins for what it prints at the
# end (the printed total sits on the last page).
_FIRST_WINS = ("vendor_name", "statement_date", "shop_or_entity", "billing_location",
               "previous_balance", "previous_balance_label")
_LAST_WINS = ("statement_total_as_printed",)


def merge_chunk_results(parts: List[UploadPart], parsed_list: List[dict]) -> dict:
    """One parsed response for the whole statement: rows in page order (each
    tagged with the first page of the part it came from as "_page"),
    columns_found as the ordered union, statement fields per _FIRST_WINS /
    _LAST_WINS, section_totals concatenated. Disagreements are recorded in
    "_merge_notes" (never silently resolved by averaging)."""
    merged = {"rows": [], "columns_found": [], "_merge_notes": [],
              "_parts": [{"first_page": p.first_page, "last_page": p.last_page, "rows": len(r.get("rows") or [])}
                         for p, r in zip(parts, parsed_list)]}
    for part, parsed in zip(parts, parsed_list):
        for row in parsed.get("rows") or []:
            merged["rows"].append({**row, "_page": part.first_page})
        for column in parsed.get("columns_found") or []:
            if column not in merged["columns_found"]:
                merged["columns_found"].append(column)
    for key in _FIRST_WINS + _LAST_WINS:
        values = [(p.first_page, r.get(key)) for p, r in zip(parts, parsed_list) if r.get(key) not in (None, "", [])]
        if not values:
            merged[key] = None
            continue
        chosen = values[0] if key in _FIRST_WINS else values[-1]
        merged[key] = chosen[1]
        distinct = {str(v) for _, v in values}
        if len(distinct) > 1:
            merged["_merge_notes"].append(f"{key}: parts disagree ({', '.join(f'p{p}={v}' for p, v in values)}); "
                                          f"used p{chosen[0]}")
    sections = [s for r in parsed_list for s in (r.get("section_totals") or [])]
    merged["section_totals"] = sections or None
    if any(r.get("_salvaged") for r in parsed_list):
        merged["_salvaged"] = True
    return merged
