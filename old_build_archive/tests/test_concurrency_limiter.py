"""
tests/test_concurrency_limiter.py

Tests for src/ai/concurrency_limiter.py's cross-process AI-call slot
semaphore. Uses a temp directory for SLOT_DIR so tests never touch the
real lakehouse/ai_call_slots/ and never leak lock files between runs.
"""

import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.ai import concurrency_limiter as cl


class TestConcurrencyLimiter(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self._real_slot_dir = cl.SLOT_DIR
        cl.SLOT_DIR = self.tmp_dir
        self._real_env = os.environ.get("VIVE_MAX_CONCURRENT_AI_CALLS")

    def tearDown(self):
        cl.SLOT_DIR = self._real_slot_dir
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        if self._real_env is None:
            os.environ.pop("VIVE_MAX_CONCURRENT_AI_CALLS", None)
        else:
            os.environ["VIVE_MAX_CONCURRENT_AI_CALLS"] = self._real_env

    def test_max_concurrent_defaults_to_two(self):
        os.environ.pop("VIVE_MAX_CONCURRENT_AI_CALLS", None)
        self.assertEqual(cl._max_concurrent(), 2)

    def test_max_concurrent_reads_env_var(self):
        os.environ["VIVE_MAX_CONCURRENT_AI_CALLS"] = "5"
        self.assertEqual(cl._max_concurrent(), 5)

    def test_acquires_distinct_slots_up_to_the_limit(self):
        first = cl._try_acquire_slot(2)
        second = cl._try_acquire_slot(2)

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first, second)

    def test_returns_none_once_all_slots_are_held(self):
        cl._try_acquire_slot(2)
        cl._try_acquire_slot(2)

        third = cl._try_acquire_slot(2)

        self.assertIsNone(third)

    def test_slot_becomes_available_again_after_release(self):
        held = cl._try_acquire_slot(1)
        self.assertIsNone(cl._try_acquire_slot(1))

        os.remove(held)

        self.assertIsNotNone(cl._try_acquire_slot(1))

    def test_ai_call_slot_context_manager_releases_the_slot_on_success(self):
        os.environ["VIVE_MAX_CONCURRENT_AI_CALLS"] = "1"

        with cl.ai_call_slot():
            self.assertEqual(len(os.listdir(self.tmp_dir)), 1)

        self.assertEqual(os.listdir(self.tmp_dir), [])

    def test_ai_call_slot_context_manager_releases_the_slot_on_exception(self):
        os.environ["VIVE_MAX_CONCURRENT_AI_CALLS"] = "1"

        with self.assertRaises(ValueError):
            with cl.ai_call_slot():
                raise ValueError("simulated failure inside the AI call")

        self.assertEqual(os.listdir(self.tmp_dir), [])

    def test_ai_call_slot_blocks_a_second_caller_until_the_first_releases(self):
        os.environ["VIVE_MAX_CONCURRENT_AI_CALLS"] = "1"
        cl.POLL_INTERVAL_SECONDS = 0.05

        acquired_second_at = {}
        released_first_at = {}

        def hold_then_release():
            with cl.ai_call_slot():
                time.sleep(0.3)
                released_first_at["t"] = time.monotonic()

        def try_acquire_second():
            start = time.monotonic()
            with cl.ai_call_slot():
                acquired_second_at["t"] = time.monotonic()

        t1 = threading.Thread(target=hold_then_release)
        t1.start()
        time.sleep(0.05)  # let t1 acquire first
        t2 = threading.Thread(target=try_acquire_second)
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        self.assertIn("t", released_first_at)
        self.assertIn("t", acquired_second_at)
        self.assertGreaterEqual(acquired_second_at["t"], released_first_at["t"])


if __name__ == "__main__":
    unittest.main()
