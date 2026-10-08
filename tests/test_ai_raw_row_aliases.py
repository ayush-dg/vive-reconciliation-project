"""
tests/test_ai_raw_row_aliases.py

src/extraction/ai_raw_row_aliases.normalize_raw_rows() renames a Claude
extraction's verbatim headers to the names in the vendor's seed mapping
(added 2026-10-08), and for Fred Beans joins the UNLABELED_TRANSACTION_CODE
parts into one transaction_code. Fred Beans rows below are the real Bronze
fields of the scanned "Fred Beans (First Choice).pdf" (dev STMT-28766577 /
prod STMT-3C9D4BBB). Reads the real seed CSV.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.extraction.ai_raw_row_aliases import normalize_raw_rows

MAPPED = {"date", "charges", "credits", "amount_due", "transaction_code", "invoice_number"}


def _claude_row(**over):
    row = {"DATE": "20AUG26", "INVOICE NUMBER": "9485340", "UNLABELED_TRANSACTION_CODE": "99",
           "UNLABELED_TRANSACTION_CODE_2": "57", "CHARGES": None, "CREDITS": "100.0",
           "AMOUNT DUE": None, "confidence": "0.9"}
    row.update(over)
    return row


class TestFredBeans(unittest.TestCase):

    def test_claude_headers_become_parser_names(self):
        invoices = [{"_raw_row": _claude_row()}]
        self.assertEqual(normalize_raw_rows(invoices, "FRED_BEANS_PARTS"), 1)
        self.assertEqual(invoices[0]["_raw_row"], {
            "date": "20AUG26", "invoice_number": "9485340", "transaction_code": "99 57",
            "charges": None, "credits": "100.0", "amount_due": None, "confidence": "0.9",
        })
        self.assertTrue(MAPPED <= set(invoices[0]["_raw_row"]))

    def test_header_variations_still_map(self):
        row = {"Invoice #": "9485340", "Charges ": "1601.57", "Amount-Due": "1601.57", "date": "30JUL26",
               "UNLABELED_TRANSACTION_CODE": "66", "UNLABELED_TRANSACTION_CODE_2": "35"}
        invoices = [{"_raw_row": row}]
        normalize_raw_rows(invoices, "FRED_BEANS_PARTS")
        out = invoices[0]["_raw_row"]
        self.assertEqual(out["invoice_number"], "9485340")
        self.assertEqual(out["charges"], "1601.57")
        self.assertEqual(out["amount_due"], "1601.57")
        self.assertEqual(out["transaction_code"], "66 35")

    def test_code_parts_join_in_number_order_and_skip_blanks(self):
        invoices = [{"_raw_row": {"UNLABELED_TRANSACTION_CODE_2": "35", "UNLABELED_TRANSACTION_CODE": "60",
                                  "UNLABELED_TRANSACTION_CODE_3": ""}}]
        normalize_raw_rows(invoices, "FRED_BEANS_PARTS")
        self.assertEqual(invoices[0]["_raw_row"], {"transaction_code": "60 35"})

    def test_parser_rows_are_unchanged(self):
        row = {"date": "10AUG26", "invoice_number": "9508982", "transaction_code": "60 35", "charges": "340.02",
               "credits": "", "amount_due": "", "page": "1", "remit_invoice_no": "9508982", "remit_amount_due": ""}
        invoices = [{"_raw_row": dict(row)}]
        self.assertEqual(normalize_raw_rows(invoices, "FRED_BEANS_PARTS"), 0)
        self.assertEqual(invoices[0]["_raw_row"], row)

    def test_existing_transaction_code_wins_over_unlabeled_parts(self):
        invoices = [{"_raw_row": {"Transaction Code": "60 35", "UNLABELED_TRANSACTION_CODE": "99"}}]
        normalize_raw_rows(invoices, "FRED_BEANS_PARTS")
        self.assertEqual(invoices[0]["_raw_row"], {"transaction_code": "60 35", "UNLABELED_TRANSACTION_CODE": "99"})

    def test_duplicate_header_keeps_first_and_the_other_under_its_own_name(self):
        invoices = [{"_raw_row": {"INVOICE NUMBER": "1", "Invoice No": "2"}}]
        normalize_raw_rows(invoices, "FRED_BEANS_PARTS")
        self.assertEqual(invoices[0]["_raw_row"], {"invoice_number": "1", "Invoice No": "2"})


class TestAstech(unittest.TestCase):
    """Generic case: no per-vendor config, names come from the seed mapping.
    Row = real Bronze fields of scanned "Astech (Lamon).pdf" (prod STMT-EC5E296A)."""

    def test_claude_headers_become_seed_names(self):
        invoices = [{"_raw_row": {"Invoice Date": "09/30/2026", "Invoice #": "SIN12897653", "Work Order #": "26122399",
                                  "RO #": "60102159", "Outstanding Amount": "97.5", "Due Date": "10/30/2026",
                                  "confidence": "0.99"}}]
        self.assertEqual(normalize_raw_rows(invoices, "ASTECH"), 1)
        self.assertEqual(invoices[0]["_raw_row"], {
            "invoice_date": "09/30/2026", "invoice_no": "SIN12897653", "work_order_no": "26122399",
            "ro_no": "60102159", "outstanding_amount": "97.5", "due_date": "10/30/2026", "confidence": "0.99",
        })

    def test_parser_row_unchanged(self):
        row = {"invoice_date": "08/05/2026", "invoice_no": "SIN12639576", "work_order_no": "25378125",
               "ro_no": "6605084", "outstanding_amount": "48.75", "due_date": "09/04/2026"}
        invoices = [{"_raw_row": dict(row)}]
        self.assertEqual(normalize_raw_rows(invoices, "ASTECH"), 0)
        self.assertEqual(invoices[0]["_raw_row"], row)


class TestOtherVendors(unittest.TestCase):

    def test_exact_mapped_names_are_never_renamed(self):
        # FAULKNER's seed maps the Claude header "PURCHASES ($)" itself.
        invoices = [{"_raw_row": {"PURCHASES ($)": "10.00", "PURCHASES": "99.00"}}]
        normalize_raw_rows(invoices, "FAULKNER")
        self.assertEqual(invoices[0]["_raw_row"], {"PURCHASES ($)": "10.00", "PURCHASES": "99.00"})

    def test_vendor_without_mapping_untouched(self):
        row = _claude_row()
        invoices = [{"_raw_row": dict(row)}]
        self.assertEqual(normalize_raw_rows(invoices, "NO_SUCH_VENDOR_XYZ"), 0)
        self.assertEqual(invoices[0]["_raw_row"], row)

    def test_rows_without_raw_row_are_skipped(self):
        invoices = [{}, {"_raw_row": None}, "x"]
        self.assertEqual(normalize_raw_rows(invoices, "FRED_BEANS_PARTS"), 0)
        self.assertEqual(normalize_raw_rows(None, "FRED_BEANS_PARTS"), 0)


if __name__ == "__main__":
    unittest.main()
