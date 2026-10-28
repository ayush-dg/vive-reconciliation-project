"""
tests/test_section_totals.py

Several account sections and no grand total (method "pdf_section_totals",
2026-10-26, Blaise Alexander STMT-B0E5C003 / Matthews Auto STMT-B0E5C004):
a scanned CDK file with two or four account statements, each closing with its
own NEW BALANCE / PAY THIS AMOUNT box, no total for the whole file. The
extraction's section totals are accepted only when each section's rows add up
to it AND the PDF's own text prints it as a labelled total (on the label's
line, or as the one amount on the line under it); any other labelled amount,
or a total the PDF does not show, changes nothing.

Synthetic data only: the OCR text is written here in the CDK footer shape
(never a customer's), and OCR is mocked -- no tesseract, network or database.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rerun.in_place import load_intake
from src.validation import section_totals as st
from src.validation.arithmetic_gate import compute_statement_total_from_invoices

INTAKE = load_intake()
NORTH, SOUTH = "Synthetic Motors North - 220-1001", "Synthetic Motors South - 220-1002"
SECTIONS = [{"section": NORTH, "subtotal": 300.0, "invoice_count": None},
            {"section": SOUTH, "subtotal": 150.0, "invoice_count": None}]


def footer(total):
    return ("CURRENT OVER 30 DAYS OVER 60 DAYS ACCOUNT NUMBER PAY THIS AMOUNT\n"
            "OVER 90 DAYS OVER 120 DAYS NEW BALANCE STATEMENT DATE\n"
            f"0.00 0.00 {total} 25 SEP 2026 220-100\n"
            "NEW BALANCE\n")


LETTERHEAD = "SYNTHETIC MOTORS 100 EXAMPLE ROAD SPRINGFIELD CUSTOMER TEST BODY SHOP 400 SAMPLE AVENUE\n" * 2


def text(north="300.00", south="150.00", extra=""):
    return (LETTERHEAD + "SYNTHETIC MOTORS STATEMENT\nDATE SOURCE INVOICE REFERENCE AMOUNT\n"
            "08-18 4 N100 146.43\n09-03 4 N101 153.57\n" + footer(north) +
            "SYNTHETIC MOTORS STATEMENT\nDATE SOURCE INVOICE REFERENCE AMOUNT\n"
            "09-08 4 S200 100.00\n09-09 4 S201 50.00\n" + footer(south) + extra)


def inv(number, amount, section):
    return {"invoice_number": number, "invoice_date": "09-03", "outstanding_amount": amount, "credit": None,
            "amount_due": None, "section": section, "_raw_row": {"INVOICE": number, "AMOUNT": amount, "section": section}}


def rows():
    return [inv("N100", 146.43, NORTH), inv("N101", 153.57, NORTH), inv("S200", 100.0, SOUTH), inv("S201", 50.0, SOUTH)]


class TestCheck(unittest.TestCase):

    def check(self, rs=None, sections=SECTIONS, txt=None, computed=450.0):
        return st.check_section_totals(rs if rs is not None else rows(), sections, text() if txt is None else txt, computed)

    def test_each_section_total_printed_under_its_label_passes(self):
        out = self.check()
        self.assertTrue(out["passed"], out["reason"])
        self.assertEqual((out["printed_total"], out["computed"]), (450.0, 450.0))
        self.assertEqual(sorted(f["amount"] for f in out["printed_totals_found"]), [150.0, 300.0])

    def test_totals_on_the_label_line_pass(self):
        txt = "N100 146.43\nN101 153.57\nNEW BALANCE 300.00\nS200 100.00\nS201 50.00\nNEW BALANCE 150.00\n"
        self.assertTrue(self.check(txt=txt)["passed"])

    def test_a_section_total_the_pdf_does_not_print_changes_nothing(self):
        out = self.check(txt=text(south="0.00"))
        self.assertFalse(out["passed"])
        self.assertIn("is not found as a labelled total", out["reason"])

    def test_a_total_printed_without_a_label_does_not_count(self):
        txt = "N100 146.43\nN101 153.57\n300.00\nS200 100.00\nS201 50.00\nNEW BALANCE 150.00\n"
        self.assertFalse(self.check(txt=txt)["passed"])

    def test_another_labelled_amount_refuses(self):
        out = self.check(txt=text(extra="PAY THIS AMOUNT\n-68.45 0.00 220-100\n"))
        self.assertFalse(out["passed"])
        self.assertIn("-68.45", out["reason"])

    def test_two_non_zero_amounts_under_the_label_are_not_read(self):
        out = self.check(txt=text(north="300.00 12.00"))
        self.assertFalse(out["passed"])

    def test_rows_that_do_not_add_up_to_their_section_fail(self):
        rs = rows()
        rs[1]["outstanding_amount"] = 135.57
        out = self.check(rs, computed=432.0)
        self.assertFalse(out["passed"])
        self.assertIn("rows total", out["reason"])

    def test_a_row_in_no_section_fails(self):
        rs = rows()
        rs[3]["section"] = None
        self.assertIn("in no extracted section", self.check(rs)["reason"])

    def test_charges_minus_credits_must_be_the_sum(self):
        self.assertFalse(self.check(computed=451.0)["passed"])

    def test_one_section_is_not_applicable(self):
        self.assertFalse(self.check(sections=SECTIONS[:1])["applicable"])

    def test_two_sections_with_the_same_total_need_two_printed_totals(self):
        rs = [inv("N100", 150.0, NORTH), inv("S200", 150.0, SOUTH)]
        sections = [dict(SECTIONS[0], subtotal=150.0), SECTIONS[1]]
        once = "N100 150.00\nNEW BALANCE 150.00\nS200 150.00\n"
        self.assertFalse(self.check(rs, sections, once, 300.0)["passed"])
        twice = once + "NEW BALANCE 150.00\n"
        self.assertTrue(self.check(rs, sections, twice, 300.0)["passed"])


class TestIntake(unittest.TestCase):

    def statement(self):
        rs = rows()
        return {"document_metadata": {"document_type": "VENDOR_STATEMENT"},
                "vendor_metadata": {"vendor_name": "Synthetic Motors"},
                "statement_metadata": {"statement_total_as_printed": None,
                                       "statement_total_computed": compute_statement_total_from_invoices(rs),
                                       "section_totals": [dict(s) for s in SECTIONS]},
                "invoices": rs}

    def validate(self, s, txt):
        with mock.patch.object(INTAKE, "ocr_pdf_text", return_value=txt), mock.patch("builtins.print"):
            return INTAKE.apply_arithmetic_validation(s, "", "scan.pdf")

    def test_passes_with_its_own_method(self):
        result = self.validate(self.statement(), text())
        self.assertEqual((result["status"], result["method"]), ("matches", "pdf_section_totals"))
        self.assertEqual((result["printed"], result["computed"], result["difference"]), (450.0, 450.0, 0.0))
        self.assertTrue(result["detail"]["section_totals"]["passed"])

    def test_a_missing_total_stays_total_not_found(self):
        result = self.validate(self.statement(), text(north="0.00"))
        self.assertEqual(result["status"], "total_not_found")
        self.assertFalse(result["detail"]["section_totals"]["passed"])

    def test_switched_off(self):
        with mock.patch.dict(os.environ, {"SECTION_TOTALS_CHECK_ENABLED": "false"}):
            result = self.validate(self.statement(), text())
        self.assertEqual(result["status"], "total_not_found")


if __name__ == "__main__":
    unittest.main()
