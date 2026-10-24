"""A printed invoice-net line extracted as a row (src/validation/net_lines.py, wired into
notebooks/01_document_intake.py after every other correction, 2026-10-21).

Synthetic tests build a text-layer Reynolds-style statement with PyMuPDF: the main table
(DATE SOURCE INVOICE REFERENCE DESCRIPTION AMOUNT AGE) and the remittance stub (DATE INVOICE BALANCE) on
the same lines, with an invoice's net printed on a line of its own under its rows.

Two stored statements are expected to change (user decision 2026-10-21): Blaise Alexander Hyundai
Mazda STMT-36ECEA09 (a scan, read by Tesseract) and Goodwins Chevrolet Mazda STMT-57632B0C (text layer,
the same Reynolds layout; its PDF also passes as STMT-05FA5A0D). TestBlaise / TestGoodwins /
TestOnlyBlaiseAndGoodwins use the stored extractions and PDFs in scratchpad/ (real data, git-ignored;
skipped where absent)."""
import copy
import os
import sys
import tempfile
import unittest
from unittest import mock

import fitz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_oct1_intake_worker_web import load_intake  # noqa: E402
from test_text_columns import Q10, _stored, schema, to_invoices  # noqa: E402

from src.validation import net_lines as nl  # noqa: E402
from src.validation import pdf_row_match as prm  # noqa: E402

BLAISE = "STMT-36ECEA09"
GOODWINS = "STMT-57632B0C"
COLS = ["DATE", "SOURCE", "INVOICE", "REFERENCE", "DESCRIPTION", "AMOUNT", "AGE IN DAYS"]
X = {"DATE": 30, "SOURCE": 70, "INVOICE": 100, "REFERENCE": 170, "DESCRIPTION": 250, "AMOUNT": 320, "AGE IN DAYS": 365,
     "S_DATE": 400, "S_INVOICE": 440, "S_BALANCE": 550}
# (main-table cells, stub cells or None) per printed line
LINES = [
    ({"DATE": "07-23", "SOURCE": "5", "INVOICE": "HYW38880", "REFERENCE": "14701", "AMOUNT": "-288.05"},
     ("07-23", "HYW38880", "-288.05")),
    ({"DATE": "07-23", "SOURCE": "4", "INVOICE": "HYW39227-1", "REFERENCE": "CMHYW39227-1", "AMOUNT": "-545.46"}, None),
    ({"DATE": "07-23", "SOURCE": "4", "INVOICE": "HYW39227-1", "DESCRIPTION": "1", "AMOUNT": "634.54"}, None),
    ({"AMOUNT": "89.08", "AGE IN DAYS": "33"}, ("07-23", "HYW39227-1", "89.08")),
    ({"DATE": "07-23", "SOURCE": "4", "INVOICE": "MAW39287", "REFERENCE": "MAW39287", "AMOUNT": "639.51", "AGE IN DAYS": "33"},
     ("07-23", "MAW39287", "639.51")),
]
PRINTED = 440.54   # -288.05 - 545.46 + 634.54 + 639.51 (the net line not counted)


def statement_pdf(lines=LINES, extra=()):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for x, text in ((30, "DATE"), (70, "SOURCE"), (100, "INVOICE"), (170, "REFERENCE"), (250, "DESCRIPTION"),
                    (320, "AMOUNT"), (365, "AGE"), (400, "DATE"), (440, "INVOICE"), (550, "BALANCE")):
        page.insert_text((x, 100), text, fontsize=7)
    y = 116
    for main, stub in lines:
        for key, value in main.items():
            page.insert_text((X[key], y), value, fontsize=8)
        if stub:
            for key, value in zip(("S_DATE", "S_INVOICE", "S_BALANCE"), stub):
                page.insert_text((X[key], y), value, fontsize=8)
        y += 12
    page.insert_text((320, y + 20), "PAY THIS AMOUNT", fontsize=7)
    for x, yy, text in extra:
        page.insert_text((x, yy), text, fontsize=8)
    f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    f.close()
    doc.save(f.name)
    return f.name


def raw_rows(lines=LINES, date_on_net="07-23"):
    """The extraction's rows: one per printed line; the net line given the invoice's date (not printed)."""
    rows = []
    for main, _ in lines:
        row = {c: None for c in COLS}
        row.update({k: v for k, v in main.items()})
        row["AMOUNT"] = float(main["AMOUNT"])
        if row.get("AGE IN DAYS"):
            row["AGE IN DAYS"] = int(row["AGE IN DAYS"])
        if not main.get("DATE"):
            row["DATE"] = date_on_net
        rows.append(row)
    return rows


class _Case(unittest.TestCase):
    def setUp(self):
        prm._PAGES_CACHE.clear()

    def invoices(self, rows):
        with mock.patch("builtins.print"):
            return to_invoices(rows, COLS)

    def plan(self, rows=None, lines=LINES, extra=()):
        path = statement_pdf(lines, extra)
        self.addCleanup(os.remove, path)
        return nl.plan_net_line_drop(self.invoices(rows or raw_rows(lines)), path)


class TestSynthetic(_Case):

    def test_the_net_line_is_planned_with_the_rows_it_nets(self):
        plan = self.plan()
        self.assertTrue(plan["applicable"], plan["reason"])
        drop = nl.record(plan)
        self.assertEqual((drop["row_number"], drop["amount"], drop["date_extracted"], drop["invoice_number"]),
                         (4, 89.08, "07-23", "HYW39227-1"))
        self.assertEqual([(r["row_number"], r["amount"]) for r in drop["nets_rows"]], [(2, -545.46), (3, 634.54)])

    def test_an_amount_one_cent_off_the_net_is_kept(self):
        lines = copy.deepcopy(LINES)
        lines[3] = ({"AMOUNT": "89.09", "AGE IN DAYS": "33"}, ("07-23", "HYW39227-1", "89.09"))
        self.assertEqual(self.plan(lines=lines)["reason"], nl.NOT_APPLICABLE)

    def test_a_row_carrying_an_invoice_number_is_kept(self):
        rows = raw_rows()
        rows[3]["INVOICE"] = "HYW39227-1"
        self.assertEqual(self.plan(rows=rows)["reason"], nl.NOT_APPLICABLE)

    def test_a_row_carrying_a_reference_or_description_is_kept(self):
        for key in ("REFERENCE", "DESCRIPTION"):
            with self.subTest(cell=key):
                rows = raw_rows()
                rows[3][key] = "X1"
                self.assertEqual(self.plan(rows=rows)["reason"], nl.NOT_APPLICABLE)

    def test_a_printed_line_carrying_a_date_is_kept(self):
        lines = copy.deepcopy(LINES)
        lines[3] = ({"DATE": "07-23", "AMOUNT": "89.08", "AGE IN DAYS": "33"}, ("07-23", "HYW39227-1", "89.08"))
        plan = self.plan(rows=raw_rows(), lines=lines)
        self.assertFalse(plan["applicable"])
        self.assertIn("nothing before it", plan["reason"])

    def test_two_net_lines_are_kept(self):
        lines = copy.deepcopy(LINES) + [
            ({"DATE": "07-24", "SOURCE": "4", "INVOICE": "HYW40000", "REFERENCE": "CMHYW40000", "AMOUNT": "-10.00"}, None),
            ({"DATE": "07-24", "SOURCE": "4", "INVOICE": "HYW40000", "AMOUNT": "30.00"}, None),
            ({"AMOUNT": "20.00", "AGE IN DAYS": "32"}, ("07-24", "HYW40000", "20.00"))]
        plan = self.plan(lines=lines)
        self.assertFalse(plan["applicable"])
        self.assertIn("2 rows look like invoice-net lines", plan["reason"])

    def test_the_net_of_rows_from_two_different_invoices_is_kept(self):
        lines = copy.deepcopy(LINES)
        lines[1] = ({"DATE": "07-23", "SOURCE": "4", "INVOICE": "HYW39226", "REFERENCE": "HYW39226", "AMOUNT": "-545.46"}, None)
        self.assertEqual(self.plan(lines=lines)["reason"], nl.NOT_APPLICABLE)

    def test_without_the_amount_on_the_stub_it_is_kept(self):
        lines = copy.deepcopy(LINES)
        lines[3] = ({"AMOUNT": "89.08", "AGE IN DAYS": "33"}, None)
        plan = self.plan(lines=lines)
        self.assertFalse(plan["applicable"])
        self.assertIn("not printed again with invoice", plan["reason"])

    def test_not_directly_under_the_invoices_rows_it_is_kept(self):
        lines = copy.deepcopy(LINES)
        lines.insert(3, ({"DATE": "07-23", "SOURCE": "4", "INVOICE": "MAW39999", "AMOUNT": "5.00"}, None))
        plan = self.plan(rows=raw_rows(), lines=lines)   # the PDF prints another line between them
        self.assertFalse(plan["applicable"])
        self.assertIn("does not print the invoice's last row", plan["reason"])

    def test_without_a_pdf_it_is_kept(self):
        self.assertFalse(nl.plan_net_line_drop(self.invoices(raw_rows()), None)["applicable"])


class TestIntake(_Case):

    def gate(self, printed=PRINTED, env=None, lines=LINES):
        path = statement_pdf(lines)
        self.addCleanup(os.remove, path)
        intake = load_intake()
        s = schema(self.invoices(raw_rows(lines)), printed, vendor="Synthetic Dealer")
        with mock.patch.dict(os.environ, env or {}), mock.patch("builtins.print"):
            return s, intake.apply_arithmetic_validation(s, intake.extract_pdf_text(path)[0], path)

    def test_the_row_is_dropped_only_when_the_gate_then_passes(self):
        s, v = self.gate()
        self.assertEqual((v["status"], v["method"], v["computed"], v["difference"]), ("matches", "primary", PRINTED, 0.0))
        self.assertEqual(len(s["invoices"]), 4)
        self.assertEqual(v["detail"]["net_line_drops"][0]["row_number"], 4)

    def test_if_the_rest_still_does_not_pass_nothing_changes(self):
        s, v = self.gate(printed=PRINTED + 1)
        self.assertEqual(v["status"], "mismatch")
        self.assertEqual(len(s["invoices"]), 5)
        self.assertIn("still do not pass", v["detail"]["net_line_check"]["reason"])

    def test_the_switch_turns_it_off(self):
        s, v = self.gate(env={nl.ENV_FLAG: "false"})
        self.assertEqual((v["status"], len(s["invoices"])), ("mismatch", 5))
        self.assertNotIn("net_line_drops", v["detail"] or {})


@unittest.skipUnless(os.path.exists(Q10), "saved replay data not present")
class _Stored(_Case):
    SID = None

    @classmethod
    def setUpClass(cls):
        if cls.SID is None:
            raise unittest.SkipTest("base class")
        cls.st = _stored()[cls.SID]
        if not (cls.st.get("pdf") and os.path.exists(cls.st["pdf"])):
            raise unittest.SkipTest(f"{cls.SID} PDF not on disk")

    def gate(self, change=None):
        rows = copy.deepcopy(self.st["rows"])
        if change:
            change(rows)
        invoices = self.invoices(rows)
        intake = load_intake()
        s = schema(invoices, self.st["printed"], vendor=self.st["vendor"])
        with mock.patch("builtins.print"):
            return s, intake.apply_arithmetic_validation(s, intake.extract_pdf_text(self.st["pdf"])[0], self.st["pdf"])

    def assert_fails(self, v):
        self.assertEqual(v["status"], "mismatch")
        self.assertNotIn("net_line_drops", v["detail"])


class TestBlaise(_Stored):
    SID = BLAISE

    def test_blaise_passes_with_exactly_the_net_line_dropped(self):
        s, v = self.gate()
        self.assertEqual((v["status"], v["method"], v["printed"], v["computed"], v["difference"]),
                         ("matches", "primary", 3969.44, 3969.44, 0.0))
        drops = v["detail"]["net_line_drops"]
        self.assertEqual([(d["row_number"], d["amount"], d["invoice_number"], d["page"]) for d in drops],
                         [(4, 89.08, "HYW39227-1", 1)])
        self.assertEqual([r["row_number"] for r in drops[0]["nets_rows"]], [2, 3])
        self.assertEqual(len(s["invoices"]), 12)
        self.assertNotIn(4, [i["row_number"] for i in s["invoices"]])

    def test_mutations_fail(self):
        def digit(rows):
            rows[4]["AMOUNT"] = 639.57

        def drop_real_row(rows):
            rows.pop(6)

        def duplicate(rows):
            rows.insert(5, dict(rows[5]))

        def other_sign(rows):
            rows[1]["AMOUNT"] = 545.46
        for name, fn in (("changed digit", digit), ("dropped real row", drop_real_row), ("duplicated row", duplicate),
                         ("amount moved to the other sign", other_sign)):
            with self.subTest(mutation=name):
                self.assert_fails(self.gate(fn)[1])


class TestGoodwins(_Stored):
    SID = GOODWINS

    def test_goodwins_passes_with_exactly_the_net_line_dropped(self):
        s, v = self.gate()
        self.assertEqual((v["status"], v["method"], v["printed"], v["computed"], v["difference"]),
                         ("matches", "primary", 3321.31, 3321.31, 0.0))
        drops = v["detail"]["net_line_drops"]
        self.assertEqual([(d["row_number"], d["amount"], d["invoice_number"], d["page"]) for d in drops],
                         [(5, 2573.51, "CVW357073", 1)])
        self.assertEqual([(r["row_number"], r["amount"]) for r in drops[0]["nets_rows"]], [(3, -506.33), (4, 3079.84)])
        self.assertEqual([i["row_number"] for i in s["invoices"]], [1, 2, 3, 4])

    def test_mutations_fail(self):
        def digit(rows):
            rows[0]["AMOUNT"] = 142.48

        def drop_real_row(rows):
            rows.pop(1)

        def duplicate(rows):
            rows.insert(1, dict(rows[0]))
        for name, fn in (("changed digit", digit), ("dropped real row", drop_real_row), ("duplicated row", duplicate)):
            with self.subTest(mutation=name):
                self.assert_fails(self.gate(fn)[1])


@unittest.skipUnless(os.path.exists(Q10), "saved replay data not present")
class TestOnlyBlaiseAndGoodwins(unittest.TestCase):
    """Over every stored statement with a PDF, the planner applies to exactly the two expected
    statements: Blaise and Goodwins (user decision 2026-10-21)."""

    def test_the_planner_applies_to_blaise_and_goodwins_and_no_other_stored_statement(self):
        applicable = set()
        for sid, st in _stored().items():
            if st["engine"] != "claude_sonnet" or not st["rows"] or not (st.get("pdf") and os.path.exists(st["pdf"])):
                continue   # python-library rows carry invoice numbers on every row (no candidate)
            with mock.patch("builtins.print"):
                invoices = to_invoices(st["rows"], [k for k in st["keys"] if k != "confidence"])
            if not nl._candidates([i for i in invoices if not i.get("informational")]):
                continue
            prm._PAGES_CACHE.clear()
            if nl.plan_net_line_drop(invoices, st["pdf"])["applicable"]:
                applicable.add(sid)
        self.assertEqual(applicable, {BLAISE, GOODWINS})


class TestDetailPage(unittest.TestCase):

    def test_the_drop_is_shown(self):
        import test_pdf_row_match as prm_tests
        page = prm_tests.TestValidationPageBadge(methodName="test_method_labels")
        intake = {"statement_id": "B", "source_file": "b.pdf", "vendor_name": "Blaise", "statement_period": "2026-08",
                  "statement_total_as_printed": 3969.44, "validation_status": "matches", "validation_difference": 0.0,
                  "validation_method": "primary", "previous_balance": None, "previous_balance_source": None,
                  "ingestion_timestamp": "2026-10-01T21:00:00+00:00", "passed": True, "primary_computed": None,
                  "validation_attempts": [],
                  "net_line_drops": [{"row_number": 4, "amount": 89.08, "date_extracted": "07-23", "invoice_number": "HYW39227-1",
                                      "nets_rows": [{"row_number": 2, "amount": -545.46}, {"row_number": 3, "amount": 634.54}],
                                      "page": 1, "printed_line": "89.08 | 33 07-23 HYW39227-1 89.08"}]}
        page._patch(get_extraction_validation_detail=lambda sid: {"intake": intake, "computed_total": 3969.44, "lines": []})
        try:
            html = page._client().get("/validation/B").text
        finally:
            page.doCleanups()
        self.assertIn('id="net-line-drops"', html)
        self.assertIn("Invoice-net line removed", html)
        self.assertIn("HYW39227-1", html)
        self.assertIn("row 2 $-545.46 + row 3 $634.54", html)


if __name__ == "__main__":
    unittest.main()
