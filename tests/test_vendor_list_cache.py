"""
tests/test_vendor_list_cache.py

Shared vendor-list cache (2026-11-13, src/matching/netsuite_vendor_resolver.py):
the active-vendor list is fetched at most once per NETSUITE_VENDOR_CACHE_SECONDS
(default 30 min) and shared by every lookup; first-word name searches run on
that copy; a lookup that resolves nothing refreshes the list once (a vendor
created in NetSuite since the last fetch); a failed refresh keeps the old copy.
"""

import os
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.matching import netsuite_vendor_resolver as resolver

ROWS = [("1", "Gates GMC Nissan", "Gates GMC Nissan", None),
        ("2", None, "Quirk Subaru of Bangor", "Quirk Subaru"),
        ("3", "QUIRK CHEVROLET", None, None)]


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class VendorListCacheTests(unittest.TestCase):

    def setUp(self):
        resolver.reset_vendor_cache()
        self.addCleanup(resolver.reset_vendor_cache)
        self.clock = _Clock()
        patches = [mock.patch.object(resolver, "_clock", self.clock),
                   mock.patch.object(resolver, "_load_overrides", return_value={}),
                   mock.patch.dict(os.environ, {"NETSUITE_VENDOR_CACHE_SECONDS": ""})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.rows = list(ROWS)
        self.fetch = mock.patch.object(resolver, "_fetch_active_vendor_rows",
                                       side_effect=lambda: (list(self.rows), "fabric")).start()
        self.addCleanup(mock.patch.stopall)

    def test_fetched_once_and_shared_within_30_minutes(self):
        self.assertEqual(resolver.resolve_entity_ids("V1", "Gates GMC Nissan"), ["1"])
        self.clock.now += 29 * 60
        self.assertEqual(resolver.resolve_entity_ids("V2", "Quirk Subaru of Bangor"), ["2"])
        self.assertEqual(resolver._first_word_like_lookup("Quirk Auto Group"), ["2", "3"])
        self.assertEqual(self.fetch.call_count, 1)

    def test_refetched_after_30_minutes(self):
        resolver._active_vendor_rows()
        self.clock.now += 30 * 60 + 1
        resolver._active_vendor_rows()
        self.assertEqual(self.fetch.call_count, 2)

    def test_first_word_search_matches_any_name_column_case_insensitively(self):
        self.assertEqual(resolver._active_vendor_ids_like("%quirk%"), ["2", "3"])
        self.assertEqual(resolver._active_vendor_ids_like("%gates%"), ["1"])
        self.assertEqual(resolver._active_vendor_ids_like("%nomatch%"), [])

    def test_a_new_vendor_is_found_by_one_refresh_on_a_miss(self):
        resolver._active_vendor_rows()
        self.rows.append(("9", "Brand New Motors", None, None))  # created in NetSuite meanwhile
        self.clock.now += 5 * 60
        self.assertEqual(resolver.resolve_entity_ids("V9", "Brand New Motors"), ["9"])
        self.assertEqual(self.fetch.call_count, 2)

    def test_a_name_that_never_resolves_refreshes_at_most_once_a_minute(self):
        resolver._active_vendor_rows()
        self.clock.now += 120
        self.assertIsNone(resolver.resolve_entity_ids("VX", "Zz Unknown"))
        self.assertIsNone(resolver.resolve_entity_ids("VX", "Zz Unknown"))
        self.assertEqual(self.fetch.call_count, 2)  # first fetch + one refresh, not one per call

    def test_a_failed_refresh_keeps_the_old_copy(self):
        resolver._active_vendor_rows()
        self.clock.now += 31 * 60
        self.fetch.side_effect = RuntimeError("NetSuite down")
        self.assertEqual(resolver.resolve_entity_ids("V1", "Gates GMC Nissan"), ["1"])

    def test_no_copy_and_a_failed_fetch_resolves_nothing(self):
        self.fetch.side_effect = RuntimeError("NetSuite down")
        self.assertIsNone(resolver.resolve_entity_ids("V1", "Gates GMC Nissan"))

    def test_overrides_still_win_without_reading_the_list(self):
        with mock.patch.object(resolver, "_load_overrides", return_value={"V1": {"entity_ids": ["77", "78"]}}):
            self.assertEqual(resolver.resolve_entity_ids("V1", "Gates GMC Nissan"), ["77", "78"])
        self.fetch.assert_not_called()

    def test_background_refresh_keeps_the_list_fresh(self):
        refreshed = threading.Event()
        calls = []

        def fake_rows(force_refresh=False):
            calls.append(force_refresh)
            if len(calls) >= 2:
                refreshed.set()
            return []
        with mock.patch.object(resolver, "_active_vendor_rows", side_effect=fake_rows):
            resolver.stop_background_refresh()
            resolver.start_background_refresh(interval_seconds=0.05)
            resolver.start_background_refresh(interval_seconds=0.05)  # idempotent
            self.assertTrue(refreshed.wait(5))
            resolver.stop_background_refresh()  # stopped before the mock goes away
        self.assertTrue(all(calls))  # always a forced refresh

    def test_many_threads_at_once_fetch_once(self):
        started = threading.Event()

        def slow_fetch():
            started.set()
            return list(self.rows), "fabric"
        self.fetch.side_effect = slow_fetch
        results = []
        threads = [threading.Thread(target=lambda: results.append(resolver._dynamic_lookup("Gates GMC Nissan")))
                   for _ in range(15)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results, [["1"]] * 15)
        self.assertEqual(self.fetch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
