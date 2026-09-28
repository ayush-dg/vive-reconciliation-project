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
    MIN_INVOICE_SEARCH_CHARS,
    _select_for,
    amount_bounds,
    build_conditions,
    build_order_by,
    escape_like,
    parse_iso_date,
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
    """No vendor, no amount and no usable invoice fragment would scan all
    1.37M bill rows and return an arbitrary slice -- refused before any
    query is issued."""

    ENV = {
        "FABRIC_TENANT_ID": "t", "FABRIC_CLIENT_ID": "c",
        "FABRIC_CLIENT_SECRET": "s", "FABRIC_SQL_ENDPOINT": "e",
        "FABRIC_LAKEHOUSE_NAME": "lh",
    }

    def _run(self, **kwargs):
        """Runs a search with the Fabric call mocked out, and reports
        whether a query was actually issued."""
        with mock.patch.dict(os.environ, self.ENV), \
             mock.patch.object(netsuite_search, "execute_lakehouse_query", return_value=[]) as q:
            result = search_open_ap(**kwargs)
        return result, q

    def test_no_vendor_no_amount_no_invoice_runs_no_query(self):
        result, q = self._run(entity_ids=None, amount=None)
        q.assert_not_called()
        self.assertTrue(result["needs_filter"])
        self.assertFalse(result["error"])
        self.assertEqual(result["rows"], [])

    def test_amount_with_any_tolerance_still_counts_as_no_amount(self):
        """"Any amount" removes the amount predicate entirely, so it does
        not satisfy the guardrail on its own."""
        result, q = self._run(amount=195.65, amount_tolerance="any")
        q.assert_not_called()
        self.assertTrue(result["needs_filter"])

    def test_amount_alone_is_enough_to_run(self):
        result, q = self._run(amount=195.65)
        self.assertTrue(q.called)
        self.assertFalse(result["needs_filter"])

    def test_vendor_alone_is_enough_to_run(self):
        result, q = self._run(entity_ids=["12203"])
        self.assertTrue(q.called)
        self.assertFalse(result["needs_filter"])


class TestInvoiceOnlyGuardrail(unittest.TestCase):
    """A long-enough invoice fragment narrows a search on its own: hunting
    a specific number with no vendor and no amount is exactly the "was
    this booked under some other vendor?" case the panel exists for.
    Confirmed live that a real 8-character number answers in ~2.8s.
    """

    ENV = TestGuardrail.ENV
    _run = TestGuardrail._run

    def test_four_char_invoice_alone_is_enough_to_run(self):
        result, q = self._run(entity_ids=None, amount=None,
                              amount_tolerance="any", invoice_contains="900C")
        self.assertTrue(q.called)
        self.assertFalse(result["needs_filter"])

    def test_three_char_invoice_alone_is_refused(self):
        """The 3-vs-4 boundary: "900" matches a large fraction of 1.37M
        tranids, which is the unscoped scan the guardrail prevents."""
        result, q = self._run(entity_ids=None, amount=None,
                              amount_tolerance="any", invoice_contains="900")
        q.assert_not_called()
        self.assertTrue(result["needs_filter"])

    def test_boundary_is_exactly_min_invoice_search_chars(self):
        """Pinned against the constant rather than the literal 4, so the
        threshold and its tests cannot drift apart."""
        just_under = "x" * (MIN_INVOICE_SEARCH_CHARS - 1)
        just_over = "x" * MIN_INVOICE_SEARCH_CHARS
        _, q_under = self._run(amount_tolerance="any", invoice_contains=just_under)
        q_under.assert_not_called()
        _, q_over = self._run(amount_tolerance="any", invoice_contains=just_over)
        self.assertTrue(q_over.called)

    def test_whitespace_does_not_count_toward_the_minimum(self):
        """"  90  " is two real characters padded to six -- it must not
        pass on the strength of its spaces."""
        result, q = self._run(amount_tolerance="any", invoice_contains="  90  ")
        q.assert_not_called()
        self.assertTrue(result["needs_filter"])

    def test_long_invoice_still_runs_with_include_paid(self):
        """The case that actually answers the demo question: the invoice
        is in NetSuite but already Paid In Full, so it is only reachable
        with include_paid on."""
        result, q = self._run(entity_ids=None, amount=None, amount_tolerance="any",
                              invoice_contains="900CC752", include_paid=True)
        self.assertTrue(q.called)
        self.assertFalse(result["needs_filter"])

    def test_short_invoice_with_a_vendor_is_fine(self):
        """The length rule only governs whether the fragment can stand
        ALONE -- with a vendor scoping the search, any length is fine."""
        result, q = self._run(entity_ids=["12203"], amount_tolerance="any",
                              invoice_contains="90")
        self.assertTrue(q.called)
        self.assertFalse(result["needs_filter"])

    def test_refusal_message_names_the_invoice_option(self):
        result, _ = self._run(amount_tolerance="any", invoice_contains="90")
        self.assertIn(str(MIN_INVOICE_SEARCH_CHARS), result["message"])
        self.assertIn("invoice", result["message"].lower())

    def test_unknown_tolerance_is_rejected_without_querying(self):
        result, q = self._run(entity_ids=["1"], amount_tolerance="nonsense")
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


# ---------------------------------------------------------------------------
# ORDER BY -- the bug that made TOP N return an arbitrary N
# ---------------------------------------------------------------------------

class TestOrderBy(unittest.TestCase):
    """`SELECT TOP 100 ... WHERE ...` with no ORDER BY lets SQL Server
    return ANY 100 matching rows. Confirmed live 2026-09-28 that a real
    Keystone search matched 4,247 rows and 19 of the 20 genuinely-closest
    bills were missing from the 100 that came back. The ranking therefore
    has to happen in SQL, before TOP -- not in Python afterwards.
    """

    def test_amount_mode_orders_by_closeness(self):
        sql, params = build_order_by(158.55)
        self.assertEqual(sql, "ABS(ABS(TRY_CAST(t.total AS DECIMAL(18,2))) - ?) ASC")
        self.assertEqual(params, [158.55])

    def test_amount_mode_uses_absolute_target(self):
        """A statement credit line carries a negative amount; NetSuite
        stores totals positive."""
        _, params = build_order_by(-158.55)
        self.assertEqual(params, [158.55])

    def test_date_mode_orders_by_parsed_trandate_desc(self):
        sql, params = build_order_by(None)
        self.assertEqual(sql, "TRY_CONVERT(date, t.trandate, 101) DESC")
        self.assertEqual(params, [])
        self.assertNotIn("t.trandate DESC", sql,
                         "a raw string sort would put 9/3/2026 before 10/1/2025")

    def test_generated_sql_contains_order_by_before_top_takes_effect(self):
        conditions = build_conditions(BILL_TABLE, entity_ids=["12203"])
        sql, _ = _select_for(BILL_TABLE, conditions, 100, build_order_by(158.55))
        self.assertIn("ORDER BY", sql)
        self.assertIn("SELECT TOP 100", sql)
        self.assertLess(sql.index("SELECT TOP 100"), sql.index("ORDER BY"),
                        "TOP must be evaluated against an ORDERED set")

    def test_order_by_params_bind_after_where_params(self):
        """pyodbc binds ? positionally and the WHERE clause is emitted
        first, so the ORDER BY parameter must come last."""
        conditions = build_conditions(BILL_TABLE, entity_ids=["12203"], bounds=(1.0, 2.0))
        _, params = _select_for(BILL_TABLE, conditions, 100, build_order_by(158.55))
        self.assertEqual(params[-1], 158.55)
        self.assertEqual(params[:-1], ["F", "12203", 1.0, 2.0, "A"])

    def test_date_mode_adds_no_params(self):
        conditions = build_conditions(BILL_TABLE, entity_ids=["12203"])
        _, params = _select_for(BILL_TABLE, conditions, 100, build_order_by(None))
        self.assertEqual(params, ["F", "12203", "A"])


class TestSortAmountIsNotAFilter(unittest.TestCase):
    """sort_amount RANKS; amount+tolerance FILTER. The modal ranks by
    closeness to the statement amount even at "Any amount", so ranking
    must not narrow anything -- and must not satisfy the guardrail."""

    ENV = TestGuardrail.ENV
    _run = TestGuardrail._run

    def test_sort_amount_alone_does_not_satisfy_the_guardrail(self):
        result, q = self._run(entity_ids=None, amount=None,
                              amount_tolerance="any", sort_amount=158.55)
        q.assert_not_called()
        self.assertTrue(result["needs_filter"])

    def test_sort_amount_adds_no_where_condition(self):
        """It belongs in ORDER BY only -- build_conditions never sees it."""
        conditions = build_conditions(BILL_TABLE, entity_ids=["12203"], bounds=None)
        fragments = " ".join(_fragments(conditions))
        self.assertNotIn("BETWEEN", fragments)

    def test_sort_amount_ranks_while_filter_is_any(self):
        with mock.patch.dict(os.environ, self.ENV), \
             mock.patch.object(netsuite_search, "execute_lakehouse_query", return_value=[]) as q:
            search_open_ap(entity_ids=["12203"], amount=None,
                           amount_tolerance="any", sort_amount=158.55)
        sql = q.call_args_list[0].args[0]
        params = q.call_args_list[0].args[1]
        self.assertIn("ABS(ABS(TRY_CAST(t.total AS DECIMAL(18,2))) - ?) ASC", sql)
        self.assertNotIn("BETWEEN", sql)
        self.assertIn(158.55, params)


class TestUpToTolerance(unittest.TestCase):
    """Ramp's "<= $199" shape: open-ended below the target rather than a
    window around it."""

    def test_up_to_bounds_start_at_zero(self):
        self.assertEqual(amount_bounds(158.55, "up_to"), (0.0, 158.55))

    def test_up_to_uses_absolute_value(self):
        self.assertEqual(amount_bounds(-158.55, "up_to"), (0.0, 158.55))

    def test_up_to_is_an_accepted_tolerance(self):
        self.assertIn("up_to", netsuite_search.TOLERANCES)

    def test_up_to_produces_a_between_condition(self):
        conditions = build_conditions(BILL_TABLE, bounds=amount_bounds(158.55, "up_to"))
        self.assertIn("TRY_CAST(t.total AS DECIMAL(18,2)) BETWEEN ? AND ?", _fragments(conditions))
        self.assertIn(0.0, _params(conditions))
        self.assertIn(158.55, _params(conditions))

    def test_up_to_satisfies_the_guardrail_on_its_own(self):
        with mock.patch.dict(os.environ, TestGuardrail.ENV), \
             mock.patch.object(netsuite_search, "execute_lakehouse_query", return_value=[]) as q:
            result = search_open_ap(amount=158.55, amount_tolerance="up_to")
        self.assertTrue(q.called)
        self.assertFalse(result["needs_filter"])


class TestDateRangeFilter(unittest.TestCase):

    ENV = TestGuardrail.ENV
    _run = TestGuardrail._run

    def test_both_bounds_produce_one_condition_pair(self):
        conditions = build_conditions(BILL_TABLE, entity_ids=["1"],
                                      date_from="2026-01-01", date_to="2026-09-28")
        joined = " AND ".join(_fragments(conditions))
        self.assertIn("TRY_CONVERT(date, t.trandate, 101) >= ?", joined)
        self.assertIn("TRY_CONVERT(date, t.trandate, 101) <= ?", joined)
        self.assertIn("2026-01-01", _params(conditions))
        self.assertIn("2026-09-28", _params(conditions))

    def test_from_only(self):
        conditions = build_conditions(BILL_TABLE, entity_ids=["1"], date_from="2026-01-01")
        joined = " AND ".join(_fragments(conditions))
        self.assertIn(">= ?", joined)
        self.assertNotIn("<= ?", joined)

    def test_to_only(self):
        conditions = build_conditions(BILL_TABLE, entity_ids=["1"], date_to="2026-09-28")
        joined = " AND ".join(_fragments(conditions))
        self.assertIn("<= ?", joined)
        self.assertNotIn(">= ?", joined)

    def test_no_dates_adds_nothing(self):
        conditions = build_conditions(BILL_TABLE, entity_ids=["1"])
        self.assertNotIn("TRY_CONVERT", " ".join(_fragments(conditions)))

    def test_parse_iso_date_accepts_blank_as_no_bound(self):
        self.assertEqual(parse_iso_date("", "Date from"), (None, None))
        self.assertEqual(parse_iso_date(None, "Date from"), (None, None))

    def test_parse_iso_date_rejects_garbage(self):
        value, err = parse_iso_date("28/09/2026", "Date from")
        self.assertIsNone(value)
        self.assertIn("2026-09-28", err)

    def test_bad_date_is_a_friendly_error_not_a_crash(self):
        result, q = self._run(entity_ids=["12203"], date_from="not-a-date")
        q.assert_not_called()
        self.assertTrue(result["error"])
        self.assertIn("Date from", result["message"])

    def test_start_after_end_is_reported(self):
        result, q = self._run(entity_ids=["12203"],
                              date_from="2026-09-28", date_to="2026-09-01")
        q.assert_not_called()
        self.assertTrue(result["error"])
        self.assertIn("after", result["message"])


class TestRowShape(unittest.TestCase):

    RAW = {
        "source_table": BILL_TABLE, "tranid": "900CC752", "entity": "12203",
        "total": "158.55", "trandate": "7/9/2026", "duedate": "8/9/2026",
        "transactionnumber": "VENDBILL1", "custbody_cgh_ro": "3104605",
        "location": "10", "status_code": "B", "unapplied_amount": None,
        "companyname": "AUTO DATA LABELS INC", "entityid": "ADL",
    }

    def test_duedate_is_returned(self):
        row = netsuite_search._shape_row(dict(self.RAW))
        self.assertEqual(row["duedate"], "8/9/2026")
        self.assertEqual(row["duedate_display"], "Aug 9, 2026")

    def test_trandate_is_reformatted_for_display_only(self):
        row = netsuite_search._shape_row(dict(self.RAW))
        self.assertEqual(row["trandate"], "7/9/2026", "raw value preserved")
        self.assertEqual(row["trandate_display"], "Jul 9, 2026")

    def test_unparseable_date_falls_back_to_the_raw_string(self):
        raw = dict(self.RAW, trandate="not a date")
        self.assertEqual(netsuite_search._shape_row(raw)["trandate_display"], "not a date")

    def test_missing_duedate_renders_empty_not_none(self):
        raw = dict(self.RAW, duedate=None)
        self.assertEqual(netsuite_search._shape_row(raw)["duedate_display"], "")

    def test_credit_rows_are_flagged(self):
        raw = dict(self.RAW, source_table=CREDIT_TABLE, unapplied_amount="5")
        row = netsuite_search._shape_row(raw)
        self.assertTrue(row["is_credit"])
        self.assertEqual(row["record_type"], "Credit")

    def test_bill_rows_are_not_flagged_as_credit(self):
        self.assertFalse(netsuite_search._shape_row(dict(self.RAW))["is_credit"])


if __name__ == "__main__":
    unittest.main()
