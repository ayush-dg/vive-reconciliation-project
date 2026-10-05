"""
tests/test_oct1_intake_worker_web.py

Wiring for the 2026-10-06 validation work, outside the gate itself:
  - notebooks/01_document_intake.py apply_arithmetic_validation() and the
    duplicate-PDF check in run_intake() (no database or cloud writes: the
    duplicate check returns before anything is written, and every
    write function is replaced by a mock that fails the test if called),
  - web/worker.py job messages for NOT_A_STATEMENT and duplicates,
  - the Validation page's method badge and checks table,
  - migrations/019 and the Azure SQL column list,
  - the OCR binary lookup (no more hard-coded Windows path).
Synthetic data only.
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from src.ai.claude_sonnet_client import NOT_A_STATEMENT
from src.lakehouse.migrations import apply_pending_migrations
from src.pipeline_markers import DUPLICATE_MARKER, NOT_A_STATEMENT_MARKER


_INTAKE = None


def load_intake():
    """The intake notebook calls load_dotenv() on import, which would put
    the real .env (cloud endpoints and credentials) into this test
    process's environment for every test that runs afterwards. Load it
    lazily and restore os.environ exactly, so nothing here can reach a
    real service or change how other test modules behave."""
    global _INTAKE
    if _INTAKE is None:
        import importlib.util
        saved = dict(os.environ)
        try:
            spec = importlib.util.spec_from_file_location(
                "intake_oct1_fixes_test",
                os.path.join(os.path.dirname(__file__), "..", "notebooks", "01_document_intake.py"),
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            os.environ.clear()
            os.environ.update(saved)
        _INTAKE = module
    return _INTAKE


class _IntakeModule:
    def __getattr__(self, name):
        return getattr(load_intake(), name)


INTAKE = _IntakeModule()
TEXT_LAYER = "\n".join(f"09/{d:02d}/26 INV{d:05d} PO{d} 10.00" for d in range(1, 25))


def schema(invoices, printed, *, vendor="Synthetic Vendor", doc_type="VENDOR_STATEMENT", **stmt):
    from src.validation.arithmetic_gate import compute_statement_total_from_invoices
    return {
        "document_metadata": {"document_type": doc_type},
        "vendor_metadata": {"vendor_name": vendor},
        "statement_metadata": {"statement_total_as_printed": printed,
                               "statement_total_computed": compute_statement_total_from_invoices(invoices) if invoices else None,
                               **stmt},
        "invoices": invoices,
    }


def inv(number, out=None, credit=None, due=None, raw=None):
    return {"invoice_number": number, "outstanding_amount": out, "credit": credit, "amount_due": due, "_raw_row": raw or {}}


class TestApplyArithmeticValidation(unittest.TestCase):

    def test_not_a_statement(self):
        result = INTAKE.apply_arithmetic_validation(schema([], None, doc_type=NOT_A_STATEMENT), "From: someone")
        self.assertEqual(result["status"], "not_a_statement")

    def test_open_item_statement_passes_by_open_balance(self):
        rows = [inv("1", 911.0, due=911.0), inv(None, -1030.0, due=0.0), inv("2", 715.0, due=715.0)]
        result = INTAKE.apply_arithmetic_validation(schema(rows, 1626.0), TEXT_LAYER)
        self.assertEqual((result["status"], result["method"]), ("matches", "open_balance"))

    def test_previous_balance_corroborated_by_text_layer(self):
        rows = [inv("1", 175.5), inv(None, -707.0), inv("2", 175.5)]
        s = schema(rows, 351.0, previous_balance=707.0, previous_balance_label="Balance Forward")
        result = INTAKE.apply_arithmetic_validation(s, TEXT_LAYER + "\n08/31/2026 Balance Forward 707.00")
        self.assertEqual(result["method"], "statement_equation")
        self.assertEqual(s["statement_metadata"]["previous_balance_source"], "model+text_layer")

    def test_adversarial_previous_balance_not_in_text_layer_fails(self):
        rows = [inv("1", 175.5), inv(None, -707.0), inv("2", 175.5)]
        s = schema(rows, 351.0, previous_balance=707.0, previous_balance_label="Balance Forward")
        result = INTAKE.apply_arithmetic_validation(s, TEXT_LAYER)  # no balance-forward line printed
        self.assertEqual(result["status"], "mismatch")
        self.assertIsNone(s["statement_metadata"]["previous_balance"])
        self.assertTrue(s["statement_metadata"]["previous_balance_source"].startswith("rejected"))

    def test_fenix_override_without_its_column_keeps_the_generic_total(self):
        # Claude-extracted Fenix rows carry "Charged", not the configured "due".
        rows = [inv("3358852", 315.0, raw={"Charged": 315.0}), inv("3397555", 115.0, raw={"Charged": 115.0})]
        result = INTAKE.apply_arithmetic_validation(schema(rows, 430.0, vendor="Fenix Parts"), TEXT_LAYER)
        self.assertEqual((result["status"], result["method"]), ("matches", "primary"))


class TestDuplicateCheck(unittest.TestCase):

    def setUp(self):
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.write(b"%PDF-1.4 synthetic")
        f.close()
        self.pdf = f.name
        self.addCleanup(os.remove, self.pdf)
        no_writes = mock.MagicMock(side_effect=AssertionError("nothing may be written"))
        for name in ("execute_sql", "write_to_bronze", "write_intake_log", "upload_pdf_to_blob_storage"):
            patcher = mock.patch.object(load_intake(), name, no_writes)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_identical_pdf_is_reported_as_duplicate_and_writes_nothing(self):
        with mock.patch.object(load_intake(), "check_cache", return_value={"statement_id": "STMT-OLD"}), \
             mock.patch.object(load_intake(), "execute_query", return_value=[{"cnt": 7}]), \
             mock.patch("builtins.print") as printed:
            result = INTAKE.run_intake(pdf_path=self.pdf)
        self.assertEqual(result["duplicate_of"], "STMT-OLD")
        self.assertEqual(result["statement_id"], "STMT-OLD")
        self.assertEqual(result["bronze_count"], 7)
        output = "\n".join(str(c.args[0]) for c in printed.call_args_list if c.args)
        self.assertIn("Statement ID: STMT-OLD", output)
        self.assertIn(f"{DUPLICATE_MARKER} STMT-OLD", output)

    def test_allow_duplicate_skips_the_early_return(self):
        with mock.patch.object(load_intake(), "check_cache", return_value=None), \
             mock.patch.object(load_intake(), "extract_pdf_text", side_effect=RuntimeError("reached extraction")):
            with self.assertRaisesRegex(RuntimeError, "reached extraction"):
                INTAKE.run_intake(pdf_path=self.pdf, allow_duplicate=True)


class TestWorkerMessages(unittest.TestCase):

    def _run(self, stdout, silver_count):
        from web import worker
        job = {"job_id": "J1", "pdf_path": __file__, "pdf_filename": "x.pdf", "source_blob_path": None}
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")
        with mock.patch("web.worker.subprocess.run", return_value=completed), \
             mock.patch("web.queries.get_silver_row_count", return_value=silver_count), \
             mock.patch("web.queries.get_vendor_name_for_statement", return_value="Vendor"), \
             mock.patch("web.queries.update_job_status") as update:
            worker._run_job(job)
        return update.call_args.kwargs

    def test_not_a_statement_message_is_the_last_line(self):
        out = f"Statement ID: STMT-1\n  {NOT_A_STATEMENT_MARKER} no line-item table found\nPIPELINE STOPPED"
        kwargs = self._run(out, 0)
        self.assertEqual(kwargs["status"], "FAILED")
        self.assertTrue(kwargs["error_message"].strip().splitlines()[-1].startswith(NOT_A_STATEMENT_MARKER))

    def test_zero_rows_message_unchanged_otherwise(self):
        kwargs = self._run("Statement ID: STMT-1\nPIPELINE STOPPED", 0)
        self.assertTrue(kwargs["error_message"].startswith("Extraction completed but produced 0 rows"))

    def test_duplicate_completes_against_the_existing_statement(self):
        out = f"Statement ID: STMT-OLD\n  {DUPLICATE_MARKER} STMT-OLD -- already extracted"
        kwargs = self._run(out, 12)
        self.assertEqual((kwargs["status"], kwargs["statement_id"]), ("COMPLETED", "STMT-OLD"))
        self.assertIn("Duplicate of STMT-OLD", kwargs["error_message"])

    def test_normal_completion_has_no_message(self):
        kwargs = self._run("Statement ID: STMT-2\n", 12)
        self.assertEqual(kwargs["status"], "COMPLETED")
        self.assertNotIn("error_message", kwargs)


def _client():
    from web.deps import require_login
    from web.routers import validation
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    app.include_router(validation.router)
    app.dependency_overrides[require_login] = lambda: "tester"
    return TestClient(app)


def _patch(testcase, **fns):
    for name, fn in fns.items():
        patcher = mock.patch(f"web.queries.{name}", fn)
        patcher.start()
        testcase.addCleanup(patcher.stop)


SIDEBAR = {"get_open_recon_exceptions_count": lambda: 0, "get_pending_review_count": lambda: 0,
           "get_outlook_synced_jobs": lambda: []}


class TestValidationPage(unittest.TestCase):

    def test_list_shows_method_badge_for_passed_runs(self):
        runs = [
            {"statement_id": "A", "source_file": "a.pdf", "vendor_name": "Bishop's", "statement_period": "2026-09",
             "statement_total_as_printed": 2796.0, "validation_status": "matches", "validation_difference": 0.0,
             "validation_method": "open_balance", "ingestion_timestamp": "2026-10-01T21:00:00+00:00", "shop": None,
             "passed": True},
            {"statement_id": "B", "source_file": "b.pdf", "vendor_name": "Clinton", "statement_period": "2026-08",
             "statement_total_as_printed": 2885.74, "validation_status": "mismatch", "validation_difference": -100.0,
             "validation_method": None, "ingestion_timestamp": "2026-10-01T21:00:00+00:00", "shop": None,
             "passed": False},
        ]
        _patch(self, get_validation_report=lambda: [dict(r) for r in runs], **SIDEBAR)
        html = _client().get("/validation").text
        self.assertIn("Open balances", html)
        self.assertEqual(html.count('class="badge info"'), 1)

    def test_detail_shows_method_and_checks_tried(self):
        intake = {
            "statement_id": "C", "source_file": "c.pdf", "vendor_name": "Goldstein", "statement_period": "2026-08",
            "statement_total_as_printed": 2602.42, "validation_status": "mismatch", "validation_difference": 505.34,
            "validation_method": None, "previous_balance": None, "previous_balance_source": None,
            "ingestion_timestamp": "2026-10-01T21:00:00+00:00", "passed": False, "primary_computed": None,
            "validation_attempts": [
                {"method": "open_balance", "applicable": False, "passed": False, "computed": None,
                 "reason": "the amount_due column is a running balance, not a per-row open balance"},
                {"method": "running_balance", "applicable": True, "passed": False, "computed": None,
                 "reason": "running balance chain breaks",
                 "first_broken_row": {"invoice_number": "47877", "row_number": 2, "expected_balance": -902.55,
                                      "printed_balance": -397.21}},
            ],
        }
        _patch(self, get_extraction_validation_detail=lambda sid: {"intake": intake, "computed_total": 2097.08,
                                                                     "lines": []}, **SIDEBAR)
        html = _client().get("/validation/C").text
        self.assertIn("Validation checks tried", html)
        self.assertIn("Running balance", html)
        self.assertIn("First broken row: 47877", html)
        self.assertIn("Not applicable", html)


class TestValidationDetailQuery(unittest.TestCase):

    def test_detail_parses_validation_detail_json(self):
        from web import queries
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        apply_pending_migrations(conn)
        detail = {"primary_computed": 1096.0, "attempts": [{"method": "open_balance", "passed": True}]}
        conn.execute(
            "INSERT INTO document_intake_log (document_id, statement_id, source_file, statement_total_as_printed, "
            "validation_status, validation_difference, validation_method, validation_detail, ingestion_timestamp) "
            "VALUES ('d', 'S1', 's.pdf', 2126.0, 'matches', 0.0, 'open_balance', ?, '2026-10-01T00:00:00')",
            [json.dumps(detail)],
        )

        def execute_query(sql, params=None):
            return [dict(r) for r in conn.execute(sql, params or []).fetchall()]

        with mock.patch.object(queries, "execute_query", execute_query), \
             mock.patch.object(queries, "recon_query", lambda sql, params=None: []):
            data = queries.get_extraction_validation_detail("S1")
        self.assertEqual(data["intake"]["validation_method"], "open_balance")
        self.assertEqual(data["intake"]["primary_computed"], 1096.0)
        self.assertEqual(data["intake"]["validation_attempts"][0]["method"], "open_balance")


class TestMigration019(unittest.TestCase):

    def test_sqlite_migration_adds_the_columns(self):
        conn = sqlite3.connect(":memory:")
        apply_pending_migrations(conn)
        intake_cols = {r[1] for r in conn.execute("PRAGMA table_info(document_intake_log)")}
        bronze_cols = {r[1] for r in conn.execute("PRAGMA table_info(bronze_vendor_statement_raw)")}
        self.assertTrue({"validation_method", "validation_detail", "previous_balance",
                         "previous_balance_source", "section_totals"} <= intake_cols)
        self.assertTrue({"raw_unallocated", "raw_section"} <= bronze_cols)

    def test_azure_sql_column_list_matches(self):
        from src.lakehouse import azure_sql_migrations as az
        intake = {name for name, _ in az.COLUMNS["document_intake_log"]}
        bronze = {name for name, _ in az.COLUMNS["bronze_vendor_statement_raw"]}
        self.assertTrue({"validation_method", "validation_detail", "previous_balance",
                         "previous_balance_source", "section_totals"} <= intake)
        self.assertTrue({"raw_unallocated", "raw_section"} <= bronze)


class TestTesseractLookup(unittest.TestCase):

    def test_uses_the_binary_on_path(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "extraction", "python_library"))
        import ocr_embed
        with mock.patch("ocr_embed.shutil.which", return_value="/usr/bin/tesseract"):
            self.assertEqual(ocr_embed._find_tesseract(), "/usr/bin/tesseract")

    def test_falls_back_to_plain_name_when_nothing_found(self):
        import ocr_embed
        with mock.patch("ocr_embed.shutil.which", return_value=None), \
             mock.patch("ocr_embed.os.path.exists", return_value=False):
            self.assertEqual(ocr_embed._find_tesseract(), "tesseract")


if __name__ == "__main__":
    unittest.main()
