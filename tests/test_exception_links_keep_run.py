"""
tests/test_exception_links_keep_run.py

The "Review exceptions" links on a recon run's report, Home's runs table
and the batches page carry that run's statement_id, so they open that run's
exceptions -- not whichever run is the vendor's newest (the review route's
fallback when no statement_id is given). Runs with no recon_summary row
(e.g. a failed job) keep the plain vendor link, since the route 404s on a
statement_id it can't find.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from web.deps import require_login
from web.routers import batches, dashboard, reports


def _client(router, fns):
    for name, fn in fns.items():
        patcher = mock.patch(f"web.queries.{name}", fn)
        patcher.start()
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    app.include_router(router)
    app.dependency_overrides[require_login] = lambda: "tester"
    return TestClient(app)


SIDEBAR = {"get_open_recon_exceptions_count": lambda: 0, "get_pending_review_count": lambda: 0}


class TestExceptionLinksKeepRun(unittest.TestCase):

    def tearDown(self):
        mock.patch.stopall()

    def test_report_detail_links_its_own_run(self):
        report = {"summary": {"statement_id": "STMT-OLD", "vendor_name": "Columbia Ford", "statement_period": "2026-09",
                              "total_invoice_count": 3, "matched_count": 1, "exception_count": 2,
                              "statement_total": 10.0, "overall_status": "EXCEPTIONS", "erp_version": None,
                              "erp_total": 10.0, "difference": 0.0, "match_percentage": 33.3, "reconciliation_timestamp": None},
                  "matched": [], "exceptions": [], "intake": None}
        client = _client(reports.router, {**SIDEBAR, "get_statement_report": lambda sid: report})
        html = client.get("/reports/STMT-OLD").text
        self.assertIn('href="/exceptions/Columbia%20Ford?statement_id=STMT-OLD"', html)

    def test_home_run_links_its_own_run(self):
        run = {"statement_id": "S1", "vendor_name": "Fenix", "vendor_display_name": "Fenix", "shop": None,
               "statement_period": "2026-08", "total_invoice_count": 5, "matched_count": 3,
               "exception_count": 2, "overall_status": "EXCEPTIONS", "reconciliation_timestamp": None, "job_id": None}
        data = {"kpis": {"total_invoices": 5, "auto_reconciled": 3, "open_exceptions": 2, "statement_total": 1.0,
                         "vendor_count": 1, "match_rate": 60.0},
                "runs": [run], "total": 1, "reconciled": 0, "period_options": [], "statement_count": 1}
        client = _client(dashboard.router, {
            **SIDEBAR, "get_run_timestamps": lambda: [], "get_outlook_synced_jobs": lambda: [],
            "get_home_dashboard": lambda **kw: data, "get_active_jobs": lambda: [], "get_failed_jobs": lambda: [],
            "get_recent_completed_batches": lambda limit=3: [], "get_last_netsuite_sync": lambda: None,
            "get_last_outlook_sync": lambda: None})
        html = client.get("/").text
        self.assertIn('href="/exceptions/Fenix?statement_id=S1"', html)

    def test_batches_link_keeps_run_only_for_completed_jobs(self):
        def job(job_id, status, sid):
            return {"job_id": job_id, "pdf_filename": f"{job_id}.pdf", "status": status, "statement_id": sid,
                    "vendor_name": "Fenix", "submitted_at": "2026-10-14T10:00:00+00:00", "completed_at": None}
        groups = [{"date": "2026-10-14", "jobs": [job("ok", "COMPLETED", "S1"), job("bad", "FAILED", "S2")]}]
        client = _client(batches.router, {**SIDEBAR, "get_all_batches": lambda: [], "get_manual_uploads": lambda: groups})
        html = client.get("/batches").text
        self.assertIn('href="/exceptions/Fenix?statement_id=S1"', html)
        self.assertNotIn("statement_id=S2", html)
        self.assertIn('href="/exceptions/Fenix" class="link"', html)


if __name__ == "__main__":
    unittest.main()
