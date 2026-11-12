"""
tests/test_exceptions_bill_credit.py

"(Bill)" / "(Credit)" after the invoice number on the Exceptions review list
(2026-11-12): web/queries.py's get_exception_kinds() reads the recon table
(exception_id -> statement lines + matched NetSuite record type) and Silver's
line_type, one statement-scoped query each per page, and
web/routers/exceptions.py's _attach_bill_or_credit() puts the result on each
row. Unknown -> no label.

The recon table is an in-memory SQLite built by the real migrations; Silver
is a stubbed recon_query. Nothing touches the network.
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

from src.lakehouse import recon_table as rt
from tests.test_recon_table import _DbTest
from web import queries
from web.deps import require_login, templates
from web.routers import exceptions
from web.routers.exceptions import REASON_BADGE, SEARCHABLE_REASONS

STMT = {"statement_id": "STMT-BC", "vendor_id": "TEST_VENDOR", "vendor_name": "Test Vendor",
        "statement_period": "2026-10"}
BILL = {"record_type": "bill", "id": 1, "tranid": "INV-1001", "amount": 120.0}
CREDIT = {"record_type": "credit", "id": 2, "tranid": "CM-1005", "amount": 15.0}


def _exc(eid, inv, reason, amount):
    return {"exception_id": eid, "statement_id": "STMT-BC", "invoice_number": inv, "vendor_id": "TEST_VENDOR",
            "exception_reason": reason, "statement_amount": amount, "erp_amount": None,
            "match_confidence": None, "date_raised": None, "days_open": None, "invoice_date": None}


# One exception per rule. E-PAY is a PAYMENT line with no NetSuite record:
# nothing says bill or credit, so no label.
EXCS = [
    _exc("E-MISS", "INV-1001", "Not Found in NetSuite", 120.0),     # CHARGE line
    _exc("E-CRL", "CM-1002", "Not Found in NetSuite", 42.5),           # CREDIT line (amount stored abs)
    _exc("E-NEG", "INV-1003", "Not Found in NetSuite", -8.0),            # no recon row, negative amount
    _exc("E-PAID", "INV-1004", "Appears to be Paid", 298.47),         # line type unknown, NetSuite bill
    _exc("E-NSCR", "CM-1005", "Amount Mismatch", 16.0),                 # line type unknown, NetSuite credit
    _exc("E-PAY", "PMT-1006", "Not Found in NetSuite", 60.0),            # PAYMENT, no record
]
LINES = [
    {"statement_line_id": "L1", "line_number": 1, "invoice_number": "INV-1001", "charge_amount": 120.0},
    {"statement_line_id": "L2", "line_number": 2, "invoice_number": "CM-1002", "charge_amount": -42.5},
    {"statement_line_id": "L3", "line_number": 3, "invoice_number": "INV-1004", "charge_amount": 298.47},
    {"statement_line_id": "L4", "line_number": 4, "invoice_number": "CM-1005", "charge_amount": -16.0},
    {"statement_line_id": "L5", "line_number": 5, "invoice_number": "PMT-1006", "payment_amount": 60.0},
]
RESULTS = {
    "L1": {"status": "Not found in NetSuite", "exception_id": "E-MISS", "statement_amount": 120.0},
    "L2": {"status": "Not found in NetSuite", "exception_id": "E-CRL", "statement_amount": 42.5},
    "L3": {"status": "Appears to be paid", "exception_id": "E-PAID", "statement_amount": 298.47, "netsuite": BILL},
    "L4": {"status": "Amount mismatch", "exception_id": "E-NSCR", "statement_amount": 16.0, "netsuite": CREDIT},
    "L5": {"status": "Not found in NetSuite", "exception_id": "E-PAY", "statement_amount": 60.0},
}
# Silver line types; L3/L4 missing (e.g. a line-selection-rule vendor, filtered out by the query).
SILVER = [{"statement_line_id": "L1", "line_type": "CHARGE"}, {"statement_line_id": "L2", "line_type": "CREDIT"},
          {"statement_line_id": "L5", "line_type": "PAYMENT"}]
EXPECTED = {"E-MISS": "Bill", "E-CRL": "Credit", "E-NEG": "Credit", "E-PAID": "Bill", "E-NSCR": "Credit"}


class ExceptionKindRuleTests(unittest.TestCase):
    def _kind(self, exc=None, links=(), line_types=None):
        return queries.exception_kind(exc or {"statement_amount": 10.0}, list(links), line_types or {})

    def test_charge_line_is_a_bill(self):
        self.assertEqual(self._kind(links=[{"statement_line_id": "L"}], line_types={"L": "CHARGE"}), "Bill")

    def test_credit_line_is_a_credit(self):
        self.assertEqual(self._kind(links=[{"statement_line_id": "L"}], line_types={"L": "CREDIT"}), "Credit")

    def test_negative_amount_is_a_credit(self):
        self.assertEqual(self._kind({"statement_amount": -3.5}), "Credit")

    def test_positive_amount_alone_says_nothing(self):
        # Credits are stored abs(), so positive is not proof of a charge.
        self.assertIsNone(self._kind({"statement_amount": 3.5}))

    def test_netsuite_record_type(self):
        for record_type, kind in (("bill", "Bill"), ("credit", "Credit"), ("vendorbill", "Bill"),
                                  ("VendorCredit", "Credit")):
            self.assertEqual(self._kind(links=[{"netsuite_record_type": record_type}]), kind)

    def test_line_type_wins_over_record_type(self):
        links = [{"statement_line_id": "L", "netsuite_record_type": "bill"}]
        self.assertEqual(self._kind(links=links, line_types={"L": "CREDIT"}), "Credit")

    def test_mixed_line_types_fall_through(self):
        links = [{"statement_line_id": "A", "netsuite_record_type": "bill"},
                 {"statement_line_id": "B", "netsuite_record_type": "bill"}]
        self.assertEqual(self._kind(links=links, line_types={"A": "CHARGE", "B": "CREDIT"}), "Bill")

    def test_unknown_is_none(self):
        self.assertIsNone(self._kind(links=[{"statement_line_id": "L"}], line_types={"L": "PAYMENT"}))
        self.assertIsNone(self._kind(links=[{"netsuite_record_type": "journal"}]))
        self.assertIsNone(self._kind({"statement_amount": None}))
        self.assertIsNone(self._kind({"statement_amount": "n/a"}))


class _Calls:
    def __init__(self, fn):
        self.fn, self.sql = fn, []

    def __call__(self, sql, params=None):
        self.sql.append(sql)
        return self.fn(sql, params)


class GetExceptionKindsTests(_DbTest):
    def setUp(self):
        super().setUp()
        rt.replace_auto_rows("STMT-BC", rt.build_auto_rows(STMT, LINES, RESULTS))
        self.recon = _Calls(lambda sql, params: [dict(r) for r in self.conn.execute(sql, params or []).fetchall()])
        self.silver = _Calls(lambda sql, params: [dict(r) for r in SILVER])
        for name, fn in (("execute_query", self.recon), ("recon_query", self.silver)):
            patcher = mock.patch.object(queries, name, fn)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_every_rule_on_one_page(self):
        self.assertEqual(queries.get_exception_kinds([dict(e) for e in EXCS]), EXPECTED)

    def test_one_query_each_not_one_per_row(self):
        many = [dict(e, exception_id=f"{e['exception_id']}-{i}") for i in range(10) for e in EXCS]
        queries.get_exception_kinds(many)
        self.assertEqual(len(self.recon.sql), 1)
        self.assertEqual(len(self.silver.sql), 1)

    def test_silver_query_skips_line_selection_vendors(self):
        queries.get_exception_kinds([dict(e) for e in EXCS])
        self.assertIn("silver.vendor_line_selection_rule", self.silver.sql[0])
        self.assertIn("NOT EXISTS", self.silver.sql[0])

    def test_no_rows_means_no_query(self):
        self.assertEqual(queries.get_exception_kinds([]), {})
        self.assertEqual(self.recon.sql + self.silver.sql, [])

    def test_failed_recon_lookup_keeps_only_the_sign_rule(self):
        with mock.patch.object(queries, "execute_query", side_effect=RuntimeError("down")):
            self.assertEqual(queries.get_exception_kinds([dict(e) for e in EXCS]), {"E-NEG": "Credit"})

    def test_failed_silver_lookup_keeps_the_other_rules(self):
        with mock.patch.object(queries, "recon_query", side_effect=RuntimeError("down")):
            kinds = queries.get_exception_kinds([dict(e) for e in EXCS])
        self.assertEqual(kinds, {"E-NEG": "Credit", "E-PAID": "Bill", "E-NSCR": "Credit"})


def _client():
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="x")
    app.include_router(exceptions.router)
    app.dependency_overrides[require_login] = lambda: "ap@vive.com"
    return TestClient(app)


def _page(kinds, url="/exceptions/Test%20Vendor?statement_id=STMT-BC", rows=EXCS, counts=(9, 3)):
    """The review page with every query stubbed; returns (html, get_open_exceptions mock)."""
    patches = [
        mock.patch.object(exceptions.queries, "get_statement_by_id", return_value=dict(STMT)),
        mock.patch.object(exceptions.queries, "get_exception_counts", return_value=counts),
        mock.patch.object(exceptions.queries, "get_statement_shop", return_value=None),
        mock.patch.object(exceptions.queries, "get_manual_matches", return_value=[]),
        mock.patch.object(exceptions.queries, "get_cleared_exceptions", return_value=[]),
        mock.patch.object(exceptions.queries, "get_exception_kinds", side_effect=kinds),
        mock.patch.object(exceptions, "fetch_netsuite_record_for_invoice", return_value=None),
        mock.patch.object(exceptions, "_writeback_status", return_value=None),
        mock.patch.object(exceptions, "_statement_pdf_url", return_value=None),
        mock.patch.object(exceptions, "sidebar_context", return_value={}),
        mock.patch.object(exceptions.completion, "history", return_value=[]),
        mock.patch.object(exceptions.completion, "current_status", return_value=None),
    ]
    with mock.patch.object(exceptions.queries, "get_open_exceptions",
                           side_effect=lambda *a: [dict(e) for e in rows]) as open_exc:
        for p in patches:
            p.start()
        try:
            resp = _client().get(url)
        finally:
            for p in patches:
                p.stop()
    assert resp.status_code == 200
    return resp.text, open_exc


def _list_rows(html):
    return re.findall(r'<a href="[^"]*&selected=([^"]+)"\s+class="exception-row[^"]*">(.*?)</a>', html, re.S)


def _invoice_lines(html):
    return [re.search(r'<div class="einv">(.*?)</div>', body, re.S).group(1) for _, body in _list_rows(html)]


class ReviewPageTests(unittest.TestCase):
    def test_rows_carry_the_label_in_brackets(self):
        html, _ = _page(lambda rows: EXPECTED)
        lines = dict(zip([eid for eid, _ in _list_rows(html)], _invoice_lines(html)))
        self.assertEqual(lines["E-MISS"], 'Invoice #INV-1001 <span class="einv-kind einv-kind-bill">(Bill)</span>')
        self.assertEqual(lines["E-CRL"], 'Invoice #CM-1002 <span class="einv-kind einv-kind-credit">(Credit)</span>')
        self.assertEqual(lines["E-NEG"], 'Invoice #INV-1003 <span class="einv-kind einv-kind-credit">(Credit)</span>')
        self.assertEqual(lines["E-PAID"], 'Invoice #INV-1004 <span class="einv-kind einv-kind-bill">(Bill)</span>')
        self.assertEqual(lines["E-NSCR"], 'Invoice #CM-1005 <span class="einv-kind einv-kind-credit">(Credit)</span>')
        self.assertEqual(lines["E-PAY"], "Invoice #PMT-1006")

    def test_the_detail_title_shows_it_too(self):
        html, _ = _page(lambda rows: EXPECTED)
        self.assertIn('<h2>Invoice #INV-1001 <span class="einv-kind einv-kind-bill">(Bill)</span></h2>', html)

    def test_the_label_is_escaped(self):
        html, _ = _page(lambda rows: {"E-MISS": "<b>x</b>"})
        self.assertIn("(&lt;b&gt;x&lt;/b&gt;)", html)
        self.assertNotIn("<b>x</b>", html)

    def test_a_failed_lookup_leaves_the_page_working(self):
        with mock.patch.object(queries, "execute_query", side_effect=RuntimeError("down")), \
                mock.patch.object(queries, "recon_query", side_effect=RuntimeError("down")):
            html, _ = _page(queries.get_exception_kinds)
        self.assertEqual(len(_list_rows(html)), len(EXCS))
        self.assertEqual(html.count('class="einv-kind '), 1)  # only the sign rule is left
        self.assertIn('Invoice #INV-1003 <span class="einv-kind einv-kind-credit">(Credit)</span>', html)

    def test_order_counts_badges_and_amounts_are_unchanged(self):
        with_label, open_a = _page(lambda rows: EXPECTED)
        without, open_b = _page(lambda rows: {})
        strip = lambda h: re.sub(r' <span class="einv-kind[^"]*">\([^)]*\)</span>', "", h)
        self.assertEqual(strip(with_label), without)
        self.assertEqual([eid for eid, _ in _list_rows(with_label)], [e["exception_id"] for e in EXCS])
        self.assertIn("3 / 9 resolved", with_label)
        self.assertEqual(open_a.call_args, open_b.call_args)

    def test_filter_and_sort_are_passed_through_unchanged(self):
        paid = [e for e in EXCS if e["exception_reason"] == "Appears to be Paid"]
        html, open_exc = _page(lambda rows: EXPECTED, url="/exceptions/Test%20Vendor?statement_id=STMT-BC"
                               "&filter=paid&sort=amount", rows=paid)
        open_exc.assert_called_once_with("STMT-BC", "paid", "amount")
        self.assertEqual(_invoice_lines(html), ['Invoice #INV-1004 <span class="einv-kind einv-kind-bill">(Bill)</span>'])

    def test_one_lookup_per_page(self):
        lookup = mock.Mock(return_value=EXPECTED)
        _page(lookup)
        lookup.assert_called_once()
        self.assertEqual([e["exception_id"] for e in lookup.call_args[0][0]], [e["exception_id"] for e in EXCS])

    def test_page_makes_one_recon_and_one_silver_query(self):
        many = [dict(e, exception_id=f"X{i}") for i, e in enumerate(EXCS * 8)]
        links = [{"exception_id": e["exception_id"], "statement_line_id": f"L{i}", "netsuite_record_type": None}
                 for i, e in enumerate(many)]
        recon = _Calls(lambda sql, params: links)
        silver = _Calls(lambda sql, params: [{"statement_line_id": f"L{i}", "line_type": "CHARGE"}
                                             for i in range(len(many))])
        with mock.patch.object(queries, "execute_query", recon), mock.patch.object(queries, "recon_query", silver):
            html, _ = _page(queries.get_exception_kinds, rows=many)
        self.assertEqual((len(recon.sql), len(silver.sql)), (1, 1))
        self.assertEqual(html.count("(Bill)</span>"), len(many) + 1)  # every row + the detail title

    def test_nothing_linked_skips_silver(self):
        recon, silver = _Calls(lambda sql, params: []), _Calls(lambda sql, params: [])
        with mock.patch.object(queries, "execute_query", recon), mock.patch.object(queries, "recon_query", silver):
            _page(queries.get_exception_kinds)
        self.assertEqual((len(recon.sql), len(silver.sql)), (1, 0))

    def test_an_empty_list_makes_no_lookup(self):
        lookup = mock.Mock(return_value={})
        html, _ = _page(lookup, rows=[])
        lookup.assert_not_called()
        self.assertIn("No open exceptions", html)


_DBT = os.path.join(os.path.dirname(__file__), "..", "dbt", "vive_recon")


def _split_top_level(text):
    """Splits a select list on commas outside (), {} and quotes."""
    items, depth, start, quote = [], 0, 0, None
    for i, ch in enumerate(text):
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch in "({":
            depth += 1
        elif ch in ")}":
            depth -= 1
        elif ch == "," and depth == 0:
            items.append(text[start:i])
            start = i + 1
    return items + [text[start:]]


def _model_columns(model):
    """Output columns of a dbt model: its last top-level select list."""
    with open(os.path.join(_DBT, "models", "silver", f"{model}.sql"), encoding="utf-8") as f:
        sql = re.sub(r"--[^\n]*", "", f.read())
    start = sql.rindex("\nselect\n") + len("\nselect\n")
    select_list = sql[start:sql.index("\nfrom ", start)]
    names = (re.search(r"(?:\bas\s+|\.|^)(\w+)\s*$", item.strip(), re.I) for item in _split_top_level(select_list))
    return {m.group(1).lower() for m in names if m}


def _seed_columns(seed):
    with open(os.path.join(_DBT, "seeds", f"{seed}.csv"), encoding="utf-8") as f:
        return {c.strip().lower() for c in f.readline().split(",")}


SILVER_COLUMNS = {
    "statement_line": _model_columns("statement_line"),
    "statement": _model_columns("statement"),
    "vendor_line_selection_rule": _seed_columns("vendor_line_selection_rule"),
}


def _unknown_columns(sql):
    """Every alias.column in sql whose table (from `silver.<table> <alias>`) lacks that column."""
    aliases = {a.lower(): t.lower() for t, a in re.findall(r"silver\.(\w+)\s+(?:AS\s+)?(\w+)", sql, re.I)}
    used = {(a.lower(), c.lower()) for a, c in re.findall(r"\b(\w+)\.(\w+)\b", sql) if a.lower() in aliases}
    return sorted(f"{a}.{c}" for a, c in used if c not in SILVER_COLUMNS[aliases[a]])


def _silver_sql():
    seen = []
    with mock.patch.object(queries, "recon_query", lambda sql, params=None: seen.append(sql) or []):
        queries._silver_line_types(["STMT-1"])
    return seen[0]


class SilverSqlColumnTests(unittest.TestCase):
    """The Silver query is stubbed everywhere else, so check its columns
    against the dbt models / seed that build those tables."""

    def test_the_column_lists_are_read(self):
        self.assertTrue({"statement_line_id", "statement_id", "line_type"} <= SILVER_COLUMNS["statement_line"])
        self.assertNotIn("vendor_id", SILVER_COLUMNS["statement_line"])
        self.assertTrue({"statement_id", "vendor_id"} <= SILVER_COLUMNS["statement"])
        self.assertTrue({"vendor_id", "is_active", "rule_type", "credit_indicator"}
                        <= SILVER_COLUMNS["vendor_line_selection_rule"])

    def test_the_checker_catches_a_missing_column(self):
        self.assertEqual(_unknown_columns("SELECT sl.vendor_id FROM silver.statement_line sl"), ["sl.vendor_id"])

    def test_every_column_the_query_uses_exists(self):
        self.assertEqual(_unknown_columns(_silver_sql()), [])


def _sel_lines():
    """A charge, a reprint, a payment (code 50 batch row and code 5), a sign-typed credit, a CM row typed CHARGE."""
    return [
        {"statement_line_id": "A", "original_invoice_number": "INV-1001", "line_type": "CHARGE",
         "transaction_code": "1", "line_date": "2026-10-01", "charge_amount": 10.0},
        {"statement_line_id": "B", "original_invoice_number": "INV-1001", "line_type": "CHARGE",
         "transaction_code": "1", "line_date": "2026-10-05", "charge_amount": 10.0},
        {"statement_line_id": "C", "original_invoice_number": "INV-1002", "line_type": "PAYMENT",
         "transaction_code": "5", "line_date": "2026-10-02", "payment_amount": 4.0, "po_number": "INV-1003"},
        {"statement_line_id": "D", "original_invoice_number": "INV-1003", "line_type": "PAYMENT",
         "transaction_code": "7", "line_date": "2026-10-02", "payment_amount": 6.0},
        {"statement_line_id": "E", "original_invoice_number": "INV-1004", "line_type": "CREDIT",
         "transaction_code": "4", "line_date": "2026-10-03", "charge_amount": -3.0},
        {"statement_line_id": "F", "original_invoice_number": "CM1005", "line_type": "CHARGE",
         "transaction_code": "1", "line_date": "2026-10-03", "charge_amount": 2.0},
        {"statement_line_id": "G", "original_invoice_number": "INV-1006", "line_type": "CHARGE",
         "transaction_code": "50", "line_date": "2026-10-03", "charge_amount": 1.0, "po_number": "INV-1003"},
    ]


def _changed_types(rules):
    from src.matching.vendor_line_selection import select_lines
    before = {l["statement_line_id"]: l["line_type"] for l in _sel_lines()}
    after = select_lines("TEST_VENDOR", _sel_lines(), {"TEST_VENDOR": rules})
    return {l["statement_line_id"] for l in after if l["line_type"] != before[l["statement_line_id"]]}


def _rule(applies_to, rule_type, **extra):
    return {applies_to: dict({"vendor_id": "TEST_VENDOR", "applies_to": applies_to, "rule_type": rule_type,
                              "primary_code": "5", "fallback_code": None, "credit_indicator": None}, **extra)}


class SkipNarrowingTests(unittest.TestCase):
    """Only rules that can change line_type skip the Silver step."""

    def test_safe_rule_types_never_change_line_type(self):
        for rules in (_rule("charge", "keep_earliest"), _rule("charge", "exclude_by_transaction_code"),
                      _rule("credit", "exclude_by_transaction_code"), _rule("credit", "dedup_by_earliest_date"),
                      {**_rule("charge", "keep_earliest"), **_rule("credit", "dedup_by_earliest_date")}):
            self.assertEqual(_changed_types(rules), set(), rules)

    def test_the_skipped_ones_can(self):
        self.assertTrue(_changed_types(_rule("charge", "keep_earliest", credit_indicator="CM")))
        self.assertTrue(_changed_types(_rule("both", "reclassify_payment_by_po_reference")))

    def test_safe_list_is_exactly_the_three(self):
        self.assertEqual(set(queries._LINE_TYPE_SAFE_RULES),
                         {"keep_earliest", "exclude_by_transaction_code", "dedup_by_earliest_date"})

    def test_query_still_skips_credit_indicator_and_other_types(self):
        sql = _silver_sql()
        self.assertIn("r.credit_indicator IS NOT NULL", sql)
        self.assertIn("r.rule_type IS NULL", sql)
        self.assertRegex(sql, r"r\.rule_type NOT IN \(\?, \?, \?\)")

    def test_params_are_statement_ids_then_rule_types(self):
        seen = []
        with mock.patch.object(queries, "recon_query", lambda sql, params=None: seen.append((sql, params)) or []):
            queries._silver_line_types(["S1", "S2"])
        sql, params = seen[0]
        self.assertEqual(params, ["S1", "S2", *queries._LINE_TYPE_SAFE_RULES])
        self.assertEqual(sql.count("?"), len(params))


class TemplateTests(unittest.TestCase):
    def test_a_row_without_the_key_renders_as_before(self):
        # Older callers / other pages that render rows without bill_or_credit.
        html = templates.get_template("exceptions_review.html").render(
            active_page="exceptions", vendor_name="X", vendor_display_name="X", vendor_url_name="X",
            not_found=False, statement={"statement_id": "S"}, exceptions=[dict(EXCS[0])], selected=None,
            total=1, resolved=0, progress_pct=0, filter="all", reason_badge=REASON_BADGE,
            searchable_reasons=SEARCHABLE_REASONS, follow_up_choices={}, user="t")
        self.assertEqual(_invoice_lines(html), ["Invoice #INV-1001"])


if __name__ == "__main__":
    unittest.main()
