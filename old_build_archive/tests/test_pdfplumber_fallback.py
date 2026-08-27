"""
tests/test_pdfplumber_fallback.py

Tests for src/ai/pdfplumber_fallback.py's OCR pseudo-table construction and
column mapping. See PIPELINE_VERIFICATION_REPORT.md Finding 3: OCR fallback
found 0 usable invoices on a real scanned test document because (1) the
cell-splitting heuristic assumed 2+-space column gaps, which this
document's single-space OCR output never had, and (2) invoice_number
column matching didn't recognize a "Ref"/"Reference"-style header.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.ai.pdfplumber_fallback import _map_columns, _ocr_text_to_pseudo_table


class TestOcrTextToPseudoTable(unittest.TestCase):

    def test_single_space_separated_line_falls_back_to_whitespace_split(self):
        """Reproduces the real bug: Tesseract output using single spaces
        between columns previously collapsed into one un-splittable cell."""
        text = "Txn Ref Entity Ledger DocClass Posted OutstandingVariance Flag"
        rows = _ocr_text_to_pseudo_table(text)
        self.assertEqual(
            rows[0],
            ["Txn", "Ref", "Entity", "Ledger", "DocClass", "Posted", "OutstandingVariance", "Flag"],
        )

    def test_two_or_more_space_separated_line_still_splits_normally(self):
        """Regression check: a document whose OCR output DOES preserve wide
        column gaps must keep splitting on those gaps, not get shredded
        into one cell per word."""
        text = "Invoice #    Description of charges    Amount"
        rows = _ocr_text_to_pseudo_table(text)
        self.assertEqual(rows[0], ["Invoice #", "Description of charges", "Amount"])

    def test_single_word_line_stays_a_single_cell(self):
        """A one-word line (e.g. a page title) must not be affected by the
        fallback -- there's nothing to split either way."""
        rows = _ocr_text_to_pseudo_table("TOTAL")
        self.assertEqual(rows[0], ["TOTAL"])

    def test_blank_lines_are_skipped(self):
        rows = _ocr_text_to_pseudo_table("Invoice #  Amount\n\n   \nINV-1  100.00")
        self.assertEqual(len(rows), 2)


class TestMapColumnsRecognizesReferenceHeaders(unittest.TestCase):

    def test_txn_ref_header_maps_to_invoice_number(self):
        col_map = _map_columns(["Txn", "Ref", "Entity"])
        self.assertEqual(col_map.get("invoice_number"), 1)

    def test_reference_number_header_maps_to_invoice_number(self):
        col_map = _map_columns(["Reference Number", "Amount"])
        self.assertEqual(col_map.get("invoice_number"), 0)

    def test_reference_date_header_does_not_map_to_invoice_number(self):
        """A "Reference Date" column is a date, not an identifier -- must
        not be misclassified just because it contains "reference"."""
        col_map = _map_columns(["Reference Date", "Amount"])
        self.assertNotEqual(col_map.get("invoice_number"), 0)

    def test_existing_invoice_number_header_still_works(self):
        """Regression check: the original keyword-based matching this
        change extends must still work unchanged."""
        col_map = _map_columns(["Invoice #", "Amount"])
        self.assertEqual(col_map.get("invoice_number"), 0)

    def test_existing_ro_number_header_still_works(self):
        """Regression check: RO #, checked after invoice_number in the
        elif chain, must not get swallowed by the broadened ref matching."""
        col_map = _map_columns(["RO #", "Amount"])
        self.assertEqual(col_map.get("ro_number"), 0)
        self.assertIsNone(col_map.get("invoice_number"))

    def test_bare_ref_substring_inside_another_word_does_not_match(self):
        """"Preferred Vendor" contains "ref" as a substring but not as a
        standalone word -- must not be misread as an invoice_number column."""
        col_map = _map_columns(["Preferred Vendor", "Amount"])
        self.assertIsNone(col_map.get("invoice_number"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
