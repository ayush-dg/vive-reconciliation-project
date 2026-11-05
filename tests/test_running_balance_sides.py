"""
tests/test_running_balance_sides.py

Amounts read on the wrong side of a running balance (2026-11-05, Elite Auto
Glass STMT-ADEF9707: Invoiced / Paid / Balance). "Invoiced" is now a charge
column, so the running Balance is no longer summed as the charge; and a
charge-only row whose balance went DOWN by exactly that amount becomes a
payment (and the reverse), only when the running balance then holds on every
row. src/validation/running_balance_sides.py; wired in
notebooks/01_document_intake.py _try_running_balance_sides().
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.ai.claude_sonnet_client import ClaudeSonnetClient
from src.validation import running_balance_sides as rbs
from src.validation.arithmetic_gate import compute_statement_total_from_invoices


def _inv(n, charge=None, credit=None, balance=None):
    return {"invoice_number": f"INV{n}", "invoice_date": "2026-10-30",
            "outstanding_amount": charge, "amount": charge, "charges": charge,
            "credit": credit, "credits": credit, "amount_due": balance}


def _ledger(previous, entries):
    """[(charge, credit, read_as)] -> invoices with a true running balance;
    read_as "swap" puts the amount on the wrong side, as the AI did."""
    balance, out = previous, []
    for i, (charge, credit, read_as) in enumerate(entries):
        balance = round(balance + (charge or 0) - (credit or 0), 2)
        if read_as == "swap":
            charge, credit = credit, charge
        out.append(_inv(i, charge, credit, balance))
    return out


class TestPlan(unittest.TestCase):
    def test_payments_read_as_charges_are_moved(self):
        invs = _ledger(1000.0, [(100, None, ""), (50, None, ""), (None, 135, "swap"), (None, 270, "swap"),
                                (20, None, ""), (None, 40, "")])
        plan = rbs.plan_running_balance_sides(invs, 1000.0)
        self.assertTrue(plan["applicable"], plan["reason"])
        self.assertEqual([(m["index"], m["to"], m["amount"]) for m in plan["moves"]],
                         [(2, "credit", 135.0), (3, "credit", 270.0)])
        rbs.apply_running_balance_sides(plan, invs)
        self.assertEqual(round(1000.0 + compute_statement_total_from_invoices(invs), 2), invs[-1]["amount_due"])
        self.assertIsNone(invs[2]["outstanding_amount"])
        self.assertEqual(invs[2]["credit"], 135.0)
        self.assertEqual(rbs.plan_running_balance_sides(invs, 1000.0)["moves"], [])

    def test_a_charge_read_as_a_payment_is_moved_back(self):
        invs = _ledger(0.0, [(10, None, ""), (20, None, ""), (30, None, "swap"), (40, None, ""), (None, 5, "")])
        plan = rbs.plan_running_balance_sides(invs, 0.0)
        self.assertEqual([(m["index"], m["to"]) for m in plan["moves"]], [(2, "charge")])
        rbs.apply_running_balance_sides(plan, invs)
        self.assertEqual((invs[2]["outstanding_amount"], invs[2]["credit"]), (30.0, None))

    def test_without_a_previous_balance_the_chain_starts_at_the_first_row(self):
        invs = _ledger(500.0, [(10, None, ""), (20, None, ""), (None, 30, "swap"), (40, None, ""), (5, None, "")])
        plan = rbs.plan_running_balance_sides(invs, None)
        self.assertEqual([m["index"] for m in plan["moves"]], [2])

    def test_a_break_no_move_explains_changes_nothing(self):
        invs = _ledger(0.0, [(10, None, ""), (20, None, ""), (None, 30, "swap"), (40, None, ""), (5, None, "")])
        invs[4]["amount_due"] += 7.77   # a row that fits neither side
        plan = rbs.plan_running_balance_sides(invs, 0.0)
        self.assertFalse(plan["applicable"])
        self.assertIn("does not hold on 1 row", plan["reason"])

    def test_a_per_row_open_balance_is_never_touched(self):
        # Keystone-style: amount_due is each invoice's own open amount, not a running total.
        invs = [_inv(i, charge=c, balance=c) for i, c in enumerate((100.0, 25.5, 60.0, 12.0, 80.0))]
        plan = rbs.plan_running_balance_sides(invs, None)
        self.assertFalse(plan["applicable"])
        self.assertEqual(plan["moves"], [])

    def test_a_row_with_both_a_charge_and_a_payment_is_never_moved(self):
        invs = _ledger(0.0, [(10, None, ""), (20, None, ""), (40, 5, ""), (30, None, ""), (5, None, "")])
        invs[2]["amount_due"] = round(invs[1]["amount_due"] - 35, 2)   # would fit a flip, but the row has both
        invs[3]["amount_due"] = round(invs[2]["amount_due"] + 30, 2)
        invs[4]["amount_due"] = round(invs[3]["amount_due"] + 5, 2)
        self.assertFalse(rbs.plan_running_balance_sides(invs, 0.0)["applicable"])

    def test_too_few_rows(self):
        invs = _ledger(0.0, [(10, None, ""), (None, 20, "swap")])
        plan = rbs.plan_running_balance_sides(invs, 0.0)
        self.assertFalse(plan["applicable"])
        self.assertIn("needs 5", plan["reason"])

    def test_no_balance_column_is_not_applicable(self):
        self.assertEqual(rbs.plan_running_balance_sides([_inv(1, 10)], None)["reason"], rbs.NOT_APPLICABLE)

    def test_switch(self):
        with mock.patch.dict(os.environ, {rbs.ENV_FLAG: "false"}):
            self.assertFalse(rbs.enabled())
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(rbs.ENV_FLAG, None)
            self.assertTrue(rbs.enabled())

    def test_record_says_what_moved(self):
        invs = _ledger(1000.0, [(100, None, ""), (50, None, ""), (None, 135, "swap"), (20, None, ""), (5, None, "")])
        rec = rbs.record(rbs.plan_running_balance_sides(invs, 1000.0), invs)
        self.assertEqual(rec, [{"row_number": 3, "invoice_number": "INV2", "date": "2026-10-30", "amount": 135.0,
                                "from": "charge", "to": "payment", "balance": 1015.0}])


class TestInvoicedIsACharge(unittest.TestCase):
    def test_elite_layout_maps_invoiced_and_keeps_balance_as_the_running_balance(self):
        cols = ["Date", "Transaction", "Account", "Reference", "Invoiced", "Paid", "Balance"]
        rows = [{"Date": "2026-10-04", "Transaction": "11069", "Account": "VIVE", "Reference": "7800076",
                 "Invoiced": 3.38, "Paid": None, "Balance": 9282.44}]
        field_map = ClaudeSonnetClient.__new__(ClaudeSonnetClient)._map_columns(cols, rows)
        self.assertEqual((field_map["charges"], field_map["credit"], field_map["amount_due"]),
                         ("Invoiced", "Paid", "Balance"))
        inv = ClaudeSonnetClient.__new__(ClaudeSonnetClient)._rows_to_invoices(rows, cols)[0][0]
        self.assertEqual((inv["outstanding_amount"], inv["amount_due"]), (3.38, 9282.44))

    def test_invoiced_date_is_still_a_date(self):
        field_map = ClaudeSonnetClient.__new__(ClaudeSonnetClient)._map_columns(
            ["Invoiced Date", "Invoice #", "Amount"], [{"Invoiced Date": "2026-10-01", "Invoice #": "1", "Amount": 5.0}])
        self.assertEqual(field_map["invoice_date"], "Invoiced Date")
        self.assertEqual(field_map["charges"], "Amount")


class TestIntakeWiring(unittest.TestCase):
    """The intake keeps the moves only when the whole gate then passes."""

    @classmethod
    def setUpClass(cls):
        from test_intake_sharepoint_hook import load_intake
        cls.intake = load_intake()

    def _schema(self, invs, printed):
        return {"invoices": invs, "document_metadata": {"document_type": "VENDOR_STATEMENT"},
                "vendor_metadata": {"vendor_name": "Synthetic Glass"},
                "statement_metadata": {"statement_total_as_printed": printed, "previous_balance": 1000.0,
                                       "previous_balance_label": "Previous Balance",
                                       "statement_total_computed": compute_statement_total_from_invoices(invs)}}

    def _validate(self, schema):
        text = "Previous Balance 1,000.00\nTotal Due 865.00\n"
        with mock.patch("builtins.print"), \
                mock.patch.object(self.intake, "text_columns", mock.Mock(enabled=lambda: False)), \
                mock.patch.object(self.intake, "resolve_vendor_id", return_value="SYNTHETIC_GLASS"):
            return self.intake.apply_arithmetic_validation(schema, text, None)

    def test_moves_are_kept_when_the_statement_then_passes(self):
        invs = _ledger(1000.0, [(100, None, ""), (50, None, ""), (None, 135, "swap"), (None, 170, "swap"),
                                (20, None, "")])
        schema = self._schema(invs, invs[-1]["amount_due"])
        v = self._validate(schema)
        self.assertEqual(v["status"], "matches", v)
        self.assertEqual(len(v["detail"]["running_balance_corrections"]), 2)
        self.assertEqual(invs[2]["credit"], 135.0)

    def test_nothing_changes_when_the_statement_still_fails(self):
        invs = _ledger(1000.0, [(100, None, ""), (50, None, ""), (None, 135, "swap"), (None, 170, "swap"),
                                (20, None, "")])
        schema = self._schema(invs, 12345.67)   # a printed total the rows can never reach
        v = self._validate(schema)
        self.assertEqual(v["status"], "mismatch")
        self.assertNotIn("running_balance_corrections", v.get("detail") or {})
        self.assertEqual(invs[2]["outstanding_amount"], 135.0)   # untouched
        self.assertIn("running_balance_check", v["detail"])


if __name__ == "__main__":
    unittest.main()
