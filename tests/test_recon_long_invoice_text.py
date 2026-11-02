"""
tests/test_recon_long_invoice_text.py

2026-11-02, prod: Wheels On Site statements showed "Reconciliation Not run". Their invoice number is
inside the DESCRIPTION text ("Invoice #00630634: Due ... Work Order: ...; Vin ...; RO# ...; PO# ...",
up to 114 chars), matching read 00630634 from it fine, but the full text went into
original_invoice_number (VARCHAR(100) in silver.recon_matched_invoices / recon_exceptions), so the
INSERT failed and the whole statement's results were lost. The stored copy is now cut to 100 chars.

The job note for such statements said "no ERP reference data loaded for this vendor yet, matching
skipped" -- the legacy Phase 2's error, printed for every statement past the validation gate,
reconciled or not. It now says what NetSuite matching did (RECON_DONE / RECON_FAILED markers).
"""

import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.matching import fabric_matching as fm
from src.pipeline_markers import RECON_DONE_MARKER, RECON_FAILED_MARKER
from web import worker

WHEELS_ON_SITE_TEXT = ("Invoice #00630634: Due 10/25/2026. Work Order: 2019 Ford Mustang; Vin - K5141279; "
                       "RO# - 60500458; PO# - 60500458")
NO_VOUCHER = "ValueError: No real voucher-sourced INTERNAL_ERP rows for vendor_id='WHEELS_ON_SITE'\n"


class StoredInvoiceTextIsCutTests(unittest.TestCase):

    def _row(self, table, write, **kwargs):
        writes = fm._PendingWrites()
        write(writes, **kwargs)
        columns, rows = writes._rows[table]
        return dict(zip(columns, rows[0]))

    def test_a_matched_line_keeps_its_invoice_and_cuts_the_raw_text(self):
        self.assertGreater(len(WHEELS_ON_SITE_TEXT), fm.INVOICE_TEXT_MAX)
        row = self._row("silver.recon_matched_invoices", fm._write_match,
                        statement_id="STMT-1", vendor_id="WHEELS_ON_SITE", shop="S", invoice_number="00630634",
                        ro_number=None, stmt_amount=169.5, erp_amount=169.5, now="t",
                        original_invoice_number=WHEELS_ON_SITE_TEXT)
        self.assertEqual(row["invoice_number"], "00630634")
        self.assertEqual(row["original_invoice_number"], WHEELS_ON_SITE_TEXT[:100])

    def test_an_exception_cuts_both_texts(self):
        row = self._row("silver.recon_exceptions", fm._write_exception,
                        statement_id="STMT-1", vendor_id="V", shop="S", shop_owner=None,
                        invoice_number="x" * 130, ro_number=None, stmt_amount=1.0, erp_amount=None,
                        reason="Not Found in NetSuite", now="t", original_invoice_number=WHEELS_ON_SITE_TEXT)
        self.assertEqual(len(row["invoice_number"]), 100)
        self.assertEqual(len(row["original_invoice_number"]), 100)

    def test_short_and_missing_values_are_unchanged(self):
        row = self._row("silver.recon_exceptions", fm._write_exception,
                        statement_id="STMT-1", vendor_id="V", shop="S", shop_owner=None,
                        invoice_number="INV1", ro_number=None, stmt_amount=1.0, erp_amount=None,
                        reason="Not Found in NetSuite", now="t", original_invoice_number=None)
        self.assertEqual((row["invoice_number"], row["original_invoice_number"]), ("INV1", None))


class ShortErrorTests(unittest.TestCase):

    def test_driver_noise_is_dropped(self):
        exc = Exception("22001", "[22001] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]String or binary "
                                 "data would be truncated in table 'w.silver.recon_exceptions'. (2628) (SQLExecDirectW)")
        self.assertEqual(fm._short_error(exc),
                         "Exception: String or binary data would be truncated in table 'w.silver.recon_exceptions'.")

    def test_a_plain_error_keeps_its_text(self):
        self.assertEqual(fm._short_error(ValueError("boom")), "ValueError: boom")


class JobNoteTests(unittest.TestCase):

    def run_job(self, stdout):
        job = {"job_id": "J1", "pdf_path": __file__, "pdf_filename": "x.pdf", "source_blob_path": None}
        completed = subprocess.CompletedProcess(args=[], returncode=1, stdout=stdout, stderr="")
        with mock.patch("web.worker.subprocess.run", return_value=completed), \
                mock.patch("web.queries.get_silver_row_count", return_value=13), \
                mock.patch("web.queries.get_vendor_name_for_statement", return_value="Wheels On Site"), \
                mock.patch.object(worker, "_write_blob_outcome"), mock.patch("builtins.print"), \
                mock.patch("web.queries.update_job_status") as update:
            worker._run_job(job)
        kwargs = update.call_args.kwargs
        self.assertEqual(kwargs["status"], "COMPLETED")
        return kwargs["error_message"]

    def test_reconciled(self):
        note = self.run_job(f"Statement ID: STMT-1\n{RECON_DONE_MARKER} 8 matched, 5 exceptions\n{NO_VOUCHER}")
        self.assertEqual(note, "Extracted 13 rows and reconciled: 8 matched, 5 exceptions.")

    def test_reconciliation_failed(self):
        note = self.run_job(f"Statement ID: STMT-1\n{RECON_FAILED_MARKER} ProgrammingError: String or binary "
                            f"data would be truncated\n{NO_VOUCHER}")
        self.assertEqual(note, "Extracted 13 rows, but reconciliation failed: "
                               "ProgrammingError: String or binary data would be truncated")

    def test_matching_never_ran(self):
        note = self.run_job(f"Statement ID: STMT-1\n    Fabric Silver build: skipped/failed\n{NO_VOUCHER}")
        self.assertTrue(note.startswith("Extracted 13 rows -- not reconciled"), note)

    def test_the_old_message_is_gone(self):
        note = self.run_job(f"Statement ID: STMT-1\n{RECON_DONE_MARKER} 1 matched, 0 exceptions\n{NO_VOUCHER}")
        self.assertNotIn("no ERP reference data", note)


if __name__ == "__main__":
    unittest.main()
