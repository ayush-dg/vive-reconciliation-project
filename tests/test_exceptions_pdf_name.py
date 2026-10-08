"""
tests/test_exceptions_pdf_name.py

Hovering a vendor name on the exceptions vendor cards shows the statement's
PDF file name (added 2026-10-08): get_exception_runs() sets "pdf_name" from
document_intake_log (original_filename, else source_file) and
exceptions_vendors.html adds it to the name's tooltip. No database access:
the card data and query results are mocked.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from web import queries
from web.deps import require_login
from web.routers import exceptions


class TestPdfNameHelper(unittest.TestCase):

    def test_prefers_original_filename(self):
        self.assertEqual(queries._pdf_name({"original_filename": "Astech (Lamon).pdf", "source_file": "tmp.pdf"}),
                         "Astech (Lamon).pdf")

    def test_falls_back_to_source_file_without_folders(self):
        self.assertEqual(queries._pdf_name({"original_filename": None, "source_file": "sample_data/ab12/Rivian.pdf"}),
                         "Rivian.pdf")
        self.assertEqual(queries._pdf_name({"original_filename": "", "source_file": "C:\\x\\Empire.pdf"}), "Empire.pdf")

    def test_none_without_a_row_or_a_name(self):
        self.assertIsNone(queries._pdf_name(None))
        self.assertIsNone(queries._pdf_name({"original_filename": None, "source_file": None}))


def _run(**over):
    run = {"statement_id": "STMT-P1", "vendor_name": "Keystone Automotive Industries",
           "vendor_display_name": "Keystone", "shop": None, "billing_location": None,
           "statement_period": "2026-09", "total_invoice_count": 77, "matched_count": 73,
           "exception_count": 4, "statement_total": 0, "overall_status": "EXCEPTIONS_PRESENT",
           "reconciliation_timestamp": "2026-10-08T12:00:00", "reason_breakdown": {"Not Found": 4},
           "aging": None, "pdf_name": "Keystone (First Choice) - statement.pdf"}
    run.update(over)
    return run


class TestVendorCardTooltip(unittest.TestCase):
    """Route + template, with the card data mocked (the real query reads Fabric)."""

    def _page(self, run):
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-secret")
        app.include_router(exceptions.router)
        app.dependency_overrides[require_login] = lambda: "reviewer@vive.com"
        with mock.patch.object(queries, "get_run_timestamps", return_value=[]),              mock.patch.object(queries, "get_outlook_synced_jobs", return_value=[]),              mock.patch.object(queries, "get_exception_runs", return_value=[run]),              mock.patch.object(queries, "get_open_recon_exceptions_count", return_value=4):
            return TestClient(app).get("/exceptions?range=all")

    def test_vendor_name_tooltip_includes_pdf_name(self):
        resp = self._page(_run())
        self.assertEqual(resp.status_code, 200)
        self.assertIn('title="Keystone Automotive Industries&#10;PDF: Keystone (First Choice) - statement.pdf"',
                      resp.text)

    def test_no_pdf_name_keeps_the_plain_tooltip(self):
        resp = self._page(_run(pdf_name=None))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('title="Keystone Automotive Industries"', resp.text)
        self.assertNotIn("PDF: ", resp.text)


class TestExceptionRunsPdfName(unittest.TestCase):
    """get_exception_runs() reads the name from document_intake_log."""

    def test_pdf_name_comes_from_the_intake_row(self):
        runs = [{"statement_id": "STMT-P1", "vendor_name": "Keystone Automotive Industries",
                 "total_invoice_count": 77, "matched_count": 73, "exception_count": 4,
                 "statement_total": 0, "overall_status": "EXCEPTIONS_PRESENT",
                 "reconciliation_timestamp": "2026-10-08T12:00:00"},
                {"statement_id": "STMT-P2", "vendor_name": "Astech",
                 "total_invoice_count": 1, "matched_count": 0, "exception_count": 1,
                 "statement_total": 0, "overall_status": "EXCEPTIONS_PRESENT",
                 "reconciliation_timestamp": "2026-10-08T12:00:00"}]
        intake = [{"statement_id": "STMT-P1", "billing_location": None, "statement_period": "2026-09",
                   "shop_or_entity": None, "original_filename": "Keystone (First Choice) - statement.pdf",
                   "source_file": "sample_data/x/k.pdf"}]
        with mock.patch.object(queries, "recon_query", side_effect=[runs, []]),              mock.patch.object(queries, "execute_query", return_value=intake),              mock.patch.object(queries, "_get_exceptions_only_vendors", return_value=[]),              mock.patch.object(queries, "_attach_aging_summaries"):
            out = {r["statement_id"]: r for r in queries.get_exception_runs()}
        self.assertEqual(out["STMT-P1"]["pdf_name"], "Keystone (First Choice) - statement.pdf")
        self.assertIsNone(out["STMT-P2"]["pdf_name"])


if __name__ == "__main__":
    unittest.main()
