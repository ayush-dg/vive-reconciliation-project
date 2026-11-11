"""
tests/test_payment_rows.py

A payment printed as a row but read as a positive charge (2026-11-11, Colonie
Garage STMT-91096ABB: Previous Balance 2,354.38 / Order/Invoice Number
300720097 1,036.17 / "Payment - Thank You" 2,354.38 / Balance 1,036.17, all
unsigned). src/validation/payment_rows.py; wired in
notebooks/01_document_intake.py _try_payment_rows().
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.validation import payment_rows as pr
from src.validation.arithmetic_gate import compute_statement_total_from_invoices


def _row(date, text, amount):
    """A row shaped as the AI returns an unlabelled Colonie line."""
    return {"outstanding_amount": amount, "page_number": 1, "transaction_code": f"{date} {text} {amount}",
            "_raw_row": {"UNLABELED_TRANSACTION_CODE": date, "UNLABELED_TRANSACTION_CODE_2": text,
                         "UNLABELED_TRANSACTION_CODE_3": amount}}


def _colonie():
    return [_row("10/15/26", "Order/Invoice Number 300720097", 1036.17),
            _row("10/26/26", "Payment - Thank You", 2354.38)]


class TestPlan(unittest.TestCase):
    def test_colonie_payment_row_becomes_a_credit_by_the_statement_equation(self):
        invs = _colonie()
        plan = pr.plan_payment_rows(invs, 3390.55, 1036.17, 2354.38)
        self.assertTrue(plan["applicable"], plan)
        self.assertEqual([r["index"] for r in plan["rows"]], [1])
        self.assertEqual(plan["rows"][0]["text"], "10/26/26 Payment - Thank You")
        self.assertEqual(pr.apply_payment_rows(plan, invs), 1)
        self.assertEqual(invs[1]["credit"], 2354.38)
        self.assertIsNone(invs[1]["outstanding_amount"])
        self.assertEqual(compute_statement_total_from_invoices(invs), round(1036.17 - 2354.38, 2))

    def test_without_a_previous_balance_the_rows_alone_must_reach_the_printed_total(self):
        invs = [_row("10/01/26", "Invoice 1001", 500.0), _row("10/02/26", "Invoice 1002", 300.0),
                _row("10/05/26", "PYMT received", 200.0)]
        plan = pr.plan_payment_rows(invs, 1000.0, 600.0)
        self.assertTrue(plan["applicable"], plan)

    def test_nothing_when_the_total_still_does_not_add_up(self):
        plan = pr.plan_payment_rows(_colonie(), 3390.55, 999.99, 2354.38)
        self.assertFalse(plan["applicable"])
        self.assertIn("not the printed 999.99", plan["reason"])

    def test_a_late_payment_fee_is_a_charge_not_a_payment(self):
        invs = [_row("10/01/26", "Invoice 1001", 500.0), _row("10/20/26", "Late Payment Fee", 25.0)]
        self.assertEqual(pr.plan_payment_rows(invs, 525.0, 475.0)["reason"], pr.NOT_APPLICABLE)

    def test_payment_due_and_finance_charge_are_not_payments(self):
        for text in ("Payment Due 11/15/26", "Finance charge on past due payment", "Interest"):
            self.assertFalse(pr.reads_as_payment(text), text)
        for text in ("Payment - Thank You", "PYMT #4471", "Paid by check 1203", "Remittance", "Thank you"):
            self.assertTrue(pr.reads_as_payment(text), text)

    def test_a_row_already_holding_a_credit_is_never_touched(self):
        invs = _colonie()
        invs[1]["credit"] = 2354.38
        self.assertEqual(pr.plan_payment_rows(invs, 3390.55, 1036.17, 2354.38)["reason"], pr.NOT_APPLICABLE)

    def test_text_fields_are_used_when_there_are_no_raw_cells(self):
        inv = {"description": "Payment received - thank you", "amount": 40.0}
        self.assertEqual(pr.row_text(inv), "Payment received - thank you")

    def test_switch(self):
        with mock.patch.dict(os.environ, {pr.ENV_FLAG: "false"}):
            self.assertFalse(pr.enabled())
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(pr.ENV_FLAG, None)
            self.assertTrue(pr.enabled())


class TestIntake(unittest.TestCase):
    """Through the intake's own gate: kept only when the statement then passes."""

    @classmethod
    def setUpClass(cls):
        from src.rerun import in_place
        cls.intake = in_place.load_intake()

    def _schema(self, invs, printed):
        return {"invoices": invs,
                "vendor_metadata": {"vendor_name": "Colonie Garage, Inc."},
                "statement_metadata": {"statement_total_as_printed": printed, "previous_balance": 2354.38,
                                       "previous_balance_label": "Previous Balance",
                                       "statement_total_computed": compute_statement_total_from_invoices(invs)}}

    def _validate(self, schema):
        with mock.patch("builtins.print"), \
                mock.patch.object(self.intake, "text_columns", mock.Mock(enabled=lambda: False)), \
                mock.patch.object(self.intake, "resolve_vendor_id", return_value="COLONIE_GARAGE_INC."):
            return self.intake.apply_arithmetic_validation(schema, "", None)

    def test_colonie_passes_after_the_payment_row_is_a_credit(self):
        invs = _colonie()
        v = self._validate(self._schema(invs, 1036.17))
        self.assertEqual(v["status"], "matches", v)
        self.assertEqual(v["detail"]["payment_row_corrections"][0]["amount"], 2354.38)
        self.assertEqual(invs[1]["credit"], 2354.38)

    def test_nothing_changes_when_the_statement_still_fails(self):
        invs = _colonie()
        v = self._validate(self._schema(invs, 12345.67))
        self.assertEqual(v["status"], "mismatch")
        self.assertNotIn("payment_row_corrections", v.get("detail") or {})
        self.assertEqual(invs[1]["outstanding_amount"], 2354.38)
        self.assertIn("payment_row_check", v["detail"])


if __name__ == "__main__":
    unittest.main()
