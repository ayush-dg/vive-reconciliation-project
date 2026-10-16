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


if __name__ == "__main__":
    unittest.main()
