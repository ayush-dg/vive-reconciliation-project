"""
tests/test_home_time_window.py

Home's time filter: web/time_window.py's Eastern-day/month -> UTC
boundaries (both DST transitions), the "Last run" session grouping, the
labels; queries.get_home_dashboard()'s one runs-in-window query driving
the KPI cards, "N of M" and the table together; and the route's URL
handling (defaults, fallbacks, and which params each link keeps).

Query tests run the real SQL against in-memory SQLite stand-ins for the
Fabric Warehouse and Azure SQL (same approach as
tests/test_list_filters_and_sort.py). Timestamps are stored in the same
"YYYY-MM-DD HH:MM:SS[.ffffff]" text form the adapter below binds window
boundaries in, so SQLite's text comparison orders them correctly -- on
Fabric they are real DATETIME2 values and bound datetimes.
"""

import os
import re
import sqlite3
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from web import queries
from web import time_window as tw
from web.deps import require_login
from web.routers import dashboard

sqlite3.register_adapter(datetime, lambda d: d.isoformat(" "))

U = lambda *a: datetime(*a)  # naive UTC, as pyodbc returns DATETIME2


# ---------------------------------------------------------------------------
# Boundaries
# ---------------------------------------------------------------------------

class TestEasternBoundaries(unittest.TestCase):

    def test_edt_day_starts_at_0400_utc(self):
        self.assertEqual(tw.day_bounds(date(2026, 9, 29)), (U(2026, 9, 29, 4), U(2026, 9, 30, 4)))

    def test_est_day_starts_at_0500_utc(self):
        self.assertEqual(tw.day_bounds(date(2026, 12, 15)), (U(2026, 12, 15, 5), U(2026, 12, 16, 5)))

    def test_spring_forward_day_is_23_hours(self):
        start, end = tw.day_bounds(date(2026, 3, 8))
        self.assertEqual((start, end), (U(2026, 3, 8, 5), U(2026, 3, 9, 4)))
        self.assertEqual(end - start, timedelta(hours=23))

    def test_fall_back_day_is_25_hours(self):
        start, end = tw.day_bounds(date(2026, 11, 1))
        self.assertEqual((start, end), (U(2026, 11, 1, 4), U(2026, 11, 2, 5)))
        self.assertEqual(end - start, timedelta(hours=25))

    def test_month_spanning_fall_back(self):
        self.assertEqual(tw.month_bounds(2026, 11), (U(2026, 11, 1, 4), U(2026, 12, 1, 5)))

    def test_month_spanning_spring_forward(self):
        self.assertEqual(tw.month_bounds(2026, 3), (U(2026, 3, 1, 5), U(2026, 4, 1, 4)))

    def test_december_rolls_into_january(self):
        self.assertEqual(tw.month_bounds(2026, 12), (U(2026, 12, 1, 5), U(2027, 1, 1, 5)))

    def test_run_just_before_eastern_midnight_belongs_to_previous_day(self):
        sep28 = tw.resolve_window("date", "2026-09-28")
        sep29 = tw.resolve_window("date", "2026-09-29")
        late = U(2026, 9, 29, 3, 59, 59)   # 11:59:59 PM ET, Sep 28
        midnight = U(2026, 9, 29, 4)       # 12:00 AM ET, Sep 29
        self.assertTrue(sep28.start_utc <= late < sep28.end_utc)
        self.assertFalse(sep29.start_utc <= late < sep29.end_utc)
        self.assertTrue(sep29.start_utc <= midnight < sep29.end_utc)
        self.assertFalse(sep28.start_utc <= midnight < sep28.end_utc)


class TestResolveWindow(unittest.TestCase):

    NOW = datetime(2026, 9, 29, 13, 0, tzinfo=timezone.utc)  # 9:00 AM ET

    def test_default_is_last_run(self):
        w = tw.resolve_window(outlook_jobs=[{"submitted_at": U(2026, 9, 29, 12), "statement_id": "S1"}], now=self.NOW)
        self.assertEqual(w.range, "last")

    def test_date_alone_implies_range_date(self):
        w = tw.resolve_window(None, "2026-09-28", None)
        self.assertEqual((w.range, w.date, w.start_utc), ("date", "2026-09-28", U(2026, 9, 28, 4)))

    def test_month_alone_implies_range_month(self):
        w = tw.resolve_window(None, None, "2026-11")
        self.assertEqual((w.range, w.month, w.start_utc, w.end_utc),
                         ("month", "2026-11", U(2026, 11, 1, 4), U(2026, 12, 1, 5)))

    def test_bad_values_fall_back_to_last(self):
        jobs = [{"submitted_at": U(2026, 9, 29), "statement_id": "S1"}]
        for args in (("date", "2026-13-40", None), ("date", "", None), ("month", None, "2026-9x"),
                     ("month", None, None), ("bogus", None, None), (None, "not-a-date", None)):
            with self.subTest(args=args):
                self.assertEqual(tw.resolve_window(*args, outlook_jobs=jobs).range, "last")

    def test_today_uses_the_eastern_calendar_day(self):
        # 02:00Z on Sep 29 is still 10 PM on Sep 28 in New York.
        w = tw.resolve_window("today", now=datetime(2026, 9, 29, 2, 0, tzinfo=timezone.utc))
        self.assertEqual((w.date, w.start_utc, w.end_utc), ("2026-09-28", U(2026, 9, 28, 4), U(2026, 9, 29, 4)))

    def test_this_month_uses_the_eastern_calendar_month(self):
        w = tw.resolve_window("month_current", now=datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc))
        self.assertEqual((w.month, w.start_utc, w.end_utc), ("2026-09", U(2026, 9, 1, 4), U(2026, 10, 1, 4)))

    def test_all_time_has_no_bounds(self):
        w = tw.resolve_window("all")
        self.assertEqual(w.sql(), ("", []))

    def test_sql_is_a_bound_half_open_predicate(self):
        w = tw.resolve_window("date", "2026-09-28")
        self.assertEqual(w.sql(), (" AND reconciliation_timestamp >= ? AND reconciliation_timestamp < ?",
                                   [U(2026, 9, 28, 4), U(2026, 9, 29, 4)]))


def _job(statement_id, submitted_at, status="COMPLETED"):
    return {"statement_id": statement_id, "submitted_at": submitted_at, "status": status}


class TestOutlookLastSync(unittest.TestCase):
    """web/time_window.py's outlook_last_sync() -- pure grouping logic
    over already-Outlook-scoped job dicts (queries.get_outlook_synced_jobs()
    is what actually excludes manual/dropzone/Event-Grid jobs via
    source_blob_path IS NOT NULL; see TestGetOutlookSyncedJobsQuery for
    that part)."""

    def test_chains_back_while_gaps_are_within_ten_minutes(self):
        jobs = [_job("S4", U(2026, 9, 29, 12, 8)), _job("S3", U(2026, 9, 29, 12, 2)),
                _job("S2", U(2026, 9, 29, 11, 54)), _job("S1", U(2026, 9, 29, 11, 50)),
                _job("S0", U(2026, 9, 29, 11, 30))]  # last gap 20m breaks the chain
        chain = tw.outlook_last_sync(jobs)
        self.assertEqual([j["statement_id"] for j in chain], ["S4", "S3", "S2", "S1"])

    def test_a_gap_over_ten_minutes_starts_a_new_sync(self):
        jobs = [_job("S2", U(2026, 9, 29, 12, 8)), _job("S1", U(2026, 9, 29, 11, 50))]  # 18m apart
        chain = tw.outlook_last_sync(jobs)
        self.assertEqual([j["statement_id"] for j in chain], ["S2"])

    def test_gap_of_exactly_ten_minutes_still_chains(self):
        jobs = [_job("S2", U(2026, 9, 29, 12, 10)), _job("S1", U(2026, 9, 29, 12, 0))]
        chain = tw.outlook_last_sync(jobs)
        self.assertEqual([j["statement_id"] for j in chain], ["S2", "S1"])

    def test_gap_just_over_ten_minutes_breaks(self):
        jobs = [_job("S2", U(2026, 9, 29, 12, 10, 1)), _job("S1", U(2026, 9, 29, 12, 0))]
        chain = tw.outlook_last_sync(jobs)
        self.assertEqual([j["statement_id"] for j in chain], ["S2"])

    def test_takes_the_newest_sync_only_ignoring_an_older_one(self):
        jobs = [_job("N2", U(2026, 9, 29, 12, 8)), _job("N1", U(2026, 9, 29, 12, 3)),
                _job("O2", U(2026, 9, 29, 8, 0)), _job("O1", U(2026, 9, 29, 7, 55))]
        chain = tw.outlook_last_sync(jobs)
        self.assertEqual({j["statement_id"] for j in chain}, {"N1", "N2"})

    def test_order_and_input_timestamp_types_do_not_matter(self):
        jobs = [_job("S2", "2026-09-29T12:08:00+00:00"), _job("S1", "2026-09-29 12:03:00")]
        chain = tw.outlook_last_sync(jobs)
        self.assertEqual([j["statement_id"] for j in chain], ["S2", "S1"])

    def test_threshold_is_the_named_constant(self):
        self.assertEqual(tw.OUTLOOK_SYNC_GAP, timedelta(minutes=10))

    def test_a_job_with_no_statement_id_yet_still_counts_toward_the_chain(self):
        # Still processing -- no statement_id, but it's still part of the
        # sync (see the "still processing" label test below).
        jobs = [_job(None, U(2026, 9, 29, 12, 8), "PROCESSING"), _job("S1", U(2026, 9, 29, 12, 3))]
        chain = tw.outlook_last_sync(jobs)
        self.assertEqual(len(chain), 2)

    def test_no_jobs_at_all_returns_none(self):
        self.assertIsNone(tw.outlook_last_sync([]))

    def test_a_sync_that_queued_zero_pdfs_is_simply_invisible(self):
        # No job rows are ever created for an empty "Sync to Webapp" click
        # (see mailbox_sync.py) -- there's nothing to special-case here;
        # the next older non-empty sync just wins.
        jobs = [_job("OLDER", U(2026, 9, 20, 9, 0))]
        chain = tw.outlook_last_sync(jobs)
        self.assertEqual([j["statement_id"] for j in chain], ["OLDER"])


class TestResolveWindowLast(unittest.TestCase):

    def test_single_job_with_a_statement(self):
        w = tw.resolve_window("last", outlook_jobs=[_job("S1", U(2026, 9, 29, 12, 8))])
        self.assertEqual((w.statement_ids, w.sync_time_utc, w.sync_job_count),
                         (frozenset({"S1"}), U(2026, 9, 29, 12, 8), 1))
        self.assertFalse(w.empty)

    def test_statement_ids_excludes_jobs_still_processing(self):
        jobs = [_job(None, U(2026, 9, 29, 12, 8), "PROCESSING"), _job("S1", U(2026, 9, 29, 12, 3))]
        w = tw.resolve_window("last", outlook_jobs=jobs)
        self.assertEqual(w.statement_ids, frozenset({"S1"}))
        self.assertEqual(w.sync_job_count, 2)  # still counts toward the total
        self.assertEqual((w.sync_completed, w.sync_failed, w.sync_processing), (1, 0, 1))

    def test_window_carries_the_syncs_job_counts_by_status(self):
        jobs = [_job("C1", U(2026, 9, 29, 12, 8)), _job("F1", U(2026, 9, 29, 12, 7), "FAILED"),
                _job(None, U(2026, 9, 29, 12, 6), "FAILED"), _job(None, U(2026, 9, 29, 12, 5), "PENDING"),
                _job(None, U(2026, 9, 29, 12, 4), "PROCESSING")]
        w = tw.resolve_window("last", outlook_jobs=jobs)
        self.assertEqual((w.sync_job_count, w.sync_completed, w.sync_failed, w.sync_processing), (5, 1, 2, 2))


# ---------------------------------------------------------------------------
# sync_status_counts() / sync_count_text() -- "still processing" means a
# job really is PENDING/PROCESSING (2026-10-06), not "no recon_summary row"
# ---------------------------------------------------------------------------

class TestSyncStatusCounts(unittest.TestCase):

    def test_only_pending_and_processing_count_as_still_processing(self):
        chain = [_job("A", None, "PENDING"), _job("B", None, "PROCESSING"),
                 _job("C", None, "COMPLETED"), _job("D", None, "FAILED")]
        self.assertEqual(tw.sync_status_counts(chain), (1, 1, 2))

    def test_failed_counts_as_failed_with_or_without_a_statement_id(self):
        # Oct 1: three 0-row extractions kept their statement_id, the
        # 30-minute timeout never got one -- all four are just failed.
        chain = [_job("STMT-1", None, "FAILED"), _job(None, None, "FAILED")]
        self.assertEqual(tw.sync_status_counts(chain), (0, 2, 0))

    def test_a_completed_cache_hit_counts_as_completed(self):
        # A cache hit completes with a statement_id that never gets a
        # silver.recon_summary row of its own -- that is not "processing".
        self.assertEqual(tw.sync_status_counts([_job("STMT-CACHE-HIT", None, "COMPLETED")]), (1, 0, 0))

    def test_empty_chain(self):
        self.assertEqual(tw.sync_status_counts([]), (0, 0, 0))

    def test_text_all_completed_is_a_plain_count(self):
        self.assertEqual(tw.sync_count_text(572, 0, 0), "572 statements")
        self.assertEqual(tw.sync_count_text(1, 0, 0), "1 statement")
        self.assertEqual(tw.sync_count_text(1500, 0, 0), "1,500 statements")

    def test_text_with_failures(self):
        self.assertEqual(tw.sync_count_text(568, 4, 0), "572 statements (568 completed, 4 failed)")

    def test_text_with_everything(self):
        self.assertEqual(tw.sync_count_text(500, 2, 70),
                         "572 statements (500 completed, 2 failed, 70 still processing)")

    def test_text_leaves_zero_counts_out(self):
        self.assertEqual(tw.sync_count_text(2, 0, 1), "3 statements (2 completed, 1 still processing)")
        self.assertEqual(tw.sync_count_text(0, 0, 3), "3 statements (3 still processing)")
        self.assertEqual(tw.sync_count_text(0, 2, 0), "2 statements (2 failed)")
        self.assertEqual(tw.sync_count_text(0, 1, 1), "2 statements (1 failed, 1 still processing)")

    def test_sql_is_a_python_side_membership_filter_not_a_predicate(self):
        w = tw.resolve_window("last", outlook_jobs=[_job("S1", U(2026, 9, 29, 12, 8))])
        self.assertEqual(w.sql(), ("", []))

    def test_no_outlook_jobs_at_all_gives_an_empty_window(self):
        w = tw.resolve_window("last", outlook_jobs=[])
        self.assertTrue(w.empty)
        self.assertEqual(w.sql(), (" AND 1 = 0", []))
        self.assertIsNone(w.statement_ids)


# ---------------------------------------------------------------------------
# outlook_all_syncs() -- every sync, not just the newest (2026-09-30)
# ---------------------------------------------------------------------------

class TestOutlookAllSyncs(unittest.TestCase):

    def test_no_jobs_at_all_returns_empty_list(self):
        self.assertEqual(tw.outlook_all_syncs([]), [])

    def test_a_single_sync(self):
        jobs = [_job("S2", U(2026, 9, 29, 12, 8)), _job("S1", U(2026, 9, 29, 12, 3))]
        syncs = tw.outlook_all_syncs(jobs)
        self.assertEqual(len(syncs), 1)
        self.assertEqual([j["statement_id"] for j in syncs[0]], ["S2", "S1"])

    def test_multiple_gap_separated_syncs_newest_first(self):
        jobs = [_job("N2", U(2026, 9, 29, 12, 8)), _job("N1", U(2026, 9, 29, 12, 3)),
                _job("M1", U(2026, 9, 29, 9, 0)),
                _job("O2", U(2026, 9, 28, 8, 0)), _job("O1", U(2026, 9, 28, 7, 55))]
        syncs = tw.outlook_all_syncs(jobs)
        self.assertEqual([[j["statement_id"] for j in s] for s in syncs],
                         [["N2", "N1"], ["M1"], ["O2", "O1"]])

    def test_a_job_with_no_statement_id_still_counts_toward_its_chain(self):
        jobs = [_job(None, U(2026, 9, 29, 12, 8)), _job("S1", U(2026, 9, 29, 12, 3))]
        syncs = tw.outlook_all_syncs(jobs)
        self.assertEqual(len(syncs), 1)
        self.assertEqual(len(syncs[0]), 2)

    def test_exactly_ten_minute_gap_still_chains_but_over_breaks(self):
        exact = [_job("S2", U(2026, 9, 29, 12, 10)), _job("S1", U(2026, 9, 29, 12, 0))]
        self.assertEqual(len(tw.outlook_all_syncs(exact)), 1)
        over = [_job("S2", U(2026, 9, 29, 12, 10, 1)), _job("S1", U(2026, 9, 29, 12, 0))]
        self.assertEqual(len(tw.outlook_all_syncs(over)), 2)

    def test_outlook_last_sync_is_just_the_newest_of_all_syncs(self):
        jobs = [_job("N2", U(2026, 9, 29, 12, 8)), _job("N1", U(2026, 9, 29, 12, 3)),
                _job("O1", U(2026, 9, 28, 8, 0))]
        self.assertEqual(tw.outlook_last_sync(jobs), tw.outlook_all_syncs(jobs)[0])


class TestOutlookSyncOptions(unittest.TestCase):

    def test_no_jobs_gives_no_options_and_not_truncated(self):
        options, truncated = tw.outlook_sync_options([])
        self.assertEqual(options, [])
        self.assertFalse(truncated)

    def test_options_newest_first_with_value_and_label(self):
        jobs = [_job("N1", U(2026, 9, 29, 16, 2)),
                _job("O1", U(2026, 9, 28, 12, 0))]
        options, truncated = tw.outlook_sync_options(jobs)
        self.assertFalse(truncated)
        self.assertEqual([o["value"] for o in options],
                         ["2026-09-29T16:02:00Z", "2026-09-28T12:00:00Z"])
        self.assertEqual(options[0]["label"], "Sep 29, 12:02 PM ET · 1 statement")

    def test_still_processing_jobs_are_counted_by_status(self):
        jobs = [_job(None, U(2026, 9, 29, 16, 2), "PROCESSING"), _job("A", U(2026, 9, 29, 16, 0)),
                _job("B", U(2026, 9, 29, 15, 58))]
        options, _ = tw.outlook_sync_options(jobs)
        self.assertEqual(options[0]["label"], "Sep 29, 12:02 PM ET · 3 statements (2 completed, 1 still processing)")

    def test_a_sync_with_zero_statements_yet_is_still_listed(self):
        jobs = [_job(None, U(2026, 9, 29, 16, 2), "PENDING"), _job(None, U(2026, 9, 29, 16, 0), "PENDING")]
        options, _ = tw.outlook_sync_options(jobs)
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]["label"], "Sep 29, 12:02 PM ET · 2 statements (2 still processing)")

    def test_failed_jobs_and_cache_hits_in_a_finished_sync(self):
        # Until 2026-10-06 this read "2 of 3 statements": the failed job
        # had no statement_id. Nothing here is in flight any more.
        jobs = [_job("CACHE-HIT", U(2026, 9, 29, 16, 2)), _job("A", U(2026, 9, 29, 16, 0)),
                _job(None, U(2026, 9, 29, 15, 58), "FAILED")]
        options, _ = tw.outlook_sync_options(jobs)
        self.assertEqual(options[0]["label"], "Sep 29, 12:02 PM ET · 3 statements (2 completed, 1 failed)")

    def test_capped_at_30_with_a_truncated_flag(self):
        jobs = [_job(f"S{i}", U(2026, 9, 1, 0, 0) + timedelta(days=i)) for i in range(35)]
        # Each job 1 day apart -- every job is its own sync (gap >> 10 min).
        options, truncated = tw.outlook_sync_options(jobs)
        self.assertEqual(len(options), 30)
        self.assertTrue(truncated)

    def test_a_bookmark_past_the_cap_still_resolves_via_resolve_window(self):
        jobs = [_job(f"S{i}", U(2026, 9, 1, 0, 0) + timedelta(days=i)) for i in range(35)]
        options, truncated = tw.outlook_sync_options(jobs)
        self.assertTrue(truncated)
        oldest_value = tw.outlook_all_syncs(jobs)[-1][0]["submitted_at"].isoformat() + "Z"
        self.assertNotIn(oldest_value, [o["value"] for o in options])
        w = tw.resolve_window("last", outlook_jobs=jobs, sync_=oldest_value)
        self.assertEqual(w.statement_ids, frozenset({"S0"}))


class TestResolveWindowSyncParam(unittest.TestCase):

    def setUp(self):
        self.jobs = [_job("N1", U(2026, 9, 29, 16, 2)), _job("O1", U(2026, 9, 28, 12, 0))]

    def test_no_sync_param_defaults_to_the_latest(self):
        w = tw.resolve_window("last", outlook_jobs=self.jobs)
        self.assertEqual(w.statement_ids, frozenset({"N1"}))

    def test_valid_sync_param_selects_that_sync(self):
        w = tw.resolve_window("last", outlook_jobs=self.jobs, sync_="2026-09-28T12:00:00Z")
        self.assertEqual(w.statement_ids, frozenset({"O1"}))
        self.assertEqual(w.sync_time_utc, U(2026, 9, 28, 12, 0))

    def test_stale_or_unknown_sync_param_falls_back_to_latest_no_error(self):
        w = tw.resolve_window("last", outlook_jobs=self.jobs, sync_="2019-01-01T00:00:00Z")
        self.assertEqual(w.statement_ids, frozenset({"N1"}))

    def test_malformed_sync_param_falls_back_to_latest_no_error(self):
        w = tw.resolve_window("last", outlook_jobs=self.jobs, sync_="not-a-timestamp")
        self.assertEqual(w.statement_ids, frozenset({"N1"}))

    def test_empty_sync_param_is_treated_as_none(self):
        w = tw.resolve_window("last", outlook_jobs=self.jobs, sync_="")
        self.assertEqual(w.statement_ids, frozenset({"N1"}))


class TestMonthOptionsAndLabels(unittest.TestCase):

    def test_month_options_are_eastern_months_with_runs_newest_first(self):
        ts = [U(2026, 10, 1, 2), U(2026, 9, 15), U(2026, 8, 3), U(2026, 9, 1)]  # Oct 1 02:00Z = Sep 30 ET
        self.assertEqual(tw.month_options(ts), ["2026-09", "2026-08"])

    def test_last_run_label_all_statements_matched(self):
        # 15:50Z/15:55Z/16:02Z UTC = 11:50/11:55/12:02 ET (EDT, UTC-4 in
        # September); gaps 5m/7m both chain.
        jobs = [_job("A", U(2026, 9, 29, 15, 50)), _job("B", U(2026, 9, 29, 15, 55)),
                _job("C", U(2026, 9, 29, 16, 2))]
        w = tw.resolve_window("last", outlook_jobs=jobs)
        self.assertEqual(tw.window_label(w, 3), "Last sync · Sep 29, 12:02 PM ET · 3 statements")

    def test_last_run_label_still_processing(self):
        jobs = [_job(None, U(2026, 9, 29, 16, 2), "PROCESSING"), _job("A", U(2026, 9, 29, 16, 0)),
                _job("B", U(2026, 9, 29, 15, 58))]
        w = tw.resolve_window("last", outlook_jobs=jobs)
        self.assertEqual(tw.window_label(w, 2),
                         "Last sync · Sep 29, 12:02 PM ET · 3 statements (2 completed, 1 still processing)")

    def test_last_run_label_oct1_sync_shape(self):
        # The dev Oct 1 sync (Phase 3 snapshot): 572 jobs, newest queued
        # 21:39:17Z = 5:39 PM ET, nothing in flight. 481 have a
        # recon_summary row; 87 completed cache hits do not; 3 failed
        # 0-row jobs kept a statement_id; 1 timed-out job has none.
        # Read "481 of 572 statements (91 still processing)" until
        # 2026-10-06.
        newest = U(2026, 10, 1, 21, 39, 17)
        jobs = ([_job(f"R{i}", newest) for i in range(481)]
                + [_job(f"C{i}", newest) for i in range(87)]
                + [_job(f"F{i}", newest, "FAILED") for i in range(3)]
                + [_job(None, newest, "FAILED")])
        w = tw.resolve_window("last", outlook_jobs=jobs)
        self.assertEqual(tw.window_label(w, 481),
                         "Last sync · Oct 1, 5:39 PM ET · 572 statements (568 completed, 4 failed)")
        options, _ = tw.outlook_sync_options(jobs)
        self.assertEqual(options[0]["label"], "Oct 1, 5:39 PM ET · 572 statements (568 completed, 4 failed)")

    def test_last_run_label_ignores_the_recon_summary_count(self):
        # Every job completed, but only one has a recon_summary row (the
        # other is a cache hit) -- still a plain, finished "2 statements".
        jobs = [_job("A", U(2026, 9, 29, 16, 2)), _job("CACHE-HIT", U(2026, 9, 29, 16, 0))]
        w = tw.resolve_window("last", outlook_jobs=jobs)
        self.assertEqual(tw.window_label(w, 1), "Last sync · Sep 29, 12:02 PM ET · 2 statements")

    def test_last_run_label_single_job(self):
        # 16:08Z UTC = 12:08 PM ET.
        w = tw.resolve_window("last", outlook_jobs=[_job("S1", U(2026, 9, 29, 16, 8))])
        self.assertEqual(tw.window_label(w, 1), "Last sync · Sep 29, 12:08 PM ET · 1 statement")

    def test_last_run_label_no_outlook_jobs_at_all(self):
        w = tw.resolve_window("last", outlook_jobs=[])
        self.assertEqual(tw.window_label(w, 0), "Last sync · no runs")

    def test_other_labels(self):
        now = datetime(2026, 9, 29, 13, tzinfo=timezone.utc)
        self.assertEqual(tw.window_label(tw.resolve_window("today", now=now), 0), "Today · Sep 29 · no runs yet")
        self.assertEqual(tw.window_label(tw.resolve_window("month_current", now=now), 213),
                         "This month · September 2026 · 213 statements")
        self.assertEqual(tw.window_label(tw.resolve_window("date", "2026-09-28"), 53), "Sep 28, 2026 · 53 statements")
        self.assertEqual(tw.window_label(tw.resolve_window("month", None, "2026-08"), 0), "August 2026 · no runs")
        self.assertEqual(tw.window_label(tw.resolve_window("all"), 1500), "All time · 1,500 statements")

    def test_short_labels_and_empty_messages(self):
        self.assertEqual(tw.window_short(tw.resolve_window("date", "2026-09-28")), "Sep 28, 2026")
        self.assertEqual(tw.window_short(tw.resolve_window("all")), "all time")
        self.assertEqual(tw.empty_message(tw.resolve_window("today")), "No reconciliation runs today yet.")
        self.assertEqual(tw.empty_message(tw.resolve_window("month", None, "2026-08")),
                         "No reconciliation runs in August 2026.")


# ---------------------------------------------------------------------------
# get_home_dashboard() -- one query drives cards + N of M + table
# ---------------------------------------------------------------------------

_SELECT_TOP_RE = re.compile(r"^\s*SELECT\s+TOP\s+(\d+)\s+(.*)$", re.IGNORECASE | re.DOTALL)


def _query_fn(conn):
    def query(sql, params=None):
        top = _SELECT_TOP_RE.match(sql)
        if top:
            sql = f"SELECT {top.group(2)}\nLIMIT {top.group(1)}"
        return [dict(r) for r in conn.execute(sql, params or []).fetchall()]
    return query


class TestHomeDashboardQuery(unittest.TestCase):

    def setUp(self):
        self.fabric = sqlite3.connect(":memory:", check_same_thread=False)
        self.fabric.row_factory = sqlite3.Row
        self.fabric.execute("ATTACH DATABASE ':memory:' AS silver")
        self.fabric.execute(
            """CREATE TABLE silver.recon_summary (
                   statement_id TEXT, vendor_name TEXT, statement_period TEXT,
                   total_invoice_count INTEGER, matched_count INTEGER, exception_count INTEGER,
                   statement_total REAL, overall_status TEXT, reconciliation_timestamp TEXT,
                   is_latest_version INTEGER)"""
        )
        self.local = sqlite3.connect(":memory:", check_same_thread=False)
        self.local.row_factory = sqlite3.Row
        self.local.execute("CREATE TABLE document_intake_log (statement_id TEXT, statement_period TEXT, shop_or_entity TEXT)")
        self.local.execute("CREATE TABLE jobs (job_id TEXT, statement_id TEXT, submitted_at TEXT, source_blob_path TEXT, "
                           "status TEXT)")
        for target, conn in (("web.queries.recon_query", self.fabric), ("web.queries.execute_query", self.local)):
            patcher = mock.patch(target, _query_fn(conn))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.fabric.close)
        self.addCleanup(self.local.close)

        # Session A (Sep 29 ET): three runs, each gap under 2h.
        self._run("A1", "Fenix", ts="2026-09-29 12:08:00.421634", invoices=10, matched=10, exc=0, total=100, period="2026-08")
        self._run("A2", "Bald Hill", ts="2026-09-29 11:00:00", invoices=20, matched=15, exc=5, total=200, period="2026-08")
        self._run("A3", "Fenix", ts="2026-09-29 09:30:16", invoices=5, matched=4, exc=1, total=50, period="2026-07")
        # Session B (Sep 28 ET), >2h before A.
        self._run("B1", "Abc Parts", ts="2026-09-28 09:31:00", invoices=40, matched=40, exc=0, total=400, period="2026-08")
        # Sep 28 23:59:59 ET (03:59:59Z Sep 29) -- belongs to Sep 28, not Sep 29.
        self._run("B2", "Abc Parts", ts="2026-09-29 03:59:59", invoices=1, matched=1, exc=0, total=1, period="2026-08")

    def _run(self, sid, vendor, *, ts, invoices, matched, exc, total, period=None):
        self.fabric.execute(
            "INSERT INTO silver.recon_summary VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, 1)",
            [sid, vendor, invoices, matched, exc, total, "RECONCILED" if exc == 0 else "EXCEPTIONS_PRESENT", ts],
        )
        if period:
            self.local.execute("INSERT INTO document_intake_log VALUES (?, ?, NULL)", [sid, period])

    def _window(self, *args, **kwargs):
        return tw.resolve_window(*args, timestamps=queries.get_run_timestamps(),
                                 outlook_jobs=queries.get_outlook_synced_jobs(), **kwargs)

    def _ids(self, data):
        return [r["statement_id"] for r in data["runs"]]

    def _outlook_job(self, statement_id, submitted_at, source_blob_path="mailbox/2026/09/29/x__f.pdf",
                     status="COMPLETED"):
        self.local.execute(
            "INSERT INTO jobs (statement_id, submitted_at, source_blob_path, status) VALUES (?, ?, ?, ?)",
            [statement_id, submitted_at, source_blob_path, status],
        )

    def test_last_run_covers_only_the_latest_outlook_sync(self):
        # A1/A2/A3 queued by one "Sync to Webapp" click (gaps < 10 min);
        # B1 by an earlier, separate click (well over 10 min before it).
        self._outlook_job("A1", "2026-09-29 12:08:00")
        self._outlook_job("A2", "2026-09-29 12:04:00")
        self._outlook_job("A3", "2026-09-29 12:01:00")
        self._outlook_job("B1", "2026-09-28 09:31:00")
        data = queries.get_home_dashboard(self._window("last"))
        self.assertEqual(self._ids(data), ["A1", "A2", "A3"])
        self.assertEqual(data["statement_count"], 3)

    def test_manual_dropzone_and_event_grid_jobs_are_excluded_from_last_run(self):
        self._outlook_job("A1", "2026-09-29 12:08:00")
        # Newer than A1, but none of these ever set source_blob_path --
        # if any leaked in, it would wrongly become the sync's anchor.
        self.local.execute("INSERT INTO jobs (statement_id, submitted_at, source_blob_path) VALUES (?, ?, NULL)",
                           ["A2", "2026-09-29 13:00:00"])  # manual upload
        self.local.execute("INSERT INTO jobs (statement_id, submitted_at, source_blob_path) VALUES (?, ?, NULL)",
                           ["A3", "2026-09-29 13:05:00"])  # dropzone-watcher / event-grid shape
        outlook_jobs = queries.get_outlook_synced_jobs()
        self.assertEqual([j["statement_id"] for j in outlook_jobs], ["A1"])
        data = queries.get_home_dashboard(self._window("last"))
        self.assertEqual(self._ids(data), ["A1"])

    def test_last_run_label_reflects_a_still_processing_job(self):
        self._outlook_job("A1", "2026-09-29 12:08:00")
        self._outlook_job("A2", "2026-09-29 12:05:00")
        self._outlook_job(None, "2026-09-29 12:03:00", status="PROCESSING")  # not yet through intake
        window = self._window("last")
        data = queries.get_home_dashboard(window)
        self.assertEqual(self._ids(data), ["A1", "A2"])
        self.assertEqual(tw.window_label(window, data["statement_count"]),
                         "Last sync · Sep 29, 8:08 AM ET · 3 statements (2 completed, 1 still processing)")

    def test_outlook_synced_jobs_carry_their_status(self):
        self._outlook_job("A1", "2026-09-29 12:08:00", status="FAILED")
        self.assertEqual(queries.get_outlook_synced_jobs(),
                         [{"submitted_at": "2026-09-29 12:08:00", "statement_id": "A1", "status": "FAILED"}])

    def test_finished_sync_with_cache_hits_and_failures_is_not_still_processing(self):
        # Oct 1 shape, scaled down: A1-A3 reached recon_summary; CACHE1
        # completed as a cache hit (no recon_summary row of its own);
        # FAIL1 failed after intake gave it a statement_id; one job
        # failed before it got one. Nothing is PENDING/PROCESSING.
        for sid, ts in (("A1", "2026-09-29 12:08:00"), ("A2", "2026-09-29 12:07:00"),
                        ("A3", "2026-09-29 12:06:00"), ("CACHE1", "2026-09-29 12:05:00")):
            self._outlook_job(sid, ts)
        self._outlook_job("FAIL1", "2026-09-29 12:04:00", status="FAILED")
        self._outlook_job(None, "2026-09-29 12:03:00", status="FAILED")
        window = self._window("last")
        data = queries.get_home_dashboard(window)
        # The cards/"N of M"/table still cover only the recon_summary runs.
        self.assertEqual(self._ids(data), ["A1", "A2", "A3"])
        self.assertEqual(data["statement_count"], 3)
        self.assertEqual(tw.window_label(window, data["statement_count"]),
                         "Last sync · Sep 29, 8:08 AM ET · 6 statements (4 completed, 2 failed)")

    def test_no_outlook_jobs_gives_the_existing_empty_state(self):
        window = self._window("last")  # jobs table has no rows at all
        self.assertTrue(window.empty)
        data = queries.get_home_dashboard(window)
        self.assertEqual(data["statement_count"], 0)
        self.assertEqual(data["runs"], [])

    def test_cards_table_and_n_of_m_cover_the_same_runs(self):
        # Any window works for this -- a calendar range (not "last", which
        # is Outlook-based and tested on its own above) that covers
        # exactly Session A (A1/A2/A3).
        data = queries.get_home_dashboard(self._window("date", "2026-09-29"))
        k = data["kpis"]
        self.assertEqual((k["total_invoices"], k["auto_reconciled"], k["statement_total"], k["vendor_count"]),
                         (35, 29, 350.0, 2))
        self.assertEqual(k["match_rate"], round(29 / 35 * 100, 1))
        # Open exceptions = SUM(exception_count) of the same rows as the table.
        self.assertEqual(k["open_exceptions"], sum(r["exception_count"] for r in data["runs"]))
        self.assertEqual(k["open_exceptions"], 6)
        self.assertEqual((data["reconciled"], data["total"]), (1, 3))

    def test_runs_with_no_invoices_are_left_out_of_everything(self):
        # 2026-10-06: a 0-invoice run (no line reached matching; stored as
        # RECONCILED) and a NULL-count run in the same window as Session A.
        # Neither may show in the table, "N of M reconciled", the KPI
        # cards (incl. vendor count) or the Month options.
        self._run("Z0", "Ghost Parts", ts="2026-09-29 10:00:00", invoices=0, matched=0, exc=0, total=0, period="2026-08")
        self.fabric.execute(
            "INSERT INTO silver.recon_summary VALUES ('ZN', 'Null Parts', NULL, NULL, NULL, NULL, NULL, 'RECONCILED', ?, 1)",
            ["2026-09-29 10:30:00"],
        )
        self._run("ZA", "August Ghost", ts="2026-08-15 12:00:00", invoices=0, matched=0, exc=0, total=0)
        data = queries.get_home_dashboard(self._window("date", "2026-09-29"))
        self.assertEqual(self._ids(data), ["A1", "A2", "A3"])
        self.assertEqual((data["reconciled"], data["total"], data["statement_count"]), (1, 3, 3))
        self.assertEqual(data["kpis"]["vendor_count"], 2)
        self.assertEqual(data["kpis"]["total_invoices"], 35)
        everything = queries.get_home_dashboard(self._window("all"))
        self.assertNotIn("Z0", self._ids(everything) + [r["statement_id"] for r in everything["runs"]])
        self.assertEqual(everything["statement_count"], 5)
        # August only has a 0-invoice run, so it's not offered as a month.
        self.assertEqual(tw.month_options(queries.get_run_timestamps()), ["2026-09"])

    def test_last_run_leaves_out_a_sync_job_whose_run_has_no_invoices(self):
        self._run("Z0", "Ghost Parts", ts="2026-09-29 12:09:00", invoices=0, matched=0, exc=0, total=0)
        self._outlook_job("A1", "2026-09-29 12:08:00")
        self._outlook_job("Z0", "2026-09-29 12:07:00")
        window = self._window("last")
        data = queries.get_home_dashboard(window)
        self.assertEqual(self._ids(data), ["A1"])
        self.assertEqual((data["reconciled"], data["total"], data["kpis"]["vendor_count"]), (1, 1, 1))
        # The sync line still counts the job itself -- it completed.
        self.assertEqual(tw.window_label(window, data["statement_count"]),
                         "Last sync · Sep 29, 8:08 AM ET · 2 statements")

    def test_status_and_period_narrow_the_table_but_not_the_cards(self):
        base = queries.get_home_dashboard(self._window("date", "2026-09-29"))
        data = queries.get_home_dashboard(self._window("date", "2026-09-29"), status="exceptions", period="2026-08")
        self.assertEqual(self._ids(data), ["A2"])
        self.assertEqual((data["reconciled"], data["total"]), (0, 1))
        self.assertEqual(data["kpis"], base["kpis"])
        self.assertEqual(data["statement_count"], 3)

    def test_period_options_come_from_the_window_only(self):
        data = queries.get_home_dashboard(self._window("date", "2026-09-28"))
        self.assertEqual(self._ids(data), ["B2", "B1"])
        self.assertEqual(data["period_options"], ["2026-08"])

    def test_eastern_day_boundary_in_sql(self):
        sep29 = queries.get_home_dashboard(self._window("date", "2026-09-29"))
        self.assertEqual(self._ids(sep29), ["A1", "A2", "A3"])  # B2 (11:59:59 PM ET Sep 28) excluded

    def test_month_window(self):
        data = queries.get_home_dashboard(self._window("month", None, "2026-09"))
        self.assertEqual(data["statement_count"], 5)
        self.assertEqual(queries.get_home_dashboard(self._window("month", None, "2026-08"))["statement_count"], 0)

    def test_all_time_matches_every_run(self):
        self.assertEqual(queries.get_home_dashboard(self._window("all"))["statement_count"], 5)
        self.assertEqual(queries.get_home_dashboard(None)["statement_count"], 5)

    def test_empty_window_is_all_zeros_not_an_error(self):
        data = queries.get_home_dashboard(self._window("date", "2026-01-01"))
        self.assertEqual(data["runs"], [])
        self.assertEqual((data["total"], data["reconciled"], data["statement_count"]), (0, 0, 0))
        self.assertEqual(data["kpis"], {"total_invoices": 0, "auto_reconciled": 0, "open_exceptions": 0,
                                        "statement_total": 0, "vendor_count": 0, "match_rate": None})

    def test_all_time_with_no_runs_at_all(self):
        self.fabric.execute("DELETE FROM silver.recon_summary")
        w = self._window("all")
        self.assertFalse(w.empty)  # "all" is never empty by itself -- it's just an unbound query
        self.assertEqual(queries.get_home_dashboard(w)["statement_count"], 0)

    def test_month_options_from_run_timestamps(self):
        self.assertEqual(tw.month_options(queries.get_run_timestamps()), ["2026-09"])


# ---------------------------------------------------------------------------
# Route -- URL params and what every link keeps
# ---------------------------------------------------------------------------

class TestHomeRouteTimeWindow(unittest.TestCase):

    def setUp(self):
        self.windows = []
        self.result = {
            "kpis": {"total_invoices": 599, "auto_reconciled": 512, "open_exceptions": 87,
                     "statement_total": 1234.5, "vendor_count": 5, "match_rate": 85.5},
            "runs": [{"statement_id": "S1", "vendor_name": "Fenix", "vendor_display_name": "Fenix", "shop": None,
                      "statement_period": "2026-08", "total_invoice_count": 5, "matched_count": 5,
                      "exception_count": 0, "overall_status": "RECONCILED", "reconciliation_timestamp": None,
                      "job_id": None}],
            "total": 47, "reconciled": 19, "period_options": ["2026-08"], "statement_count": 4,
        }

        def get_home_dashboard(window=None, status="all", period=None, limit=10):
            self.windows.append((window, status, period))
            return self.result

        fns = {
            "get_run_timestamps": lambda: [U(2026, 9, 29, 7, 36), U(2026, 9, 29, 9, 30), U(2026, 9, 29, 11, 0),
                                           U(2026, 9, 29, 12, 8), U(2026, 8, 20, 12)],
            # 4 jobs chained within OUTLOOK_SYNC_GAP -- one Outlook sync,
            # newest at 12:08Z = 8:08 AM ET, all completed (see
            # window_label()'s sync_count_text()).
            "get_outlook_synced_jobs": lambda: [
                {"submitted_at": U(2026, 9, 29, 12, 8), "statement_id": "S1", "status": "COMPLETED"},
                {"submitted_at": U(2026, 9, 29, 12, 4), "statement_id": "S2", "status": "COMPLETED"},
                {"submitted_at": U(2026, 9, 29, 12, 1), "statement_id": "S3", "status": "COMPLETED"},
                {"submitted_at": U(2026, 9, 29, 11, 58), "statement_id": "S4", "status": "COMPLETED"},
            ],
            "get_home_dashboard": get_home_dashboard,
            "get_active_jobs": lambda: [], "get_failed_jobs": lambda: [],
            "get_recent_completed_batches": lambda limit=3: [],
            "get_last_netsuite_sync": lambda: None, "get_last_outlook_sync": lambda: None,
            "get_open_recon_exceptions_count": lambda: 1806, "get_pending_review_count": lambda: 3,
        }
        for name, fn in fns.items():
            patcher = mock.patch(f"web.queries.{name}", fn)
            patcher.start()
            self.addCleanup(patcher.stop)
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-secret")
        app.include_router(dashboard.router)
        app.dependency_overrides[require_login] = lambda: "tester"
        self.client = TestClient(app)

    def _get(self, url):
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        return resp.text.replace("&amp;", "&")

    def _window(self):
        return self.windows[-1][0]

    def test_default_is_last_run_with_label(self):
        html = self._get("/")
        self.assertEqual(self._window().range, "last")
        self.assertIn("Last sync · Sep 29, 8:08 AM ET · 4 statements", html)
        self.assertIn('href="/" class="filter-chip active">Last run', html)

    def test_sync_wording_no_longer_names_outlook_except_the_top_bar_badge(self):
        # 2026-10-06: "Past Outlook syncs"/"Last Outlook sync" became
        # "Past syncs"/"Last sync"; the top bar's "Outlook: <time>" badge
        # (the actual Outlook pull time) stays.
        html = self._get("/")
        self.assertRegex(html, r'id="window-sync-btn"[^>]*>\s*Past syncs<svg')
        self.assertNotIn("Past Outlook syncs", html)
        self.assertNotIn("Last Outlook sync", html)
        self.assertIn("Outlook: never synced", html)

    def test_label_counts_failed_jobs_not_missing_recon_rows(self):
        # statement_count (recon_summary rows) is 4 in self.result; the
        # sync's 5 jobs are 4 completed + 1 failed, none in flight.
        jobs = [{"submitted_at": U(2026, 9, 29, 12, 9), "statement_id": None, "status": "FAILED"},
                {"submitted_at": U(2026, 9, 29, 12, 8), "statement_id": "S1", "status": "COMPLETED"},
                {"submitted_at": U(2026, 9, 29, 12, 4), "statement_id": "S2", "status": "COMPLETED"},
                {"submitted_at": U(2026, 9, 29, 12, 1), "statement_id": "S3", "status": "COMPLETED"},
                {"submitted_at": U(2026, 9, 29, 11, 58), "statement_id": "S4", "status": "COMPLETED"}]
        with mock.patch("web.queries.get_outlook_synced_jobs", lambda: jobs):
            html = self._get("/")
        self.assertIn("Last sync · Sep 29, 8:09 AM ET · 5 statements (4 completed, 1 failed)", html)
        self.assertNotIn("still processing)", html)
        # "N of M reconciled" is unchanged -- still the recon_summary runs.
        self.assertIn("19 of 47 statements reconciled", html)

    def test_no_syncs_yet_wording(self):
        self.result["statement_count"] = 0  # an empty "last" window matches no runs
        with mock.patch("web.queries.get_outlook_synced_jobs", lambda: []):
            html = self._get("/")
        self.assertIn("<option disabled>No syncs yet</option>", html)
        self.assertIn("Last sync · no runs", html)
        self.assertNotIn("No Outlook syncs yet", html)

    def test_cards_use_the_window_sub_labels(self):
        html = self._get("/")
        self.assertIn("across 5 vendors · last run", html)
        self.assertIn("85.5% matched · last run", html)
        self.assertIn("needs review · last run", html)
        self.assertIn("19 of 47 statements reconciled", html)

    def test_date_alone_selects_that_day(self):
        html = self._get("/?date=2026-09-28")
        self.assertEqual((self._window().range, self._window().date), ("date", "2026-09-28"))
        self.assertIn('value="2026-09-28"', html)
        # No range chip is "active" (Last run/Today), and no dedicated
        # visual state on the calendar button itself (see home.html's
        # comment) -- the selected day is instead shown in the window
        # label under the chips.
        self.assertIn("Sep 28, 2026 · 4 statements", html)

    def test_month_alone_still_selects_that_month(self):
        # The Month select was removed 2026-10-01, but an old bookmarked
        # ?month= link still resolves (resolve_window() is unchanged) --
        # shown in the window label, with no control of its own.
        # month_options() itself is covered by
        # test_month_options_are_eastern_months_with_runs_newest_first.
        html = self._get("/?month=2026-09")
        self.assertEqual((self._window().range, self._window().month), ("month", "2026-09"))
        self.assertIn("September 2026 · 4 statements", html)
        self.assertNotIn('<select name="month"', html)

    def test_range_all_still_resolves_with_no_all_time_control(self):
        # The Month select's blank "All time" option (how range=all used
        # to be reached) was removed 2026-10-01; an old bookmarked
        # ?range=all link still resolves, shown in the window label.
        html = self._get("/?range=all")
        self.assertEqual(self._window().range, "all")
        self.assertIn("All time · 4 statements", html)
        self.assertNotIn(">All time</option>", html)
        self.assertNotIn('id="window-month"', html)

    def test_bad_params_fall_back_to_last_run(self):
        for url in ("/?range=bogus", "/?range=date&date=nope", "/?month=2026-99", "/?date=2026-02-30"):
            with self.subTest(url=url):
                self._get(url)
                self.assertEqual(self._window().range, "last")

    def test_only_last_run_and_today_are_chips(self):
        # "This month"/"All time" chips were removed 2026-09-30, and the
        # Month select (whose blank option was "All time") 2026-10-01 --
        # Today and Last run are the only chips, Today first.
        html = self._get("/")
        time_window = re.search(r'id="time-window".*?</div>', html, re.S).group(0)
        chip_labels = re.findall(r'class="filter-chip[^"]*">([^<]+)</a>', time_window)
        self.assertEqual(chip_labels, ["Today", "Last run"])

    def test_range_chips_keep_status_and_clear_period(self):
        html = self._get("/?range=date&date=2026-09-28&status=exceptions&period=2026-08")
        self.assertIn('href="/?status=exceptions" class="filter-chip ">Last run', html)
        self.assertIn('href="/?range=today&status=exceptions" class="filter-chip ">Today', html)

    def test_calendar_button_and_hidden_date_input(self):
        html = self._get("/?date=2026-09-28")
        self.assertIn('id="window-date-btn"', html)
        self.assertIn('<use href="#i-calendar"/>', html)
        self.assertIn('id="window-date" class="ns-sr-only"', html)
        self.assertIn('value="2026-09-28"', html)
        # No visible dd-mm-yyyy chip-styled box any more.
        self.assertNotIn('id="window-date" class="filter-chip', html)

    def test_date_and_month_forms_keep_status_not_period(self):
        html = self._get("/?range=all&status=reconciled&period=2026-08")
        for form in re.findall(r'<form method="get" action="/" style="display:contents">.*?</form>', html, re.S):
            self.assertIn('<input type="hidden" name="status" value="reconciled">', form)
            self.assertNotIn('name="period"', form)

    def test_status_chips_and_period_select_keep_the_window(self):
        html = self._get("/?range=date&date=2026-09-28&status=exceptions&period=2026-08")
        self.assertIn('href="/?range=date&date=2026-09-28&period=2026-08" class="filter-chip ">All', html)
        self.assertIn('href="/?range=date&date=2026-09-28&status=reconciled&period=2026-08" class="filter-chip ">Reconciled', html)
        runs_form = re.search(r'<form method="get" action="/" class="filter-chips"[^>]*id="runs-filters">.*?</form>', html, re.S).group(0)
        self.assertIn('<input type="hidden" name="range" value="date">', runs_form)
        self.assertIn('<input type="hidden" name="date" value="2026-09-28">', runs_form)
        self.assertIn('<input type="hidden" name="status" value="exceptions">', runs_form)

    def test_status_period_passed_through_with_window(self):
        self._get("/?range=month&month=2026-09&status=exceptions&period=2026-08")
        window, status, period = self.windows[-1]
        self.assertEqual((window.range, window.month, status, period), ("month", "2026-09", "exceptions", "2026-08"))

    def test_selected_period_missing_from_window_stays_selected(self):
        html = self._get("/?period=2026-01")
        self.assertIn('<option value="2026-01" selected>Jan 2026</option>', html)

    def test_empty_window_message_links_to_last_run(self):
        self.result = {**self.result, "runs": [], "total": 0, "reconciled": 0, "statement_count": 0,
                       "period_options": [],
                       "kpis": {"total_invoices": 0, "auto_reconciled": 0, "open_exceptions": 0,
                                "statement_total": 0, "vendor_count": 0, "match_rate": None}}
        html = self._get("/?range=today&status=exceptions")
        self.assertIn("No reconciliation runs today yet.", html)
        self.assertIn('<a href="/?status=exceptions" class="link">Last run</a>', html)
        # No "All time" link since 2026-10-01 (the All time option is gone).
        self.assertNotIn('class="link">All time</a>', html)
        self.assertIn("—% matched · today", html)
        self.assertIn("none open · today", html)
        self.assertRegex(html, r"Today · \w{3} \d{1,2} · no runs yet")

    def test_filtered_out_window_offers_clear_filters_that_keeps_the_window(self):
        self.result = {**self.result, "runs": [], "total": 0, "reconciled": 0}
        html = self._get("/?range=date&date=2026-09-28&status=exceptions&period=2026-07")
        self.assertIn('No reconciliation runs match these filters. <a href="/?range=date&date=2026-09-28" class="link">Clear filters</a>', html)

    def test_pending_review_line_is_not_window_scoped(self):
        html = self._get("/?range=date&date=2026-01-01")
        self.assertIn("3 rows pending review", html)


class TestHomeRouteSyncDropdown(unittest.TestCase):
    """The "Last run" dropdown (2026-09-30) -- web/routers/dashboard.py's
    sync_options/sync_truncated/selected_sync ctx values and home_url()'s
    ?sync= handling. Two real Outlook syncs in the fixture (unlike
    TestHomeRouteTimeWindow's single-sync fixture above), so a ?sync=
    selecting the OLDER one is actually observable."""

    def setUp(self):
        self.windows = []
        result = {
            "kpis": {"total_invoices": 0, "auto_reconciled": 0, "open_exceptions": 0,
                     "statement_total": 0, "vendor_count": 0, "match_rate": None},
            "runs": [], "total": 0, "reconciled": 0, "period_options": [], "statement_count": 0,
        }

        def get_home_dashboard(window=None, status="all", period=None, limit=10):
            self.windows.append(window)
            return result

        fns = {
            "get_run_timestamps": lambda: [],
            # Two syncs: newest (Sep 29, 2 jobs) and older (Sep 28, 1 job).
            "get_outlook_synced_jobs": lambda: [
                {"submitted_at": U(2026, 9, 29, 16, 2), "statement_id": "N1", "status": "COMPLETED"},
                {"submitted_at": U(2026, 9, 29, 15, 58), "statement_id": "N2", "status": "COMPLETED"},
                {"submitted_at": U(2026, 9, 28, 12, 0), "statement_id": "O1", "status": "COMPLETED"},
            ],
            "get_home_dashboard": get_home_dashboard,
            "get_active_jobs": lambda: [], "get_failed_jobs": lambda: [],
            "get_recent_completed_batches": lambda limit=3: [],
            "get_last_netsuite_sync": lambda: None, "get_last_outlook_sync": lambda: None,
            "get_open_recon_exceptions_count": lambda: 0, "get_pending_review_count": lambda: 0,
        }
        for name, fn in fns.items():
            patcher = mock.patch(f"web.queries.{name}", fn)
            patcher.start()
            self.addCleanup(patcher.stop)
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-secret")
        app.include_router(dashboard.router)
        app.dependency_overrides[require_login] = lambda: "tester"
        self.client = TestClient(app)

    def _get(self, url):
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        return resp.text.replace("&amp;", "&")

    def test_default_selects_the_latest_sync_with_no_sync_param_in_the_url(self):
        html = self._get("/")
        self.assertEqual(self.windows[-1].statement_ids, frozenset({"N1", "N2"}))
        select = re.search(r'<select name="sync".*?</select>', html, re.S).group(0)
        # Custom picker (2026-10-01): "None" (= the Last run chip) comes
        # first, but the hidden control still pre-selects the newest sync.
        options = re.findall(r'<option value="([^"]*)"[^>]*>([^<]*)</option>', select)
        self.assertEqual(options[0], ("", "None"))
        self.assertIn('value="2026-09-29T16:02:00Z" selected', select)
        self.assertIn("Sep 29, 12:02 PM ET · 2 statements", select)
        self.assertIn("Sep 28, 8:00 AM ET · 1 statement", select)
        # No explicit ?sync=, so Last run is the highlighted control and the
        # picker's button is not.
        self.assertIn('href="/" class="filter-chip active">Last run', html)
        self.assertRegex(html, r'class="filter-chip sync-picker-btn\s*" id="window-sync-btn"')

    def test_choosing_an_older_sync_narrows_the_window(self):
        html = self._get("/?sync=2026-09-28T12:00:00Z")
        self.assertEqual(self.windows[-1].statement_ids, frozenset({"O1"}))
        select = re.search(r'<select name="sync".*?</select>', html, re.S).group(0)
        self.assertIn('value="2026-09-28T12:00:00Z" selected', select)

    def test_choosing_today_clears_sync(self):
        html = self._get("/?sync=2026-09-28T12:00:00Z")
        self.assertIn('href="/?range=today"', html)

    def test_malformed_sync_falls_back_to_latest(self):
        self._get("/?sync=garbage")
        self.assertEqual(self.windows[-1].statement_ids, frozenset({"N1", "N2"}))


if __name__ == "__main__":
    unittest.main()
