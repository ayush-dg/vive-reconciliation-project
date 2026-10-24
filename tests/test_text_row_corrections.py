"""Row correction from the printed line (C2: src/validation/text_columns.py plan_text_row_corrections /
apply_text_row_corrections, wired into notebooks/01_document_intake.py apply_arithmetic_validation,
2026-10-20).

Synthetic tests build text-layer PDFs with PyMuPDF: a CHARGES / CREDITS / BALANCE layout (as Goldstein
Subaru prints it) and a single signed AMOUNT layout with invoice subtotal lines (as NYE prints it).
TestTargets / TestOnlyTheTargets / TestMutations use the stored extractions and PDFs in scratchpad/
(real data, git-ignored) and skip where those files are not present."""
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

from src.validation import text_columns as tc  # noqa: E402

TWO_COLUMNS = ["DATE", "REF NO.", "CHARGES", "CREDITS", "BALANCE"]
AMOUNT_COLUMNS = ["DATE", "INVOICE", "REFERENCE", "AMOUNT"]


def _right_aligned(page, text, right, y, font="cour", size=9):
    page.insert_text((right - fitz.get_text_length(text, fontname=font, fontsize=size), y), text, fontname=font, fontsize=size)


def _save(doc):
    f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    f.close()
    doc.save(f.name)
    return f.name


def two_column_pdf(lines, scan=False):
    """lines: [(date, ref, side, amount_text)] under DATE / REF NO. / CHARGES / CREDITS / BALANCE."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    if scan:
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 50, 50), 0)
        pix.clear_with(200)
        page.insert_image(fitz.Rect(30, 30, 300, 300), pixmap=pix)
        return _save(doc)
    right = {}
    for text, x in (("DATE", 41), ("REF NO.", 171), ("CHARGES", 345), ("CREDITS", 422), ("BALANCE", 493)):
        page.insert_text((x, 318), text, fontname="helv", fontsize=8)
        right[text] = x + fitz.get_text_length(text, fontname="helv", fontsize=8)
    y = 340
    for date, ref, side, amount in lines:
        page.insert_text((41, y), date, fontname="cour", fontsize=9)
        page.insert_text((171, y), ref, fontname="cour", fontsize=9)
        if amount:
            _right_aligned(page, amount, right["CHARGES" if side == "charge" else "CREDITS"], y)
        y += 14
    page.insert_text((438, y + 10), "Total", fontname="helv", fontsize=8)
    return _save(doc)


def two_column_rows(lines, changes=None):
    """Extraction rows for printed lines; changes: {index: (side, value or None)} overrides a row's amount."""
    rows = []
    for i, (date, ref, side, amount) in enumerate(lines):
        value = float(amount.replace(",", "")) if amount else None
        side, value = (changes or {}).get(i, (side, value))
        rows.append({"DATE": date, "REF NO.": ref, "CHARGES": value if side == "charge" else None,
                     "CREDITS": value if side == "credit" else None, "BALANCE": None, "confidence": 0.95})
    return rows


def amount_pdf(lines):
    """lines: [(date, invoice, reference, amount_text)]; date None = a printed invoice subtotal (no date)."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    right = {}
    for text, x in (("DATE", 32), ("INVOICE", 115), ("REFERENCE", 172), ("AMOUNT", 316), ("BALANCE", 531)):
        page.insert_text((x, 272), text, fontname="helv", fontsize=8)
        right[text] = x + fitz.get_text_length(text, fontname="helv", fontsize=8)
    y = 290
    for date, invoice, reference, amount in lines:
        if date:
            page.insert_text((29, y), date, fontname="cour", fontsize=9)
            page.insert_text((98, y), invoice, fontname="cour", fontsize=9)
            if reference:
                page.insert_text((165, y), reference, fontname="cour", fontsize=9)
        _right_aligned(page, amount, right["AMOUNT"] + 9, y)
        y += 10
    return _save(doc)


def amount_rows(rows):
    return [{"DATE": d, "INVOICE": inv, "REFERENCE": ref, "AMOUNT": value, "confidence": 0.95} for d, inv, ref, value in rows]


LINES = [("07/10/2026", "479940", "charge", "984.13"), ("08/05/2026", "47866", "credit", "649.88"),
         ("08/11/2026", "47981", "charge", "1,128.95"), ("08/25/2026", "220830", "credit", "984.13")]   # = 479.07


class _Case(unittest.TestCase):

    def pdf(self, path):
        self.addCleanup(os.remove, path)
        return path

    def validate(self, rows, pdf, printed, columns=TWO_COLUMNS, env=None):
        intake = load_intake()
        s = schema(to_invoices(rows, columns), printed)
        with mock.patch.dict(os.environ, env or {}), mock.patch.object(intake, "ocr_pdf_text", return_value=""), \
                mock.patch("builtins.print"):
            text = intake.extract_pdf_text(pdf)[0]
            v = intake.apply_arithmetic_validation(s, text, pdf)
        return s, v

    def assert_unchanged(self, s, v, rows, columns=TWO_COLUMNS):
        self.assertEqual(v["status"], "mismatch")
        self.assertNotIn("text_column_corrections", v.get("detail") or {})
        self.assertEqual(s["invoices"], to_invoices(rows, columns))


class TestTwoColumns(_Case):

    def test_a_missing_amount_is_filled_and_a_payment_moved_from_its_printed_lines(self):
        rows = two_column_rows(LINES, {0: (None, None), 3: ("charge", 984.13)})   # as RH Long 479940 / 220830
        s, v = self.validate(rows, self.pdf(two_column_pdf(LINES)), 479.07)
        self.assertEqual((v["status"], v["method"]), ("matches", "primary"))
        self.assertEqual([(c["row_number"], c["invoice_number"], c["date"], c["change"], c["extracted_field"],
                           c["extracted_value"], c["field"], c["printed_value"], c["page"])
                          for c in v["detail"]["text_column_corrections"]],
                         [(1, "479940", "07/10/2026", "filled", None, None, "charge", 984.13, 1),
                          (4, "220830", "08/25/2026", "moved", "charge", 984.13, "credit", 984.13, 1)])
        filled, moved = s["invoices"][0], s["invoices"][3]   # corrected in place: the dicts written to Bronze
        self.assertEqual((filled["outstanding_amount"], filled["_raw_row"]["CHARGES"]), (984.13, 984.13))
        self.assertEqual((moved["credit"], moved["outstanding_amount"], moved["_raw_row"]["CHARGES"],
                          moved["_raw_row"]["CREDITS"]), (984.13, None, None, 984.13))
        self.assertEqual(s["statement_metadata"]["statement_total_computed"], 479.07)

    def test_a_statement_that_already_passes_is_untouched(self):
        rows = two_column_rows(LINES)
        s, v = self.validate(rows, self.pdf(two_column_pdf(LINES)), 479.07)
        self.assertEqual(v["status"], "matches")
        self.assertNotIn("text_column_corrections", v.get("detail") or {})
        self.assertNotIn("text_column_check", v.get("detail") or {})
        self.assertEqual(s["invoices"], to_invoices(rows, TWO_COLUMNS))

    def test_two_printed_lines_with_the_same_identity_change_nothing(self):
        lines = LINES + [("08/12/2026", "48129", "charge", "13.42"), ("08/12/2026", "48129", "charge", "13.42")]
        rows = two_column_rows(lines, {0: (None, None)})
        s, v = self.validate(rows, self.pdf(two_column_pdf(lines)), 505.91)
        self.assert_unchanged(s, v, rows)
        self.assertIn("matches 2 printed lines, not exactly one", v["detail"]["text_column_check"]["row_check"])

    def test_a_row_without_a_printed_line_changes_nothing(self):
        rows = two_column_rows(LINES, {0: (None, None)}) + two_column_rows([("08/30/2026", "99999", "charge", "5.00")])
        s, v = self.validate(rows, self.pdf(two_column_pdf(LINES)), 479.07)
        self.assert_unchanged(s, v, rows)
        self.assertIn("matches 0 printed lines", v["detail"]["text_column_check"]["row_check"])

    def test_a_printed_line_without_a_row_changes_nothing(self):
        rows = two_column_rows(LINES, {0: (None, None)})
        del rows[2]   # 47981's printed 1,128.95 has no row
        s, v = self.validate(rows, self.pdf(two_column_pdf(LINES)), 479.07)
        self.assert_unchanged(s, v, rows)
        self.assertIn("1 printed line(s) match no extracted row", v["detail"]["text_column_check"]["row_check"])

    def test_a_printed_total_one_cent_off_changes_nothing(self):
        rows = two_column_rows(LINES, {0: (None, None)})
        s, v = self.validate(rows, self.pdf(two_column_pdf(LINES)), 479.08)
        self.assert_unchanged(s, v, rows)
        self.assertIn("not the printed 479.08", v["detail"]["text_column_check"]["row_check"])

    def test_a_scan_changes_nothing(self):
        rows = two_column_rows(LINES, {0: (None, None)})
        s, v = self.validate(rows, self.pdf(two_column_pdf(LINES, scan=True)), 479.07)
        self.assert_unchanged(s, v, rows)
        self.assertEqual(v["detail"]["text_column_check"]["row_check"], "no text layer (scan)")

    def test_the_switch_turns_it_off(self):
        rows = two_column_rows(LINES, {0: (None, None)})
        s, v = self.validate(rows, self.pdf(two_column_pdf(LINES)), 479.07, env={tc.ENV_FLAG: "false"})
        self.assert_unchanged(s, v, rows)
        self.assertNotIn("text_column_check", v.get("detail") or {})

    def test_an_amount_printed_nowhere_is_never_written_over(self):
        rows = two_column_rows(LINES, {0: (None, None), 2: ("charge", 1128.59)})   # a digit the PDF never prints
        s, v = self.validate(rows, self.pdf(two_column_pdf(LINES)), 479.07)
        self.assert_unchanged(s, v, rows)
        self.assertIn("is printed nowhere on the PDF", v["detail"]["text_column_check"]["row_check"])

    def test_reaching_the_total_only_by_inventing_an_amount_fails(self):
        # 479940's printed line has no amount; the printed total needs 984.13 that no printed line holds
        lines = [("07/10/2026", "479940", "charge", "")] + LINES[1:]
        rows = two_column_rows(lines)
        s, v = self.validate(rows, self.pdf(two_column_pdf(lines)), 479.07)
        self.assert_unchanged(s, v, rows)
        self.assertIn("line without exactly one amount", v["detail"]["text_column_check"]["row_check"])
        # and with every line printing its amount but a printed total no line adds up to
        rows = two_column_rows(LINES, {0: (None, None)})
        s, v = self.validate(rows, self.pdf(two_column_pdf(LINES)), 579.07)
        self.assert_unchanged(s, v, rows)
        self.assertIn("the PDF's columns total 479.07, not the printed 579.07", v["detail"]["text_column_check"]["row_check"])


NYE_LINES = [("08-11", "CHW252426C", None, "235.45"), ("08-21", "CHW252426C", "CMCHW252426C", "-167.96"),
             (None, "", None, "67.49"),                                    # printed subtotal of CHW252426C
             ("08-11", "CHW252427C", "CHW252427C", "692.24"), ("08-11", "CHW252445C", None, "53.41")]   # = 813.14


class TestAmountColumnWithSubtotals(_Case):

    def test_an_amount_taken_from_a_subtotal_is_replaced_by_the_rows_own_printed_amount(self):
        rows = amount_rows([("08-11", "CHW252426C", None, 235.45), ("08-21", "CHW252426C", "CMCHW252426C", -167.96),
                            ("08-11", "CHW252427C", "CHW252427C", 67.49), ("08-11", "CHW252445C", None, 692.24)])
        pdf = self.pdf(amount_pdf(NYE_LINES))
        self.assertEqual(len(tc.read_pdf_table(pdf)["lines"]), 4)   # the subtotal line is never a transaction
        s, v = self.validate(rows, pdf, 813.14, columns=AMOUNT_COLUMNS)
        self.assertEqual(v["status"], "matches")
        self.assertEqual([(c["invoice_number"], c["change"], c["extracted_value"], c["printed_value"])
                          for c in v["detail"]["text_column_corrections"]],
                         [("CHW252427C", "replaced", 67.49, 692.24), ("CHW252445C", "replaced", 692.24, 53.41)])
        self.assertEqual([r["_raw_row"]["AMOUNT"] for r in s["invoices"]], [235.45, -167.96, 692.24, 53.41])

    def test_a_subtotal_extracted_as_an_extra_row_changes_nothing(self):
        rows = amount_rows([("08-11", "CHW252426C", None, 235.45), ("08-21", "CHW252426C", "CMCHW252426C", -167.96),
                            ("08-11", "CHW252426C", None, 67.49),
                            ("08-11", "CHW252427C", "CHW252427C", 692.24), ("08-11", "CHW252445C", None, 53.41)])
        s, v = self.validate(rows, self.pdf(amount_pdf(NYE_LINES)), 813.14, columns=AMOUNT_COLUMNS)
        self.assert_unchanged(s, v, rows, columns=AMOUNT_COLUMNS)
        self.assertIn("claim the same printed line", v["detail"]["text_column_check"]["row_check"])


# The four audited targets: (row, reference, date, change, extracted field, extracted value, printed field,
# printed value, page) -- each checked against the PDF's words (Goldstein's printed running balance,
# RH Long's printed CHARGES / PYMTS/CR columns, NYE's page-2 lines).
RH_LONG = []
for _row, _inv, _date, _value in ((3, "479940", "07/10/26", 984.13), (5, "482505", "07/22/26", 25.11),
                                  (7, "483795", "07/28/26", 31.5), (9, "484528", "07/31/26", 114.84),
                                  (11, "484591", "07/31/26", 84.89)):
    RH_LONG += [(_row, _inv, _date, "filled", None, None, "charge", _value, 1),
                (_row + 1, "220830", "08/25/26", "moved", "charge", _value, "credit", _value, 1)]
NYE = [(30, "CHW252427C", "08-11", "replaced", "amount", 67.49, "amount", 692.24, 2),
       (31, "CHW252445C", "08-11", "replaced", "amount", 692.24, "amount", 53.41, 2)]
TARGETS = {
    "STMT-33A495CD": [(2, "47877", "08/05/2026", "moved", "credit", 252.67, "charge", 252.67, 1)],
    "STMT-74B91C07": RH_LONG,
    "STMT-4AD32710": NYE,
    "STMT-E2B6D395": NYE,
}


@unittest.skipUnless(os.path.exists(Q10), "saved replay data not present")
class _Stored(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.data = _stored()

    def statement(self, sid, change=None):
        st = self.data[sid]
        if not (st.get("pdf") and os.path.exists(st["pdf"])):
            self.skipTest(f"{sid}: PDF not on disk")
        rows = copy.deepcopy(st["rows"])
        if change:
            change(rows)
        return st, to_invoices(rows, [k for k in st["keys"] if k != "confidence"])

    def run_gate(self, st, invoices, env=None):
        intake = load_intake()
        s = schema(invoices, st["printed"], vendor=st["vendor"])
        with mock.patch.dict(os.environ, env or {}), mock.patch.object(intake, "ocr_pdf_text", return_value=""), \
                mock.patch("builtins.print"):
            text = intake.extract_pdf_text(st["pdf"])[0]
            return s, intake.apply_arithmetic_validation(s, text, st["pdf"])


class TestTargets(_Stored):

    def test_the_four_targets_pass_with_exactly_their_corrections(self):
        for sid, expected in TARGETS.items():
            with self.subTest(statement=sid):
                st, invoices = self.statement(sid)
                s, before = self.run_gate(st, copy.deepcopy(invoices), env={tc.ENV_FLAG: "false"})
                self.assertEqual(before["status"], "mismatch")
                s, v = self.run_gate(st, invoices)
                self.assertEqual((v["status"], v["method"]), ("matches", "primary"))
                self.assertEqual([(c["row_number"], c["invoice_number"], c["date"], c["change"], c["extracted_field"],
                                   c["extracted_value"], c["field"], c["printed_value"], c["page"])
                                  for c in v["detail"]["text_column_corrections"]], expected)
                self.assertAlmostEqual(s["statement_metadata"]["statement_total_computed"], st["printed"], places=2)
                for c in v["detail"]["text_column_corrections"]:   # the corrected raw row holds the printed value
                    raw = s["invoices"][c["row_number"] - 1]["_raw_row"]
                    self.assertIn(c["printed_value"], raw.values())


@unittest.skipUnless(os.path.exists(Q10), "saved replay data not present")
class TestOnlyTheTargets(unittest.TestCase):

    def test_the_planner_applies_to_no_other_stored_statement(self):
        applicable = set()
        for sid, st in _stored().items():
            if not (st.get("pdf") and os.path.exists(st["pdf"])) or st["engine"] != "claude_sonnet" or not st["rows"]:
                continue
            with mock.patch("builtins.print"):
                invoices = to_invoices(st["rows"], [k for k in st["keys"] if k != "confidence"])
            if tc.plan_text_row_corrections(invoices, st["pdf"], st["printed"])["applicable"]:
                applicable.add(sid)
        self.assertEqual(applicable, set(TARGETS))


class TestMutations(_Stored):
    # per target: (a correct row to move to the wrong column, its raw column, the other column)
    CORRECT_ROW = {"STMT-33A495CD": (2, "CHARGES", "CREDITS"), "STMT-74B91C07": (12, "CHARGES", "PYMTS/CR"),
                   "STMT-4AD32710": (17, "AMOUNT", None), "STMT-E2B6D395": (17, "AMOUNT", None)}

    def gate(self, sid, change):
        st, invoices = self.statement(sid, change)
        return self.run_gate(st, invoices)[1]

    def test_a_changed_digit_fails(self):
        for sid, (index, column, _) in self.CORRECT_ROW.items():
            with self.subTest(statement=sid):
                def change(rows):
                    rows[index][column] = round(rows[index][column] + 0.09, 2)
                v = self.gate(sid, change)
                self.assertEqual(v["status"], "mismatch")
                self.assertIn("printed nowhere on the PDF", v["detail"]["text_column_check"]["row_check"])

    def test_a_dropped_row_fails(self):
        for sid, (index, _, _) in self.CORRECT_ROW.items():
            with self.subTest(statement=sid):
                v = self.gate(sid, lambda rows: rows.pop(index))
                self.assertEqual(v["status"], "mismatch")
                self.assertIn("match no extracted row", v["detail"]["text_column_check"]["row_check"])

    def test_a_duplicated_row_fails(self):
        for sid, (index, _, _) in self.CORRECT_ROW.items():
            with self.subTest(statement=sid):
                v = self.gate(sid, lambda rows: rows.insert(index + 1, dict(rows[index])))
                self.assertEqual(v["status"], "mismatch")
                self.assertIn("claim the same printed line", v["detail"]["text_column_check"]["row_check"])

    def test_a_correct_row_moved_to_the_wrong_column_is_corrected_back_and_passes(self):
        # Moving a correct row to the wrong column is corrected back to its printed line and the
        # statement passes; the correction is listed with the target's own corrections. (Single AMOUNT
        # layout, NYE: the wrong column is a sign flip.)
        for sid, (index, column, other) in self.CORRECT_ROW.items():
            with self.subTest(statement=sid):
                st, clean = self.statement(sid)
                s_clean, v_clean = self.run_gate(st, clean)

                def change(rows):
                    if other:
                        rows[index][column], rows[index][other] = None, rows[index][column]
                    else:
                        rows[index][column] = -rows[index][column]
                st, invoices = self.statement(sid, change)
                s, v = self.run_gate(st, invoices)
                self.assertEqual(v["status"], "matches")
                self.assertEqual(len(v["detail"]["text_column_corrections"]), len(TARGETS[sid]) + 1)
                self.assertIn(index + 1, [c["row_number"] for c in v["detail"]["text_column_corrections"]])
                self.assertEqual(s["invoices"], s_clean["invoices"])   # same rows as the unmutated correction


class TestDetailPage(unittest.TestCase):

    def test_the_row_corrections_are_shown(self):
        import test_pdf_row_match as prm
        page = prm.TestValidationPageBadge(methodName="test_method_labels")
        intake = {"statement_id": "N", "source_file": "n.pdf", "vendor_name": "NYE AUTOMOTIVE GROUP",
                  "statement_period": "2026-08", "statement_total_as_printed": 7983.30, "validation_status": "matches",
                  "validation_difference": 0.0, "validation_method": "primary", "previous_balance": None,
                  "previous_balance_source": None, "ingestion_timestamp": "2026-10-01T21:00:00+00:00", "passed": True,
                  "primary_computed": 7983.30, "validation_attempts": [],
                  "text_column_corrections": [
                      {"row_number": 30, "invoice_number": "CHW252427C", "date": "08-11", "change": "replaced",
                       "extracted_field": "amount", "extracted_value": 67.49, "field": "amount",
                       "printed_value": 692.24, "page": 2, "printed_line": "08-11 4 CHW252427C CHW252427C 692.24"},
                      {"row_number": 3, "invoice_number": "479940", "date": "07/10/26", "change": "filled",
                       "extracted_field": None, "extracted_value": None, "field": "charge", "printed_value": 984.13,
                       "page": 1, "printed_line": "07/10/26 479940 4102441 85 984.13"}]}
        page._patch(get_extraction_validation_detail=lambda sid: {"intake": intake, "computed_total": None, "lines": []})
        try:
            html = page._client().get("/validation/N").text
        finally:
            page.doCleanups()
        self.assertIn('id="text-row-corrections"', html)
        self.assertIn("2 rows were set to the amount and column printed on their own line", html)
        self.assertIn("amount replaced", html)
        self.assertIn("amount filled in", html)
        self.assertIn("no amount", html)
        self.assertNotIn('id="text-column-corrections"', html)


if __name__ == "__main__":
    unittest.main()
