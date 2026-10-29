"""
tests/test_exceptions_writeback_status.py

The small NetSuite write-back status in the top-right of a statement's
exception review page (web/netsuite_status.py, the pill in
exceptions_review.html, and _writeback_status() in web/routers/exceptions.py).
Green when it all went through, amber when part was blocked, red on a failure,
grey when nothing was written, absent when the statement has no run. Uses a
throwaway SQLite file for the end-to-end check; nothing touches Azure,
Fabric or NetSuite.
"""

import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
from decimal import Decimal
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.lakehouse import connection
from src.lakehouse.migrations import apply_pending_migrations
from src.netsuite import log_store
from src.netsuite import writeback as wb
from web import netsuite_status
from web.deps import templates
from web.routers import exceptions
from web.routers.exceptions import REASON_BADGE, SEARCHABLE_REASONS

FINISHED = "2026-10-19T14:38:08+00:00"


def _run(**overrides):
    run = {"outcome": "completed", "written": 24, "failed": 0, "period_locked": 0, "held_by_other": 0,
           "not_written": 0, "not_written_counts": "{}", "finished_at": FINISHED, "error_message": None}
    run.update(overrides)
    return run


class PillRulesTests(unittest.TestCase):
    def test_no_run_means_no_pill(self):
        self.assertIsNone(netsuite_status.writeback_pill(None))

    def test_everything_written_is_green(self):
        pill = netsuite_status.writeback_pill(_run())
        self.assertEqual((pill["css"], pill["label"], pill["ok"]), ("badge-success", "NetSuite write-back", True))

    def test_lines_skipped_by_design_do_not_turn_a_clean_run_amber(self):
        pill = netsuite_status.writeback_pill(_run(not_written=9, not_written_counts='{"not in sandbox": 9}'))
        self.assertEqual(pill["css"], "badge-success")
        self.assertIn("not written: 9 not in NetSuite", pill["tooltip"])
        self.assertTrue(pill["tooltip"].startswith("Whole statement: "))

    def test_a_locked_period_makes_it_amber(self):
        pill = netsuite_status.writeback_pill(_run(period_locked=18))
        self.assertEqual((pill["css"], pill["label"], pill["ok"]), ("badge-warning", "NetSuite write-back · partial", False))
        self.assertIn("18 period locked", pill["tooltip"])

    def test_a_bill_another_statement_saved_first_makes_it_amber(self):
        self.assertEqual(netsuite_status.writeback_pill(_run(held_by_other=2))["css"], "badge-warning")

    def test_nothing_written_because_everything_was_blocked_is_amber(self):
        pill = netsuite_status.writeback_pill(_run(written=0, period_locked=5))
        self.assertEqual((pill["css"], pill["label"]), ("badge-warning", "NetSuite write-back · not written"))

    def test_a_failed_write_is_red_even_if_others_went_through(self):
        pill = netsuite_status.writeback_pill(_run(failed=3, period_locked=1))
        self.assertEqual((pill["css"], pill["label"], pill["ok"]), ("badge-danger", "NetSuite write-back · failed", False))

    def test_a_run_that_failed_as_a_whole_is_red_and_shows_the_error(self):
        pill = netsuite_status.writeback_pill(_run(outcome="failed", written=0,
                                                   error_message="RuntimeError: boom\nmore"))
        self.assertEqual((pill["css"], pill["label"]), ("badge-danger", "NetSuite write-back · failed"))
        self.assertEqual(pill["tooltip"], "RuntimeError: boom")

    def test_nothing_to_write_is_grey(self):
        pill = netsuite_status.writeback_pill(_run(written=0, not_written=2,
                                                   not_written_counts='{"already up to date": 2}'))
        self.assertEqual((pill["css"], pill["label"]), ("badge-neutral", "NetSuite write-back · nothing to write"))

    def test_broken_counts_json_does_not_break_the_pill(self):
        self.assertEqual(netsuite_status.writeback_pill(_run(not_written_counts="{not json"))["css"], "badge-success")


def _render(writeback=None, **extra):
    ctx = dict(
        active_page="exceptions", vendor_name="Columbia Ford", vendor_display_name="Columbia Ford",
        vendor_url_name="Columbia%20Ford", not_found=False, statement={"statement_id": "STMT-TEST"},
        exceptions=[], selected=None, total=12, resolved=0, progress_pct=0, filter="all",
        reason_badge=REASON_BADGE, high_confidence_count=0, bulk_approve_threshold=0.99,
        netsuite_record=None, searchable_reasons=SEARCHABLE_REASONS, open_exception_count=12, user="tester",
    )
    if writeback is not None:
        ctx["writeback"] = writeback
    ctx.update(extra)
    return templates.get_template("exceptions_review.html").render(**ctx)


def _topbar(html):
    return re.search(r'<div class="topbar-actions">.*?</div>', html, re.S).group(0)


def _box_head(html):
    """The header row of the exception box: title, badges, up to the Raised line."""
    return re.search(r'<div class="detail-view-head">.*?<div class="detail-view-sub">', html, re.S).group(0)


SELECTED = {
    "exception_id": "exc-1", "statement_id": "STMT-TEST", "invoice_number": "15116460",
    "vendor_id": "BMW_OF_NORTH_HAVEN", "statement_amount": 36.80, "erp_amount": None,
    "exception_reason": "Not Found in NetSuite", "exception_status": "OPEN",
    "date_raised": "2026-10-16T10:51:00+00:00", "days_open": 2, "match_confidence": None,
    "escalation_status": None, "invoice_date": None, "ro_number": None,
}


class PillPlacementTests(unittest.TestCase):
    """The status lives in the top bar, not inside the exception box: a pill
    beside one invoice's own badges read as if it described that invoice."""

    def _page(self, run=None, **extra):
        return _render(netsuite_status.writeback_pill(run if run is not None else _run()), selected=SELECTED, **extra)

    def test_with_an_exception_open_the_pill_is_in_the_top_bar(self):
        self.assertIn("NetSuite write-back", _topbar(self._page()))

    def test_it_is_not_inside_the_exception_box(self):
        self.assertNotIn("NetSuite write-back", _box_head(self._page()))
        self.assertEqual(self._page().count("NetSuite write-back"), 1)

    def test_the_label_carries_no_number(self):
        for run in (_run(), _run(period_locked=3), _run(failed=2), _run(written=0)):
            with self.subTest(run=run):
                label = netsuite_status.writeback_pill(run)["label"]
                self.assertFalse(re.search(r"\d", label), label)


class PageRenderTests(unittest.TestCase):
    """With no open exception there is no box, so the status stays in the top bar."""

    def test_a_successful_write_back_shows_a_green_pill_in_the_top_right(self):
        bar = _topbar(_render(netsuite_status.writeback_pill(_run())))
        self.assertIn("badge-success", bar)
        self.assertIn("NetSuite write-back", bar)
        self.assertIn("#i-check-circle", bar)
        self.assertIn("12 exceptions", bar)            # the existing count is still there

    def test_the_pill_sits_before_the_exception_count(self):
        bar = _topbar(_render(netsuite_status.writeback_pill(_run())))
        self.assertLess(bar.index("NetSuite write-back"), bar.index("12 exceptions"))

    def test_the_tooltip_carries_the_breakdown_and_the_time(self):
        bar = _topbar(_render(netsuite_status.writeback_pill(_run(period_locked=18))))
        self.assertRegex(bar, r'title="Whole statement: 24 written; 18 period locked · ')

    def test_amber_and_red_use_their_own_colours_and_no_tick(self):
        amber = _topbar(_render(netsuite_status.writeback_pill(_run(period_locked=1))))
        red = _topbar(_render(netsuite_status.writeback_pill(_run(failed=1))))
        self.assertIn("badge-warning", amber)
        self.assertIn("badge-danger", red)
        self.assertNotIn("#i-check-circle", amber + red)

    def test_a_statement_with_no_run_shows_no_pill(self):
        for writeback in (None, False):
            with self.subTest(writeback=writeback):
                html = _render(**({} if writeback is None else {"writeback": writeback}))
                self.assertNotIn("NetSuite write-back", _topbar(html))
                self.assertIn("12 exceptions", _topbar(html))


def _card(**overrides):
    card = dict(
        vendor_name="BMW_OF_NORTH_HAVEN", vendor_display_name="Bmw Of North Haven", url_name="BMW_OF_NORTH_HAVEN",
        statement_id="STMT-1", exception_count=1, matched_count=7, total_invoice_count=8, statement_total=2200.0,
        shop=None, billing_location=None, statement_period=None, pdf_name=None, aging=None,
        reason_breakdown={"Not Found in NetSuite": 1}, writeback=None)
    card.update(overrides)
    return card


def _render_cards(*cards):
    from types import SimpleNamespace as NS
    return templates.get_template("exceptions_vendors.html").render(
        active_page="exceptions", vendors=list(cards), range="all",
        window=NS(range="all", date=None, month=None, sync_time_utc=None, empty=False),
        sync_options=[], selected_sync="", sync_truncated=False, window_label="All time",
        vendor_options=[], shop_options=[], location_options=[], user="t",
        open_exceptions_count=1, pending_review_count=0, user_email="t", user_name="t")


def _card_html(html, statement_id):
    return next(c for c in re.findall(r'<a href="[^"]*"[^>]*class="vendor-card.*?</a>', html, re.S)
                if f"statement_id={statement_id}" in c or statement_id in c)


def _card_head(card_html):
    """The card's header: name block on the left, badges on the right."""
    return card_html.split('<div class="vendor-card-body">')[0]


class VendorCardTests(unittest.TestCase):
    def _html(self, run=None, **card):
        wb_pill = netsuite_status.writeback_pill(run) if run is not None else None
        return _card_html(_render_cards(_card(writeback=wb_pill, **card)), "STMT-1")

    def test_the_green_badge_with_a_tick_sits_in_the_header_under_the_exception_badge(self):
        head = _card_head(self._html(_run()))
        self.assertIn("badge-success", head)
        self.assertIn("NetSuite write-back", head)
        self.assertLess(head.index("1 exception"), head.index("NetSuite write-back"))
        # the tick is part of the visible badge text, right before the label
        self.assertRegex(head, r'<svg[^>]*><use href="#i-check-circle"/></svg>NetSuite write-back</span>')

    def test_the_two_badges_are_stacked_and_right_aligned(self):
        head = _card_head(self._html(_run()))
        self.assertIn("flex-direction:column;align-items:flex-end", head)

    def test_it_is_a_badge_not_a_line_in_the_body_or_footer(self):
        html = self._html(_run())
        self.assertNotIn("NetSuite write-back", html.split('<div class="vendor-card-body">')[1])
        self.assertNotIn("aging-line", html.replace("Oldest exception", ""))

    def test_the_hover_text_has_the_full_name_the_breakdown_and_the_time(self):
        html = self._html(_run(period_locked=2))
        self.assertRegex(html, r'title="NetSuite write-back · partial — Whole statement: 24 written; 2 period locked · ')

    def test_amber_red_and_grey_use_their_own_badge_colours_short_wording_and_no_tick(self):
        for run, css, text in ((_run(period_locked=1), "badge-warning", "Write-back · partial"),
                               (_run(failed=1), "badge-danger", "Write-back · failed"),
                               (_run(written=0), "badge-neutral", "Nothing to write")):
            with self.subTest(text=text):
                head = _card_head(self._html(run))
                self.assertIn(css, head)
                self.assertIn(text, head)
                self.assertNotIn("#i-check-circle", head)

    def test_the_badge_never_wraps(self):
        self.assertIn("white-space:nowrap", _card_head(self._html(_run())))

    def test_a_card_with_no_write_back_has_just_its_usual_badge(self):
        for writeback in (None, False):
            with self.subTest(writeback=writeback):
                html = _card_html(_render_cards(_card(writeback=writeback)), "STMT-1")
                self.assertNotIn("write-back", html.lower())
                self.assertIn("1 exception", html)

    def test_a_reconciled_card_shows_it_beside_the_reconciled_badge(self):
        head = _card_head(self._html(_run(), exception_count=0, matched_count=8, reason_breakdown={}))
        self.assertIn("Reconciled", head)
        self.assertLess(head.index("Reconciled"), head.index("NetSuite write-back"))

    def test_each_card_shows_only_its_own_statements_status(self):
        done = _card(statement_id="STMT-1", writeback=netsuite_status.writeback_pill(_run()))
        none = _card(statement_id="STMT-2", writeback=None)
        html = _render_cards(done, none)
        self.assertIn("NetSuite write-back", _card_html(html, "STMT-1"))
        self.assertNotIn("write-back", _card_html(html, "STMT-2").lower())

    def test_every_short_label_is_a_short_one_with_no_number(self):
        for run in (_run(), _run(period_locked=3), _run(failed=2), _run(written=0), _run(outcome="failed")):
            with self.subTest(run=run):
                short = netsuite_status.writeback_pill(run)["short"]
                self.assertLessEqual(len(short), 26)
                self.assertFalse(re.search(r"\d", short), short)


class AttachTests(unittest.TestCase):
    def test_every_card_gets_its_own_status_from_one_batched_lookup(self):
        cards = [{"statement_id": "STMT-1"}, {"statement_id": "STMT-2"}, {"statement_id": None}]
        with mock.patch.object(log_store, "get_latest_runs", return_value={"STMT-1": _run()}) as lookup:
            exceptions._attach_writeback_status(cards)
        lookup.assert_called_once_with(["STMT-1", "STMT-2"])         # one call, not one per card
        self.assertEqual(cards[0]["writeback"]["label"], "NetSuite write-back")
        self.assertIsNone(cards[1]["writeback"])
        self.assertIsNone(cards[2]["writeback"])

    def test_a_database_problem_leaves_the_cards_without_a_line(self):
        cards = [{"statement_id": "STMT-1"}]
        with mock.patch.object(log_store, "get_latest_runs", side_effect=sqlite3.OperationalError("no such table")):
            exceptions._attach_writeback_status(cards)
        self.assertIsNone(cards[0]["writeback"])


class GapStatusTests(unittest.TestCase):
    def test_a_reverted_statement_no_longer_shows_as_written(self):
        run = _run(outcome="reverted", written=0, not_written_counts='{"reverted": 7}')
        pill = netsuite_status.writeback_pill(run)
        self.assertEqual((pill["css"], pill["label"], pill["short"], pill["ok"]),
                         ("badge-neutral", "NetSuite write-back · reverted", "Write-back · reverted", False))
        self.assertIn("7 records cleared", pill["tooltip"])

    def test_one_record_reads_in_the_singular(self):
        run = _run(outcome="reverted", written=0, not_written_counts='{"reverted": 1}')
        self.assertIn("1 record cleared", netsuite_status.writeback_pill(run)["tooltip"])

    def test_writes_a_run_never_reached_make_it_amber_not_green(self):
        run = _run(written=2, not_written_counts='{"not attempted (run stopped early)": 3}')
        pill = netsuite_status.writeback_pill(run)
        self.assertEqual((pill["css"], pill["label"]), ("badge-warning", "NetSuite write-back · partial"))

    def test_the_status_module_uses_the_same_reason_text_as_the_write_back(self):
        self.assertEqual(netsuite_status.NOT_ATTEMPTED, wb.CAT_NOT_ATTEMPTED)

    def test_the_revert_pill_label_and_short_have_no_number(self):
        pill = netsuite_status.writeback_pill(_run(outcome="reverted", not_written_counts='{"reverted": 7}'))
        self.assertFalse(re.search(r"\d", pill["label"] + pill["short"]))


class LookupTests(unittest.TestCase):
    def test_no_statement_id_means_no_lookup(self):
        with mock.patch.object(log_store, "get_runs") as get_runs:
            self.assertIsNone(exceptions._writeback_status(None))
        get_runs.assert_not_called()

    def test_the_newest_run_is_the_one_shown(self):
        runs = [_run(written=7), _run(written=1)]            # get_runs() is newest first
        with mock.patch.object(log_store, "get_runs", return_value=runs):
            self.assertEqual(exceptions._writeback_status("STMT-1")["label"], "NetSuite write-back")

    def test_a_statement_with_no_saved_run_has_no_pill(self):
        with mock.patch.object(log_store, "get_runs", return_value=[]):
            self.assertIsNone(exceptions._writeback_status("STMT-1"))

    def test_a_database_problem_hides_the_pill_instead_of_breaking_the_page(self):
        # e.g. the log tables have not been created on this database yet
        with mock.patch.object(log_store, "get_runs", side_effect=sqlite3.OperationalError("no such table")):
            self.assertIsNone(exceptions._writeback_status("STMT-1"))


class EndToEndTests(unittest.TestCase):
    """A real saved run, read back through the same lookup the page uses."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="nswb_pill_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        db = os.path.join(self.dir, "test.db")
        for patcher in (mock.patch.object(connection, "DB_PATH", db),
                        mock.patch.dict(os.environ, {"AZURE_SQL_SERVER": ""})):
            patcher.start()
            self.addCleanup(patcher.stop)
        conn = sqlite3.connect(db)
        apply_pending_migrations(conn)
        conn.close()

    def _plan(self, invoice):
        return wb.Plan(invoice_number=invoice, statement_amount=Decimal("10"), action=wb.PATCH_MATCHED,
                       record_type="vendorbill", record_id="1", fields={})

    def test_a_clean_saved_run_gives_the_green_pill(self):
        ok = wb.ApplyResult(self._plan("A"), True, "updated", "1")
        log_store.save_run("STMT-E2E", [ok], [ok.plan], started_at="2026-10-19T10:00:00+00:00")
        pill = exceptions._writeback_status("STMT-E2E")
        self.assertEqual((pill["css"], pill["label"]), ("badge-success", "NetSuite write-back"))

    def test_a_run_with_a_locked_period_gives_the_amber_pill(self):
        ok = wb.ApplyResult(self._plan("A"), True, "updated", "1")
        locked = wb.ApplyResult(self._plan("B"), False, "closed", category=wb.CAT_PERIOD_LOCKED)
        log_store.save_run("STMT-E2E", [ok, locked], [ok.plan, locked.plan], started_at="2026-10-19T10:00:00+00:00")
        self.assertEqual(exceptions._writeback_status("STMT-E2E")["css"], "badge-warning")

    def test_the_batched_lookup_returns_the_newest_run_per_statement(self):
        ok = wb.ApplyResult(self._plan("A"), True, "updated", "1")
        locked = wb.ApplyResult(self._plan("B"), False, "closed", category=wb.CAT_PERIOD_LOCKED)
        log_store.save_run("STMT-X", [ok], [ok.plan], started_at="2026-10-19T09:00:00+00:00")
        log_store.save_run("STMT-X", [ok, locked], [ok.plan, locked.plan], started_at="2026-10-19T11:00:00+00:00")
        log_store.save_run("STMT-Y", [ok], [ok.plan], started_at="2026-10-19T10:00:00+00:00")
        latest = log_store.get_latest_runs(["STMT-X", "STMT-Y", "STMT-NONE", None, "STMT-X"])
        self.assertEqual(sorted(latest), ["STMT-X", "STMT-Y"])
        self.assertEqual(latest["STMT-X"]["period_locked"], 1)            # the 11:00 run, not the 09:00 one
        self.assertEqual(log_store.get_latest_runs([]), {})
        # Over 200 ids (2026-10-29): one query for every statement's newest run, the same answer.
        many = ["STMT-X", "STMT-Y"] + [f"STMT-PAD{i}" for i in range(250)]
        big = log_store.get_latest_runs(many)
        self.assertEqual(sorted(big), ["STMT-X", "STMT-Y"])
        self.assertEqual(big["STMT-X"]["period_locked"], 1)
        self.assertNotIn("newest", big["STMT-X"])
        self.assertEqual({k: dict(v) for k, v in big.items()}, {k: dict(v) for k, v in latest.items()})

    def test_a_revert_after_a_write_flips_the_page_status_to_reverted(self):
        ok = wb.ApplyResult(self._plan("A"), True, "updated", "1")
        log_store.save_run("STMT-R", [ok], [ok.plan], started_at="2026-10-19T09:00:00+00:00")
        self.assertEqual(exceptions._writeback_status("STMT-R")["label"], "NetSuite write-back")
        action = {"op": "PATCH", "record_type": "vendorbill", "record_id": "1", "invoice_number": "A", "body": {}}
        log_store.save_revert("STMT-R", [(action, True, "reverted")], started_at="2026-10-19T10:00:00+00:00")
        self.assertEqual(exceptions._writeback_status("STMT-R")["label"], "NetSuite write-back · reverted")

    def test_a_statement_that_was_never_written_has_no_pill(self):
        self.assertIsNone(exceptions._writeback_status("STMT-NEVER"))


if __name__ == "__main__":
    unittest.main()
