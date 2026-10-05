"""
tests/test_python_extractors_oct1_fixes.py

pdfplumber vendor-extractor fixes from the 2026-10-01 validation review,
exercised on small synthetic PDFs generated here (PyMuPDF, words placed at
the x positions the real layouts use) -- no customer PDFs.
  - extract_wilberts: column positions read from the page header when the
    fixed bounds find nothing (Statement_2234465 returned 0 rows).
  - extract_empire: payment rows with no doc number but an unapplied
    balance (EMPIRE COLE 0926 / SEB 0826 were off by exactly that balance).
  - adapter field maps: Empire balance / Adas open_amount as amount_due,
    which the gate's open_balance fallback verifies.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "extraction", "python_library"))

import pymupdf

import extract_empire
import extract_wilberts
from src.extraction.python_library.adapter import _FIELD_MAP, PythonLibraryExtractionEngine
from src.validation.arithmetic_gate import validate_with_fallbacks


def make_pdf(testcase, lines):
    """lines: [(y, [(x, text), ...]), ...] -> path of a one-page PDF."""
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    for y, words in lines:
        for x, text in words:
            page.insert_text((x, y), text, fontsize=7)
    f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    f.close()
    doc.save(f.name)
    doc.close()
    testcase.addCleanup(os.remove, f.name)
    return f.name


class TestWilbertsHeaderDerivedColumns(unittest.TestCase):
    """Oct 1 layout: Store value at x0=75 (inside the fixed 0-85 date
    bucket), money right-aligned under Amount/Balance, remittance stub on
    the right."""

    def _statement(self):
        header = [(30.8, "Date"), (75.0, "Store"), (99.1, "Invoice"), (128.8, "#"), (147.3, "Reference"),
                  (297.9, "Amount"), (340.3, "Core"), (360.7, "Chg"), (397.8, "Balance"),
                  (438.5, "Invoice"), (468.0, "#"), (540.0, "Balance")]
        rows = [
            [(30.8, "09/02/26"), (75.0, "1"), (99.1, "1721891"), (147.3, "PO#10200461"),
             (299.2, "$200.00"), (399.6, "$200.00"), (438.5, "1721891"), (552.3, "$200.00")],
            [(30.8, "09/02/26"), (75.0, "1"), (99.1, "1722451"), (147.3, "CR"), (161.1, "for"), (172.6, "#1718352,"),
             (293.8, "($750.00)"), (394.3, "($750.00)"), (438.5, "1722451"), (548.0, "($750.00)")],
            [(30.8, "09/04/26"), (75.0, "1"), (99.1, "Payment"), (147.3, "CR"), (161.1, "for"), (172.6, "#acct"),
             (287.2, "($1,667.00)"), (408.5, "$0.00"), (438.5, "Payment"), (560.0, "$0.00")],
            [(30.8, "09/15/26"), (75.0, "1"), (99.1, "1727693"), (147.3, "PO#10200463"),
             (299.2, "$925.00"), (399.6, "$925.00"), (438.5, "1727693"), (552.3, "$925.00")],
        ]
        lines = [(200, header)] + [(220 + 14 * i, r) for i, r in enumerate(rows)]
        lines.append((320, [(394.0, "Balance"), (425.0, "Due"), (450.0, "$375.00")]))
        return make_pdf(self, lines)

    def test_header_derived_columns_extract_every_row(self):
        result = extract_wilberts.extract(self._statement())
        items = result["line_items"]
        self.assertEqual([i["invoice_number"] for i in items], ["1721891", "1722451", "Payment", "1727693"])
        self.assertEqual([i["store"] for i in items], ["1", "1", "1", "1"])
        self.assertEqual([i["balance"] for i in items], ["200.00", "-750.00", "0.00", "925.00"])
        self.assertEqual(items[2]["amount"], "-1667.00")
        self.assertEqual(result["summary"]["total_computed"], "375.00")
        self.assertTrue(result["summary"]["reconciles"])

    def test_fixed_bounds_alone_found_nothing_on_this_layout(self):
        import pdfplumber
        with pdfplumber.open(self._statement()) as pdf:
            fixed, _, _ = extract_wilberts._extract_line_items(pdf, use_page_header=False)
        self.assertEqual(fixed, [])


class TestEmpirePaymentRows(unittest.TestCase):

    def _statement(self):
        lines = [
            (40, [(19.3, "EMPIRE"), (60.0, "AUTO"), (85.0, "PARTS")]),
            (60, [(19.3, "Activity"), (60.0, "through"), (95.0, "09/30/26")]),
            (100, [(19.3, "09/01/26"), (72.6, "2014"), (95.0, "Sienna"), (205.0, "41155814"),
                   (428.7, "130.00"), (475.0, "10/10/26"), (554.0, "130.00")]),
            (114, [(19.3, "09/02/26"), (72.6, "Return"), (205.0, "41160840"),
                   (428.7, "-102.00"), (475.0, "10/10/26"), (554.0, "-102.00")]),
            (128, [(19.3, "09/29/26"), (72.6, "LOCKBOX"), (420.3, "-3,049.00"), (554.0, "-193.00")]),
            (160, [(19.3, "Total"), (45.0, "Balance:"), (80.0, "$-165.00")]),
        ]
        return make_pdf(self, lines)

    def test_payment_row_with_unapplied_balance_is_extracted(self):
        result = extract_empire.extract(self._statement())
        items = result["line_items"]
        self.assertEqual(len(items), 3)
        payment = items[2]
        self.assertEqual((payment["doc_no"], payment["amount"], payment["balance"]), ("", "-3,049.00", "-193.00"))
        self.assertEqual(result["summary"]["total_balance_computed_from_balance_column"], "-165.00")
        self.assertTrue(result["summary"]["reconciles"])

    def test_payment_label_must_be_a_payment_word(self):
        self.assertTrue(extract_empire.PAYMENT_LABEL_RE.match("LOCKBOX"))
        self.assertTrue(extract_empire.PAYMENT_LABEL_RE.match("Cash"))
        self.assertFalse(extract_empire.PAYMENT_LABEL_RE.match("2014 Sienna"))

    def test_engine_and_gate_pass_via_open_balance(self):
        schema = PythonLibraryExtractionEngine().understand("", self._statement())
        meta = schema["statement_metadata"]
        self.assertEqual(meta["statement_total_as_printed"], -165.0)
        self.assertEqual([i["amount_due"] for i in schema["invoices"]], [130.0, -102.0, -193.0])
        result = validate_with_fallbacks(meta["statement_total_as_printed"], meta["statement_total_computed"],
                                         schema["invoices"])
        self.assertEqual((result["status"], result["method"]), ("matches", "open_balance"))


class TestAdapterFieldMaps(unittest.TestCase):

    def test_adas_and_empire_expose_their_open_balance_column(self):
        self.assertEqual(_FIELD_MAP["extract_adas"]["amount_due_field"], "open_amount")
        self.assertEqual(_FIELD_MAP["extract_adas"]["charge_field"], "amount")  # matching unchanged
        self.assertEqual(_FIELD_MAP["extract_empire"]["amount_due_field"], "balance")


if __name__ == "__main__":
    unittest.main()
