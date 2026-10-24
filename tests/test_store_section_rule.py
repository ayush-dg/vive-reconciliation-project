"""Complete-section rule of pdf_store_sections (src/validation/pdf_row_match.py _vendor_section, 2026-10-19).

A statement passes when its rows are ONE complete store section of its own vendor (printed row numbers
1..N, rows sum to the printed Amount Due to the cent) and every printed line it did not extract sits
under a DIFFERENT, explicitly headed section. Synthetic pages reuse test_pdf_row_match's store builder;
TestLvHonda uses the stored extraction and PDF in scratchpad/ (real data, git-ignored; skipped where
absent)."""
import copy
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_pdf_row_match import STORE_A, STORE_B_PART, _PdfCase, row, store_page, store_rows  # noqa: E402

from src.validation import arithmetic_gate as g  # noqa: E402
from src.validation import pdf_row_match as m  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Q10 = os.path.join(REPO, "scratchpad", "saved_from_temp_20261019", "replay_inputs", "q10_rows.json")
SECTIONS = [("Store A", 3, "797.39", STORE_A), ("Store B", 5, "300.00", STORE_B_PART)]


class TestCompleteSection(_PdfCase):

    def check(self, sections=SECTIONS, rows=None, vendor="Store A"):
        path = self.pdf([store_page(sections)])
        return m.check_pdf_store_sections(9999.99, store_rows(STORE_A) if rows is None else rows,
                                          pdf_path=path, vendor_name=vendor)

    def test_the_vendors_complete_section_passes_and_the_other_sections_lines_are_recorded(self):
        out = self.check()
        self.assertTrue(out["passed"], out.get("section_rule") or out.get("reason"))
        self.assertEqual(out["computed"], 797.39)
        self.assertEqual(out["section_used"], {"section": "Store A", "invoices": 3, "amount_due": 797.39, "rows": 3})
        self.assertEqual([(l["section"], l["page"]) for l in out["lines_ignored"]], [("Store B", 1), ("Store B", 1)])

    def test_case_and_punctuation_of_the_vendor_name_do_not_matter(self):
        self.assertTrue(self.check(vendor="STORE-A")["passed"])

    def test_without_a_vendor_name_the_rule_does_not_apply(self):
        out = self.check(vendor=None)
        self.assertFalse(out["passed"])
        self.assertEqual(out["problem_counts"]["missing"], 2)

    def test_a_vendor_name_not_matching_the_section_fails(self):
        out = self.check(vendor="Store C")
        self.assertFalse(out["passed"])
        self.assertIn("is not the statement's vendor", out["section_rule"])

    def test_an_unmatched_line_under_the_same_section_name_fails(self):
        out = self.check(sections=[("Store A", 3, "797.39", STORE_A), ("Store A", 5, "300.00", STORE_B_PART)])
        self.assertFalse(out["passed"])

    def test_a_missing_row_of_the_section_fails(self):
        out = self.check(rows=store_rows(STORE_A[:2]))
        self.assertFalse(out["passed"])
        self.assertIn("not complete", out["section_rule"])

    def test_a_wrong_digit_fails(self):
        rows = store_rows(STORE_A)
        rows[1]["outstanding_amount"] = 533.30
        self.assertFalse(self.check(rows=rows)["passed"])

    def test_a_row_in_the_wrong_column_fails(self):
        rows = store_rows(STORE_A)
        rows[0] = row("367814-1", "08/01/26", credit=150.59, due=150.59)
        self.assertFalse(self.check(rows=rows)["passed"])

    def test_the_section_sum_off_by_one_cent_fails(self):
        out = self.check(sections=[("Store A", 3, "797.40", STORE_A), ("Store B", 5, "300.00", STORE_B_PART)])
        self.assertFalse(out["passed"])
        self.assertIn("printed Amount Due 797.40", out["section_rule"])

    def test_rows_from_two_sections_fail(self):
        out = self.check(rows=store_rows(STORE_A + STORE_B_PART[:1]))
        self.assertFalse(out["passed"])
        self.assertIn("not all under one", out["section_rule"])

    def test_an_already_complete_extraction_takes_the_old_path_unchanged(self):
        out = self.check(rows=store_rows(STORE_A + STORE_B_PART))
        self.assertTrue(out["passed"])
        self.assertNotIn("section_used", out)


class TestUnmatchedLineWithoutHeader(unittest.TestCase):
    """_vendor_section on a hand-built table: an unmatched transaction line under no store header."""

    def table(self, other_store):
        store = {"name": "Store A", "count": 1, "amount_due": 10.0}
        own = {"page": 1, "text": "1 08/01/26 X1 $10.00", "is_transaction": True, "store": store,
               "row_number_printed": 1, "money": [{"value": 10.0, "role": "charge"}]}
        own["_used_money"] = [id(own["money"][0])]
        stray = {"page": 1, "text": "08/02/26 X2 $5.00", "is_transaction": True,
                 "store": None if other_store is None else {"name": other_store, "count": 9, "amount_due": 1.0}}
        return [own, stray], [({}, own)], [{"problem": "missing"}]

    def test_no_header_fails(self):
        table, matches, failures = self.table(None)
        section, why = m._vendor_section(table, matches, failures, "Store A")
        self.assertIsNone(section)
        self.assertIn("under no store header", why)

    def test_another_named_section_passes(self):
        table, matches, failures = self.table("Store Z")
        section, why = m._vendor_section(table, matches, failures, "Store A")
        self.assertIsNotNone(section, why)

    def test_a_wrong_or_extra_row_never_takes_the_rule(self):
        table, matches, _ = self.table("Store Z")
        for problem in ("wrong", "extra", "unverifiable"):
            section, _ = m._vendor_section(table, matches, [{"problem": "missing"}, {"problem": problem}], "Store A")
            self.assertIsNone(section, problem)


@unittest.skipUnless(os.path.exists(Q10), "saved replay data not present")
class TestLvHonda(unittest.TestCase):
    SID = "STMT-4E854578"

    @classmethod
    def setUpClass(cls):
        with open(Q10, encoding="utf-8") as f:
            cls.st = json.load(f)[cls.SID]
        if not (cls.st.get("pdf") and os.path.exists(cls.st["pdf"])):
            raise unittest.SkipTest("LV Honda PDF not on disk")

    def gate(self, change=None, vendor=None):
        from src.ai.claude_sonnet_client import ClaudeSonnetClient
        raw = copy.deepcopy(self.st["rows"])
        if change:
            change(raw)
        cols = [k for k in self.st["keys"] if k != "confidence"]
        with mock.patch("builtins.print"):
            invoices = ClaudeSonnetClient.__new__(ClaudeSonnetClient)._rows_to_invoices(raw, cols)[0]
        return g.validate_with_fallbacks(self.st["printed"], g.compute_statement_total_from_invoices(invoices), invoices,
                                         pdf_path=self.st["pdf"], vendor_name=vendor or self.st["vendor"])

    def test_the_stored_56_honda_rows_pass_on_their_section(self):
        v = self.gate()
        self.assertEqual((v["status"], v["method"], v["computed"]), ("matches", "pdf_store_sections", 21521.17))
        self.assertEqual(v["detail"]["section_used"],
                         {"section": "Lehigh Valley Honda", "invoices": 56, "amount_due": 21521.17, "rows": 56})
        self.assertEqual(len(v["detail"]["lines_ignored"]), 11)
        self.assertEqual({l["section"] for l in v["detail"]["lines_ignored"]}, {"Lehigh Valley Hyundai"})

    def test_another_vendor_name_does_not_pass(self):
        self.assertEqual(self.gate(vendor="Lehigh Valley Hyundai")["status"], "mismatch")

    def test_mutations_fail(self):
        def wrong_column(raw):   # 601849-5's 180.80 purchase read as a payment
            raw[0]["Payments"], raw[0]["Purchases"] = raw[0]["Purchases"], None

        def digit(raw):
            raw[10]["Purchases"] = 137.04

        def drop(raw):
            raw.pop(20)
        for name, fn in (("wrong column", wrong_column), ("changed digit", digit), ("dropped row", drop)):
            with self.subTest(mutation=name):
                self.assertEqual(self.gate(fn)["status"], "mismatch")


    def test_a_negative_purchase_read_as_a_payment_is_the_same_signed_amount(self):
        # Known limit of the row checks (not of this rule): 601815-1R prints -$63.46 under Purchases; as a
        # 63.46 payment it reduces the balance identically, and lines are compared by signed amount.
        def move(raw):
            raw[5]["Payments"], raw[5]["Purchases"] = abs(raw[5]["Purchases"]), None
        self.assertEqual(self.gate(move)["status"], "matches")


class TestDetailPage(unittest.TestCase):

    def test_the_section_is_shown(self):
        import test_pdf_row_match as prm
        page = prm.TestValidationPageBadge(methodName="test_method_labels")
        intake = {"statement_id": "L", "source_file": "l.pdf", "vendor_name": "Lehigh Valley Honda",
                  "statement_period": "2026-08", "statement_total_as_printed": 168640.83, "validation_status": "matches",
                  "validation_difference": 147119.66, "validation_method": "pdf_store_sections", "previous_balance": None,
                  "previous_balance_source": None, "ingestion_timestamp": "2026-10-01T21:00:00+00:00", "passed": True,
                  "primary_computed": 21521.17, "validation_attempts": [],
                  "section_used": {"section": "Lehigh Valley Honda", "invoices": 56, "amount_due": 21521.17, "rows": 56},
                  "lines_ignored": [{"page": 3, "section": "Lehigh Valley Hyundai", "text": "1 08/01/26 367814-1"}] * 11}
        page._patch(get_extraction_validation_detail=lambda sid: {"intake": intake, "computed_total": None, "lines": []})
        try:
            html = page._client().get("/validation/L").text
        finally:
            page.doCleanups()
        self.assertIn('id="section-used"', html)
        self.assertIn("Lehigh Valley Honda: 56 of 56 invoices", html)
        self.assertIn("11 printed lines of other sections set aside: Lehigh Valley Hyundai", html)


if __name__ == "__main__":
    unittest.main()
