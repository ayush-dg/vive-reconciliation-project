"""
tests/test_extract_autoly.py

src/extraction/python_library/extract_autoly.py -- the Autoly statement
layout (Bow, Chuck's, Ding's, Goyette's, ... 2026-10-01), on synthetic PDFs
generated here with PyMuPDF at the real layout's positions: right-aligned
money columns, the merged "DueDescription" header word, a Due amount glued to
its Description, the payment remittance stub, the aging and totals blocks.
No customer PDFs.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "extraction", "python_library"))

import pymupdf

import extract_all
import extract_autoly
from src.extraction.python_library.adapter import ROUTABLE_VENDOR_SIGNATURES, PythonLibraryExtractionEngine
from src.validation.arithmetic_gate import validate_with_fallbacks

FONT = 7


def width(text):
    return pymupdf.get_text_length(text, fontname="helv", fontsize=FONT)


class AutolyPdf:
    """Builds a synthetic Autoly statement. shift moves the whole ledger
    table right; merged_header prints "Unalloc.DueDescription" as one word."""

    def __init__(self, testcase, *, shift=0.0, merged_header=False, vendor="Synthetic Parts - AUTOLY"):
        self.testcase = testcase
        self.s = shift
        self.merged_header = merged_header
        self.vendor = vendor
        self.pages = []
        self.y = 0
        # Right edges of the right-aligned money columns, and where Due /
        # Description start -- the real layout's positions.
        self.right = {"charged": 324 + shift, "paid": 362 + shift, "unalloc": 400 + shift}
        self.due_x0 = 422.9 + shift if not merged_header else 400 + shift
        self.right["due"] = self.due_x0 + width("Due")
        self.desc_x0 = 441 + shift

    def text(self, x, y, s):
        self.pages[-1].append((x, y, s))

    def new_page(self, *, header=True, letterhead=True):
        self.pages.append([])
        if letterhead:
            for i, line in enumerate((self.vendor, "1 TEST ROAD", "TESTVILLE NH 00000")):
                self.text(55, 50 + 9 * i, line)
            self.text(351, 110, "Statement # 9")
            self.text(371, 122, "Period 09/01/26 - 09/30/26")
            self.text(404, 157, "Open Items")
            self.text(479, 157, "Unalloc.")
            self.text(515, 157, "Aged Amount")
            for i, line in enumerate(("TEST COLLISION", "1 SHOP ST", "SHOPVILLE ME 00001")):
                self.text(90, 158 + 9.5 * i, line)
        if header:
            y, s = 270, self.s
            self.text(20 + s, y, "Date")
            self.text(57 + s, y, "Transaction Type")
            self.text(172 + s, y, "Sls")
            self.text(221 + s, y, "Cust PO/Chk #")
            self.text(self.right["charged"] - width("Charged"), y, "Charged")
            self.text(self.right["paid"] - width("Paid"), y, "Paid")
            if self.merged_header:
                self.text(self.right["unalloc"] - width("Unalloc."), y, "Unalloc.DueDescription")
            else:
                self.text(self.right["unalloc"] - width("Unalloc."), y, "Unalloc.")
                self.text(self.due_x0, y, "DueDescription")
        self.y = 285 if header else 100

    def aging_total(self, due, unalloc, balance):
        self.text(370, 246, "Total")
        for x1, value in ((448, due), (510, unalloc), (567, balance)):
            self.text(x1 - width(value), 246, value)

    def row(self, date, tx, *, sls="aj", po="", charged=None, paid=None, unalloc=None, due=None, desc="", glue=True):
        y, s = self.y, self.s
        self.text(20 + s, y, date)
        self.text(57 + s, y, tx)
        if sls:
            self.text(172 + s, y, sls)
        if po:
            self.text(221 + s, y, po)
        for column, value in (("charged", charged), ("paid", paid), ("unalloc", unalloc)):
            if value is not None:
                self.text(self.right[column] - width(value), y, value)
        if due is not None:
            x = self.right["due"] - width(due)
            if glue and desc:
                self.text(x, y, due + desc)  # no gap: pdfplumber reads one word
            else:
                self.text(x, y, due)
                if desc:
                    self.text(self.desc_x0, y, desc)
        elif desc:
            self.text(self.desc_x0, y, desc)
        self.y += 12

    def line(self, x, s):
        self.text(x + self.s, self.y, s)
        self.y += 12

    def totals(self, due, unalloc, balance):
        self.y += 20
        for x, s in ((326, f"Total due {due}"), (317, f"Unallocated {unalloc}"), (315, f"Balance due {balance}")):
            self.text(x, self.y, s)
            self.y += 13

    def save(self, *, image_only=False):
        doc = pymupdf.open()
        for words in self.pages:
            page = doc.new_page(width=595, height=842)
            for x, y, s in words:
                page.insert_text((x, y), s, fontsize=FONT)
        if image_only:
            scan = pymupdf.open()
            for page in doc:
                pix = page.get_pixmap(dpi=100)
                new = scan.new_page(width=page.rect.width, height=page.rect.height)
                new.insert_image(new.rect, stream=pix.tobytes("png"))
            doc.close()
            doc = scan
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.close()
        doc.save(f.name)
        doc.close()
        self.testcase.addCleanup(os.remove, f.name)
        return f.name


def standard(testcase, **kwargs):
    """Invoice partly credited, the credit, an open invoice, an invoice
    already paid (Due 0.00 glued to its description), and a payment with an
    unallocated remainder: Total due 650.00 - Unallocated 150.00 = 500.00."""
    pdf = AutolyPdf(testcase, **kwargs)
    pdf.new_page()
    pdf.aging_total("650.00", "150.00", "500.00")
    pdf.row("09/01/26", "Invoice #1001", po="7001", charged="500.00", due="400.00", desc="2019 SANTA FE Door")
    pdf.row("09/02/26", "Credit #1002 for inv. 1001", paid="100.00", unalloc="0.00", desc="2019 SANTA FE Door")
    pdf.row("09/05/26", "Invoice #1003", po="7002", charged="250.00", due="250.00", desc="2021 F150 Mirror")
    pdf.row("09/09/26", "Invoice #1004", po="7003", charged="300.00", due="0.00", desc="2017 FORESTER Lid")
    pdf.row("09/20/26", "Payment: Check 555", sls="chris", po="555", paid="1000.00", unalloc="150.00",
            desc="Payment: Check 555")
    pdf.totals("650.00", "150.00", "500.00")
    return pdf


def by_ref(items):
    return {i["reference_number"]: i for i in items}


class TestExtractAutoly(unittest.TestCase):

    def check_standard(self, result):
        items = by_ref(result["line_items"])
        self.assertEqual(len(result["line_items"]), 5)
        self.assertEqual((items["1001"]["type"], items["1001"]["charged"], items["1001"]["paid"], items["1001"]["due"]),
                         ("INVOICE", "500.00", None, "400.00"))
        self.assertEqual(items["1001"]["description"], "2019 SANTA FE Door")
        self.assertEqual(items["1001"]["po_chk_number"], "7001")
        self.assertEqual((items["1002"]["type"], items["1002"]["original_invoice_ref"], items["1002"]["paid"],
                          items["1002"]["unalloc"], items["1002"]["due"]), ("CREDIT", "1001", "100.00", "0.00", None))
        self.assertEqual((items["1004"]["due"], items["1004"]["description"]), ("0.00", "2017 FORESTER Lid"))
        self.assertEqual((items["555"]["type"], items["555"]["paid"], items["555"]["unalloc"], items["555"]["due"]),
                         ("PAYMENT", "1000.00", "150.00", None))
        self.assertEqual(items["555"]["description"], "")  # remittance stub dropped
        summary = result["summary"]
        self.assertEqual(summary["balance_due_printed"], "500.00")
        self.assertTrue(summary["reconciles"])
        self.assertEqual(summary["unplaced_values"], [])

    def test_reads_every_column(self):
        result = extract_autoly.extract(standard(self).save())
        self.check_standard(result)
        summary = result["summary"]
        self.assertEqual(summary["vendor_name"], "Synthetic Parts - AUTOLY")
        self.assertEqual(summary["customer_name"], "TEST COLLISION")
        self.assertEqual((summary["period_start"], summary["period_end"]), ("09/01/26", "09/30/26"))

    def test_due_glued_to_description_is_split(self):
        pdf = AutolyPdf(self)
        pdf.new_page()
        pdf.row("09/01/26", "Invoice #2001", charged="1130.00", due="1030.00", desc="2019 RANGER Door")
        pdf.totals("1030.00", "0.00", "1030.00")
        item = extract_autoly.extract(pdf.save())["line_items"][0]
        self.assertEqual((item["due"], item["description"]), ("1030.00", "2019 RANGER Door"))

    def test_unalloc_and_due_headers_merged_into_one_word(self):
        self.check_standard(extract_autoly.extract(standard(self, merged_header=True).save()))

    def test_columns_follow_the_header_not_fixed_positions(self):
        self.check_standard(extract_autoly.extract(standard(self, shift=30).save()))

    def test_page_without_a_header_reuses_the_previous_columns(self):
        pdf = standard(self)
        pdf.new_page(header=False, letterhead=False)
        pdf.row("09/25/26", "Invoice #1005", charged="80.00", due="80.00", desc="Bolt")
        result = extract_autoly.extract(pdf.save())
        self.assertEqual(by_ref(result["line_items"])["1005"]["due"], "80.00")
        self.assertEqual(result["summary"]["pages_without_header"], 1)

    def test_wrapped_original_invoice_number(self):
        pdf = AutolyPdf(self)
        pdf.new_page()
        pdf.row("09/02/26", "Credit #3002 for inv.", paid="50.00", unalloc="0.00", desc="Door")
        pdf.line(57, "3001")
        item = extract_autoly.extract(pdf.save())["line_items"][0]
        self.assertEqual((item["reference_number"], item["original_invoice_ref"]), ("3002", "3001"))

    def test_aging_rows_totals_and_notes_are_not_rows(self):
        pdf = standard(self)
        pdf.line(23, "MARKED-UP COPY OF YOUR STATEMENT.")
        result = extract_autoly.extract(pdf.save())
        self.assertEqual(len(result["line_items"]), 5)

    def test_printed_total_falls_back_to_the_aging_total_row(self):
        pdf = AutolyPdf(self)
        pdf.new_page()
        pdf.aging_total("650.00", "150.00", "500.00")
        pdf.row("09/01/26", "Invoice #1001", charged="500.00", due="500.00", desc="Door")
        summary = extract_autoly.extract(pdf.save())["summary"]
        self.assertEqual((summary["total_due_printed"], summary["unallocated_printed"], summary["balance_due_printed"]),
                         ("650.00", "150.00", "500.00"))

    def test_adversarial_no_header_gives_no_rows(self):
        # Nothing to place columns by: no rows, so the intake retries with AI.
        pdf = AutolyPdf(self)
        pdf.new_page(header=False)
        pdf.row("09/01/26", "Invoice #1001", charged="500.00", due="500.00", desc="Door")
        self.assertEqual(extract_autoly.extract(pdf.save())["line_items"], [])

    def test_adversarial_amount_between_columns_is_not_placed(self):
        pdf = AutolyPdf(self)
        pdf.new_page()
        pdf.row("09/01/26", "Invoice #1001", charged="500.00", due="500.00", desc="Door")
        pdf.text(pdf.right["charged"] + 19 - width("99.00"), pdf.y - 12, "99.00")  # 19pt right of Charged
        result = extract_autoly.extract(pdf.save())
        item = result["line_items"][0]
        self.assertEqual((item["charged"], item["paid"], item["due"]), ("500.00", None, "500.00"))
        self.assertEqual([u["text"] for u in result["summary"]["unplaced_values"]], ["99.00"])


class TestAutolyThroughAdapterAndGate(unittest.TestCase):

    def understand(self, path):
        return PythonLibraryExtractionEngine().understand("", path)

    def validate(self, schema):
        meta = schema["statement_metadata"]
        return validate_with_fallbacks(meta["statement_total_as_printed"], meta["statement_total_computed"], schema["invoices"])

    def test_adapter_fields(self):
        schema = self.understand(standard(self).save())
        self.assertEqual(schema["_model_used"], "extract_autoly")
        self.assertEqual(schema["vendor_metadata"]["vendor_name"], "Synthetic Parts - AUTOLY")
        self.assertEqual(schema["vendor_metadata"]["shop_or_entity"], ["TEST COLLISION"])
        meta = schema["statement_metadata"]
        self.assertEqual((meta["statement_total_as_printed"], meta["statement_date"]), (500.0, "2026-09-30"))
        payment = next(i for i in schema["invoices"] if i["invoice_number"] == "555")
        self.assertEqual((payment["credit"], payment["unallocated"], payment["amount_due"]), (1000.0, 150.0, None))
        invoice = next(i for i in schema["invoices"] if i["invoice_number"] == "1001")
        self.assertEqual((invoice["charges"], invoice["amount_due"], invoice["po_number"]), (500.0, 400.0, "7001"))

    def test_passes_by_open_balance(self):
        result = self.validate(self.understand(standard(self).save()))
        self.assertEqual((result["status"], result["method"]), ("matches", "open_balance"))

    def test_adversarial_due_printed_under_paid_fails(self):
        # Position decides: an amount printed in the Paid column is Paid, so
        # a statement whose invoice carries no Due cannot reach its total.
        pdf = AutolyPdf(self)
        pdf.new_page()
        pdf.row("09/01/26", "Invoice #1001", charged="500.00", paid="500.00", desc="Door")
        pdf.row("09/05/26", "Invoice #1003", charged="250.00", due="250.00", desc="Mirror")
        pdf.totals("750.00", "0.00", "750.00")
        result = self.validate(self.understand(pdf.save()))
        self.assertEqual(result["status"], "mismatch")
        self.assertIsNone(result["method"])

    def test_adversarial_due_values_not_adding_up_fails(self):
        pdf = standard(self)
        pdf.pages[-1] = [w for w in pdf.pages[-1] if not w[2].startswith("Balance due")]
        pdf.text(315, pdf.y, "Balance due 600.00")
        result = self.validate(self.understand(pdf.save()))
        self.assertEqual(result["status"], "mismatch")
        self.assertIsNone(result["method"])


class TestAutolyRouting(unittest.TestCase):

    def test_signature_is_routable(self):
        self.assertIn(extract_autoly.VENDOR_SIGNATURE[0], ROUTABLE_VENDOR_SIGNATURES)

    def test_detected_as_autoly(self):
        self.assertIs(extract_all.detect_vendor(standard(self).save()), extract_autoly)

    def test_fenix_ne_keeps_its_own_extractor(self):
        # Fenix NE bills through Autoly too and prints the same header.
        self.assertIs(extract_all.detect_vendor(standard(self, vendor="Fenix NE").save()), extract_all.extract_fenix)

    def test_autoly_letterhead_without_the_ledger_table_is_not_matched(self):
        # Brown's Auto Salvage- Autoly: an aging-only layout, stays on AI.
        pdf = AutolyPdf(self, vendor="Brown's Auto Salvage- Autoly")
        pdf.new_page(header=False)
        pdf.text(20, 300, "Current 31-60 Days 61-90 Days 91-120 Days Over 120 Days Balance Due")
        with self.assertRaises(extract_all.UnknownVendorError):
            extract_all.detect_vendor(pdf.save())

    def test_text_pdf_routes_to_python_library_and_a_scan_to_ai(self):
        from test_oct1_intake_worker_web import load_intake
        intake = load_intake()
        self.assertEqual(intake._determine_extraction_route(standard(self).save())["engine"], "python_library")
        self.assertEqual(intake._determine_extraction_route(standard(self).save(image_only=True))["engine"], "ai")


if __name__ == "__main__":
    unittest.main()
