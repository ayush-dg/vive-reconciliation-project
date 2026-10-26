"""
tests/test_charge_payment_rows.py

A row printing a charge, a payment against it and the balance left (2026-10-26,
Dent Wizard Prestige STMT-B0E5C006: "I-000-207315 ... Charge 152.00  Tax 0.00
Payments -45.00  Balance 107.00"). The AI read every cell right, but:

- the gate netted such a row to its payment alone (-45.00), as it nets every
  row that has a credit -- 5 rows counted -210.00 instead of 786.00, and the
  open-balance check (786.00 = printed) was refused by its row guard;
- the row verifier asked the PDF only for that one amount, so the 152.00
  printed under Charge was left over: "PDF line also prints 152.00 under
  Charge which the extracted row does not carry".

Now a row whose charge and payment differ and whose amount due equals charge
minus payment nets to that balance (in the gate's total and in _row_net), and
the verifier checks every populated money column of it: the charge, the
payment and the balance. Every other row shape nets exactly as before (the
ABC duplicate face value, credit-only rows, rows without a matching balance).

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
    _check_open_balance, _row_net, check_invoice_balance, compute_statement_total_from_invoices,
    validate_with_fallbacks,
)

X = {"date": 30, "inv": 95, "svc": 200, "charge": 300, "tax": 360, "pay": 420, "bal": 500}
HEADER = (("date", "Date"), ("inv", "Invoice #"), ("svc", "Service"), ("charge", "Charge"), ("tax", "Tax"),
          ("pay", "Payments"), ("bal", "Balance"))
# (invoice, date, charge, payment, balance) as printed
PRINTED = [("I-000-500101", "09/01/2026", "137.00", "-30.00", "107.00"),
           ("I-000-500102", "09/14/2026", "445.00", "-90.00", "355.00"),
           ("I-000-500103", "09/22/2026", "140.00", "-30.00", "110.00")]
TOTAL = 572.0


def row(invoice, date, charge, payment, due):
    return {"invoice_number": invoice, "invoice_date": date, "outstanding_amount": charge, "credit": payment,
            "amount_due": due,
            "_raw_row": {"Date": date, "Invoice #": invoice, "Service": "Wheels", "Charge": charge, "Tax": 0.0,
                         "Payments": payment, "Balance": due}}


def rows():
    return [row("I-000-500101", "09/01/2026", 137.0, -30.0, 107.0),
            row("I-000-500102", "09/14/2026", 445.0, -90.0, 355.0),
            row("I-000-500103", "09/22/2026", 140.0, -30.0, 110.0)]


class TestNetting(unittest.TestCase):

    def test_the_row_nets_to_its_balance(self):
        self.assertEqual([round(_row_net(r), 2) for r in rows()], [107.0, 355.0, 110.0])
        self.assertEqual(compute_statement_total_from_invoices(rows()), TOTAL)

    def test_the_statement_passes_its_primary_check(self):
        rs = rows()
        result = validate_with_fallbacks(TOTAL, compute_statement_total_from_invoices(rs), rs)
        self.assertEqual((result["status"], result["method"]), ("matches", "primary"))

    def test_the_open_balance_guard_accepts_the_rows(self):
        result = _check_open_balance(TOTAL, rows(), tolerance=0.01)
        self.assertTrue(result["passed"], result.get("reason"))

    def test_the_invoice_balance_check_flags_nothing(self):
        self.assertEqual(check_invoice_balance(rows())["flag_count"], 0)

    # -- every other row shape nets exactly as before ------------------------

    def test_abc_duplicate_face_value_still_nets_to_the_credit(self):
        r = {"invoice_number": "CM1", "outstanding_amount": 50.0, "credit": 50.0, "amount_due": 0.0}
        self.assertEqual(_row_net(r), -50.0)
        self.assertEqual(compute_statement_total_from_invoices([r]), -50.0)

    def test_credit_only_row_is_unchanged(self):
        r = {"invoice_number": "P1", "outstanding_amount": None, "credit": 30.0, "amount_due": None}
        self.assertEqual(_row_net(r), -30.0)

    def test_charge_and_credit_without_a_balance_is_unchanged(self):
        r = {"invoice_number": "X1", "outstanding_amount": 137.0, "credit": 30.0, "amount_due": None}
        self.assertEqual(_row_net(r), -30.0)
        self.assertEqual(compute_statement_total_from_invoices([r]), -30.0)

    def test_charge_and_credit_whose_balance_is_not_the_difference_is_unchanged(self):
        r = {"invoice_number": "X1", "outstanding_amount": 137.0, "credit": 30.0, "amount_due": 108.0}
        self.assertEqual(_row_net(r), -30.0)
        self.assertEqual(compute_statement_total_from_invoices([r]), -30.0)

    def test_non_numeric_values_are_left_to_the_old_rule(self):
        r = {"invoice_number": "X1", "outstanding_amount": "137.00", "credit": 30.0, "amount_due": 107.0}
        self.assertEqual(_row_net(r), -30.0)


class TestRowVerifier(unittest.TestCase):

    def setUp(self):
        m._PAGES_CACHE.clear()

    def pdf(self, printed=PRINTED, total="572.00"):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        for x, y, text in [(30, 50, "SYNTHETIC WHEEL REPAIR CO"), (30, 62, "STATEMENT OF ACCOUNT"),
                           (30, 74, "Customer Test Body Shop")]:
            page.insert_text((x, y), text, fontsize=9)
        for key, label in HEADER:
            page.insert_text((X[key], 120), label, fontsize=9)
        y = 136
        for invoice, date, charge, payment, balance in printed:
            for key, value in (("date", date), ("inv", invoice), ("svc", "Wheels"), ("charge", charge),
                               ("tax", "0.00"), ("pay", payment), ("bal", balance)):
                page.insert_text((X[key], y), value, fontsize=9)
            y += 14
        page.insert_text((X["pay"], y + 12), "Total Due:", fontsize=9)
        page.insert_text((X["bal"], y + 12), total, fontsize=9)
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.close()
        doc.save(f.name)
        self.addCleanup(os.remove, f.name)
        return f.name

    def test_every_row_is_verified_with_its_charge_payment_and_balance(self):
        result = m.check_pdf_row_match(TOTAL, rows(), pdf_path=self.pdf())
        self.assertTrue(result["passed"], result.get("reason"))
        self.assertEqual(result["rows_verified"], 3)

    def test_the_full_match_passes_cell_by_cell(self):
        result = m.check_pdf_full_match(TOTAL, rows(), pdf_path=self.pdf())
        self.assertTrue(result["passed"], result.get("reason"))
        self.assertEqual(result["computed"], TOTAL)

    def test_a_wrong_charge_fails(self):
        rs = rows()
        rs[0].update(outstanding_amount=138.0, amount_due=108.0)
        result = m.check_pdf_row_match(TOTAL + 1, rs, pdf_path=self.pdf())
        self.assertFalse(result["passed"])
        self.assertEqual(result["problem_counts"]["wrong"], 1)

    def test_a_wrong_payment_fails(self):
        rs = rows()
        rs[1].update(credit=-91.0, amount_due=354.0)
        result = m.check_pdf_row_match(TOTAL - 1, rs, pdf_path=self.pdf())
        self.assertFalse(result["passed"])

    def test_a_balance_the_pdf_does_not_print_fails(self):
        printed = list(PRINTED)
        printed[2] = ("I-000-500103", "09/22/2026", "140.00", "-30.00", "111.00")
        result = m.check_pdf_row_match(TOTAL, rows(), pdf_path=self.pdf(printed))
        self.assertFalse(result["passed"])
        self.assertIn("balance", result["offending_rows"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
