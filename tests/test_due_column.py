"""Due amount read out of a merged "Due Description" cell (C3: src/validation/due_column.py, wired into
notebooks/01_document_intake.py apply_arithmetic_validation, 2026-10-20).

Synthetic tests build a text-layer Autoly ledger with PyMuPDF (Charged / Paid / Unalloc. / Due amounts
right-aligned under their header, Description after Due). TestStored / TestOnlyTheTen / TestMutations
use the stored extractions and PDFs in scratchpad/ (real data, git-ignored) and skip where those files
are not present; the Noakers PDF is a scan, read by Tesseract OCR."""
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

from src.validation import due_column as dc  # noqa: E402

COLUMNS = ["Date", "Transaction Type", "Sls", "Cust PO/Chk #", "Charged", "Paid", "Unalloc.", "Due Description"]
RIGHT = {"Charged": 324.0, "Paid": 362.0, "Unalloc.": 400.0, "Due": 438.0}


def ledger_pdf(lines, totals=None):
    """lines: [(date, type, ref, {column: amount_text}, description)] as an Autoly ledger."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)

    def right(text, edge, y, font="helv", size=8):
        page.insert_text((edge - fitz.get_text_length(text, fontname=font, fontsize=size), y), text, fontname=font, fontsize=size)
    for text, x in (("Date", 29), ("Transaction", 66), ("Type", 113), ("Sls", 181), ("Cust", 230), ("PO/Chk#", 250)):
        page.insert_text((x, 300), text, fontname="helv", fontsize=8)
    for name, edge in RIGHT.items():
        right(name, edge, 300)
    page.insert_text((442, 300), "Description", fontname="helv", fontsize=8)
    y = 316
    for date, kind, ref, amounts, description in lines:
        page.insert_text((29, y), date, fontname="helv", fontsize=8)
        page.insert_text((66, y), f"{kind} {ref}", fontname="helv", fontsize=8)
        page.insert_text((230, y), ref.lstrip("#"), fontname="helv", fontsize=8)
        for column, text in amounts.items():
            right(text, RIGHT[column], y)
        page.insert_text((442, y), description, fontname="helv", fontsize=8)
        y += 15
    if totals:
        page.insert_text((300, y + 5), "Totals", fontname="helv", fontsize=8)
        for column, text in totals.items():
            right(text, RIGHT[column], y + 5)
    f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    f.close()
    doc.save(f.name)
    return f.name


LINES = [("09/03/26", "Invoice", "#100001", {"Charged": "225.00", "Due": "225.00"}, "(YOR) 2019 SENTRA L Front Door"),
         ("09/04/26", "Invoice", "#100002", {"Charged": "560.00", "Due": "500.00"}, "(CHU) 2019 ESCAPE Lid/Gate"),
         ("09/10/26", "Payment: Check", "555123", {"Paid": "1000.00", "Unalloc.": "0.00"}, "Payment: Check 555123")]
TOTALS = {"Unalloc.": "0.00", "Due": "725.00"}   # printed total = 725.00 - 0.00


def ledger_rows(changes=None):
    rows = [{"Date": "09/03/26", "Transaction Type": "Invoice #100001", "Sls": "YOR/jeff", "Cust PO/Chk #": "100001",
             "Charged": 225.0, "Paid": None, "Unalloc.": None, "Due Description": "225.00 (YOR) 2019 SENTRA L Front Door"},
            {"Date": "09/04/26", "Transaction Type": "Invoice #100002", "Sls": "YOR/jeff", "Cust PO/Chk #": "100002",
             "Charged": 560.0, "Paid": None, "Unalloc.": None, "Due Description": "500.00 (CHU) 2019 ESCAPE Lid/Gate"},
            {"Date": "09/10/26", "Transaction Type": "Payment: Check 555123", "Sls": "CHU/cynthia", "Cust PO/Chk #": "555123",
             "Charged": None, "Paid": 1000.0, "Unalloc.": 0.0, "Due Description": "Payment: Check 555123"}]
    for index, change in (changes or {}).items():
        rows[index].update(change)
    return [dict(r, confidence=0.95) for r in rows]


class _Case(unittest.TestCase):

    def pdf(self, lines=LINES, totals=TOTALS):
        path = ledger_pdf(lines, totals)
        self.addCleanup(os.remove, path)
        return path

    def validate(self, invoices, pdf, printed, env=None):
        intake = load_intake()
        s = schema(invoices, printed)
        with mock.patch.dict(os.environ, env or {}), mock.patch.object(intake, "ocr_pdf_text", return_value=""), \
                mock.patch("builtins.print"):
            text = intake.extract_pdf_text(pdf)[0]
            v = intake.apply_arithmetic_validation(s, text, pdf)
        return s, v

    def assert_unchanged(self, s, v, invoices, reason):
        self.assertEqual(v["status"], "mismatch")
        self.assertNotIn("text_column_corrections", v.get("detail") or {})
        self.assertEqual(s["invoices"], invoices)
        self.assertIn(reason, v["detail"]["due_column_check"]["reason"])


class TestSynthetic(_Case):

    def test_the_leading_due_amounts_are_moved_and_the_statement_passes(self):
        s, v = self.validate(to_invoices(ledger_rows(), COLUMNS), self.pdf(), 725.00)
        self.assertEqual((v["status"], v["method"]), ("matches", "open_balance"))
        self.assertEqual([(c["row_number"], c["invoice_number"], c["date"], c["field"], c["from"], c["amount"], c["page"])
                          for c in v["detail"]["text_column_corrections"]],
                         [(1, "100001", "09/03/26", "Due", "225.00 (YOR) 2019 SENTRA L Front Door", 225.0, 1),
                          (2, "100002", "09/04/26", "Due", "500.00 (CHU) 2019 ESCAPE Lid/Gate", 500.0, 1)])
        first = s["invoices"][0]   # corrected in place: the dict written to Bronze
        self.assertEqual((first["amount_due"], first["_raw_row"]["Due"], first["_raw_row"]["Due Description"]),
                         (225.0, 225.0, "(YOR) 2019 SENTRA L Front Door"))
        self.assertIsNone(s["invoices"][2].get("amount_due"))

    def test_a_leading_amount_that_differs_from_the_printed_due_changes_nothing(self):
        invoices = to_invoices(ledger_rows({1: {"Due Description": "560.00 (CHU) 2019 ESCAPE Lid/Gate"}}), COLUMNS)
        s, v = self.validate(copy.deepcopy(invoices), self.pdf(), 725.00)
        self.assert_unchanged(s, v, invoices, "the PDF's Due cell is 500.0")

    def test_a_row_whose_due_already_holds_a_value_changes_nothing(self):
        invoices = to_invoices(ledger_rows(), COLUMNS)
        invoices[0]["amount_due"] = 225.0
        s, v = self.validate(copy.deepcopy(invoices), self.pdf(), 725.00)
        self.assertNotIn("text_column_corrections", v.get("detail") or {})
        self.assertEqual(s["invoices"], invoices)
        self.assertEqual(v["detail"]["due_column_check"]["reason"], "a row's Due field already holds a value")

    def test_a_printed_line_without_a_row_changes_nothing(self):
        invoices = to_invoices(ledger_rows()[1:], COLUMNS)
        s, v = self.validate(copy.deepcopy(invoices), self.pdf(), 725.00)
        self.assert_unchanged(s, v, invoices, "1 printed line(s) match no extracted row")

    def test_a_row_without_a_printed_line_changes_nothing(self):
        extra = dict(ledger_rows()[0], **{"Date": "09/20/26", "Transaction Type": "Invoice #100009",
                                          "Cust PO/Chk #": "100009"})
        invoices = to_invoices(ledger_rows() + [extra], COLUMNS)
        s, v = self.validate(copy.deepcopy(invoices), self.pdf(), 725.00)
        self.assert_unchanged(s, v, invoices, "matches 0 printed lines")

    def test_due_minus_unalloc_one_cent_off_the_printed_total_changes_nothing(self):
        invoices = to_invoices(ledger_rows(), COLUMNS)
        s, v = self.validate(copy.deepcopy(invoices), self.pdf(), 725.01)
        self.assert_unchanged(s, v, invoices, "= 725.00, not the printed 725.01")

    def test_a_description_with_no_leading_amount_changes_nothing(self):
        invoices = to_invoices(ledger_rows({0: {"Due Description": "(YOR) 2019 SENTRA L Front Door"},
                                            1: {"Due Description": "(CHU) 2019 ESCAPE Lid/Gate"}}), COLUMNS)
        s, v = self.validate(copy.deepcopy(invoices), self.pdf(), 725.00)
        self.assert_unchanged(s, v, invoices, "no Due Description cell starts with an amount")

    def test_an_extracted_amount_the_pdf_does_not_print_changes_nothing(self):
        # STMT-A74BA583's case: an extracted Paid where the PDF prints none
        invoices = to_invoices(ledger_rows({0: {"Paid": 225.0}}), COLUMNS)
        s, v = self.validate(copy.deepcopy(invoices), self.pdf(), 725.00)
        self.assert_unchanged(s, v, invoices, "extracted Paid 225.0, the PDF prints None")
        invoices = to_invoices(ledger_rows({2: {"Paid": 999.0}}), COLUMNS)
        s, v = self.validate(copy.deepcopy(invoices), self.pdf(), 725.00)
        self.assert_unchanged(s, v, invoices, "extracted Paid 999.0, the PDF prints 1000.0")

    def test_the_switch_turns_it_off(self):
        invoices = to_invoices(ledger_rows(), COLUMNS)
        s, v = self.validate(copy.deepcopy(invoices), self.pdf(), 725.00, env={dc.ENV_FLAG: "false"})
        self.assertEqual(v["status"], "mismatch")
        self.assertNotIn("text_column_corrections", v.get("detail") or {})
        self.assertNotIn("due_column_check", v.get("detail") or {})
        self.assertEqual(s["invoices"], invoices)


# The ten statements: (row, reference, date, Due moved out of the description), each checked by eye
# against the PDF's Due column (text-layer words; the Noakers scan's page image).
TEN = {
    "STMT-0D64E1F3": [(1, "1503634", "09/03/26", 225.0), (2, "1504084", "09/04/26", 560.0), (3, "1504568", "09/08/26", 210.0)],
    "STMT-14DF18D8": [(1, "816725", "08/03/26", 650.0), (2, "816736", "08/03/26", 180.0), (3, "817358", "08/05/26", 430.0),
                      (5, "818857", "08/12/26", 305.0), (6, "818859", "08/12/26", 1505.0), (7, "820343", "08/19/26", 280.0)],
    "STMT-587EA687": [(1, "823063", "09/01/26", 230.0), (2, "823064", "09/01/26", 1130.0), (3, "827766", "09/23/26", 130.0)],
    "STMT-149A24AE": [(1, "823063", "09/01/26", 230.0), (2, "823064", "09/01/26", 1130.0), (3, "827766", "09/23/26", 130.0)],
    "STMT-043EACF2": [(2, "1484479", "07/17/26", 620.0), (4, "1500813", "08/27/26", 305.0), (5, "1501465", "08/28/26", 320.0)],
    "STMT-213522C8": [(1, "1500813", "08/27/26", 305.0), (2, "1501465", "08/28/26", 320.0), (3, "1504694", "09/08/26", 210.0),
                      (4, "1505787", "09/10/26", 860.0)],
    "STMT-BEF5BB80": [(1, "788759", "09/03/26", 155.0), (2, "789718", "09/10/26", 725.0), (4, "792203", "09/23/26", 0.0),
                      (6, "792921", "09/28/26", 1116.0)],
    "STMT-7DF58A05": [(2, "783441", "08/06/26", 1030.0)],
    "STMT-A9CDD843": [(1, "167784", "09/02/26", 1125.0), (2, "169200", "09/08/26", 75.0), (4, "169688", "09/09/26", 800.0),
                      (5, "171070", "09/14/26", 61.0), (6, "171099", "09/14/26", 0.0), (9, "174270", "09/23/26", 1075.0)],
    "STMT-105A9665": [(1, "1181531", "09/08/26", 50.0), (3, "1183738", "09/15/26", 200.0)],
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
        with mock.patch.dict(os.environ, env or {}), mock.patch("builtins.print"):
            text = intake.extract_pdf_text(st["pdf"])[0]
            return s, intake.apply_arithmetic_validation(s, text, st["pdf"])


class TestStored(_Stored):

    def test_the_ten_statements_pass_with_exactly_their_moves(self):
        for sid, expected in TEN.items():
            with self.subTest(statement=sid):
                st, invoices = self.statement(sid)
                s, before = self.run_gate(st, copy.deepcopy(invoices), env={dc.ENV_FLAG: "false"})
                self.assertEqual(before["status"], "mismatch")
                s, v = self.run_gate(st, invoices)
                self.assertEqual((v["status"], v["method"]), ("matches", "open_balance"))
                self.assertEqual([(c["row_number"], c["invoice_number"], c["date"], c["amount"])
                                  for c in v["detail"]["text_column_corrections"]], expected)
                for c in v["detail"]["text_column_corrections"]:
                    self.assertEqual((c["field"], c["extracted_field"], c["printed_value"]),
                                     ("Due", "Due Description", c["amount"]))
                    row = s["invoices"][c["row_number"] - 1]
                    self.assertEqual((row["amount_due"], row["_raw_row"]["Due"]), (c["amount"], c["amount"]))

    def test_a74ba583_stays_refused(self):
        st, invoices = self.statement("STMT-A74BA583")
        s, v = self.run_gate(st, invoices)
        self.assertEqual(v["status"], "mismatch")
        self.assertIn("extracted Paid 690.0, the PDF prints None", v["detail"]["due_column_check"]["reason"])


@unittest.skipUnless(os.path.exists(Q10), "saved replay data not present")
class TestOnlyTheTen(unittest.TestCase):

    def test_the_planner_applies_to_no_other_stored_statement(self):
        applicable = set()
        for sid, st in _stored().items():
            if not (st.get("pdf") and os.path.exists(st["pdf"])) or not st["rows"]:
                continue
            if st["engine"] == "claude_sonnet":
                with mock.patch("builtins.print"):
                    invoices = to_invoices(st["rows"], [k for k in st["keys"] if k != "confidence"])
            else:   # python-library rows: the planner decides applicability from the raw columns alone
                invoices = [{"_raw_row": dict(r)} for r in st["rows"]]
            if dc.plan_due_column_corrections(invoices, st["pdf"], st["printed"])["applicable"]:
                applicable.add(sid)
        self.assertEqual(applicable, set(TEN))


class TestMutations(_Stored):
    # (statement, a charged invoice row, a payment row)
    CASES = (("STMT-0D64E1F3", 0, 3), ("STMT-14DF18D8", 0, 7))

    def gate(self, sid, change):
        st, invoices = self.statement(sid, change)
        return self.run_gate(st, invoices)[1]

    def assert_fails(self, v, reason):
        self.assertEqual(v["status"], "mismatch")
        self.assertNotIn("text_column_corrections", v["detail"])
        self.assertIn(reason, v["detail"]["due_column_check"]["reason"])

    def test_a_changed_digit_in_charged_fails(self):
        for sid, invoice, _ in self.CASES:
            with self.subTest(statement=sid):
                def change(rows):
                    rows[invoice]["Charged"] = rows[invoice]["Charged"] + 1
                self.assert_fails(self.gate(sid, change), "extracted Charged")

    def test_a_dropped_row_fails(self):
        for sid, invoice, _ in self.CASES:
            with self.subTest(statement=sid):
                self.assert_fails(self.gate(sid, lambda rows: rows.pop(invoice + 1)), "match no extracted row")

    def test_a_duplicated_row_fails(self):
        for sid, invoice, _ in self.CASES:
            with self.subTest(statement=sid):
                self.assert_fails(self.gate(sid, lambda rows: rows.insert(invoice + 1, dict(rows[invoice]))),
                                  "claim the same printed line")

    def test_a_payment_moved_to_the_charged_column_fails(self):
        for sid, _, payment in self.CASES:
            with self.subTest(statement=sid):
                def change(rows):
                    rows[payment]["Charged"], rows[payment]["Paid"] = rows[payment]["Paid"], None
                self.assert_fails(self.gate(sid, change), "extracted Charged")


class TestDetailPage(unittest.TestCase):

    def test_the_due_moves_are_shown(self):
        import test_pdf_row_match as prm
        page = prm.TestValidationPageBadge(methodName="test_method_labels")
        intake = {"statement_id": "C", "source_file": "c.pdf", "vendor_name": "Chuck's Auto Parts Solutions",
                  "statement_period": "2026-09", "statement_total_as_printed": 995.00, "validation_status": "matches",
                  "validation_difference": 0.0, "validation_method": "open_balance", "previous_balance": None,
                  "previous_balance_source": None, "ingestion_timestamp": "2026-10-01T21:00:00+00:00", "passed": True,
                  "primary_computed": -4824.00, "validation_attempts": [],
                  "text_column_corrections": [
                      {"row_number": 1, "invoice_number": "1503634", "date": "09/03/26", "change": "due_from_description",
                       "field": "Due", "from": "225.00 (YOR) 2019 SENTRA L Front Door", "extracted_field": "Due Description",
                       "extracted_value": 225.0, "printed_value": 225.0, "amount": 225.0,
                       "description": "(YOR) 2019 SENTRA L Front Door", "page": 1}]}
        page._patch(get_extraction_validation_detail=lambda sid: {"intake": intake, "computed_total": None, "lines": []})
        try:
            html = page._client().get("/validation/C").text
        finally:
            page.doCleanups()
        self.assertIn('id="due-column-corrections"', html)
        self.assertIn('1 Due amount had been extracted at the front of the "Due Description" text', html)
        self.assertIn("Due moved out of the description", html)
        self.assertIn("(Due Description)", html)
        self.assertIn("(Due)", html)
        self.assertNotIn('id="text-row-corrections"', html)


if __name__ == "__main__":
    unittest.main()
