"""
tests/test_extract_ef320.py

src/extraction/python_library/extract_ef320.py -- the CDK "eF320-Accounts
Receivable Statement" (Faulkner Honda / Nissan / Subaru, 2026-10-25), on
synthetic PDFs generated here with PyMuPDF at the real layout's positions:
letterhead, the DATE / PURCHASES ($) / PAYMENTS & CREDITS ($) / BALANCE DUE ($)
header, the COMPANY ID / JOURNAL ID / REFERENCE # / PREVIOUS BALANCE
sub-header, right-aligned amounts, the aging line and the finance-charge
footer. No customer PDFs.
"""

import csv
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "extraction", "python_library"))

import pymupdf

import extract_all
import extract_ef320
from src.extraction.python_library.adapter import ROUTABLE_VENDOR_SIGNATURES, PythonLibraryExtractionEngine
from src.lakehouse.field_names import normalize_field_name
from src.validation.arithmetic_gate import validate_with_fallbacks

SEED = os.path.join(os.path.dirname(__file__), "..", "dbt", "vive_recon", "seeds", "vendor_field_mapping.csv")
# Right edges of the right-aligned money columns as printed on the real form.
AMOUNT_RIGHT = {"purchases": 363.9, "payments": 469.0, "balance": 564.0}
AGING_RIGHT = (108.5, 203.3, 298.2, 393.0, 487.8, 582.7)
FOOTER = ('FINANCE CHARGES will apply if the new balance is unpaid one month from the closing date of statement. '
          'The "FINANCE CHARGES" are computed a periodic rate of 1.50% per month which is an')


def width(text, size=8):
    return pymupdf.get_text_length(text, fontname="helv", fontsize=size)


class Ef320Pdf:
    """A synthetic one-page eF320 statement. company_id=False prints the
    Nissan variant (JOURNAL ID / REFERENCE # only)."""

    def __init__(self, testcase, *, dealer="Example Motors of Testville", company_id=True):
        self.testcase = testcase
        self.company_id = company_id
        self.words = []          # (x, baseline, text, size)
        self.text(19.4, 28, "Customer # 1001", 9)
        self.text(513.8, 34, "eF320-Accounts Receivable Statement", 5)
        self.text(19.9, 48, "REMIT TO:", 10)
        self.text(516.4, 57, "ACCOUNTS DUE", 10)
        if dealer:
            self.text(181.7, 61, dealer, 10)
        self.text(490.1, 69, "AND PAYABLE BY THE", 10)
        self.text(181.7, 91, "PO Box 1", 8)
        self.text(181.7, 101, "Testville, PA 00000", 8)
        self.text(466.8, 139, "CUST NO", 9)
        self.text(541.9, 139, "1001", 9)
        self.text(455.6, 155, "CLOSING DATE", 9)
        self.text(534.5, 155, "09-28-2026", 9)
        for i, line in enumerate(("TEST COLLISION", "TEST SHOP", "1 MAIN ST", "SHOPVILLE PA 00001-0001")):
            self.text(76.3, 160 + 11 * i, line, 9)
        self.text(480.5, 219, "AMOUNT ENCLOSED", 8)
        self.text(245.3, 238, "PLEASE RETURN THIS PORTION WITH YOUR CHECK", 8)
        y = 291
        self.text(41.2, y, "DATE")
        self.text(139.3, y, "DOCUMENT/TRANSACTION")
        self.text(291.5, y, "PURCHASES ($)")
        self.text(375.2, y, "PAYMENTS & CREDITS ($)")
        self.text(498.7, y, "BALANCE DUE ($)")
        y = 306
        if company_id:
            self.text(84.9, y, "COMPANY ID")
        self.text(147.1, y, "JOURNAL ID")
        self.text(209.4, y, "REFERENCE #")
        self.text(337.6, y, "PREVIOUS BALANCE")
        self.y = 318

    def text(self, x, y, s, size=8):
        self.words.append((x, y, s, size))

    def row(self, date, ref, *, company="32", journal="32", purchases=None, payments=None, balance=None):
        self.text(23.7, self.y, date)
        if company and self.company_id:
            self.text(84.9, self.y, company)
        if journal:
            self.text(147.1, self.y, journal)
        if ref:
            self.text(209.4, self.y, ref)
        for column, value in (("purchases", purchases), ("payments", payments), ("balance", balance)):
            if value is not None:
                self.text(AMOUNT_RIGHT[column] - width(value), self.y, value)
        self.y += 12.6

    def line(self, x, s):
        self.text(x, self.y, s)
        self.y += 12.6

    def aging(self, *amounts):
        self.y += 6
        self.text(44.7, self.y, "CURRENT ($)")
        for x, label in ((130.1, "OVER 30 DAYS ($)"), (224.9, "OVER 60 DAYS ($)"), (319.8, "OVER 90 DAYS ($)"),
                         (412.3, "OVER 120 DAYS ($)"), (509.7, "BALANCE DUE ($)")):
            self.text(x, self.y, label)
        self.y += 12.6
        for right, value in zip(AGING_RIGHT, amounts):
            self.text(right - width(value), self.y, value)
        self.y += 15
        self.text(21.4, self.y, FOOTER, 5.5)
        self.text(21.4, self.y + 30, "Page 1 of 1 Customer Copy Copyright 2022 CDK Global, LLC", 6)

    def save(self):
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        for x, y, s, size in self.words:
            page.insert_text((x, y), s, fontsize=size)
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.close()
        doc.save(f.name)
        doc.close()
        self.testcase.addCleanup(os.remove, f.name)
        return f.name


def one_purchase(testcase, **kwargs):
    """The Faulkner Honda shape: one dated line, aging, BALANCE DUE 41.62."""
    pdf = Ef320Pdf(testcase, **kwargs)
    pdf.row("08-28-2026", "518306", purchases="41.62")
    pdf.aging("0.00", "41.62", "0.00", "0.00", "0.00", "41.62")
    return pdf


class TestExtractEf320(unittest.TestCase):

    def test_routed_by_the_ef320_signature(self):
        self.assertIn("eF320-Accounts Receivable Statement", ROUTABLE_VENDOR_SIGNATURES)
        self.assertIs(extract_all.detect_vendor(one_purchase(self).save()), extract_ef320)

    def test_one_dated_line_with_a_reference_is_one_row(self):
        result = extract_ef320.extract(one_purchase(self).save())
        self.assertEqual(result["line_items"], [{
            "page": 1, "DATE": "08-28-2026", "COMPANY ID": "32", "JOURNAL ID": "32", "REFERENCE #": "518306",
            "PURCHASES ($)": "41.62", "PAYMENTS & CREDITS ($)": None, "BALANCE DUE ($)": None}])
        summary = result["summary"]
        self.assertEqual(summary["balance_due_printed"], "41.62")
        self.assertEqual((summary["aging_current"], summary["aging_over_30"]), ("0.00", "41.62"))
        self.assertTrue(summary["reconciles"])
        self.assertEqual((summary["vendor_name"], summary["customer_number"], summary["closing_date"]),
                         ("Example Motors of Testville", "1001", "09-28-2026"))
        self.assertEqual((summary["customer_name"], summary["billing_city_state_zip"]),
                         ("TEST COLLISION", "SHOPVILLE PA 00001-0001"))
        self.assertNotIn("parse_problem", summary)

    def test_journal_id_only_variant(self):
        pdf = Ef320Pdf(self, company_id=False)
        pdf.row("09-25-2026", "731452", purchases="5.87")
        pdf.aging("5.87", "0.00", "0.00", "0.00", "0.00", "5.87")
        item = extract_ef320.extract(pdf.save())["line_items"][0]
        self.assertEqual((item["COMPANY ID"], item["JOURNAL ID"], item["REFERENCE #"], item["PURCHASES ($)"]),
                         (None, "32", "731452", "5.87"))

    def test_adapter_and_gate_match_the_printed_balance_due(self):
        schema = PythonLibraryExtractionEngine().understand("", one_purchase(self).save())
        inv = schema["invoices"][0]
        self.assertEqual((inv["invoice_number"], inv["invoice_date"], inv["charges"], inv["credits"],
                          inv["transaction_code"]), ("518306", "2026-08-28", 41.62, None, "32"))
        meta = schema["statement_metadata"]
        self.assertEqual((meta["statement_total_as_printed"], meta["statement_total_computed"], meta["statement_date"]),
                         (41.62, 41.62, "2026-09-28"))
        self.assertEqual(schema["vendor_metadata"]["vendor_name"], "Example Motors of Testville")
        self.assertEqual(schema["vendor_metadata"]["shop_or_entity"], ["TEST COLLISION"])
        result = validate_with_fallbacks(meta["statement_total_as_printed"], meta["statement_total_computed"],
                                         schema["invoices"])
        self.assertEqual((result["status"], result["method"]), ("matches", "primary"))

    def test_purchases_and_payments_columns(self):
        pdf = Ef320Pdf(self)
        pdf.row("09-03-2026", "100001", purchases="1,200.00")
        pdf.row("09-10-2026", "100002", payments="200.00")
        pdf.aging("1,000.00", "0.00", "0.00", "0.00", "0.00", "1,000.00")
        result = extract_ef320.extract(pdf.save())
        items = {i["REFERENCE #"]: i for i in result["line_items"]}
        self.assertEqual((items["100001"]["PURCHASES ($)"], items["100001"]["PAYMENTS & CREDITS ($)"]), ("1,200.00", None))
        self.assertEqual((items["100002"]["PURCHASES ($)"], items["100002"]["PAYMENTS & CREDITS ($)"]), (None, "200.00"))
        self.assertTrue(result["summary"]["reconciles"])

    def test_balance_only_dated_line_is_not_a_row(self):
        # The 2026-10-19 opening-balance rule (pdf_row_match._opening_balance_line)
        # expects the extraction to have no row for a dated, unlabelled,
        # balance-only first line: it is reported, never made a row.
        pdf = Ef320Pdf(self)
        pdf.row("07-31-2026", None, company=None, journal=None, balance="887.00")
        pdf.row("08-28-2026", "518306", purchases="41.62")
        pdf.aging("0.00", "928.62", "0.00", "0.00", "0.00", "928.62")
        result = extract_ef320.extract(pdf.save())
        self.assertEqual([i["REFERENCE #"] for i in result["line_items"]], ["518306"])
        self.assertEqual(result["summary"]["opening_balance_lines"],
                         [{"page": 1, "date": "07-31-2026", "amount": "887.00"}])
        self.assertFalse(result["summary"]["reconciles"])

    def test_unknown_line_in_the_table_returns_no_rows(self):
        pdf = Ef320Pdf(self)
        pdf.row("08-28-2026", "518306", purchases="41.62")
        pdf.line(139.3, "MEMO CORE RETURN")
        pdf.aging("0.00", "41.62", "0.00", "0.00", "0.00", "41.62")
        result = extract_ef320.extract(pdf.save())
        self.assertEqual(result["line_items"], [])
        self.assertIn("undated line", result["summary"]["parse_problem"])

    def test_no_dealer_name_returns_no_rows(self):
        result = extract_ef320.extract(one_purchase(self, dealer=None).save())
        self.assertEqual(result["line_items"], [])
        self.assertIn("dealer name", result["summary"]["parse_problem"])

    def test_field_names_map_through_the_existing_seed_rows(self):
        # The rows reach Silver through the vendors' existing mapping rows:
        # every field Silver needs is mapped for each eF320 vendor seen.
        with open(SEED, newline="", encoding="utf-8") as f:
            seed = list(csv.DictReader(f))
        for vendor_id in ("FAULKNER", "FETTE", "MORONG_FALMOUTH"):
            mapped = {normalize_field_name(r["raw_field_name"]): r["canonical_field_name"]
                      for r in seed if r["vendor_id"] == vendor_id}
            for field, canonical in (("DATE", "line_date"), ("REFERENCE #", "original_invoice_number"),
                                     ("PURCHASES ($)", "charge_amount")):
                self.assertEqual(mapped.get(normalize_field_name(field)), canonical, (vendor_id, field))


if __name__ == "__main__":
    unittest.main()
