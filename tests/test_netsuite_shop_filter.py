"""
tests/test_netsuite_shop_filter.py

The "Find in NetSuite" Shop filter (2026-10-16): NetSuite's own location
names (config/netsuite_locations.json via src/netsuite/locations.py) offered
on the always-open panel, starting on "Any shop"; the ticked codes go to
/netsuite-search as `locations` and become a t.location IN (...) condition.
"""

import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from src.matching import netsuite_search as ns
from src.netsuite import locations
from web.deps import require_login, templates
from web.routers import exceptions
from web.routers.exceptions import REASON_BADGE, SEARCHABLE_REASONS

LOCS = {"64": {"name": "Lamon", "inactive": False}, "28": {"name": "Highway 35", "inactive": False},
        "40": {"name": "International Auto Works", "inactive": True}}


def _with_locations():
    patcher = mock.patch.object(locations, "_load", return_value=LOCS)
    patcher.start()
    return patcher


class TestLocations(unittest.TestCase):

    def setUp(self):
        self.addCleanup(_with_locations().stop)

    def test_shop_options_are_active_and_by_name(self):
        self.assertEqual(locations.shop_options(), [{"code": "28", "name": "Highway 35"},
                                                    {"code": "64", "name": "Lamon"}])

    def test_names_include_inactive_and_unknown_codes_are_dropped(self):
        self.assertEqual(locations.location_names()["40"], "International Auto Works")
        self.assertEqual(locations.known_codes(["64", "999", " 28", "64", "x;drop"]), ["64", "28"])


class TestSavedList(unittest.TestCase):

    def test_the_committed_list_has_lamon_as_64(self):
        # config/netsuite_locations.json, from scripts/sync_netsuite_locations.py.
        self.assertEqual(locations.location_names().get("64"), "Lamon")
        self.assertGreater(len(locations.shop_options()), 50)


class TestSearchCondition(unittest.TestCase):

    def test_locations_become_one_more_condition(self):
        conds = ns.build_conditions(ns.BILL_TABLE, entity_ids=["1"], locations=["64", "28"])
        self.assertIn(("t.location IN (?,?)", ["64", "28"]), conds)
        self.assertNotIn("t.location", " ".join(f for f, _ in ns.build_conditions(ns.BILL_TABLE, entity_ids=["1"])))

    def test_shop_alone_does_not_pass_the_guardrail(self):
        with mock.patch.object(ns, "_fabric_configured", return_value=True):
            result = ns.search_open_ap(locations=["64"])
        self.assertTrue(result["needs_filter"])

    def test_rows_carry_the_location_name(self):
        self.addCleanup(_with_locations().stop)
        row = ns._shape_row({"source_table": ns.BILL_TABLE, "tranid": "1", "location": "64"})
        self.assertEqual((row["location_code"], row["location_name"]), ("64", "Lamon"))


class TestSearchRoute(unittest.TestCase):

    def test_known_codes_are_passed_through(self):
        self.addCleanup(_with_locations().stop)
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="x")
        app.include_router(exceptions.router)
        app.dependency_overrides[require_login] = lambda: "tester"
        empty = {"rows": [], "row_count": 0, "truncated": False, "error": False, "needs_filter": False, "message": None}
        with mock.patch.object(exceptions, "search_open_ap", return_value=empty) as search, \
                mock.patch.object(exceptions.queries, "get_last_netsuite_sync", return_value=None):
            TestClient(app).get("/netsuite-search", params={"amount": "10", "locations": "64,999,28"})
            self.assertEqual(search.call_args.kwargs["locations"], ["64", "28"])
            TestClient(app).get("/netsuite-search", params={"amount": "10"})
            self.assertIsNone(search.call_args.kwargs["locations"])


class TestPanelMarkup(unittest.TestCase):

    def _render(self):
        return templates.get_template("exceptions_review.html").render(
            active_page="exceptions", vendor_name="Conicelli Toyota", vendor_display_name="Conicelli Toyota",
            vendor_url_name="Conicelli%20Toyota", not_found=False, statement={"statement_id": "S"}, exceptions=[],
            selected={"exception_id": "e", "statement_id": "S", "invoice_number": "271249", "vendor_id": "CT",
                      "statement_amount": 50.51, "erp_amount": 57.54, "exception_reason": "Amount Mismatch",
                      "exception_status": "OPEN", "date_raised": None, "days_open": 3, "match_confidence": None,
                      "escalation_status": None, "invoice_date": None, "ro_number": None},
            total=5, resolved=0, progress_pct=0, filter="all", reason_badge=REASON_BADGE, high_confidence_count=0,
            bulk_approve_threshold=0.99, netsuite_record=None, searchable_reasons=SEARCHABLE_REASONS,
            shop_options=[{"code": "28", "name": "Highway 35"}, {"code": "64", "name": "Lamon"}])

    def test_panel_is_open_on_the_page_not_a_dialog(self):
        html = self._render()
        self.assertIn('<section class="ns-inline" id="nsPanel"', html)
        # The only dialog is the Accept-as-match confirm (2026-10-19), never the search.
        self.assertNotIn('<dialog class="ns-modal"', html)
        self.assertEqual(html.count("<dialog"), 1)
        self.assertNotIn('id="nsFindBtn"', html)

    def test_shop_list_offers_netsuite_names_and_starts_on_any_shop(self):
        html = self._render()
        self.assertIn('<span class="ns-chip-value" id="nsChipShopValue">Any shop</span>', html)
        boxes = re.findall(r'<input type="checkbox" value="(\d+)" data-name="([^"]+)">', html)
        self.assertEqual(boxes, [("28", "Highway 35"), ("64", "Lamon")])
        self.assertNotRegex(html, r'value="\d+" data-name="[^"]+" checked')


class TestPanelScript(unittest.TestCase):

    def setUp(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "web", "static", "app.js"), encoding="utf-8") as f:
            self.js = f.read()

    def test_searches_on_load_and_sends_the_ticked_shops(self):
        self.assertIn('const nsPanel = document.getElementById("nsPanel");', self.js)
        self.assertIn('locations: state.shops.join(",")', self.js)
        self.assertIn("shops: [],", self.js)
        tail = self.js[self.js.index("// Always open: search straight away"):]
        self.assertIn("runSearch();", tail[:200])

    def test_shop_chip_text_and_clear(self):
        self.assertIn('if (!state.shops.length) return "Any shop";', self.js)
        self.assertIn("shop: function () { state.shops = []; },", self.js)


if __name__ == "__main__":
    unittest.main()
