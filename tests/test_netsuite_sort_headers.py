"""
tests/test_netsuite_sort_headers.py

Sortable Vendor / Bill # / Status / Amount headers in the "Find in NetSuite"
results (2026-11-12, UAT 23). Sorting happens in the browser (static/app.js
nsSort + one delegated click listener on #nsResults); the partial only adds
a <button> per sortable header and a data-sort-value per cell. Rendered
through the app's own Jinja environment: no route, no database.
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web.deps import templates

PARTIAL = "_netsuite_search_results.html"
APP_JS = os.path.join(os.path.dirname(__file__), "..", "web", "static", "app.js")


def _row(n, vendor, tranid, status, total, credit=False, matched=None):
    return {"record_type": "Credit" if credit else "Bill", "is_credit": credit, "tranid": tranid,
            "internal_id": str(1000 + n), "vendor_name": vendor, "entity_id": "9001", "total": total,
            "trandate": "10/2/2026", "trandate_display": "Oct 2, 2026", "duedate_display": None,
            "status_label": status, "ro_number": None, "location_code": None, "location_name": None,
            "transaction_number": f"VB-{n}", "already_matched": matched}


ROWS = [
    _row(1, "Test Vendor", "INV-10", "Open", 120.0),
    _row(2, "other vendor", "INV-2", "Paid In Full", 15.5),
    _row(3, "—", "CM-5", "Open", 42.1, credit=True),
    _row(4, "Test Vendor", None, None, None),
    _row(5, "Test Vendor", "INV-7", "Open", 9.99,
         matched={"invoice_number": "INV-7", "statement_id": "STMT-T", "status": "Matched", "matched_by": "system"}),
]


def _result(rows=ROWS, truncated=False):
    matched = sum(1 for r in rows if r.get("already_matched"))
    return {"rows": rows, "row_count": len(rows), "truncated": truncated, "error": False,
            "needs_filter": False, "message": None, "source": "fabric", "matched_count": matched}


def _render(source=None, **result):
    ctx = {"result": _result(**result), "last_sync": None}
    if source is None:
        return templates.get_template(PARTIAL).render(**ctx)
    return templates.env.from_string(source).render(**ctx)


def _source():
    with open(os.path.join(os.path.dirname(__file__), "..", "web", "templates", PARTIAL), encoding="utf-8") as f:
        return f.read()


def _sort_values(html, col):
    """data-sort-value of column `col` (0 = pick) for each result row, in order."""
    rows = re.findall(r'<tr class="ns-modal-row.*?</tr>', html, re.S)
    return [re.findall(r'<td[^>]*?(?: data-sort-value="([^"]*)")?>', r)[col] for r in rows]


class SortableHeaderMarkupTests(unittest.TestCase):
    def test_four_headers_are_buttons_with_a_sort_key(self):
        html = _render()
        headers = re.findall(r'<th([^>]*)><button type="button" class="ns-sort" data-sort="(\w+)" '
                             r'data-sort-type="(\w+)">([^<]+)<span class="ns-sort-arrow" aria-hidden="true">'
                             r'</span></button></th>', html)
        self.assertEqual([(key, kind, label) for _, key, kind, label in headers],
                         [("vendor", "text", "Vendor"), ("bill", "natural", "Bill #"),
                          ("status", "text", "Status"), ("amount", "number", "Amount")])
        for attrs, *_ in headers:
            self.assertIn('aria-sort="none"', attrs)
        self.assertIn('class="ns-col-amount" aria-sort="none"', html)

    def test_pick_and_details_headers_are_not_sortable(self):
        html = _render()
        self.assertIn('<th class="ns-col-pick"><span class="ns-sr-only">Pick</span></th>', html)
        self.assertIn('<th class="ns-col-toggle"><span class="ns-sr-only">Details</span></th>', html)
        self.assertEqual(html.count('class="ns-sort"'), 4)

    def test_cells_carry_the_sort_values(self):
        html = _render()
        self.assertEqual(_sort_values(html, 1), ["Test Vendor", "other vendor", "", "Test Vendor", "Test Vendor"])
        self.assertEqual(_sort_values(html, 2), ["INV-10", "INV-2", "CM-5", "", "INV-7"])
        self.assertEqual(_sort_values(html, 3), ["Open", "Paid In Full", "Open", "", "Open"])
        # The amount shown, as a plain number; a credit sorts by the value shown.
        self.assertEqual(_sort_values(html, 4), ["120.00", "15.50", "42.10", "", "9.99"])
        self.assertIn('data-sort-value="42.10">$42.10</td>', html)

    def test_sort_values_are_escaped(self):
        html = _render(rows=[_row(1, 'A "quoted" <b>', 'X"1', "Open", 1.0)])
        self.assertIn('data-sort-value="A &#34;quoted&#34; &lt;b&gt;"', html)
        self.assertIn('data-sort-value="X&#34;1"', html)
        self.assertNotIn("<b>", html)

    def test_row_ids_keep_the_server_order(self):
        # app.js returns to the default order by these numbers.
        html = _render()
        self.assertEqual(re.findall(r'data-row-id="nsrow-(\d+)"', html), ["1", "2", "3", "4", "5"])

    def test_truncated_note_says_only_these_rows_are_sorted(self):
        html = _render(truncated=True)
        self.assertIn("Showing first 5 — narrow your filters. Sorting a column reorders only these 5.", html)
        self.assertNotIn("Sorting a column", _render())

    def test_no_inline_script_in_the_partial(self):
        # It is swapped in with innerHTML, where a <script> would never run.
        self.assertNotIn("<script", _source())


class NothingElseChangedTests(unittest.TestCase):
    def _old_source(self):
        """The partial as it was before UAT 23: the new markup taken back out."""
        src = _source()
        src = re.sub(r'[ \t]*\{# Sortable headers.*?#\}\n', "", src, flags=re.S)
        src = re.sub(r'<th( class="[^"]*")? aria-sort="none"><button type="button" class="ns-sort" [^>]*>'
                     r'([^<]+)<span class="ns-sort-arrow" aria-hidden="true"></span></button></th>', r"<th\1>\2</th>", src)
        src = re.sub(r' data-sort-value="\{\{.*?\}\}"', "", src)
        return src.replace(" Sorting a column reorders only these {{ result.row_count }}.", "")

    @staticmethod
    def _strip_new(html):
        html = re.sub(r'<th( class="[^"]*")? aria-sort="none"><button type="button" class="ns-sort" [^>]*>'
                      r'([^<]+)<span class="ns-sort-arrow" aria-hidden="true"></span></button></th>', r"<th\1>\2</th>", html)
        html = re.sub(r' data-sort-value="[^"]*"', "", html)
        html = re.sub(r"\n[ \t]*\n([ \t]*<th>Vendor</th>)", r"\n\1", html)  # the Jinja comment's line
        return html.replace(" Sorting a column reorders only these 5.", "")

    def test_the_render_minus_the_new_markup_is_the_old_render(self):
        old = self._old_source()
        self.assertNotIn("data-sort", old)
        for truncated in (False, True):
            self.assertEqual(self._strip_new(_render(truncated=truncated)), _render(old, truncated=truncated))

    def test_the_old_template_matches_deploy_dev_layout(self):
        # The pieces app.js and the Accept bar read are all still there.
        html = _render()
        for marker in ('class="ns-pick"', 'data-internal-id="1001"', 'data-amount="120.00"',
                       'class="ns-details-btn"', 'id="nsrow-1-details"', 'data-matched="1" hidden',
                       'class="ns-show-matched"'):
            self.assertIn(marker, html)
        self.assertNotIn("<form", html)
        self.assertNotIn("method=", html)


class AppJsWiringTests(unittest.TestCase):
    def setUp(self):
        with open(APP_JS, encoding="utf-8") as f:
            self.js = f.read()

    def test_pure_helpers_and_delegated_listener(self):
        self.assertIn("var nsSort = (function () {", self.js)
        for name in ("compareText", "compareNatural", "compareNumber", "order", "nextDirection"):
            self.assertIn(f"function {name}(", self.js)
        self.assertIn('nsResults.addEventListener("click"', self.js)
        self.assertIn('ev.target.closest("button.ns-sort")', self.js)

    def test_rows_move_with_their_details_row(self):
        body = self.js[self.js.index("function sortResults(btn)"):]
        body = body[:body.index('nsResults.addEventListener("click"')]
        self.assertIn('tbody.appendChild(item.tr)', body)
        self.assertIn('document.getElementById(item.tr.dataset.rowId + "-details")', body)
        self.assertIn('th.setAttribute("aria-sort", direction)', body)
        # Sorting never re-renders: no innerHTML, no fetch.
        self.assertNotIn("innerHTML", body)
        self.assertNotIn("fetch(", body)


if __name__ == "__main__":
    unittest.main()
