"""
tests/test_last_payment_notes.py

src/validation/last_payment.py -- an unlabelled "LAST PAYMENT" note that the
extraction model returned as a line item (MAINE OXY, 2026-10-01) is
recognised from the PDF text layer. Synthetic text and rows only.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.validation.arithmetic_gate import compute_statement_total_from_invoices
from src.validation.last_payment import last_payment_note_amounts, mark_last_payment_notes


def maine_oxy_text(*extra_lines):
    return "\n".join([
        "STATEMENT",
        "TOTAL BALANCE:",
        "165.11",
        "08/31/26 5000359406 6 165.11",
        "LAST PAYMENT: 07/21/26 134.03",
        "165.11 .00 .00 .00 .00",
        *extra_lines,
    ])


def row(invoice_number, out=None, credit=None, **extra):
    inv = {"invoice_number": invoice_number, "outstanding_amount": out, "amount": out, "charges": out,
           "credit": credit, "credits": credit, "amount_due": None, "informational": False}
    inv.update(extra)
    return inv


class TestLastPaymentNoteAmounts(unittest.TestCase):

    def test_amount_only_on_the_last_payment_line(self):
        self.assertEqual(last_payment_note_amounts(maine_oxy_text()), {134.03})

    def test_amount_also_printed_elsewhere_is_excluded(self):
        text = maine_oxy_text("07/21/26 PAYMENT - THANK YOU 134.03")
        self.assertEqual(last_payment_note_amounts(text), set())

    def test_no_text_layer(self):
        self.assertEqual(last_payment_note_amounts(None), set())
        self.assertEqual(last_payment_note_amounts(""), set())


class TestMarkLastPaymentNotes(unittest.TestCase):

    def test_unlabelled_note_row_becomes_informational(self):
        rows = [row("5000359406", 165.11), row(None, 134.03, invoice_date="07/21/26")]
        self.assertEqual(compute_statement_total_from_invoices(rows), 299.14)  # Oct 1: counted as a charge
        self.assertEqual(mark_last_payment_notes(rows, maine_oxy_text()), 1)
        self.assertTrue(rows[1]["informational"])
        self.assertIsNone(rows[1]["outstanding_amount"])
        self.assertEqual(compute_statement_total_from_invoices(rows), 165.11)
        self.assertEqual(len(rows), 2)  # the row itself is kept

    def test_real_payment_row_inside_the_table_is_not_affected(self):
        # The same payment amount printed on its own table line -> not a note.
        text = maine_oxy_text("07/21/26 PAYMENT - THANK YOU (134.03)")
        rows = [row("5000359406", 165.11), row(None, credit=134.03)]
        self.assertEqual(mark_last_payment_notes(rows, text), 0)
        self.assertEqual(rows[1]["credit"], 134.03)
        self.assertFalse(rows[1]["informational"])

    def test_payment_row_with_a_different_amount_is_not_affected(self):
        rows = [row("5000359406", 165.11), row(None, credit=500.0)]
        self.assertEqual(mark_last_payment_notes(rows, maine_oxy_text()), 0)
        self.assertEqual(rows[1]["credit"], 500.0)

    def test_row_with_an_invoice_number_is_not_affected(self):
        rows = [row("5000359406", 165.11), row("INV-134", 134.03)]
        self.assertEqual(mark_last_payment_notes(rows, maine_oxy_text()), 0)
        self.assertEqual(rows[1]["outstanding_amount"], 134.03)

    def test_nothing_happens_without_a_text_layer(self):
        rows = [row(None, 134.03)]
        self.assertEqual(mark_last_payment_notes(rows, None), 0)
        self.assertEqual(rows[0]["outstanding_amount"], 134.03)


if __name__ == "__main__":
    unittest.main()
