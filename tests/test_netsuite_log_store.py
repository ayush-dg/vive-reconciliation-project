"""
tests/test_netsuite_log_store.py

The database copy of the NetSuite write-back log (src/netsuite/log_store.py):
saving a run and its invoice rows, saving a run that failed as a whole, never
raising when the database misbehaves, and the SQLite migration and the Azure
SQL definitions describing the same columns. Uses a throwaway SQLite file;
nothing touches Azure, Fabric or NetSuite.
"""

import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
from decimal import Decimal
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.lakehouse import azure_sql_migrations as azure
from src.lakehouse import connection
from src.lakehouse.migrations import apply_pending_migrations
from src.netsuite import log_store
from src.netsuite import writeback as wb

STMT = "STMT-LOG00001"
STARTED = "2026-10-19T10:00:00+00:00"


class _TempDbCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="nswb_log_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        db = os.path.join(self.dir, "test.db")
        for patcher in (mock.patch.object(connection, "DB_PATH", db),
                        mock.patch.dict(os.environ, {"AZURE_SQL_SERVER": ""})):
            patcher.start()
            self.addCleanup(patcher.stop)
        conn = sqlite3.connect(db)
        apply_pending_migrations(conn)
        conn.close()

    def _written(self, invoice="INV1", amount="100.00", seconds=1.5):
        plan = wb.Plan(invoice_number=invoice, statement_amount=Decimal(amount), action=wb.PATCH_MATCHED,
                       record_type="vendorbill", record_id="501", fields={"custbody_reconciled": True},
                       previous={"custbody_reconciled": "F"})
        return wb.ApplyResult(plan, True, "updated", "501", seconds=seconds)

    def _locked(self, invoice="INV2"):
        plan = wb.Plan(invoice_number=invoice, statement_amount=Decimal("5"), action=wb.PATCH_MATCHED,
                       record_type="vendorbill", record_id="502", fields={})
        return wb.ApplyResult(plan, False, "period closed", category=wb.CAT_PERIOD_LOCKED)

    def _skipped(self, invoice="INV3"):
        return wb._skip(invoice, None, "no such bill in the sandbox", category=wb.CAT_NOT_IN_SANDBOX)


class SaveRunTests(_TempDbCase):
    def _save(self, **extra):
        written, locked, skipped = self._written(), self._locked(), self._skipped()
        run_id = log_store.save_run(STMT, [written, locked], [written.plan, locked.plan, skipped],
                                    started_at=STARTED, sandbox="7321761-sb1", log_path="x.json", **extra)
        return run_id

    def test_a_run_is_saved_with_its_counts(self):
        run_id = self._save()
        (run,) = log_store.get_runs(STMT)
        self.assertEqual(run["run_id"], run_id)
        self.assertEqual((run["outcome"], run["source"], run["sandbox"]), ("completed", "pipeline", "7321761-sb1"))
        self.assertEqual((run["written"], run["failed"], run["period_locked"], run["held_by_other"],
                          run["not_written"]), (1, 0, 1, 0, 1))
        self.assertEqual(json.loads(run["not_written_counts"]), {wb.CAT_NOT_IN_SANDBOX: 1})
        self.assertEqual((run["started_at"], run["log_path"]), (STARTED, "x.json"))

    def test_every_invoice_line_is_saved_with_its_outcome_and_reason(self):
        run_id = self._save()
        rows = {r["invoice_number"]: r for r in log_store.get_records(run_id)}
        self.assertEqual({k: (v["outcome"], v["reason"]) for k, v in rows.items()}, {
            "INV1": ("written", ""),
            "INV2": ("period locked", "period locked"),
            "INV3": ("not written", wb.CAT_NOT_IN_SANDBOX),
        })
        self.assertEqual(rows["INV1"]["seconds"], 1.5)
        self.assertEqual(rows["INV2"]["detail"], "period closed")

    def test_what_was_sent_and_what_it_replaced_are_kept_so_a_write_can_be_undone(self):
        run_id = self._save()
        row = next(r for r in log_store.get_records(run_id) if r["invoice_number"] == "INV1")
        self.assertEqual(json.loads(row["fields_sent"]), {"custbody_reconciled": True})
        self.assertEqual(json.loads(row["previous_values"]), {"custbody_reconciled": "F"})
        self.assertEqual((row["record_type"], row["record_id"]), ("vendorbill", "501"))

    def test_a_blank_statement_amount_is_stored_as_null(self):
        run_id = self._save()
        amounts = {r["invoice_number"]: r["statement_amount"] for r in log_store.get_records(run_id)}
        self.assertEqual(amounts["INV1"], 100.0)
        self.assertIsNone(amounts["INV3"])

    def test_a_manual_run_is_marked_as_such(self):
        self._save(source="cli")
        self.assertEqual(log_store.get_runs(STMT)[0]["source"], "cli")

    def test_runs_of_different_statements_do_not_mix(self):
        self._save()
        log_store.save_run("STMT-OTHER", [self._written("X")], [], started_at=STARTED)
        self.assertEqual(len(log_store.get_runs(STMT)), 1)
        self.assertEqual(len(log_store.get_runs("STMT-OTHER")), 1)

    def test_runs_come_back_newest_first(self):
        first = log_store.save_run(STMT, [], [], started_at="2026-10-19T09:00:00+00:00")
        second = log_store.save_run(STMT, [], [], started_at="2026-10-19T11:00:00+00:00")
        self.assertEqual([r["run_id"] for r in log_store.get_runs(STMT)], [second, first])

    def test_a_run_with_nothing_to_write_is_still_recorded(self):
        run_id = log_store.save_run(STMT, [], [self._skipped()], started_at=STARTED)
        (run,) = log_store.get_runs(STMT)
        self.assertEqual((run["written"], run["not_written"]), (0, 1))
        self.assertEqual(len(log_store.get_records(run_id)), 1)


class UnattemptedRowsTests(_TempDbCase):
    def _stopped(self):
        first = self._written("A")
        failed = wb.ApplyResult(first.plan, False, "Invalid field value", category=wb.CAT_WRITE_FAILED)
        unreached = [self._written("B").plan, self._written("C").plan]
        return failed, [failed.plan] + unreached

    def test_the_writes_a_stopped_run_never_reached_are_saved_as_not_attempted(self):
        failed, plans = self._stopped()
        run_id = log_store.save_run(STMT, [failed], plans, started_at=STARTED)
        rows = {r["invoice_number"]: r for r in log_store.get_records(run_id)}
        self.assertEqual(rows["A"]["outcome"], "failed")
        for invoice in ("B", "C"):
            self.assertEqual((rows[invoice]["outcome"], rows[invoice]["reason"]),
                             ("not attempted", wb.CAT_NOT_ATTEMPTED))
        self.assertEqual(len(rows), 3)                 # nothing vanished

    def test_the_run_counts_include_them(self):
        failed, plans = self._stopped()
        log_store.save_run(STMT, [failed], plans, started_at=STARTED)
        (run,) = log_store.get_runs(STMT)
        self.assertEqual((run["failed"], run["written"], run["not_written"]), (1, 0, 2))
        self.assertEqual(json.loads(run["not_written_counts"]), {wb.CAT_NOT_ATTEMPTED: 2})


class SaveRevertTests(_TempDbCase):
    def _results(self):
        patch = {"op": "PATCH", "record_type": "vendorbill", "record_id": "1", "invoice_number": "A",
                 "body": {"custbody_reconciled": False}}
        delete = {"op": "DELETE", "record_type": "customrecord_statement_line", "record_id": "9", "invoice_number": "B"}
        return [(patch, True, "reverted"), (delete, False, "HTTPError: nope")]

    def test_an_undo_run_is_saved_with_one_row_per_record(self):
        run_id = log_store.save_revert(STMT, self._results(), started_at=STARTED, sandbox="x-sb1", log_path="r.json")
        (run,) = log_store.get_runs(STMT)
        self.assertEqual((run["run_id"], run["outcome"], run["source"]), (run_id, "reverted", "cli"))
        self.assertEqual((run["written"], run["failed"], run["log_path"]), (0, 1, "r.json"))
        self.assertEqual(json.loads(run["not_written_counts"]), {"reverted": 1})
        rows = {r["invoice_number"]: r for r in log_store.get_records(run_id)}
        self.assertEqual((rows["A"]["action"], rows["A"]["outcome"]), ("REVERT_PATCH", "reverted"))
        self.assertEqual((rows["B"]["action"], rows["B"]["outcome"]), ("REVERT_DELETE", "failed"))
        self.assertEqual(json.loads(rows["A"]["fields_sent"]), {"custbody_reconciled": False})

    def test_an_undo_run_becomes_the_statements_newest_run(self):
        log_store.save_run(STMT, [self._written()], [self._written().plan], started_at="2026-10-19T09:00:00+00:00")
        log_store.save_revert(STMT, self._results(), started_at="2026-10-19T10:00:00+00:00")
        self.assertEqual(log_store.get_latest_runs([STMT])[STMT]["outcome"], "reverted")

    def test_a_database_error_returns_none_instead_of_raising(self):
        with mock.patch.object(log_store, "_insert_many", side_effect=RuntimeError("db is down")):
            self.assertIsNone(log_store.save_revert(STMT, self._results(), started_at=STARTED))


class SaveFailedRunTests(_TempDbCase):
    def test_a_run_that_failed_as_a_whole_keeps_the_error_and_traceback(self):
        try:
            raise AttributeError("'NoneType' object has no attribute 'lower'")
        except AttributeError as exc:
            run_id = log_store.save_failed_run(STMT, exc, started_at=STARTED, log_path="err.json")
        (run,) = log_store.get_runs(STMT)
        self.assertEqual(run["run_id"], run_id)
        self.assertEqual((run["outcome"], run["error_type"]), ("failed", "AttributeError"))
        self.assertIn("has no attribute 'lower'", run["error_message"])
        self.assertIn("raise AttributeError", run["error_traceback"])
        self.assertEqual((run["written"], run["not_written"], run["log_path"]), (0, 0, "err.json"))
        self.assertEqual(log_store.get_records(run_id), [])


class NeverRaisesTests(_TempDbCase):
    def test_a_database_error_returns_none_instead_of_failing_the_job(self):
        with mock.patch.object(log_store, "_insert_many", side_effect=RuntimeError("db is down")):
            self.assertIsNone(log_store.save_run(STMT, [self._written()], [], started_at=STARTED))
            self.assertIsNone(log_store.save_failed_run(STMT, ValueError("x"), started_at=STARTED))

    def test_missing_tables_are_not_fatal(self):
        # e.g. a deploy whose migration has not created the tables yet
        with mock.patch.object(connection, "DB_PATH", os.path.join(self.dir, "empty.db")):
            self.assertIsNone(log_store.save_run(STMT, [self._written()], [], started_at=STARTED))


class SchemaParityTests(unittest.TestCase):
    """The SQLite migration and the Azure SQL definitions must describe the
    same columns, or the code that works locally breaks in production."""

    def _sqlite_columns(self, table):
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(os.path.join(tmp, "t.db"))
            apply_pending_migrations(conn)
            cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            conn.close()
        return cols

    def _azure_columns(self, table):
        return re.findall(r"^\s+(\w+)\s+(?:INT|NVARCHAR|FLOAT)", azure.TABLES[table], re.M)

    def test_both_tables_have_the_same_columns_in_sqlite_and_azure(self):
        for table in ("netsuite_writeback_run", "netsuite_writeback_record"):
            with self.subTest(table=table):
                self.assertEqual(self._azure_columns(table), self._sqlite_columns(table))

    def test_the_columns_the_store_writes_all_exist(self):
        self.assertEqual(list(log_store._RUN_COLUMNS), self._sqlite_columns("netsuite_writeback_run")[1:])
        self.assertEqual(list(log_store._RECORD_COLUMNS), self._sqlite_columns("netsuite_writeback_record")[1:])

    def test_the_new_azure_tables_come_last_so_they_cannot_block_an_older_one(self):
        self.assertEqual(list(azure.TABLES)[-2:], ["netsuite_writeback_run", "netsuite_writeback_record"])
        self.assertEqual(list(azure.INDEXES)[-3:],
                         ["idx_nswb_run_statement", "idx_nswb_record_run", "idx_nswb_record_statement"])


if __name__ == "__main__":
    unittest.main()
