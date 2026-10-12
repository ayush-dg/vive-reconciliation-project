"""
tests/test_revalidate.py

src/rerun/revalidate.py + scripts/revalidate_intake.py -- recompute only the
seven document_intake_log validation columns from stored rows + a local PDF
(2026-10-12). Azure SQL is SQLite built from migrations/*.sql; the Lakehouse
raw rows are the in-memory fake from tests/test_rerun_in_place.py.
SYNTHETIC data only (a generated no-total statement PDF).
"""

import hashlib
import json
import os
import shutil
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.lakehouse import connection  # noqa: E402
from src.rerun import revalidate  # noqa: E402
from test_oct1_intake_worker_web import load_intake  # noqa: E402
from test_pdf_row_match import HEALEY_LINES, statement_page, write_pdf  # noqa: E402
from test_rerun_in_place import FakeIO, World  # noqa: E402

SID, OTHER, EMAIL = "STMT-NOTOT001", "STMT-OTHER002", "STMT-EMAIL003"
RAW_ROWS = [  # what the model returned for HEALEY_LINES (Claude row shape)
    {"DATE": "8/19/2026", "INVOICE": "CM6237539", "DESCRIPTION": None, "CHARGES": -4.67, "CREDITS": None, "BALANCE": -4.67, "confidence": 0.95},
    {"DATE": "8/19/2026", "INVOICE": "6237682", "DESCRIPTION": None, "CHARGES": 5.47, "CREDITS": None, "BALANCE": 5.47, "confidence": 0.95},
    {"DATE": "9/1/2026", "INVOICE": "1401474", "DESCRIPTION": None, "CHARGES": None, "CREDITS": None, "BALANCE": -100.54, "confidence": 0.93},
    {"DATE": "9/1/2026", "INVOICE": "6238592", "DESCRIPTION": None, "CHARGES": 403.91, "CREDITS": None, "BALANCE": 403.91, "confidence": 0.95},
]
NO_TABLE_LOG = ("[Engine] Attempting ClaudeSonnetClient (primary path)...\n  [ClaudeSonnetClient] Columns found: []\n"
                "  [Engine] ClaudeSonnetClient success — 0 invoices extracted\n")


class RevalidateCase(unittest.TestCase):

    def setUp(self):
        self.world = World()
        self.addCleanup(shutil.rmtree, self.world.dir, ignore_errors=True)
        self.io = FakeIO(self.world)
        self.intake = load_intake()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AZURE_SQL", "FABRIC_"))}
        for patcher in (mock.patch.dict(os.environ, env, clear=True), mock.patch.object(connection, "DB_PATH", self.world.db)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.pdf = write_pdf([statement_page(HEALEY_LINES)])
        self.addCleanup(os.remove, self.pdf)
        self.hash = hashlib.sha256(open(self.pdf, "rb").read()).hexdigest()
        for sid, rows, status in ((SID, RAW_ROWS, "total_not_found"), (OTHER, RAW_ROWS, "matches"), (EMAIL, [], "total_not_found")):
            self.world.insert("document_intake_log", document_id=f"d-{sid}", document_hash=self.hash, source_file=f"{sid}.pdf",
                              ingestion_timestamp="2026-10-01T22:00:00+00:00", document_type="VENDOR_STATEMENT",
                              vendor_name="Synthetic Dodge", statement_period="2026-09", statement_id=sid,
                              invoice_count=len(rows), validation_status=status, validation_difference=None,
                              validation_method="primary" if status == "matches" else None,
                              statement_total_as_printed=None, extraction_method="claude_sonnet",
                              extraction_model="claude-sonnet-4-6")
            self.world.lh["raw_statement"].append({"statement_id": sid, "raw_payload": json.dumps(rows)})
        self.world.insert("jobs", job_id="job-email", pdf_filename="email.pdf", pdf_path="x.pdf",
                          submitted_at="2026-10-01T21:00:00+00:00", statement_id=EMAIL, status="FAILED",
                          error_message=NO_TABLE_LOG)

    def intake_rows(self):
        return {r["statement_id"]: r for r in self.world.sql("SELECT * FROM document_intake_log")}

    def plan(self, sids=(SID,)):
        with mock.patch("builtins.print"):
            return revalidate.plan(self.io, self.intake, list(sids), {s: self.pdf for s in sids})


class TestPlanAndApply(RevalidateCase):

    def test_dry_run_recomputes_and_writes_nothing(self):
        before = self.world.snapshot()
        p = self.plan()
        self.assertEqual(self.world.snapshot(), before)
        row = p["rows"][0]
        self.assertEqual((row["new"]["validation_status"], row["new"]["validation_method"]), ("matches", "pdf_rows_no_total"))
        self.assertIsNone(row["new"]["validation_difference"])
        self.assertEqual(row["old"]["validation_status"], "total_not_found")

    def test_apply_changes_only_the_seven_columns_of_the_target(self):
        p = self.plan()
        before = self.intake_rows()
        paths = revalidate.backup(p, [os.path.join(self.world.dir, "b1"), os.path.join(self.world.dir, "b2")])
        self.assertEqual(len(paths), 2)
        for d in ("b1", "b2"):
            names = os.listdir(os.path.join(self.world.dir, d))
            self.assertEqual(sorted(n.rsplit("_", 1)[-1] for n in names), ["backup.json", "undo.py", "undo.sql"])
        result = revalidate.apply(self.io, p, p["fingerprint"], paths)
        self.assertTrue(result["verified"], result)
        after = self.intake_rows()
        self.assertEqual(after[SID]["validation_status"], "matches")
        self.assertEqual(after[SID]["validation_method"], "pdf_rows_no_total")
        for col in before[SID]:
            if col not in revalidate.COLUMNS:
                self.assertEqual(after[SID][col], before[SID][col], col)
        self.assertEqual(after[OTHER], before[OTHER])
        self.assertEqual(after[EMAIL], before[EMAIL])

    def test_undo_restores_the_old_values(self):
        p = self.plan()
        before = self.intake_rows()
        paths = revalidate.backup(p, [os.path.join(self.world.dir, "b")])
        revalidate.apply(self.io, p, p["fingerprint"], paths)
        doc = json.load(open(paths[0], encoding="utf-8"))
        revalidate.undo(doc, apply_changes=True)
        self.assertEqual(self.intake_rows(), before)

    def test_apply_refuses_when_a_row_changed_since_the_dry_run(self):
        p = self.plan()
        paths = revalidate.backup(p, [os.path.join(self.world.dir, "b")])
        self.world.sql("UPDATE document_intake_log SET validation_status = 'mismatch' WHERE statement_id = ?", [SID])
        before = self.world.snapshot()
        with self.assertRaisesRegex(revalidate.RefusedError, "changed since the dry run"):
            revalidate.apply(self.io, p, p["fingerprint"], paths)
        self.assertEqual(self.world.snapshot(), before)

    def test_apply_refuses_without_a_backup(self):
        p = self.plan()
        before = self.world.snapshot()
        with self.assertRaisesRegex(revalidate.RefusedError, "no backup"):
            revalidate.apply(self.io, p, p["fingerprint"], [])
        self.assertEqual(self.world.snapshot(), before)

    def test_one_transaction_rolls_back_everything(self):
        p = self.plan((SID, EMAIL))
        paths = revalidate.backup(p, [os.path.join(self.world.dir, "b")])
        p["rows"][1]["statement_id"] = "STMT-MISSING9"  # second UPDATE hits 0 rows
        before = self.world.snapshot()
        with mock.patch.object(revalidate, "fingerprint", return_value=p["fingerprint"]), \
                self.assertRaises(revalidate.RefusedError):
            revalidate._transaction([revalidate._update(r["new"], r["statement_id"], r["ingestion_timestamp"], r["old"])
                                     for r in p["rows"]])
        self.assertEqual(self.world.snapshot(), before)

    def test_pdf_hash_mismatch_is_refused(self):
        self.world.sql("UPDATE document_intake_log SET document_hash = ? WHERE statement_id = ?", ["0" * 64, SID])
        with self.assertRaisesRegex(revalidate.RefusedError, "SHA-256"):
            self.plan()


class TestNotAStatement(RevalidateCase):

    def test_zero_rows_with_no_table_evidence_becomes_not_a_statement(self):
        row = self.plan((EMAIL,))["rows"][0]
        self.assertEqual(row["new"]["validation_status"], "not_a_statement")
        self.assertIn("Columns found: []", json.loads(row["new"]["validation_detail"])["not_a_statement_evidence"])

    def test_zero_rows_without_evidence_is_left_unchanged(self):
        self.world.sql("UPDATE jobs SET error_message = 'Worker error: timed out' WHERE statement_id = ?", [EMAIL])
        p = self.plan((EMAIL,))
        self.assertEqual(p["rows"], [])
        self.assertIn("no job output", p["unchanged"][0]["reason"])


class TestCli(RevalidateCase):

    def test_cli_dry_run_writes_the_plan_file_only(self):
        from scripts import revalidate_intake as cli
        out = os.path.join(self.world.dir, "plan.json")
        before = self.world.snapshot()
        with mock.patch("builtins.print"):
            code = cli.main(["--statement-id", SID, "--pdf", f"{SID}={self.pdf}", "--plan-out", out], io=self.io, intake=self.intake)
        self.assertEqual(code, 0)
        self.assertEqual(self.world.snapshot(), before)
        self.assertEqual(json.load(open(out))["rows"][0]["statement_id"], SID)

    def test_cli_apply_refuses_a_wrong_confirm(self):
        from scripts import revalidate_intake as cli
        out = os.path.join(self.world.dir, "plan.json")
        with mock.patch("builtins.print"):
            cli.main(["--statement-id", SID, "--pdf", f"{SID}={self.pdf}", "--plan-out", out], io=self.io, intake=self.intake)
            before = self.world.snapshot()
            code = cli.main(["--plan", out, "--apply", "--confirm", "0" * 16], io=self.io, intake=self.intake)
        self.assertEqual(code, 2)
        self.assertEqual(self.world.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
