"""
pdf_row_match.py

The Arithmetic Validation Gate's last-resort checks (2026-10-12), run only
when the primary check and every earlier fallback have failed. They can only
ADD a pass: anything unreadable, over the page cap or over the OCR time
budget is "not verified", never a pass.

Every extracted row is located on the PDF itself -- the text layer's word
positions, or for a scanned page Tesseract's image_to_data -- and compared:
invoice number (O/0 and l/I/1 tolerant), date, amount to the cent, and the
column the amount is printed under (header-driven, with the same CHARGE/
CREDIT/OUTSTANDING keyword lists claude_sonnet_client.py maps columns with).
A statement fails on ANY row that is wrong, unverifiable, missing (a PDF
transaction line no extracted row matched) or extra (an extracted row with no
line on the PDF).

pdf_row_match (check_pdf_row_match): every row verified AND an equation built
only from the PDF's own printed numbers reconciles to the printed total --
the rows' printed amounts, a printed previous balance plus the rows, the
printed open-balance column, or the printed running balance.

pdf_store_sections (check_pdf_store_sections): for group statements printed
as store sections headed "<store>  Invoices: N | Amount Due: $X" (VinArt /
Tekion), every row verified, at least one store complete (printed row numbers
1..N, N rows, rows sum to X to the cent) and every other store's rows inside
1..N with no duplicates. The printed total there is the group's, so it is
recorded, not reconciled.

pdf_full_match (check_pdf_full_match, 2026-10-16, user decision): the gate's
very last fallback -- a pass when the extraction matches the PDF cell by
cell, whether or not any total equation reconciles. Every PDF transaction
line has exactly one extracted row and vice versa; every column printed in
the table header is present in the extraction (a printed column the
extraction lacks fails -- Chuck's missing Due column); and every cell is
compared in its own column: amounts to the cent with their printed sign,
dates as dates, invoice/reference numbers exactly (O/0, l/I/1 only), free
text normalised for case, spacing and punctuation.

check_rows_only: for a statement with no printed total anywhere on the PDF --
rows verified both ways, no equation. Passing it is the statement's pass
(validation_method "pdf_rows_no_total", set by the intake); any row problem,
an unreadable PDF, the page cap or the OCR budget is a fail.

Rules each forced by a false pass of the 2026-10-09 prototype (see
scratchpad/oct1_report and the replay notes):
- a balance-column equation counts only when every matched row's extracted
  amount_due equals the balance printed on its line (Chuck's STMT-0D64E1F3:
  the PDF's Due column reconciles but the extraction never captured it);
- a printed invoice-subtotal line is not a transaction, and printed aging
  buckets are corroboration only, never a pass on their own (Goodwins
  STMT-57632B0C passed on aging with an extra subtotal row);
- a dated, unlabelled line printing only a balance is a PDF row that must be
  extracted -- with ONE exception since 2026-10-19 (user decision, reversing
  the prototype's rule for Town Fair STMT-00DDF55B): the statement's first
  line on the text layer, printing only a date and one amount under BALANCE,
  with every other line matched one-to-one and opening + rows = printed to
  the cent, is the opening balance (_opening_balance_line).

A scanned cell or line OCR disputes may be re-read once (REREAD_DPI, binarised) with a
character whitelist; the re-read is accepted only when it EQUALS the extracted
value, and a disagreement leaves the row unverified.
"""

import datetime
import logging
import os
import re
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Optional

logger = logging.getLogger(__name__)

MAX_PAGES = 12
OCR_TIME_BUDGET_SECONDS = 30.0
OCR_MAX_WORKERS = 4
OCR_DPI = 300
OCR_CONFIG = "--psm 6"
# Re-read of a disputed cell: 250 dpi read 24/25 control cells correctly,
# 500-600 dpi only 0-5 (Tesseract is tuned for ordinary text heights).
REREAD_DPI = 250
REREAD_THRESHOLD = 160
REREAD_BORDER_PX = 40
MIN_TEXT_WORDS = 10          # fewer words than this on a page -> treat it as a scan
_PT_PER_PX = 72.0 / OCR_DPI
_CENT = 0.005
_PAGES_CACHE_SIZE = 8

_LABEL_WORDS_EXCLUDED = ("total", "subtotal", "balance forward", "previous balance", "prior balance",
                         "beginning balance", "opening balance", "brought forward", "last statement",
                         "amount due", "balance due", "please pay", "pay this amount", "aging")
_PREVIOUS_BALANCE_LABELS = ("previous balance", "prior balance", "beginning balance", "opening balance",
                            "balance forward", "brought forward", "last statement balance", "balance from last")
_AGING_WORDS = ("current", "30", "60", "90", "120", "over", "days", "past")
_STORE_HEADER_RE = re.compile(
    r"^(?P<store>.*?)\s*Invoices:?\s*(?P<count>\d+)\D{0,3}\s*\|?\s*Amount\s*Due:?\s*\$?(?P<amount>[\d,]+\.\d\d)",
    re.IGNORECASE)
_ROW_NUMBER_RE = re.compile(r"^\D{0,2}?(\d{1,4})[.,]?$")


class NotVerified(Exception):
    """The PDF could not be read completely (page cap, OCR budget, unreadable
    page) -- the check reports "not verified", never a pass."""


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------

_MONEY_RE = re.compile(r"^(\()?(-)?\$?(-)?(\d{1,3}(?:,\d{3})+|\d+)\.(\d{2})(\))?(-)?(CR)?$", re.IGNORECASE)
_MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


def parse_money(text: str) -> Optional[float]:
    """'1,234.56' / '$1,234.56' / '-5.00' / '5.00-' / '(5.00)' / '5.00CR' -> float."""
    s = text.strip().rstrip(".,;:*")
    m = _MONEY_RE.match(s)
    if not m:
        return None
    value = float(m.group(4).replace(",", "") + "." + m.group(5))
    negative = bool((m.group(1) and m.group(6)) or m.group(2) or m.group(3) or m.group(7) or m.group(8))
    return -value if negative else value


def _year(y: str) -> int:
    y = int(y)
    return y + 2000 if y < 100 else y


_DATE_OCR_FIX = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "|": "1"})


def parse_date(text) -> Optional[datetime.date]:
    """mm/dd/yy(yy), mm-dd-yy, yyyy-mm-dd, ddMONyy, and mm-dd with no year
    (compared as month and day only: year 2000 is a placeholder on both
    sides). O/0 and l/I/1 are tolerated in the numeric parts (Tesseract
    reads "01SEP26" as "O1SEP26")."""
    if text is None:
        return None
    s = str(text).strip().strip(".,;:*()")
    m = re.match(r"^([0-9OolI|]{1,2})([A-Za-z]{3})([0-9OolI|]{2,4})$", s)
    if m and m.group(2).upper() in _MONTHS:
        s = m.group(1).translate(_DATE_OCR_FIX) + m.group(2) + m.group(3).translate(_DATE_OCR_FIX)
    elif re.match(r"^[0-9OolI|/\-.]+$", s) and re.search(r"\d", s):
        s = s.translate(_DATE_OCR_FIX)
    try:
        m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?$", s)
        if m:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2}|\d{4})$", s)
        if m:
            return datetime.date(_year(m.group(3)), int(m.group(1)), int(m.group(2)))
        m = re.match(r"^(\d{1,2})[/\-](\d{1,2})$", s)
        if m:
            return datetime.date(2000, int(m.group(1)), int(m.group(2)))
        m = re.match(r"^(\d{1,2})[\-\s]?([A-Za-z]{3})[A-Za-z]*[\-\s]?(\d{2}|\d{4})$", s)
        if m and m.group(2).upper() in _MONTHS:
            return datetime.date(_year(m.group(3)), _MONTHS[m.group(2).upper()], int(m.group(1)))
    except ValueError:
        return None
    return None


_INVOICE_TRANSLATE = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "i": "1", "L": "1"})


def norm_invoice(text) -> str:
    """O/0 and l/I/1 tolerant, case-insensitive, punctuation-free."""
    return re.sub(r"[^0-9A-Z]", "", str(text or "").translate(_INVOICE_TRANSLATE).upper())


# --------------------------------------------------------------------------
# Reading the PDF into lines of positioned words
# --------------------------------------------------------------------------

def _text_layer_words(page):
    words = page.extract_words(x_tolerance=2, y_tolerance=2, keep_blank_chars=False)
    return [{"text": w["text"], "x0": w["x0"], "x1": w["x1"], "top": w["top"], "bottom": w["bottom"]} for w in words]


def _tesseract():
    import pytesseract
    from src.ai.ocr_extractor import _configure_tesseract_path
    _configure_tesseract_path(pytesseract)
    return pytesseract


def _render(pdf_path, page_index, dpi, clip=None):
    import fitz
    from PIL import Image
    with fitz.open(pdf_path) as doc:
        page = doc[page_index]
        pix = page.get_pixmap(dpi=dpi, clip=fitz.Rect(*clip) if clip else None)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples), page.rotation


# Fewer amounts + dates than this on an OCR'd page -> consult orientation
# detection. A sideways scan still yields id-like digit strings (A New Age
# STMT-B218C63A: 11) but no amounts or dates (0, against 36-80 upright).
MIN_READABLE_TOKENS = 3


def _ocr_words(pytesseract, image, deadline, page_index):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise NotVerified("OCR time budget exhausted")
    try:
        data = pytesseract.image_to_data(image, config=OCR_CONFIG, output_type=pytesseract.Output.DICT, timeout=remaining)
    except RuntimeError as e:   # pytesseract raises RuntimeError on its timeout
        raise NotVerified(f"OCR failed or timed out on page {page_index + 1} ({e})")
    words = []
    for i, text in enumerate(data["text"]):
        if not str(text).strip() or float(data["conf"][i]) < 0:
            continue
        x, y, w, h = (data[k][i] * _PT_PER_PX for k in ("left", "top", "width", "height"))
        words.append({"text": str(text).strip(), "x0": x, "x1": x + w, "top": y, "bottom": y + h})
    return words


def _readable_tokens(words):
    return sum(1 for w in words if parse_money(w["text"]) is not None or parse_date(w["text"]))


def _ocr_page(pdf_path, page_index, deadline):
    """(words in page points, rotation applied). The page is read as
    rendered first; only when that read finds almost no amounts or
    dates is Tesseract's orientation detection (OSD) consulted, and the
    rotated read is kept only if it reads better. (Running OSD on every
    page doubled the OCR time, and on NYE 9-4-26 it turned an upright page
    upside down.) Raises NotVerified on a timeout or OCR failure."""
    pytesseract = _tesseract()
    if time.monotonic() > deadline:
        raise NotVerified("OCR time budget exhausted")
    image, page_rotation = _render(pdf_path, page_index, OCR_DPI)
    words = _ocr_words(pytesseract, image, deadline, page_index)
    if _readable_tokens(words) >= MIN_READABLE_TOKENS:
        return words, page_rotation
    try:
        osd = pytesseract.image_to_osd(image, config="--psm 0", timeout=max(1, deadline - time.monotonic()))
        rotation = int(re.search(r"Rotate:\s*(\d+)", osd).group(1))
    except RuntimeError as e:
        if "timeout" in str(e).lower():
            raise NotVerified("OCR time budget exhausted")
        return words, page_rotation
    except Exception:
        return words, page_rotation  # OSD can't decide on sparse pages
    if not rotation:
        return words, page_rotation
    rotated = _ocr_words(pytesseract, image.rotate(-rotation, expand=True), deadline, page_index)
    if _readable_tokens(rotated) > _readable_tokens(words):
        return rotated, rotation
    return words, page_rotation


def _group_lines(words):
    lines = []
    for w in sorted(words, key=lambda w: ((w["top"] + w["bottom"]) / 2, w["x0"])):
        mid = (w["top"] + w["bottom"]) / 2
        height = max(w["bottom"] - w["top"], 1.0)
        if lines and abs(mid - lines[-1]["mid"]) <= 0.45 * max(height, lines[-1]["height"]):
            line = lines[-1]
            line["words"].append(w)
            line["mid"] = sum((x["top"] + x["bottom"]) / 2 for x in line["words"]) / len(line["words"])
        else:
            lines.append({"mid": mid, "height": height, "words": [w]})
    for line in lines:
        line["words"].sort(key=lambda w: w["x0"])
        line["text"] = " ".join(w["text"] for w in line["words"])
        line["top"] = min(w["top"] for w in line["words"])
        line["bottom"] = max(w["bottom"] for w in line["words"])
    return lines


_PAGES_CACHE: "OrderedDict" = OrderedDict()


def read_pdf_lines(pdf_path, budget_seconds=OCR_TIME_BUDGET_SECONDS, max_workers=OCR_MAX_WORKERS):
    """[{"page", "source", "rotation", "lines"}] or raises NotVerified.
    Cached per file (the intake can run the gate twice for one statement);
    the cache keeps the last _PAGES_CACHE_SIZE files only."""
    key = (os.path.abspath(pdf_path), os.path.getmtime(pdf_path), budget_seconds, max_workers)
    if key not in _PAGES_CACHE:
        try:
            _PAGES_CACHE[key] = _read_pdf_lines(pdf_path, budget_seconds, max_workers)
        except NotVerified as e:
            _PAGES_CACHE[key] = e
        while len(_PAGES_CACHE) > _PAGES_CACHE_SIZE:
            _PAGES_CACHE.popitem(last=False)
    cached = _PAGES_CACHE[key]
    if isinstance(cached, NotVerified):
        raise cached
    return cached


def _read_pdf_lines(pdf_path, budget_seconds, max_workers):
    """Text-layer pages are read directly; scanned pages are OCR'd in
    parallel, one Tesseract process per page driven from a thread (the GIL
    is released while Tesseract runs), at most min(cpu count, max_workers)
    at a time, all within one shared time budget."""
    import pdfplumber

    deadline = time.monotonic() + budget_seconds
    with pdfplumber.open(pdf_path) as pdf:
        if len(pdf.pages) > MAX_PAGES:
            raise NotVerified(f"{len(pdf.pages)} pages (cap {MAX_PAGES})")
        text_words = [_text_layer_words(page) for page in pdf.pages]
    scans = [i for i, words in enumerate(text_words) if len(words) < MIN_TEXT_WORDS]
    ocr = {}
    if scans:
        workers = max(1, min(len(scans), os.cpu_count() or 1, max_workers))
        if workers == 1:
            for i in scans:
                ocr[i] = _ocr_page(pdf_path, i, deadline)
        else:
            pool = ThreadPoolExecutor(max_workers=workers)
            try:
                futures = {i: pool.submit(_ocr_page, pdf_path, i, deadline) for i in scans}
                for i, future in futures.items():
                    try:
                        ocr[i] = future.result(timeout=max(0.0, deadline - time.monotonic()) + 1.0)
                    except FutureTimeout:
                        raise NotVerified("OCR time budget exhausted")
            finally:
                # Tesseract calls carry their own timeout, so nothing outlives the budget.
                pool.shutdown(wait=False, cancel_futures=True)
    pages = []
    for i, words in enumerate(text_words):
        if i in ocr:
            pages.append({"page": i + 1, "source": "ocr", "rotation": ocr[i][1], "lines": _group_lines(ocr[i][0])})
        else:
            pages.append({"page": i + 1, "source": "text_layer", "rotation": 0, "lines": _group_lines(words)})
    return pages


# --------------------------------------------------------------------------
# Columns (header-driven)
# --------------------------------------------------------------------------

def classify_header(phrase: str) -> str:
    """The same keyword decisions claude_sonnet_client._map_columns() makes,
    reduced to the column roles this check needs."""
    from src.ai.claude_sonnet_client import (
        CHARGE_KEYWORDS, CREDIT_KEYWORDS, DATE_KEYWORDS, DUE_DATE_KEYWORDS, EXACT_CHARGE_HEADERS,
        EXACT_CREDIT_HEADERS, INVOICE_NUMBER_KEYWORDS, NOT_CREDIT_PHRASES, OUTSTANDING_KEYWORDS,
        REFERENCE_ONLY_KEYWORDS, SIGNED_COLUMN_CHARGE_WORDS, SIGNED_COLUMN_EXCLUDE_WORDS,
    )
    h = re.sub(r"\s+", " ", phrase.lower().strip().replace("_", " "))

    def any_in(words):
        return any(k in h for k in words)

    if any_in(INVOICE_NUMBER_KEYWORDS) or h == "invoice":
        return "ref"
    if "date" not in h and any_in(REFERENCE_ONLY_KEYWORDS):
        return "ref"
    if any_in(DUE_DATE_KEYWORDS) or any_in(DATE_KEYWORDS):
        return "date"
    if h.startswith("unalloc") and "due" not in h:
        return "unalloc"
    if "credit" in h and any_in(SIGNED_COLUMN_CHARGE_WORDS) and not any(k in f" {h}" for k in SIGNED_COLUMN_EXCLUDE_WORDS):
        return "signed"
    if any_in(OUTSTANDING_KEYWORDS):
        return "balance"
    if (any_in(CREDIT_KEYWORDS) or h in EXACT_CREDIT_HEADERS) and not any_in(NOT_CREDIT_PHRASES):
        return "credit"
    if any_in(CHARGE_KEYWORDS) or h in EXACT_CHARGE_HEADERS:
        return "charge"
    if h in ("total", "sub-total", "subtotal"):
        return "total"
    return "other"


_AMOUNT_ROLES = ("charge", "credit", "signed")


def _phrases(line, gap_factor=0.55):
    """Header words merged into phrases: a gap wider than ~half a line
    height starts a new phrase."""
    out = []
    for w in line["words"]:
        if out and w["x0"] - out[-1]["x1"] <= gap_factor * line["height"] + 1.0:
            out[-1]["text"] += " " + w["text"]
            out[-1]["x1"] = w["x1"]
        else:
            out.append({"text": w["text"], "x0": w["x0"], "x1": w["x1"]})
    return out


def _line_has_money(line):
    return any(parse_money(w["text"]) is not None for w in line["words"])


def _find_header(lines, classify=None):
    """(index, columns) of the best header line on a page, or (None, None).
    A header has no money values, at least two recognised column roles, at
    least one amount-type role, and amounts within the next few lines. A
    wrapped header line directly above is merged into the phrases it
    overlaps ("Amount" over "Due"). classify: the header classifier
    (default classify_header; see account_blocks.py)."""
    classify = classify or classify_header
    best = (None, None, 0)
    for i, line in enumerate(lines):
        if _line_has_money(line) or len(line["words"]) < 2:
            continue
        phrases = _phrases(line)
        above = lines[i - 1] if i > 0 else None
        # A wrapped header line holds words only -- a line with any digit
        # (phone, account number, date) is letterhead, not a header.
        if (above is not None and line["top"] - above["bottom"] < 0.8 * line["height"]
                and not any(re.search(r"\d", w["text"]) for w in above["words"])):
            for w in above["words"]:
                host = next((p for p in phrases if w["x0"] < p["x1"] and w["x1"] > p["x0"]), None)
                if host is not None:
                    host["text"] = w["text"] + " " + host["text"]
        columns = [{**p, "role": classify(p["text"])} for p in phrases]
        roles = [c["role"] for c in columns]
        known = sum(1 for r in roles if r != "other")
        if known < 2 or not any(r in _AMOUNT_ROLES + ("balance", "total") for r in roles):
            continue
        if not any(_line_has_money(l) for l in lines[i + 1:i + 7]):
            continue
        if known > best[2]:
            best = (i, columns, known)
    if best[0] is None:
        return None, None
    columns = best[1]
    roles = {c["role"] for c in columns}
    # A bare "Total" column is the row amount only when nothing else is
    # (the client's last-resort rule); a lone balance column (KSI's
    # "Remaining Amount") is likewise the row amount column.
    for c in columns:
        if c["role"] == "total":
            c["role"] = "charge" if not roles & {"charge", "credit", "signed", "balance"} else "other"
    roles = {c["role"] for c in columns}
    if not roles & set(_AMOUNT_ROLES):
        for c in columns:
            if c["role"] == "balance":
                c["role"] = "charge"
                c["balance_as_amount"] = True
    return best[0], columns


def column_of(word, columns):
    """The header column a value sits under: the header phrase it overlaps
    most, else the nearest one within 30pt."""
    best, best_overlap = None, 0.0
    for c in columns:
        overlap = min(word["x1"], c["x1"] + 2) - max(word["x0"], c["x0"] - 2)
        if overlap > best_overlap:
            best, best_overlap = c, overlap
    if best is not None:
        return best
    distances = [(min(abs(word["x0"] - c["x1"]), abs(c["x0"] - word["x1"])), k) for k, c in enumerate(columns)]
    if distances:
        d, k = min(distances)
        if d <= 30:
            return columns[k]
    return None


# --------------------------------------------------------------------------
# Building the PDF's own table
# --------------------------------------------------------------------------

def _is_label_line(text):
    t = text.lower()
    return any(k in t for k in _LABEL_WORDS_EXCLUDED)


def _id_like(text):
    s = re.sub(r"[^0-9A-Za-z]", "", text)
    return len(s) >= 4 and sum(ch.isdigit() for ch in s) >= 3 and parse_money(text) is None and parse_date(text) is None


def _annotate_line(line, columns, in_region):
    """Parsed money values (each with the column role it sits under), dates,
    the printed row number and whether the line is a PDF transaction."""
    money = []
    for k, w in enumerate(line["words"]):
        value = parse_money(w["text"])
        if value is None:
            continue
        prev = line["words"][k - 1] if k else None
        nxt = line["words"][k + 1] if k + 1 < len(line["words"]) else None
        if prev is not None and prev["text"] in ("-", "−") and w["x0"] - prev["x1"] < 4:
            value = -abs(value)
        if nxt is not None and nxt["text"].upper() in ("CR", "CR.") and nxt["x0"] - w["x1"] < 8:
            value = -abs(value)
        col = column_of(w, columns) if in_region and columns else None
        money.append({"value": value, "role": col["role"] if col else None,
                      "column": col["text"] if col else None, "word": w})
    dates = [d for d in (parse_date(w["text"]) for w in line["words"]) if d]
    for k in range(len(line["words"]) - 2):  # "Aug 14 2026" over three words
        joined = " ".join(x["text"] for x in line["words"][k:k + 3])
        m = re.match(r"^([A-Za-z]{3})[a-z]*\.? (\d{1,2}),? (\d{4})$", joined)
        if m and m.group(1).upper() in _MONTHS:
            try:
                dates.append(datetime.date(int(m.group(3)), _MONTHS[m.group(1).upper()], int(m.group(2))))
            except ValueError:
                pass
    amount_values = [m for m in money if m["role"] in _AMOUNT_ROLES and abs(m["value"]) > _CENT]
    balance_values = [m for m in money if m["role"] == "balance" and abs(m["value"]) > _CENT]
    # A transaction line: an amount under a charge/credit column, or -- dated
    # and unlabelled -- a value under the balance column only (an unlabelled
    # balance-forward line is a PDF row too: Town Fair).
    is_transaction = bool(
        in_region and not _is_label_line(line["text"]) and (
            (amount_values and (dates or any(_id_like(w["text"]) for w in line["words"])))
            or (balance_values and dates)
        )
    )
    row_number = None
    if line["words"]:
        m = _ROW_NUMBER_RE.match(line["words"][0]["text"])
        if m and not dates or (m and parse_date(line["words"][0]["text"]) is None):
            row_number = int(m.group(1)) if m else None
    return {"money": money, "dates": dates, "is_transaction": is_transaction, "row_number_printed": row_number}


def build_table(pages, classify=None):
    """Every line of every page, annotated (see _annotate_line). Pages
    without a header reuse the last header's columns; a printed store header
    ("<store> Invoices: N | Amount Due: $X") sets the store of the lines
    below it. classify: passed to _find_header (None = classify_header)."""
    table = []
    columns = None
    store = None
    for page in pages:
        lines = page["lines"]
        header_index, page_columns = _find_header(lines, classify)
        if page_columns:
            columns = page_columns
        for i, line in enumerate(lines):
            h = _STORE_HEADER_RE.match(line["text"])
            if h:
                store = {"name": h.group("store").strip(" |:"), "count": int(h.group("count")),
                         "amount_due": float(h.group("amount").replace(",", ""))}
            in_region = columns is not None and (header_index is None or i > header_index)
            entry = {"page": page["page"], "source": page["source"], "rotation": page.get("rotation", 0),
                     "text": line["text"], "words": line["words"], "top": line["top"], "bottom": line["bottom"],
                     "height": line.get("height", line["bottom"] - line["top"]), "in_region": in_region,
                     "columns": columns, "is_subtotal": False, "store": store if not h else None,
                     "is_store_header": bool(h)}
            entry.update(_annotate_line(line, columns, in_region))
            if h:
                entry["is_transaction"] = False
            table.append(entry)
    _mark_invoice_subtotals(table)
    return table


def _line_amount(line):
    values = [m["value"] for m in line["money"] if m["role"] in _AMOUNT_ROLES and abs(m["value"]) > _CENT]
    return values[0] if len(values) == 1 else None


def _mark_invoice_subtotals(table):
    """A line whose single amount equals the sum of the two or more
    consecutive transaction lines directly above it that print the same
    invoice number is that invoice's printed subtotal (Goodwins: 3,079.84 -
    506.33 = 2,573.51 for CVW357073), not a transaction of its own."""
    for k, line in enumerate(table):
        if not line["is_transaction"]:
            continue
        amount = _line_amount(line)
        if amount is None:
            continue
        tokens = {norm_invoice(w["text"]) for w in line["words"] if _id_like(w["text"])}
        run, j = [], k - 1
        while j >= 0 and table[j]["is_transaction"] and not table[j]["is_subtotal"]:
            above_tokens = {norm_invoice(w["text"]) for w in table[j]["words"] if _id_like(w["text"])}
            if not tokens & above_tokens or _line_amount(table[j]) is None:
                break
            run.append(_line_amount(table[j]))
            j -= 1
        if len(run) >= 2 and abs(round(sum(run) - amount, 2)) <= _CENT:
            line["is_transaction"] = False
            line["is_subtotal"] = True


# --------------------------------------------------------------------------
# Row matching
# --------------------------------------------------------------------------

def _row_amounts(inv):
    """[(expected signed net, kind)] for one extracted row, as the gate counts it."""
    from src.validation.arithmetic_gate import _row_net
    bf, pa = inv.get("balance_forward"), inv.get("payment_applied")
    if bf and pa:
        return [(round(bf, 2), "settlement_forward"), (round(-abs(pa), 2), "settlement_payment")]
    return [(round(_row_net(inv), 2), "net")]


def _invoice_on_line(invoice_norm, line):
    tokens = [norm_invoice(w["text"]) for w in line["words"]]
    for start in range(len(tokens)):
        joined = ""
        for end in range(start, len(tokens)):
            joined += tokens[end]
            if joined == invoice_norm:
                return True
            if len(joined) >= len(invoice_norm) or not invoice_norm.startswith(joined):
                break
    return False


def _money_matches(expected, item):
    """Does printed value `item` under its column carry the row's signed
    amount? Charge/signed column: the printed sign is the row's sign. Credit
    column: always a reduction (the gate nets abs(credit))."""
    v = item["value"]
    if item["role"] == "credit":
        return abs(abs(v) - abs(expected)) <= _CENT and expected < 0
    if item["role"] in ("charge", "signed"):
        return abs(v - expected) <= _CENT
    return False


def _check_row(inv, line, allow_balance_only=False):
    """None if the row matches this line exactly, else a reason string.
    allow_balance_only (rows-only mode only): a row with no amount matches a
    line that prints no amount either, only a balance equal to the row's
    extracted amount_due (Healey's 1401474: Amount blank, Balance -100.54)."""
    if line.get("is_subtotal"):
        return "the PDF line is a printed invoice subtotal, not a transaction"
    want_date = parse_date(inv.get("invoice_date"))
    if allow_balance_only and abs(sum(a for a, _ in _row_amounts(inv))) <= _CENT:
        printed_amounts = [m for m in line["money"] if m["role"] in _AMOUNT_ROLES and abs(m["value"]) > _CENT]
        balance = _balance_value(line)
        due = inv.get("amount_due")
        if (not printed_amounts and balance is not None and due is not None and abs(due - balance) <= _CENT
                and (want_date is None or want_date in line["dates"])):
            line["_used_money"] = []
            return None
    if want_date is not None and want_date not in line["dates"]:
        return f"date {inv.get('invoice_date')} not on the PDF line (PDF dates: " \
               f"{', '.join(d.isoformat() for d in line['dates']) or 'none'})"
    if want_date is None and line["dates"] and inv.get("invoice_date"):
        return f"date {inv.get('invoice_date')!r} unreadable"
    if want_date is None and line["dates"]:
        return "date missing from the extracted row"
    used = []
    for amount, kind in _row_amounts(inv):
        if abs(amount) <= _CENT:
            if kind == "net" and any(m["role"] in _AMOUNT_ROLES and abs(m["value"]) > _CENT for m in line["money"]):
                return "extracted row has no amount; the PDF line prints one"
            if kind == "net":
                return "extracted row has no amount (unverifiable)"
            continue
        hit = next((m for m in line["money"] if id(m) not in used and _money_matches(amount, m)), None)
        if hit is None:
            same_value = [m for m in line["money"] if abs(abs(m["value"]) - abs(amount)) <= _CENT]
            if same_value:
                m = same_value[0]
                return (f"amount {amount:,.2f} printed as {m['value']:,.2f} under "
                        f"{m['column'] or 'no recognised column'} ({m['role'] or 'none'}) -- wrong column or sign")
            printed = ", ".join(f"{m['value']:,.2f} ({m['role'] or '-'})" for m in line["money"]) or "none"
            return f"amount {amount:,.2f} not on the PDF line (printed: {printed})"
        used.append(id(hit))
    # Another amount on the line is only acceptable when it repeats the
    # matched amount under a second charge column (Sub-Total = Total).
    matched_values = [m["value"] for m in line["money"] if id(m) in used]
    leftover = [m for m in line["money"] if id(m) not in used and m["role"] in _AMOUNT_ROLES and abs(m["value"]) > _CENT
                and not (m["role"] == "charge" and any(abs(m["value"] - v) <= _CENT for v in matched_values))]
    if leftover:
        return "PDF line also prints " + ", ".join(f"{m['value']:,.2f} under {m['column']}" for m in leftover) + \
               " which the extracted row does not carry"
    line["_used_money"] = used
    return None


def match_rows(invoices, table, allow_balance_only=False, reread=None):
    """(matches, failures, rereads). matches: [(row, line)] in row order.
    failures: every offending row -- wrong, unverifiable, extra (not on the
    PDF) and missing (a PDF transaction line no row matched). reread: an
    optional OCR re-reader (see _Rereader) given one chance per disputed
    scanned row; it is accepted only when its independent read equals the
    extracted value."""
    consumed = set()  # id() of matched table lines (the re-reader may insert lines)
    matches, failures, unmatched = [], [], []
    for position, inv in enumerate(invoices, start=1):
        label = {"position": position, "row_number": inv.get("row_number"), "invoice_number": inv.get("invoice_number"),
                 "date": inv.get("invoice_date"), "amount": round(sum(a for a, _ in _row_amounts(inv)), 2)}
        if inv.get("informational"):
            continue
        invoice_norm = norm_invoice(inv.get("invoice_number"))
        candidates = [k for k, line in enumerate(table) if id(line) not in consumed and line["in_region"]]
        if invoice_norm:
            candidates = [k for k in candidates if _invoice_on_line(invoice_norm, table[k])]
        else:
            want_date = parse_date(inv.get("invoice_date"))
            candidates = [k for k in candidates if (table[k]["is_transaction"] or table[k]["is_subtotal"])
                          and (want_date is None or want_date in table[k]["dates"])]
        if not candidates:
            anywhere = invoice_norm and any(_invoice_on_line(invoice_norm, line) for line in table)
            unmatched.append((position, inv, {**label, "problem": "extra" if not anywhere else "unverifiable",
                              "reason": ("invoice not found on the PDF" if invoice_norm else "no PDF line with this date/amount")
                              if not anywhere else "invoice is on the PDF but outside any recognised table/column"}))
            continue
        reasons = []
        for k in candidates:
            reason = _check_row(inv, table[k], allow_balance_only)
            if reason is None:
                consumed.add(id(table[k]))
                matches.append((position, inv, table[k]))
                break
            reasons.append(f"p{table[k]['page']}: {reason}")
        else:
            unmatched.append((position, inv, {**label, "problem": "wrong", "reason": reasons[0]}))
    rereads = []
    if reread is not None and unmatched:
        unmatched = reread.resolve(unmatched, matches, table, consumed, rereads)
    failures = [f for _, _, f in unmatched]
    for k, line in enumerate(table):
        if line["is_transaction"] and id(line) not in consumed:
            failures.append({"position": None, "row_number": None, "invoice_number": None, "date": None,
                             "amount": None, "problem": "missing",
                             "reason": f"PDF line not extracted (p{line['page']}): {line['text'][:110]}"})
    matches.sort(key=lambda m: m[0])
    return [(inv, line) for _, inv, line in matches], failures, rereads


# --------------------------------------------------------------------------
# Re-reading a disputed scanned cell or line (OCR second opinion)
# --------------------------------------------------------------------------

# Two-digit month/day first ("2308/19/26" -> "23" + "08/19/26", not
# "230" + "8/19/26"); a wrong split can only fail the row-number checks.
_ROW_NUMBER_AND_DATE_RES = (re.compile(r"^(\d{1,3}?)(\d{2}/\d{2}/\d{2,4})$"),
                            re.compile(r"^(\d{1,3})(\d{1,2}/\d{1,2}/\d{2,4})$"))


def _split_row_number_from_date(words):
    """A whitelisted re-read can glue a printed row number to the date next
    to it ("23" + "08/19/26" -> "2308/19/26"); split such a token back into
    the two words it was printed as."""
    out = []
    for w in words:
        m = None if parse_date(w["text"]) else next(
            (m for m in (r.match(w["text"]) for r in _ROW_NUMBER_AND_DATE_RES)
             if m and m.group(1) and parse_date(m.group(2))), None)
        if m:
            share = len(m.group(1)) / len(w["text"])
            cut = w["x0"] + (w["x1"] - w["x0"]) * share
            out.append({**w, "text": m.group(1), "x1": cut})
            out.append({**w, "text": m.group(2), "x0": cut})
        else:
            out.append(w)
    return out


class _Rereader:
    """A second, independent OCR read of ONE disputed spot on an unrotated
    scanned page, at REREAD_DPI, binarised, with a character whitelist. Two cases:

    - an extracted row whose date and amount sit on an unmatched PDF line
      whose invoice cell OCR read differently: the invoice cell is re-read and
      accepted only if it equals the extracted invoice number;
    - an extracted row with no PDF line at all between two matched
      neighbours on the same page (OCR skipped the line): the band between
      them is re-read and accepted only if it holds exactly one line that
      matches the row exactly (invoice, date, amount, column).

    Anything else -- a disagreement, an empty read, a rotated page, the time
    budget -- leaves the row unverified."""

    def __init__(self, pdf_path, deadline):
        self.pdf_path = pdf_path
        self.deadline = deadline

    def _ocr(self, page_number, box, whitelist, psm):
        if time.monotonic() > self.deadline:
            return None
        pytesseract = _tesseract()
        from PIL import ImageOps
        x0, top, x1, bottom = box
        image, _ = _render(self.pdf_path, page_number - 1, REREAD_DPI, clip=(x0, top, x1, bottom))
        # Binarised and given a white margin: on the 25 control cells of
        # STMT-7A968D83 that OCR had read correctly, this read 24 back
        # exactly, against 4 at 500 dpi colour (2026-10-12 experiment).
        image = ImageOps.grayscale(image).point(lambda p: 255 if p > REREAD_THRESHOLD else 0)
        image = ImageOps.expand(image, border=REREAD_BORDER_PX, fill=255)
        config = f"--psm {psm} -c tessedit_char_whitelist={whitelist}"
        try:
            data = pytesseract.image_to_data(image, config=config, output_type=pytesseract.Output.DICT,
                                             timeout=max(1.0, self.deadline - time.monotonic()))
        except RuntimeError:
            return None
        scale = 72.0 / REREAD_DPI
        words = []
        for i, text in enumerate(data["text"]):
            if str(text).strip() and float(data["conf"][i]) >= 0:
                left, upper = data["left"][i] - REREAD_BORDER_PX, data["top"][i] - REREAD_BORDER_PX
                words.append({"text": str(text).strip(), "x0": x0 + left * scale,
                              "x1": x0 + (left + data["width"][i]) * scale,
                              "top": top + upper * scale, "bottom": top + (upper + data["height"][i]) * scale})
        return words

    @staticmethod
    def _eligible(line):
        return line["source"] == "ocr" and not line.get("rotation")

    def resolve(self, unmatched, matches, table, consumed, log):
        still = []
        for position, inv, failure in unmatched:
            fixed = self._cell(inv, table, consumed, log) or self._band(position, inv, matches, table, consumed, log)
            if fixed is None:
                still.append((position, inv, failure))
                continue
            consumed.add(id(fixed))
            matches.append((position, inv, fixed))
        return still

    def _cell(self, inv, table, consumed, log):
        invoice = str(inv.get("invoice_number") or "")
        want = norm_invoice(invoice)
        if not want:
            return None
        for k, line in enumerate(table):
            if id(line) in consumed or not line["is_transaction"] or not self._eligible(line):
                continue
            ids = [w for w in line["words"] if _id_like(w["text"])]
            if len(ids) != 1:
                continue
            probe = dict(line, words=[dict(w) for w in line["words"]])
            cell = next(w for w in probe["words"] if w["text"] == ids[0]["text"])
            cell["text"] = invoice
            probe["text"] = " ".join(w["text"] for w in probe["words"])
            if _check_row(inv, probe) is not None:
                continue  # date/amount/column don't agree either -- not this line
            whitelist = "".join(sorted(set(re.sub(r"\s", "", invoice.upper())) | set("0123456789")))
            pad = 0.6 * line["height"]
            words = self._ocr(line["page"], (ids[0]["x0"] - pad, line["top"] - pad, ids[0]["x1"] + pad, line["bottom"] + pad),
                              whitelist, 7)
            got = "".join(w["text"] for w in words or [])
            accepted = bool(got) and norm_invoice(got) == want
            log.append({"page": line["page"], "kind": "invoice cell", "ocr": ids[0]["text"], "reread": got,
                        "extracted": invoice, "accepted": accepted})
            if accepted:
                _check_row(inv, probe)
                line.update(words=probe["words"], text=probe["text"], money=probe["money"])
                line["_used_money"] = probe.get("_used_money", [])
                return line
            return None
        return None

    def _band(self, position, inv, matches, table, consumed, log):
        before = [m for m in matches if m[0] < position]
        after = [m for m in matches if m[0] > position]
        if not before or not after:
            return None
        prev_line = max(before, key=lambda m: m[0])[2]
        next_line = min(after, key=lambda m: m[0])[2]
        if prev_line["page"] != next_line["page"] or not self._eligible(prev_line) or not self._eligible(next_line):
            return None
        top, bottom = prev_line["bottom"] + 0.5, next_line["top"] - 0.5
        if bottom - top < 0.6 * prev_line["height"]:
            return None
        x0 = min(w["x0"] for w in prev_line["words"] + next_line["words"]) - 6
        x1 = max(w["x1"] for w in prev_line["words"] + next_line["words"]) + 6
        invoice = str(inv.get("invoice_number") or "")
        whitelist = "".join(sorted(set(re.sub(r"\s", "", invoice.upper())) | set("0123456789/-.,$()")))
        words = self._ocr(prev_line["page"], (x0, top, x1, bottom), whitelist, 6)
        lines = _group_lines(_split_row_number_from_date(words)) if words else []
        accepted = False
        new = None
        if len(lines) == 1:
            columns = prev_line["columns"]
            new = {"page": prev_line["page"], "source": "ocr", "rotation": 0, "text": lines[0]["text"],
                   "words": lines[0]["words"], "top": lines[0]["top"], "bottom": lines[0]["bottom"],
                   "height": lines[0]["height"], "in_region": True, "columns": columns, "is_subtotal": False,
                   "store": prev_line.get("store"), "is_store_header": False}
            new.update(_annotate_line(lines[0], columns, True))
            accepted = (_invoice_on_line(norm_invoice(invoice), new) and _check_row(inv, new) is None)
        log.append({"page": prev_line["page"], "kind": "skipped line", "reread": lines[0]["text"] if len(lines) == 1 else
                    f"{len(lines)} line(s)", "extracted": f"{invoice} {inv.get('invoice_date')}", "accepted": accepted})
        if not accepted:
            return None
        # A line OCR did read in this band (misread) is replaced, not
        # duplicated; otherwise the re-read line is inserted in place.
        inside = [l for l in table if id(l) not in consumed and l["page"] == new["page"]
                  and top <= (l["top"] + l["bottom"]) / 2 <= bottom and (l["is_transaction"] or l["money"])]
        if len(inside) > 1:
            return None
        if inside:
            inside[0].update(new)
            return inside[0]
        table.insert(table.index(next_line), new)
        return new


# --------------------------------------------------------------------------
# Equations from the PDF's own numbers
# --------------------------------------------------------------------------

def _printed_net(line):
    """The row's signed amount as printed (charge/signed: as printed;
    credit column: a reduction)."""
    total = 0.0
    for m in line["money"]:
        if id(m) in line.get("_used_money", ()):
            total += -abs(m["value"]) if m["role"] == "credit" else m["value"]
    return round(total, 2)


def _balance_value(line):
    """The line's printed balance; a remittance stub repeating it on the
    right (Bishop's, Yerty) is fine, two different balances are not."""
    values = [m["value"] for m in line["money"] if m["role"] == "balance"]
    if values and all(abs(v - values[0]) <= _CENT for v in values):
        return values[0]
    return None


def _printed_anywhere(table, value, exclude):
    return any(id(line) not in exclude and any(abs(abs(m["value"]) - abs(value)) <= _CENT for m in line["money"])
               for line in table)


def equations(table, matches, printed, tolerance):
    """Every PDF-number equation that can be formed; each entry records
    whether it reconciles to the printed total. Only "rows",
    "previous_balance", "open_balance" and "running_balance" can pass;
    "aging" is corroboration only."""
    order = {id(line): k for k, line in enumerate(table)}
    row_lines = sorted({id(line): line for _, line in matches}.values(), key=lambda l: order[id(l)])
    nets = [_printed_net(line) for line in row_lines]
    rows_total = round(sum(nets), 2)
    out = []

    def add(name, computed, detail, carried_by_extraction=True):
        out.append({"equation": name, "computed": round(computed, 2),
                    "reconciles": abs(round(printed - computed, 2)) <= tolerance and carried_by_extraction,
                    "detail": detail, "carried_by_extraction": carried_by_extraction})

    rows_by_line = {}
    for inv, line in matches:
        rows_by_line.setdefault(id(line), []).append(inv)

    def balance_not_carried():
        """Rows whose extracted amount_due differs from the balance printed
        on their line (blank on the PDF = none extracted)."""
        bad = []
        for line in row_lines:
            printed_balance = _balance_value(line)
            for inv in rows_by_line.get(id(line), []):
                due = inv.get("amount_due")
                if printed_balance is None and due in (None, 0, 0.0):
                    continue
                if printed_balance is None or due is None or abs(round(due - printed_balance, 2)) > _CENT:
                    bad.append(inv.get("invoice_number"))
        return bad

    add("rows", rows_total, "sum of the matched lines' printed amounts")

    previous = None
    for line in table:
        if any(k in line["text"].lower() for k in _PREVIOUS_BALANCE_LABELS) and line["money"]:
            previous = line["money"][-1]["value"]
            add("previous_balance", previous + rows_total,
                f"printed previous balance {previous:,.2f} (p{line['page']}: {line['text'][:60]}) + rows {rows_total:,.2f}")
            break

    balances = [_balance_value(line) for line in row_lines]
    charge_lines = [b for b, net in zip(balances, nets) if net > 0]
    if charge_lines and sum(1 for b in charge_lines if b is not None) * 2 >= len(charge_lines):
        unallocated = sum(abs(m["value"]) for line in row_lines for m in line["money"] if m["role"] == "unalloc")
        bad = balance_not_carried()
        add("open_balance", sum(b or 0 for b in balances) - unallocated,
            "sum of the printed open-balance column on the matched lines"
            + (f" minus printed unallocated {unallocated:,.2f}" if unallocated else "")
            + (f"; extracted amount_due differs on {len(bad)} row(s), e.g. {bad[:3]}" if bad else ""),
            carried_by_extraction=not bad)
    if row_lines and all(b is not None for b in balances):
        running = previous if previous is not None else 0.0
        chain_ok = True
        for net, bal in zip(nets, balances):
            if abs(round(running + net - bal, 2)) > tolerance:
                chain_ok = False
                break
            running = bal
        if chain_ok:
            bad = balance_not_carried()
            add("running_balance", balances[-1], "printed running balance chain holds; last printed balance"
                + (f"; extracted amount_due differs on {len(bad)} row(s)" if bad else ""), carried_by_extraction=not bad)

    for k, line in enumerate(table):
        words = line["text"].lower()
        if "current" in words and sum(1 for w in _AGING_WORDS if w in words) >= 3 and not line["money"]:
            for values_line in table[k + 1:k + 3]:
                values = [m["value"] for m in values_line["money"]]
                if len(values) >= 3:
                    buckets = values[:-1] if abs(round(sum(values[:-1]) - values[-1], 2)) <= tolerance else values
                    add("aging", sum(buckets),
                        f"aging buckets on p{values_line['page']}: {', '.join(f'{v:,.2f}' for v in buckets)} (corroboration only)",
                        carried_by_extraction=False)
                    break
            break
    return out


# --------------------------------------------------------------------------
# The gate checks
# --------------------------------------------------------------------------

def _analyse(rows, pdf_path, budget_seconds, allow_balance_only=False):
    """(pages, table, matches, failures, rereads) or raises NotVerified."""
    started = time.monotonic()
    try:
        pages = read_pdf_lines(pdf_path, budget_seconds)
    except NotVerified:
        raise
    except Exception as e:
        raise NotVerified(f"PDF unreadable ({type(e).__name__}: {e})") from None
    table = build_table(pages)
    deadline = started + budget_seconds
    reread = _Rereader(pdf_path, deadline) if any(p["source"] == "ocr" for p in pages) else None
    matches, failures, rereads = match_rows(rows, table, allow_balance_only=allow_balance_only, reread=reread)
    return pages, table, matches, failures, rereads


def _not_applicable(reason):
    return {"applicable": False, "passed": False, "computed": None, "reason": reason}


def _row_result(pages, table, rows, matches, failures, rereads, started):
    result = {"applicable": True, "passed": False, "computed": None,
              "text_source": "+".join(sorted({p["source"] for p in pages})), "pages": len(pages),
              "rows": len(rows), "rows_verified": len(matches),
              "pdf_transaction_lines": sum(1 for l in table if l["is_transaction"]),
              "seconds": round(time.monotonic() - started, 2)}
    if rereads:
        result["ocr_rereads"] = rereads
    if failures:
        result.update(reason=f"{len(failures)} row problem(s)", offending_rows=failures[:5],
                      problem_counts={p: sum(1 for f in failures if f["problem"] == p)
                                      for p in ("wrong", "unverifiable", "missing", "extra")})
    return result


def _opening_balance_line(table, matches, failures):
    """The statement's opening-balance line, or None (2026-10-19, Town Fair
    STMT-00DDF55B: "07-31-26 887.00" printed alone under BALANCE before the
    first transaction; the extraction correctly has no row for it). It is
    accepted ONLY when every one of these holds -- otherwise it stays a
    missing row:
      - the only problem is exactly one unmatched PDF line (no wrong, extra or
        unverifiable row, no other missing line);
      - that line comes from the PDF's text layer (never OCR: a scan could
        hide a real transaction's reference and charge);
      - it is the first transaction-area line: every matched line is below it;
      - it prints a date and exactly one amount, under the BALANCE column, and
        nothing else (no reference, no charge or credit, no label);
      - no labelled previous/opening balance is printed anywhere (that path
        is the printed previous-balance equation's);
    the caller then requires opening + rows = printed to the cent."""
    if any(f["problem"] != "missing" for f in failures) or len(failures) != 1:
        return None
    matched = {id(line) for _, line in matches}
    order = {id(line): k for k, line in enumerate(table)}
    missing = [line for line in table if line["is_transaction"] and id(line) not in matched]
    if len(missing) != 1:
        return None
    line = missing[0]
    if line["source"] != "text_layer" or line.get("is_subtotal") or line.get("is_store_header"):
        return None
    if matched and order[id(line)] > min(order[i] for i in matched):
        return None
    money = [m for m in line["money"] if abs(m["value"]) > _CENT]
    if len(money) != 1 or money[0]["role"] != "balance" or not line["dates"]:
        return None
    for w in line["words"]:
        if w is money[0]["word"] or parse_date(w["text"]) is not None:
            continue
        return None  # anything else printed on the line: a reference, a label, a second figure
    if any(any(k in l["text"].lower() for k in _PREVIOUS_BALANCE_LABELS) for l in table):
        return None
    return line


def check_pdf_row_match(printed, rows, *, tolerance=0.01, pdf_path=None, budget_seconds=OCR_TIME_BUDGET_SECONDS, **_):
    """Gate method "pdf_row_match" (see the module docstring)."""
    started = time.monotonic()
    if not pdf_path:
        return _not_applicable("no PDF available")
    if not rows:
        return _not_applicable("no rows")
    if printed is None:
        return _not_applicable("no printed total")
    try:
        pages, table, matches, failures, rereads = _analyse(rows, pdf_path, budget_seconds)
    except NotVerified as e:
        return {"applicable": True, "passed": False, "computed": None, "reason": f"not verified: {e}",
                "seconds": round(time.monotonic() - started, 2)}
    result = _row_result(pages, table, rows, matches, failures, rereads, started)
    opening = _opening_balance_line(table, matches, failures) if failures else None
    if failures and opening is None:
        return result
    if opening is not None:
        # The only unmatched PDF line is a verified opening-balance line
        # (2026-10-19): it is not a missing row, and it only takes part in
        # the "opening_balance_line" equation below.
        result.pop("offending_rows", None)
        result.pop("problem_counts", None)
        result["opening_balance_line"] = {"page": opening["page"], "date": opening["dates"][0].isoformat(),
                                          "amount": opening["money"][0]["value"], "text": opening["text"][:80]}
    if not _printed_anywhere(table, printed, exclude={id(l) for _, l in matches}):
        result["reason"] = f"printed total {printed:,.2f} is not printed on the PDF outside the rows"
        return result
    eqs = equations(table, matches, printed, tolerance)
    if opening is not None:
        # With an opening line every other equation is moot: only opening + rows may reconcile.
        rows_total = next(e["computed"] for e in eqs if e["equation"] == "rows")
        value = opening["money"][0]["value"]
        computed = round(value + rows_total, 2)
        # Exactly to the cent -- stricter than the gate's usual 0.01 tolerance.
        eqs = [{"equation": "opening_balance_line", "computed": computed,
                "reconciles": abs(round(printed - computed, 2)) < _CENT, "carried_by_extraction": True,
                "detail": f"opening balance {value:,.2f} printed alone on the first line (p{opening['page']}) "
                          f"+ rows {rows_total:,.2f}"}]
    result["equations"] = eqs
    passing = [e for e in eqs if e["reconciles"]]
    if not passing:
        result["reason"] = ("every row verified, but no equation from the PDF's numbers reconciles: "
                            + "; ".join(f"{e['equation']} {e['computed']:,.2f}" for e in eqs))
        return result
    result.update(passed=True, computed=passing[0]["computed"], equation=passing[0]["equation"], reason="")
    return result


def _name_key(name) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(name or "").lower()))


def _same_vendor(a, b) -> bool:
    """Names of one vendor: equal once case and punctuation are ignored, or
    resolving to the same vendor id (config/vendor_aliases.json)."""
    if _name_key(a) and _name_key(a) == _name_key(b):
        return True
    from src.vendor_identity import resolve_vendor_id
    ida, idb = resolve_vendor_id(a), resolve_vendor_id(b)
    return ida is not None and ida == idb


def _vendor_section(table, matches, failures, vendor_name):
    """({"section_used", "lines_ignored"}, None) when the statement is ONE
    complete store section of its own vendor and every unmatched printed line
    belongs to a different, explicitly headed section (2026-10-19, LV Honda
    STMT-4E854578: the Honda section's 56 rows, then the first 11 of 39 rows
    of the Lehigh Valley Hyundai section, which continues beyond this PDF and
    whose rows are another statement's). Else (None, why) -- why is "" when
    the rule does not even apply. Every condition must hold:
      - the only problems are unmatched printed lines (no wrong, extra or
        unverifiable row);
      - every matched row sits under one store header, and that store is the
        statement's vendor (_same_vendor);
      - that section is complete: printed row numbers exactly 1..N for its
        "Invoices: N", and its rows sum to its printed "Amount Due" to the cent;
      - every unmatched line sits under a store header whose name is NOT this
        vendor's."""
    if not vendor_name or any(f["problem"] != "missing" for f in failures):
        return None, ""
    stores = {(line.get("store") or {}).get("name") for _, line in matches}
    if len(stores) != 1 or None in stores:
        return None, "the verified rows are not all under one printed store header"
    name = next(iter(stores))
    if not _same_vendor(name, vendor_name):
        return None, f"the rows' section {name!r} is not the statement's vendor {vendor_name!r}"
    store = next(line["store"] for _, line in matches)
    lines = [line for _, line in matches]
    numbers = sorted(l["row_number_printed"] for l in lines) if all(l["row_number_printed"] is not None for l in lines) else None
    total = round(sum(_printed_net(l) for l in lines), 2)
    if numbers != list(range(1, store["count"] + 1)):
        return None, f"section {name!r} is not complete: printed row numbers are not exactly 1..{store['count']}"
    if abs(round(total - store["amount_due"], 2)) >= _CENT:
        return None, f"section {name!r} rows sum to {total:,.2f}, printed Amount Due {store['amount_due']:,.2f}"
    matched = {id(l) for l in lines}
    ignored = []
    for line in table:
        if not line["is_transaction"] or id(line) in matched:
            continue
        other = (line.get("store") or {}).get("name")
        if other is None:
            return None, f"an unmatched printed line is under no store header (p{line['page']}: {line['text'][:60]})"
        if _same_vendor(other, vendor_name):
            return None, f"an unmatched printed line is under the vendor's own section {other!r} (p{line['page']})"
        ignored.append({"page": line["page"], "section": other, "text": line["text"][:80]})
    if len(ignored) != len(failures):
        return None, "the unmatched lines do not account for every problem"
    return {"section_used": {"section": name, "invoices": store["count"], "amount_due": store["amount_due"],
                             "rows": len(lines)},
            "lines_ignored": ignored}, None


def check_pdf_store_sections(printed, rows, *, tolerance=0.01, pdf_path=None, budget_seconds=OCR_TIME_BUDGET_SECONDS,
                             vendor_name=None, **_):
    """Gate method "pdf_store_sections" (see the module docstring). A store
    is complete only when its rows sum to its printed Amount Due exactly to
    the cent. The computed figure is the sum of the complete stores' printed
    Amount Due;
    the printed total is the group's and is recorded, not reconciled."""
    started = time.monotonic()
    if not pdf_path:
        return _not_applicable("no PDF available")
    if not rows:
        return _not_applicable("no rows")
    if printed is None:
        return _not_applicable("no printed total")
    try:
        pages, table, matches, failures, rereads = _analyse(rows, pdf_path, budget_seconds)
    except NotVerified as e:
        return {"applicable": True, "passed": False, "computed": None, "reason": f"not verified: {e}",
                "seconds": round(time.monotonic() - started, 2)}
    headers = [l for l in table if l["is_store_header"]]
    if not headers:
        return _not_applicable("no printed store headers (\"<store> Invoices: N | Amount Due: $X\")")
    result = _row_result(pages, table, rows, matches, failures, rereads, started)
    if failures:
        section, why = _vendor_section(table, matches, failures, vendor_name)
        if section is None:
            if why:
                result["section_rule"] = why
            return result
        # One complete section of this vendor, everything else under other
        # named sections (2026-10-19, LV Honda STMT-4E854578).
        result.pop("offending_rows", None)
        result.pop("problem_counts", None)
        result.update(section)
        if not _printed_anywhere(table, printed, exclude={id(l) for _, l in matches}):
            result["reason"] = f"printed total {printed:,.2f} is not printed on the PDF outside the rows"
            return result
        result.update(passed=True, computed=section["section_used"]["amount_due"], reason="")
        return result
    stores = OrderedDict()
    for line in table:
        if line["is_store_header"]:
            h = _STORE_HEADER_RE.match(line["text"])
            stores.setdefault(h.group("store").strip(" |:"), {"count": int(h.group("count")),
                                                               "amount_due": float(h.group("amount").replace(",", "")),
                                                               "lines": []})
    for _, line in matches:
        store = line.get("store")
        if store is None or store["name"] not in stores:
            result["reason"] = f"a verified row is not under any printed store header (p{line['page']}: {line['text'][:60]})"
            return result
        stores[store["name"]]["lines"].append(line)
    sections, complete_total, problems = [], 0.0, []
    for name, s in stores.items():
        numbers = [l["row_number_printed"] for l in s["lines"]]
        total = round(sum(_printed_net(l) for l in s["lines"]), 2)
        entry = {"section": name, "printed_invoices": s["count"], "printed_amount_due": s["amount_due"],
                 "rows_in_file": len(numbers), "rows_total": total}
        if not numbers:
            entry["status"] = "header only"
        elif any(n is None for n in numbers):
            entry["status"] = "failing"
            problems.append(f"{name}: a row has no printed row number")
        elif len(set(numbers)) != len(numbers):
            entry["status"] = "failing"
            problems.append(f"{name}: duplicated printed row numbers")
        elif min(numbers) < 1 or max(numbers) > s["count"]:
            entry["status"] = "failing"
            problems.append(f"{name}: printed row numbers outside 1..{s['count']}")
        elif sorted(numbers) == list(range(1, s["count"] + 1)) and abs(round(total - s["amount_due"], 2)) < _CENT:
            entry["status"] = "complete+reconciled"
            complete_total += s["amount_due"]
        elif sorted(numbers) == list(range(1, s["count"] + 1)):
            entry["status"] = "failing"
            problems.append(f"{name}: all {s['count']} rows present but they sum to {total:,.2f}, "
                            f"printed Amount Due {s['amount_due']:,.2f}")
        else:
            entry["status"] = "partial"
        if numbers and entry["status"] != "failing":
            entry["row_numbers"] = f"{min(numbers)}-{max(numbers)}"
        sections.append(entry)
    result["sections"] = sections
    result["printed_total_is_sum_of_sections"] = abs(round(printed - sum(s["amount_due"] for s in stores.values()), 2)) <= tolerance
    if problems:
        result["reason"] = "; ".join(problems)
        return result
    if not any(s["status"] == "complete+reconciled" for s in sections):
        result["reason"] = "no store section is complete in this file"
        return result
    if not _printed_anywhere(table, printed, exclude={id(l) for _, l in matches}):
        result["reason"] = f"printed total {printed:,.2f} is not printed on the PDF outside the rows"
        return result
    result.update(passed=True, computed=round(complete_total, 2), reason="")
    return result


# Labels of a printed statement total. A PDF that prints any of them next to
# an amount has a total, so the no-total rule must not apply to it -- even
# when the extraction missed that total (NYE 9-4-26 prints a NEW BALANCE per
# account).
_PRINTED_TOTAL_LABELS = ("total", "balance due", "amount due", "new balance", "pay this amount", "please pay")


def check_rows_only(rows, pdf_path, budget_seconds=OCR_TIME_BUDGET_SECONDS, printed=None):
    """For a statement with NO printed total: every extracted row against its
    PDF line and every PDF transaction line against a row, with no equation
    (2026-10-12, user decision: this is the statement's pass/fail).
    Returns {"status": "rows_verified" | "rows_do_not_match" | "not_verified"
    | "has_printed_total", ...}; only "rows_verified" is a pass. Same 30 s
    OCR budget and 12-page cap as the other PDF checks."""
    started = time.monotonic()
    if printed is not None:
        return {"status": "has_printed_total", "reason": f"the extraction has a printed total ({printed})"}
    if not pdf_path or not rows:
        return {"status": "not_verified", "reason": "no PDF" if not pdf_path else "no rows"}
    try:
        pages, table, matches, failures, rereads = _analyse(rows, pdf_path, budget_seconds, allow_balance_only=True)
    except NotVerified as e:
        return {"status": "not_verified", "reason": str(e), "seconds": round(time.monotonic() - started, 2)}
    total_lines = [l for l in table if l["money"] and any(k in l["text"].lower() for k in _PRINTED_TOTAL_LABELS)]
    result = _row_result(pages, table, rows, matches, failures, rereads, started)
    result.pop("passed", None)
    result.pop("computed", None)
    result.pop("applicable", None)
    if total_lines:
        result.update(status="has_printed_total",
                      reason=f"the PDF prints a total (p{total_lines[0]['page']}: {total_lines[0]['text'][:80]})")
    elif failures:
        result.update(status="rows_do_not_match", offending_rows=failures[:10])
    else:
        result.update(status="rows_verified", reason="")
    return result


# --------------------------------------------------------------------------
# pdf_full_match: every row and every column, no equation (2026-10-16)
# --------------------------------------------------------------------------

FULL_MATCH_LABEL = "PDF full match (every row and column)"
# _raw_row keys that are not printed columns: the model's per-row
# confidence, its section name and the split-upload page tag.
_NOT_A_COLUMN = frozenset({"confidence", "section", "_page"})
_MONEY_KINDS = frozenset({"charge", "credit", "signed", "balance", "unalloc", "total"})


def _squash(text) -> str:
    return re.sub(r"[^0-9a-z]", "", str(text or "").lower())


def _norm_text(text) -> str:
    """Free text compared without case, spacing or punctuation."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]|_", " ", str(text or "").lower())).strip()


def _cell_kind(column) -> str:
    role = column["role"]
    if role == "date":
        return "date"
    if role == "ref":
        return "ref"
    if role in _MONEY_KINDS:
        return "money"
    return "text"


def _blank(value) -> bool:
    return value is None or str(value).strip() == ""


def _as_money(value) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return parse_money(re.sub(r"\s+", "", str(value)))


def _same_date(a, b) -> bool:
    da, db = parse_date(a), parse_date(b)
    if da is None or db is None:
        return False
    if da.year == 2000 or db.year == 2000:  # a printed date with no year
        return (da.month, da.day) == (db.month, db.day)
    return da == db


def cell_equals(kind: str, extracted, printed: str) -> bool:
    """One extracted cell against the text printed in its column."""
    if _blank(extracted) or _blank(printed):
        return _blank(extracted) and _blank(printed)
    if kind == "money":
        e, p = _as_money(extracted), _as_money(printed)
        return e is not None and p is not None and abs(e - p) <= _CENT
    if kind == "date":
        return _same_date(extracted, printed)
    if kind == "ref":
        return norm_invoice(extracted) == norm_invoice(printed) != ""
    e_money, p_money = _as_money(extracted), _as_money(printed)
    if e_money is not None and p_money is not None:
        return abs(e_money - p_money) <= _CENT
    return _norm_text(extracted) == _norm_text(printed)


def _column_map(columns, keys):
    """({id(printed header column): extracted key}, [printed headers with no
    extracted column]). A header matches the key whose name is the same once
    case, spacing and punctuation are dropped, else the one key (3+
    characters) containing it or contained in it."""
    def squash(text):  # the invoice-number O/0, l/I/1 tolerance too (Chuck's "Sls" read as "SIs")
        return _squash(str(text or "").translate(_INVOICE_TRANSLATE))

    mapping, missing, taken = {}, [], set()
    for c in columns:
        sq = squash(c["text"])
        same = [k for k in keys if squash(k) == sq]
        near = [k for k in keys if len(sq) >= 3 and len(squash(k)) >= 3 and (sq in squash(k) or squash(k) in sq)]
        key = same[0] if len(same) == 1 else (near[0] if not same and len(near) == 1 else None)
        if key is None or key in taken:
            missing.append(c["text"])
            continue
        mapping[id(c)] = key
        taken.add(key)
    return mapping, missing


def _find_value_words(words, value, free):
    """The word(s) on a line holding `value` (one word, or up to four
    consecutive ones), only among word ids in `free`; None if absent."""
    target_money, target_text = _as_money(value), _norm_text(value)
    for size in (1, 2, 3, 4):
        for start in range(0, len(words) - size + 1):
            run = words[start:start + size]
            if not all(id(w) in free for w in run):
                continue
            text = " ".join(w["text"] for w in run)
            if target_money is not None:
                if _as_money(text) is not None and abs(_as_money(text) - target_money) <= _CENT:
                    return run
            elif target_text and _norm_text(text) == target_text:
                return run
    return None


def check_pdf_full_match(printed, rows, *, tolerance=0.01, pdf_path=None, budget_seconds=OCR_TIME_BUDGET_SECONDS, **_):
    """Gate method "pdf_full_match" (see the module docstring). Runs only
    after every other method has failed and can only add a pass."""
    started = time.monotonic()
    if not pdf_path:
        return _not_applicable("no PDF available")
    if not rows:
        return _not_applicable("no rows")
    if not all(isinstance(inv.get("_raw_row"), dict) and inv["_raw_row"] for inv in rows):
        return _not_applicable("a row has no extracted cells (_raw_row) to compare")
    try:
        pages, table, matches, failures, rereads = _analyse(rows, pdf_path, budget_seconds)
    except NotVerified as e:
        return {"applicable": True, "passed": False, "computed": None, "reason": f"not verified: {e}",
                "seconds": round(time.monotonic() - started, 2)}
    result = _row_result(pages, table, rows, matches, failures, rereads, started)
    if failures:
        return result
    if len(matches) != len(rows) or len({id(line) for _, line in matches}) != len(matches):
        result["reason"] = "rows and PDF lines are not one-to-one"
        return result
    keys = []
    for inv in rows:
        keys += [k for k in inv["_raw_row"] if k not in _NOT_A_COLUMN and k not in keys]
    reread = _Rereader(pdf_path, started + budget_seconds) if any(p["source"] == "ocr" for p in pages) else None
    column_report, problems, unlabelled_keys = OrderedDict(), [], []
    for inv, line in matches:
        columns = line["columns"] or []
        mapping, missing = _column_map(columns, keys)
        if missing:
            problems.append(f"printed column(s) {missing} not in the extraction (p{line['page']})")
            break
        unlabelled = [k for k in keys if k not in set(mapping.values())]
        unlabelled_keys = unlabelled_keys or unlabelled
        raw = inv["_raw_row"]
        free = {id(w) for w in line["words"]}
        # A column the PDF prints without a header (the model's UNLABELED_*
        # columns) claims its words first, so they can't be taken for a
        # neighbouring labelled column's cell.
        for key in unlabelled:
            entry = column_report.setdefault(key, {"printed": None, "extracted_as": key, "kind": "unlabelled",
                                                   "cells": 0, "ok": 0})
            entry["cells"] += 1
            if _blank(raw.get(key)):
                entry["ok"] += 1
                continue
            run = _find_value_words(line["words"], raw.get(key), free)
            if run is None:
                entry.setdefault("problem", f"p{line['page']}: {raw.get(key)!r} not on the line")
                problems.append(f"unlabelled column {key}: {raw.get(key)!r} not on the PDF line (p{line['page']})")
                continue
            entry["ok"] += 1
            free -= {id(w) for w in run}
        # The line's words, left to right, must be used up exactly by the
        # row's cells in header order: a printed value no cell holds, or a
        # cell whose value is not printed next, fails. Amounts, dates and
        # references must also sit under their own header (wrong column =
        # fail); free text may run past its header's edges, as printed text
        # does.
        words = sorted((w for w in line["words"] if id(w) in free), key=lambda w: w["x0"])
        pos, line_failed = 0, False
        for c in sorted(columns, key=lambda col: col["x0"]):
            key = mapping[id(c)]
            value = raw.get(key)
            kind = _cell_kind(c)
            entry = column_report.setdefault(c["text"], {"printed": c["text"], "extracted_as": key, "kind": kind,
                                                         "cells": 0, "ok": 0})
            entry["cells"] += 1
            if _blank(value):
                entry["ok"] += 1  # a value printed here anyway is left over -> caught below
                continue
            run, problem = None, None
            if kind == "money" and _as_money(value) is None:
                # An amount column whose extracted cell is not an amount -- e.g.
                # Autoly's "Due" amount merged into the description text
                # ("650.00 2015 MERCEDES ...") -- means the amount was never
                # extracted: the same failure as Chuck's missing Due column.
                problem = f"amount column {c['text']} holds non-amount {value!r}"
                entry.setdefault("problem", f"p{line['page']} {inv.get('invoice_number')}: {problem}")
                problems.append(f"{c['text']}: {inv.get('invoice_number')} {problem} (p{line['page']})")
                line_failed = True
                break
            for k in range(1, min(16, len(words) - pos) + 1):
                if cell_equals(kind, value, " ".join(w["text"] for w in words[pos:pos + k])):
                    run = words[pos:pos + k]
                    break
            if run is not None and kind != "text" and not all(column_of(w, columns) is c for w in run):
                under = column_of(run[0], columns)
                problem = f"{value!r} is printed under {under['text'] if under else 'no column'}, not {c['text']}"
                run = None
            if run is None and problem is None and reread is not None and line["source"] == "ocr" and not line.get("rotation"):
                # A disputed scanned cell: one equality-only re-read (_Rereader)
                # of the words OCR placed under this column here.
                under = []
                while pos + len(under) < len(words) and column_of(words[pos + len(under)], columns) is c:
                    under.append(words[pos + len(under)])
                if under:
                    pad = 0.6 * line["height"]
                    box = (min(w["x0"] for w in under) - pad, line["top"] - pad,
                           max(w["x1"] for w in under) + pad, line["bottom"] + pad)
                    whitelist = "".join(sorted(set(re.sub(r"\s", "", str(value))) | set("0123456789.,-/()$")))
                    got = " ".join(w["text"] for w in reread._ocr(line["page"], box, whitelist, 7) or [])
                    accepted = bool(got) and cell_equals(kind, value, got)
                    rereads.append({"page": line["page"], "kind": f"{kind} cell ({c['text']})",
                                    "ocr": " ".join(w["text"] for w in under), "reread": got, "extracted": str(value),
                                    "accepted": accepted})
                    if accepted:
                        run = under
                        entry["rereads_accepted"] = entry.get("rereads_accepted", 0) + 1
            if run is not None:
                entry["ok"] += 1
                pos += len(run)
                continue
            printed_next = " ".join(w["text"] for w in words[pos:pos + 4]) or "nothing"
            problem = problem or f"extracted {value!r}, the PDF prints {printed_next!r} next"
            entry.setdefault("problem", f"p{line['page']} {inv.get('invoice_number')}: {problem}")
            problems.append(f"{c['text']}: {inv.get('invoice_number')} {problem} (p{line['page']})")
            line_failed = True
            break
        if not line_failed and pos < len(words):
            left = " ".join(w["text"] for w in words[pos:])
            problems.append(f"{inv.get('invoice_number')}: the PDF also prints {left!r}, which no extracted cell holds "
                            f"(p{line['page']})")
    result["columns"] = list(column_report.values())
    if unlabelled_keys:
        result["unlabelled_columns"] = unlabelled_keys
    if rereads:
        result["ocr_rereads"] = rereads
    result["seconds"] = round(time.monotonic() - started, 2)
    if problems:
        result["reason"] = f"{len(problems)} cell/column problem(s): " + "; ".join(problems[:5])
        return result
    result.update(passed=True, computed=round(sum(_printed_net(line) for _, line in matches), 2), reason="")
    return result
