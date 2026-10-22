"""
tests/test_backfill_recon.py

scripts/backfill_recon.py's plan_statement(): recon rows for a statement
matched before the recon table existed come from a dry run of matching, but
only when that dry run reproduces the STORED results; exception rows are
linked to the stored exception ids and decisions already made are applied.
Everything here is faked -- nothing touches Fabric or Azure SQL.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import backfill_recon as bf
from src.lakehouse import recon_table


def _exc_row(exception_id, invoice, amount, reason="Not Found in NetSuite"):
    # silver.recon_exceptions column order (fabric_matching._EXCEPTION_COLUMNS)
    return [exception_id, "V", None, invoice, invoice, None, amount, None, "EXCEPTION", reason, "OPEN",
            "STMT-1", "2026-10-13", None]


def _match_row(invoice, amount):
    return ["m", "V", None, invoice, invoice, None, amount, amount, 1, "MATCHED", "STMT-1", "2026-10-13"]


class _FakeMatching:
    def __init__(self, matches, exceptions, rows):
        self.result = {"vendor_id": "V", "recon_rows": rows,
                       "would_write": {"silver.recon_matched_invoices": matches,
                                       "silver.recon_exceptions": exceptions}}

    def run_fabric_matching(self, statement_id, dry_run=False, keep_run_time=False):
        assert dry_run and keep_run_time
        return self.result


class _FakeQueries:
    def __init__(self, stored_matches, stored_exceptions, decisions=()):
        self.stored_matches, self.stored_exceptions, self.decisions = stored_matches, stored_exceptions, list(decisions)

    def recon_query(self, sql, params):
        return self.stored_matches if "recon_matched_invoices" in sql else self.stored_exceptions

    def execute_query(self, sql, params):
        return self.decisions


class _FakeRecon:
    SOURCE_AUTO = recon_table.SOURCE_AUTO
    STATUS_BY_DISPOSITION = recon_table.STATUS_BY_DISPOSITION
    STATUS_MATCHED = recon_table.STATUS_MATCHED
    STATUS_NOT_RECONCILED = recon_table.STATUS_NOT_RECONCILED

    line_amount = staticmethod(recon_table.line_amount)
    status_for_reason = staticmethod(recon_table.status_for_reason)
    build_auto_rows = staticmethod(recon_table.build_auto_rows)

    def __init__(self, existing=()):
        self.existing = list(existing)

    def rows_for_statement(self, statement_id):
        return self.existing


def _rows():
    return [
        {"line_number": 1, "invoice_number": "A1", "status": recon_table.STATUS_MATCHED, "exception_id": None},
        {"line_number": 2, "invoice_number": "B2", "status": "Not found in NetSuite", "exception_id": "dry-1"},
        {"line_number": 3, "invoice_number": "A1", "status": recon_table.STATUS_NOT_RECONCILED,
         "exception_id": None, "note": "payment/reversal of invoice A1's charge"},
    ]


class PlanStatementTests(unittest.TestCase):
    def _plan(self, stored_exc_status="OPEN", decisions=(), stored_matches=None, existing=()):
        fm = _FakeMatching([_match_row("A1", 100.0)], [_exc_row("dry-1", "B2", 50.0)], _rows())
        queries = _FakeQueries(
            stored_matches if stored_matches is not None else [{"invoice_number": "A1", "statement_amount": 100.0}],
            [{"exception_id": "real-9", "invoice_number": "B2", "exception_reason": "Not Found in NetSuite",
              "statement_amount": 50.0, "exception_status": stored_exc_status}],
            decisions)
        return bf.plan_statement(fm, _FakeRecon(existing), queries, "STMT-1")

    def test_rows_are_linked_to_the_stored_exception(self):
        rows, report = self._plan()
        self.assertEqual(rows[1]["exception_id"], "real-9")
        self.assertEqual((report["action"], report["rows"], report["matched"], report["exceptions"], report["set_aside"]),
                         ("backfill", 3, 1, 1, 1))

    def test_an_accepted_exception_is_backfilled_as_accepted(self):
        rows, report = self._plan("RESOLVED", [
            {"exception_id": "real-9", "disposition_status": "PENDING", "disposed_by": "a", "disposed_at": "1",
             "disposition_notes": None},
            {"exception_id": "real-9", "disposition_status": "ACCEPTED", "disposed_by": "admin@vive.com",
             "disposed_at": "2026-10-20T14:19:27", "disposition_notes": "ok"}])
        self.assertEqual((rows[1]["status"], rows[1]["matched_by"], rows[1]["note"]),
                         (recon_table.STATUS_ACCEPTED, "admin@vive.com", "ok"))
        self.assertEqual(report["resolved"], 1)

    def test_an_undone_decision_leaves_the_exception_open(self):
        rows, _ = self._plan("OPEN", [{"exception_id": "real-9", "disposition_status": "ACCEPTED",
                                       "disposed_by": "a", "disposed_at": "1", "disposition_notes": None}])
        self.assertEqual(rows[1]["status"], "Not found in NetSuite")

    def test_a_statement_whose_stored_results_differ_is_skipped(self):
        rows, report = self._plan(stored_matches=[{"invoice_number": "A1", "statement_amount": 99.0}])
        self.assertIsNone(rows)
        self.assertIn("stored results differ", report["detail"])

    def test_a_statement_that_already_has_recon_rows_is_skipped(self):
        rows, report = self._plan(existing=[{"source": recon_table.SOURCE_AUTO}])
        self.assertIsNone(rows)
        self.assertEqual(report["detail"], "already has recon rows")

    def test_only_manual_rows_do_not_count_as_already_backfilled(self):
        rows, _ = self._plan(existing=[{"source": recon_table.SOURCE_MANUAL}])
        self.assertIsNotNone(rows)


class FallbackTests(unittest.TestCase):
    """Stored results matching no longer reproduces (NetSuite changed since):
    --fallback pairs every line with its stored result by invoice and amount."""

    class _FM(_FakeMatching):
        lines = [
            {"statement_line_id": "L1", "line_number": 1, "invoice_number": "A1", "charge_amount": 100.0},
            {"statement_line_id": "L2", "line_number": 2, "invoice_number": "B2", "charge_amount": 50.0},
            {"statement_line_id": "L3", "line_number": 3, "invoice_number": "A1", "charge_amount": -100.0},
            {"statement_line_id": "L4", "line_number": 4, "invoice_number": "C3", "charge_amount": 7.0},
        ]

        def get_warehouse_connection(self):
            class _C:
                def cursor(self):
                    return None
            return _C()

        def _fetch_statement(self, cur, sid):
            return {"vendor_id": "V", "vendor_name_raw": "Vendor"}

        def _fetch_lines(self, cur, sid):
            return [dict(l) for l in self.lines]

        def _previous_run_time(self, cur, sid):
            return "2026-10-14T15:02:21"

    def _plan(self, fallback):
        fm = self._FM([_match_row("A1", 100.0), _match_row("Z9", 1.0)], [], [])  # matching today differs
        queries = _FakeQueries(
            [{"invoice_number": "A1", "statement_amount": 100.0, "erp_amount": 100.0}],
            [{"exception_id": "real-9", "invoice_number": "B2", "exception_reason": "Not Found in NetSuite",
              "statement_amount": 50.0, "erp_amount": None, "exception_status": "OPEN"}])
        return bf.plan_statement(fm, _FakeRecon(), queries, "STMT-1", fallback=fallback)

    def test_an_invoice_matched_as_a_whole_still_shares_its_result(self):
        # No line carries the amount of the stored result (a per-invoice total):
        # every line of that invoice shares it.
        fm = self._FM([_match_row("Z9", 1.0)], [], [])
        fm.lines = [{"statement_line_id": "L1", "line_number": 1, "invoice_number": "A1", "charge_amount": 60.0},
                    {"statement_line_id": "L2", "line_number": 2, "invoice_number": "A1", "charge_amount": 40.0}]
        queries = _FakeQueries([{"invoice_number": "A1", "statement_amount": 100.0, "erp_amount": 100.0}], [])
        rows, _ = bf.plan_statement(fm, _FakeRecon(), queries, "STMT-1", fallback=True)
        self.assertEqual([r["status"] for r in rows], [recon_table.STATUS_MATCHED] * 2)

    def test_without_fallback_it_is_skipped(self):
        rows, report = self._plan(False)
        self.assertIsNone(rows)
        self.assertIn("--fallback", report["detail"])

    def test_with_fallback_each_line_gets_its_stored_result(self):
        rows, report = self._plan(True)
        by_line = {r["line_number"]: r for r in rows}
        self.assertEqual(by_line[1]["status"], recon_table.STATUS_MATCHED)
        self.assertEqual((by_line[2]["status"], by_line[2]["exception_id"]), ("Not found in NetSuite", "real-9"))
        # Line 3 is another line of A1, whose match already sits on line 1 -> set aside.
        self.assertEqual(by_line[3]["status"], recon_table.STATUS_NOT_RECONCILED)
        self.assertIn("result is on line 1", by_line[3]["note"])
        self.assertEqual(by_line[4]["status"], recon_table.STATUS_NOT_RECONCILED)
        self.assertEqual(by_line[4]["note"], bf.FALLBACK_NOTE)
        self.assertEqual(by_line[1]["created_at"], "2026-10-14T15:02:21")
        self.assertTrue(report["detail"].startswith("fallback"))
        self.assertEqual(report["exceptions"], 1)


if __name__ == "__main__":
    unittest.main()
