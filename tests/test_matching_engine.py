"""
tests/test_matching_engine.py

Tests for the deterministic matching engine.
No database, no files — pure unit tests on classify_match().
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.matching.engine import classify_match, amounts_match


TOLERANCE_PCT = 0.01
TOLERANCE_ABS = 0.50


def make_stmt(invoice_number, amount, ro_number=None):
    return {
        "record_id": f"stmt-{invoice_number}",
        "invoice_number": invoice_number,
        "invoice_number_normalized": invoice_number,
        "outstanding_amount": amount,
        "ro_number": ro_number,
    }


def make_erp(invoice_number, amount, ro_number=None):
    return {
        "record_id": f"erp-{invoice_number}",
        "invoice_number": invoice_number,
        "invoice_number_normalized": invoice_number,
        "outstanding_amount": amount,
        "ro_number": ro_number,
    }


class TestAmountsMatch(unittest.TestCase):

    def test_exact_match(self):
        self.assertTrue(amounts_match(48.75, 48.75, TOLERANCE_PCT, TOLERANCE_ABS))

    def test_within_absolute_tolerance(self):
        self.assertTrue(amounts_match(100.00, 100.30, TOLERANCE_PCT, TOLERANCE_ABS))

    def test_outside_tolerance(self):
        self.assertFalse(amounts_match(48.75, 40.00, TOLERANCE_PCT, TOLERANCE_ABS))

    def test_none_amounts(self):
        self.assertFalse(amounts_match(None, 48.75, TOLERANCE_PCT, TOLERANCE_ABS))
        self.assertFalse(amounts_match(48.75, None, TOLERANCE_PCT, TOLERANCE_ABS))


class TestClassifyMatch(unittest.TestCase):

    def test_level1_exact_invoice_and_amount_match(self):
        stmt = make_stmt("SIN12200241", 48.75, "RO-001")
        erp = [make_erp("SIN12200241", 48.75, "RO-001")]
        result = classify_match(stmt, erp, TOLERANCE_PCT, TOLERANCE_ABS)
        self.assertEqual(result["match_status"], "MATCHED")
        self.assertEqual(result["match_level"], 1)
        self.assertIsNone(result["exception_reason"])

    def test_invoice_matches_but_amount_mismatch(self):
        stmt = make_stmt("SIN12200241", 48.75)
        erp = [make_erp("SIN12200241", 40.00)]
        result = classify_match(stmt, erp, TOLERANCE_PCT, TOLERANCE_ABS)
        self.assertEqual(result["match_status"], "EXCEPTION")
        self.assertEqual(result["exception_reason"], "Amount Mismatch")
        self.assertIsNone(result["matched_erp"])

    def test_invoice_missing_from_erp(self):
        stmt = make_stmt("SIN12200241", 48.75)
        erp = [make_erp("SIN99999999", 48.75)]  # completely different invoice
        result = classify_match(stmt, erp, TOLERANCE_PCT, TOLERANCE_ABS)
        self.assertEqual(result["match_status"], "EXCEPTION")
        self.assertEqual(result["exception_reason"], "Invoice Missing")

    def test_level3_ro_number_match(self):
        stmt = make_stmt("SIN12200241", 48.75, ro_number="RO-12345")
        erp = [make_erp("DIFFERENT-INV", 48.75, ro_number="RO-12345")]
        result = classify_match(stmt, erp, TOLERANCE_PCT, TOLERANCE_ABS)
        self.assertEqual(result["match_status"], "MATCHED")
        self.assertEqual(result["match_level"], 3)

    def test_empty_erp_candidates_is_invoice_missing(self):
        stmt = make_stmt("SIN12200241", 48.75)
        result = classify_match(stmt, [], TOLERANCE_PCT, TOLERANCE_ABS)
        self.assertEqual(result["match_status"], "EXCEPTION")
        self.assertEqual(result["exception_reason"], "Invoice Missing")

    def test_amount_within_tolerance_still_matches(self):
        # $0.30 difference on a $100 invoice — within $0.50 absolute tolerance
        stmt = make_stmt("INV-001", 100.00)
        erp = [make_erp("INV-001", 100.30)]
        result = classify_match(stmt, erp, TOLERANCE_PCT, TOLERANCE_ABS)
        self.assertEqual(result["match_status"], "MATCHED")
        self.assertEqual(result["match_level"], 1)

    def test_picks_best_erp_candidate_with_matching_amount(self):
        """When multiple ERP rows share an invoice number, prefer the one with matching amount."""
        stmt = make_stmt("SIN12200241", 48.75)
        erp = [
            make_erp("SIN12200241", 99.99),   # wrong amount
            make_erp("SIN12200241", 48.75),   # correct amount
        ]
        # Give second ERP a different record_id
        erp[1]["record_id"] = "erp-SIN12200241-correct"
        result = classify_match(stmt, erp, TOLERANCE_PCT, TOLERANCE_ABS)
        self.assertEqual(result["match_status"], "MATCHED")
        self.assertEqual(result["matched_erp"]["record_id"], "erp-SIN12200241-correct")


if __name__ == "__main__":
    unittest.main(verbosity=2)
