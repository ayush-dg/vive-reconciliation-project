"""
tests/test_web_queries.py

Tests for web/queries.py's vendor-list-summary functions
(get_vendor_summaries, get_recent_runs, get_all_runs) against a real
in-memory SQLite DB built from migrations/001_initial_schema.sql. No mocks
of the query layer itself -- these exercise real SQL, so a regression in
the query text is actually caught.

Covers the bug where a vendor's gold_reconciliation_summary row says
exception_count=0 / overall_status='RECONCILED' (written once by matching
from Silver-classified exceptions only) even though gold_exceptions has
open EXTRACTION_INCOMPLETE rows for that same statement_id (raised later,
by intake -- see notebooks/01_document_intake.py write_skip_exception()).
The vendor-list summary must reflect the live gold_exceptions state, the
same way the detail page (get_open_exceptions/get_exception_counts) does.
"""

import os
import sqlite3
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web import queries

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "migrations", "001_initial_schema.sql")


def _make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    return conn


def _wire_fake_backend(conn):
    """Returns (execute_sql, execute_query) bound to `conn`, matching the
    real src.lakehouse.connection signatures/return shapes closely enough
    for queries.py's call sites."""
    def execute_sql(sql, params=None):
        cur = conn.execute(sql, params or [])
        conn.commit()
        return cur

    def execute_query(sql, params=None):
        cur = conn.execute(sql, params or [])
        return [dict(row) for row in cur.fetchall()]

    return execute_sql, execute_query


def _insert_summary(execute_sql, *, statement_id, vendor_name, exception_count, overall_status,
                     reconciliation_timestamp):
    execute_sql(
        """
        INSERT INTO gold_reconciliation_summary (
            summary_id, vendor_id, vendor_name, statement_period, statement_id,
            statement_total, erp_total, difference, total_invoice_count,
            matched_count, exception_count, match_percentage, overall_status,
            reconciliation_timestamp, erp_version
        ) VALUES (?, ?, ?, '2026-05', ?, 1000.0, 1000.0, 0.0, 10, 10, ?, 100.0, ?, ?, 1)
        """,
        [f"SUM-{statement_id}", vendor_name.upper(), vendor_name, statement_id,
         exception_count, overall_status, reconciliation_timestamp],
    )


def _insert_open_exception(execute_sql, *, statement_id, exception_reason, exception_id):
    execute_sql(
        """
        INSERT INTO gold_exceptions (
            exception_id, vendor_id, invoice_number, statement_amount, erp_amount,
            match_status, exception_reason, exception_status, statement_id, date_raised
        ) VALUES (?, 'VENDOR_X', NULL, NULL, NULL, 'EXCEPTION', ?, 'OPEN', ?, '2026-05-01T00:00:00+00:00')
        """,
        [exception_id, exception_reason, statement_id],
    )


class TestVendorSummaryReflectsLiveExtractionIncompleteCount(unittest.TestCase):
    """The exact reported bug: matching found 0 real exceptions (summary
    says RECONCILED), but intake later raised 2 open EXTRACTION_INCOMPLETE
    rows for that same statement -- the vendor list must show 2, not 0."""

    def setUp(self):
        self.conn = _make_db()
        execute_sql, execute_query = _wire_fake_backend(self.conn)
        patcher1 = mock.patch("web.queries.execute_sql", execute_sql)
        patcher2 = mock.patch("web.queries.execute_query", execute_query)
        patcher1.start()
        patcher2.start()
        self.addCleanup(patcher1.stop)
        self.addCleanup(patcher2.stop)
        self.addCleanup(self.conn.close)

        _insert_summary(
            execute_sql, statement_id="STMT-1", vendor_name="Acme Parts",
            exception_count=0, overall_status="RECONCILED",
            reconciliation_timestamp="2026-05-01T00:00:00+00:00",
        )
        _insert_open_exception(execute_sql, statement_id="STMT-1",
                                exception_reason="EXTRACTION_INCOMPLETE", exception_id="EXC-1")
        _insert_open_exception(execute_sql, statement_id="STMT-1",
                                exception_reason="EXTRACTION_INCOMPLETE", exception_id="EXC-2")

    def test_get_vendor_summaries_shows_live_count_not_stale_zero(self):
        vendors = queries.get_vendor_summaries()
        self.assertEqual(len(vendors), 1)
        self.assertEqual(vendors[0]["exception_count"], 2)
        self.assertIn("extraction incomplete", vendors[0]["reason_breakdown"])
        self.assertEqual(vendors[0]["reason_breakdown"]["extraction incomplete"], 2)

    def test_get_recent_runs_shows_live_count_and_non_reconciled_status(self):
        runs = queries.get_recent_runs()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["exception_count"], 2)
        self.assertNotEqual(runs[0]["overall_status"], "RECONCILED")

    def test_get_all_runs_shows_live_count_and_non_reconciled_status(self):
        runs = queries.get_all_runs()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["exception_count"], 2)
        self.assertNotEqual(runs[0]["overall_status"], "RECONCILED")


class TestVendorSummaryStillReconciledWhenTrulyClean(unittest.TestCase):
    """A vendor with genuinely zero open exceptions of any kind must still
    show as reconciled -- the fix must not flip every vendor to "has
    exceptions" regardless of actual state."""

    def setUp(self):
        self.conn = _make_db()
        execute_sql, execute_query = _wire_fake_backend(self.conn)
        patcher1 = mock.patch("web.queries.execute_sql", execute_sql)
        patcher2 = mock.patch("web.queries.execute_query", execute_query)
        patcher1.start()
        patcher2.start()
        self.addCleanup(patcher1.stop)
        self.addCleanup(patcher2.stop)
        self.addCleanup(self.conn.close)

        _insert_summary(
            execute_sql, statement_id="STMT-2", vendor_name="Clean Vendor",
            exception_count=0, overall_status="RECONCILED",
            reconciliation_timestamp="2026-05-01T00:00:00+00:00",
        )

    def test_vendor_summaries_reconciled_stays_reconciled(self):
        vendors = queries.get_vendor_summaries()
        self.assertEqual(vendors[0]["exception_count"], 0)
        self.assertEqual(vendors[0]["reason_breakdown"], {})

    def test_recent_runs_reconciled_stays_reconciled(self):
        runs = queries.get_recent_runs()
        self.assertEqual(runs[0]["exception_count"], 0)
        self.assertEqual(runs[0]["overall_status"], "RECONCILED")


class TestVendorSummaryExcludesResolvedExceptions(unittest.TestCase):
    """A resolved exception must not inflate the live count -- only
    exception_status = 'OPEN' rows count, matching the detail page."""

    def setUp(self):
        self.conn = _make_db()
        execute_sql, execute_query = _wire_fake_backend(self.conn)
        patcher1 = mock.patch("web.queries.execute_sql", execute_sql)
        patcher2 = mock.patch("web.queries.execute_query", execute_query)
        patcher1.start()
        patcher2.start()
        self.addCleanup(patcher1.stop)
        self.addCleanup(patcher2.stop)
        self.addCleanup(self.conn.close)

        _insert_summary(
            execute_sql, statement_id="STMT-3", vendor_name="Partly Resolved",
            exception_count=2, overall_status="MINOR_EXCEPTIONS",
            reconciliation_timestamp="2026-05-01T00:00:00+00:00",
        )
        _insert_open_exception(execute_sql, statement_id="STMT-3",
                                exception_reason="Invoice Missing", exception_id="EXC-3")
        execute_sql(
            """
            INSERT INTO gold_exceptions (
                exception_id, vendor_id, invoice_number, statement_amount, erp_amount,
                match_status, exception_reason, exception_status, statement_id, date_raised
            ) VALUES ('EXC-4', 'VENDOR_X', 'INV-1', 100.0, NULL, 'EXCEPTION', 'Invoice Missing',
                      'RESOLVED', 'STMT-3', '2026-05-01T00:00:00+00:00')
            """
        )

    def test_resolved_row_not_counted(self):
        vendors = queries.get_vendor_summaries()
        self.assertEqual(vendors[0]["exception_count"], 1)


class TestOpenExceptionsCountScopedToLatestRunPerVendor(unittest.TestCase):
    """Reproduces the reported bug: the same vendor/period statement was
    run 3 times while debugging a cache/connectivity issue, producing 3
    statement_ids, each with its own gold_reconciliation_summary row and
    its own OPEN gold_exceptions rows (superseded runs are never cleaned
    up -- matching's DELETE FROM gold_exceptions is scoped to the
    statement_id it's currently processing, not older ones). Only the
    latest statement_id's exceptions should count toward the KPI, exactly
    like get_recent_runs()/get_vendor_summaries() already scope to it."""

    def setUp(self):
        self.conn = _make_db()
        execute_sql, execute_query = _wire_fake_backend(self.conn)
        patcher1 = mock.patch("web.queries.execute_sql", execute_sql)
        patcher2 = mock.patch("web.queries.execute_query", execute_query)
        patcher1.start()
        patcher2.start()
        self.addCleanup(patcher1.stop)
        self.addCleanup(patcher2.stop)
        self.addCleanup(self.conn.close)
        self.execute_sql = execute_sql
        self.execute_query = execute_query

        # 3 runs of the same vendor/period (earliest -> latest), mirroring
        # the reported STMT-<earlier>, STMT-833A23C0, STMT-7A290260 sequence.
        _insert_summary(
            execute_sql, statement_id="STMT-EARLIEST", vendor_name="Enterprise Reconciliation Register",
            exception_count=2, overall_status="MINOR_EXCEPTIONS",
            reconciliation_timestamp="2026-05-01T00:00:00+00:00",
        )
        _insert_summary(
            execute_sql, statement_id="STMT-833A23C0", vendor_name="Enterprise Reconciliation Register",
            exception_count=3, overall_status="MINOR_EXCEPTIONS",
            reconciliation_timestamp="2026-05-01T01:00:00+00:00",
        )
        _insert_summary(
            execute_sql, statement_id="STMT-7A290260", vendor_name="Enterprise Reconciliation Register",
            exception_count=2, overall_status="MINOR_EXCEPTIONS",
            reconciliation_timestamp="2026-05-01T02:00:00+00:00",  # latest
        )
        # Superseded runs left OPEN exceptions behind (2 + 3 = 5 stray rows).
        for i in range(2):
            _insert_open_exception(execute_sql, statement_id="STMT-EARLIEST",
                                    exception_reason="Invoice Missing", exception_id=f"OLD1-{i}")
        for i in range(3):
            _insert_open_exception(execute_sql, statement_id="STMT-833A23C0",
                                    exception_reason="Invoice Missing", exception_id=f"OLD2-{i}")
        # The latest run's own 2 open exceptions -- the only ones that
        # should count.
        for i in range(2):
            _insert_open_exception(execute_sql, statement_id="STMT-7A290260",
                                    exception_reason="Invoice Missing", exception_id=f"LATEST-{i}")

    def test_confirms_root_cause_stray_open_exceptions_exist_on_superseded_runs(self):
        """Diagnostic check (per the bug report) -- confirms superseded
        runs really do still have OPEN rows sitting in gold_exceptions,
        grouped by statement_id."""
        rows = self.execute_query(
            "SELECT statement_id, COUNT(*) AS c FROM gold_exceptions "
            "WHERE exception_status = 'OPEN' GROUP BY statement_id ORDER BY statement_id"
        )
        counts = {r["statement_id"]: r["c"] for r in rows}
        self.assertEqual(counts, {"STMT-EARLIEST": 2, "STMT-833A23C0": 3, "STMT-7A290260": 2})
        # An unscoped flat COUNT(*) — the pre-fix behavior — would total 7,
        # not the 2 that belong to the latest run.
        self.assertEqual(sum(counts.values()), 7)

    def test_open_exceptions_count_matches_latest_run_only(self):
        self.assertEqual(queries.get_open_exceptions_count(), 2)

    def test_kpi_open_exceptions_agrees_with_recent_runs_table_sum(self):
        """The actual reported symptom: the KPI card and the sum of the
        table's per-row exception_count must agree."""
        kpis = queries.get_kpis()
        runs = queries.get_recent_runs()
        table_sum = sum(r["exception_count"] for r in runs)
        self.assertEqual(kpis["open_exceptions"], table_sum)
        self.assertEqual(kpis["open_exceptions"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
