"""
tests/test_payment_column.py

A bare "Payment" column the client leaves unmapped (no balance column on the
document) -- Blue Sun Quonset STMT-B0E5C001, 2026-10-26: the Sep 30
statement prints a previous balance, and 15,510.89 + 4,479.94 - 6,754.82 =
13,236.01, but its "Pymt 6,754.82" row carried no amount, so the gate
computed 19,990.83.

The intake now maps that column as a credit only when the statement equation
(previous balance + amounts - payments = printed total) then closes and the
whole gate passes by statement_equation. Otherwise nothing changes -- in
particular a statement whose printed total is the sum of Amount (the Oct 1
Blue Sun layout the client's rule protects) passes as before with the column
unmapped.

The rows go through ClaudeSonnetClient._rows_to_invoices exactly as the
model's rows do. OCR is mocked: no tesseract, network or database. Synthetic
data only.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.ai.claude_sonnet_client import ClaudeSonnetClient
from src.rerun.in_place import load_intake
from src.validation.arithmetic_gate import compute_statement_total_from_invoices

INTAKE = load_intake()
COLUMNS = ["Date", "Invoice#", "Description", "P.O.#", "Amount", "Payment"]


def raw(date, invoice, desc, amount=None, payment=None):
    return {"Date": date, "Invoice#": invoice, "Description": desc, "P.O.#": None, "Amount": amount,
            "Payment": payment, "confidence": 0.99}


def invoices(rows):
    client = ClaudeSonnetClient.__new__(ClaudeSonnetClient)
    return client._rows_to_invoices([dict(r) for r in rows], COLUMNS)[0]


def statement(rows, printed, previous=1000.0, label="PREVIOUS BALANCE"):
    inv = invoices(rows)
    return {"document_metadata": {"document_type": "VENDOR_STATEMENT"},
            "vendor_metadata": {"vendor_name": "Synthetic Towing Service"},
            "statement_metadata": {"statement_total_as_printed": printed,
                                   "statement_total_computed": compute_statement_total_from_invoices(inv),
                                   "previous_balance": previous, "previous_balance_label": label},
            "invoices": inv}


SEP = [raw("3-Sep-26", "T-100", "Repairs", amount=100.0),
       raw("14-Sep-26", None, "Pymt", payment=250.0),
       raw("16-Sep-26", "T-101", "Tow", amount=200.0)]


def validate(s):
    with mock.patch.object(INTAKE, "ocr_pdf_text", return_value=""), mock.patch("builtins.print"):
        return INTAKE.apply_arithmetic_validation(s, "", "scan.pdf")


class TestPaymentColumn(unittest.TestCase):

    def test_the_client_leaves_the_payment_unmapped(self):
        pymt = invoices(SEP)[1]
        self.assertIsNone(pymt["credit"])
        self.assertEqual(pymt["_raw_row"]["Payment"], 250.0)

    def test_payment_mapped_when_the_statement_equation_closes(self):
        s = statement(SEP, printed=1050.0)          # 1,000.00 + 300.00 - 250.00
        result = validate(s)
        self.assertEqual((result["status"], result["method"]), ("matches", "statement_equation"))
        self.assertEqual(s["invoices"][1]["credit"], 250.0)
        self.assertEqual(s["statement_metadata"]["statement_total_computed"], 50.0)
        fixes = result["detail"]["payment_column_corrections"]
        self.assertEqual([(f["date"], f["payment"], f["column"]) for f in fixes], [("14-Sep-26", 250.0, "Payment")])

    def test_unchanged_when_the_equation_does_not_close(self):
        s = statement(SEP, printed=1060.0)
        result = validate(s)
        self.assertEqual(result["status"], "mismatch")
        self.assertIsNone(s["invoices"][1]["credit"])
        self.assertIn("does not close", result["detail"]["payment_column_check"]["reason"])

    def test_oct_1_layout_printed_total_is_the_sum_of_amount_is_unchanged(self):
        s = statement(SEP, printed=300.0, previous=None, label=None)
        result = validate(s)
        self.assertEqual((result["status"], result["method"]), ("matches", "primary"))
        self.assertIsNone(s["invoices"][1]["credit"])
        self.assertNotIn("payment_column_corrections", result.get("detail") or {})

    def test_unchanged_without_a_verified_previous_balance(self):
        s = statement(SEP, printed=1050.0, label="08/31/26")   # a date, not a balance-forward label
        result = validate(s)
        self.assertEqual(result["status"], "mismatch")
        self.assertIsNone(s["invoices"][1]["credit"])

    def test_unchanged_when_a_paid_row_also_has_a_charge(self):
        rows = [raw("3-Sep-26", "T-100", "Repairs", amount=100.0),
                raw("14-Sep-26", "T-100", "Pymt", amount=40.0, payment=290.0),
                raw("16-Sep-26", "T-101", "Tow", amount=200.0)]
        s = statement(rows, printed=1050.0)
        result = validate(s)
        self.assertEqual(result["status"], "mismatch")
        self.assertIsNone(s["invoices"][1]["credit"])

    def test_switched_off(self):
        s = statement(SEP, printed=1050.0)
        with mock.patch.dict(os.environ, {"PAYMENT_COLUMN_CORRECTION_ENABLED": "false"}):
            result = validate(s)
        self.assertEqual(result["status"], "mismatch")
        self.assertIsNone(s["invoices"][1]["credit"])


if __name__ == "__main__":
    unittest.main()
