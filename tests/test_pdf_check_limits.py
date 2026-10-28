"""
tests/test_pdf_check_limits.py

The two limits of the gate's PDF checks (src/validation/pdf_row_match.py) as
deployment settings (2026-10-26): VIVE_PDF_CHECK_OCR_BUDGET_SECONDS (the OCR
time budget, default 30 s) and VIVE_PDF_CHECK_MAX_PAGES (the page cap,
default 12). On dev, five Oct 25 statements whose rows are right (Chuck's,
LV Honda, LV Hyundai, MB LV, LV Acura) stopped at "OCR time budget
exhausted" because dev reads PDFs 10-32x slower than a laptop.

- unset, blank, non-numeric or not positive = the default (unchanged);
- every PDF check and every reader of the PDF lines takes the setting at
  call time; an explicit budget_seconds still wins;
- the validation OCR text stays capped at 12 pages whatever the setting
  says -- that read has no time budget (the Oct 25 timeouts).

SYNTHETIC DATA ONLY: every PDF is generated here with PyMuPDF.
"""

import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import fitz

from src.validation import account_blocks
from src.validation import pdf_row_match as m

BUDGET_ENV = "VIVE_PDF_CHECK_OCR_BUDGET_SECONDS"
PAGES_ENV = "VIVE_PDF_CHECK_MAX_PAGES"

X = {"date": 40, "inv": 110, "desc": 200, "charge": 330, "credit": 410, "bal": 490}
HEADER = (("date", "DATE"), ("inv", "INVOICE"), ("desc", "DESCRIPTION"),
          ("charge", "CHARGES"), ("credit", "CREDITS"), ("bal", "BALANCE"))
LINES = [
    {"date": "08/03/26", "inv": "100231", "desc": "Parts", "charge": "120.00", "bal": "120.00"},
    {"date": "08/09/26", "inv": "100244", "desc": "Parts", "charge": "75.50", "bal": "195.50"},
]


def statement_page():
    items = [(40, 50, "SYNTHETIC PARTS SUPPLY"), (40, 62, "123 Example Road Springfield"),
             (40, 74, "STATEMENT OF ACCOUNT")]
    items += [(X[k], 120, label) for k, label in HEADER]
    y = 136
    for line in LINES:
        items += [(X[k], y, v) for k, v in line.items()]
        y += 14
    return items + [(X["desc"], y + 10, "TOTAL DUE"), (X["bal"], y + 10, "195.50")]


def terms_page(k):
    """A text-layer page (10+ words, so it is not taken for a scan) with no table."""
    return [(40, 60, f"page {k} terms and conditions of sale apply here to every order placed")]


def rows():
    return [{"invoice_number": "100231", "invoice_date": "08/03/26", "outstanding_amount": 120.0, "credit": None,
             "amount_due": 120.0},
            {"invoice_number": "100244", "invoice_date": "08/09/26", "outstanding_amount": 75.5, "credit": None,
             "amount_due": 195.5}]


class _Case(unittest.TestCase):
    def setUp(self):
        m._PAGES_CACHE.clear()
        self.addCleanup(m._PAGES_CACHE.clear)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(BUDGET_ENV, None)
        os.environ.pop(PAGES_ENV, None)

    def pdf(self, pages):
        doc = fitz.open()
        for items in pages:
            page = doc.new_page(width=612, height=792)
            for x, y, text in items:
                page.insert_text((x, y), text, fontsize=9)
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.close()
        doc.save(f.name)
        self.addCleanup(os.remove, f.name)
        return f.name


class TestSettings(_Case):

    def test_defaults_are_unchanged(self):
        self.assertEqual(m.max_pages(), 12)
        self.assertEqual(m.ocr_time_budget_seconds(), 30.0)

    def test_settings_are_read(self):
        os.environ[PAGES_ENV] = "20"
        os.environ[BUDGET_ENV] = "600"
        self.assertEqual(m.max_pages(), 20)
        self.assertEqual(m.ocr_time_budget_seconds(), 600.0)

    def test_unusable_values_keep_the_default(self):
        for value in ("", "  ", "abc", "0", "-5", "1e999x"):
            os.environ[PAGES_ENV] = value
            os.environ[BUDGET_ENV] = value
            with self.subTest(value=value):
                self.assertEqual(m.max_pages(), 12)
                self.assertEqual(m.ocr_time_budget_seconds(), 30.0)

    def test_a_fractional_page_cap_keeps_the_default(self):
        os.environ[PAGES_ENV] = "15.5"
        self.assertEqual(m.max_pages(), 12)


class TestPageCap(_Case):

    def thirteen_pages(self):
        return self.pdf([statement_page()] + [terms_page(k) for k in range(2, 14)])

    def test_thirteen_pages_are_not_verified_by_default(self):
        result = m.check_pdf_row_match(195.5, rows(), pdf_path=self.thirteen_pages())
        self.assertFalse(result["passed"])
        self.assertEqual(result["reason"], "not verified: 13 pages (cap 12)")

    def test_a_raised_cap_reads_all_thirteen_pages(self):
        os.environ[PAGES_ENV] = "20"
        result = m.check_pdf_row_match(195.5, rows(), pdf_path=self.thirteen_pages())
        self.assertTrue(result["passed"], result.get("reason"))
        self.assertEqual(result["pages"], 13)

    def test_a_lowered_cap_refuses(self):
        os.environ[PAGES_ENV] = "1"
        path = self.pdf([statement_page(), terms_page(2)])
        with self.assertRaises(m.NotVerified) as ctx:
            m.read_pdf_lines(path)
        self.assertEqual(str(ctx.exception), "2 pages (cap 1)")

    def test_a_cached_read_is_not_reused_under_another_cap(self):
        path = self.pdf([statement_page(), terms_page(2)])
        os.environ[PAGES_ENV] = "1"
        with self.assertRaises(m.NotVerified):
            m.read_pdf_lines(path)
        del os.environ[PAGES_ENV]
        self.assertEqual(len(m.read_pdf_lines(path)), 2)

    def test_account_blocks_uses_the_same_cap(self):
        path = self.thirteen_pages()
        self.assertEqual(account_blocks.check_pdf_account_blocks(rows(), path, 195.5)["reason"], "13 pages (cap 12)")
        os.environ[PAGES_ENV] = "20"
        self.assertNotIn("cap", account_blocks.check_pdf_account_blocks(rows(), path, 195.5)["reason"])


class TestOcrBudget(_Case):

    def recorded_budgets(self, calls):
        seen = []

        def reader(pdf_path, budget_seconds, max_workers, *rest):
            seen.append(budget_seconds)
            raise m.NotVerified("stop here")
        path = self.pdf([statement_page()])
        with mock.patch.object(m, "_read_pdf_lines", reader):
            for call in calls:
                m._PAGES_CACHE.clear()
                call(path)
        return seen

    CALLS = (
        lambda p: m.check_pdf_row_match(195.5, rows(), pdf_path=p),
        lambda p: m.check_pdf_store_sections(195.5, rows(), pdf_path=p),
        lambda p: m.check_pdf_full_match(195.5, [dict(r, _raw_row={"x": 1}) for r in rows()], pdf_path=p),
        lambda p: m.check_rows_only(rows(), p),
        lambda p: _swallow(m.read_pdf_lines, p),
    )

    def test_every_check_takes_the_budget_setting(self):
        os.environ[BUDGET_ENV] = "600"
        self.assertEqual(self.recorded_budgets(self.CALLS), [600.0] * len(self.CALLS))

    def test_without_a_setting_the_budget_is_30_seconds(self):
        self.assertEqual(self.recorded_budgets(self.CALLS), [30.0] * len(self.CALLS))

    def test_an_explicit_budget_still_wins(self):
        os.environ[BUDGET_ENV] = "600"
        seen = self.recorded_budgets([lambda p: m.check_pdf_row_match(195.5, rows(), pdf_path=p, budget_seconds=5)])
        self.assertEqual(seen, [5])

    def test_a_tiny_budget_on_a_scan_is_not_verified(self):
        path = self.pdf([[], []])  # two blank pages -> both go to OCR

        def slow(pdf_path, page_index, deadline):
            time.sleep(0.5)
            if time.monotonic() > deadline:
                raise m.NotVerified("OCR time budget exhausted")
            return [], 0
        os.environ[BUDGET_ENV] = "0.2"
        with mock.patch.object(m, "_ocr_page", slow):
            result = m.check_pdf_row_match(10.0, rows()[:1], pdf_path=path)
        self.assertFalse(result["passed"])
        self.assertTrue(result["reason"].startswith("not verified"), result["reason"])


def _swallow(fn, *a):
    try:
        return fn(*a)
    except m.NotVerified:
        return None


class TestValidationOcrTextCap(_Case):
    """The intake's validation OCR text has no time budget, so it keeps its own 12-page cap."""

    def test_a_raised_check_cap_does_not_raise_the_ocr_text_cap(self):
        from src.rerun.in_place import load_intake
        intake = load_intake()
        os.environ[PAGES_ENV] = "20"
        path = self.pdf([[] for _ in range(16)])
        with mock.patch.object(intake, "ocr_pdf_text", return_value="Total due 100.00") as ocr, \
                mock.patch("builtins.print"):
            text, source = intake._validation_text("", path, {"statement_total_as_printed": None}, True)
        self.assertEqual((text, source), ("", None))
        ocr.assert_not_called()
        self.assertEqual(intake.OCR_TEXT_MAX_PAGES, 12)


if __name__ == "__main__":
    unittest.main()
