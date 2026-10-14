"""
tests/test_bennetts_alternate_tranid.py

Bennett's Auto Recovery prints a bare Call # (36498); NetSuite holds it
behind the 2-digit year of the line's date (26-36498). The alternate is
built from the line date, so a call from 2025 tries 25-, not 26-.
"""

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.matching.fabric_matching import _alternate_tranids


class TestBennettsAlternateTranid(unittest.TestCase):

    def test_year_prefix_from_line_date(self):
        self.assertEqual(_alternate_tranids("BENNETTS_AUTO_RECOVERY", "36498", date(2026, 9, 2)), ["26-36498"])
        self.assertEqual(_alternate_tranids("BENNETTS_AUTO_RECOVERY", "32115", "2025-09-09"), ["25-32115"])

    def test_no_date_or_non_numeric_call_adds_nothing(self):
        self.assertEqual(_alternate_tranids("BENNETTS_AUTO_RECOVERY", "36498"), [])
        self.assertEqual(_alternate_tranids("BENNETTS_AUTO_RECOVERY", "26-36498", date(2026, 9, 2)), [])

    def test_other_vendors_unaffected(self):
        self.assertEqual(_alternate_tranids("SOME_VENDOR", "36498", date(2026, 9, 2)), [])
        self.assertEqual(_alternate_tranids("SULLIVAN_TIRE", "0119-0053554", date(2026, 8, 5)), ["53554"])


if __name__ == "__main__":
    unittest.main()
