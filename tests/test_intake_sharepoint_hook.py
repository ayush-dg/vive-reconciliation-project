"""
tests/test_intake_sharepoint_hook.py

The intake side of the SharePoint archive (notebooks/01_document_intake.py):
  - write_intake_log() keeps the SharePoint columns on a same-statement,
    same-file re-intake and drops them for a different file.
Runs against a temporary SQLite database with every migration applied;
the SharePoint client is never real. Synthetic data only.
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.lakehouse.migrations import apply_pending_migrations

_INTAKE = None


def load_intake():
    """Load the notebook lazily and restore os.environ exactly afterwards --
    its load_dotenv() must not leave real settings in this test process."""
    global _INTAKE
    if _INTAKE is None:
        import importlib.util
        saved = dict(os.environ)
        try:
            spec = importlib.util.spec_from_file_location(
                "intake_sharepoint_hook_test",
                os.path.join(os.path.dirname(__file__), "..", "notebooks", "01_document_intake.py"),
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            os.environ.clear()
            os.environ.update(saved)
        _INTAKE = module
    return _INTAKE


HASH_A = "a" * 64
HASH_B = "b" * 64
SP_VALUES = {
    "sharepoint_status": "uploaded",
    "sharepoint_web_url": "https://vivecollision.sharepoint.com/sites/x/a.pdf",
    "sharepoint_item_id": "item-1",
    "sharepoint_drive_id": "drive-1",
    "sharepoint_path": "General/Vendor Statements/_dev_test/v/2026/09/a__aaaaaaaaaaaa.pdf",
    "sharepoint_error": None,
    "sharepoint_uploaded_at": "2026-10-17T10:00:00+00:00",
}


def schema_result(vendor="Synthetic Vendor"):
    return {
        "document_metadata": {"document_type": "VENDOR_STATEMENT"},
        "vendor_metadata": {"vendor_name": vendor},
        "statement_metadata": {"statement_date": "09/30/2026"},
    }


class _TempDb(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        apply_pending_migrations(conn)
        conn.close()
        self.addCleanup(os.remove, self.db)
        for patcher in (mock.patch("src.lakehouse.connection.DB_PATH", self.db),
                        mock.patch.dict(os.environ, {"AZURE_SQL_SERVER": ""})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.intake = load_intake()

    def row(self, statement_id):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM document_intake_log WHERE statement_id = ?", [statement_id]).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    def write(self, statement_id, document_hash, pdf="synthetic.pdf"):
        self.intake.write_intake_log("doc-" + document_hash[:4] + statement_id, pdf, document_hash,
                                     schema_result(), statement_id, "2026-09", 3, "RECONCILIATION")

    def stamp(self, statement_id, values=SP_VALUES):
        conn = sqlite3.connect(self.db)
        try:
            conn.execute(f"UPDATE document_intake_log SET {', '.join(c + ' = ?' for c in values)} "
                         "WHERE statement_id = ?", list(values.values()) + [statement_id])
            conn.commit()
        finally:
            conn.close()


class TestReIntakeKeepsSharePointColumns(_TempDb):
    def test_same_statement_same_file_keeps_every_value(self):
        self.write("STMT-1", HASH_A)
        self.stamp("STMT-1")
        self.write("STMT-1", HASH_A)              # re-intake: DELETE + INSERT
        rows = self.row("STMT-1")
        self.assertEqual(len(rows), 1)
        for col, value in SP_VALUES.items():
            self.assertEqual(rows[0][col], value, col)

    def test_same_statement_different_file_drops_them(self):
        self.write("STMT-1", HASH_A)
        self.stamp("STMT-1")
        self.write("STMT-1", HASH_B)
        rows = self.row("STMT-1")
        self.assertEqual(len(rows), 1)
        for col in self.intake.SHAREPOINT_COLUMNS:
            self.assertIsNone(rows[0][col], col)

    def test_a_failed_result_is_carried_too(self):
        self.write("STMT-1", HASH_A)
        failed = {"sharepoint_status": "failed", "sharepoint_error": "base folder missing",
                  "sharepoint_uploaded_at": "2026-10-17T10:00:00+00:00"}
        self.stamp("STMT-1", failed)
        self.write("STMT-1", HASH_A)
        row = self.row("STMT-1")[0]
        self.assertEqual((row["sharepoint_status"], row["sharepoint_error"]), ("failed", "base folder missing"))
        self.assertIsNone(row["sharepoint_web_url"])

    def test_first_intake_has_nothing_to_carry(self):
        self.write("STMT-NEW", HASH_A)
        row = self.row("STMT-NEW")[0]
        self.assertIsNone(row["sharepoint_status"])

    def test_other_statements_are_not_touched(self):
        self.write("STMT-1", HASH_A)
        self.stamp("STMT-1")
        self.write("STMT-2", HASH_A)              # same file, different statement
        self.assertIsNone(self.row("STMT-2")[0]["sharepoint_status"])
        self.assertEqual(self.row("STMT-1")[0]["sharepoint_status"], "uploaded")

    def test_lookup_failure_carries_nothing_and_never_raises(self):
        with mock.patch.object(self.intake, "execute_query", side_effect=RuntimeError("no such column")), \
             mock.patch("builtins.print"):
            self.assertEqual(self.intake.carried_sharepoint_values("STMT-1", HASH_A), {})

    def test_intake_log_values_is_unchanged(self):
        # src/rerun/in_place.py UPDATEs intake_log_values() keys only, so the
        # SharePoint columns must never be among them.
        values = self.intake.intake_log_values("d", "x.pdf", HASH_A, schema_result(), "STMT-1", "2026-09", 1,
                                               "RECONCILIATION")
        self.assertFalse(set(values) & set(self.intake.SHAREPOINT_COLUMNS))


SECRET = "client-secret-never-shown"
ENV_ON = {
    "SHAREPOINT_ARCHIVE_ENABLED": "true",
    "SHAREPOINT_TENANT_ID": "tenant", "SHAREPOINT_CLIENT_ID": "client", "SHAREPOINT_CLIENT_SECRET": SECRET,
    "SHAREPOINT_SITE_HOSTNAME": "vivecollision.sharepoint.com", "SHAREPOINT_SITE_PATH": "/sites/aivendorstatements",
    "SHAREPOINT_LIBRARY": "Documents", "SHAREPOINT_BASE_FOLDER": "General/Vendor Statements/_dev_test",
}


class TestArchiveHook(_TempDb):
    def setUp(self):
        super().setUp()
        fd, self.pdf = tempfile.mkstemp(suffix=".pdf", prefix="Fred Beans ")
        with os.fdopen(fd, "wb") as f:
            f.write(b"%PDF-1.4 synthetic")
        self.addCleanup(os.remove, self.pdf)
        self.write("STMT-1", HASH_A, pdf=self.pdf)
        self.client_cls = mock.MagicMock()
        self.client_cls.return_value.upload_statement_pdf.return_value = self.result("uploaded")
        patcher = mock.patch.object(self.intake, "SharePointArchiveClient", self.client_cls)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def result(status, **kw):
        from src.storage.sharepoint_client import SharePointUploadResult
        if status in ("uploaded", "existing"):
            kw.setdefault("web_url", SP_VALUES["sharepoint_web_url"])
            kw.setdefault("item_id", "item-1")
            kw.setdefault("drive_id", "drive-1")
            kw.setdefault("path", SP_VALUES["sharepoint_path"])
        return SharePointUploadResult(status, **kw)

    def hook(self, env=ENV_ON, routing="RECONCILIATION", research=False, month="2026-09", period="2026-10"):
        with mock.patch.dict(os.environ, env), mock.patch("builtins.print") as printed:
            returned = self.intake.archive_statement_to_sharepoint(
                "STMT-1", self.pdf, "Fred Beans", month, period, HASH_A, routing, research)
        self.assertIsNone(returned)
        self.output = "\n".join(str(c.args[0]) for c in printed.call_args_list if c.args)
        self.assertNotIn(SECRET, self.output)
        return self.row("STMT-1")[0]

    def test_flag_off_does_nothing_at_all(self):
        row = self.hook(env={"SHAREPOINT_ARCHIVE_ENABLED": ""})
        self.client_cls.assert_not_called()
        self.assertIsNone(row["sharepoint_status"])
        self.assertEqual(self.output, "")

    def test_parked_is_never_archived(self):
        row = self.hook(routing="PARKED")
        self.client_cls.assert_not_called()
        self.assertIsNone(row["sharepoint_status"])
        self.assertIn("not archived (routing PARKED)", self.output)

    def test_research_mode_is_never_archived(self):
        row = self.hook(research=True)
        self.client_cls.assert_not_called()
        self.assertIsNone(row["sharepoint_status"])
        self.assertIn("research mode", self.output)

    def test_missing_settings_are_recorded_as_skipped(self):
        row = self.hook(env=dict(ENV_ON, SHAREPOINT_CLIENT_SECRET=""))
        self.client_cls.assert_not_called()
        self.assertEqual(row["sharepoint_status"], "skipped")
        self.assertEqual(row["sharepoint_error"], "missing setting(s): SHAREPOINT_CLIENT_SECRET")
        self.assertIsNone(row["sharepoint_web_url"])

    def test_upload_is_recorded(self):
        row = self.hook()
        kwargs = self.client_cls.return_value.upload_statement_pdf.call_args.kwargs
        self.assertEqual((kwargs["year"], kwargs["month"]), ("2026", "09"))
        self.assertEqual(kwargs["document_hash"], HASH_A)
        self.assertEqual(kwargs["original_filename"], os.path.basename(self.pdf))
        self.assertEqual(kwargs["vendor_name"], "Fred Beans")
        self.assertEqual(row["sharepoint_status"], "uploaded")
        self.assertEqual(row["sharepoint_web_url"], SP_VALUES["sharepoint_web_url"])
        self.assertEqual((row["sharepoint_item_id"], row["sharepoint_drive_id"]), ("item-1", "drive-1"))
        self.assertEqual(row["sharepoint_path"], SP_VALUES["sharepoint_path"])
        self.assertIsNone(row["sharepoint_error"])
        self.assertTrue(row["sharepoint_uploaded_at"])
        self.assertIn("month from statement date", self.output)
        settings = self.client_cls.call_args.args[0]
        self.assertEqual(settings["base_folder"], "General/Vendor Statements/_dev_test")

    def test_month_falls_back_to_statement_period(self):
        self.hook(month=None, period="2026-10")
        kwargs = self.client_cls.return_value.upload_statement_pdf.call_args.kwargs
        self.assertEqual((kwargs["year"], kwargs["month"]), ("2026", "10"))
        self.assertIn("statement period (no statement date)", self.output)

    def test_existing_file_is_recorded_as_existing(self):
        self.client_cls.return_value.upload_statement_pdf.return_value = self.result("existing")
        row = self.hook()
        self.assertEqual(row["sharepoint_status"], "existing")
        self.assertEqual(row["sharepoint_web_url"], SP_VALUES["sharepoint_web_url"])

    def test_failure_is_recorded_and_intake_carries_on(self):
        self.client_cls.return_value.upload_statement_pdf.return_value = self.result(
            "failed", error="base folder missing (it is never created automatically)")
        row = self.hook()
        self.assertEqual(row["sharepoint_status"], "failed")
        self.assertIn("base folder missing", row["sharepoint_error"])
        self.assertIsNone(row["sharepoint_web_url"])
        self.assertIn("no link will be written", self.output)

    def test_unexpected_error_never_raises(self):
        self.client_cls.side_effect = RuntimeError(f"boom {SECRET}")
        row = self.hook()
        self.assertIsNone(row["sharepoint_status"])
        self.assertIn("failed unexpectedly (RuntimeError)", self.output)

    def test_database_error_while_recording_never_raises(self):
        with mock.patch.object(self.intake, "execute_sql", side_effect=RuntimeError("db down")):
            self.hook()
        self.assertIn("could not be recorded (RuntimeError)", self.output)

    def test_already_archived_statement_is_not_uploaded_again(self):
        self.stamp("STMT-1")
        self.hook()
        self.client_cls.return_value.upload_statement_pdf.assert_not_called()
        self.assertIn("already archived", self.output)

    def test_a_previous_failure_is_retried(self):
        self.stamp("STMT-1", {"sharepoint_status": "failed", "sharepoint_error": "timeout"})
        row = self.hook()
        self.assertEqual(row["sharepoint_status"], "uploaded")
        self.assertIsNone(row["sharepoint_error"])


class TestBothStep8SitesCallTheHook(unittest.TestCase):
    """run_intake() with every database, cloud and extraction step mocked --
    only checks that each Step 8 site calls the hook with the right values."""

    def setUp(self):
        self.intake = load_intake()
        fd, self.pdf = tempfile.mkstemp(suffix=".pdf", prefix="Synthetic ")
        with os.fdopen(fd, "wb") as f:
            f.write(b"%PDF-1.4 synthetic")
        self.addCleanup(os.remove, self.pdf)
        self.hook = mock.MagicMock()
        self.patch(self.intake, "archive_statement_to_sharepoint", self.hook)
        self.patch(self.intake, "compute_file_hash", mock.MagicMock(return_value=HASH_A))
        self.patch(self.intake, "write_intake_log", mock.MagicMock())
        self.patch(self.intake, "upload_pdf_to_blob_storage", mock.MagicMock(return_value=None))
        self.patch(self.intake, "execute_sql", mock.MagicMock(side_effect=AssertionError("no direct writes")))
        self.patch(self.intake, "resolve_version_info", mock.MagicMock(
            return_value={"version_number": 1, "previous_statement_id": None, "is_latest_version": 1}))
        self.patch(self.intake, "normalize_to_silver", mock.MagicMock(return_value=0))
        self.patch(self.intake, "_research_mode_extraction_only", mock.MagicMock(return_value=False))
        printed = mock.patch("builtins.print")
        printed.start()
        self.addCleanup(printed.stop)

    def patch(self, target, name, value):
        patcher = mock.patch.object(target, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def hook_args(self):
        self.hook.assert_called_once()
        names = ("statement_id", "pdf_path", "vendor_name", "statement_month", "statement_period",
                 "document_hash", "routing", "research_only")
        return dict(zip(names, self.hook.call_args.args))

    def test_cache_hit_site(self):
        def query(sql, params=None):
            if "COUNT(*)" in sql:
                return [{"cnt": 3}]
            if "SELECT vendor_id, statement_period" in sql:
                return [{"vendor_id": "V1", "statement_period": "2026-08"}]
            if "FROM document_intake_log" in sql:
                return [{"vendor_name": "Old Vendor", "document_type": "VENDOR_STATEMENT",
                         "statement_month": "2026-08", "statement_date": "08/31/2026"}]
            raise AssertionError(sql)
        self.patch(self.intake, "execute_query", mock.MagicMock(side_effect=query))
        self.patch(self.intake, "check_cache", mock.MagicMock(
            return_value={"statement_id": "STMT-OLD", "extraction_method": "python_library"}))
        self.patch(self.intake, "copy_extraction_incomplete_exceptions", mock.MagicMock(return_value=0))
        result = self.intake.run_intake(pdf_path=self.pdf, statement_id="STMT-NEW", allow_duplicate=True)
        self.assertTrue(result["cache_hit"])
        args = self.hook_args()
        self.assertEqual(args["statement_id"], "STMT-NEW")
        self.assertEqual(args["vendor_name"], "Old Vendor")
        self.assertEqual(args["statement_month"], "2026-08")
        self.assertEqual((args["routing"], args["research_only"]), ("RECONCILIATION", False))
        self.assertEqual(args["document_hash"], HASH_A)

    def run_normal_path(self, document_type="VENDOR_STATEMENT"):
        engine = mock.MagicMock()
        engine.return_value.understand.return_value = {
            "document_metadata": {"document_type": document_type},
            "vendor_metadata": {"vendor_name": "Synthetic Vendor"},
            "statement_metadata": {"statement_date": "09/30/2026"},
            "invoices": [],
            "_provider_used": "python_library",
        }
        self.patch(self.intake, "check_cache", mock.MagicMock(return_value=None))
        self.patch(self.intake, "extract_pdf_text", mock.MagicMock(return_value=("text", 1)))
        self.patch(self.intake, "_determine_extraction_route", mock.MagicMock(return_value={
            "engine": "python_library", "pdf_type": "text", "reason": "test", "new_vendor_warning": None}))
        self.patch(self.intake, "PythonLibraryExtractionEngine", engine)
        self.patch(self.intake, "DocumentUnderstandingEngine", engine)
        self.patch(self.intake, "apply_arithmetic_validation", mock.MagicMock())
        self.patch(self.intake, "resolve_billing_location", mock.MagicMock(return_value=(None, None)))
        self.patch(self.intake, "resolve_vendor_id", mock.MagicMock(return_value="V1"))
        self.patch(self.intake, "write_raw_statement", mock.MagicMock(return_value=False))
        self.patch(self.intake, "write_to_bronze", mock.MagicMock(return_value=0))
        self.patch(self.intake, "update_cache", mock.MagicMock())
        import contextlib
        import src.lakehouse.bronze_raw as bronze_raw
        import src.lakehouse.bronze_unnest as bronze_unnest
        import src.lakehouse.fabric_dbt_runner as dbt_runner
        self.patch(bronze_raw, "promote_staged_raw_statement", mock.MagicMock(return_value=False))
        self.patch(bronze_raw, "_refresh_sql_endpoint_metadata", mock.MagicMock())
        self.patch(bronze_unnest, "write_unnested_from_invoices", mock.MagicMock(return_value=(0, 0)))
        self.patch(dbt_runner, "fabric_pipeline_lock", contextlib.nullcontext)
        return self.intake.run_intake(pdf_path=self.pdf, statement_id="STMT-FRESH", statement_period="2026-10")

    def test_normal_site(self):
        result = self.run_normal_path()
        self.assertFalse(result["cache_hit"])
        args = self.hook_args()
        self.assertEqual(args["statement_id"], "STMT-FRESH")
        self.assertEqual(args["vendor_name"], "Synthetic Vendor")
        self.assertEqual(args["statement_month"], "2026-09")
        self.assertEqual(args["statement_period"], "2026-10")
        self.assertEqual((args["routing"], args["research_only"]), ("RECONCILIATION", False))
        # Step 7 (intake log) runs before the hook.
        self.intake.write_intake_log.assert_called_once()

    def test_normal_site_passes_parked_through(self):
        self.run_normal_path(document_type="NOT_A_STATEMENT")
        self.assertEqual(self.hook_args()["routing"], "PARKED")


if __name__ == "__main__":
    unittest.main()
