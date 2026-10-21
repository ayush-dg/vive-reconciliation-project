"""pdf_full_match for a statement with no printed total (src/validation/full_match_no_total.py, wired
into notebooks/01_document_intake.py after the no-total rule and the account-blocks check, 2026-10-22).

SYNTHETIC text-layer PDFs (the helpers of tests/test_pdf_row_match.py / test_pdf_full_match.py). At the
intake the step is reached only when the no-total rule refuses -- here because the PDF prints a
"Total payments received" line (a total-ish word with an amount, but not a statement total). Real data
(Healey, Lithia, every stored statement) where present in scratchpad/ (git-ignored; skipped where
absent)."""
import copy
import os
import sys
import tempfile
import unittest
from unittest import mock

import fitz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_oct1_intake_worker_web import load_intake  # noqa: E402
from test_pdf_full_match import full_rows  # noqa: E402
from test_pdf_row_match import GOOD_LINES, X, _PdfCase, statement_page, write_pdf  # noqa: E402
from test_text_columns import Q10, _stored, schema  # noqa: E402

from src.validation import full_match_no_total as fm  # noqa: E402
from src.validation import pdf_row_match as prm  # noqa: E402
from src.validation.arithmetic_gate import compute_statement_total_from_invoices  # noqa: E402

ROWS_TOTAL = 175.75   # GOOD_LINES: 120.00 + 75.50 - 50.00 + 30.25
PAYMENTS_NOTE = [(X["desc"], 260, "Total payments received"), (X["bal"], 260, "50.00")]


def under_label(label, value, x=400, y=320):
    """A total label with its amount printed on the line below."""
    return [(x, y, label), (x, y + 12, value)]


class _Case(_PdfCase):

    def check(self, rows=None, lines=GOOD_LINES, extra=(), pages=None):
        path = self.pdf(pages or [statement_page(lines, extra=extra)])
        rows = full_rows() if rows is None else rows
        try:
            text = "\n".join(l["text"] for p in prm.read_pdf_lines(path) for l in p["lines"])
        except prm.NotVerified:
            text = ""
        return fm.check_full_match_no_total(rows, path, compute_statement_total_from_invoices(rows), text)


class TestPasses(_Case):

    def test_no_printed_total_and_every_cell_correct_passes(self):
        out = self.check()
        self.assertTrue(out["passed"], out["reason"])
        self.assertEqual(out["computed"], ROWS_TOTAL)
        self.assertEqual(out["safety"]["result"], "none printed")
        self.assertEqual(out["full_match"]["rows_verified"], 4)

    def test_a_total_printed_under_its_label_that_equals_the_rows_passes_and_is_recorded(self):
        out = self.check(extra=under_label("TOTAL DUE", "175.75"))
        self.assertTrue(out["passed"], out["reason"])
        self.assertEqual([(a["label"], a["page"], a["amount"], a["read"]) for a in out["safety"]["total_like_amounts"]],
                         [("TOTAL DUE", 1, 175.75, "printed under the label")])
        self.assertEqual(out["safety"]["result"], "every printed total-like amount equals the rows")

    def test_a_total_on_its_own_line_that_equals_the_rows_passes(self):
        self.assertTrue(self.check(extra=[(300, 320, "Balance due"), (400, 320, "175.75")])["passed"])


class TestSafety(_Case):

    def test_a_total_one_cent_off_the_rows_is_refused(self):
        out = self.check(extra=under_label("TOTAL DUE", "175.76"))
        self.assertFalse(out["passed"])
        self.assertIn("TOTAL DUE 175.76 on page 1, not the rows' charges - credits 175.75", out["reason"])

    def test_two_different_labelled_totals_are_refused(self):
        out = self.check(extra=under_label("TOTAL DUE", "175.75") + under_label("NEW BALANCE", "180.00", x=480))
        self.assertFalse(out["passed"])
        self.assertIn("NEW BALANCE 180.00", out["reason"])

    def test_a_bare_balance_box_that_differs_is_refused(self):
        out = self.check(extra=[(400, 40, "BALANCE"), (500, 40, "AMOUNT PAID"), (400, 52, "200.00")])
        self.assertFalse(out["passed"])
        self.assertIn("BALANCE 200.00", out["reason"])

    def test_two_account_blocks_are_refused(self):
        block = [(450, 30, "STATEMENT PAGE 1 of 1"), (480, 70, "Total Amount Due"), (490, 82, "195.50")]
        pages = [statement_page(GOOD_LINES[:2], extra=block),
                 statement_page(GOOD_LINES[2:], extra=[(450, 30, "STATEMENT PAGE 1 of 1"), (480, 70, "Total Amount Due"),
                                                        (490, 82, "-19.75")])]
        out = self.check(pages=pages)
        self.assertFalse(out["passed"])
        self.assertIn("account blocks", out["reason"])


class TestRowsAndCells(_Case):

    def assertRefused(self, rows=None, **kw):
        out = self.check(rows=rows, **kw)
        self.assertFalse(out["passed"])
        return out

    def test_each_row_or_cell_fault_is_refused(self):
        def amount(r):
            r[1]["_raw_row"]["CHARGES"] = 75.51
            r[1]["outstanding_amount"] = 75.51

        def date(r):
            r[0]["_raw_row"]["DATE"] = "08/04/26"
            r[0]["invoice_date"] = "08/04/26"

        def text(r):
            r[0]["_raw_row"]["DESCRIPTION"] = "Labour"

        def column(r):
            raw = r[0]["_raw_row"]
            raw["CHARGES"], raw["CREDITS"] = None, raw["CHARGES"]

        def missing(r):
            r.pop(2)

        def extra(r):
            r.append(copy.deepcopy(r[0]))
            r[-1]["invoice_number"] = r[-1]["_raw_row"]["INVOICE"] = "999999"

        def duplicate(r):
            r.append(copy.deepcopy(r[1]))
        for name, fn in (("wrong amount", amount), ("wrong date", date), ("wrong text cell", text),
                         ("amount in the wrong column", column), ("missing row", missing), ("extra row", extra),
                         ("duplicated row", duplicate)):
            with self.subTest(fault=name):
                rows = full_rows()
                fn(rows)
                self.assertRefused(rows)

    def test_a_printed_column_the_extraction_lacks_is_refused(self):
        rows = full_rows()
        for r in rows:
            del r["_raw_row"]["BALANCE"]
        self.assertIn("not in the extraction", self.assertRefused(rows)["reason"])


class TestNotVerified(_Case):

    def test_over_the_page_cap_is_not_verified(self):
        pages = [statement_page(GOOD_LINES)] + [[(40, 60, f"page {k} terms and conditions of sale apply here")]
                                               for k in range(prm.MAX_PAGES)]
        out = self.check(pages=pages)
        self.assertFalse(out["passed"])
        self.assertIn("not verified", out["reason"])

    def test_a_scan_ocr_cannot_read_is_not_verified(self):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 50, 50), 0)
        pix.clear_with(200)
        page.insert_image(fitz.Rect(30, 30, 300, 300), pixmap=pix)
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.close()
        doc.save(f.name)
        self.addCleanup(os.remove, f.name)
        rows = full_rows()
        out = fm.check_full_match_no_total(rows, f.name, ROWS_TOTAL, "")
        self.assertFalse(out["passed"])
        self.assertIn("not verified", out["reason"])


class TestIntake(_Case):

    def gate(self, extra=(), env=None, rows=None):
        path = self.pdf([statement_page(GOOD_LINES, extra=list(PAYMENTS_NOTE) + list(extra))])
        intake = load_intake()
        s = schema(full_rows() if rows is None else rows, None, vendor="Synthetic Parts")
        with mock.patch.dict(os.environ, env or {}), mock.patch("builtins.print"):
            return s, intake.apply_arithmetic_validation(s, intake.extract_pdf_text(path)[0], path)

    def test_after_the_no_total_rule_refuses_the_full_match_passes(self):
        s, v = self.gate()
        self.assertEqual(v["detail"]["rows_only"]["status"], "has_printed_total")
        self.assertEqual((v["status"], v["method"], v["printed"], v["difference"], v["computed"]),
                         ("matches", "pdf_full_match_no_total", None, None, ROWS_TOTAL))
        self.assertIsNone(s["statement_metadata"]["statement_total_as_printed"])
        self.assertEqual(v["detail"]["full_match_no_total"]["safety"]["result"], "none printed")

    def test_a_differing_printed_total_keeps_it_total_not_found(self):
        s, v = self.gate(extra=under_label("TOTAL DUE", "175.76"))
        self.assertEqual((v["status"], v["method"]), ("total_not_found", None))
        self.assertIn("TOTAL DUE 175.76", v["detail"]["full_match_no_total"]["reason"])

    def test_the_switch_turns_it_off(self):
        s, v = self.gate(env={fm.ENV_FLAG: "false"})
        self.assertEqual((v["status"], v["method"]), ("total_not_found", None))
        self.assertNotIn("full_match_no_total", v["detail"])

    def test_without_a_total_like_line_the_no_total_rule_still_decides(self):
        path = self.pdf([statement_page(GOOD_LINES)])
        intake = load_intake()
        s = schema(full_rows(), None, vendor="Synthetic Parts")
        with mock.patch("builtins.print"):
            v = intake.apply_arithmetic_validation(s, intake.extract_pdf_text(path)[0], path)
        self.assertEqual((v["status"], v["method"]), ("matches", "pdf_rows_no_total"))
        self.assertNotIn("full_match_no_total", v["detail"])


@unittest.skipUnless(os.path.exists(Q10), "saved replay data not present")
class TestStored(unittest.TestCase):

    def run_intake(self, sid):
        from test_text_columns import to_invoices
        st = _stored()[sid]
        if not (st.get("pdf") and os.path.exists(st["pdf"])):
            self.skipTest(f"{sid}: PDF not on disk")
        with mock.patch("builtins.print"):
            invoices = to_invoices(st["rows"], [k for k in st["keys"] if k != "confidence"])
        intake = load_intake()
        s = schema(invoices, st["printed"], vendor=st["vendor"])
        with mock.patch("builtins.print"):
            return intake.apply_arithmetic_validation(s, intake.extract_pdf_text(st["pdf"])[0], st["pdf"])

    def test_the_new_step_passes_no_stored_statement(self):
        # Only a statement with no printed total can end total_not_found: run every such stored statement
        # (with rows and a PDF) through the intake and record which ones reached the new step.
        reached = {}
        for sid, st in _stored().items():
            if st["printed"] is not None or not st["rows"] or not (st.get("pdf") and os.path.exists(st["pdf"])):
                continue
            if st["engine"] != "claude_sonnet":
                continue   # python-library rows are rebuilt by the replay, not here
            prm._PAGES_CACHE.clear()
            v = self.run_intake(sid)
            self.assertNotEqual(v["method"], fm.METHOD, sid)
            if "full_match_no_total" in (v["detail"] or {}):
                reached[sid] = v["detail"]["full_match_no_total"]["reason"]
        for sid in ("STMT-BC27722E", "STMT-2B791829", "STMT-EB62A450"):   # NYE 9-4-26: 16 pages
            self.assertIn("not verified", reached.get(sid, "not verified (not stored here)"), sid)

    def test_healey_and_lithia_keep_their_methods(self):
        for sid, method in (("STMT-1880E21C", "pdf_rows_no_total"), ("STMT-142DA134", "pdf_account_blocks")):
            with self.subTest(statement=sid):
                prm._PAGES_CACHE.clear()
                v = self.run_intake(sid)
                self.assertEqual((v["status"], v["method"]), ("matches", method))
                self.assertNotIn("full_match_no_total", v["detail"])


class TestDetailPage(unittest.TestCase):

    def render(self, outcome):
        import test_pdf_row_match as prm_tests
        page = prm_tests.TestValidationPageBadge(methodName="test_method_labels")
        intake = {"statement_id": "F", "source_file": "f.pdf", "vendor_name": "Synthetic", "statement_period": "2026-09",
                  "statement_total_as_printed": None, "validation_status": "matches", "validation_difference": None,
                  "validation_method": "pdf_full_match_no_total", "previous_balance": None, "previous_balance_source": None,
                  "ingestion_timestamp": "2026-10-01T21:00:00+00:00", "passed": True, "primary_computed": None,
                  "validation_attempts": [], "full_match_no_total": outcome}
        page._patch(get_extraction_validation_detail=lambda sid: {"intake": intake, "computed_total": None, "lines": []})
        try:
            return page._client().get("/validation/F").text
        finally:
            page.doCleanups()

    def test_the_method_and_its_safety_record_are_shown(self):
        html = self.render({"passed": True, "reason": "", "full_match": {"rows": 4, "rows_verified": 4, "columns": [{}] * 6},
                            "safety": {"total_like_amounts": [{"label": "TOTAL DUE", "page": 1, "amount": 175.75}],
                                       "result": "every printed total-like amount equals the rows"}})
        self.assertIn("PDF full match, no printed total", html)
        self.assertIn('id="full-match-no-total"', html)
        self.assertIn("4 of 4 rows and 6 columns matched cell by cell", html)
        self.assertIn("TOTAL DUE p1 $175.75 -- every printed total-like amount equals the rows", html)

    def test_none_printed_is_shown(self):
        html = self.render({"passed": True, "reason": "", "full_match": {"rows": 4, "rows_verified": 4, "columns": [{}] * 6},
                            "safety": {"total_like_amounts": [], "result": "none printed"}})
        self.assertIn("printed totals checked: none printed", html)

    def test_label(self):
        from web.deps import validation_method_label
        self.assertEqual(validation_method_label("pdf_full_match_no_total"), "PDF full match, no printed total")


if __name__ == "__main__":
    unittest.main()
