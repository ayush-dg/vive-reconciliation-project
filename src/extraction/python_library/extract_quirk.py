"""
Extract Quirk Auto Group (Vive Collision - Colemans) parts/service account
statement PDF into:
  1. Quirk Colemans - line items.csv  (structured transaction list)
  2. Quirk Colemans - summary.csv     (header info + printed grand total)

This PDF has real embedded text (confirmed via pdfplumber probe - not a
scan), but page 1 (and every page) starts with a garbled, reversed run of
text ("The Reynolds and Reynolds Company" watermark, printed as vertical
characters along the left margin and read back-to-front by pdfplumber).
That text is harmless noise from a DMS-vendor logo, not statement data -
it sits at x0 ~20-27 with a very narrow x1 (<=27), so it never lands in
any of the real table columns (which all start at x0 >= 29) and never
matches any of the regexes below. Header regexes are anchored on literal
strings that appear well below the watermark ("DATE dd MMM yyyy acct#",
"VIVE COLLISION...") rather than assuming clean text from the top of the
page.

Same DMS family / same dual-column layout idea as Fred Beans
(extract_statement.py): each transaction row prints the invoice detail on
the left and a "please circle invoices being paid" remittance-stub echo
(date / invoice / balance) on the right. Native extract_table() does not
find ruled lines here, so rows are reconstructed from extract_words()
using x0 bucketing for the text columns and x1 (right-edge) bucketing for
the two money columns (amount / remit balance), the same technique used
in extract_statement.py because both money columns are right-aligned to a
fixed edge while their left edge shifts with digit count.

Column boundaries below were measured directly from this document's word
positions (see e.g. a plain detail row at top=347.3 on page 1):
    date            x0  29 - 54     "07-07"
    source          x0  71 - 76     "4"   (legend: 3=SERVICE 4=PARTS
                                            5=PAYMENT 11=ADJUSTMENT S=FINANCE)
    invoice         x0  98 - 158
    reference       x0 165 - 236
    description     x0 245 - 320    usually blank; holds things like the
                                     "PS" partial-shipment marker on a
                                     credit-memo continuation line, or a
                                     department subtotal code (e.g. "220",
                                     "H220"). No source="S" (finance
                                     charge) rows occur anywhere in this
                                     particular statement.
    amount          money, x1 <= 400   (e.g. "789.84" x1=358)
    age_in_days     x0 360 - 400       (e.g. "24")
    remit_date      x0 400 - 435       ("07-07" echoed, or "*****")
    remit_invoice   x0 435 - 520
    remit_balance   money, x1 >  400   (e.g. "789.84" x1=585)

A genuine transaction row is identified structurally (has a MM-DD date in
the date column AND a non-blank invoice column) rather than by its
position from the top of the page, so the reversed watermark text cannot
corrupt row detection. Rows lacking a date (e.g. the running combined-
amount line printed under a split credit memo, or the per-department
subtotal rows like "220  13637.26  *****  220  13637.26") are skipped as
line items - counting them would double count amounts already captured by
the individual detail rows above them.

The statement is organized into six vendor-code departments per account
(here: CV, JE, HY, SU, 7C, FO), each ending in a subtotal row. The final
page's "NEW BALANCE" box holds the grand total, and it equals the sum of
the six department subtotals, which in turn equals the sum of every
individual line item's amount - all three arithmetic paths agree.
"""

import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["QUIRK AUTO GROUP"]

ROW_TOLERANCE = 3.0

DATE_RE = re.compile(r"^\d{2}-\d{2}$")
MONEY_RE = re.compile(r"^-?[\d,]+\.\d{2}$")
SUBTOTAL_CODE_RE = re.compile(r"^[A-Z]{0,2}\d{2,4}$")

FIELDNAMES = [
    "page", "date", "source", "invoice", "reference", "description",
    "amount", "age_in_days", "remit_date", "remit_invoice", "remit_balance",
]


def classify_word(w):
    """Bucket a word into a column name using x0 for text columns and x1
    (right edge) for the two right-aligned money columns."""
    text, x0, x1 = w["text"], w["x0"], w["x1"]
    if MONEY_RE.match(text):
        return "amount" if x1 <= 400 else "remit_balance"
    if x0 < 60:
        return "date"
    if x0 < 90:
        return "source"
    if x0 < 160:
        return "invoice"
    if x0 < 245:
        return "reference"
    if x0 < 360:
        return "description"
    if x0 < 400:
        return "age_in_days"
    if x0 < 435:
        return "remit_date"
    if x0 < 520:
        return "remit_invoice"
    return "remit_balance"


WATERMARK_MAX_X1 = 28  # see module docstring: reversed watermark glyphs sit at x0 ~20-27


def drop_watermark(words):
    """The 'Reynolds and Reynolds' watermark is rendered as a handful of
    narrow, reversed-character strings stacked vertically at x0 ~20-27
    (x1 <= ~27), which is just left of where the real date column begins
    (x0 = 29). Without this filter, a watermark token can land within
    ROW_TOLERANCE of a real row's top and get merged into it, poisoning
    that row's 'date' bucket (x0 < 60) with garbage - e.g. it silently ate
    the SU department's subtotal row on page 4 until this filter was
    added. No real column ever starts left of x0=29, so this is safe."""
    return [w for w in words if w["x0"] >= WATERMARK_MAX_X1]


def group_rows(words):
    rows = []
    current_top = None
    current_row = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if current_top is None or abs(w["top"] - current_top) <= ROW_TOLERANCE:
            current_row.append(w)
        else:
            rows.append(current_row)
            current_row = [w]
        current_top = w["top"]
    if current_row:
        rows.append(current_row)
    return rows


def lines_for(words, x0_lo, x0_hi, top_lo, top_hi, tol=3.0):
    """Group words in a given (x0, top) window into text lines, left to
    right - used to pull the two side-by-side address blocks (customer
    bill-to on the left, vendor remit-to on the right) apart, since they
    sit on the same visual rows and plain extract_text() interleaves them
    into single merged/unmerged lines unpredictably."""
    ws = [w for w in words if x0_lo <= w["x0"] <= x0_hi and top_lo <= w["top"] <= top_hi]
    ws.sort(key=lambda w: (w["top"], w["x0"]))
    lines, current, last_top = [], [], None
    for w in ws:
        if last_top is None or abs(w["top"] - last_top) <= tol:
            current.append(w)
        else:
            lines.append(current)
            current = [w]
        last_top = w["top"]
    if current:
        lines.append(current)
    return [" ".join(x["text"] for x in sorted(line, key=lambda w: w["x0"])) for line in lines]


def parse_header_info(page1_text, page1_words):
    info = {}

    m = re.search(r"\bDATE (\d{2} [A-Z]{3} \d{4}) (\d+)\b", page1_text)
    if m:
        info["statement_date"] = m.group(1)
        info["account_number"] = m.group(2)

    customer_lines = lines_for(page1_words, 110, 300, 138, 210)
    vendor_lines = lines_for(page1_words, 440, 545, 138, 210)

    if len(customer_lines) >= 3:
        info["customer_name"] = customer_lines[0]
        info["billing_address_line1"] = customer_lines[1]
        info["billing_city_state_zip"] = customer_lines[2]
    if len(customer_lines) >= 4:
        info["customer_phone"] = customer_lines[3]

    if len(vendor_lines) >= 3:
        info["vendor_name"] = vendor_lines[0]
        info["remit_address_line1"] = vendor_lines[1]
        info["remit_city_state_zip"] = vendor_lines[2]
    if len(vendor_lines) >= 4:
        info["remit_phone"] = vendor_lines[3]

    return info


def parse_grand_total(last_page_words):
    """The final page's totals box has a 'NEW BALANCE' label with its
    value printed on the row below, x-aligned under the label."""
    rows = group_rows(last_page_words)
    for i, row in enumerate(rows):
        texts = [w["text"] for w in row]
        if "NEW" in texts and "BALANCE" in texts:
            bal_word = next(w for w in row if w["text"] == "BALANCE")
            for j in range(i + 1, min(i + 3, len(rows))):
                for w in rows[j]:
                    if MONEY_RE.match(w["text"]) and abs(w["x0"] - bal_word["x0"]) < 40:
                        return w["text"]
    return None


# How far below a header row's own top a value can sit and still count as
# "printed under that header" -- measured directly from this document (row
# 1: header top=702.5/703.1, its furthest value -- PAY THIS AMOUNT, in the
# remittance-stub column -- sits at top=720.5, diff=18.0; row 2: header
# top=728.0, value top=737.5-738.9, diff up to 10.9). 20 covers both with
# margin but stays well short of the next header row entirely (diff 25+),
# so a header row's own digit tokens (e.g. the literal "120" in "OVER 120
# DAYS") are never mistaken for a value.
AGING_VALUE_TOP_WINDOW = 20


def _bucket_by_x0(anchors_x0):
    """Turns a dict of {field_name: header_x0} into column (lo, hi) ranges
    using the midpoint between each header and its next-rightmost neighbor
    -- the same column-boundary-bucketing technique classify_word() and
    extract_wilberts.py's bucket_column() already use, chosen over a fixed
    +/- tolerance around each header's own x0 because the bucket headers
    here are uneven widths ("CURRENT" vs "PAY THIS AMOUNT") and a value's
    left edge doesn't sit a fixed distance from its header's left edge."""
    ordered = sorted(anchors_x0.items(), key=lambda kv: kv[1])
    bounds = {}
    for i, (name, x0) in enumerate(ordered):
        lo = x0 - 40 if i == 0 else (ordered[i - 1][1] + x0) / 2
        # Cap the rightmost column's own width instead of leaving it
        # unbounded -- an unbounded last column can reach far enough right
        # to swallow unrelated printed text well past this aging block
        # (e.g. the account-number value echoed again just above the
        # NEW BALANCE row on this document, at x0=346.6, would otherwise
        # land inside an unbounded NEW BALANCE bucket starting at x0=177.75).
        hi = (x0 + ordered[i + 1][1]) / 2 if i < len(ordered) - 1 else x0 + 100
        bounds[name] = (lo, hi)
    return bounds


def parse_aging_summary(last_page_words):
    """Statement-level aging bucket row (CURRENT / OVER 30/60/90/120 DAYS /
    NEW BALANCE / ACCOUNT NUMBER / PAY THIS AMOUNT) -- finds the two header
    rows, then reads the money/digit value printed under each one using
    column-range bucketing (see _bucket_by_x0()). Per the investigation:
    this header repeats as a footer template on every page, but only the
    FINAL page has real values printed beneath it (pages 1-5 print the same
    labels over blank cells) -- so this must be called with the last page's
    words only, never scanned across every page. Returns a dict of flat
    scalar fields; a bucket with nothing printed beneath it is None. Never
    merged into line_items (INV-03: no summary/total row may ever be
    ingested as if it were a real invoice line)."""
    rows = group_rows(last_page_words)

    row1 = row2 = None
    for row in rows:
        texts = [w["text"] for w in row]
        if row1 is None and "CURRENT" in texts and "ACCOUNT" in texts and "NUMBER" in texts:
            row1 = row
        elif row2 is None and "NEW" in texts and "BALANCE" in texts and "STATEMENT" in texts:
            row2 = row
    if row1 is None or row2 is None:
        return {}

    anchors_x0 = {}
    over1 = sorted((w for w in row1 if w["text"] == "OVER"), key=lambda w: w["x0"])
    for w in row1:
        if w["text"] == "CURRENT":
            anchors_x0["aging_current"] = w["x0"]
        elif w["text"] == "ACCOUNT":
            anchors_x0["aging_account_number"] = w["x0"]
        elif w["text"] == "PAY":
            anchors_x0["aging_pay_this_amount"] = w["x0"]
    if len(over1) >= 1:
        anchors_x0["aging_over_30"] = over1[0]["x0"]
    if len(over1) >= 2:
        anchors_x0["aging_over_60"] = over1[1]["x0"]

    over2 = sorted((w for w in row2 if w["text"] == "OVER"), key=lambda w: w["x0"])
    for w in row2:
        if w["text"] == "NEW":
            anchors_x0["aging_new_balance"] = w["x0"]
    if len(over2) >= 1:
        anchors_x0["aging_over_90"] = over2[0]["x0"]
    if len(over2) >= 2:
        anchors_x0["aging_over_120"] = over2[1]["x0"]

    row1_fields = {"aging_current", "aging_over_30", "aging_over_60",
                   "aging_account_number", "aging_pay_this_amount"}
    row1_bounds = _bucket_by_x0({k: v for k, v in anchors_x0.items() if k in row1_fields})
    row2_bounds = _bucket_by_x0({k: v for k, v in anchors_x0.items() if k not in row1_fields})

    result = {name: None for name in anchors_x0}

    def fill_from(header_row, bounds):
        header_top = header_row[0]["top"]
        for row in rows:
            row_top = row[0]["top"]
            # Strictly after the header row itself (excludes the header's
            # own text, e.g. the literal digits in "OVER 120 DAYS"), within
            # AGING_VALUE_TOP_WINDOW points below it.
            if not (header_top < row_top <= header_top + AGING_VALUE_TOP_WINDOW):
                continue
            for w in row:
                if not (MONEY_RE.match(w["text"]) or w["text"].isdigit()):
                    continue
                for name, (lo, hi) in bounds.items():
                    if result[name] is None and lo <= w["x0"] < hi:
                        result[name] = w["text"]

    fill_from(row1, row1_bounds)
    fill_from(row2, row2_bounds)
    return result


def extract(pdf_path):
    """Returns {"line_items": [...], "fieldnames": [...], "summary": {...}, "full_text": None}."""
    line_items = []
    department_subtotals = {}
    header_info = {}
    printed_total = None
    aging_summary = {}

    with pdfplumber.open(pdf_path) as pdf:
        page1_words = drop_watermark(pdf.pages[0].extract_words())
        header_info = parse_header_info(pdf.pages[0].extract_text() or "", page1_words)

        for page_num, page in enumerate(pdf.pages, start=1):
            words = drop_watermark(page.extract_words())
            rows = group_rows(words)

            for row in rows:
                cols = {name: [] for name in (
                    "date", "source", "invoice", "reference", "description",
                    "amount", "age_in_days", "remit_date", "remit_invoice", "remit_balance",
                )}
                for w in row:
                    cols[classify_word(w)].append(w)

                def joined(name):
                    return " ".join(w["text"] for w in sorted(cols[name], key=lambda w: w["x0"]))

                date = joined("date")
                invoice = joined("invoice")
                amount = joined("amount")
                description = joined("description")

                if DATE_RE.match(date) and invoice:
                    line_items.append({
                        "page": page_num,
                        "date": date,
                        "source": joined("source"),
                        "invoice": invoice,
                        "reference": joined("reference"),
                        "description": description,
                        "amount": amount,
                        "age_in_days": joined("age_in_days"),
                        "remit_date": joined("remit_date"),
                        "remit_invoice": joined("remit_invoice"),
                        "remit_balance": joined("remit_balance"),
                    })
                elif not date and not invoice and amount and SUBTOTAL_CODE_RE.match(description):
                    # Per-department subtotal row, e.g. "220  13637.26  *****  220  13637.26".
                    department_subtotals[description] = amount

            if page_num == len(pdf.pages):
                printed_total = parse_grand_total(words)
                aging_summary = parse_aging_summary(words)

    computed_total = round(sum(float(r["amount"].replace(",", "")) for r in line_items), 2)
    computed_from_departments = round(
        sum(float(v.replace(",", "")) for v in department_subtotals.values()), 2
    )
    printed_total_val = float((printed_total or "0").replace(",", ""))

    summary = dict(header_info)
    summary["department_subtotals"] = department_subtotals
    summary["total_from_department_subtotals"] = f"{computed_from_departments:,.2f}"
    summary["total_computed"] = f"{computed_total:,.2f}"
    summary["total_printed"] = printed_total
    summary["reconciles"] = computed_total == printed_total_val
    # Statement-level aging bucket totals from the final page only (see
    # parse_aging_summary()'s own docstring) -- never merged into
    # line_items (INV-03).
    summary.update(aging_summary)

    return {
        "line_items": line_items,
        "fieldnames": FIELDNAMES,
        "summary": summary,
        "full_text": None,
    }


if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "Quirk Colemans.PDF"
    result = extract(pdf_path)
    print(f"Line items extracted: {len(result['line_items'])}")
    print(f"Summary: {result['summary']}")
