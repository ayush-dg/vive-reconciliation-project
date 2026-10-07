"""
tests/test_validation_text_fallbacks.py

The 2026-10-07 text-based additions to the Arithmetic Validation Gate:
  - printed_total.py: the printed total read from a total-labelled line when
    the extraction returned none (Collex / Clinton Honda CDK layout, Fenix
    reprints),
  - ocr_text.py wiring: a scan's OCR text read with the same labelled-line
    rules as a text layer (Paragon Seacoast, Emerson Toyota),
  - notebooks/01_document_intake.py apply_arithmetic_validation() using them.

Every addition only supplies a printed figure; the extracted rows still have
to reproduce it exactly (0.01). The adversarial tests prove a wrong
extraction -- misread amount, a group statement's single store, unlabelled
or disagreeing figures -- still fails. OCR is always mocked here:
no tesseract, network or database is touched. Synthetic data only, modelled
on the Oct 1 / Oct 5 statements named in each test.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.ai.claude_sonnet_client import NOT_A_STATEMENT
from src.validation.arithmetic_gate import compute_statement_total_from_invoices
from src.validation.previous_balance import resolve_previous_balance
from src.validation.printed_total import find_printed_total
from test_oct1_intake_worker_web import INTAKE, TEXT_LAYER, load_intake


def inv(number, out=None, credit=None, due=None):
    return {"invoice_number": number, "outstanding_amount": out, "credit": credit, "amount_due": due, "_raw_row": {}}


def schema(invoices, printed, **stmt):
    return {
        "document_metadata": {"document_type": stmt.pop("doc_type", "VENDOR_STATEMENT")},
        "vendor_metadata": {"vendor_name": "Synthetic Vendor"},
        "statement_metadata": {"statement_total_as_printed": printed,
                               "statement_total_computed": compute_statement_total_from_invoices(invoices) if invoices else None,
                               **stmt},
        "invoices": invoices,
    }


CDK_STUB = ("08/31/26 INV9001 1,200.00\nACCOUNT PAST DUE CURRENT PLEASE PAY\n"
            "ST A T US 0.00 4,484.09 T H IS A M O U N T 4,484.09\nOVER 30 OVER 60 OVER 90 OVER 120\n"
            "FINANCE CHARGES will apply if the new balance is unpaid one month from the closing date")
GROUP_PAGE = ("Emmaus, PA 18049 Monthly Statement\nTotal Amount Due $168,640.83\n"
              "Lehigh Valley Honda Invoices: 56: Amount Due: $21,521.17\n"
              "Lehigh Valley Hyundai Invoices: 39 Amount Due: $25,603.60\n")


# ---------------------------------------------------------------------------
# printed_total.find_printed_total()
# ---------------------------------------------------------------------------

class TestFindPrintedTotal(unittest.TestCase):

    def test_cdk_letter_spaced_split_label(self):
        # Collex Tinton / Clinton Honda Lyndhurst: "PLEASE PAY" / "... THIS AMOUNT 4,484.09".
        self.assertEqual(find_printed_total(CDK_STUB), 4484.09)

    def test_two_labels_printing_the_same_amount(self):
        # Fenix reprint: "Total due 3425.00" and "Balance due 3425.00".
        self.assertEqual(find_printed_total("Total due 3425.00\nBalance due 3425.00"), 3425.0)

    def test_adversarial_labels_disagree(self):
        self.assertIsNone(find_printed_total("Total due 3425.00\nBalance due 3245.00"))

    def test_adversarial_group_total_and_store_amount_disagree(self):
        # A group statement prints two different "amount due" figures -- never pick one.
        self.assertIsNone(find_printed_total(GROUP_PAGE))

    def test_adversarial_only_zero_values(self):
        self.assertIsNone(find_printed_total("ST A T US 0.00 0.00 T H IS A M O U N T 0.00"))

    def test_adversarial_value_not_on_the_label_line(self):
        # Lithia: the label heads a column, the figure sits on the next, unlabelled line.
        self.assertIsNone(find_printed_total("Current 30-59 60-89 Total Amount Due\n$1,112.52 ($296.40) $0.00 $816.12"))

    def test_adversarial_no_label_or_prose_only(self):
        self.assertIsNone(find_printed_total("Grand 100.00\nFINANCE CHARGES will apply if the new balance is unpaid"))
        self.assertIsNone(find_printed_total(""))
        self.assertIsNone(find_printed_total(None))


# ---------------------------------------------------------------------------
# previous_balance on OCR text
# ---------------------------------------------------------------------------

OCR_PARAGON = "47 Bath Rd TOTAL DUE $351.00\n" + "\n".join(f"line {i} of the scan" for i in range(40)) + \
    "\n08/31/2026 Balance Forward 1,755.00\n"


class TestPreviousBalanceOnOcrText(unittest.TestCase):

    def test_labelled_value_in_ocr_text(self):
        result = resolve_previous_balance(None, None, OCR_PARAGON, text_source="ocr")
        self.assertEqual((result["value"], result["source"]), (1755.0, "ocr"))

    def test_model_value_corroborated_by_ocr(self):
        result = resolve_previous_balance(1755.0, "Balance Forward", OCR_PARAGON, text_source="ocr")
        self.assertEqual((result["value"], result["source"]), (1755.0, "model+ocr"))

    def test_adversarial_model_value_not_printed_on_a_labelled_ocr_line(self):
        result = resolve_previous_balance(1575.0, "Balance Forward", OCR_PARAGON, text_source="ocr")
        self.assertIsNone(result["value"])
        self.assertTrue(result["source"].startswith("rejected"))

    def test_default_source_is_unchanged(self):
        result = resolve_previous_balance(None, None, OCR_PARAGON)
        self.assertEqual(result["source"], "text_layer")


# ---------------------------------------------------------------------------
# apply_arithmetic_validation() wiring
# ---------------------------------------------------------------------------

def paragon_rows():
    # Paragon Seacoast (scan): two charges and a payment; the printed 351.00
    # also includes the 1,755.00 balance forward.
    return [inv("P1", 175.5), inv(None, -1755.0), inv("P2", 175.5)]


class TestApplyValidationWithText(unittest.TestCase):

    def test_scan_previous_balance_read_from_ocr(self):
        s = schema(paragon_rows(), 351.0)
        with mock.patch.object(load_intake(), "ocr_pdf_text", return_value=OCR_PARAGON) as ocr:
            result = INTAKE.apply_arithmetic_validation(s, "", "scan.pdf")
        ocr.assert_called_once_with("scan.pdf")
        self.assertEqual((result["status"], result["method"]), ("matches", "statement_equation"))
        self.assertEqual(s["statement_metadata"]["previous_balance_source"], "ocr")
        self.assertEqual(result["detail"]["text_source"], "ocr")

    def test_adversarial_scan_with_a_misread_row_still_fails(self):
        rows = [inv("P1", 175.5), inv(None, -1755.0), inv("P2", 157.5)]
        with mock.patch.object(load_intake(), "ocr_pdf_text", return_value=OCR_PARAGON):
            result = INTAKE.apply_arithmetic_validation(schema(rows, 351.0), "", "scan.pdf")
        self.assertEqual(result["status"], "mismatch")

    def test_adversarial_scan_whose_ocr_has_no_labelled_balance_still_fails(self):
        ocr_text = "\n".join(f"line {i} 1,755.00" for i in range(40))  # value printed, never labelled
        with mock.patch.object(load_intake(), "ocr_pdf_text", return_value=ocr_text):
            result = INTAKE.apply_arithmetic_validation(schema(paragon_rows(), 351.0), "", "scan.pdf")
        self.assertEqual(result["status"], "mismatch")

    def test_adversarial_ocr_balance_never_undoes_a_running_balance_pass(self):
        # A scan whose primary check uses a different computed total (e.g. a
        # per-vendor gate column) but whose printed row balances chain from
        # 0 to the printed 130.00. Its OCR text shows a labelled balance
        # forward (85.00): trying that first would make it the chain's
        # opening and break the chain -- the pass must survive.
        rows = [inv("N1", 100.0, due=100.0), inv("N2", 30.0, due=130.0)]
        s = schema(rows, 130.0, statement_total_computed=100.0)
        ocr_text = OCR_PARAGON.replace("1,755.00", "85.00")
        with mock.patch.object(load_intake(), "ocr_pdf_text", return_value=ocr_text) as ocr:
            result = INTAKE.apply_arithmetic_validation(s, "", "scan.pdf")
        ocr.assert_called_once()
        self.assertEqual((result["status"], result["method"]), ("matches", "running_balance"))
        self.assertIsNone(s["statement_metadata"]["previous_balance"])

    def test_adversarial_failing_scan_keeps_its_own_previous_balance_record(self):
        # When the OCR value doesn't help either, nothing about the previous
        # balance is recorded from it.
        rows = [inv("P1", 175.5), inv(None, -1755.0), inv("P2", 157.5)]
        s = schema(rows, 351.0)
        with mock.patch.object(load_intake(), "ocr_pdf_text", return_value=OCR_PARAGON):
            INTAKE.apply_arithmetic_validation(s, "", "scan.pdf")
        self.assertIsNone(s["statement_metadata"]["previous_balance"])

    def test_ocr_unavailable_behaves_as_before(self):
        with mock.patch.object(load_intake(), "ocr_pdf_text", return_value=""):
            result = INTAKE.apply_arithmetic_validation(schema(paragon_rows(), 351.0), "", "scan.pdf")
        self.assertEqual(result["status"], "mismatch")
        self.assertNotIn("text_source", result["detail"] or {})

    def test_no_ocr_when_the_pdf_has_a_text_layer(self):
        with mock.patch.object(load_intake(), "ocr_pdf_text") as ocr:
            INTAKE.apply_arithmetic_validation(schema(paragon_rows(), 351.0), TEXT_LAYER, "text.pdf")
        ocr.assert_not_called()

    def test_no_ocr_when_the_scan_already_matches(self):
        rows = [inv("P1", 175.5), inv("P2", 175.5)]
        with mock.patch.object(load_intake(), "ocr_pdf_text") as ocr:
            result = INTAKE.apply_arithmetic_validation(schema(rows, 351.0), "", "scan.pdf")
        ocr.assert_not_called()
        self.assertEqual(result["method"], "primary")

    def test_no_ocr_for_a_non_statement(self):
        with mock.patch.object(load_intake(), "ocr_pdf_text") as ocr:
            result = INTAKE.apply_arithmetic_validation(schema([], None, doc_type=NOT_A_STATEMENT), "", "mail.pdf")
        ocr.assert_not_called()
        self.assertEqual(result["status"], "not_a_statement")

    def test_missing_printed_total_read_from_the_text_layer(self):
        rows = [inv("C1", 1200.0), inv("C2", 3284.09)]
        s = schema(rows, None)
        result = INTAKE.apply_arithmetic_validation(s, TEXT_LAYER + "\n" + CDK_STUB, "collex.pdf")
        self.assertEqual((result["status"], result["method"]), ("matches", "primary"))
        self.assertEqual(s["statement_metadata"]["statement_total_as_printed"], 4484.09)
        self.assertEqual(result["detail"]["printed_total_source"], "text_layer")

    def test_adversarial_printed_total_from_text_with_wrong_rows_fails(self):
        rows = [inv("C1", 1200.0), inv("C2", 3248.09)]  # a misread row
        s = schema(rows, None)
        result = INTAKE.apply_arithmetic_validation(s, TEXT_LAYER + "\n" + CDK_STUB, "collex.pdf")
        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(s["statement_metadata"]["statement_total_as_printed"], 4484.09)

    def test_an_extracted_printed_total_is_never_replaced(self):
        rows = [inv("C1", 1200.0), inv("C2", 3284.09)]
        s = schema(rows, 4000.0)
        result = INTAKE.apply_arithmetic_validation(s, TEXT_LAYER + "\n" + CDK_STUB, "collex.pdf")
        self.assertEqual(s["statement_metadata"]["statement_total_as_printed"], 4000.0)
        self.assertEqual(result["status"], "mismatch")

    def test_no_printed_total_anywhere_stays_total_not_found(self):
        result = INTAKE.apply_arithmetic_validation(schema([inv("H1", 10.0)], None), TEXT_LAYER, "healey.pdf")
        self.assertEqual(result["status"], "total_not_found")

    def test_adversarial_group_statement_fragment_still_fails(self):
        # LV HONDA LV 0826 (Oct 1): pages 9-11 of a 13-page group statement.
        # Its 56 Honda rows reproduce the Honda section line, but the printed
        # total is the whole group's and the file also holds the start of the
        # Hyundai section -- rows the extraction never returned. It must fail.
        rows = [inv(f"H{i}", a) for i, a in enumerate([384.31] * 55 + [384.31 * -55 + 21521.17])]
        with mock.patch.object(load_intake(), "ocr_pdf_text", return_value=GROUP_PAGE * 12):
            result = INTAKE.apply_arithmetic_validation(schema(rows, 168640.83), "", "honda.pdf")
        self.assertEqual(round(sum(r["outstanding_amount"] for r in rows), 2), 21521.17)
        self.assertEqual(result["status"], "mismatch")
        self.assertIsNone(result["method"])

if __name__ == "__main__":
    unittest.main()
