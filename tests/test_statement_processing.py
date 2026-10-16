"""
tests/test_statement_processing.py

Statement Processing (2026-10-16, was the Validation page): each intake
attempt's Extraction -> Validation -> Reconciliation stages and reason line
(web/statement_processing.py), and the list and detail pages that show them.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from web import statement_processing as sp
from web.deps import require_login


def _intake(sid="S1", status="matches", diff=0.0, ts="2026-10-15T10:00:00+00:00", **kw):
    return {"statement_id": sid, "source_file": f"{sid}.pdf", "vendor_name": "Conicelli Toyota",
            "statement_period": "2026-10", "statement_total_as_printed": 2083.45, "validation_status": status,
            "validation_difference": diff, "validation_method": "primary", "ingestion_timestamp": ts,
            "shop": "Lamon Auto Body", "passed": status == "matches", **kw}


def _states(card):
    return [(s["state"], s["label"]) for s in card["stages"]]


class TestReasonSummary(unittest.TestCase):

    def test_design_wording(self):
        self.assertEqual(sp.reason_summary({"Amount Mismatch": 3, "Not Found in NetSuite": 2}),
                         "Amount mismatch on 3 invoices, 2 not found in NetSuite.")
        self.assertEqual(sp.reason_summary({"Not Found in NetSuite": 2}), "2 invoices not found in NetSuite.")
        self.assertEqual(sp.reason_summary({"Amount Mismatch": 1}), "Amount mismatch on 1 invoice.")
        self.assertEqual(sp.reason_summary({"Possible Duplicate in NetSuite": 2}), "2 possible duplicates in NetSuite.")
        self.assertEqual(sp.reason_summary({}), "")


class TestIntakeCard(unittest.TestCase):

    def test_reconciled_clean(self):
        card = sp.intake_card(_intake(), recon={"exceptions": 0, "reasons": {}})
        self.assertEqual(_states(card), [("ok", "Done"), ("ok", "Passed"), ("ok", "Done")])
        self.assertEqual(card["status"], "ok")
        self.assertFalse(card["note"])

    def test_reconciled_with_exceptions(self):
        card = sp.intake_card(_intake(), recon={"exceptions": 5, "reasons": {"Amount Mismatch": 3,
                                                                             "Not Found in NetSuite": 2}})
        self.assertEqual(_states(card)[2], ("warn", "5 exceptions"))
        self.assertEqual((card["status"], card["has_exceptions"], card["failed"]), ("review", True, False))
        self.assertEqual(card["note"], "Amount mismatch on 3 invoices, 2 not found in NetSuite.")

    def test_failed_validation_not_reached(self):
        card = sp.intake_card(_intake(status="mismatch", diff=45.0), job={"status": "COMPLETED"})
        self.assertEqual(_states(card), [("ok", "Done"), ("fail", "Failed"), ("skip", "Not reached")])
        self.assertEqual((card["status"], card["failed"], card["validation_passed"]), ("failed", True, False))
        self.assertEqual(card["note"], "Extracted total doesn't match printed total.")

    def test_no_printed_total_is_a_validation_failure(self):
        card = sp.intake_card(_intake(status="total_not_found", diff=None))
        self.assertEqual(_states(card)[1], ("fail", "Failed"))
        self.assertIn("No printed total", card["note"])

    def test_reconciliation_running_and_failed(self):
        running = sp.intake_card(_intake(), job={"status": "PROCESSING"})
        self.assertEqual((_states(running)[2], running["status"]), (("run", "Running"), "running"))
        failed = sp.intake_card(_intake(), job={"status": "FAILED", "error_message":
                                                "...\n\nNo lines read: 12 lines were extracted but none matched"})
        self.assertEqual(_states(failed)[2], ("fail", "Failed"))
        self.assertEqual(failed["note"], "No lines read: 12 lines were extracted but none matched")
        self.assertTrue(failed["failed"])


class TestJobCard(unittest.TestCase):

    def test_failed_extraction(self):
        card = sp.job_card({"job_id": "J1", "status": "FAILED", "pdf_filename": "Fred Beans.pdf",
                            "error_message": "banner\nScanned PDF, no text layer found.", "submitted_at": "x"})
        self.assertEqual(_states(card), [("fail", "Failed"), ("skip", "Not reached"), ("skip", "Not reached")])
        self.assertEqual(card["note"], "Scanned PDF, no text layer found.")
        self.assertTrue(card["checked"])
        self.assertFalse(card["validation_passed"])

    def test_queued_and_running_have_no_verdict(self):
        for status, label in (("PENDING", "Queued"), ("PROCESSING", "Running")):
            card = sp.job_card({"job_id": "J1", "status": status, "pdf_filename": "x.pdf"})
            self.assertEqual(_states(card)[0], ("run", label))
            self.assertEqual(card["status"], "running")
            self.assertFalse(card["checked"])


class TestBuildCards(unittest.TestCase):

    def test_adds_failed_and_running_jobs_but_not_duplicates_or_completed(self):
        jobs = [
            {"job_id": "J5", "status": "PROCESSING", "statement_id": None, "submitted_at": "2026-10-15T12:00:00+00:00"},
            {"job_id": "J4", "status": "FAILED", "statement_id": None, "pdf_filename": "scan.pdf",
             "error_message": "Scanned PDF", "submitted_at": "2026-10-15T11:00:00+00:00"},
            {"job_id": "J3", "status": "COMPLETED", "statement_id": "S1", "error_message": "Duplicate of S1 -- ...",
             "submitted_at": "2026-10-15T10:30:00+00:00"},
            {"job_id": "J2", "status": "COMPLETED", "statement_id": "GONE", "submitted_at": "2026-10-15T10:20:00+00:00"},
            {"job_id": "J1", "status": "COMPLETED", "statement_id": "S1", "submitted_at": "2026-10-15T09:59:00+00:00"},
        ]
        cards = sp.build_cards([_intake()], jobs, {"S1": {"exceptions": 0, "reasons": {}}})
        self.assertEqual([c["job_id"] or c["statement_id"] for c in cards], ["J5", "J4", "J3"])
        # S1's card uses its newest job (J3) and is the only intake card.
        self.assertEqual(cards[2]["statement_id"], "S1")

    def test_default_tab(self):
        self.assertEqual(sp.default_tab(sp.intake_card(_intake(status="mismatch"))), "validation")
        self.assertEqual(sp.default_tab(sp.intake_card(_intake(), recon={"exceptions": 2, "reasons": {}})),
                         "reconciliation")
        self.assertEqual(sp.default_tab(sp.intake_card(_intake(), recon={"exceptions": 0, "reasons": {}})),
                         "validation")
        self.assertEqual(sp.default_tab(sp.job_card({"status": "FAILED"})), "extraction")


class TestLineResults(unittest.TestCase):

    def test_lines_share_their_invoice_result_and_tiles_add_up(self):
        lines = [
            {"line_number": 0, "invoice_number": "TOW271249", "line_net_amount": 199.41},
            {"line_number": 1, "invoice_number": "TOW271249", "line_net_amount": -50.51},
            {"line_number": 2, "invoice_number": "TOW274949", "charge_amount": 30.06, "payment_amount": None},
            {"line_number": 3, "invoice_number": "TOW279574", "line_net_amount": 138.35},
            {"line_number": 4, "invoice_number": None, "payment_amount": 10.0},
        ]
        matched = [{"invoice_number": "TOW279574", "statement_amount": 138.35, "erp_amount": 138.35}]
        exceptions = [
            {"invoice_number": "TOW271249", "statement_amount": 148.90, "erp_amount": 141.87,
             "exception_reason": "Amount Mismatch"},
            {"invoice_number": "TOW274949", "statement_amount": 30.06, "erp_amount": None,
             "exception_reason": "Not Found in NetSuite"},
        ]
        out = sp.line_results(lines, matched, exceptions)
        rows = out["rows"]
        self.assertEqual([r["status"] for r in rows], ["mismatch", "mismatch", "missing", "matched", "none"])
        self.assertTrue(rows[0]["shared"] and rows[1]["shared"])
        self.assertEqual(rows[0]["invoice_lines"], 2)
        self.assertEqual(rows[0]["difference"], 7.03)
        self.assertEqual(rows[2]["amount"], 30.06)
        self.assertEqual(rows[4]["amount"], -10.0)
        self.assertEqual(out["tiles"], {"matched": 1, "matched_amount": 138.35, "mismatch": 1, "mismatch_amount": 7.03,
                                        "missing": 1, "missing_amount": 30.06, "other": 0, "invoices": 3})
        self.assertEqual(out["counts"], {"matched": 1, "mismatch": 2, "missing": 1, "other": 0, "none": 1})


def _client(fns):
    from web.routers import validation
    for name, fn in fns.items():
        mock.patch(f"web.queries.{name}", fn).start()
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    app.include_router(validation.router)
    app.dependency_overrides[require_login] = lambda: "tester"
    return TestClient(app)


SIDEBAR = {"get_open_recon_exceptions_count": lambda: 0, "get_pending_review_count": lambda: 0,
           "get_outlook_synced_jobs": lambda: []}


class TestPages(unittest.TestCase):

    def tearDown(self):
        mock.patch.stopall()

    def test_list_shows_stages_reason_and_chips(self):
        jobs = [{"job_id": "J9", "status": "FAILED", "statement_id": None, "pdf_filename": "Fred Beans.pdf",
                 "error_message": "Scanned PDF, no text layer found.", "submitted_at": "2026-10-15T11:00:00+00:00"},
                {"job_id": "J8", "status": "PROCESSING", "statement_id": None, "pdf_filename": "new.pdf",
                 "submitted_at": "2026-10-15T12:00:00+00:00"}]
        html = _client({**SIDEBAR, "get_validation_report": lambda: [_intake("S1"), _intake("S2", "mismatch", 45.0)],
                        "get_processing_jobs": lambda: jobs,
                        "get_recon_status": lambda: {"S1": {"exceptions": 2, "reasons": {"Not Found in NetSuite": 2}}}
                        }).get("/validation").text
        self.assertIn("Statement Processing Status", html)
        self.assertIn('data-filter="exceptions">Exceptions</button>', html)
        self.assertIn("2 invoices not found in NetSuite.", html)
        self.assertIn("Extracted total doesn&#39;t match printed total.", html)
        self.assertIn("Scanned PDF, no text layer found.", html)
        self.assertIn('<span class="sp-sname">Reconciliation</span><span class="sp-sstate">2 exceptions</span>', html)
        # Hero: S1 passed, S2 and the failed extraction failed; the running job doesn't count.
        self.assertIn('id="hero-total">3</div>', html)
        self.assertIn('id="hero-passed">1</div>', html)
        # A failed extraction with no statement has no View link.
        self.assertEqual(html.count("View →"), 2)

    def _detail(self, intake, summary, matched=(), exceptions=(), job=None, lines=(), tab=""):
        report = {"summary": summary, "intake": None, "matched": list(matched), "exceptions": list(exceptions)}
        return _client({**SIDEBAR,
                        "get_extraction_validation_detail": lambda sid: {"intake": intake, "computed_total": 2083.45,
                                                                         "lines": list(lines)},
                        "get_latest_job_for_statement": lambda sid: job,
                        "get_statement_report": lambda sid: report,
                        "get_extracted_rows_for_statement": lambda sid: []}).get("/validation/S1" + tab).text

    def test_detail_opens_reconciliation_tab_when_there_are_exceptions(self):
        intake = {**_intake(), "validation_attempts": [], "primary_computed": None, "previous_balance": None}
        html = self._detail(intake, {"vendor_name": "Conicelli Toyota", "exception_count": 1},
                            exceptions=[{"invoice_number": "A1", "statement_amount": 5.0, "erp_amount": None,
                                         "exception_reason": "Not Found in NetSuite"}],
                            lines=[{"line_number": 0, "invoice_number": "A1", "line_net_amount": 5.0}])
        self.assertIn('id="tab-reconciliation" data-panel="p-reconciliation"\n          aria-controls="p-reconciliation" aria-selected="true"', html)
        self.assertIn('id="p-validation" role="tabpanel" aria-labelledby="tab-validation" hidden', html)
        self.assertIn("Line-by-line against NetSuite", html)
        self.assertIn("Not in NetSuite", html)
        self.assertIn('href="/exceptions/Conicelli%20Toyota?statement_id=S1"', html)

    def test_detail_for_a_validation_stop(self):
        intake = {**_intake(status="mismatch", diff=45.0), "validation_attempts": [], "primary_computed": None,
                  "previous_balance": None}
        html = self._detail(intake, None, job={"status": "COMPLETED", "error_message": "Not reconciled -- ..."})
        self.assertIn('id="tab-validation" data-panel="p-validation"\n          aria-controls="p-validation" aria-selected="true"', html)
        self.assertIn("only statements that pass validation 100% go on to reconciliation", html)

    def test_tab_query_param_wins(self):
        intake = {**_intake(), "validation_attempts": [], "primary_computed": None, "previous_balance": None}
        html = self._detail(intake, None, tab="?tab=extraction")
        self.assertIn('aria-controls="p-extraction" aria-selected="true"', html)


if __name__ == "__main__":
    unittest.main()
