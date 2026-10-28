"""
tests/test_job_recovery.py

Restart recovery for jobs (2026-10-26; design: backups/fix_f1_20261025/restart_recovery_4d.md). On dev
on Oct 25 two Fred Beans jobs died with their host and were only noticed by the 40-minute rule, Berlin
City and NYE 9-4-26 were killed by the 30-minute cap after a paid AI call, and a late write from the
old host could overwrite a newer attempt. With VIVE_JOB_RECOVERY_ENABLED=true:

- a claim records its owner (claimed_by), a heartbeat (heartbeat_at) and the attempt number;
- the worker beats every HEARTBEAT_SECONDS while the pipeline runs;
- a PROCESSING job whose heartbeat is older than HEARTBEAT_STALE_MINUTES, or that hit the 30-minute
  cap, is retried -- at most JOB_MAX_ATTEMPTS (2) attempts in all -- and every attempt's reason is
  kept in attempt_log; after the cap it ends FAILED with a plain last line (never silent);
- every final write from the worker is guarded by the claim, so a late write from an old attempt
  never overwrites a newer one.

Switched off (the default), nothing changes. SQLite in memory, the real migrations, a fake clock and
stand-in pipelines only: no database server, network or AI.
"""

import os
import sqlite3
import subprocess
import sys
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.lakehouse.migrations import apply_pending_migrations
from web import queries, worker

T0 = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


class _Db(unittest.TestCase):
    ENABLED = "true"

    def setUp(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        apply_pending_migrations(conn)
        self.conn = conn
        self.lock = threading.Lock()
        self.now = [T0]

        def execute_sql(sql, params=None):
            with self.lock:
                cur = conn.execute(sql, params or [])
                conn.commit()
                return cur

        def execute_query(sql, params=None):
            with self.lock:
                return [dict(r) for r in conn.execute(sql, params or []).fetchall()]
        for target, value in (("web.queries.execute_sql", execute_sql), ("web.queries.execute_query", execute_query),
                              ("web.queries._utcnow", lambda: self.now[0])):
            p = mock.patch(target, value)
            p.start()
            self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ, {"VIVE_JOB_RECOVERY_ENABLED": self.ENABLED})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(conn.close)

    def add_job(self, job_id="J1", filename="a.pdf"):
        queries.create_job(job_id, filename, os.path.abspath(__file__), "tester")

    def job(self, job_id="J1"):
        return queries.get_job_by_id(job_id)

    def tick(self, minutes):
        self.now[0] += timedelta(minutes=minutes)


class TestClaimAndHeartbeat(_Db):

    def test_a_claim_records_owner_heartbeat_and_attempt(self):
        self.add_job()
        job = queries.claim_next_pending_job(worker_id="host-A")
        self.assertEqual((job["status"], job["claimed_by"], job["heartbeat_at"], job["attempts"]),
                         ("PROCESSING", "host-A", T0.isoformat(), 1))

    def test_a_beating_job_is_never_requeued(self):
        self.add_job()
        job = queries.claim_next_pending_job(worker_id="host-A")
        for _ in range(6):
            self.tick(4)
            self.assertTrue(queries.heartbeat_job("J1", job["claim_token"]))
            self.assertEqual(queries.requeue_stale_processing_jobs(), 0)
        self.assertEqual(self.job()["status"], "PROCESSING")

    def test_two_workers_never_run_the_same_job(self):
        self.add_job()
        barrier, got = threading.Barrier(2), []

        def claim(name):
            barrier.wait()
            got.append(queries.claim_next_pending_job(worker_id=name))
        threads = [threading.Thread(target=claim, args=(n,)) for n in ("host-A", "host-B")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(j is None for j in got), [False, True])
        # ...and while its owner beats, nobody else gets it.
        owner = next(j for j in got if j)
        self.tick(4)
        queries.heartbeat_job("J1", owner["claim_token"])
        self.tick(3)
        self.assertEqual(queries.requeue_stale_processing_jobs(), 0)
        self.assertIsNone(queries.claim_next_pending_job(worker_id="host-C"))


class TestStalls(_Db):

    def test_stall_then_retry_then_success(self):
        self.add_job()
        first = queries.claim_next_pending_job(worker_id="host-A")
        self.tick(6)                                   # host A died: no heartbeat for 6 minutes
        self.assertEqual(queries.requeue_stale_processing_jobs(), 1)
        job = self.job()
        self.assertEqual((job["status"], job["claim_token"], job["attempts"]), ("PENDING", None, 1))
        self.assertIn("attempt 1: stalled", job["attempt_log"])
        self.assertIn("host-A", job["attempt_log"])
        second = queries.claim_next_pending_job(worker_id="host-B")
        self.assertEqual((second["attempts"], second["claimed_by"]), (2, "host-B"))
        self.assertTrue(queries.update_job_status("J1", status="COMPLETED", completed_at=T0.isoformat(),
                                                  statement_id="STMT-1", claim_token=second["claim_token"]))
        # The old host comes back and writes its outcome late: refused, the newer attempt stands.
        self.assertFalse(queries.update_job_status("J1", status="FAILED", error_message="late",
                                                   claim_token=first["claim_token"]))
        job = self.job()
        self.assertEqual((job["status"], job["statement_id"]), ("COMPLETED", "STMT-1"))
        self.assertIn("attempt 1: stalled", job["attempt_log"])

    def test_the_attempt_cap_ends_failed_with_every_reason(self):
        self.add_job()
        queries.claim_next_pending_job(worker_id="host-A")
        self.tick(6)
        queries.requeue_stale_processing_jobs()
        queries.claim_next_pending_job(worker_id="host-B")
        self.tick(6)
        self.assertEqual(queries.requeue_stale_processing_jobs(), 1)
        job = self.job()
        self.assertEqual(job["status"], "FAILED")
        self.assertIsNotNone(job["completed_at"])
        lines = job["error_message"].strip().splitlines()
        self.assertTrue(any("attempt 1: stalled" in l and "host-A" in l for l in lines))
        self.assertTrue(any("attempt 2: stalled" in l and "host-B" in l for l in lines))
        self.assertTrue(lines[-1].startswith("Stalled host: abandoned after 2 attempts"), lines[-1])
        self.assertIsNone(queries.claim_next_pending_job(worker_id="host-C"))   # never silently retried again

    def test_a_job_claimed_before_the_switch_keeps_the_40_minute_rule(self):
        self.add_job()
        self.conn.execute("UPDATE jobs SET status='PROCESSING', started_at=?, claim_token='old' WHERE job_id='J1'",
                          [(T0 - timedelta(minutes=30)).isoformat()])
        self.assertEqual(queries.requeue_stale_processing_jobs(), 0)
        self.tick(11)
        self.assertEqual(queries.requeue_stale_processing_jobs(), 1)
        self.assertEqual(self.job()["status"], "PENDING")


class _FakeTimeout:
    """subprocess.run stand-in: the pipeline is stopped by the cap after printing its step lines."""

    def __init__(self, steps):
        self.steps = steps

    def __call__(self, *a, **k):
        out = "\n".join(f"    Step timing: {s}" for s in self.steps).encode()
        raise subprocess.TimeoutExpired(cmd=["pipeline"], timeout=1800, output=out, stderr=b"")


class TestWorkerWithRecovery(_Db):

    def run_job(self, job, run):
        with mock.patch("web.worker.subprocess.run", run), mock.patch.object(worker, "_write_blob_outcome") as outcome, \
                mock.patch.object(worker, "_restore_missing_pdf"), mock.patch("builtins.print"):
            worker._run_job(job)
        return outcome

    def test_the_30_minute_cap_is_retried_then_ends_failed_with_both_reasons(self):
        self.add_job()
        outcome = self.run_job(queries.claim_next_pending_job(worker_id="host-A"),
                               _FakeTimeout(["pdf_text=1.0s", "ai_call=300.0s"]))
        job = self.job()
        self.assertEqual(job["status"], "PENDING")
        self.assertIn("attempt 1: hit the 30-minute cap (last step finished: ai_call)", job["attempt_log"])
        outcome.assert_not_called()                     # the mailbox blob is not marked failed: it is being retried
        outcome = self.run_job(queries.claim_next_pending_job(worker_id="host-B"), _FakeTimeout(["pdf_text=1.0s"]))
        job = self.job()
        self.assertEqual(job["status"], "FAILED")
        last = job["error_message"].strip().splitlines()[-1]
        self.assertTrue(last.startswith("Timed out: stopped at the 30-minute cap on 2 attempts"), last)
        self.assertIn("attempt 2: hit the 30-minute cap (last step finished: pdf_text)", job["error_message"])
        self.assertEqual(outcome.call_args.args[1], "failed")

    def test_the_worker_beats_while_the_pipeline_runs(self):
        self.add_job()
        job = queries.claim_next_pending_job(worker_id="host-A")
        beats = []
        real = queries.heartbeat_job

        def counting(job_id, token):
            beats.append(job_id)
            return real(job_id, token)

        def slow_pipeline(*a, **k):
            time.sleep(1.2)
            k["stdout"].write(b"Statement ID: STMT-9\n")
            return subprocess.CompletedProcess(args=[], returncode=0, stdout=None, stderr="")
        with mock.patch.object(queries, "HEARTBEAT_SECONDS", 0.2), mock.patch.object(queries, "heartbeat_job", counting), \
                mock.patch("web.queries.get_silver_row_count", return_value=4), \
                mock.patch("web.queries.get_vendor_name_for_statement", return_value="V"):
            self.run_job(job, slow_pipeline)
        self.assertGreaterEqual(len(beats), 3)
        self.assertEqual(self.job()["status"], "COMPLETED")

    def test_a_restart_mid_job_then_the_old_hosts_late_outcome_is_ignored(self):
        self.add_job()
        old = queries.claim_next_pending_job(worker_id="host-A")   # host A starts, then its container restarts
        self.tick(6)
        queries.requeue_stale_processing_jobs()
        new = queries.claim_next_pending_job(worker_id="host-B")
        done = lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=0, stdout="Statement ID: STMT-7\n", stderr="")
        with mock.patch("web.queries.get_silver_row_count", return_value=3), \
                mock.patch("web.queries.get_vendor_name_for_statement", return_value="V"):
            self.run_job(new, done)
            outcome = self.run_job(old, lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=1, stdout="boom",
                                                                                     stderr=""))
        job = self.job()
        self.assertEqual((job["status"], job["statement_id"]), ("COMPLETED", "STMT-7"))
        outcome.assert_not_called()   # the stale attempt writes nothing, not even the blob outcome


class TestSwitchedOff(_Db):
    ENABLED = "false"

    def test_nothing_changes_when_switched_off(self):
        self.add_job()
        job = queries.claim_next_pending_job()
        self.assertEqual((job["claimed_by"], job["heartbeat_at"], job["attempts"]), (None, None, 0))
        self.tick(6)
        self.assertEqual(queries.requeue_stale_processing_jobs(), 0)   # the 40-minute rule on started_at only
        queries.update_job_status("J1", status="COMPLETED", claim_token="someone-else")
        self.assertEqual(self.job()["status"], "COMPLETED")             # no claim guard


if __name__ == "__main__":
    unittest.main()
