"""
tests/test_deps_friendly_dt.py

Tests for web/deps.py's friendly_dt() Jinja filter, which renders every
stored-UTC timestamp in the app as US Eastern (America/New_York).

The zone is deliberately DST-aware rather than a fixed UTC-5 offset --
the summer/winter pair below is the regression guard for that: a fixed
offset passes the January case and fails the July one.

Every test injects `now` rather than reading the wall clock, so the
"Today" boundary case is deterministic regardless of when the suite runs
or what timezone the machine running it is set to.
"""

import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web.deps import friendly_dt


class TestFriendlyDtZoneConversion(unittest.TestCase):

    # A fixed "now" far from every timestamp under test, so nothing here
    # accidentally lands on the "Today" branch -- that boundary gets its
    # own test below.
    NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)

    def test_summer_timestamp_converts_to_edt_utc_minus_4(self):
        """2026-07-15 is inside DST, so Eastern is UTC-4: 18:00Z -> 2:00 PM."""
        self.assertEqual(
            friendly_dt("2026-07-15T18:00:00+00:00", now=self.NOW),
            "Jul 15, 2026, 2:00 PM ET",
        )

    def test_winter_timestamp_converts_to_est_utc_minus_5(self):
        """2026-01-15 is outside DST, so Eastern is UTC-5: 18:00Z -> 1:00 PM.

        Paired with the summer case above, this is what a fixed UTC-5
        offset could not satisfy -- it would render the July timestamp as
        1:00 PM too.
        """
        self.assertEqual(
            friendly_dt("2026-01-15T18:00:00+00:00", now=self.NOW),
            "Jan 15, 2026, 1:00 PM ET",
        )

    def test_naive_datetime_object_is_treated_as_utc(self):
        """Fabric/Azure SQL DATETIME2 columns come back as naive datetime
        objects (confirmed live against silver.recon_exceptions.date_raised)
        -- these must be read as UTC, not as machine-local time."""
        self.assertEqual(
            friendly_dt(datetime(2026, 7, 15, 18, 0), now=self.NOW),
            "Jul 15, 2026, 2:00 PM ET",
        )

    def test_aware_datetime_object_is_converted_not_relabelled(self):
        self.assertEqual(
            friendly_dt(datetime(2026, 7, 15, 18, 0, tzinfo=timezone.utc), now=self.NOW),
            "Jul 15, 2026, 2:00 PM ET",
        )

    def test_iso_string_with_z_suffix_parses(self):
        """datetime.fromisoformat() rejects a bare "Z" on Python 3.10 and
        below and accepts it on 3.11+; friendly_dt() normalizes it either
        way, so this stays pinned regardless of runtime."""
        self.assertEqual(
            friendly_dt("2026-07-15T18:00:00Z", now=self.NOW),
            "Jul 15, 2026, 2:00 PM ET",
        )

    def test_midnight_utc_renders_as_12_hour_clock_not_zero(self):
        """00:30Z in July is 8:30 PM the PREVIOUS Eastern day -- guards both
        the hour % 12 or 12 wrap and the date rolling backwards."""
        self.assertEqual(
            friendly_dt("2026-07-16T00:30:00+00:00", now=self.NOW),
            "Jul 15, 2026, 8:30 PM ET",
        )


class TestFriendlyDtTodayBoundary(unittest.TestCase):
    """The "Today" branch compares calendar dates in Eastern, so a
    timestamp can be "today" in UTC and still render as yesterday's date.
    """

    def test_early_morning_utc_is_previous_day_in_eastern(self):
        """02:00Z on Jul 16 is 10:00 PM Jul 15 in Eastern (UTC-4). With
        "now" at 14:00Z on Jul 16 (10:00 AM ET, still Jul 16), the two
        fall on different Eastern dates -- so this must render as an
        explicit Jul 15 date, NOT "Today"."""
        self.assertEqual(
            friendly_dt(
                "2026-07-16T02:00:00+00:00",
                now=datetime(2026, 7, 16, 14, 0, tzinfo=timezone.utc),
            ),
            "Jul 15, 2026, 10:00 PM ET",
        )

    def test_same_eastern_day_renders_as_today(self):
        self.assertEqual(
            friendly_dt(
                "2026-07-16T13:00:00+00:00",
                now=datetime(2026, 7, 16, 14, 0, tzinfo=timezone.utc),
            ),
            "Today, 9:00 AM ET",
        )

    def test_naive_now_is_also_treated_as_utc(self):
        """Callers passing an injected naive "now" get the same UTC
        assumption the timestamp argument gets -- otherwise the two sides
        of the date comparison would be in different zones."""
        self.assertEqual(
            friendly_dt("2026-07-16T13:00:00+00:00", now=datetime(2026, 7, 16, 14, 0)),
            "Today, 9:00 AM ET",
        )


class TestFriendlyDtFallbacks(unittest.TestCase):

    def test_none_returns_em_dash(self):
        self.assertEqual(friendly_dt(None), "—")

    def test_empty_string_returns_em_dash(self):
        self.assertEqual(friendly_dt(""), "—")

    def test_unparseable_value_is_returned_verbatim(self):
        """Never raise out of a template filter -- an unrecognised value
        is shown as-is rather than blanking the page."""
        self.assertEqual(friendly_dt("not a timestamp"), "not a timestamp")


if __name__ == "__main__":
    unittest.main()
