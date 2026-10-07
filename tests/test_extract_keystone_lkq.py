"""
tests/test_extract_keystone_lkq.py

extract_keystone.py reading LKQ-branded copies of the Keystone ledger
(2026-10-07, e.g. "LKQ prestige 093026.pdf" from LKQ Broadway Auto): "$" and
parenthesised amounts, routing on the ledger's exact column-header line, and
the vendor name taken from the letterhead -- while Keystone's own statements
keep their fixed name. The LKQ PDF is built here with PyMuPDF at the real
document's word positions (no customer PDF in the repo); Keystone's sample
PDF checks nothing changed for Keystone (all 34 stored Keystone statements
were also replayed unchanged before this was committed).
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "extraction", "python_library"))

import fitz  # noqa: E402
import extract_all  # noqa: E402
import extract_keystone  # noqa: E402
from src.extraction.python_library import adapter  # noqa: E402

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "src", "extraction", "python_library", "sample_pdfs", "Keystone Neet's.pdf")
HEADER = "Purchase Order Balance Forward Period Activity Credit Applied Payment Applied Balance Due"


def lkq_pdf(rows, header=True, letterhead="LKQ Test Auto"):
    """One page laid out like LKQ Broadway Auto's statement (x positions from the real PDF)."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((40, 40), f"{letterhead} MONTHLY STATEMENT", fontsize=9)
    page.insert_text((40, 60), "Statement Date: 09/30/2026", fontsize=9)
    page.insert_text((40, 80), "AMOUNT DUE: $708.00", fontsize=9)
    if header:
        page.insert_text((40, 340), "Reference Reference " + HEADER, fontsize=7)
    page.insert_text((156, 362), "Balance forward", fontsize=7)
    page.insert_text((281, 362), "$332.00", fontsize=7)
    page.insert_text((542, 362), "$332.00", fontsize=7)
    y = 372
    for date, ref, po, activity, credit, payment, balance in rows:
        for x, text in ((40, date), (96, ref), (176, po), (342, activity), (400, credit), (462, payment), (542, balance)):
            if text:
                page.insert_text((x, y), text, fontsize=7)
        y += 9.4
    page.insert_text((40, 700), "Month Totals $332.00 $1,539.00 $831.00 $332.00 $708.00", fontsize=7)
    path = os.path.join(tempfile.mkdtemp(), "lkq.pdf")
    doc.save(path)
    return path


ROWS = [
    ("09/15/26", "178436155", "1401585", "$264.50", "", "", "$596.50"),
    ("09/15/26", "", "CHECK 7226916971", "", "", "($332.00)", "$264.50"),
    ("09/16/26", "178485796", "1401587", "$326.50", "", "", "$591.00"),
    ("09/25/26", "178601157", "1401610", "$376.50", "", "", "$967.50"),
    ("09/28/26", "178860875", "RET(Ref:178097542)", "", "($259.50)", "", "$708.00"),
    ("09/30/26", "178911832", "15279802301", "$571.50", "", "", "$1,279.50"),
    ("09/30/26", "178941073", "RET(Ref:178911832)", "", "($571.50)", "", "$708.00"),
]


class TestAmountTokens(unittest.TestCase):

    def test_dollar_and_parentheses(self):
        self.assertEqual(extract_keystone._amount("$1,279.50"), "1,279.50")
        self.assertEqual(extract_keystone._amount("($259.50)"), "259.50-")
        self.assertEqual(adapter._parse_money(extract_keystone._amount("($259.50)")), -259.5)
        self.assertEqual(extract_keystone._amount("1,279.50"), "1,279.50")  # Keystone's own format unchanged

    def test_adversarial_non_amount_tokens_untouched(self):
        for token in ("RET(Ref:178097542)", "()", "(", "CHECK", "09/30/26"):
            self.assertEqual(extract_keystone._amount(token), token)


class TestLkqLedger(unittest.TestCase):

    def test_reads_lkq_rows_amounts_vendor_and_total(self):
        r = extract_keystone.extract(lkq_pdf(ROWS))
        items = r["line_items"]
        self.assertEqual(len(items), 7)
        self.assertEqual(items[0]["period_activity"], "264.50")
        self.assertEqual(items[1]["payment_applied"], "332.00-")
        self.assertEqual(items[4]["credit_applied"], "259.50-")
        self.assertEqual(r["summary"]["vendor_name"], "LKQ Test Auto")
        self.assertEqual(r["summary"]["total_printed"], "708.00")
        self.assertEqual(r["summary"]["month_totals_balance_due"], "708.00")

    def test_routes_by_the_ledger_header_and_names_the_branch(self):
        path = lkq_pdf(ROWS)
        self.assertIs(extract_all.detect_vendor(path), extract_keystone)
        result = adapter.PythonLibraryExtractionEngine().understand("", path)
        self.assertEqual(result["vendor_metadata"]["vendor_name"], "LKQ Test Auto")
        credits = [inv for inv in result["invoices"] if inv.get("credit")]
        self.assertEqual(sorted(abs(c["credit"]) for c in credits), [259.5, 571.5])

    def test_adversarial_lkq_letterhead_without_the_ledger_header_does_not_route(self):
        with self.assertRaises(extract_all.UnknownVendorError):
            extract_all.detect_vendor(lkq_pdf(ROWS, header=False))


class TestKeystoneUnchanged(unittest.TestCase):

    def test_keystone_sample_keeps_its_fixed_name_and_amounts(self):
        r = extract_keystone.extract(SAMPLE)
        self.assertNotIn("vendor_name", r["summary"])
        self.assertTrue(r["summary"]["reconciles"])
        self.assertFalse(any("$" in (v or "") for item in r["line_items"] for v in item.values()))
        result = adapter.PythonLibraryExtractionEngine().understand("", SAMPLE)
        self.assertEqual(result["vendor_metadata"]["vendor_name"], "Keystone Automotive Industries")


if __name__ == "__main__":
    unittest.main()
