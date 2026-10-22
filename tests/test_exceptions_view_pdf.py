"""
tests/test_exceptions_view_pdf.py

The "View PDF" button in the top bar of a statement's exception review page:
_statement_pdf_url() in web/routers/exceptions.py builds the short
/statements/<statement id>/<name>.pdf link (the route in
web/routers/statements.py) only when an archived PDF exists, and the button
opens it in a new tab -- otherwise it is greyed out. Nothing touches Azure.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web.routers import exceptions
from tests.test_exceptions_writeback_status import _render, _topbar


def _url(archived):
    with mock.patch.object(exceptions.queries, "get_statement_pdf", return_value=archived):
        return exceptions._statement_pdf_url("STMT-60A970B4")


class PdfUrlTests(unittest.TestCase):
    def test_an_archived_pdf_gets_the_short_link(self):
        self.assertEqual(_url({"blob_storage_path": "https://x/a.pdf", "original_filename": "BMW.pdf"}),
                         "/statements/STMT-60A970B4/BMW.pdf")

    def test_odd_characters_in_the_name_are_made_url_safe(self):
        url = _url({"blob_storage_path": "https://x/a.pdf", "original_filename": "EZ Auto, Lees, Oct 26.pdf"})
        self.assertEqual(url, "/statements/STMT-60A970B4/EZ%20Auto_%20Lees_%20Oct%2026.pdf")

    def test_a_folder_in_the_name_is_dropped_and_pdf_is_added(self):
        self.assertEqual(_url({"blob_storage_path": "https://x/a", "original_filename": "in\\box/Statement"}),
                         "/statements/STMT-60A970B4/Statement.pdf")

    def test_a_missing_name_falls_back_to_statement_pdf(self):
        self.assertEqual(_url({"blob_storage_path": "https://x/a.pdf", "original_filename": None}),
                         "/statements/STMT-60A970B4/statement.pdf")

    def test_no_archived_pdf_means_no_link(self):
        self.assertIsNone(_url(None))

    def test_a_database_problem_means_no_link(self):
        with mock.patch.object(exceptions.queries, "get_statement_pdf", side_effect=RuntimeError("down")):
            self.assertIsNone(exceptions._statement_pdf_url("STMT-1"))

    def test_no_statement_id_means_no_lookup(self):
        with mock.patch.object(exceptions.queries, "get_statement_pdf") as lookup:
            self.assertIsNone(exceptions._statement_pdf_url(None))
        lookup.assert_not_called()

    def test_the_link_matches_the_pdf_route(self):
        url = _url({"blob_storage_path": "https://x/a.pdf", "original_filename": "BMW.pdf"})
        _, _, statement_id, filename = url.split("/")
        self.assertRegex(statement_id, r"^STMT-[0-9A-Za-z-]{1,40}$")
        self.assertTrue(filename.lower().endswith(".pdf"))


class ButtonTests(unittest.TestCase):
    def test_with_a_pdf_the_button_opens_it_in_a_new_tab(self):
        bar = _topbar(_render(pdf_url="/statements/STMT-TEST/BMW.pdf"))
        self.assertIn('href="/statements/STMT-TEST/BMW.pdf"', bar)
        self.assertIn('target="_blank"', bar)
        self.assertIn('rel="noopener"', bar)
        self.assertIn("View PDF", bar)
        self.assertNotIn("is-disabled", bar)

    def test_without_a_pdf_the_button_is_greyed_out(self):
        bar = _topbar(_render(pdf_url=None))
        self.assertIn("View PDF", bar)
        self.assertIn("is-disabled", bar)
        self.assertIn('title="PDF not available"', bar)
        self.assertNotIn("/statements/", bar)

    def test_the_button_comes_before_the_exception_count(self):
        bar = _topbar(_render(pdf_url="/statements/STMT-TEST/BMW.pdf"))
        self.assertLess(bar.index("View PDF"), bar.index("12 exceptions"))

    def test_a_missing_statement_page_has_no_button(self):
        from web.deps import templates
        html = templates.get_template("exceptions_review.html").render(
            active_page="exceptions", vendor_name="X", vendor_display_name="X", not_found=True, user="t")
        self.assertNotIn("View PDF", html)


if __name__ == "__main__":
    unittest.main()
