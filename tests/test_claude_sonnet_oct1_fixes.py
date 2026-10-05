"""
tests/test_claude_sonnet_oct1_fixes.py

ClaudeSonnetClient column-mapping and request fixes from the 2026-10-01
validation review (scratchpad/oct1_report/oct1_root_cause_analysis.md).
Synthetic rows shaped like each Oct 1 layout; no real API calls.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["CLAUDE_SONNET_TEST_API_KEY"] = "test-claude-key"
os.environ["CLAUDE_SONNET_TEST_DEPLOYMENT"] = "claude-sonnet-4-6"

from src.ai import claude_sonnet_client as csc
from src.ai.claude_sonnet_client import ClaudeSonnetClient
from src.validation.arithmetic_gate import compute_statement_total_from_invoices

CONFIG = {
    "provider": "claude_sonnet",
    "model": "claude-sonnet-4-6",
    "api_key_env_var": "CLAUDE_SONNET_TEST_API_KEY",
    "endpoint_env_var": "CLAUDE_SONNET_TEST_ENDPOINT_UNSET",
    "deployment_env_var": "CLAUDE_SONNET_TEST_DEPLOYMENT",
    "temperature": 0.1,
    "max_output_tokens": 64000,
    "timeout_seconds": 60,
    "retry_policy": {"max_retries": 2, "backoff_seconds": 0, "backoff_multiplier": 1},
}


def client():
    return ClaudeSonnetClient(CONFIG, transport=None)


def invoices_for(columns, rows):
    invoices, _ = client()._rows_to_invoices(rows, columns)
    return invoices


class TestFallbackAmountFloats(unittest.TestCase):
    """F5: JSON floats ending in 0 cents (156.10 -> 156.1) were rejected."""

    def test_float_amounts_with_zero_cents_are_accepted(self):
        self.assertEqual(ClaudeSonnetClient._fallback_amount({"Amt X": 156.1}), ("Amt X", 156.1))
        self.assertEqual(ClaudeSonnetClient._fallback_amount({"Amt X": -10.0}), ("Amt X", -10.0))
        self.assertEqual(ClaudeSonnetClient._fallback_amount({"Amt X": 70.0}), ("Amt X", 70.0))

    def test_integers_are_still_rejected(self):
        # An invoice/PO number returned as a JSON integer is never an amount.
        self.assertEqual(ClaudeSonnetClient._fallback_amount({"Ref": 2504844}), (None, None))

    def test_named_amount_column_preferred_over_first_number(self):
        row = {"Parts": 87.7, "Labor": 104.0, "Total": 191.7}
        self.assertEqual(ClaudeSonnetClient._fallback_amount(row), ("Total", 191.7))

    def test_unnamed_columns_keep_first_currency_value(self):
        self.assertEqual(ClaudeSonnetClient._fallback_amount({"Col A": "12DEC25", "Col C": "706.29"}), ("Col C", 706.29))

    def test_row_level_rows_no_longer_lose_x_x0_amounts(self):
        # NOVUS / O'Reilly: no recognised amount column, amounts like 70.00.
        cols = ["Doc", "Posted", "Value"]
        rows = [{"Doc": "H0028300", "Posted": "08/05/2026", "Value": 70.0},
                {"Doc": "H0028299", "Posted": "08/21/2026", "Value": 332.17}]
        self.assertEqual([i["outstanding_amount"] for i in invoices_for(cols, rows)], [70.0, 332.17])


class TestHeaderMapping(unittest.TestCase):

    def test_bare_total_header_is_the_amount_when_nothing_else_maps(self):
        # Twin City: Parts / Labor / Tire / Fees / Tax / Total.
        cols = ["INV Number", "INV Date", "Parts", "Labor", "Fees", "Total"]
        rows = [{"INV Number": "190033", "INV Date": "Aug 24, 2026", "Parts": 87.7, "Labor": 104.0, "Fees": None, "Total": 191.7},
                {"INV Number": "190172", "INV Date": "Aug 27, 2026", "Parts": None, "Labor": 24.0, "Fees": 5.95, "Total": 29.95}]
        self.assertEqual([i["outstanding_amount"] for i in invoices_for(cols, rows)], [191.7, 29.95])

    def test_total_header_never_displaces_a_real_amount_column(self):
        field_map = client()._map_columns(["Invoice #", "Amount Due", "Total"], [])
        self.assertEqual(field_map["outstanding_amount"], "Amount Due")

    def test_signed_invoice_credit_column(self):
        # Continental "Invoice / Credit": every row used to be subtracted.
        cols = ["Trans Date", "Invoice", "Invoice / Credit", "Balance"]
        rows = [{"Trans Date": "07/14/26", "Invoice": "20493533", "Invoice / Credit": -270.0, "Balance": -270.0},
                {"Trans Date": "08/25/26", "Invoice": "20581623", "Invoice / Credit": 222.0, "Balance": -48.0}]
        invs = invoices_for(cols, rows)
        self.assertEqual((invs[0]["charges"], invs[0]["credit"]), (None, 270.0))
        self.assertEqual((invs[1]["charges"], invs[1]["credit"]), (222.0, None))
        self.assertEqual(compute_statement_total_from_invoices(invs), -48.0)

    def test_charges_and_credits_header_is_signed(self):
        # Parts Authority "CHARGES AND CREDITS".
        field_map = client()._map_columns(["DATE", "REFERENCE", "CHARGES AND CREDITS", "BALANCE"], [])
        self.assertEqual(field_map.get("signed_amount"), "CHARGES AND CREDITS")
        self.assertNotIn("credit", field_map)

    def test_invoice_credit_number_column_is_not_signed(self):
        field_map = client()._map_columns(["Invoice/Credit #", "Amount"], [])
        self.assertNotIn("signed_amount", field_map)

    def test_applied_to_is_not_a_credit_column(self):
        # Yerty: "Applied To" holds a PO number.
        field_map = client()._map_columns(["Invoice #", "Applied To", "Original Amount", "Amount Remain"], [])
        self.assertNotIn("credit", field_map)

    def test_singular_charge_and_payment_headers(self):
        # Headlights Depot / Wheel Collision.
        field_map = client()._map_columns(["Date", "Description", "Charge", "Payment", "Balance"], [])
        self.assertEqual(field_map["charges"], "Charge")
        self.assertEqual(field_map["credit"], "Payment")
        self.assertEqual(field_map["amount_due"], "Balance")

    def test_payment_due_date_is_still_a_date(self):
        field_map = client()._map_columns(["Payment Due Date", "Invoice #", "Amount"], [])
        self.assertEqual(field_map.get("due_date"), "Payment Due Date")
        self.assertNotIn("credit", field_map)

    def test_open_amount_is_the_outstanding_column(self):
        field_map = client()._map_columns(["DATE", "TRANS #", "INV AMOUNT", "OPEN AMOUNT"], [])
        self.assertEqual(field_map["outstanding_amount"], "OPEN AMOUNT")
        self.assertNotIn("charges", field_map)

    def test_unallocated_column(self):
        cols = ["Date", "Transaction Type", "Charged", "Paid", "Unalloc.", "Due"]
        rows = [{"Date": "08/28/26", "Transaction Type": "Payment: Check 7226856588", "Charged": None,
                 "Paid": 3265.0, "Unalloc.": 650.0, "Due": None}]
        inv = invoices_for(cols, rows)[0]
        self.assertEqual(inv["unallocated"], 650.0)
        self.assertEqual(inv["credit"], 3265.0)

    def test_run_together_unalloc_due_header_stays_outstanding(self):
        field_map = client()._map_columns(["Charged", "Paid", "Unalloc. Due"], [])
        self.assertNotIn("unallocated", field_map)
        self.assertEqual(field_map["amount_due"], "Unalloc. Due")


class TestRecapRows(unittest.TestCase):
    """F6: CDK/Reynolds per-invoice net-balance recap lines."""

    COLS = ["DATE", "INVOICE", "AMOUNT"]

    def test_recap_line_after_multi_line_invoice_is_dropped(self):
        rows = [{"DATE": "07-08", "INVOICE": "TOW369860", "AMOUNT": 1128.06},
                {"DATE": "07-16", "INVOICE": "TOW369860", "AMOUNT": -109.14},
                {"DATE": None, "INVOICE": None, "AMOUNT": 1018.92},
                {"DATE": "07-09", "INVOICE": "TOW369962", "AMOUNT": 37.05}]
        invs = invoices_for(self.COLS, rows)
        self.assertEqual([i["invoice_number"] for i in invs], ["TOW369860", "TOW369860", "TOW369962"])

    def test_dated_payment_without_invoice_number_is_kept(self):
        rows = [{"DATE": "07-08", "INVOICE": "A1", "AMOUNT": 100.0},
                {"DATE": "07-09", "INVOICE": "A1", "AMOUNT": -40.0},
                {"DATE": "07-20", "INVOICE": None, "AMOUNT": 60.0}]
        self.assertEqual(len(invoices_for(self.COLS, rows)), 3)

    def test_undated_row_that_is_not_the_group_net_is_kept(self):
        rows = [{"DATE": "07-08", "INVOICE": "A1", "AMOUNT": 100.0},
                {"DATE": "07-09", "INVOICE": "A1", "AMOUNT": -40.0},
                {"DATE": None, "INVOICE": None, "AMOUNT": 75.0}]
        self.assertEqual(len(invoices_for(self.COLS, rows)), 3)

    def test_single_row_invoice_is_never_a_recap_group(self):
        rows = [{"DATE": "07-08", "INVOICE": "A1", "AMOUNT": 100.0},
                {"DATE": None, "INVOICE": None, "AMOUNT": 100.0}]
        self.assertEqual(len(invoices_for(self.COLS, rows)), 2)


class TestLastPaymentNotes(unittest.TestCase):
    """F8: an informational "LAST PAYMENT" note never carries an amount."""

    def test_maine_oxy_last_payment_note_gets_no_amount(self):
        cols = ["DATE", "INVOICE NUMBER", "CODE", "AMOUNT"]
        rows = [{"DATE": "08/31/26", "INVOICE NUMBER": "5000359406", "CODE": "6", "AMOUNT": 165.11},
                {"DATE": "07/21/26", "INVOICE NUMBER": None, "CODE": "LAST PAYMENT:", "AMOUNT": 134.03}]
        invs = invoices_for(cols, rows)
        self.assertEqual(len(invs), 2)  # still reaches Bronze
        self.assertTrue(invs[1]["informational"])
        self.assertIsNone(invs[1]["outstanding_amount"])
        self.assertEqual(compute_statement_total_from_invoices(invs), 165.11)

    def test_fallback_never_assigns_an_amount_to_the_note(self):
        cols = ["Col A", "Col B"]
        rows = [{"Col A": "07/30/26", "Col B": "Last payment of 2177.85 received"}]
        inv = invoices_for(cols, rows)[0]
        self.assertTrue(inv["informational"])
        self.assertIsNone(inv["outstanding_amount"])

    def test_note_with_its_own_invoice_number_is_a_normal_row(self):
        cols = ["Invoice #", "Description", "Amount"]
        rows = [{"Invoice #": "INV9", "Description": "Last payment adjustment", "Amount": 12.5}]
        inv = invoices_for(cols, rows)[0]
        self.assertFalse(inv["informational"])
        self.assertEqual(inv["outstanding_amount"], 12.5)


class TestRunningLedgerMapping(unittest.TestCase):
    """LKQ prints Balance Due as a running balance; Keystone (same headers)
    as a per-row open balance. Only a provable chain is remapped."""

    COLS = ["Reference Date", "Reference Number", "Balance Forward", "Period Activity",
            "Credit Applied", "Payment Applied", "Balance Due"]

    @staticmethod
    def ledger_row(number, activity=None, credit=None, payment=None, balance=None):
        return {"Reference Date": "08/04/26", "Reference Number": number, "Balance Forward": None,
                "Period Activity": activity, "Credit Applied": credit, "Payment Applied": payment, "Balance Due": balance}

    def test_running_balance_ledger_is_remapped_to_activity(self):
        rows = [self.ledger_row("177299876", activity=61.5, balance=1539.5),
                self.ledger_row("177310269", activity=109.5, balance=1649.0),
                self.ledger_row("177593667", credit=-109.5, balance=1539.5),
                self.ledger_row("7226837198", payment=-1478.0, balance=61.5)]
        invs = invoices_for(self.COLS, rows)
        self.assertEqual([i["outstanding_amount"] for i in invs], [61.5, 109.5, None, None])
        self.assertEqual([i["credit"] for i in invs], [None, None, 109.5, 1478.0])
        self.assertEqual([i["amount_due"] for i in invs], [1539.5, 1649.0, 1539.5, 61.5])
        self.assertEqual(compute_statement_total_from_invoices(invs), -1416.5)

    def test_open_item_ledger_is_left_unchanged(self):
        rows = [self.ledger_row("G4803890", activity=466.59, balance=466.59),
                self.ledger_row("G4803891", activity=152.08, balance=152.08),
                self.ledger_row("G4803892", activity=326.55, balance=326.55)]
        invs = invoices_for(self.COLS, rows)
        self.assertEqual([i["outstanding_amount"] for i in invs], [466.59, 152.08, 326.55])
        self.assertTrue(all(i["amount_due"] is None for i in invs))


class TestSections(unittest.TestCase):

    def test_row_section_key_is_carried_and_never_used_as_a_value(self):
        cols = ["Invoice#", "Purchases"]
        rows = [{"Invoice#": "601849-5", "Purchases": 180.8, "section": "Lehigh Valley Honda"}]
        inv = invoices_for(cols, rows)[0]
        self.assertEqual(inv["section"], "Lehigh Valley Honda")
        self.assertEqual(inv["invoice_number"], "601849-5")

    def test_section_totals_parsing(self):
        parse = ClaudeSonnetClient._parse_section_totals
        self.assertEqual(parse([{"section": "Honda", "subtotal": "21,521.17", "invoice_count": "56"}]),
                         [{"section": "Honda", "subtotal": 21521.17, "invoice_count": 56}])
        self.assertIsNone(parse(None))
        self.assertIsNone(parse([{"section": "Honda", "subtotal": None}]))  # incomplete -> unusable


class TestGenerateWithFile(unittest.TestCase):

    def setUp(self):
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.write(b"%PDF-1.4 tiny")
        f.close()
        self.pdf = f.name
        self.addCleanup(os.remove, self.pdf)

    def test_read_timeout_is_not_retried(self):
        c = client()
        with mock.patch.object(c, "_real_file_call", return_value=(False, "", csc.READ_TIMEOUT_ERROR)) as call:
            response = c.generate_with_file(self.pdf, "")
        self.assertFalse(response.success)
        self.assertEqual(call.call_count, 1)
        self.assertIn("timed out", response.error)

    def test_other_errors_are_still_retried(self):
        c = client()
        with mock.patch.object(c, "_real_file_call", return_value=(False, "", "Claude API overloaded")) as call:
            c.generate_with_file(self.pdf, "")
        self.assertEqual(call.call_count, 3)

    def test_no_table_at_all_is_marked_not_a_statement(self):
        c = client()
        body = json.dumps({"vendor_name": None, "columns_found": [], "rows": []})
        with mock.patch.object(c, "_real_file_call", return_value=(True, body, None)):
            response = c.generate_with_file(self.pdf, "")
        self.assertTrue(response.success)
        self.assertEqual(response.parsed_json["document_metadata"]["document_type"], csc.NOT_A_STATEMENT)

    def test_previous_balance_and_sections_reach_statement_metadata(self):
        c = client()
        body = json.dumps({
            "vendor_name": "X", "statement_total_as_printed": 526.5,
            "previous_balance": "707.00", "previous_balance_label": "Balance Forward",
            "section_totals": [{"section": "Main", "subtotal": 526.5, "invoice_count": 3}],
            "columns_found": ["Invoice #", "Amount"],
            "rows": [{"Invoice #": "63170", "Amount": 175.5, "section": "Main"}],
        })
        with mock.patch.object(c, "_real_file_call", return_value=(True, body, None)):
            meta = c.generate_with_file(self.pdf, "").parsed_json["statement_metadata"]
        self.assertEqual(meta["previous_balance"], 707.0)
        self.assertEqual(meta["previous_balance_label"], "Balance Forward")
        self.assertEqual(meta["section_totals"], [{"section": "Main", "subtotal": 526.5, "invoice_count": 3}])


class TestOversizedPdf(unittest.TestCase):

    def _image_pdf(self):
        import pymupdf
        from PIL import Image
        import io
        noise = Image.frombytes("RGB", (1400, 1400), os.urandom(1400 * 1400 * 3))
        buf = io.BytesIO()
        noise.save(buf, format="PNG")
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        page.insert_image(page.rect, stream=buf.getvalue())
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.close()
        doc.save(f.name)
        doc.close()
        self.addCleanup(os.remove, f.name)
        return f.name

    def test_small_pdf_is_sent_unchanged(self):
        path = self._image_pdf()
        with open(path, "rb") as fh:
            original = fh.read()
        self.assertEqual(client()._pdf_bytes_for_upload(path), original)

    def test_oversized_pdf_is_re_rendered_under_the_limit(self):
        path = self._image_pdf()
        size = os.path.getsize(path)
        c = client()
        with mock.patch.object(ClaudeSonnetClient, "MAX_UPLOAD_PDF_BYTES", size - 1):
            sent = c._pdf_bytes_for_upload(path)
        self.assertLess(len(sent), size)
        self.assertTrue(sent.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
