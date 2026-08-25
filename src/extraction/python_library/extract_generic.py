"""
Generic, vendor-agnostic extractor for text-embedded vendor statement PDFs.

Unlike every other extract_<vendor>.py module in this folder (each hand-
tuned to one vendor's exact column x-positions / header wording / row
quirks), this module never hardcodes a vendor name, a signature string, or
a pixel column boundary. For any new text-embedded statement it has never
seen, it:

  1. Tries pdfplumber's ruled-line table detection (extract_tables(),
     default "lines" strategy) on each page - the foundation requested.
  2. If that finds nothing usable, tries pdfplumber's "text" strategy
     table detection (clusters words into a grid without needing ruled
     lines).
  3. If that ALSO finds nothing usable, falls back to a generic header-
     driven column detector: it looks for a row of words matching known
     header-keyword synonyms (DATE, INVOICE, CHARGE, CREDIT, BALANCE, ...),
     turns that row's word positions into column boundaries, and buckets
     every later row's words into those columns by x-position - the same
     general technique used by hand in extract_empire.py / extract_quirk.py
     / etc., just derived from the header text instead of a human measuring
     pixel positions per vendor.

Known, deliberate scope limits (see the honesty write-up this was tested
against for concrete per-vendor pass/fail evidence):
  - A vendor whose row boundary is NOT "does this row have a date" (e.g. a
    statement that prints several genuinely distinct charge/credit rows
    under one suppressed/blank date, distinguished only by some other
    per-row token) will not be reconstructed correctly by the continuation-
    row merge logic below, which assumes a row lacking a recognizable date
    is a wrapped continuation of the row above it, not a new transaction.
  - Column-role assignment depends on the header wording matching the
    synonym table in HEADER_SYNONYM_TESTS. A header using vocabulary not
    represented there will leave that column unclassified (dropped, not
    guessed at).
"""

import re
import sys

import pdfplumber

ROW_TOLERANCE = 3.0
# Measured across every sample vendor's header row: within-phrase word gaps
# ("Invoice"->"#", "Due"->"Date", "Core"->"Chg") are consistently ~2-3px;
# real inter-column gaps are consistently >=12px. 8px cleanly separates them.
HEADER_PHRASE_GAP = 8.0
# Max vertical gap (in 'top' units) between two physical lines for them to
# be considered part of the same wrapped, multi-line column header (e.g. a
# "Transaction" / "Date" stack for one "Transaction Date" column).
HEADER_ROW_MERGE_GAP = 8.0

DATE_RES = [
    re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$"),      # 07/06/26, 07/06/2026
    re.compile(r"^\d{2}[A-Z]{3}\d{2}$"),           # 23DEC25
    re.compile(r"^\d{1,2}-\d{1,2}(-\d{2,4})?$"),   # 07-07, 07-07-26
]
MONEY_RE = re.compile(r"^\(?-?\$?\s?[\d,]+\.\d{2}-?\)?$")
INVOICE_HASH_RE = re.compile(r"#[A-Za-z]*(\d+)")

TOTALS_BLACKLIST_RE = re.compile(
    r"\b(GRAND TOTAL|SUBTOTAL|SUB TOTAL|MONTH TOTALS?|NEW BALANCE|"
    r"BALANCE FORWARD|TOTAL OUTSTANDING|TOTAL UNAPPLIED|TOTAL BALANCE|"
    r"TOTAL DUE|PAST DUE|AGE OF OUTSTANDING|PLEASE PAY|AMOUNT DUE:|"
    r"CURRENT\s+\S*\s*DAYS|STATEMENT DATE|ACCOUNT NO)\b",
    re.IGNORECASE,
)

FIELDNAMES = [
    "page", "row_kind", "date", "invoice_number", "reference", "description",
    "charge", "credit", "balance", "amount_generic",
]


# ---------------------------------------------------------------------------
# Header keyword -> canonical column role
# ---------------------------------------------------------------------------

def classify_header_phrase(text):
    """Maps a header phrase (already whitespace-normalized) to one of
    DATE / DUE_DATE / INVOICE / REFERENCE / DESCRIPTION / CHARGE / CREDIT /
    BALANCE, generously matching common vendor-statement synonyms. Returns
    None for header text this table doesn't need to understand (e.g. "Age",
    "Source", "Store", "Page")."""
    t = text.upper().strip()
    t = re.sub(r"\s+", " ", t)

    if "DATE" in t:
        return "DUE_DATE" if "DUE" in t else "DATE"

    if re.search(r"\bREFERENCE\s*(NO\.?|NUMBER|#)\b", t):
        return "INVOICE"
    if "INVOICE" in t or "DOC" in t:
        return "INVOICE"
    if re.search(r"\bREFERENCE\b", t):
        return "REFERENCE"
    if re.search(r"\b(PURCHASE ORDER|WORK ORDER|\bPO\b|\bRO\b)\b", t):
        return "REFERENCE"
    if re.search(r"\b(DESCRIPTION|MESSAGE)\b", t):
        return "DESCRIPTION"

    if re.search(r"\b(CHARGES?|PURCHASES?|DEBITS?)\b", t):
        return "CHARGE"
    if re.search(r"\b(CREDITS?|PAYMENTS?)\b", t):
        return "CREDIT"
    if re.search(r"\b(BALANCE|OUTSTANDING|OPEN AMOUNT)\b", t):
        return "BALANCE"
    if re.search(r"\bAMOUNT\b", t):
        return "CHARGE"

    return None


# ---------------------------------------------------------------------------
# Word / row grouping helpers
# ---------------------------------------------------------------------------

def group_rows(words, tol=ROW_TOLERANCE):
    rows = []
    current_top = None
    current_row = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if current_top is None or abs(w["top"] - current_top) <= tol:
            current_row.append(w)
            current_top = w["top"] if current_top is None else current_top
        else:
            rows.append(current_row)
            current_row = [w]
            current_top = w["top"]
    if current_row:
        rows.append(current_row)
    return rows


def merge_into_phrases(row_words, gap=HEADER_PHRASE_GAP):
    ws = sorted(row_words, key=lambda w: w["x0"])
    phrases = []
    current = []
    for w in ws:
        if current and (w["x0"] - current[-1]["x1"]) > gap:
            phrases.append(current)
            current = [w]
        else:
            current.append(w)
    if current:
        phrases.append(current)
    return [
        {"text": " ".join(x["text"] for x in p), "x0": p[0]["x0"], "x1": p[-1]["x1"]}
        for p in phrases
    ]


def detect_header(row_words):
    """Returns a list of {"role", "x0", "x1"} column definitions if this row
    looks like a real column header, else None."""
    phrases = merge_into_phrases(row_words)
    classified = [(p, classify_header_phrase(p["text"])) for p in phrases]
    roles_found = {role for _, role in classified if role}
    if len(roles_found) < 2:
        return None
    if "DATE" not in roles_found and "INVOICE" not in roles_found:
        return None

    columns = []
    seen_roles = set()
    for i, (p, role) in enumerate(classified):
        if not role:
            # Header text we don't have a synonym for (e.g. a "Store",
            # "Source", "Age", row-number "#" column). Still reserve this
            # phrase's own column slot - via a unique, never-read role name
            # - so its words get bucketed into their OWN column instead of
            # bleeding into a neighboring classified column and corrupting
            # it (e.g. a bare store-number column sitting between DATE and
            # INVOICE would otherwise glue onto the invoice number).
            columns.append({"role": f"_ignored_{i}", "x0": p["x0"], "x1": p["x1"]})
            continue
        if role in seen_roles:
            # Duplicate role (e.g. a remittance-stub echo of "Invoice #" /
            # "Amount Due" further right on the page) - keep only the
            # left-most occurrence as authoritative, matching how several
            # of the hand-written vendor extractors explicitly ignore the
            # tear-off duplicate columns. Still reserve its column slot
            # (as unread) so it doesn't bleed into a real neighbor either.
            columns.append({"role": f"_ignored_{i}", "x0": p["x0"], "x1": p["x1"]})
            continue
        seen_roles.add(role)
        columns.append({"role": role, "x0": p["x0"], "x1": p["x1"]})
    return columns if columns else None


def build_column_bounds(columns, page_width):
    """Column boundaries at the midpoints between adjacent header phrases,
    same convention every hand-written extractor in this folder uses."""
    columns = sorted(columns, key=lambda c: c["x0"])
    bounds = []
    for i, col in enumerate(columns):
        lo = 0.0 if i == 0 else (columns[i - 1]["x1"] + col["x0"]) / 2.0
        hi = page_width if i == len(columns) - 1 else (col["x1"] + columns[i + 1]["x0"]) / 2.0
        bounds.append((col["role"], lo, hi))
    return bounds


def bucket_words(words, bounds):
    cols = {role: [] for role, _, _ in bounds}
    for w in words:
        xmid = (w["x0"] + w["x1"]) / 2.0
        target = None
        for role, lo, hi in bounds:
            if lo <= xmid < hi:
                target = role
                break
        if target is None:
            target = bounds[-1][0] if xmid >= bounds[-1][1] else bounds[0][0]
        cols[target].append(w)
    return {role: " ".join(w["text"] for w in sorted(ws, key=lambda w: w["x0"])) for role, ws in cols.items()}


def is_date(s):
    s = (s or "").strip()
    return bool(s) and any(r.match(s) for r in DATE_RES)


def clean_money(raw):
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or not MONEY_RE.match(s):
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    if s.endswith("-"):
        neg = True
        s = s[:-1]
    if s.startswith("-"):
        neg = True
        s = s[1:]
    s = s.replace("$", "").replace(",", "")
    try:
        val = float(s)
    except ValueError:
        return None
    return -val if neg else val


def row_text(cols):
    return " ".join(v for v in cols.values() if v)


# ---------------------------------------------------------------------------
# Tier 1/2: pdfplumber table-detection foundation
# ---------------------------------------------------------------------------

def try_table_strategy(page, carried_schema=None, table_settings=None):
    """Attempts pdfplumber's built-in table extraction. Returns
    (rows, schema) if a usable table is found on this page, else None.
    "Usable" means either: (a) this table's own first row classifies as a
    real header (>=2 known column roles, including DATE or INVOICE), or
    (b) no classifiable header is present but carried_schema was handed in
    from a previous page and this table has the same column count - many
    multi-page ruled-line statements only print the header once, on page 1,
    and every later page's "table" is pure data with the same column
    layout, so the previous page's column-role-by-index mapping is reused
    and this table's first row is treated as data, not header."""
    try:
        tables = page.extract_tables(table_settings) if table_settings else page.extract_tables()
    except Exception:
        return None
    if not tables:
        return None

    best = None
    for table in tables:
        if not table:
            continue
        header_cells = [(c or "").strip() for c in table[0]]
        role_by_index = {}
        seen_roles = set()
        for i, cell in enumerate(header_cells):
            role = classify_header_phrase(cell)
            if role and role not in seen_roles:
                role_by_index[i] = role
                seen_roles.add(role)

        header_is_real = len(seen_roles) >= 2 and ("DATE" in seen_roles or "INVOICE" in seen_roles)
        if header_is_real:
            body_rows_raw = table[1:]
            use_role_by_index = role_by_index
            new_schema = {"role_by_index": role_by_index, "ncols": len(header_cells)}
        elif carried_schema and carried_schema["ncols"] == len(header_cells):
            body_rows_raw = table  # no real header on this page - it's all data
            use_role_by_index = carried_schema["role_by_index"]
            new_schema = carried_schema
        else:
            continue

        rows_out = []
        date_hits = 0
        bad = False
        for raw_row in body_rows_raw:
            cols = {role: (raw_row[i] or "").strip() if i < len(raw_row) else "" for i, role in use_role_by_index.items()}
            if any("\n" in (v or "") for v in cols.values()):
                # pdfplumber collapsed multiple physical rows into one
                # newline-joined cell per column - unusable without a
                # reliable way to zip differing per-column line counts
                # back together (see extract_wilberts.py's docstring for
                # exactly this failure mode). Bail out of this table.
                bad = True
                break
            rows_out.append(cols)
            if is_date(cols.get("DATE", "")):
                date_hits += 1

        if bad or not rows_out:
            continue
        if "DATE" in use_role_by_index.values() and date_hits == 0:
            continue  # a date column is mapped but no row ever had one - not real tabular data

        if best is None or len(rows_out) > len(best[0]):
            best = (rows_out, new_schema)

    return best


# ---------------------------------------------------------------------------
# Tier 3: generic header-driven word-bucketing fallback
# ---------------------------------------------------------------------------

def find_header(rows, start_idx):
    """Tries to detect a column header starting at rows[start_idx], allowing
    the header to be wrapped across up to 3 consecutive physical lines (e.g.
    a "Transaction" / "date" stack for one column, printed on a different
    baseline than the rest of the header row). Returns (header_cols,
    rows_consumed) or (None, 0)."""
    row = rows[start_idx]
    header_cols = detect_header(row)
    consumed = 1

    for extra in (1, 2):
        if start_idx + extra >= len(rows):
            break
        prev_top = rows[start_idx + extra - 1][0]["top"]
        this_top = rows[start_idx + extra][0]["top"]
        if this_top - prev_top > HEADER_ROW_MERGE_GAP:
            break
        combined_words = [w for r in rows[start_idx:start_idx + extra + 1] for w in r]
        combined_cols = detect_header(combined_words)
        if combined_cols and (header_cols is None or len(combined_cols) > len(header_cols)):
            header_cols = combined_cols
            consumed = extra + 1

    return (header_cols, consumed) if header_cols else (None, 0)


def extract_page_words_fallback(page, carried_bounds):
    words = page.extract_words()
    rows = group_rows(words)
    bounds = carried_bounds
    body_rows = []
    header_locked = False

    i = 0
    while i < len(rows):
        if not header_locked:
            header_cols, consumed = find_header(rows, i)
            if header_cols:
                bounds = build_column_bounds(header_cols, page.width)
                header_locked = True
                i += consumed
                continue

        if bounds is None:
            i += 1
            continue

        cols = bucket_words(rows[i], bounds)
        i += 1
        text_all = row_text(cols)
        if not text_all.strip():
            continue
        if TOTALS_BLACKLIST_RE.search(text_all):
            continue

        date_val = cols.get("DATE", "")
        has_id = bool(cols.get("INVOICE", "").strip())
        money_hits = sum(1 for r in ("CHARGE", "CREDIT", "BALANCE") if MONEY_RE.match(cols.get(r, "").strip() or ""))

        if is_date(date_val) and (has_id or money_hits):
            body_rows.append({"kind": "row", "cols": cols})
        elif money_hits >= 2 and not is_date(date_val):
            # A dateless row carrying two or more money-looking values across
            # different columns is almost always a totals/aging-summary block
            # (e.g. "Current / Over 30 / Over 60 / Over 90"), not a wrapped
            # continuation of the row above - genuine wrapped text (a
            # description or reference fragment) never carries its own money
            # values in this dataset. Drop it rather than merging it in.
            continue
        elif len(text_all) > 100 and not is_date(date_val):
            # A dateless "continuation candidate" this long is almost always
            # a legal/finance-charge disclaimer paragraph printed at the
            # bottom of the page, not a wrapped fragment of the row above -
            # every genuine wrapped continuation in this dataset (a vehicle
            # description, a "DT#nnnnnn" reference tail) is well under 100
            # characters. Drop it rather than merging it in and corrupting
            # the last real row on the page.
            continue
        elif body_rows and (has_id or money_hits or text_all.strip()):
            body_rows.append({"kind": "continuation", "cols": cols})
        # else: stray/blank/unclassifiable row - dropped.

    return body_rows, bounds


def merge_continuations(raw_rows):
    merged = []
    for entry in raw_rows:
        if entry["kind"] == "row":
            merged.append(dict(entry["cols"]))
            continue
        if not merged:
            continue
        prev = merged[-1]
        for role, val in entry["cols"].items():
            if not val:
                continue
            if not prev.get(role):
                prev[role] = val
            else:
                prev[role] = f"{prev[role]} {val}".strip()
    return merged


# ---------------------------------------------------------------------------
# Top-level per-document extraction
# ---------------------------------------------------------------------------

def finalize_row(page_num, cols, method):
    charge = clean_money(cols.get("CHARGE", ""))
    credit = clean_money(cols.get("CREDIT", ""))
    balance = clean_money(cols.get("BALANCE", ""))

    # Split-charge/credit handling: if the document only ever populates one
    # of CHARGE/CREDIT (a single combined amount column), infer the other
    # from sign. If both a CHARGE-role and CREDIT-role column exist
    # separately (already split on the page), leave them exactly as read -
    # a row legitimately may have only one of the two filled in.
    if charge is not None and credit is None and charge < 0:
        credit, charge = -charge, None

    amount_generic = charge if charge is not None else (-credit if credit is not None else balance)

    invoice_number = (cols.get("INVOICE") or "").strip()
    if not invoice_number:
        # No column was ever labeled INVOICE/DOC/etc., but a vendor may still
        # print "Invoice #12345" or "#INV160200" inline inside a free-text
        # description/reference column. "#" immediately followed by an
        # alphanumeric id is a common enough convention to treat generically
        # (not a vendor-specific pattern) - and it deliberately stops at the
        # last digit, so a glued trailing word like "#INV160200Pay" still
        # yields "INV160200", not "INV160200Pay".
        for source in (cols.get("DESCRIPTION"), cols.get("REFERENCE")):
            m = INVOICE_HASH_RE.search(source or "")
            if m:
                invoice_number = m.group(1)
                break

    return {
        "page": page_num,
        "row_kind": method,
        "date": (cols.get("DATE") or "").strip(),
        "invoice_number": invoice_number,
        "reference": (cols.get("REFERENCE") or "").strip(),
        "description": (cols.get("DESCRIPTION") or "").strip(),
        "charge": charge,
        "credit": credit,
        "balance": balance,
        "amount_generic": amount_generic,
    }


def extract(pdf_path):
    """Returns {"line_items": [...], "fieldnames": [...], "summary": {...},
    "full_text": None} - same shape as every extract_<vendor>.py module in
    this folder, so it's a drop-in alternative to any of them."""
    line_items = []
    carried_bounds = None
    carried_table_schema = None
    tier_used_per_page = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            result = try_table_strategy(page, carried_table_schema)
            tier = "table_lines"
            if not result:
                result = try_table_strategy(
                    page, carried_table_schema, {"vertical_strategy": "text", "horizontal_strategy": "text"}
                )
                tier = "table_text"
            if result:
                rows, carried_table_schema = result
                for cols in rows:
                    if not row_text(cols).strip():
                        continue
                    if TOTALS_BLACKLIST_RE.search(row_text(cols)):
                        continue
                    line_items.append(finalize_row(page_num, cols, tier))
                tier_used_per_page.append((page_num, tier))
                continue

            raw_rows, carried_bounds = extract_page_words_fallback(page, carried_bounds)
            merged = merge_continuations(raw_rows)
            for cols in merged:
                line_items.append(finalize_row(page_num, cols, "word_bucket_fallback"))
            tier_used_per_page.append((page_num, "word_bucket_fallback" if carried_bounds else "no_header_found"))

    summary = {
        "tier_used_per_page": tier_used_per_page,
        "line_item_count": len(line_items),
    }

    return {
        "line_items": line_items,
        "fieldnames": FIELDNAMES,
        "summary": summary,
        "full_text": None,
    }


if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "sample_pdfs/Astech Owego.pdf"
    result = extract(pdf_path)
    print(f"Line items extracted: {len(result['line_items'])}")
    print(f"Tiers used: {result['summary']['tier_used_per_page']}")
    for item in result["line_items"][:10]:
        print(item)
