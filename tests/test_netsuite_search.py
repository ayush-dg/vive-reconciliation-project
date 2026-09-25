"""
tests/test_netsuite_search.py

Tests for src/matching/netsuite_search.py (the WHERE-clause builder,
tolerance bounds, LIKE escaping and the no-filter guardrail) and for
GET /netsuite-search, the exception review page's open-AP search panel.

Deliberately self-contained: the search module is pure SQL-building plus
one Fabric call, so every test here either exercises the builders
directly or mocks search_open_ap()/execute_lakehouse_query(). Nothing
touches Fabric, Azure SQL or SQLite, so these do not overlap with the
database-backed tests that already fail in this local environment.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from src.matching import netsuite_search
from src.matching.netsuite_search import (
    BILL_TABLE,
    CREDIT_TABLE,
    amount_bounds,
    build_conditions,
    escape_like,
    search_open_ap,
)
from web.deps import require_login
from web.routers import exceptions


def _fragments(conditions):
    return [fragment for fragment, _ in conditions]


def _params(conditions):
    return [p for _, values in conditions for p in values]


class TestBuildConditions(unittest.TestCase):
    """Each filter is meant to be independent -- one (fragment, params)
    pair per active filter -- so that a future location/shop filter is a
    single append rather than a rewrite."""

    def test_no_filters_is_just_the_baseline_plus_open(self):
        conditions = build_conditions(BILL_TABLE)
        self.assertEqual(
            _fragments(conditions),
            ["t.voided = ?", "t.tranid IS NOT NULL", "t.status = ?"],
        )
        self.assertEqual(_params(conditions), ["F", "A"])

    def test_entity_filter_alone(self):
        conditions = build_conditions(BILL_TABLE, entity_ids=["123", "456"])
        self.assertIn("t.entity IN (?,?)", _fragments(conditions))
        self.assertEqual(_params(conditions), ["F", "123", "456", "A"])

    def test_amount_filter_alone(self):
        conditions = build_conditions(BILL_TABLE, bounds=(195.64, 195.66))
        self.assertIn("TRY_CAST(t.total AS DECIMAL(18,2)) BETWEEN ? AND ?", _fragments(conditions))
        self.assertEqual(_params(conditions), ["F", 195.64, 195.66, "A"])

    def test_invoice_filter_alone(self):
        conditions = build_conditions(BILL_TABLE, invoice_contains="Z1451096")
        self.assertIn("LOWER(t.tranid) LIKE LOWER(?) ESCAPE '\\'", _fragments(conditions))
        self.assertIn("%Z1451096%", _params(conditions))

    def test_blank_invoice_filter_is_not_applied(self):
        """An empty box means "no filter", not "match the empty string"."""
        conditions = build_conditions(BILL_TABLE, invoice_contains="   ")
        self.assertNotIn("LOWER(t.tranid) LIKE LOWER(?) ESCAPE '\\'", _fragments(conditions))

    def test_all_filters_combined_keeps_one_pair_each(self):
        conditions = build_conditions(
            BILL_TABLE, entity_ids=["12203"], bounds=(16.31, 16.33),
            invoice_contains="TS247", include_paid=False,
        )
        self.assertEqual(
            _fragments(conditions),
            [
                "t.voided = ?",
                "t.tranid IS NOT NULL",
                "t.entity IN (?)",
                "TRY_CAST(t.total AS DECIMAL(18,2)) BETWEEN ? AND ?",
                "LOWER(t.tranid) LIKE LOWER(?) ESCAPE '\\'",
                "t.status = ?",
            ],
        )
        self.assertEqual(
            _params(conditions), ["F", "12203", 16.31, 16.33, "%TS247%", "A"]
        )


class TestOpenVersusPaidCondition(unittest.TestCase):

    def test_bills_filter_on_status_a_when_open_only(self):
        self.assertIn("t.status = ?", _fragments(build_conditions(BILL_TABLE)))

    def test_credits_filter_on_unapplied_when_open_only(self):
        """Credits have no status column -- confirmed live that
        `unapplied` carries the still-open balance (0 <= unapplied <=
        total, never NULL), so that is the open-ness test."""
        conditions = build_conditions(CREDIT_TABLE)
        self.assertIn("TRY_CAST(t.unapplied AS DECIMAL(18,2)) > ?", _fragments(conditions))
        self.assertIn(0, _params(conditions))

    def test_include_paid_drops_the_status_condition_for_bills(self):
        conditions = build_conditions(BILL_TABLE, include_paid=True)
        self.assertNotIn("t.status = ?", _fragments(conditions))
        self.assertNotIn("A", _params(conditions))

    def test_include_paid_drops_the_unapplied_condition_for_credits(self):
        conditions = build_conditions(CREDIT_TABLE, include_paid=True)
        self.assertNotIn("TRY_CAST(t.unapplied AS DECIMAL(18,2)) > ?", _fragments(conditions))


class TestAmountBounds(unittest.TestCase):

    def test_exact_is_one_cent_either_side(self):
        self.assertEqual(amount_bounds(195.65, "exact"), (195.64, 195.66))

    def test_one_dollar(self):
        self.assertEqual(amount_bounds(195.65, "1_dollar"), (194.65, 196.65))

    def test_five_percent(self):
        self.assertEqual(amount_bounds(200.00, "5_percent"), (190.00, 210.00))

    def test_any_means_no_amount_filter(self):
        self.assertIsNone(amount_bounds(195.65, "any"))

    def test_no_amount_means_no_amount_filter(self):
        self.assertIsNone(amount_bounds(None, "exact"))

    def test_negative_target_is_compared_on_absolute_value(self):
        """A statement credit line carries a negative amount, while
        NetSuite stores every total positive (confirmed live: 0 negative
        totals on either table) -- so the bounds must be positive."""
        self.assertEqual(amount_bounds(-16.32, "exact"), (16.31, 16.33))
        self.assertEqual(amount_bounds(-200.00, "5_percent"), (190.00, 210.00))


class TestEscapeLike(unittest.TestCase):
    """Unescaped, a '%' or '_' in a real invoice number silently becomes a
    wildcard and the search quietly returns the wrong rows."""

    def test_percent_is_escaped(self):
        self.assertEqual(escape_like("50%OFF"), "50\\%OFF")

    def test_underscore_is_escaped(self):
        self.assertEqual(escape_like("INV_123"), "INV\\_123")

    def test_open_bracket_is_escaped(self):
        self.assertEqual(escape_like("A[BC"), "A\\[BC")

    def test_backslash_is_escaped_first(self):
        """The escape character itself must be doubled, and doubled
        BEFORE the metacharacters, or escaping would escape its own
        escapes."""
        self.assertEqual(escape_like("A\\B"), "A\\\\B")

    def test_plain_text_is_untouched(self):
        self.assertEqual(escape_like("CM9327256"), "CM9327256")

    def test_escaping_happens_inside_the_built_condition(self):
        conditions = build_conditions(BILL_TABLE, invoice_contains="INV_1")
        self.assertIn("%INV\\_1%", _params(conditions))


class TestGuardrail(unittest.TestCase):
    """No vendor and no amount would scan all 1.37M bill rows and return
    an arbitrary slice -- refused before any query is issued."""

    ENV = {
        "FABRIC_TENANT_ID": "t", "FABRIC_CLIENT_ID": "c",
        "FABRIC_CLIENT_SECRET": "s", "FABRIC_SQL_ENDPOINT": "e",
        "FABRIC_LAKEHOUSE_NAME": "lh",
    }

    def test_no_vendor_and_no_amount_runs_no_query(self):
        with mock.patch.dict(os.environ, self.ENV), \
             mock.patch.object(netsuite_search, "execute_lakehouse_query") as q:
            result = search_open_ap(entity_ids=None, amount=None)
        q.assert_not_called()
        self.assertTrue(result["needs_filter"])
        self.assertFalse(result["error"])
        self.assertEqual(result["rows"], [])

    def test_amount_with_any_tolerance_still_counts_as_no_amount(self):
        """"Any amount" removes the amount predicate entirely, so it does
        not satisfy the guardrail on its own."""
        with mock.patch.dict(os.environ, self.ENV), \
             mock.patch.object(netsuite_search, "execute_lakehouse_query") as q:
            result = search_open_ap(amount=195.65, amount_tolerance="any")
        q.assert_not_called()
        self.assertTrue(result["needs_filter"])

    def test_amount_alone_is_enough_to_run(self):
        with mock.patch.dict(os.environ, self.ENV), \
             mock.patch.object(netsuite_search, "execute_lakehouse_query", return_value=[]) as q:
            result = search_open_ap(amount=195.65)
        self.assertTrue(q.called)
        self.assertFalse(result["needs_filter"])

    def test_vendor_alone_is_enough_to_run(self):
        with mock.patch.dict(os.environ, self.ENV), \
             mock.patch.object(netsuite_search, "execute_lakehouse_query", return_value=[]) as q:
            result = search_open_ap(entity_ids=["12203"])
        self.assertTrue(q.called)
        self.assertFalse(result["needs_filter"])

    def test_unknown_tolerance_is_rejected_without_querying(self):
        with mock.patch.dict(os.environ, self.ENV), \
             mock.patch.object(netsuite_search, "execute_lakehouse_query") as q:
            result = search_open_ap(entity_ids=["1"], amount_tolerance="nonsense")
        q.assert_not_called()
        self.assertTrue(result["error"])

    def test_fabric_failure_is_reported_not_raised(self):
        with mock.patch.dict(os.environ, self.ENV), \
             mock.patch.object(netsuite_search, "execute_lakehouse_query",
                               side_effect=RuntimeError("lakehouse down")):
            result = search_open_ap(entity_ids=["12203"])
        self.assertTrue(result["error"])
        self.assertEqual(result["rows"], [])


# ---------------------------------------------------------------------------
# GET /netsuite-search
# ---------------------------------------------------------------------------

def _make_client():
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    app.include_router(exceptions.router)
    app.dependency_overrides[require_login] = lambda: "tester"
    return TestClient(app)


class TestNetsuiteSearchRoute(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_returns_the_results_partial(self):
        fake = {"rows": [{
            "record_type": "Bill", "tranid": "390617", "vendor_name": "Keystone",
            "entity_id": "12203", "total": 195.65, "trandate": "6/9/2026",
            "status_label": "Open", "ro_number": "20100916",
            "location_code": "65", "transaction_number": "VENDBILL1199268",
        }], "row_count": 1, "truncated": False, "error": False,
            "needs_filter": False, "message": None}
        with mock.patch.object(exceptions, "search_open_ap", return_value=fake), \
             mock.patch.object(exceptions.queries, "get_last_netsuite_sync", return_value=None):
            resp = self.client.get("/netsuite-search", params={"amount": "195.65"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("390617", resp.text)
        self.assertIn("Location (code)", resp.text)
        # A partial, not a whole page.
        self.assertNotIn("<html", resp.text.lower())

    def test_truncation_notice_is_shown(self):
        fake = {"rows": [], "row_count": 100, "truncated": True, "error": False,
                "needs_filter": False, "message": None}
        fake["rows"] = [{
            "record_type": "Bill", "tranid": "X", "vendor_name": "V", "entity_id": "1",
            "total": 1.0, "trandate": "1/1/2026", "status_label": "Open",
            "ro_number": None, "location_code": "1", "transaction_number": "T",
        }]
        with mock.patch.object(exceptions, "search_open_ap", return_value=fake), \
             mock.patch.object(exceptions.queries, "get_last_netsuite_sync", return_value=None):
            resp = self.client.get("/netsuite-search", params={"amount": "1"})
        self.assertIn("narrow your filters", resp.text)

    def test_empty_state_message(self):
        fake = {"rows": [], "row_count": 0, "truncated": False, "error": False,
                "needs_filter": False, "message": None}
        with mock.patch.object(exceptions, "search_open_ap", return_value=fake), \
             mock.patch.object(exceptions.queries, "get_last_netsuite_sync", return_value=None):
            resp = self.client.get("/netsuite-search", params={"amount": "1"})
        self.assertIn("try loosening one", resp.text)

    def test_bad_amount_is_rejected_gracefully_not_a_500(self):
        with mock.patch.object(exceptions, "search_open_ap") as search:
            resp = self.client.get("/netsuite-search", params={"amount": "not-a-number"})
        self.assertEqual(resp.status_code, 200)
        search.assert_not_called()
        self.assertIn("isn", resp.text)  # "isn't a number"

    def test_bad_tolerance_is_rejected_gracefully(self):
        with mock.patch.object(exceptions, "search_open_ap") as search:
            resp = self.client.get(
                "/netsuite-search", params={"amount": "1", "tolerance": "whatever"}
            )
        self.assertEqual(resp.status_code, 200)
        search.assert_not_called()
        self.assertIn("tolerance", resp.text)

    def test_empty_amount_is_not_an_error(self):
        """A blank amount box means "no amount filter" -- the search still
        runs (scoped by vendor)."""
        fake = {"rows": [], "row_count": 0, "truncated": False, "error": False,
                "needs_filter": False, "message": None}
        with mock.patch.object(exceptions, "search_open_ap", return_value=fake) as search, \
             mock.patch.object(exceptions.queries, "get_last_netsuite_sync", return_value=None):
            resp = self.client.get("/netsuite-search", params={"amount": ""})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(search.called)
        self.assertIsNone(search.call_args.kwargs["amount"])

    def test_use_vendor_false_drops_the_entity_filter(self):
        """The whole point of the panel: dropping the vendor filter so an
        invoice booked under a different vendor can still be found."""
        fake = {"rows": [], "row_count": 0, "truncated": False, "error": False,
                "needs_filter": False, "message": None}
        with mock.patch.object(exceptions, "search_open_ap", return_value=fake) as search, \
             mock.patch.object(exceptions, "resolve_entity_ids", return_value=["12203"]) as resolve, \
             mock.patch.object(exceptions.queries, "get_last_netsuite_sync", return_value=None):
            self.client.get("/netsuite-search",
                            params={"amount": "195.65", "use_vendor": "false"})
        resolve.assert_not_called()
        self.assertIsNone(search.call_args.kwargs["entity_ids"])

    def test_use_vendor_true_resolves_entity_ids(self):
        fake = {"rows": [], "row_count": 0, "truncated": False, "error": False,
                "needs_filter": False, "message": None}
        with mock.patch.object(exceptions, "search_open_ap", return_value=fake) as search, \
             mock.patch.object(exceptions, "resolve_entity_ids", return_value=["12203"]), \
             mock.patch.object(exceptions.queries, "get_last_netsuite_sync", return_value=None):
            self.client.get("/netsuite-search", params={
                "amount": "195.65", "use_vendor": "true",
                "vendor_id": "KEYSTONE_AUTOMOTIVE_INDUSTRIES",
                "vendor_name": "Keystone Automotive",
            })
        self.assertEqual(search.call_args.kwargs["entity_ids"], ["12203"])


class TestRouteIsNotShadowed(unittest.TestCase):
    """/exceptions/{vendor_name:path} is a catch-all whose "path"
    converter matches slashes, so ANY route under /exceptions/ would be
    swallowed by it. /netsuite-search sits outside that prefix on
    purpose; this pins that it stays reachable.
    """

    def test_netsuite_search_route_is_registered_outside_exceptions(self):
        paths = [getattr(r, "path", "") for r in exceptions.router.routes]
        self.assertIn("/netsuite-search", paths)
        self.assertFalse(
            any(p.startswith("/exceptions/") and "netsuite" in p for p in paths),
            "the search route must not live under the /exceptions/ catch-all",
        )

    def test_request_reaches_the_search_handler_not_the_vendor_page(self):
        client = _make_client()
        fake = {"rows": [], "row_count": 0, "truncated": False, "error": False,
                "needs_filter": False, "message": None}
        with mock.patch.object(exceptions, "search_open_ap", return_value=fake) as search, \
             mock.patch.object(exceptions.queries, "get_last_netsuite_sync", return_value=None):
            resp = client.get("/netsuite-search", params={"amount": "1"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(search.called, "the vendor-review catch-all swallowed the request")


if __name__ == "__main__":
    unittest.main()
