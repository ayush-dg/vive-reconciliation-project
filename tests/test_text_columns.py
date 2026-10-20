"""Text-layer column correction (src/validation/text_columns.py, wired into
notebooks/01_document_intake.py apply_arithmetic_validation, 2026-10-19).

Synthetic tests build CDK-style PDFs with PyMuPDF (header PURCHASES / PAYMENTS & CREDITS / BALANCE,
amounts right-aligned under their column, as on the Downeast Toyota statements). TestDowneast /
TestOtherCdkStatements / TestMutations use the stored extractions and PDFs in scratchpad/ (real data,
git-ignored) and skip where those files are not present."""
import copy
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import fitz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_oct1_intake_worker_web import load_intake  # noqa: E402

from src.ai.claude_sonnet_client import ClaudeSonnetClient  # noqa: E402
from src.validation import text_columns as tc  # noqa: E402
from src.validation.arithmetic_gate import compute_statement_total_from_invoices  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Q10 = os.path.join(REPO, "scratchpad", "saved_from_temp_20261019", "replay_inputs", "q10_rows.json")
COLUMNS = ["DATE", "DOCUMENT / TRANSACTION", "PURCHASES", "PAYMENTS & CREDITS", "BALANCE"]
# Header x0 / amount right edges as printed on DOWNEAST MCC 0826.pdf
HEADER = [("DATE", 47), ("DOCUMENT / TRANSACTION", 152), ("PURCHASES", 336), ("PAYMENTS & CREDITS", 405),
          ("BALANCE", 517)]
RIGHT = {"charge": 385.0, "credit": 460.0}


def to_invoices(rows, columns=COLUMNS):
    return ClaudeSonnetClient.__new__(ClaudeSonnetClient)._rows_to_invoices([dict(r) for r in rows], columns)[0]


def make_pdf(lines, *, right=None, scan=False):
    """lines: [(date, ref, side, amount_text)]; right overrides an amount's right edge per line index."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    if scan:
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 50, 50), 0)
        pix.clear_with(200)
        page.insert_image(fitz.Rect(30, 30, 300, 300), pixmap=pix)
    else:
        for text, x in HEADER:
            page.insert_text((x, 260), text, fontname="helv", fontsize=8)
        y = 290
        for i, (date, ref, side, amount) in enumerate(lines):
            page.insert_text((32, y), date, fontname="cour", fontsize=9)
            page.insert_text((100, y), ref, fontname="cour", fontsize=9)
            edge = (right or {}).get(i, RIGHT[side])
            page.insert_text((edge - fitz.get_text_length(amount, fontname="cour", fontsize=9), y), amount,
                             fontname="cour", fontsize=9)
            y += 11
    f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    f.close()
    doc.save(f.name)
    return f.name


def rows_for(lines, flip=()):
    """Extraction rows for printed lines; indexes in flip are put on the other side."""
    rows = []
    for i, (date, ref, side, amount) in enumerate(lines):
        if i in flip:
            side = "credit" if side == "charge" else "charge"
        value = float(amount.replace(",", ""))
        rows.append({"DATE": date, "DOCUMENT / TRANSACTION": ref, "PURCHASES": value if side == "charge" else None,
                     "PAYMENTS & CREDITS": value if side == "credit" else None, "BALANCE": None, "confidence": 0.95})
    return rows


def schema(invoices, printed, vendor="Synthetic CDK Dealer"):
    return {"document_metadata": {"document_type": "VENDOR_STATEMENT"}, "vendor_metadata": {"vendor_name": vendor},
            "statement_metadata": {"statement_total_as_printed": printed,
                                   "statement_total_computed": compute_statement_total_from_invoices(invoices)},
            "invoices": invoices}


LINES = [("01AUG26", "100001", "charge", "500.00"), ("05AUG26", "100001", "credit", "200.00"),
         ("07AUG26", "100002", "charge", "300.00"), ("09AUG26", "100003", "credit", "50.00")]   # = 550.00


class _Case(unittest.TestCase):

    def pdf(self, lines=LINES, **kw):
        path = make_pdf(lines, **kw)
        self.addCleanup(os.remove, path)
        return path

    def validate(self, rows, pdf, printed, env=None):
        intake = load_intake()
        s = schema(to_invoices(rows), printed)
        with mock.patch.dict(os.environ, env or {}), mock.patch.object(intake, "ocr_pdf_text", return_value=""), \
                mock.patch("builtins.print"):
            text = intake.extract_pdf_text(pdf)[0]
            v = intake.apply_arithmetic_validation(s, text, pdf)
        return s, v


class TestSynthetic(_Case):

    def test_a_payment_under_purchases_is_moved_and_the_statement_passes(self):
        s, v = self.validate(rows_for(LINES, flip={1}), self.pdf(), 550.00)
        self.assertEqual((v["status"], v["method"]), ("matches", "primary"))
        self.assertEqual(v["detail"]["text_column_corrections"],
                         [{"row_number": 2, "invoice_number": "100001", "date": "05AUG26", "amount": 200.0,
                           "from": "charge", "to": "credit", "page": 1}])
        moved = s["invoices"][1]   # corrected in place: the dict the caller writes to Bronze
        self.assertEqual((moved["credit"], moved["credits"], moved["outstanding_amount"], moved["charges"]),
                         (200.0, 200.0, None, None))
        self.assertEqual((moved["_raw_row"]["PURCHASES"], moved["_raw_row"]["PAYMENTS & CREDITS"]), (None, 200.0))
        self.assertEqual(s["statement_metadata"]["statement_total_computed"], 550.00)

    def test_a_charge_under_credits_is_moved_back_too(self):
        s, v = self.validate(rows_for(LINES, flip={2}), self.pdf(), 550.00)
        self.assertEqual(v["status"], "matches")
        self.assertEqual([(c["invoice_number"], c["from"], c["to"]) for c in v["detail"]["text_column_corrections"]],
                         [("100002", "credit", "charge")])
        self.assertEqual(s["invoices"][2]["outstanding_amount"], 300.0)

    def test_an_extraction_that_already_matches_the_pdf_is_untouched(self):
        rows = rows_for(LINES)
        s, v = self.validate(rows, self.pdf(), 550.00)
        self.assertEqual(v["status"], "matches")
        self.assertNotIn("text_column_corrections", v.get("detail") or {})
        self.assertNotIn("text_column_check", v.get("detail") or {})
        self.assertEqual(s["invoices"], to_invoices(rows))

    def test_an_already_passing_statement_is_never_touched_even_if_sides_are_wrong(self):
        # two equal amounts of different invoices swapped sides: the total still matches -> not considered
        lines = LINES + [("10AUG26", "100004", "charge", "75.00"), ("11AUG26", "100005", "credit", "75.00")]
        rows = rows_for(lines, flip={4, 5})
        plan = tc.plan_text_column_corrections(to_invoices(rows), self.pdf(lines), 550.00)
        self.assertEqual(len(plan["corrections"]), 2)    # the planner sees them...
        s, v = self.validate(rows, self.pdf(lines), 550.00)
        self.assertEqual((v["status"], v["method"]), ("matches", "primary"))
        self.assertNotIn("text_column_corrections", v.get("detail") or {})   # ...but a pass is never changed
        self.assertEqual(s["invoices"], to_invoices(rows))

    def test_pdf_columns_not_equal_to_the_printed_total_change_nothing(self):
        rows = rows_for(LINES, flip={1})
        s, v = self.validate(rows, self.pdf(), 551.00)
        self.assertEqual(v["status"], "mismatch")
        self.assertIn("not the printed 551.00", v["detail"]["text_column_check"]["reason"])
        self.assertEqual(s["invoices"], to_invoices(rows))

    def test_a_row_without_its_own_printed_line_changes_nothing(self):
        rows = rows_for(LINES, flip={1}) + [rows_for(LINES)[2]]   # 100002 300.00 extracted twice, printed once
        s, v = self.validate(rows, self.pdf(), 550.00)
        self.assertEqual(v["status"], "mismatch")
        self.assertIn("2 extracted row(s), 1 printed line(s)", v["detail"]["text_column_check"]["reason"])
        self.assertEqual(s["invoices"], to_invoices(rows))

    def test_a_printed_line_without_an_extracted_row_changes_nothing(self):
        rows = rows_for(LINES, flip={1})[:3]
        s, v = self.validate(rows, self.pdf(), 550.00)
        self.assertEqual(v["status"], "mismatch")
        self.assertIn("match no extracted row", v["detail"]["text_column_check"]["reason"])

    def test_an_amount_on_a_column_boundary_changes_nothing(self):
        purchases_right = 336 + fitz.get_text_length("PURCHASES", fontname="helv", fontsize=8)
        boundary = (purchases_right + 405) / 2   # halfway between PURCHASES and PAYMENTS
        pdf = self.pdf(right={1: boundary + 1})
        rows = rows_for(LINES, flip={1})
        plan = tc.plan_text_column_corrections(to_invoices(rows), pdf, 550.00)
        self.assertEqual(plan["applicable"], False)
        self.assertIn("can't be placed in one column", plan["reason"])
        s, v = self.validate(rows, pdf, 550.00)
        # The gate's own pdf_full_match reads the straddling 200.00 as a PURCHASES amount and passes this
        # synthetic statement by itself; whatever the gate decides, no row is moved.
        self.assertNotIn("text_column_corrections", v.get("detail") or {})
        self.assertEqual(s["invoices"], to_invoices(rows))

    def test_identical_lines_printed_on_both_sides_are_not_swapped(self):
        lines = LINES + [("18SEP26", "620230", "charge", "0.02"), ("18SEP26", "620230", "credit", "0.02")]
        rows = rows_for(lines, flip={1})
        rows[4], rows[5] = rows[5], rows[4]   # extracted in the other order -- same rows, no side error
        plan = tc.plan_text_column_corrections(to_invoices(rows), self.pdf(lines), 550.00)
        self.assertEqual([(c["invoice_number"], c["amount"]) for c in plan["corrections"]], [("100001", 200.0)])

    def test_a_scan_is_never_corrected(self):
        rows = rows_for(LINES, flip={1})
        s, v = self.validate(rows, self.pdf(scan=True), 550.00)
        self.assertEqual(v["status"], "mismatch")
        self.assertEqual(v["detail"]["text_column_check"]["reason"], "no text layer (scan)")

    def test_a_pdf_without_the_cdk_header_is_never_corrected(self):
        doc = fitz.open()
        doc.new_page().insert_text((50, 100), "01AUG26 100001 500.00", fontname="cour", fontsize=9)
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.close()
        doc.save(f.name)
        self.addCleanup(os.remove, f.name)
        plan = tc.plan_text_column_corrections(to_invoices(rows_for(LINES, flip={1})), f.name, 550.00)
        self.assertFalse(plan["applicable"])
        self.assertIn("transaction line before any column header", plan["reason"])

    def test_an_extraction_with_other_columns_is_never_corrected(self):
        rows = [{"Date": "01AUG26", "Invoice": "100001", "Amount": 500.0}]
        plan = tc.plan_text_column_corrections(to_invoices(rows, ["Date", "Invoice", "Amount"]), self.pdf(), 500.0)
        self.assertEqual(plan["reason"], "the extraction has no PURCHASES / PAYMENTS & CREDITS columns")

    def test_the_switch_turns_it_off(self):
        rows = rows_for(LINES, flip={1})
        s, v = self.validate(rows, self.pdf(), 550.00, env={tc.ENV_FLAG: "false"})
        self.assertEqual(v["status"], "mismatch")
        self.assertNotIn("text_column_check", v.get("detail") or {})
        self.assertEqual(s["invoices"], to_invoices(rows))

    def test_a_wrongly_read_pdf_line_can_never_produce_a_pass(self):
        # mutation of the PDF reading: one printed line read on the wrong side -> its totals can't match
        rows = rows_for(LINES, flip={1})
        real = tc.read_pdf_transactions

        def flipped(path):
            out = real(path)
            out["lines"][3]["side"] = "charge"
            return out
        with mock.patch.object(tc, "read_pdf_transactions", flipped):
            s, v = self.validate(rows, self.pdf(), 550.00)
        self.assertEqual(v["status"], "mismatch")
        self.assertIn("the PDF's columns total 650.00", v["detail"]["text_column_check"]["reason"])


def _stored():
    with open(Q10, encoding="utf-8") as f:
        return json.load(f)


DOWNEAST = {   # (row_number, reference, date, amount, from, to) -- each checked against the PDF's word positions
    "STMT-4E6F15BD": [(29, "618064", "10AUG26", 1180.68, "charge", "credit"), (40, "618756", "10AUG26", 444.22, "charge", "credit"),
                      (82, "619492", "03JUL26", 149.26, "charge", "credit"), (83, "619492", "10AUG26", 149.26, "credit", "charge"),
                      (97, "619666", "10AUG26", 208.54, "charge", "credit"), (113, "619815", "10AUG26", 623.91, "charge", "credit")],
    "STMT-656EF295": [(21, "620230", "18SEP26", 13.24, "charge", "credit"), (85, "621371", "18SEP26", 512.85, "charge", "credit"),
                      (110, "621612", "18SEP26", 72.65, "charge", "credit")],
    "STMT-9D183149": [(50, "618519", "24JUL26", 146.23, "charge", "credit"), (56, "618607", "24JUL26", 408.20, "charge", "credit")],
    "STMT-89B2FD3E": [(3, "CM614580A", "07MAY26", 115.04, "credit", "charge"), (12, "617564", "10AUG26", 228.78, "credit", "charge"),
                      (82, "619492", "03JUL26", 149.26, "charge", "credit"), (83, "619492", "10AUG26", 149.26, "credit", "charge")],
}


@unittest.skipUnless(os.path.exists(Q10), "saved replay data not present")
class _Stored(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.data = _stored()

    def statement(self, sid):
        st = self.data[sid]
        if not (st.get("pdf") and os.path.exists(st["pdf"])):
            self.skipTest(f"{sid}: PDF not on disk")
        cols = [k for k in st["keys"] if k != "confidence"]
        return st, to_invoices(st["rows"], cols)

    def run_gate(self, st, invoices, printed=None, env=None):
        intake = load_intake()
        s = schema(invoices, st["printed"] if printed is None else printed, vendor=st["vendor"])
        with mock.patch.dict(os.environ, env or {}), mock.patch.object(intake, "ocr_pdf_text", return_value=""), \
                mock.patch("builtins.print"):
            text = intake.extract_pdf_text(st["pdf"])[0]
            return s, intake.apply_arithmetic_validation(s, text, st["pdf"])


class TestDowneast(_Stored):

    def test_the_four_downeast_statements_pass_with_exactly_their_corrections(self):
        for sid, expected in DOWNEAST.items():
            with self.subTest(statement=sid):
                st, invoices = self.statement(sid)
                s, before = self.run_gate(st, copy.deepcopy(invoices), env={tc.ENV_FLAG: "false"})
                self.assertEqual(before["status"], "mismatch")
                s, v = self.run_gate(st, invoices)
                self.assertEqual((v["status"], v["method"]), ("matches", "primary"))
                self.assertEqual([(c["row_number"], c["invoice_number"], c["date"], c["amount"], c["from"], c["to"])
                                  for c in v["detail"]["text_column_corrections"]], expected)
                self.assertAlmostEqual(s["statement_metadata"]["statement_total_computed"], st["printed"], places=2)


class TestOtherCdkStatements(_Stored):
    # the other 8 stored CDK-header statements with a PDF on disk: never corrected
    REASONS = {"STMT-2EB30976": "no text layer (scan)", "STMT-CBD5BEF4": "no text layer (scan)",
               "STMT-01D6A366": "no text layer (scan)",
               "STMT-91FAD48D": "the PDF's columns total 25,487.70, not the printed 30,266.24",
               "STMT-3DCC5881": "no printed total", "STMT-6481B7EE": "no printed total",
               "STMT-7BD15C34": "no printed total", "STMT-E0B16E06": "no printed total"}

    def test_the_planner_refuses_each_for_its_reason(self):
        for sid, reason in self.REASONS.items():
            with self.subTest(statement=sid):
                st, invoices = self.statement(sid)
                plan = tc.plan_text_column_corrections(invoices, st["pdf"], st["printed"])
                self.assertEqual((plan["applicable"], plan["reason"]), (False, reason))

    def test_passing_text_layer_statements_are_unchanged_end_to_end(self):
        for sid in ("STMT-91FAD48D", "STMT-3DCC5881", "STMT-6481B7EE", "STMT-7BD15C34", "STMT-E0B16E06"):
            with self.subTest(statement=sid):
                st, invoices = self.statement(sid)
                original = copy.deepcopy(invoices)
                s, off = self.run_gate(st, copy.deepcopy(invoices), env={tc.ENV_FLAG: "false"})
                s, on = self.run_gate(st, invoices)
                self.assertEqual((on["status"], on["method"]), (off["status"], off["method"]))
                self.assertNotIn("text_column_corrections", on.get("detail") or {})
                self.assertEqual(s["invoices"], original)


class TestMutations(_Stored):
    SID = "STMT-9D183149"

    def mutated(self, change):
        st, invoices = self.statement(self.SID)
        rows = copy.deepcopy(st["rows"])
        change(rows)
        cols = [k for k in st["keys"] if k != "confidence"]
        return st, to_invoices(rows, cols)

    def test_printed_total_off_by_one_cent_is_never_corrected(self):
        st, invoices = self.statement(self.SID)
        s, v = self.run_gate(st, invoices, printed=st["printed"] + 0.01)
        self.assertEqual(v["status"], "mismatch")
        self.assertNotIn("text_column_corrections", v["detail"])

    def test_a_misread_amount_is_never_corrected(self):
        def change(rows):
            row = next(r for r in rows if r["DOCUMENT / TRANSACTION"] == "618519" and r.get("PURCHASES") == 146.23)
            row["PURCHASES"] = 146.32
        st, invoices = self.mutated(change)
        s, v = self.run_gate(st, invoices)
        self.assertEqual(v["status"], "mismatch")
        self.assertIn("printed line(s)", v["detail"]["text_column_check"]["reason"])

    def test_a_dropped_row_is_never_corrected(self):
        st, invoices = self.mutated(lambda rows: rows.pop(10))
        s, v = self.run_gate(st, invoices)
        self.assertEqual(v["status"], "mismatch")
        self.assertIn("match no extracted row", v["detail"]["text_column_check"]["reason"])

    def test_a_further_row_on_the_wrong_side_is_put_back_as_printed(self):
        def change(rows):
            row = next(r for r in rows if r["DOCUMENT / TRANSACTION"] == "618519" and r.get("PURCHASES") == 584.87)
            row["PURCHASES"], row["PAYMENTS & CREDITS"] = None, 584.87
        st, invoices = self.mutated(change)
        s, v = self.run_gate(st, invoices)
        self.assertEqual(v["status"], "matches")
        self.assertEqual(len(v["detail"]["text_column_corrections"]), 3)


if __name__ == "__main__":
    unittest.main()
