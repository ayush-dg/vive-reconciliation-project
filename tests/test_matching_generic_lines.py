"""
tests/test_matching_generic_lines.py

The vendor-agnostic line handling in src/matching/fabric_matching.py
(2026-10-21): every line printed under one statement invoice is part of that
invoice, not a separate invoice. Exact duplicate lines count once; a credit
filed under a number containing the invoice matches at the exact amount; and,
after matching, a line that didn't match but pays off its invoice's charge is
set aside, and a mismatch against a NetSuite record another line matched is
Not Found. Cases are the real ones from prod (Gates GMC, Columbia Ford, NYE,
Nucar). Pure functions only -- nothing touches Fabric.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.matching import fabric_matching as fm


def _line(n, inv, line_type, charge=None, payment=None, **extra):
    return {"statement_line_id": f"L{n}", "line_number": n, "invoice_number": inv, "line_type": line_type,
            "charge_amount": charge, "payment_amount": payment, "line_date": extra.get("line_date"),
            "invoice_number_ref": extra.get("ref"), "transaction_code": extra.get("code"),
            "document_number": extra.get("doc", inv)}


def _decision(line, kind, stmt_amount, record=None):
    return {"item": line, "inv": line["invoice_number"], "kind": kind, "stmt_amount": stmt_amount,
            "netsuite_total": None if record is None else record["amount"], "ns_record": record,
            "rule": None, "table": "netsuite_vendorcredit"}


class SettleUnmatchedLinesTests(unittest.TestCase):
    def test_a_payment_closing_a_matched_invoice_is_set_aside(self):
        # Gates GMC 322756: charge matched; -1272.32 pays it off; -75 is a credit.
        charge = _line(1, "322756", "CHARGE", 1272.32)
        payoff = _line(2, "322756", "CREDIT", -1272.32)
        credit = _line(3, "322756", "CREDIT", -75.0)
        decisions = [
            _decision(charge, "match", 1272.32, {"record_type": "bill", "id": 1, "amount": 1272.32}),
            _decision(payoff, "Not Found in NetSuite", 1272.32),
            _decision(credit, "Not Found in NetSuite", 75.0),
        ]
        fm._settle_unmatched_lines(decisions, [charge, payoff, credit])
        self.assertEqual([d["kind"] for d in decisions], ["match", "set_aside", "Not Found in NetSuite"])
        self.assertIn("322756", decisions[1]["note"])

    def test_a_credit_memo_for_the_full_amount_that_matched_is_untouched(self):
        # NYE CM251052C-2: the code-4 credit memo is in NetSuite at the full
        # charge amount; only the code-5 payment that also equals it is set aside.
        charge = _line(104, "251052C-2", "CHARGE", 67.01)
        memo = _line(105, "251052C-2", "CREDIT", -67.01, code="4")
        payment = _line(106, "251052C-2", "CREDIT", -67.01, code="5")
        decisions = [
            _decision(charge, "match", 67.01, {"record_type": "bill", "id": 1, "amount": 67.01}),
            _decision(memo, "match", 67.01, {"record_type": "credit", "id": 2, "amount": 67.01}),
            _decision(payment, "Amount Mismatch", 67.01, {"record_type": "credit", "id": 3, "amount": 60.0}),
        ]
        fm._settle_unmatched_lines(decisions, [charge, memo, payment])
        self.assertEqual([d["kind"] for d in decisions], ["match", "match", "set_aside"])

    def test_a_charge_that_is_not_in_netsuite_stays_an_exception(self):
        # Columbia Ford 243955: the bill isn't in NetSuite -- one exception
        # for the charge, the two lines paying it are set aside.
        charge = _line(7, "243955", "CHARGE", 17.87)
        lines = [charge, _line(8, "243955", "CREDIT", -17.87, code="85"), _line(9, "243955", "CREDIT", -17.87, code="50")]
        decisions = [_decision(charge, "Not Found in NetSuite", 17.87)] + [
            _decision(l, "Not Found in NetSuite", 17.87) for l in lines[1:]]
        fm._settle_unmatched_lines(decisions, lines)
        self.assertEqual([d["kind"] for d in decisions], ["Not Found in NetSuite", "set_aside", "set_aside"])

    def test_a_credit_with_no_charge_on_its_invoice_is_never_set_aside(self):
        memo = _line(45, "CM6303960", "CREDIT", -62.31)
        decisions = [_decision(memo, "Not Found in NetSuite", 62.31)]
        fm._settle_unmatched_lines(decisions, [memo])
        self.assertEqual(decisions[0]["kind"], "Not Found in NetSuite")

    def test_a_mismatch_against_a_record_another_line_matched_becomes_not_found(self):
        # Nucar: line 49 matched CM6303960-1 exactly; line 46's $125 had been
        # compared with that same record.
        record = {"record_type": "credit", "id": 77, "amount": 75.0}
        exact = _decision(_line(49, "CM6303960-1", "CREDIT", -75.0), "match", 75.0, record)
        near = _decision(_line(46, "CM6303960", "CREDIT", -125.0), "Amount Mismatch", 125.0, dict(record))
        fm._settle_unmatched_lines([near, exact], [near["item"], exact["item"]])
        self.assertEqual((near["kind"], near["netsuite_total"], near["ns_record"]), ("Not Found in NetSuite", None, None))
        self.assertEqual(exact["kind"], "match")

    def test_a_mismatch_against_an_unused_record_stays_a_mismatch(self):
        charge = _line(1, "500100", "CHARGE", 100.0)
        decisions = [_decision(charge, "Amount Mismatch", 100.0, {"record_type": "bill", "id": 5, "amount": 90.0})]
        fm._settle_unmatched_lines(decisions, [charge])
        self.assertEqual(decisions[0]["kind"], "Amount Mismatch")


class ExactDuplicateLinesTests(unittest.TestCase):
    def test_identical_lines_count_once(self):
        a = _line(1, "CM274949", "CREDIT", -30.06, line_date="2026-08-01")
        b = dict(a, statement_line_id="L2", line_number=2)
        self.assertEqual(fm._drop_exact_duplicate_lines([a, b]), [a])

    def test_a_different_date_or_reference_keeps_both(self):
        a = _line(1, "CM6283886", "CREDIT", -75.0, line_date="2026-08-01", ref="CMCVW6283886")
        b = dict(a, statement_line_id="L2", line_number=2, invoice_number_ref="CMCVW6283886*1")
        c = dict(a, statement_line_id="L3", line_number=3, line_date="2026-09-01")
        self.assertEqual(len(fm._drop_exact_duplicate_lines([a, b, c])), 3)


class CreditContainingInvoiceTests(unittest.TestCase):
    def _credits(self, **by_tranid):
        c = fm._Candidates()
        c.update({k.lower(): v for k, v in by_tranid.items()})
        return c

    def test_a_credit_whose_number_contains_the_invoice_matches_at_the_exact_amount(self):
        credits = self._credits(**{"243726cr": [58.35], "243726cr-1": [85.27]})
        self.assertEqual(fm._credit_containing_invoice(credits, "243726", 85.27), ("243726cr-1", 85.27))

    def test_no_match_at_a_different_amount(self):
        self.assertIsNone(fm._credit_containing_invoice(self._credits(**{"243726cr": [58.35]}), "243726", 60.0))

    def test_two_records_at_that_amount_is_ambiguous(self):
        credits = self._credits(**{"243726cr": [58.35], "x243726": [58.35]})
        self.assertIsNone(fm._credit_containing_invoice(credits, "243726", 58.35))

    def test_short_numbers_are_not_searched(self):
        self.assertIsNone(fm._credit_containing_invoice(self._credits(**{"cm1234x": [10.0]}), "1234", 10.0))


class PreviousRunTimeTests(unittest.TestCase):
    class _Cur:
        def __init__(self, row):
            self.row, self.sql = row, None

        def execute(self, sql, params):
            self.sql = sql

        def fetchone(self):
            return self.row

    def test_the_stored_timestamp_is_reused(self):
        from datetime import datetime
        cur = self._Cur((datetime(2026, 10, 13, 13, 42, 19),))
        self.assertEqual(fm._previous_run_time(cur, "STMT-1"), "2026-10-13T13:42:19")
        self.assertIn("silver.recon_summary", cur.sql)

    def test_no_earlier_result_gives_none(self):
        self.assertIsNone(fm._previous_run_time(self._Cur(None), "STMT-1"))


class SwitchTests(unittest.TestCase):
    def test_on_by_default_and_off_with_false(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MATCHING_GENERIC_LINES", None)
            self.assertTrue(fm._generic_lines_enabled())
        with mock.patch.dict(os.environ, {"MATCHING_GENERIC_LINES": "false"}):
            self.assertFalse(fm._generic_lines_enabled())


if __name__ == "__main__":
    unittest.main()
