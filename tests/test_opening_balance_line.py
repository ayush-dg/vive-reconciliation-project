"""Opening-balance line (src/validation/pdf_row_match.py _opening_balance_line, 2026-10-19).

A statement's first line on the text layer printing only a date and one amount under BALANCE is the
opening balance, not a missing row -- only when every other line is matched one-to-one and
opening + rows = printed to the cent. Synthetic PDFs reuse test_pdf_row_match's builder; TestTownFair
uses the stored extraction and PDF in scratchpad/ (real data, git-ignored; skipped where absent)."""
import copy
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_pdf_row_match import _PdfCase, row, statement_page  # noqa: E402

from src.validation import arithmetic_gate as g  # noqa: E402
from src.validation import pdf_row_match as m  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Q10 = os.path.join(REPO, "scratchpad", "saved_from_temp_20261019", "replay_inputs", "q10_rows.json")

OPENING = {"date": "07/31/26", "bal": "887.00"}
CHARGE = {"date": "08/20/26", "inv": "728380", "desc": "Parts", "charge": "209.00"}
PAYMENT = {"date": "08/24/26", "inv": "550824", "desc": "Payment", "credit": "887.00"}


def rows():
    return [row("728380", "08/20/26", 209.0), row("550824", "08/24/26", credit=887.0)]


class TestOpeningBalanceLine(_PdfCase):

    def check(self, lines, total, invoices=None, extra=()):
        path = self.pdf([statement_page(lines, total=total, extra=extra)])
        return m.check_pdf_row_match(float(total.replace(",", "")), invoices if invoices is not None else rows(),
                                     pdf_path=path)

    def test_a_verified_opening_line_passes_with_its_record(self):
        out = self.check([OPENING, CHARGE, PAYMENT], "209.00")
        self.assertTrue(out["passed"], out.get("reason"))
        self.assertEqual((out["equation"], out["computed"]), ("opening_balance_line", 209.0))
        self.assertEqual({k: out["opening_balance_line"][k] for k in ("page", "date", "amount")},
                         {"page": 1, "date": "2026-07-31", "amount": 887.0})

    def test_without_the_opening_line_nothing_changes(self):
        out = self.check([CHARGE, PAYMENT], "-678.00")
        self.assertTrue(out["passed"], out.get("reason"))
        self.assertEqual(out["equation"], "rows")
        self.assertNotIn("opening_balance_line", out)

    def test_the_opening_line_not_first_fails(self):
        out = self.check([CHARGE, OPENING, PAYMENT], "209.00")
        self.assertFalse(out["passed"])
        self.assertIn("PDF line not extracted", json.dumps(out["offending_rows"]))

    def test_an_opening_line_with_a_reference_fails(self):
        out = self.check([{**OPENING, "inv": "100000"}, CHARGE, PAYMENT], "209.00")
        self.assertFalse(out["passed"])

    def test_an_opening_line_with_a_label_or_text_fails(self):
        out = self.check([{**OPENING, "desc": "Forward"}, CHARGE, PAYMENT], "209.00")
        self.assertFalse(out["passed"])

    def test_the_amount_in_the_charges_column_fails(self):
        out = self.check([{"date": "07/31/26", "charge": "887.00"}, CHARGE, PAYMENT], "209.00")
        self.assertFalse(out["passed"])

    def test_the_equation_off_by_one_cent_fails(self):
        out = self.check([OPENING, CHARGE, PAYMENT], "209.01")
        self.assertFalse(out["passed"])
        self.assertIn("opening_balance_line 209.00", out["reason"])

    def test_an_extra_unmatched_line_besides_the_opening_fails(self):
        out = self.check([OPENING, CHARGE, PAYMENT, {"date": "08/28/26", "inv": "728399", "charge": "10.00"}], "219.00")
        self.assertFalse(out["passed"])

    def test_a_dropped_row_fails(self):
        out = self.check([OPENING, CHARGE, PAYMENT], "209.00", invoices=rows()[:1])
        self.assertFalse(out["passed"])

    def test_a_changed_digit_fails(self):
        bad = rows()
        bad[0]["outstanding_amount"] = 290.0
        out = self.check([OPENING, CHARGE, PAYMENT], "209.00", invoices=bad)
        self.assertFalse(out["passed"])

    def test_a_row_in_the_wrong_column_fails(self):
        bad = rows()
        bad[1] = row("550824", "08/24/26", 887.0)   # the payment read as a charge
        out = self.check([OPENING, CHARGE, PAYMENT], "209.00", invoices=bad)
        self.assertFalse(out["passed"])

    def test_a_labelled_previous_balance_elsewhere_fails(self):
        out = self.check([OPENING, CHARGE, PAYMENT], "209.00", extra=[(200, 60, "PREVIOUS BALANCE 887.00")])
        self.assertFalse(out["passed"])
        self.assertNotIn("opening_balance_line", out)

    def test_an_ocr_line_is_never_an_opening(self):
        path = self.pdf([statement_page([OPENING, CHARGE, PAYMENT], total="209.00")])
        table = m.build_table(m.read_pdf_lines(path))
        matches, failures, _ = m.match_rows(rows(), table)
        opening = m._opening_balance_line(table, matches, failures)
        self.assertIsNotNone(opening)
        opening["source"] = "ocr"
        self.assertIsNone(m._opening_balance_line(table, matches, failures))

    def test_the_gate_lifts_the_record_into_the_detail(self):
        path = self.pdf([statement_page([OPENING, CHARGE, PAYMENT], total="209.00")])
        invoices = rows()
        v = g.validate_with_fallbacks(209.0, g.compute_statement_total_from_invoices(invoices), invoices, pdf_path=path)
        self.assertEqual((v["status"], v["method"]), ("matches", "pdf_row_match"))
        self.assertEqual(v["detail"]["opening_balance_line"]["amount"], 887.0)


@unittest.skipUnless(os.path.exists(Q10), "saved replay data not present")
class TestTownFair(unittest.TestCase):
    SID = "STMT-00DDF55B"

    @classmethod
    def setUpClass(cls):
        with open(Q10, encoding="utf-8") as f:
            cls.st = json.load(f)[cls.SID]
        if not (cls.st.get("pdf") and os.path.exists(cls.st["pdf"])):
            raise unittest.SkipTest("Town Fair PDF not on disk")

    def gate(self, change=None):
        from src.ai.claude_sonnet_client import ClaudeSonnetClient
        raw = copy.deepcopy(self.st["rows"])
        if change:
            change(raw)
        cols = [k for k in self.st["keys"] if k != "confidence"]
        with mock.patch("builtins.print"):
            invoices = ClaudeSonnetClient.__new__(ClaudeSonnetClient)._rows_to_invoices(raw, cols)[0]
        return g.validate_with_fallbacks(self.st["printed"], g.compute_statement_total_from_invoices(invoices),
                                         invoices, pdf_path=self.st["pdf"])

    def test_town_fair_passes_on_its_opening_line(self):
        v = self.gate()
        self.assertEqual((v["status"], v["method"], v["computed"]), ("matches", "pdf_row_match", 209.0))
        self.assertEqual({k: v["detail"]["opening_balance_line"][k] for k in ("page", "date", "amount")},
                         {"page": 1, "date": "2026-07-31", "amount": 887.0})

    def test_mutations_of_town_fair_fail(self):
        def wrong_column(raw):
            raw[1]["CHARGES"], raw[1]["CREDITS"] = raw[1]["CREDITS"], None

        def digit(raw):
            raw[0]["CHARGES"] = 290.0

        def drop_charge(raw):
            raw.pop(0)
        for name, fn in (("wrong column", wrong_column), ("changed digit", digit), ("dropped charge row", drop_charge)):
            with self.subTest(mutation=name):
                self.assertEqual(self.gate(fn)["status"], "mismatch")

    def test_dropping_the_payment_row_is_a_known_gap_of_the_primary_check_not_of_this_rule(self):
        # Without the 887.00 payment, charges - credits = 209.00 = printed: the PRIMARY check passes it
        # (it did before this rule too -- the payment equals the opening it pays). The opening-balance rule
        # itself refuses: two printed lines are then unmatched.
        v = self.gate(lambda raw: raw.pop(1))
        self.assertEqual((v["status"], v["method"]), ("matches", "primary"))
        self.assertNotIn("opening_balance_line", v.get("detail") or {})


class TestDetailPage(unittest.TestCase):

    def test_the_opening_line_is_shown(self):
        import test_pdf_row_match as prm
        page = prm.TestValidationPageBadge(methodName="test_method_labels")
        intake = {"statement_id": "T", "source_file": "t.pdf", "vendor_name": "Town Fair", "statement_period": "2026-08",
                  "statement_total_as_printed": 209.0, "validation_status": "matches", "validation_difference": 0.0,
                  "validation_method": "pdf_row_match", "previous_balance": None, "previous_balance_source": None,
                  "ingestion_timestamp": "2026-10-01T21:00:00+00:00", "passed": True, "primary_computed": -678.0,
                  "validation_attempts": [], "opening_balance_line": {"page": 1, "date": "2026-07-31", "amount": 887.0}}
        page._patch(get_extraction_validation_detail=lambda sid: {"intake": intake, "computed_total": None, "lines": []})
        try:
            html = page._client().get("/validation/T").text
        finally:
            page.doCleanups()
        self.assertIn('id="opening-balance-line"', html)
        self.assertIn("printed alone under Balance on 2026-07-31, page 1", html)


if __name__ == "__main__":
    unittest.main()
