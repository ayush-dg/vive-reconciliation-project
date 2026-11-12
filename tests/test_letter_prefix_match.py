"""
tests/test_letter_prefix_match.py

Letter-prefix retry (2026-11-12, src/matching/fabric_matching.py
_letter_prefix_match()): a statement invoice number that differs from the
vendor's NetSuite bill only by a letter prefix on one side matches, at the
exact amount, when exactly one bill qualifies. Cases are the prod dry run of
2026-11-12: the good ones (Rohrich Cadillac, DeNooyer, Astech, Keystone) and
the ones it must skip (CM credit memos, letters that differ on each side).
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.matching import fabric_matching as fm


def bills(**by_tranid):
    """A vendor's bills as the matcher holds them: {tranid_lower: [totals]}."""
    out = fm._Candidates()
    for tranid, totals in by_tranid.items():
        out[tranid.lower()] = list(totals)
    return out


class LetterPrefixMatchTests(unittest.TestCase):

    def test_statement_has_the_store_letters_netsuite_does_not(self):
        # Rohrich Cadillac: CDW821003 on the statement, 821003 in NetSuite.
        self.assertEqual(fm._letter_prefix_match(bills(**{"821003": [456.57]}), "CDW821003", 456.57),
                         ("821003", 456.57))
        self.assertEqual(fm._letter_prefix_match(bills(**{"820438-2": [34.34]}), "CDW820438-2", 34.34),
                         ("820438-2", 34.34))

    def test_netsuite_has_letters_the_statement_does_not(self):
        # DeNooyer: 275700 on the statement, SS#275700 in NetSuite.
        self.assertEqual(fm._letter_prefix_match(bills(**{"ss#275700": [610.03]}), "275700", 610.03),
                         ("ss#275700", 610.03))

    def test_same_letters_other_spacing(self):
        # Astech: SIN12701265 vs "SIN 12701265".
        self.assertEqual(fm._letter_prefix_match(bills(**{"sin 12701265": [101.21]}), "SIN12701265", 101.21),
                         ("sin 12701265", 101.21))

    def test_credit_memo_lines_never_match_a_bill(self):
        # Bowser CM75029 = a full return of bill 75029: same number and amount.
        self.assertIsNone(fm._letter_prefix_match(bills(**{"75029": [1171.28]}), "CM75029", 1171.28))

    def test_letters_that_differ_on_each_side_do_not_match(self):
        # Keystone BANC8215 vs BABC8215; Quirk S1035681 vs CVCS1035681.
        self.assertIsNone(fm._letter_prefix_match(bills(**{"babc8215": [509.95]}), "BANC8215", 509.95))
        self.assertIsNone(fm._letter_prefix_match(bills(**{"cvcs1035681": [384.94]}), "S1035681", 384.94))

    def test_exact_amount_only(self):
        self.assertIsNone(fm._letter_prefix_match(bills(**{"821003": [456.00]}), "CDW821003", 456.57))

    def test_two_qualifying_bills_match_neither(self):
        # 821003 and CDW-821003 both qualify for CDW821003: ambiguous, so neither.
        self.assertIsNone(fm._letter_prefix_match(bills(**{"821003": [456.57], "cdw-821003": [456.57]}),
                                                  "CDW821003", 456.57))
        # A TOW bill is skipped (other letters), so 821003 alone matches.
        self.assertEqual(fm._letter_prefix_match(bills(**{"821003": [456.57], "tow821003": [456.57]}),
                                                 "CDW821003", 456.57), ("821003", 456.57))

    def test_short_numbers_are_left_alone(self):
        self.assertIsNone(fm._letter_prefix_match(bills(**{"123": [10.0]}), "AB123", 10.0))

    def test_the_number_itself_is_not_a_prefix_match(self):
        # The plain lookup already handled an exact number.
        self.assertIsNone(fm._letter_prefix_match(bills(**{"cdw821003": [456.57]}), "CDW821003", 456.57))

    def test_no_amount_no_match(self):
        self.assertIsNone(fm._letter_prefix_match(bills(**{"821003": [456.57]}), "CDW821003", None))


class SwitchAndAppearsPaidTests(unittest.TestCase):

    def test_on_by_default_and_can_be_turned_off(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MATCHING_LETTER_PREFIX", None)
            self.assertTrue(fm._letter_prefix_enabled())
        with mock.patch.dict(os.environ, {"MATCHING_LETTER_PREFIX": "false"}):
            self.assertFalse(fm._letter_prefix_enabled())

    def test_a_paid_bill_matched_this_way_is_appears_to_be_paid(self):
        rule = f"{fm.LETTER_PREFIX_RULE} (CDW821003 → 821003)"
        with mock.patch.dict(os.environ, {"APPEARS_PAID_ENABLED": "true"}):
            self.assertTrue(fm._appears_paid("netsuite_vendorbill", rule, {"status": "B"}))
            self.assertFalse(fm._appears_paid("netsuite_vendorbill", "alternate number (x)", {"status": "B"}))


if __name__ == "__main__":
    unittest.main()
