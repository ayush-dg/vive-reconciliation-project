"""
tests/test_interest_balance_rows.py

An interest / finance-charge line printed with no invoice amount, nothing paid
and only its balance (2026-10-26, Sullivan Tire Maurice STMT-B0E5C002:
"9/30/2026 Interest INT000081527 9/30/2026 $0.00 $0.00 $21.35"). The AI read
it right (Invoice Amount 0.00, Paid 0.00, Balance Remaining 21.35), and the
open-balance check computed exactly the printed 2,856.10 -- but its row guard
refused the row (an open balance larger than the row's own amount, 0.00), and
the row verifier called it "extracted row has no amount (unverifiable)" and
the printed line "not extracted".

Now such a row is accepted -- by the open-balance row guard and by the row
verifier -- only when ALL of this holds:
  - the row has no charge and no credit, a positive amount due, and an
    interest / finance word in its own cells;
  - its PDF line (found by its reference) prints that word, its date, no
    non-zero amount under any charge / credit column, and exactly that
    balance.
Without a PDF, or with anything else on the line, the guard fails as before.

SYNTHETIC DATA ONLY: every PDF is generated here with PyMuPDF.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import fitz

from src.validation import pdf_row_match as m
from src.validation.arithmetic_gate import (
    _check_open_balance, compute_statement_total_from_invoices, validate_with_fallbacks,
)

X = {"date": 30, "type": 90, "inv": 150, "due_date": 250, "amount": 320, "paid": 400, "bal": 480}
HEADER = (("date", "Date"), ("type", "Type"), ("inv", "Invoice Number"), ("due_date", "Due Date"),
          ("amount", "Invoice Amount"), ("paid", "Paid Amount"), ("bal", "Balance Remaining"))
INVOICES = [("8/5/2026", "Invoice", "0119-0050001", "225.28"), ("8/31/2026", "Invoice", "0119-0050002", "267.25")]
INTEREST = ("9/30/2026", "Interest", "INT000040001", "$0.00", "$0.00", "$17.60")
TOTAL = 510.13   # 225.28 + 267.25 + 17.60


def charge(invoice, date, amount):
    return {"invoice_number": invoice, "invoice_date": date, "outstanding_amount": amount, "credit": 0.0,
            "amount_due": amount, "_raw_row": {"Type": "Invoice", "Invoice Number": invoice}}


def interest(due=17.6, kind="Interest Note"):
    return {"invoice_number": "INT000040001", "invoice_date": "9/30/2026", "outstanding_amount": 0.0, "credit": 0.0,
            "amount_due": due, "_raw_row": {"Type": kind, "Invoice Number": "INT000040001"}}


def rows(**kw):
    return [charge("0119-0050001", "8/5/2026", 225.28), charge("0119-0050002", "8/31/2026", 267.25), interest(**kw)]


class _Case(unittest.TestCase):

    def setUp(self):
        m._PAGES_CACHE.clear()

    def pdf(self, interest_line=INTEREST):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        for x, y, text in [(30, 50, "SYNTHETIC TIRE AND SERVICE"), (30, 62, "STATEMENT OF ACCOUNT"),
                           (30, 74, "Customer Test Body Shop")]:
            page.insert_text((x, y), text, fontsize=9)
        for key, label in HEADER:
            page.insert_text((X[key], 120), label, fontsize=8)
        y = 136
        for date, kind, invoice, amount in INVOICES:
            for key, value in (("date", date), ("type", kind), ("inv", invoice), ("due_date", date),
                               ("amount", f"${amount}"), ("paid", "$0.00"), ("bal", f"${amount}")):
                page.insert_text((X[key], y), value, fontsize=9)
            y += 14
        date, kind, invoice, amount, paid, balance = interest_line
        for key, value in (("date", date), ("type", kind), ("inv", invoice), ("due_date", date), ("amount", amount),
                           ("paid", paid), ("bal", balance)):
            page.insert_text((X[key], y), value, fontsize=9)
        page.insert_text((X["paid"], y + 26), "Total Due:", fontsize=9)
        page.insert_text((X["bal"], y + 26), f"${TOTAL:,.2f}", fontsize=9)
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.close()
        doc.save(f.name)
        self.addCleanup(os.remove, f.name)
        return f.name


class TestOpenBalanceGuard(_Case):

    def test_the_interest_row_printed_on_the_pdf_is_accepted(self):
        result = _check_open_balance(TOTAL, rows(), tolerance=0.01, pdf_path=self.pdf())
        self.assertTrue(result["passed"], result.get("reason"))
        self.assertEqual(result["computed"], TOTAL)
        self.assertEqual([r["invoice_number"] for r in result["interest_rows_verified"]], ["INT000040001"])

    def test_the_gate_passes_on_open_balance(self):
        rs = rows()
        result = validate_with_fallbacks(TOTAL, compute_statement_total_from_invoices(rs), rs, pdf_path=self.pdf())
        self.assertEqual((result["status"], result["method"]), ("matches", "open_balance"))

    def test_without_a_pdf_the_guard_fails_as_before(self):
        result = _check_open_balance(TOTAL, rows(), tolerance=0.01)
        self.assertFalse(result["passed"])
        self.assertEqual(result["row_guard_failures"][0]["invoice_number"], "INT000040001")

    def test_a_balance_the_pdf_does_not_print_fails(self):
        line = INTEREST[:5] + ("$17.50",)
        result = _check_open_balance(TOTAL, rows(), tolerance=0.01, pdf_path=self.pdf(line))
        self.assertFalse(result["passed"])

    def test_an_amount_printed_on_the_interest_line_fails(self):
        line = INTEREST[:3] + ("$17.60", "$0.00", "$17.60")
        result = _check_open_balance(TOTAL, rows(), tolerance=0.01, pdf_path=self.pdf(line))
        self.assertFalse(result["passed"])

    def test_a_line_without_an_interest_word_fails(self):
        line = (INTEREST[0], "Adjustment") + INTEREST[2:]
        result = _check_open_balance(TOTAL, rows(), tolerance=0.01, pdf_path=self.pdf(line))
        self.assertFalse(result["passed"])

    def test_a_row_without_an_interest_word_fails(self):
        result = _check_open_balance(TOTAL, rows(kind="Adjustment"), tolerance=0.01, pdf_path=self.pdf())
        self.assertFalse(result["passed"])

    def test_a_charge_row_with_a_larger_balance_still_fails(self):
        rs = rows()
        rs[0]["amount_due"] = 300.0
        result = _check_open_balance(TOTAL, rs, tolerance=0.01, pdf_path=self.pdf())
        self.assertFalse(result["passed"])


class TestRowVerifier(_Case):

    def test_the_interest_row_is_verified_and_its_line_is_not_missing(self):
        result = m.check_pdf_row_match(TOTAL, rows(), pdf_path=self.pdf())
        self.assertTrue(result["passed"], result.get("reason"))
        self.assertEqual(result["rows_verified"], 3)

    def test_the_interest_row_with_a_wrong_balance_is_not_verified(self):
        result = m.check_pdf_row_match(TOTAL, rows(due=17.5), pdf_path=self.pdf())
        self.assertFalse(result["passed"])

    def test_a_zero_row_without_an_interest_word_stays_unverifiable(self):
        result = m.check_pdf_row_match(TOTAL, rows(kind="Adjustment"), pdf_path=self.pdf())
        self.assertFalse(result["passed"])
        self.assertIn("no amount", result["offending_rows"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
