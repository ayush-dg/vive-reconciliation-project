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
        self.assertEqual(out["counts"], {"matched": 1, "mismatch": 2, "missing": 1, "other": 0,
                                         "set_aside": 0, "none": 1})

    def test_each_line_gets_its_own_result_not_its_invoices(self):
        # Gates GMC 322756 (2026-10-21): the charge matched, the -$75 credit
        # line did not -- the credit must show Not in NetSuite, not Matched.
        lines = [
            {"line_number": 1, "invoice_number": "322756", "charge_amount": 1272.32},
            {"line_number": 2, "invoice_number": "322756", "charge_amount": -1272.32},
            {"line_number": 3, "invoice_number": "322756", "charge_amount": -75.0},
        ]
        matched = [{"invoice_number": "322756", "statement_amount": 1272.32, "erp_amount": 1272.32}]
        exceptions = [{"invoice_number": "322756", "statement_amount": 75.0, "erp_amount": None,
                       "exception_reason": "Not Found in NetSuite"}]
        out = sp.line_results(lines, matched, exceptions, {2: "payment/reversal of invoice 322756's charge"})
        self.assertEqual([r["status"] for r in out["rows"]], ["matched", "set_aside", "missing"])
        self.assertFalse(any(r["shared"] for r in out["rows"]))
        self.assertEqual(out["rows"][1]["note"], "payment/reversal of invoice 322756's charge")
        self.assertEqual(out["counts"]["missing"], out["tiles"]["missing"])
        self.assertEqual(out["counts"]["matched"], out["tiles"]["matched"])

    def test_a_result_under_the_ordinal_number_pairs_with_its_line(self):
        # Nucar: the $125 line of CM6303960 was checked as CM6303960-1.
        lines = [
            {"line_number": 46, "invoice_number": "CM6303960", "charge_amount": -125.0},
            {"line_number": 49, "invoice_number": "CM6303960-1", "charge_amount": -75.0},
        ]
        matched = [{"invoice_number": "CM6303960-1", "statement_amount": 75.0, "erp_amount": 75.0}]
        exceptions = [{"invoice_number": "CM6303960-1", "statement_amount": 125.0, "erp_amount": None,
                       "exception_reason": "Not Found in NetSuite"}]
        out = sp.line_results(lines, matched, exceptions)
        self.assertEqual([r["status"] for r in out["rows"]], ["missing", "matched"])

    def test_an_exact_invoice_number_wins_over_the_ordinal_form(self):
        # Quirk STMT-A7E43CB4: 563967E (not found) and 563967E-1 (matched), both $144.60.
        lines = [{"line_number": 77, "invoice_number": "563967E", "charge_amount": 144.6},
                 {"line_number": 78, "invoice_number": "563967E-1", "charge_amount": 144.6}]
        matched = [{"invoice_number": "563967E-1", "statement_amount": 144.6, "erp_amount": 144.6}]
        exceptions = [{"invoice_number": "563967E", "statement_amount": 144.6, "erp_amount": None,
                       "exception_reason": "Not Found in NetSuite"}]
        out = sp.line_results(lines, matched, exceptions)
        self.assertEqual([r["status"] for r in out["rows"]], ["missing", "matched"])

    def test_a_result_is_used_by_one_line_only(self):
        lines = [{"line_number": 1, "invoice_number": "A1", "charge_amount": 10.0},
                 {"line_number": 2, "invoice_number": "A1", "charge_amount": 10.0}]
        matched = [{"invoice_number": "A1", "statement_amount": 10.0, "erp_amount": 10.0}]
        out = sp.line_results(lines, matched, [])
        self.assertEqual([(r["status"], r["shared"]) for r in out["rows"]], [("matched", False), ("matched", True)])


class TestCardWithResolved(unittest.TestCase):
    """List cards read the recon table's open/resolved counts (2026-10-22)."""
    INTAKE = {"statement_id": "S1", "validation_status": "matches", "vendor_name": "Columbia Ford"}

    def test_open_and_resolved_are_both_said(self):
        card = sp.intake_card(self.INTAKE, None, {"exceptions": 1, "reasons": {"Not Found in NetSuite": 1},
                                                  "resolved": 1})
        self.assertEqual(card["stages"][2]["label"], "1 open · 1 resolved")
        self.assertEqual(card["note"], "1 invoice not found in NetSuite (1 resolved).")

    def test_everything_resolved_is_done(self):
        card = sp.intake_card(self.INTAKE, None, {"exceptions": 0, "reasons": {}, "resolved": 2})
        self.assertEqual((card["stages"][2]["state"], card["stages"][2]["label"]), ("ok", "Done · 2 resolved"))

    def test_without_resolved_it_reads_as_before(self):
        card = sp.intake_card(self.INTAKE, None, {"exceptions": 2, "reasons": {"Not Found in NetSuite": 2}})
        self.assertEqual((card["stages"][2]["label"], card["note"]), ("2 exceptions", "2 invoices not found in NetSuite."))


class TestReconView(unittest.TestCase):
    """The Reconciliation tab read from the recon table only (2026-10-22)."""

    def _row(self, n, inv, status, amount, exc=None, reason=None, **extra):
        return dict({"line_number": n, "invoice_number": inv, "status": status, "line_amount": amount,
                     "exception_id": exc, "exception_reason": reason, "netsuite_amount": None,
                     "difference": None, "source": "auto", "note": None, "matched_by": "system",
                     "matched_at": "2026-10-20T13:09:30"}, **extra)

    def _nucar(self):
        # Nucar STMT-7409AF91 as it stands: 54 matched, 4 open not-found, the
        # $125 one accepted by a reviewer, 3 payoff lines set aside.
        rows = [self._row(i, f"INV{i}", "Matched", 10.0) for i in range(1, 55)]
        rows += [self._row(60 + i, f"CM{i}", "Not found in NetSuite", -20.0, exc=f"E{i}",
                           reason="Not Found in NetSuite") for i in range(4)]
        rows.append(self._row(99, "CM6303960-1", "Accepted", -125.0, exc="E9", reason="Not Found in NetSuite",
                              matched_by="admin@vivecollision.com", matched_at="2026-10-21T15:19:50"))
        rows += [self._row(70 + i, f"P{i}", "Not reconciled", -500.0, note="payment of the invoice") for i in range(3)]
        return sp.recon_view(rows)

    def test_tiles_header_and_filters_agree(self):
        out = self._nucar()
        t, c = out["tiles"], out["counts"]
        self.assertEqual((t["matched"], t["missing"], t["mismatch"], t["open"], t["resolved"]), (54, 4, 0, 4, 1))
        self.assertEqual((c["matched"], c["missing"], c["mismatch"], c["resolved"], c["set_aside"]), (54, 4, 0, 1, 3))
        self.assertEqual(len(out["rows"]), 62)
        self.assertEqual(t["invoices"], 59)

    def test_a_resolved_line_says_so_and_who(self):
        line = next(r for r in self._nucar()["rows"] if r["line_number"] == 99)
        self.assertEqual((line["status"], line["label"]), ("resolved", "Accepted (was not in NetSuite)"))
        self.assertEqual((line["by"], line["at"]), ("admin@vivecollision.com", "2026-10-21"))

    def test_set_aside_lines_say_why_in_plain_words(self):
        rows = [self._row(1, "322756", "Not reconciled", -1272.32,
                          note="payment/reversal of invoice 322756's charge -- set aside, not an exception"),
                self._row(2, "9559776", "Not reconciled", 112.77,
                          note="set aside: invoice 9559776's result is on line 181 -- this line is a reprint/payment of it"),
                self._row(3, "X", "Not reconciled", 5.0, note="set aside by this vendor's line selection rule (reprint/duplicate)"),
                self._row(4, "Y", "Matched", 5.0)]
        reasons = [r["reason"] for r in sp.recon_view(rows)["rows"]]
        self.assertEqual(reasons, ["Payment/reversal of invoice 322756's charge", "Reprint/payment of line 181",
                                   "Reprint or duplicate (vendor rule)", None])

    def test_every_stored_note_has_a_plain_reason(self):
        self.assertEqual(sp.set_aside_reason("exact duplicate of another line on this statement -- counted once"),
                         "Duplicate of another line, counted once")
        self.assertEqual(sp.set_aside_reason("payment line closing a charge on the same invoice -- set aside before matching"),
                         "Payment closing this invoice's charge")
        self.assertEqual(sp.set_aside_reason("not checked against NetSuite on its own (backfilled from the stored results)"),
                         "Not checked on its own")
        self.assertEqual(sp.set_aside_reason("an unknown note"), "an unknown note")
        self.assertIsNone(sp.set_aside_reason(None))

    def test_a_manual_match_is_a_resolved_exception(self):
        # As on the Exceptions page ("Reconciled · matches ..."): found, then resolved.
        out = sp.recon_view([self._row(1, "338630", "Matched manually", 144.96, exc="E1", source="manual",
                                       netsuite_tranid="338630", matched_by="admin@vive.com")])
        self.assertEqual((out["tiles"]["matched"], out["tiles"]["open"], out["tiles"]["resolved"],
                          out["counts"]["resolved"]), (0, 0, 1, 1))
        self.assertEqual(out["rows"][0]["label"], "Matched manually to 338630")
        self.assertEqual(out["rows"][0]["by"], "admin@vive.com")

    def test_an_exception_on_two_lines_counts_once_in_the_tiles(self):
        out = sp.recon_view([self._row(1, "A", "Not found in NetSuite", 5.0, exc="E1", reason="Not Found in NetSuite"),
                             self._row(2, "A", "Not found in NetSuite", 5.0, exc="E1", reason="Not Found in NetSuite")])
        self.assertEqual((out["tiles"]["missing"], out["counts"]["missing"]), (1, 2))


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

    def test_detail_offers_the_pdf_in_a_new_tab(self):
        # Same link and fallbacks as the Exceptions page (2026-10-27).
        intake = {**_intake(), "validation_attempts": [], "primary_computed": None, "previous_balance": None}
        with mock.patch("web.queries.get_statement_pdf",
                        lambda sid: {"mailbox_blob_path": "mailbox/x.pdf", "original_filename": "COLLund0926.pdf"}):
            html = self._detail(intake, None)
        bar = html.split('<div class="topbar-actions">')[1].split("</div>")[0]
        self.assertIn('href="/statements/S1/COLLund0926.pdf" target="_blank" rel="noopener"', bar)
        self.assertIn("View PDF", bar)

    def test_detail_greys_the_pdf_out_when_there_is_no_copy(self):
        intake = {**_intake(), "validation_attempts": [], "primary_computed": None, "previous_balance": None}
        with mock.patch("web.queries.get_statement_pdf", lambda sid: None):
            html = self._detail(intake, None)
        bar = html.split('<div class="topbar-actions">')[1].split("</div>")[0]
        self.assertIn('pdf-btn is-disabled', bar)
        self.assertNotIn("/statements/", bar)

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
