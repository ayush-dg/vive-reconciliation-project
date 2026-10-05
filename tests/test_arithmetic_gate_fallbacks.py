"""
tests/test_arithmetic_gate_fallbacks.py

The Arithmetic Validation Gate's fallback chain
(src/validation/arithmetic_gate.py validate_with_fallbacks()) and the
2026-10-06 gate fixes. Synthetic statements only -- each modelled on an
Oct 1 layout (named in the test) but with made-up rows.

The rule these tests enforce: a fallback may only pass when it reproduces
the printed total exactly (0.01) from extracted values, and every
deliberately wrong extraction (dropped row, misread amount, misplaced
payment, unverified previous balance, broken chain, partial section) must
fail every check.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.validation import arithmetic_gate as gate
from src.validation.arithmetic_gate import (
    compute_arithmetic_validation,
    compute_statement_total_from_invoices,
    compute_vendor_column_total,
    validate_with_fallbacks,
)


def row(invoice_number=None, out=None, credit=None, due=None, **extra):
    inv = {"invoice_number": invoice_number, "outstanding_amount": out, "credit": credit, "amount_due": due}
    inv.update(extra)
    return inv


def run(printed, rows, *, computed=None, **kwargs):
    if computed is None:
        computed = compute_statement_total_from_invoices(rows)
    return validate_with_fallbacks(printed, computed, rows, **kwargs)


def attempt(result, method):
    return next(a for a in result["detail"]["attempts"] if a["method"] == method)


def assert_every_check_failed(testcase, result):
    testcase.assertEqual(result["status"], "mismatch")
    testcase.assertIsNone(result["method"])
    testcase.assertTrue(result["detail"]["attempts"])
    for a in result["detail"]["attempts"]:
        testcase.assertFalse(a["passed"], a)


# ---------------------------------------------------------------------------
# Primary check and the small gate fixes
# ---------------------------------------------------------------------------

class TestPrimaryAndGateFixes(unittest.TestCase):

    def test_primary_match_is_reported_as_method_primary(self):
        rows = [row("A1", 100.0), row("A2", 50.0), row("CM1", credit=30.0)]
        result = run(120.0, rows)
        self.assertEqual(result["status"], "matches")
        self.assertEqual(result["method"], "primary")
        self.assertIsNone(result["detail"])

    def test_no_line_items_instead_of_mismatch_against_zero(self):
        # Wilbert's Inc. STMT-3C442D16: printed 1,373.00, nothing extracted.
        result = compute_arithmetic_validation(1373.0, None)
        self.assertEqual(result["status"], "no_line_items")
        self.assertIsNone(result["difference"])
        self.assertEqual(validate_with_fallbacks(1373.0, None, [])["status"], "no_line_items")

    def test_total_not_found_takes_precedence_and_runs_no_fallback(self):
        result = validate_with_fallbacks(None, 10.0, [row("A1", 10.0, due=10.0)])
        self.assertEqual(result["status"], "total_not_found")
        self.assertIsNone(result["detail"])

    def test_keystone_negative_payment_applied_nets_to_zero(self):
        # Keystone (First Choice) row G4795354: bf 16.83, payment_applied -16.83.
        settled = row("G4795354", balance_forward=16.83, payment_applied=-16.83)
        self.assertEqual(compute_statement_total_from_invoices([settled]), 0.0)
        positive = row("G1", balance_forward=16.83, payment_applied=16.83)
        self.assertEqual(compute_statement_total_from_invoices([positive]), 0.0)

    def test_vendor_column_matches_header_case_insensitively(self):
        with mock.patch.object(gate, "_load_total_columns", return_value={"FENIX_NE": "due"}):
            invoices = [{"_raw_row": {"Due": 315.0}}, {"_raw_row": {"Due": "1,095.00"}}]
            self.assertEqual(compute_vendor_column_total("FENIX_NE", invoices), 1410.0)

    def test_vendor_column_returns_none_when_no_row_has_the_column(self):
        # Fenix STMT-917D9B0A: Claude rows had no "due" key at all -- the
        # override must step aside (None), not replace a correct total with 0.
        with mock.patch.object(gate, "_load_total_columns", return_value={"FENIX_NE": "due"}):
            invoices = [{"_raw_row": {"Charged": 315.0}}, {"_raw_row": {"Charged": 115.0}}]
            self.assertIsNone(compute_vendor_column_total("FENIX_NE", invoices))


# ---------------------------------------------------------------------------
# Fallback 1 -- open_balance
# ---------------------------------------------------------------------------

def bishops_rows():
    """Bishop's 8741900 layout: Amount column includes a payment of older,
    unlisted invoices whose Balance is $0.00; printed = sum of Balance."""
    return [
        row("759975", 911.0, due=911.0, row_number=1),
        row("759976", 715.0, due=715.0, row_number=2),
        row(None, -1030.0, due=0.0, row_number=3),  # "Payment Inv{753767}"
        row("762588", 500.0, due=500.0, row_number=4),
    ]


class TestOpenBalance(unittest.TestCase):

    def test_passes_when_open_balances_sum_to_printed(self):
        result = run(2126.0, bishops_rows())
        self.assertEqual(result["status"], "matches")
        self.assertEqual(result["method"], "open_balance")
        self.assertEqual(result["computed"], 2126.0)
        self.assertEqual(result["detail"]["primary_computed"], 1096.0)

    def test_subtracts_unallocated_payments(self):
        # Autoly (Bow HEW 0826 shape): Balance due = Total due - Unallocated.
        rows = [
            row("816725", 650.0, due=650.0),
            row("816736", 180.0, due=180.0),
            row("817498", credit=650.0, due=0.0),
            row("chris", credit=3265.0, unallocated=650.0),
        ]
        result = run(180.0, rows)
        self.assertEqual(result["method"], "open_balance")

    def test_partial_open_balance_is_allowed(self):
        rows = [row("4525414164", 215.99, due=10.0), row("4525416569", 43.98, due=43.98)]
        self.assertEqual(run(53.98, rows)["method"], "open_balance")

    def test_adversarial_dropped_row_fails(self):
        rows = [r for r in bishops_rows() if r["invoice_number"] != "762588"]
        assert_every_check_failed(self, run(2126.0, rows))

    def test_adversarial_misread_open_balance_fails(self):
        rows = bishops_rows()
        rows[0]["amount_due"] = 917.0  # read 917.00 for 911.00
        result = run(2126.0, rows)
        assert_every_check_failed(self, result)
        self.assertTrue(attempt(result, "open_balance")["row_guard_failures"])

    def test_adversarial_misread_amount_and_balance_together_fails(self):
        rows = bishops_rows()
        rows[0]["outstanding_amount"] = rows[0]["amount_due"] = 917.0
        assert_every_check_failed(self, run(2126.0, rows))

    def test_adversarial_payment_misplaced_in_open_balance_column_fails(self):
        # Fred Beans (First Choice) shape: a payment's value read into the
        # Amount Due column of a row with no amount of its own. Here the sum
        # of open balances happens to equal the printed total, so only the
        # per-row guard stands between this wrong extraction and a pass.
        rows = [row("9485341", 500.0, due=500.0), row("9485342", 300.0, due=300.0), row("9485340", None, due=250.0)]
        result = run(1050.0, rows)
        assert_every_check_failed(self, result)
        ob = attempt(result, "open_balance")
        self.assertEqual(ob["computed"], 1050.0)  # the sum alone would have matched
        self.assertTrue(ob["row_guard_failures"])

    def test_adversarial_credit_memo_read_as_charge_fails(self):
        # Bowser Klapec: credit memos read as charges while the open-balance
        # column was read correctly -- sum of open balances alone matches.
        rows = [
            row("74369", 1082.03, due=0.0),
            row("CM74369", 125.0, due=-125.0),
            row("75001", 200.0, due=200.0),
        ]
        result = run(75.0, rows)
        assert_every_check_failed(self, result)
        self.assertTrue(attempt(result, "open_balance")["row_guard_failures"])

    def test_adversarial_payments_recorded_as_charges_fails_invoice_guard(self):
        # RH Long: payments recorded as charges under one check number.
        rows = [
            row("478393", None, due=None),
            row("220830", 125.0, due=0.0),
            row("479940", None, due=None),
            row("220830", 984.13, due=0.0),
            row("485478", 200.09, due=200.09),
        ]
        result = run(200.09, rows)
        assert_every_check_failed(self, result)
        self.assertTrue(attempt(result, "open_balance")["invoice_guard_failures"])

    def test_settlement_labels_without_digits_do_not_form_invoice_groups(self):
        # Lentini (M3): two "ROA" payments and a "Debit" -- not invoice numbers.
        rows = [
            row("800829", 75.0, due=75.0),
            row("ROA", -298.0, due=0.0),
            row("ROA", -7450.0, due=0.0),
            row("Debit", 7450.0, due=0.0),
        ]
        self.assertEqual(run(75.0, rows)["method"], "open_balance")

    def test_running_balance_column_is_not_treated_as_open_balances(self):
        rows = [row("A", 100.0, due=100.0), row("B", 50.0, due=150.0), row("C", 25.0, due=175.0)]
        result = run(425.0, rows, computed=0.0)  # 425 = naive sum of the running balances
        self.assertFalse(attempt(result, "open_balance")["applicable"])
        self.assertNotEqual(result["method"], "open_balance")

    def test_off_by_two_cents_fails(self):
        result = run(2126.02, bishops_rows())
        assert_every_check_failed(self, result)


# ---------------------------------------------------------------------------
# Fallback 2 -- statement_equation
# ---------------------------------------------------------------------------

def paragon_rows():
    """Paragon Harbour: Balance Forward 707.00 (not a row), payment of it,
    three invoices; BALANCE column is a running balance."""
    return [
        row("63170", 175.5, due=882.5),
        row("63240", 175.5, due=1058.0),
        row(None, -707.0, due=351.0),
        row("63527", 175.5, due=526.5),
    ]


class TestStatementEquation(unittest.TestCase):

    def test_passes_with_verified_previous_balance(self):
        result = run(526.5, paragon_rows(), previous_balance=707.0)
        self.assertEqual(result["status"], "matches")
        self.assertEqual(result["method"], "statement_equation")
        self.assertEqual(attempt(result, "statement_equation")["previous_balance"], 707.0)

    def test_partial_payment_of_previous_balance(self):
        # EAW LV 0826: previous 226.69, partial payment 211.34 -- excluding
        # the payment would NOT reconcile; previous + activity does.
        rows = [row("7008094", 26.48), row("7008203", 104.62), row("7008145", 211.54),
                row("CSH", credit=211.34), row("7008109", 26.48), row("SHOP", 399.0), row("1FC074189", credit=15.35)]
        self.assertEqual(run(768.12, rows, previous_balance=226.69)["method"], "statement_equation")

    def test_adversarial_previous_balance_missing_or_unverified_fails(self):
        # resolve_previous_balance() returns None for a value not on a
        # labelled line of the text layer -- the gate then has nothing to use.
        assert_every_check_failed(self, run(526.5, paragon_rows(), previous_balance=None))

    def test_adversarial_dropped_row_fails(self):
        rows = paragon_rows()[:-1]
        assert_every_check_failed(self, run(526.5, rows, previous_balance=707.0))

    def test_adversarial_misread_amount_fails(self):
        rows = paragon_rows()
        rows[1]["outstanding_amount"] = 178.5
        assert_every_check_failed(self, run(526.5, rows, previous_balance=707.0))

    def test_adversarial_payment_recorded_as_charge_fails(self):
        rows = paragon_rows()
        rows[2]["outstanding_amount"] = 707.0
        assert_every_check_failed(self, run(526.5, rows, previous_balance=707.0))

    def test_not_applied_to_open_item_statements(self):
        # O'Reilly prints a BEG. BALANCE but its rows are open items.
        rows = [row("A", 100.0, due=100.0), row("B", 40.0, due=40.0), row("V1", -500.0, due=0.0)]
        result = run(240.0, rows, previous_balance=600.0)
        self.assertFalse(attempt(result, "statement_equation")["applicable"])
        self.assertEqual(result["status"], "mismatch")


# ---------------------------------------------------------------------------
# Fallback 3 -- running_balance
# ---------------------------------------------------------------------------

def chain_rows():
    return [row("A", 100.0, due=100.0, row_number=1), row("B", 50.0, due=150.0, row_number=2),
            row("PMT", credit=30.0, due=120.0, row_number=3), row("C", 20.0, due=140.0, row_number=4)]


class TestRunningBalance(unittest.TestCase):

    def test_passes_when_chain_holds_from_zero(self):
        # computed=0.0 stands in for a primary total that disagrees (e.g. a
        # vendor column override), so F1/F2 can't pass and F3 must.
        result = run(140.0, chain_rows(), computed=0.0)
        self.assertEqual(result["method"], "running_balance")

    def test_chain_starts_from_printed_previous_balance(self):
        rows = [row("A", 61.5, due=1539.5), row("B", 109.5, due=1649.0), row("CHK", credit=1478.0, due=171.0)]
        result = gate._check_running_balance(171.0, rows, tolerance=0.01, previous_balance=1478.0)
        self.assertTrue(result["passed"])

    def test_adversarial_broken_chain_reports_first_broken_row(self):
        # Goldstein Subaru: a $252.67 charge read as a credit.
        rows = [row("47866", credit=649.88, due=-649.88, row_number=1),
                row("47877", credit=252.67, due=-397.21, row_number=2),
                row("47981", 1128.95, due=731.74, row_number=3)]
        result = gate._check_running_balance(731.74, rows, tolerance=0.01, previous_balance=None)
        self.assertFalse(result["passed"])
        self.assertEqual(result["first_broken_row"]["invoice_number"], "47877")
        self.assertEqual(result["first_broken_row"]["expected_balance"], -902.55)
        full = run(731.74, rows)
        assert_every_check_failed(self, full)
        self.assertEqual(attempt(full, "running_balance")["first_broken_row"]["position"], 2)

    def test_adversarial_dropped_first_row_without_printed_opening_fails(self):
        # Inferring the opening balance from row 1 would hide this.
        rows = chain_rows()[1:]
        assert_every_check_failed(self, run(140.0, rows, computed=0.0))

    def test_adversarial_dropped_middle_row_fails(self):
        rows = [r for r in chain_rows() if r["invoice_number"] != "PMT"]
        assert_every_check_failed(self, run(140.0, rows, computed=0.0))

    def test_adversarial_last_balance_not_printed_total_fails(self):
        result = gate._check_running_balance(150.0, chain_rows(), tolerance=0.01, previous_balance=None)
        self.assertFalse(result["passed"])

    def test_not_applicable_when_a_row_has_no_balance(self):
        rows = chain_rows()
        rows[2]["amount_due"] = None
        self.assertFalse(gate._check_running_balance(140.0, rows, tolerance=0.01)["applicable"])


# ---------------------------------------------------------------------------
# Fallback 4 -- section_subtotal
# ---------------------------------------------------------------------------

class TestSectionSubtotal(unittest.TestCase):

    GROUP_TOTAL = 168640.83  # Lehigh/VinArt page-header total covering 4 accounts

    def test_single_reconciling_section_passes_against_a_group_total(self):
        rows = [row("601849-5", 180.8, section="Honda"), row("602111-2", 251.31, section="Honda")]
        sections = [{"section": "Honda", "subtotal": 432.11, "invoice_count": 2}]
        result = run(self.GROUP_TOTAL, rows, section_totals=sections)
        self.assertEqual(result["status"], "matches")
        self.assertEqual(result["method"], "section_subtotal")
        self.assertEqual(result["computed"], 432.11)
        self.assertFalse(attempt(result, "section_subtotal")["printed_total_is_sum_of_sections"])

    def test_adversarial_partial_section_from_another_account_fails(self):
        # LV Hyundai file: 8 stray Honda rows on a shared page.
        rows = [row("H1", 100.0, section="Honda"), row("Y1", 300.0, section="Hyundai"),
                row("Y2", 200.0, section="Hyundai")]
        sections = [{"section": "Honda", "subtotal": 21521.17, "invoice_count": 56},
                    {"section": "Hyundai", "subtotal": 500.0, "invoice_count": 2}]
        assert_every_check_failed(self, run(self.GROUP_TOTAL, rows, section_totals=sections))

    def test_adversarial_row_outside_any_section_fails(self):
        rows = [row("Y1", 300.0, section="Hyundai"), row("Y2", 200.0, section="Hyundai"), row("X1", 50.0)]
        sections = [{"section": "Hyundai", "subtotal": 500.0, "invoice_count": 2}]
        assert_every_check_failed(self, run(self.GROUP_TOTAL, rows, section_totals=sections))

    def test_adversarial_invoice_count_mismatch_fails(self):
        rows = [row("Y1", 300.0, section="Hyundai"), row("Y2", 200.0, section="Hyundai")]
        sections = [{"section": "Hyundai", "subtotal": 500.0, "invoice_count": 3}]
        assert_every_check_failed(self, run(self.GROUP_TOTAL, rows, section_totals=sections))

    def test_adversarial_misread_amount_fails(self):
        rows = [row("Y1", 300.0, section="Hyundai"), row("Y2", 208.0, section="Hyundai")]
        sections = [{"section": "Hyundai", "subtotal": 500.0, "invoice_count": 2}]
        assert_every_check_failed(self, run(self.GROUP_TOTAL, rows, section_totals=sections))


# ---------------------------------------------------------------------------
# A wrong extraction must fail every check even when every input exists
# ---------------------------------------------------------------------------

class TestWrongExtractionFailsEverything(unittest.TestCase):

    def test_misread_amount_with_all_fallback_inputs_present(self):
        # Running balance + previous balance + sections all available; one
        # amount misread (Clinton Honda: 174.80 for 74.80).
        rows = [
            row("234911", 174.80, due=1074.80, section="Main"),
            row("234914", 407.23, due=1482.03, section="Main"),
        ]
        sections = [{"section": "Main", "subtotal": 482.03, "invoice_count": 2}]
        result = run(1482.03, rows, previous_balance=1000.0, section_totals=sections)
        assert_every_check_failed(self, result)

    def test_informational_rows_are_ignored_by_every_check(self):
        rows = bishops_rows() + [row(None, None, informational=True)]
        self.assertEqual(run(2126.0, rows)["method"], "open_balance")


if __name__ == "__main__":
    unittest.main()
