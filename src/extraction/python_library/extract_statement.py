"""
Extract Fred Beans Parts AR statement PDF into:
  1. Fred Beans Lee's - full text.txt   (layout-preserved text, all pages)
  2. Fred Beans Lee's - line items.csv  (structured invoice/credit line items)
  3. Fred Beans Lee's - summary.csv     (header info + aging summary totals)

Uses pdfplumber (the PDF has real embedded text, confirmed via probe -
not scanned images, so no OCR is needed). Native extract_table() produced
misaligned columns on this layout, so line items are reconstructed from
extract_words() using a rule-based token classifier:
  - tokens are typed by regex (date / 2-digit code / money / other-text)
  - money tokens are assigned to charges/credits/amount_due/remit_amount_due
    by their right edge (x1), which clusters cleanly by column since the
    amounts are right-aligned (their left edge shifts with digit count,
    so x0-based bucketing mis-files wide numbers like "14,681.56")
  - the two "other-text" tokens on a row are invoice_number then
    remit_invoice_no, in left-to-right order
This was verified against the actual x1 clusters in the document
(~275 / ~355 / ~425-440 / ~570-575 for the four money columns).
"""

import re
import sys
import pdfplumber

# Signature text used by extract_all.py to recognize this vendor's layout.
VENDOR_SIGNATURE = ["Fred Beans Parts"]

ROW_TOLERANCE = 2.5  # px tolerance for grouping words into the same row

DATE_RE = re.compile(r"^\d{2}[A-Z]{3}\d{2}$")
CODE_RE = re.compile(r"^\d{2}$")
MONEY_RE = re.compile(r"^-?[\d,]+\.\d{2}-?$")

# Money column boundaries by right-edge (x1) — see module docstring.
MONEY_COLUMNS = [
    ("charges", 320),
    ("credits", 400),
    ("amount_due", 500),
    ("remit_amount_due", 10_000),
]


def classify_money(x1):
    for name, upper in MONEY_COLUMNS:
        if x1 <= upper:
            return name
    return "remit_amount_due"


def group_rows(words):
    """Group words into rows by their 'top' coordinate."""
    rows = []
    current_top = None
    current_row = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if current_top is None or abs(w["top"] - current_top) <= ROW_TOLERANCE:
            current_row.append(w)
            current_top = w["top"] if current_top is None else current_top
        else:
            rows.append(current_row)
            current_row = [w]
            current_top = w["top"]
    if current_row:
        rows.append(current_row)
    return rows


def parse_header_info(page_text):
    info = {}
    m = re.search(r"(\d{2}[A-Z]{3}\d{2})\s+([A-Z0-9]+)\s+(\d+)\s*\n", page_text)
    if m:
        info["statement_date"] = m.group(1)
        info["customer_no"] = m.group(2)
        info["page_no"] = m.group(3)
    m = re.search(r"\n(VIVE COLLISION[^\n]*)\n", page_text)
    if m:
        info["customer_name"] = m.group(1).split("  ")[0].strip()
    m = re.search(r"\n(CHURCHILL[^\n]*)\n([^\n]*ST GEORGES AVE[^\n]*)\n([^\n]*AVENEL[^\n]*)\n", page_text)
    if m:
        info["billing_line1"] = m.group(1).strip()
        info["billing_line2"] = m.group(2).strip()
        info["billing_line3"] = m.group(3).strip()
    return info


def parse_aging_summary(words, page_height):
    """The aging totals row sits just above the finance-charge disclaimer,
    below the 'CURRENT OVER 30 DAYS ...' label row. Grab the numeric row."""
    rows = group_rows(words)
    aging_values = None
    for i, row in enumerate(rows):
        texts = [w["text"] for w in row]
        joined = " ".join(texts)
        if joined.startswith("CURRENT") and "BALANCE DUE" in joined:
            # numeric totals appear 1-2 rows below this label row
            for j in range(i + 1, min(i + 3, len(rows))):
                cand = rows[j]
                cand_text = " ".join(w["text"] for w in cand)
                if re.search(r"\d,?\d*\.\d{2}", cand_text):
                    aging_values = cand
                    break
            break
    if not aging_values:
        return None
    nums = [w["text"] for w in aging_values if re.match(r"^-?[\d,]+\.\d{2}-?$", w["text"])]
    if len(nums) >= 6:
        return {
            "current": nums[0],
            "over_30_days": nums[1],
            "over_60_days": nums[2],
            "over_90_days": nums[3],
            "over_120_days": nums[4],
            "balance_due": nums[-1],
        }
    return None


def extract(pdf_path):
    """Returns {"line_items": [...], "fieldnames": [...], "summary": {...}, "full_text": str}."""
    all_text_pages = []
    line_items = []
    header_info = {}
    aging_summary = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            layout_text = page.extract_text(layout=True) or ""
            all_text_pages.append(f"{'=' * 80}\nPAGE {page_num}\n{'=' * 80}\n{layout_text}")

            plain_text = page.extract_text() or ""
            if page_num == 1:
                header_info = parse_header_info(plain_text)
            else:
                # page number differs; refresh just that field
                pinfo = parse_header_info(plain_text)
                if pinfo.get("page_no"):
                    pass  # per-page, not needed in summary

            words = page.extract_words()

            rows = group_rows(words)
            for row in rows:
                row = sorted(row, key=lambda w: w["x0"])
                codes = [w for w in row if CODE_RE.match(w["text"])]
                dates = [w for w in row if DATE_RE.match(w["text"])]
                moneys = [w for w in row if MONEY_RE.match(w["text"])]
                others = [w for w in row if w not in codes and w not in dates and w not in moneys]

                # A genuine line-item row has exactly the two transaction-code
                # tokens (e.g. "60 35"); skip headers, blanks, and totals rows.
                if len(codes) != 2:
                    continue

                date = dates[0]["text"] if dates else ""
                code1, code2 = codes[0]["text"], codes[1]["text"]
                invoice_number = others[0]["text"] if len(others) >= 1 else ""
                remit_invoice_no = others[1]["text"] if len(others) >= 2 else ""

                money_cols = {"charges": "", "credits": "", "amount_due": "", "remit_amount_due": ""}
                for w in moneys:
                    money_cols[classify_money(w["x1"])] = w["text"]

                line_items.append({
                    "page": page_num,
                    "date": date,
                    "transaction_code": f"{code1} {code2}",
                    "invoice_number": invoice_number,
                    "charges": money_cols["charges"],
                    "credits": money_cols["credits"],
                    "amount_due": money_cols["amount_due"],
                    "remit_invoice_no": remit_invoice_no,
                    "remit_amount_due": money_cols["remit_amount_due"],
                })

            if page_num == len(pdf.pages):
                aging_summary = parse_aging_summary(words, page.height)

    # Carry the date forward onto rows where it was blank (multi-line invoice
    # groups only print the date once, on the first sub-row).
    last_date = None
    for item in line_items:
        if item["date"]:
            last_date = item["date"]
        else:
            item["date"] = last_date

    fieldnames = ["page", "date", "transaction_code", "invoice_number", "charges",
                  "credits", "amount_due", "remit_invoice_no", "remit_amount_due"]

    summary = dict(header_info)
    if aging_summary:
        summary.update(aging_summary)

    return {
        "line_items": line_items,
        "fieldnames": fieldnames,
        "summary": summary,
        "full_text": "\n\n".join(all_text_pages),
    }


if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "Fred Beans Lee's.pdf"
    result = extract(pdf_path)
    print(f"Line items extracted: {len(result['line_items'])}")
    print(f"Summary: {result['summary']}")
