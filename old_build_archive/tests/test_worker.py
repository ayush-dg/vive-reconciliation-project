"""
tests/test_worker.py

Tests for web/worker.py's parallel worker pool -- pool sizing from
VIVE_WORKER_POOL_SIZE, and that stop_workers() waits for in-flight jobs
before returning rather than killing them mid-pipeline. No real
subprocess/pipeline calls are made -- queries.claim_next_pending_job and
_run_job are monkeypatched.
"""

import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web import worker


class TestPoolSize(unittest.TestCase):

    def setUp(self):
        self._real_env = os.environ.get("VIVE_WORKER_POOL_SIZE")

    def tearDown(self):
        if self._real_env is None:
            os.environ.pop("VIVE_WORKER_POOL_SIZE", None)
        else:
            os.environ["VIVE_WORKER_POOL_SIZE"] = self._real_env

    def test_defaults_to_three(self):
        os.environ.pop("VIVE_WORKER_POOL_SIZE", None)
        self.assertEqual(worker._pool_size(), 3)

    def test_reads_env_var(self):
        os.environ["VIVE_WORKER_POOL_SIZE"] = "5"
        self.assertEqual(worker._pool_size(), 5)


class TestWorkerPoolStartStop(unittest.TestCase):
    """Drives the pool directly (not via the start_worker()/stop_workers()
    process-wide singletons, which only start once per process) so each
    test gets its own independent set of threads."""

    def setUp(self):
        worker._shutdown_event.clear()
        self.claim_calls = []
        self.release_job = threading.Event()
        self.job_started = threading.Event()

        def fake_claim():
            self.claim_calls.append(1)
            if len(self.claim_calls) == 1:
                return {"job_id": "job-1", "pdf_filename": "a.pdf", "pdf_path": "sample_data/a.pdf"}
            return None

        def fake_run_job(job):
            self.job_started.set()
            self.release_job.wait(timeout=5)

        patcher1 = mock.patch("web.queries.claim_next_pending_job", side_effect=fake_claim)
        patcher2 = mock.patch("web.worker._run_job", side_effect=fake_run_job)
        patcher1.start()
        patcher2.start()
        self.addCleanup(patcher1.stop)
        self.addCleanup(patcher2.stop)

        self._real_poll_interval = worker.POLL_INTERVAL_SECONDS
        worker.POLL_INTERVAL_SECONDS = 0.05

    def tearDown(self):
        worker.POLL_INTERVAL_SECONDS = self._real_poll_interval
        worker._shutdown_event.set()
        self.release_job.set()

    def _start_pool(self, size):
        threads = []
        for i in range(size):
            t = threading.Thread(target=worker._worker_loop, args=(f"test-worker-{i}",), daemon=True)
            t.start()
            threads.append(t)
        return threads

    def test_stop_workers_waits_for_in_flight_job_before_returning(self):
        threads = self._start_pool(1)
        self.assertTrue(self.job_started.wait(timeout=2), "job never started")

        worker._shutdown_event.set()

        # The thread must still be alive -- fake_run_job is blocked on
        # release_job, so the loop can't have exited yet even though
        # shutdown was requested.
        time.sleep(0.1)
        self.assertTrue(threads[0].is_alive())

        self.release_job.set()
        threads[0].join(timeout=2)
        self.assertFalse(threads[0].is_alive())

    def test_stop_workers_is_a_no_op_when_pool_never_started(self):
        worker._worker_threads.clear()
        worker.stop_workers()  # must not raise


if __name__ == "__main__":
    unittest.main()
