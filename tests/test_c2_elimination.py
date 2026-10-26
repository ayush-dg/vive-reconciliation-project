"""C2 row correction: a row identified by elimination (2026-10-26, NYE SYNTH_9_QZXW STMT-B0E5C005).

On NYE's single signed AMOUNT layout an invoice and its credit memo can share a reference and a date
("08-14 4 XYZ900001C-1 52.17" / "08-14 4 XYZ900001C-1 CMXYZ900001C-1 1 -23.58"). C2 tells such lines
apart by the row's printed words. When the model puts the credit memo's reference on the invoice row,
that row's words match neither line and C2 refused -- so three other rows whose amounts the model took
from the neighbouring printed line were never corrected. Now such a row takes, by elimination, the ONE
line with its reference and date no other row claims -- only if its amount already equals that line's
printed amount; no cell is ever changed on an identity found that way, and every other C2 rule stands.

Synthetic text-layer PDFs only (PyMuPDF), in the NYE shape; OCR is mocked.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_text_row_corrections import AMOUNT_COLUMNS, _Case, amount_pdf, amount_rows  # noqa: E402

from src.validation import text_columns as tc  # noqa: E402
from test_text_columns import to_invoices  # noqa: E402

# The PDF: two invoices, then an invoice and its credit memo on the same day (the credit memo prints a
# reference and a description word).
LINES = [("08/11/2026", "INV9001", None, "100.00"),
         ("08/11/2026", "INV9002", None, "50.00"),
         ("08/14/2026", "INV9003", None, "41.04"),
         ("08/14/2026", "INV9003", "CMINV9003 PS", "-18.46")]
PRINTED = 172.58   # 100.00 + 50.00 + 41.04 - 18.46


def rows(inv2_amount=41.04, inv3_ref="CMINV9003", inv3_amount=41.04):
    """The model's rows: INV9002 took the next line's amount (41.04), and the INV9003 invoice row carries
    its credit memo's reference."""
    return amount_rows([("08/11/2026", "INV9001", None, 100.0), ("08/11/2026", "INV9002", None, inv2_amount),
                        ("08/14/2026", "INV9003", inv3_ref, inv3_amount),
                        ("08/14/2026", "INV9003", "CMINV9003 PS", -18.46)])


class TestElimination(_Case):

    def test_the_row_found_by_elimination_lets_the_wrong_amount_be_corrected(self):
        s, v = self.validate(rows(), self.pdf(amount_pdf(LINES)), PRINTED, AMOUNT_COLUMNS)
        self.assertEqual((v["status"], v["method"]), ("matches", "primary"))
        self.assertEqual([(c["invoice_number"], c["change"], c["extracted_value"], c["printed_value"])
                          for c in v["detail"]["text_column_corrections"]], [("INV9002", "replaced", 41.04, 50.0)])
        self.assertEqual([e["invoice_number"] for e in v["detail"]["text_column_identified_by_elimination"]], ["INV9003"])
        self.assertEqual(s["invoices"][1]["outstanding_amount"], 50.0)
        self.assertEqual(s["invoices"][2]["outstanding_amount"], 41.04)   # unchanged
        self.assertEqual(s["invoices"][2]["_raw_row"]["REFERENCE"], "CMINV9003")   # cells are never rewritten by elimination

    def test_a_row_found_by_elimination_whose_amount_differs_changes_nothing(self):
        rs = rows(inv3_amount=40.04)
        s, v = self.validate(rs, self.pdf(amount_pdf(LINES)), PRINTED, AMOUNT_COLUMNS)
        self.assert_unchanged(s, v, rs, AMOUNT_COLUMNS)
        self.assertIn("matches 0 printed lines", v["detail"]["text_column_check"]["row_check"])

    def test_two_rows_competing_for_one_line_change_nothing(self):
        rs = rows()
        rs[3]["REFERENCE"] = "CMINV9003"   # the credit memo row's words now match no line either
        s, v = self.validate(rs, self.pdf(amount_pdf(LINES)), PRINTED, AMOUNT_COLUMNS)
        self.assert_unchanged(s, v, rs, AMOUNT_COLUMNS)

    def test_a_row_with_no_line_of_its_own_still_refuses_first(self):
        rs = rows()
        rs[0]["INVOICE"] = "INV9999"   # printed nowhere
        plan = tc.plan_text_row_corrections(to_invoices(rs, AMOUNT_COLUMNS), self.pdf(amount_pdf(LINES)), PRINTED)
        self.assertFalse(plan["applicable"])
        self.assertEqual(plan["reason"], "row 1 (INV9999) 08/11/2026: matches 0 printed lines, not exactly one")

    def test_the_old_first_refusal_is_kept_when_a_later_row_refuses(self):
        rs = rows()
        rs[1]["INVOICE"] = "INV9999"   # row 2 refuses; row 3 (deferred) comes after it
        plan = tc.plan_text_row_corrections(to_invoices(rs, AMOUNT_COLUMNS), self.pdf(amount_pdf(LINES)), PRINTED)
        self.assertEqual(plan["reason"], "row 2 (INV9999) 08/11/2026: matches 0 printed lines, not exactly one")
        rs = rows()
        rs[3]["INVOICE"] = "INV9999"   # a refusal after the deferred row 3: row 3's own reason, as before
        plan = tc.plan_text_row_corrections(to_invoices(rs, AMOUNT_COLUMNS), self.pdf(amount_pdf(LINES)), PRINTED)
        self.assertEqual(plan["reason"], "row 3 (INV9003) 08/14/2026: matches 0 printed lines, not exactly one")

    def test_without_the_reference_mistake_nothing_is_eliminated(self):
        s, v = self.validate(rows(inv3_ref=None), self.pdf(amount_pdf(LINES)), PRINTED, AMOUNT_COLUMNS)
        self.assertEqual((v["status"], v["method"]), ("matches", "primary"))
        self.assertNotIn("text_column_identified_by_elimination", v["detail"])


if __name__ == "__main__":
    unittest.main()
