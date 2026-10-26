"""
tests/test_printed_total_prose.py

src/validation/printed_total.py (2026-10-25): a percentage or a prose /
footer line is never the statement's printed total. The CDK eF320 footer
("FINANCE CHARGES will apply if the new balance is unpaid ... a periodic rate
of 1.50% per month") matched the "new balance" label and supplied 1.50 as the
printed total of all three Faulkner statements on dev.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.validation import printed_total as pt

FOOTER = ('FINANCE CHARGES will apply if the new balance is unpaid one month from the closing date of statement. '
          'The "FINANCE CHARGES" are computed a periodic rate of 1.50% per month which is an')
EF320_PAGE = "\n".join([
    "Customer # 1001",
    "eF320-Accounts Receivable Statement",
    "DATE DOCUMENT/TRANSACTION PURCHASES ($) PAYMENTS & CREDITS ($) BALANCE DUE ($)",
    "COMPANY ID JOURNAL ID REFERENCE # PREVIOUS BALANCE",
    "08-28-2026 32 32 400001 23.93",
    "CURRENT ($) OVER 30 DAYS ($) OVER 60 DAYS ($) OVER 90 DAYS ($) OVER 120 DAYS ($) BALANCE DUE ($)",
    "0.00 23.93 0.00 0.00 0.00 23.93",
    FOOTER,
    "ANNUAL PERCENTAGE RATE of 18.00% applied to the unpaid balance after deducting current payments and/or "
    "credits appearing on this statement from the previous balance.",
])


class TestPercentageAndProseAreNeverTheTotal(unittest.TestCase):
    def test_finance_charge_footer_is_not_a_printed_total(self):
        self.assertIsNone(pt.find_printed_total(FOOTER))
        self.assertEqual(pt.labelled_amounts(FOOTER), set())

    def test_ef320_page_text_yields_no_printed_total(self):
        # The BALANCE DUE figure sits on the aging line BELOW its label, so the
        # text rules find no total at all -- never 1.50.
        self.assertIsNone(pt.find_printed_total(EF320_PAGE))
        self.assertEqual(pt.labelled_amounts(EF320_PAGE), set())

    def test_percentage_on_a_total_line_is_not_an_amount(self):
        self.assertEqual(pt.find_printed_total("Balance due 250.00 (1.50% finance charge)"), 250.0)
        self.assertEqual(pt.find_printed_total("Amount due 99.10 incl. 2.00 % fee"), 99.1)

    def test_prose_line_with_an_amount_is_not_a_total_line(self):
        sentence = ("If your new balance of 120.00 is not paid within thirty days a late fee will be added "
                    "to the account")
        self.assertIsNone(pt.find_printed_total(sentence))
        self.assertEqual(pt.find_printed_total(sentence + "\nTotal due 120.00"), 120.0)

    def test_real_total_lines_still_count(self):
        # Letter-spaced labels are single lowercase letters, not prose words.
        self.assertEqual(pt.find_printed_total("STORE 300081624 T o t a l D u e ---> 412.37"), 412.37)
        self.assertEqual(pt.find_printed_total("Total due 3425.00\nBalance due 3425.00"), 3425.0)
        self.assertEqual(pt.find_printed_total("STATUS 450.00 63,380.20 | PLEASE PAY THIS AMOUNT 63,830.20"), 63830.20)
        self.assertEqual(pt.find_printed_total("Please pay this amount upon receipt 75.00"), 75.0)

    def test_full_match_safety_check_still_sees_every_labelled_amount(self):
        # full_match_no_total.py reads _is_total_line / _line_amounts directly:
        # unchanged, so its "no total contradicts the rows" check stays as strict.
        self.assertTrue(pt._is_total_line(FOOTER))
        self.assertEqual(pt._line_amounts(FOOTER), [1.5])


if __name__ == "__main__":
    unittest.main()
