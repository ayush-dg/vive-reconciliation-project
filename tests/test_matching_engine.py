"""
tests/test_matching_engine.py

Tests for the deterministic matching engine.
No database, no files — pure unit tests on classify_match().
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.matching.engine import (
    classify_match, amounts_match, score_match_confidence, score_exception_confidence,
)


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

    def test_level2_ro_number_match(self):
        stmt = make_stmt("SIN12200241", 48.75, ro_number="RO-12345")
        erp = [make_erp("DIFFERENT-INV", 48.75, ro_number="RO-12345")]
        result = classify_match(stmt, erp, TOLERANCE_PCT, TOLERANCE_ABS)
        self.assertEqual(result["match_status"], "MATCHED")
        self.assertEqual(result["match_level"], 2)

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


class TestScoreMatchConfidence(unittest.TestCase):
    """Step 7: match_confidence written to gold_matched_invoices. Only
    ("INVOICE", *) and ("RO", *) are reachable via classify_match() today
    -- match_level 1 -> INVOICE, match_level 2 -> RO -- but the table
    covers PO/FUZZY tiers too, for whenever those levels get added."""

    def test_exact_invoice_match_scores_1_00(self):
        self.assertEqual(score_match_confidence(1, 48.75, 48.75), 1.00)

    def test_invoice_match_within_tolerance_scores_0_95(self):
        self.assertEqual(score_match_confidence(1, 100.00, 100.30), 0.95)

    def test_exact_ro_match_scores_0_80(self):
        self.assertEqual(score_match_confidence(2, 48.75, 48.75), 0.80)

    def test_ro_match_within_tolerance_scores_0_75(self):
        self.assertEqual(score_match_confidence(2, 100.00, 100.30), 0.75)

    def test_unknown_match_level_falls_back_to_fuzzy(self):
        self.assertEqual(score_match_confidence(99, 48.75, 48.75), 0.60)

    def test_none_amount_is_treated_as_tolerance_not_exact(self):
        self.assertEqual(score_match_confidence(1, 48.75, None), 0.95)


class TestScoreExceptionConfidence(unittest.TestCase):
    """Step 7: match_confidence written to gold_exceptions -- a distinct
    scale from score_match_confidence(), scoring confidence that the row
    is a genuine exception rather than a matching error."""

    def test_invoice_missing_scores_0_90(self):
        self.assertEqual(score_exception_confidence("Invoice Missing"), 0.90)

    def test_amount_mismatch_scores_0_85(self):
        self.assertEqual(score_exception_confidence("Amount Mismatch"), 0.85)

    def test_extraction_incomplete_scores_0_50(self):
        self.assertEqual(score_exception_confidence("EXTRACTION_INCOMPLETE"), 0.50)

    def test_unrecognized_reason_falls_back_to_0_50(self):
        self.assertEqual(score_exception_confidence("DUPLICATE_RECORD"), 0.50)


class TestRunMatchingWritesMatchConfidence(unittest.TestCase):
    """Integration-level: run_matching() actually persists match_confidence
    on both gold_matched_invoices and gold_exceptions rows."""

    def setUp(self):
        import sqlite3
        from src.lakehouse.migrations import apply_pending_migrations
        from unittest import mock

        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        apply_pending_migrations(self.conn)

        def execute_sql(sql, params=None):
            cur = self.conn.execute(sql, params or [])
            self.conn.commit()
            return cur

        def execute_query(sql, params=None):
            cur = self.conn.execute(sql, params or [])
            return [dict(row) for row in cur.fetchall()]

        patcher1 = mock.patch("src.matching.engine.execute_sql", execute_sql)
        patcher2 = mock.patch("src.matching.engine.execute_query", execute_query)
        patcher1.start()
        patcher2.start()
        self.addCleanup(patcher1.stop)
        self.addCleanup(patcher2.stop)
        self.addCleanup(self.conn.close)
        self.execute_sql = execute_sql
        self.execute_query = execute_query

    def _insert_silver(self, *, record_id, source, invoice_number, amount, ro_number=None):
        self.execute_sql(
            """
            INSERT INTO silver_reconciliation_standard (
                record_id, record_source, statement_id, vendor_id, vendor_name,
                invoice_number, invoice_number_normalized, ro_number,
                outstanding_amount, statement_period, source_file, ingestion_timestamp
            ) VALUES (?, ?, 'STMT-1', 'V1', 'Vendor One', ?, ?, ?, ?, '2026-07',
                      'statement.pdf', '2026-07-24T00:00:00+00:00')
            """,
            [record_id, source, invoice_number, invoice_number, ro_number, amount],
        )

    def test_matched_row_gets_match_confidence(self):
        from src.matching.engine import run_matching

        self._insert_silver(record_id="stmt-1", source="VENDOR_STATEMENT",
                             invoice_number="INV-1", amount=100.00)
        self._insert_silver(record_id="erp-1", source="INTERNAL_ERP",
                             invoice_number="INV-1", amount=100.00)

        run_matching("STMT-1")

        rows = self.execute_query("SELECT * FROM gold_matched_invoices WHERE statement_id = 'STMT-1'")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["match_confidence"], 1.00)

    def test_exception_row_gets_match_confidence(self):
        from src.matching.engine import run_matching

        self._insert_silver(record_id="stmt-1", source="VENDOR_STATEMENT",
                             invoice_number="INV-MISSING", amount=100.00)
        self._insert_silver(record_id="erp-1", source="INTERNAL_ERP",
                             invoice_number="INV-OTHER", amount=100.00)

        run_matching("STMT-1")

        rows = self.execute_query("SELECT * FROM gold_exceptions WHERE statement_id = 'STMT-1'")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["exception_reason"], "Invoice Missing")
        self.assertEqual(rows[0]["match_confidence"], 0.90)


if __name__ == "__main__":
    unittest.main(verbosity=2)
