"""
tests/test_exceptions_review_shop.py

The exception review page's header shows the statement's shop name next to
the vendor name (added 2026-10-08), in a smaller font. The shop comes from
document_intake_log.shop_or_entity via queries.get_statement_shop() -- the
same source as the run/vendor cards. Nothing here touches SQLite, Azure SQL
or Fabric: the template is rendered directly and execute_query is mocked.
"""

import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web import queries
from web.deps import templates
from web.routers.exceptions import REASON_BADGE, SEARCHABLE_REASONS


def _render(shop):
    return templates.get_template("exceptions_review.html").render(
        active_page="exceptions",
        vendor_name="Keystone Automotive Industries",
        vendor_display_name="Keystone",
        vendor_url_name="Keystone%20Automotive%20Industries",
        not_found=False,
        statement={"statement_id": "STMT-TEST"},
        shop=shop,
        exceptions=[], selected=None,
        total=0, resolved=0, progress_pct=0, filter="all",
        reason_badge=REASON_BADGE, high_confidence_count=0, bulk_approve_threshold=0.99,
        netsuite_record=None, searchable_reasons=SEARCHABLE_REASONS,
        open_exception_count=0, user="tester",
    )


def _h1(html):
    return re.search(r"<h1[^>]*>.*?</h1>", html, re.S).group(0)


class TestHeaderShop(unittest.TestCase):

    def test_shop_shown_next_to_vendor(self):
        h1 = _h1(_render("ADL Lamon, ADL Noakers"))
        self.assertIn("Keystone", h1)
        self.assertIn('<span class="topbar-shop" title="ADL Lamon, ADL Noakers">· ADL Lamon, ADL Noakers</span>', h1)

    def test_no_shop_no_span(self):
        h1 = _h1(_render(None))
        self.assertNotIn("topbar-shop", h1)
        self.assertEqual(re.sub(r"<[^>]+>", "", h1).strip(), "Keystone")


class TestGetStatementShop(unittest.TestCase):

    def test_joins_json_shop_list(self):
        rows = [{"statement_id": "STMT-1", "statement_period": "2026-09", "shop_or_entity": '["ADL Lamon", "ADL Noakers"]'}]
        with mock.patch.object(queries, "execute_query", return_value=rows):
            self.assertEqual(queries.get_statement_shop("STMT-1"), "ADL Lamon, ADL Noakers")

    def test_missing_or_bad_shop_is_none(self):
        for value in (None, "", "not json", "[]"):
            with self.subTest(value=value):
                rows = [{"statement_id": "STMT-1", "statement_period": None, "shop_or_entity": value}]
                with mock.patch.object(queries, "execute_query", return_value=rows):
                    self.assertIsNone(queries.get_statement_shop("STMT-1"))

    def test_no_statement_id_skips_query(self):
        with mock.patch.object(queries, "execute_query") as eq:
            self.assertIsNone(queries.get_statement_shop(None))
            eq.assert_not_called()


if __name__ == "__main__":
    unittest.main()
