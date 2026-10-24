"""
tests/test_pdf_full_match.py

The gate's last fallback "pdf_full_match" (2026-10-16, user decision): a
pass when the extraction matches the PDF cell by cell -- every row both
ways, every printed column present, every cell in its own column -- even
though no total equation reconciles. SYNTHETIC text-layer PDFs only (the
helpers of tests/test_pdf_row_match.py).
"""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from src.validation import pdf_row_match as m  # noqa: E402
from src.validation.arithmetic_gate import try_pdf_full_match  # noqa: E402
from test_pdf_row_match import GOOD_LINES, X, _PdfCase, row, statement_page  # noqa: E402

NOT_THE_TOTAL = 999.99  # the printed total never reconciles in these tests


def full_rows(lines=GOOD_LINES):
    """Extracted rows for `lines` with every printed column in _raw_row,
    as the model returns them."""
    out = []
    for line in lines:
        charge = float(line["charge"]) if "charge" in line else None
        credit = float(line["credit"]) if "credit" in line else None
        balance = float(line["bal"])
        r = row(line["inv"], line["date"], charge, credit=credit, due=balance)
        r["_raw_row"] = {"DATE": line["date"], "INVOICE": line["inv"], "DESCRIPTION": line.get("desc"),
                         "CHARGES": charge, "CREDITS": credit, "BALANCE": balance, "confidence": 0.95}
        out.append(r)
    return out


class FullMatchCase(_PdfCase):

    def check(self, rows, lines=GOOD_LINES, extra=()):
        path = self.pdf([statement_page(lines, total="999.99", extra=extra)])
        return m.check_pdf_full_match(NOT_THE_TOTAL, rows, pdf_path=path)


class TestPasses(FullMatchCase):

    def test_every_row_and_column_matching_passes_without_any_equation(self):
        result = self.check(full_rows())
        self.assertTrue(result["passed"], result.get("reason"))
        self.assertEqual(result["computed"], 175.75)
        cols = {c["printed"]: c for c in result["columns"]}
        self.assertEqual(sorted(cols), ["BALANCE", "CHARGES", "CREDITS", "DATE", "DESCRIPTION", "INVOICE"])
        self.assertTrue(all(c["ok"] == c["cells"] == 4 for c in cols.values()), cols)

    def test_text_only_differences_pass(self):
        rows = full_rows()
        rows[0]["_raw_row"]["DESCRIPTION"] = "PARTS."      # case + punctuation
        rows[2]["_raw_row"]["DESCRIPTION"] = "  payment "  # spacing
        rows[1]["_raw_row"]["DATE"] = "2026-08-09"         # same date, other format
        rows[3]["_raw_row"]["CHARGES"] = "$30.25"          # same amount as text
        self.assertTrue(self.check(rows)["passed"])

    def test_invoice_o_and_0_tolerance_only(self):
        rows = full_rows()
        rows[0]["_raw_row"]["INVOICE"] = "1OO231"
        self.assertTrue(self.check(rows)["passed"])


class TestFails(FullMatchCase):

    def assertFails(self, rows, needle=None, **kw):
        result = self.check(rows, **kw)
        self.assertFalse(result["passed"])
        if needle:
            self.assertIn(needle, result.get("reason") or "")
        return result

    def test_printed_column_missing_from_the_extraction(self):
        # Chuck's: the PDF prints a Due column the extraction never captured.
        rows = full_rows()
        for r in rows:
            del r["_raw_row"]["BALANCE"]
        self.assertFails(rows, "printed column(s) ['BALANCE'] not in the extraction")

    def test_value_under_the_wrong_column(self):
        rows = full_rows()
        raw = rows[1]["_raw_row"]
        raw["CHARGES"], raw["BALANCE"] = raw["BALANCE"], raw["CHARGES"]
        self.assertFails(rows, "CHARGES")

    def test_amount_column_holding_text_fails(self):
        # Autoly replay (STMT-14DF18D8 etc.): the printed Due amount merged
        # into the description text -- the amount was never extracted.
        rows = full_rows()
        rows[0]["_raw_row"]["CHARGES"] = "120.00 Parts"
        self.assertFails(rows, "holds non-amount")

    def test_amount_moved_to_the_empty_neighbouring_column(self):
        rows = full_rows()
        raw = rows[0]["_raw_row"]
        raw["CHARGES"], raw["CREDITS"] = None, raw["CHARGES"]
        self.assertFails(rows, "is printed under CHARGES, not CREDITS")

    def test_wrong_sign(self):
        rows = full_rows()
        rows[0]["_raw_row"]["CHARGES"] = -120.0
        self.assertFails(rows, "CHARGES")

    def test_one_cent_off(self):
        rows = full_rows()
        rows[1]["_raw_row"]["BALANCE"] = 195.51
        self.assertFails(rows, "BALANCE")

    def test_wrong_date(self):
        rows = full_rows()
        rows[1]["_raw_row"]["DATE"] = "08/10/26"
        self.assertFails(rows, "DATE")

    def test_different_wording(self):
        rows = full_rows()
        rows[0]["_raw_row"]["DESCRIPTION"] = "Labor"
        self.assertFails(rows, "DESCRIPTION")

    def test_dropped_row(self):
        rows = full_rows()
        del rows[2]
        result = self.assertFails(rows)
        self.assertEqual(result["problem_counts"]["missing"], 1)

    def test_duplicated_row(self):
        rows = full_rows()
        rows.insert(2, copy.deepcopy(rows[1]))
        self.assertFails(rows)

    def test_extra_row(self):
        rows = full_rows()
        extra = copy.deepcopy(rows[3])
        extra["invoice_number"] = extra["_raw_row"]["INVOICE"] = "MUT90001"
        rows.append(extra)
        result = self.assertFails(rows)
        self.assertEqual(result["problem_counts"]["extra"], 1)

    def test_printed_value_without_a_header_that_was_not_extracted(self):
        lines = [dict(line) for line in GOOD_LINES]
        code = [(270, 136, "99")]  # an unlabelled code printed on the first line
        self.assertFails(full_rows(lines), extra=code)

    def test_the_same_unlabelled_value_extracted_passes(self):
        rows = full_rows()
        for r in rows:
            r["_raw_row"]["UNLABELED_TRANSACTION_CODE"] = None
        rows[0]["_raw_row"]["UNLABELED_TRANSACTION_CODE"] = "99"
        self.assertTrue(self.check(rows, extra=[(270, 136, "99")])["passed"])

    def test_rows_without_extracted_cells_are_not_applicable(self):
        rows = full_rows()
        del rows[0]["_raw_row"]
        result = self.check(rows)
        self.assertFalse(result["passed"])
        self.assertFalse(result["applicable"])

    def test_no_pdf_is_not_applicable(self):
        self.assertFalse(m.check_pdf_full_match(NOT_THE_TOTAL, full_rows(), pdf_path=None)["passed"])


class TestGateOrder(FullMatchCase):

    def validation(self, status):
        return {"status": status, "printed": NOT_THE_TOTAL, "computed": 175.75,
                "difference": round(NOT_THE_TOTAL - 175.75, 2), "method": None,
                "detail": {"attempts": [{"method": "pdf_row_match", "passed": False}]}}

    def test_runs_last_and_adds_a_pass_with_per_column_detail(self):
        path = self.pdf([statement_page(GOOD_LINES, total="999.99")])
        v = try_pdf_full_match(self.validation("mismatch"), full_rows(), path)
        self.assertEqual((v["status"], v["method"]), ("matches", "pdf_full_match"))
        attempts = v["detail"]["attempts"]
        self.assertEqual([a["method"] for a in attempts], ["pdf_row_match", "pdf_full_match"])
        self.assertTrue(attempts[-1]["columns"])
        self.assertEqual(v["detail"]["primary_difference"], round(NOT_THE_TOTAL - 175.75, 2))

    def test_a_failure_is_recorded_and_changes_nothing(self):
        path = self.pdf([statement_page(GOOD_LINES, total="999.99")])
        rows = full_rows()
        rows[0]["_raw_row"]["CHARGES"] = 120.01
        before = self.validation("mismatch")
        v = try_pdf_full_match(before, rows, path)
        self.assertEqual((v["status"], v["method"]), ("mismatch", None))
        self.assertEqual(v["detail"]["attempts"][-1]["method"], "pdf_full_match")

    def test_never_runs_on_a_pass_or_without_a_printed_total(self):
        path = self.pdf([statement_page(GOOD_LINES, total="999.99")])
        for status in ("matches", "total_not_found", "not_a_statement"):
            v = self.validation(status)
            self.assertIs(try_pdf_full_match(v, full_rows(), path), v)

    def test_label(self):
        from web.deps import validation_method_label
        self.assertEqual(validation_method_label("pdf_full_match"), "PDF full match (every row and column)")


if __name__ == "__main__":
    unittest.main()
