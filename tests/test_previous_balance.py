"""
tests/test_previous_balance.py

src/validation/previous_balance.py -- the printed previous balance the
gate's statement_equation / running_balance checks rely on. A model value
is only ever accepted when the PDF's text layer corroborates it (or, for a
scan with no text layer, when it came with its printed label). Synthetic
text only, modelled on Oct 1 layouts.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.validation.previous_balance import (
    find_labelled_previous_balances,
    has_text_layer,
    is_balance_forward_label,
    resolve_previous_balance,
)

FILLER = "\n".join(f"09/{d:02d}/26 INV{d:05d} PO{d} 10.00" for d in range(1, 25))


def statement(*lines):
    return "\n".join(lines) + "\n" + FILLER


class TestFindLabelledPreviousBalances(unittest.TestCase):

    def test_reads_the_common_labels(self):
        self.assertEqual(find_labelled_previous_balances("08/31/2026 Balance Forward 707.00"), [707.0])
        self.assertEqual(find_labelled_previous_balances("PREVIOUS BALANCE 3,649.51"), [3649.51])
        self.assertEqual(find_labelled_previous_balances("08/31/2026 PRV Balance 123.88"), [123.88])
        self.assertEqual(find_labelled_previous_balances("Balance BFWD 768.12 Balance BFWD 768.12"), [768.12, 768.12])
        self.assertEqual(find_labelled_previous_balances(". BEG. BALANCE $ 481.97"), [481.97])

    def test_letter_spaced_label_and_parenthesised_negative(self):
        self.assertEqual(find_labelled_previous_balances("PR E V IO U S B A LA N C E 4,778.54"), [4778.54])
        self.assertEqual(find_labelled_previous_balances("7/1/2026 Balance Forward ($188.29)"), [-188.29])

    def test_value_must_follow_the_label_directly(self):
        # Sullivan's column-header line names "PREV BAL" but its amount is
        # the amount due, several labels later.
        line = "PREV BAL PAYMENTS & ADJ NEW CHARGES TOTAL OWING LESS FUTURE DUE PAYMENT DUE AMOUNT DUE 725.00"
        self.assertEqual(find_labelled_previous_balances(line), [])

    def test_finance_charge_boilerplate_is_ignored(self):
        line = ("applied to the unpaid balance after deducting current payments from the previous balance "
                "18.00% ANNUAL PERCENTAGE RATE")
        self.assertEqual(find_labelled_previous_balances(line), [])


class TestResolvePreviousBalance(unittest.TestCase):

    def test_text_layer_value_used_when_model_gave_none(self):
        text = statement("08/31/2026 Balance Forward 707.00")
        self.assertTrue(has_text_layer(text))
        result = resolve_previous_balance(None, None, text)
        self.assertEqual((result["value"], result["source"]), (707.0, "text_layer"))

    def test_model_value_corroborated_by_text_layer(self):
        text = statement("PREVIOUS BALANCE 1,460.00")
        result = resolve_previous_balance(1460.0, "PREVIOUS BALANCE", text)
        self.assertEqual((result["value"], result["source"]), (1460.0, "model+text_layer"))

    def test_adversarial_model_value_not_in_text_layer_is_rejected(self):
        # The text layer prints 707.00; the model says 2,745.59 (e.g. a value
        # that would happen to close the gap) -- never accepted.
        text = statement("08/31/2026 Balance Forward 707.00")
        result = resolve_previous_balance(2745.59, "Previous Balance", text)
        self.assertIsNone(result["value"])
        self.assertTrue(result["source"].startswith("rejected"))

    def test_adversarial_model_value_with_no_labelled_line_is_rejected(self):
        # Town Fair: the balance-forward line prints no label at all.
        text = statement("DATE REFERENCE NUMBER CHARGES CREDITS BALANCE", "07-31-26 887.00")
        result = resolve_previous_balance(887.0, "Balance", text)
        self.assertIsNone(result["value"])

    def test_scan_needs_the_printed_label(self):
        self.assertFalse(has_text_layer("Page 1"))
        accepted = resolve_previous_balance(80.40, "Balance Forward", "Page 1")
        self.assertEqual((accepted["value"], accepted["source"]), (80.4, "model_label_only"))
        rejected = resolve_previous_balance(80.40, None, "Page 1")
        self.assertIsNone(rejected["value"])

    def test_balance_forward_labels(self):
        for label in ("Balance Forward", "BALANCE FWD", "BAL. FWD", "Bal Fwd", "BFWD", "Previous Balance",
                      "PREV BAL", "Prior Balance", "Beg. Balance", "Beginning Balance", "Opening Balance",
                      "Balance Brought Forward", "Previous Statement Balance", "Last Balance", "Balance Forward:"):
            self.assertTrue(is_balance_forward_label(label), label)

    def test_not_balance_forward_labels(self):
        for label in ("08/01/26", "2026-08-01", "08-31", "PREV SERV CHARGES", "Total Due", "Amount Due",
                      "Balance", "Balance Due", "Current", "Statement Date", "80.40", "", None):
            self.assertFalse(is_balance_forward_label(label), label)

    def test_scan_value_under_a_date_label_is_only_a_chain_opening(self):
        # Northeast Coffee: the opening line prints its date, no label.
        result = resolve_previous_balance(80.40, "08/01/26", "Page 1")
        self.assertIsNone(result["value"])
        self.assertEqual(result["source"], "rejected: label is not a balance-forward label")
        self.assertEqual(result["chain_opening"], 80.40)

    def test_scan_value_under_another_field_name_is_not_a_previous_balance(self):
        # Emerson Toyota: "PREV SERV CHARGES 0.00 ... $179.00".
        result = resolve_previous_balance(179.0, "PREV SERV CHARGES", "Page 1")
        self.assertIsNone(result["value"])

    def test_scan_value_without_any_label_is_not_even_a_chain_opening(self):
        result = resolve_previous_balance(80.40, None, "Page 1")
        self.assertIsNone(result["value"])
        self.assertIsNone(result.get("chain_opening"))

    def test_text_layer_rule_is_unchanged_for_a_date_label(self):
        # With a text layer the value must be on a labelled line -- a date
        # label never gives it a second route.
        text = statement("08/01/26 80.40", "08/12/26 2524536 76.29 156.69")
        result = resolve_previous_balance(80.40, "08/01/26", text)
        self.assertIsNone(result["value"])
        self.assertIsNone(result.get("chain_opening"))

    def test_ambiguous_text_layer_gives_nothing(self):
        text = statement("Balance Forward 100.00", "Previous Balance 250.00")
        self.assertIsNone(resolve_previous_balance(None, None, text)["value"])

    def test_nothing_printed_gives_nothing(self):
        self.assertEqual(resolve_previous_balance(None, None, statement("TOTAL 10.00"))["value"], None)


if __name__ == "__main__":
    unittest.main()
