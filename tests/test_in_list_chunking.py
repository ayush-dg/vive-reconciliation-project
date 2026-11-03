"""
tests/test_in_list_chunking.py

SQL Server allows at most 2100 parameters per statement. Dev passed 2100
statement runs on 2026-11-03 and the Exceptions page 500'd: get_exception_runs()
put every statement_id into one document_intake_log IN list. That lookup and
_backfill_statement_periods() are now chunked. No database access: the queries
are faked and every call's parameter count is checked.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web import queries

SQL_SERVER_PARAM_CAP = 2100
RUN_COUNT = 2500


def _fake_intake_lookup(calls):
    """execute_query stand-in: answers a document_intake_log IN lookup with one
    row per requested statement_id, and records each call's parameter count."""
    def fake(sql, params=None):
        params = list(params or [])
        calls.append(len(params))
        if len(params) > SQL_SERVER_PARAM_CAP:
            raise AssertionError(f"{len(params)} parameters sent in one statement")
        return [{"statement_id": sid, "billing_location": None, "statement_period": "2026-10",
                 "shop_or_entity": None, "original_filename": f"{sid}.pdf", "source_file": None}
                for sid in params]
    return fake


class ExceptionRunsChunkingTests(unittest.TestCase):
    def test_more_runs_than_the_parameter_cap_still_load(self):
        runs = [{"statement_id": f"STMT-{i:05d}", "vendor_name": "V", "total_invoice_count": 1,
                 "matched_count": 1, "exception_count": 0, "statement_total": 0,
                 "overall_status": "RECONCILED", "reconciliation_timestamp": "2026-11-03T00:00:00"}
                for i in range(RUN_COUNT)]
        calls = []
        with mock.patch.object(queries, "recon_query", side_effect=[runs, []]), \
             mock.patch.object(queries, "execute_query", side_effect=_fake_intake_lookup(calls)), \
             mock.patch.object(queries, "_get_exceptions_only_vendors", return_value=[]), \
             mock.patch.object(queries, "_attach_aging_summaries"):
            out = queries.get_exception_runs()
        self.assertEqual(len(out), RUN_COUNT)
        self.assertGreater(len(calls), 1)
        self.assertEqual(sum(calls), RUN_COUNT)
        self.assertTrue(all(r["pdf_name"] == f"{r['statement_id']}.pdf" for r in out))


class BackfillPeriodsChunkingTests(unittest.TestCase):
    def test_more_rows_than_the_parameter_cap_get_their_period(self):
        rows = [{"statement_id": f"STMT-{i:05d}", "statement_period": None} for i in range(RUN_COUNT)]
        calls = []
        with mock.patch.object(queries, "execute_query", side_effect=_fake_intake_lookup(calls)):
            out = queries._backfill_statement_periods(rows)
        self.assertGreater(len(calls), 1)
        self.assertTrue(all(r["statement_period"] == "2026-10" for r in out))


if __name__ == "__main__":
    unittest.main()
