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
from src.lakehouse.migrations import apply_pending_migrations

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


def _make_jobs_db():
    """In-memory SQLite DB with the full migration history applied (needed
    for the jobs table + its claim_token column, added in
    migrations/005_add_jobs_table.sql and 006_add_job_claim_token.sql)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    return conn


class TestClaimNextPendingJobIsAtomic(unittest.TestCase):
    """Covers the bug where uploading the same PDF twice re-ran the full
    (~5 minute) AI extraction both times instead of cache-hitting on the
    second upload. Root cause: the worker claimed jobs via a plain SELECT
    then a separate UPDATE, so more than one worker process (e.g. a
    leftover dev server still running from an earlier session) could pick
    up two different jobs for the same just-uploaded PDF and run them
    concurrently -- each starting its own extraction before the other had
    committed its extraction_cache row. claim_next_pending_job() now does
    the claim as one atomic UPDATE that also refuses to claim anything
    while another job is already PROCESSING, so jobs for the same file are
    always fully serialized -- the second one's cache check can only run
    after the first one's cache write has committed."""

    def setUp(self):
        self.conn = _make_jobs_db()
        self.execute_sql, self.execute_query = _wire_fake_backend(self.conn)
        patcher1 = mock.patch("web.queries.execute_sql", self.execute_sql)
        patcher2 = mock.patch("web.queries.execute_query", self.execute_query)
        patcher1.start()
        patcher2.start()
        self.addCleanup(patcher1.stop)
        self.addCleanup(patcher2.stop)
        self.addCleanup(self.conn.close)

        # Two uploads of the identical PDF, queued back to back -- exactly
        # what the web upload form does for two clicks in the same session.
        queries.create_job(job_id="job-1", pdf_filename="KSI_Noakers_053126.pdf",
                            pdf_path="sample_data/KSI_Noakers_053126.pdf", submitted_by="tester")
        queries.create_job(job_id="job-2", pdf_filename="KSI_Noakers_053126.pdf",
                            pdf_path="sample_data/KSI_Noakers_053126.pdf", submitted_by="tester")

    def test_second_claim_is_refused_while_first_job_still_processing(self):
        first = queries.claim_next_pending_job()
        self.assertEqual(first["job_id"], "job-1")
        self.assertEqual(first["status"], "PROCESSING")

        # A second worker polling right now (e.g. a duplicate server
        # instance) must NOT also pick up job-2 while job-1 is in flight --
        # that's what let both jobs run their extraction concurrently.
        second = queries.claim_next_pending_job()
        self.assertIsNone(second)

    def test_next_job_claimable_only_after_first_completes(self):
        first = queries.claim_next_pending_job()
        self.assertEqual(first["job_id"], "job-1")

        queries.update_job_status("job-1", status="COMPLETED",
                                   completed_at="2026-07-22T00:05:00+00:00",
                                   statement_id="STMT-AAA111")

        second = queries.claim_next_pending_job()
        self.assertIsNotNone(second)
        self.assertEqual(second["job_id"], "job-2")
        self.assertEqual(second["status"], "PROCESSING")

    def test_claim_never_returns_the_same_job_twice(self):
        first = queries.claim_next_pending_job()
        self.assertEqual(first["job_id"], "job-1")

        # Simulate two more racing polls before job-1 finishes -- neither
        # should claim job-1 again or jump ahead to job-2.
        self.assertIsNone(queries.claim_next_pending_job())
        self.assertIsNone(queries.claim_next_pending_job())


class TestClaimNextPendingJobAllowsDifferentFilenamesConcurrently(unittest.TestCase):
    """ENH: parallel worker pool (2026-07-24, docs/INVARIANTS.md's amended
    INV-05) -- claim_next_pending_job() no longer refuses to claim
    anything while any job is PROCESSING; it only holds back jobs that
    share a pdf_filename with something already in flight."""

    def setUp(self):
        self.conn = _make_jobs_db()
        self.execute_sql, self.execute_query = _wire_fake_backend(self.conn)
        patcher1 = mock.patch("web.queries.execute_sql", self.execute_sql)
        patcher2 = mock.patch("web.queries.execute_query", self.execute_query)
        patcher1.start()
        patcher2.start()
        self.addCleanup(patcher1.stop)
        self.addCleanup(patcher2.stop)
        self.addCleanup(self.conn.close)

    def test_different_filenames_can_both_be_processing_at_once(self):
        queries.create_job(job_id="job-a", pdf_filename="vendor_a.pdf",
                            pdf_path="sample_data/vendor_a.pdf", submitted_by="tester")
        queries.create_job(job_id="job-b", pdf_filename="vendor_b.pdf",
                            pdf_path="sample_data/vendor_b.pdf", submitted_by="tester")

        first = queries.claim_next_pending_job()
        second = queries.claim_next_pending_job()

        self.assertEqual(first["job_id"], "job-a")
        self.assertEqual(first["status"], "PROCESSING")
        self.assertEqual(second["job_id"], "job-b")
        self.assertEqual(second["status"], "PROCESSING")

    def test_same_filename_still_serialized_even_with_other_jobs_interleaved(self):
        queries.create_job(job_id="job-a1", pdf_filename="vendor_a.pdf",
                            pdf_path="sample_data/vendor_a.pdf", submitted_by="tester")
        queries.create_job(job_id="job-b", pdf_filename="vendor_b.pdf",
                            pdf_path="sample_data/vendor_b.pdf", submitted_by="tester")
        queries.create_job(job_id="job-a2", pdf_filename="vendor_a.pdf",
                            pdf_path="sample_data/vendor_a.pdf", submitted_by="tester")

        first = queries.claim_next_pending_job()   # job-a1 (vendor_a.pdf)
        second = queries.claim_next_pending_job()  # job-b (different filename -- ok)
        third = queries.claim_next_pending_job()   # job-a2 blocked -- vendor_a.pdf still PROCESSING

        self.assertEqual(first["job_id"], "job-a1")
        self.assertEqual(second["job_id"], "job-b")
        self.assertIsNone(third)

    def test_second_job_for_same_filename_claimable_once_first_completes(self):
        queries.create_job(job_id="job-a1", pdf_filename="vendor_a.pdf",
                            pdf_path="sample_data/vendor_a.pdf", submitted_by="tester")
        queries.create_job(job_id="job-a2", pdf_filename="vendor_a.pdf",
                            pdf_path="sample_data/vendor_a.pdf", submitted_by="tester")

        first = queries.claim_next_pending_job()
        self.assertIsNone(queries.claim_next_pending_job())

        queries.update_job_status("job-a1", status="COMPLETED",
                                   completed_at="2026-07-24T00:05:00+00:00",
                                   statement_id="STMT-BBB222")

        second = queries.claim_next_pending_job()
        self.assertEqual(second["job_id"], "job-a2")


def _insert_gold_summary(execute_sql, *, statement_id, total_invoice_count):
    execute_sql(
        """
        INSERT INTO gold_reconciliation_summary (
            summary_id, vendor_id, vendor_name, statement_period, statement_id,
            statement_total, erp_total, difference, total_invoice_count,
            matched_count, exception_count, match_percentage, overall_status,
            reconciliation_timestamp, erp_version
        ) VALUES (?, 'V1', 'Vendor One', '2026-07', ?, 1000.0, 1000.0, 0.0, ?, ?, 0, 100.0,
                  'RECONCILED', '2026-07-24T00:00:00+00:00', 1)
        """,
        [f"SUM-{statement_id}", statement_id, total_invoice_count, total_invoice_count],
    )


def _insert_gold_exception(execute_sql, *, statement_id, exception_id, status="OPEN",
                            ai_confidence_score=None, invoice_number="INV-1"):
    execute_sql(
        """
        INSERT INTO gold_exceptions (
            exception_id, vendor_id, invoice_number, statement_amount, erp_amount,
            match_status, exception_reason, exception_status, statement_id, date_raised,
            ai_confidence_score
        ) VALUES (?, 'V1', ?, 100.0, NULL, 'EXCEPTION', 'Invoice Missing', ?, ?, '2026-07-24T00:00:00+00:00', ?)
        """,
        [exception_id, invoice_number, status, statement_id, ai_confidence_score],
    )


class TestBatchQueries(unittest.TestCase):
    """get_all_batches()/get_batch_detail()/get_manual_uploads()/
    get_recent_completed_batches() -- the /batches feature's query layer
    (see web/routers/batches.py, migrations/007_add_batch_id_to_jobs.sql)."""

    def setUp(self):
        self.conn = _make_jobs_db()
        self.execute_sql, self.execute_query = _wire_fake_backend(self.conn)
        patcher1 = mock.patch("web.queries.execute_sql", self.execute_sql)
        patcher2 = mock.patch("web.queries.execute_query", self.execute_query)
        patcher1.start()
        patcher2.start()
        self.addCleanup(patcher1.stop)
        self.addCleanup(patcher2.stop)
        self.addCleanup(self.conn.close)

    def _job(self, job_id, batch_id, status, statement_id=None,
              submitted_at="2026-07-24T10:00:00+00:00", completed_at=None, filename=None):
        queries.create_job(job_id=job_id, pdf_filename=filename or f"{job_id}.pdf",
                            pdf_path=f"sample_data/{job_id}.pdf", submitted_by="tester",
                            batch_id=batch_id)
        self.execute_sql("UPDATE jobs SET submitted_at = ? WHERE job_id = ?", [submitted_at, job_id])
        queries.update_job_status(job_id, status=status, completed_at=completed_at, statement_id=statement_id)

    def test_completed_batch_aggregates_invoices_and_status(self):
        self._job("job-1", "batch-a", "COMPLETED", statement_id="STMT-1",
                   submitted_at="2026-07-24T10:00:00+00:00", completed_at="2026-07-24T10:02:00+00:00")
        self._job("job-2", "batch-a", "COMPLETED", statement_id="STMT-2",
                   submitted_at="2026-07-24T10:01:00+00:00", completed_at="2026-07-24T10:05:00+00:00")
        _insert_gold_summary(self.execute_sql, statement_id="STMT-1", total_invoice_count=5)
        _insert_gold_summary(self.execute_sql, statement_id="STMT-2", total_invoice_count=3)
        _insert_gold_exception(self.execute_sql, statement_id="STMT-2", exception_id="EXC-1")

        batches = queries.get_all_batches()

        self.assertEqual(len(batches), 1)
        batch = batches[0]
        self.assertEqual(batch["batch_id"], "batch-a")
        self.assertEqual(batch["total_files"], 2)
        self.assertEqual(batch["completed_count"], 2)
        self.assertEqual(batch["failed_count"], 0)
        self.assertEqual(batch["active_count"], 0)
        self.assertEqual(batch["status"], "COMPLETED")
        self.assertEqual(batch["total_invoices"], 8)
        self.assertEqual(batch["total_exceptions"], 1)
        self.assertEqual(batch["time_taken"], "5m 0s")

    def test_batch_with_a_failed_job_is_partial(self):
        self._job("job-1", "batch-b", "COMPLETED", statement_id="STMT-3",
                   completed_at="2026-07-24T10:02:00+00:00")
        self._job("job-2", "batch-b", "FAILED", completed_at="2026-07-24T10:03:00+00:00")

        batch = queries.get_all_batches()[0]

        self.assertEqual(batch["status"], "PARTIAL")

    def test_batch_still_processing_has_no_time_taken(self):
        self._job("job-1", "batch-c", "COMPLETED", statement_id="STMT-4",
                   completed_at="2026-07-24T10:02:00+00:00")
        self._job("job-2", "batch-c", "PROCESSING")

        batch = queries.get_all_batches()[0]

        self.assertEqual(batch["status"], "PROCESSING")
        self.assertIsNone(batch["time_taken"])

    def test_manual_uploads_batch_id_null_excluded_from_batches(self):
        queries.create_job(job_id="manual-1", pdf_filename="manual.pdf",
                            pdf_path="sample_data/manual.pdf", submitted_by="tester")

        self.assertEqual(queries.get_all_batches(), [])

    def test_get_manual_uploads_groups_by_date(self):
        self._job("manual-1", None, "COMPLETED", submitted_at="2026-07-24T09:00:00+00:00")
        self._job("manual-2", None, "COMPLETED", submitted_at="2026-07-24T11:00:00+00:00")
        self._job("manual-3", None, "COMPLETED", submitted_at="2026-07-23T09:00:00+00:00")

        groups = queries.get_manual_uploads()

        self.assertEqual([g["date"] for g in groups], ["2026-07-24", "2026-07-23"])
        self.assertEqual(len(groups[0]["jobs"]), 2)
        self.assertEqual(len(groups[1]["jobs"]), 1)

    def test_get_batch_detail_returns_none_for_unknown_batch(self):
        result = queries.get_batch_detail("does-not-exist")

        self.assertIsNone(result["batch"])
        self.assertEqual(result["jobs"], [])

    def test_get_batch_detail_enriches_each_job(self):
        self._job("job-1", "batch-d", "COMPLETED", statement_id="STMT-5",
                   submitted_at="2026-07-24T10:00:00+00:00", completed_at="2026-07-24T10:01:30+00:00")
        self._job("job-2", "batch-d", "FAILED",
                   submitted_at="2026-07-24T10:00:00+00:00", completed_at="2026-07-24T10:00:45+00:00")
        _insert_gold_summary(self.execute_sql, statement_id="STMT-5", total_invoice_count=4)

        result = queries.get_batch_detail("batch-d")

        self.assertEqual(result["batch"]["total_files"], 2)
        self.assertEqual(result["batch"]["status"], "PARTIAL")
        by_id = {j["job_id"]: j for j in result["jobs"]}
        self.assertEqual(by_id["job-1"]["invoice_count"], 4)
        self.assertEqual(by_id["job-1"]["exception_count"], 0)
        self.assertEqual(by_id["job-2"]["invoice_count"], 0)
        self.assertIsNotNone(by_id["job-1"]["time_taken"])

    def test_get_recent_completed_batches_excludes_still_processing(self):
        self._job("job-1", "batch-done", "COMPLETED", statement_id="STMT-6",
                   submitted_at="2026-07-24T09:00:00+00:00", completed_at="2026-07-24T09:05:00+00:00")
        self._job("job-2", "batch-running", "PROCESSING",
                   submitted_at="2026-07-24T11:00:00+00:00")

        recent = queries.get_recent_completed_batches(limit=3)

        self.assertEqual([b["batch_id"] for b in recent], ["batch-done"])

    def test_get_recent_completed_batches_respects_limit(self):
        for i in range(5):
            self._job(f"job-{i}", f"batch-{i}", "COMPLETED", statement_id=f"STMT-{i}",
                       submitted_at=f"2026-07-2{i}T09:00:00+00:00", completed_at=f"2026-07-2{i}T09:05:00+00:00")

        recent = queries.get_recent_completed_batches(limit=3)

        self.assertEqual(len(recent), 3)


class TestBulkApproveExceptions(unittest.TestCase):
    """get_high_confidence_exception_count()/bulk_approve_exceptions()
    (see web/routers/exceptions.py's POST /exceptions/{vendor}/bulk-approve).
    Uses _make_jobs_db() (not _make_db()) because bulk_approve_exceptions()
    calls resolve_exception(), which writes to exception_dispositions --
    a table only present once every migration (002 onward) is applied."""

    def setUp(self):
        self.conn = _make_jobs_db()
        self.execute_sql, self.execute_query = _wire_fake_backend(self.conn)
        patcher1 = mock.patch("web.queries.execute_sql", self.execute_sql)
        patcher2 = mock.patch("web.queries.execute_query", self.execute_query)
        patcher1.start()
        patcher2.start()
        self.addCleanup(patcher1.stop)
        self.addCleanup(patcher2.stop)
        self.addCleanup(self.conn.close)

        _insert_gold_summary(self.execute_sql, statement_id="STMT-BA", total_invoice_count=3)

    def test_count_excludes_null_and_below_threshold_confidence(self):
        _insert_gold_exception(self.execute_sql, statement_id="STMT-BA", exception_id="EXC-1",
                                invoice_number="INV-1", ai_confidence_score=None)
        _insert_gold_exception(self.execute_sql, statement_id="STMT-BA", exception_id="EXC-2",
                                invoice_number="INV-2", ai_confidence_score=0.85)
        _insert_gold_exception(self.execute_sql, statement_id="STMT-BA", exception_id="EXC-3",
                                invoice_number="INV-3", ai_confidence_score=0.995)

        count = queries.get_high_confidence_exception_count("Vendor One", threshold=0.99)

        self.assertEqual(count, 1)

    def test_count_excludes_already_resolved_exceptions(self):
        _insert_gold_exception(self.execute_sql, statement_id="STMT-BA", exception_id="EXC-1",
                                invoice_number="INV-1", ai_confidence_score=0.999, status="RESOLVED")

        count = queries.get_high_confidence_exception_count("Vendor One", threshold=0.99)

        self.assertEqual(count, 0)

    def test_count_is_zero_for_unknown_vendor(self):
        count = queries.get_high_confidence_exception_count("Nobody", threshold=0.99)

        self.assertEqual(count, 0)

    def test_bulk_approve_resolves_only_qualifying_exceptions(self):
        _insert_gold_exception(self.execute_sql, statement_id="STMT-BA", exception_id="EXC-1",
                                invoice_number="INV-1", ai_confidence_score=0.995)
        _insert_gold_exception(self.execute_sql, statement_id="STMT-BA", exception_id="EXC-2",
                                invoice_number="INV-2", ai_confidence_score=0.999)
        _insert_gold_exception(self.execute_sql, statement_id="STMT-BA", exception_id="EXC-3",
                                invoice_number="INV-3", ai_confidence_score=0.50)

        approved = queries.bulk_approve_exceptions("Vendor One", threshold=0.99, reviewed_by="reviewer@vive.com")

        self.assertEqual(approved, 2)

        total, resolved = queries.get_exception_counts("STMT-BA")
        self.assertEqual(total, 3)
        self.assertEqual(resolved, 2)

        low_confidence_row = self.execute_query(
            "SELECT exception_status FROM gold_exceptions WHERE exception_id = 'EXC-3'"
        )[0]
        self.assertEqual(low_confidence_row["exception_status"], "OPEN")

    def test_bulk_approve_writes_a_disposition_row_per_exception(self):
        _insert_gold_exception(self.execute_sql, statement_id="STMT-BA", exception_id="EXC-1",
                                invoice_number="INV-1", ai_confidence_score=0.995)

        queries.bulk_approve_exceptions("Vendor One", threshold=0.99, reviewed_by="reviewer@vive.com")

        dispositions = self.execute_query(
            "SELECT * FROM exception_dispositions WHERE exception_id = 'EXC-1'"
        )
        self.assertEqual(len(dispositions), 1)
        self.assertEqual(dispositions[0]["disposition_status"], "ACCEPTED")
        self.assertEqual(dispositions[0]["disposed_by"], "reviewer@vive.com")

    def test_bulk_approve_returns_zero_for_unknown_vendor(self):
        approved = queries.bulk_approve_exceptions("Nobody", threshold=0.99, reviewed_by="reviewer@vive.com")

        self.assertEqual(approved, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
