"""
tests/test_clear_exception.py

"Clear exception" on the review page (2026-11-04): a person clears an OPEN
exception with a required note. It is recorded as a CLEARED disposition, the
invoice's recon lines become Cleared, the NetSuite flag comes off the bills the
write-back flagged (and the invoice's Statement Line), and a write-back rerun
leaves it alone. Undo reopens it and puts the flag back. NetSuite is a fake
sandbox that keeps state; the Fabric tables are mocked; Azure SQL is SQLite.
"""

import json
import os
import sqlite3
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from src.lakehouse import azure_sql_migrations as azure
from src.lakehouse import migrations as sqlite_migrations
from src.lakehouse import recon_table as rt
from src.lakehouse.migrations import apply_pending_migrations
from src.netsuite import clear_exception as ce
from src.netsuite import manual_match as mm
from src.netsuite import writeback as wb
from web import queries
from web.deps import require_login
from web.routers import exceptions

import test_accept_match as am
from test_manual_match_netsuite import FakeSandbox
from test_netsuite_writeback_plan import _recon, _row

ON = {"NETSUITE_WRITEBACK_ENABLED": "true"}
EXCEPTION = {"exception_id": "EXC-1", "statement_id": "STMT-1", "invoice_number": "INV123",
             "exception_reason": "Not Found in NetSuite", "exception_status": "OPEN",
             "vendor_id": "CONICELLI_TOYOTA", "statement_amount": 50.51}


def _sandbox():
    """INV123: one bill the write-back flagged on STMT-1, one flagged by another
    statement, and a "No match found" Statement Line."""
    ns = FakeSandbox()
    ns.add_txn(700, "INV123", total=-50.51, custbody_reconciliation_exception="7",
               custbody_statement_reference="STMT-1")
    ns.add_txn(701, "INV123", total=-12.00, custbody_reconciliation_exception="7",
               custbody_statement_reference="STMT-OTHER")
    ns.add_line(55, "STMT-1", "INV123", custrecord_sl_status="No match found",
                custrecord_sl_exception_type="No match found")
    return ns


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_REAL_DISCOVER = sqlite_migrations._discover_migrations


class SqliteMigrationTests(unittest.TestCase):
    def test_cleared_is_allowed_and_existing_rows_are_kept(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        with mock.patch.object(sqlite_migrations, "_discover_migrations",
                               side_effect=lambda: [m for m in _REAL_DISCOVER() if int(m[0]) < 27]):
            apply_pending_migrations(conn)
        conn.execute("INSERT INTO exception_dispositions (exception_id, statement_id, vendor_name, invoice_number, "
                     "disposition_status, disposition_notes) VALUES ('E0', 'S0', 'V', 'I0', 'ACCEPTED', 'kept')")
        conn.commit()
        apply_pending_migrations(conn)
        self.assertEqual(conn.execute("SELECT exception_id, disposition_notes FROM exception_dispositions").fetchall(),
                         [("E0", "kept")])
        conn.execute("INSERT INTO exception_dispositions (exception_id, statement_id, vendor_name, invoice_number, "
                     "disposition_status) VALUES ('E1', 'S0', 'V', 'I1', 'CLEARED')")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO exception_dispositions (exception_id, statement_id, vendor_name, invoice_number, "
                         "disposition_status) VALUES ('E2', 'S0', 'V', 'I2', 'NONSENSE')")
        self.assertEqual(conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' "
                                      "AND name = 'idx_exception_dispositions_lookup'").fetchall(),
                         [("idx_exception_dispositions_lookup",)])


class _FakeAzureCursor:
    """Every table, index and column already exists; the disposition CHECK is
    `constraints` (name, definition)."""

    def __init__(self, constraints):
        self.constraints, self.executed, self._last = constraints, [], ""

    def execute(self, sql, params=None):
        self.executed.append(sql)
        self._last = sql

    def fetchone(self):
        return (1,)

    def fetchall(self):
        return list(self.constraints) if "sys.check_constraints" in self._last else []


class AzureCheckConstraintTests(unittest.TestCase):
    def _run(self, constraints):
        cursor = _FakeAzureCursor(constraints)
        conn = mock.Mock()
        conn.cursor.return_value = cursor
        with mock.patch.object(azure, "get_connection", return_value=conn):
            _, _, changed = azure.run_migrations()
        return cursor.executed, changed

    def test_the_old_unnamed_constraint_is_replaced(self):
        executed, changed = self._run([("CK__exception__dispo__3B75D760",
                                        "([disposition_status]='PENDING' OR [disposition_status]='ACCEPTED')")])
        self.assertIn("ALTER TABLE exception_dispositions DROP CONSTRAINT [CK__exception__dispo__3B75D760]", executed)
        added = [s for s in executed if "ADD CONSTRAINT ck_exception_dispositions_status" in s]
        self.assertEqual(len(added), 1)
        self.assertIn("'CLEARED'", added[0])
        self.assertIn("exception_dispositions.disposition_status (CHECK ck_exception_dispositions_status)", changed)

    def test_a_database_that_already_allows_cleared_is_left_alone(self):
        executed, changed = self._run([("ck_exception_dispositions_status",
                                        "([disposition_status]='CLEARED' OR [disposition_status]='PENDING')")])
        self.assertFalse([s for s in executed if "DROP CONSTRAINT" in s or "ADD CONSTRAINT" in s])
        self.assertEqual(changed, [])

    def test_a_new_database_gets_cleared_in_the_create(self):
        self.assertIn("'CLEARED'", azure.TABLES["exception_dispositions"])


# ---------------------------------------------------------------------------
# NetSuite (fake sandbox)
# ---------------------------------------------------------------------------

class NetSuiteClearTests(unittest.TestCase):
    def test_the_flag_comes_off_this_statements_bill_and_line_only(self):
        ns = _sandbox()
        with mock.patch.dict(os.environ, ON):
            result = ce.clear_exception_writes("STMT-1", "INV123", ["81667"], ns=ns)
        self.assertEqual(result["status"], mm.STATUS_WRITTEN, result["detail"])
        self.assertIsNone(ns.txns["700"]["custbody_reconciliation_exception"])
        self.assertEqual(ns.txns["700"]["custbody_reconciled"], "F")          # flag off, NOT reconciled
        self.assertEqual(ns.txns["701"]["custbody_reconciliation_exception"], "7")  # another statement's
        # The write-back's "No match found" Statement Line is deleted (2026-11-05).
        self.assertNotIn("55", ns.lines)
        self.assertIn(("DELETE", "customrecord_statement_line", "55"), ns.calls)

    def test_undo_puts_the_flag_back(self):
        ns = _sandbox()
        with mock.patch.dict(os.environ, ON):
            result = ce.clear_exception_writes("STMT-1", "INV123", ["81667"], ns=ns)
            undone = ce.undo_clear_writes(result["before"], ns=ns)
        self.assertEqual(undone["status"], "undone", undone["detail"])
        self.assertEqual(ns.txns["700"]["custbody_reconciliation_exception"], "7")
        # The deleted Statement Line is created again (a new id) as it was.
        [line] = [l for l in ns.lines.values() if l["custrecord_sl_invoice_number"] == "INV123"]
        self.assertNotEqual(line["id"], "55")
        self.assertEqual((line["custrecord_sl_statement_id"], line["custrecord_sl_status"],
                          line["custrecord_sl_exception_type"]), ("STMT-1", "No match found", "No match found"))
        self.assertIn("re-created as", undone["detail"])

    def test_a_statement_line_that_is_not_a_not_found_line_is_patched_not_deleted(self):
        ns = FakeSandbox()
        ns.add_line(56, "STMT-1", "INV123", custrecord_sl_status="Exception",
                    custrecord_sl_exception_type="Amount differs")
        with mock.patch.dict(os.environ, ON):
            result = ce.clear_exception_writes("STMT-1", "INV123", ["81667"], ns=ns)
        self.assertEqual(result["status"], mm.STATUS_WRITTEN, result["detail"])
        self.assertEqual((ns.lines["56"]["custrecord_sl_status"], ns.lines["56"]["custrecord_sl_exception_type"]),
                         ("Cleared", None))
        self.assertFalse([c for c in ns.calls if c[0] == "DELETE"])

    def test_a_failed_delete_keeps_the_line_and_undo_creates_nothing(self):
        ns = _sandbox()

        def refuse(record_type, record_id, statement_id=None):
            ns.calls.append(("DELETE", record_type, str(record_id)))
            raise RuntimeError("403 Forbidden: permission to delete")
        ns.delete_record = refuse
        with mock.patch.dict(os.environ, ON):
            result = ce.clear_exception_writes("STMT-1", "INV123", ["81667"], ns=ns)
            self.assertIn("55", ns.lines)
            self.assertEqual(result["status"], mm.STATUS_PARTLY, result["detail"])  # bill unflagged, line not
            self.assertIn("permission to delete", result["detail"])
            ce.undo_clear_writes(result["before"], ns=ns)
        self.assertFalse([c for c in ns.calls if c[0] == "POST"])

    def test_the_recreate_body_passes_the_write_guard(self):
        from src.netsuite import guard
        copy = {"name": "STMT-1 INV123", "custrecord_sl_vendor": "81667", "custrecord_sl_statement_id": "STMT-1",
                "custrecord_sl_invoice_number": "INV123", "custrecord_sl_statement_amount": "50.51",
                "custrecord_sl_status": "No match found", "custrecord_sl_exception_type": "No match found",
                "custrecord_sl_matched_bill": None, "custrecord_sl_shop": "Vestal",
                "custrecord_sl_statement_link": "https://vive.sharepoint.com/x.pdf", "custrecord_sl_location": "12",
                "custrecord_sl_date": "10/14/2026", "custrecord_sl_reconciled": "F",
                "custrecord_sl_reconciled_date": ""}
        body = ce.recreate_body(copy)
        guard.check_create("customrecord_statement_line", body)   # raises if anything is off
        self.assertEqual(body["custrecord_sl_date"], "2026-10-14")
        self.assertEqual(body["custrecord_sl_vendor"], {"id": "81667"})
        self.assertEqual(body["custrecord_sl_location"], {"id": "12"})
        self.assertIs(body["custrecord_sl_reconciled"], False)
        self.assertEqual(body["custrecord_sl_statement_amount"], 50.51)
        self.assertNotIn("custrecord_sl_matched_bill", body)

    def test_undo_with_write_back_off_changes_nothing(self):
        ns = _sandbox()
        with mock.patch.dict(os.environ, ON):
            result = ce.clear_exception_writes("STMT-1", "INV123", ["81667"], ns=ns)
        calls = len(ns.calls)
        with mock.patch.dict(os.environ, {"NETSUITE_WRITEBACK_ENABLED": ""}):
            undone = ce.undo_clear_writes(result["before"], ns=ns)
        self.assertEqual(undone["status"], mm.STATUS_OFF)
        self.assertEqual(len(ns.calls), calls)

    def test_with_write_back_off_nothing_is_written(self):
        ns = _sandbox()
        with mock.patch.dict(os.environ, {"NETSUITE_WRITEBACK_ENABLED": ""}):
            result = ce.clear_exception_writes("STMT-1", "INV123", ["81667"], ns=ns)
        self.assertEqual(result["status"], mm.STATUS_OFF)
        self.assertEqual(ns.calls, [])

    def test_nothing_flagged_means_nothing_written(self):
        ns = FakeSandbox()
        with mock.patch.dict(os.environ, ON):
            result = ce.clear_exception_writes("STMT-1", "INV123", ["81667"], ns=ns)
        self.assertEqual((result["status"], result["before"]), (ce.STATUS_NOTHING_FLAGGED, None))
        self.assertEqual(ns.calls, [])

    def test_a_failure_is_reported_not_raised(self):
        ns = _sandbox()
        ns.fail_patch["700"] = RuntimeError("boom")
        with mock.patch.dict(os.environ, ON):
            result = ce.clear_exception_writes("STMT-1", "INV123", ["81667"], ns=ns)
        self.assertEqual(result["status"], mm.STATUS_PARTLY)
        self.assertIn("boom", result["detail"])


class WritebackRerunTests(unittest.TestCase):
    def test_a_cleared_invoice_is_not_flagged_again(self):
        results = {"header": {"vendor_id": "V", "vendor_name_raw": "Vendor", "shop_name_raw": None},
                   "matched": [], "lines": [],
                   "exceptions": [dict(_row("50.00", invoice="INV123"), exception_reason="Not Found in NetSuite"),
                                  dict(_row("10.00", invoice="INV900"), exception_reason="Not Found in NetSuite")]}
        recon = [_recon("INV123", status=rt.STATUS_CLEARED), _recon("INV900", status="Not found in NetSuite")]
        with mock.patch.object(wb, "load_statement_results", return_value=results), \
             mock.patch.object(wb, "resolve_entity_ids", return_value=["111"]), \
             mock.patch.object(wb, "resolve_pdf_link", return_value=(None, "")), \
             mock.patch.object(wb, "fetch_exception_list_ids", return_value={}), \
             mock.patch.object(wb, "fetch_sandbox_transactions", return_value={}), \
             mock.patch.object(wb, "load_recon_rows", return_value=recon), \
             mock.patch.object(wb, "fetch_transactions_by_id", return_value={}), \
             mock.patch.object(wb, "fetch_existing_statement_lines", return_value=set()):
            plans = wb.build_plans("STMT-1", mock.Mock())[1]
        by_invoice = {p.invoice_number: p for p in plans}
        self.assertEqual(by_invoice["INV123"].action, wb.SKIP_UP_TO_DATE)
        self.assertIn("cleared in the app", by_invoice["INV123"].note)
        self.assertEqual(by_invoice["INV900"].action, wb.CREATE_STATEMENT_LINE)


# ---------------------------------------------------------------------------
# Clear and Undo end to end (recon table + dispositions in SQLite)
# ---------------------------------------------------------------------------

class ClearAndUndoTests(am._Db):
    def setUp(self):
        super().setUp()
        rt.replace_auto_rows("STMT-1", rt.build_auto_rows(am.STATEMENT, am.LINES, am.RESULTS))
        conn = self.conn

        def execute_sql(sql, params=None):
            cur = conn.execute(sql, params or [])
            conn.commit()
            return cur

        def execute_query(sql, params=None):
            return [dict(r) for r in conn.execute(sql, params or []).fetchall()]

        self.ns = _sandbox()
        self.recon_sql = mock.Mock()
        for patcher in (mock.patch.object(queries, "execute_sql", execute_sql),
                        mock.patch.object(queries, "execute_query", execute_query),
                        mock.patch.object(queries, "recon_sql", self.recon_sql),
                        mock.patch.object(queries, "_recompute_summary_counts"),
                        mock.patch.object(queries, "_statement_entity_ids", return_value=["81667"]),
                        mock.patch.object(ce, "_client", return_value=self.ns),
                        mock.patch.object(mm, "_client", return_value=self.ns),
                        mock.patch.dict(os.environ, ON)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def statuses(self):
        return {r["statement_line_id"]: r["status"] for r in self.rows(source="auto", is_active=1)}

    def test_clear_then_undo(self):
        result = queries.clear_exception(EXCEPTION, "Conicelli Toyota", "ap@vive.com", "Paid by card")
        self.assertEqual(result["status"], mm.STATUS_WRITTEN)

        # Cleared: the exception resolved, the invoice's lines Cleared with the note, NetSuite unflagged.
        self.assertIn("exception_status = 'RESOLVED'", self.recon_sql.call_args_list[0].args[0])
        self.assertEqual(self.statuses(), {"L1": "Cleared", "L2": "Cleared", "L3": "Matched"})
        line = self.rows(source="auto", statement_line_id="L1")[0]
        self.assertEqual((line["matched_by"], line["note"], line["writeback_status"]),
                         ("ap@vive.com", "Paid by card", mm.STATUS_WRITTEN))
        self.assertIsNone(self.ns.txns["700"]["custbody_reconciliation_exception"])
        [cleared] = queries.get_cleared_exceptions("STMT-1")
        self.assertEqual((cleared["exception_id"], cleared["invoice_number"], cleared["disposition_notes"],
                          cleared["disposed_by"]), ("EXC-1", "INV123", "Paid by card", "ap@vive.com"))

        # Undo: open again, a PENDING row recording it, lines and NetSuite flag back.
        self.assertTrue(queries.undo_clear_exception("EXC-1", "STMT-1", "Conicelli Toyota", "lead@vive.com"))
        self.assertIn("exception_status = 'OPEN'", self.recon_sql.call_args.args[0])
        self.assertEqual(self.recon_sql.call_args.args[1], ["EXC-1"])
        self.assertEqual(self.statuses(), {"L1": "Not found in NetSuite", "L2": "Not found in NetSuite",
                                           "L3": "Matched"})
        line = self.rows(source="auto", statement_line_id="L1")[0]
        self.assertEqual((line["matched_by"], line["note"], line["writeback_status"]), (None, None, "undo: undone"))
        self.assertEqual(self.ns.txns["700"]["custbody_reconciliation_exception"], "7")
        self.assertEqual(queries.get_cleared_exceptions("STMT-1"), [])
        latest = self.conn.execute("SELECT disposition_status, disposition_notes, disposed_by FROM "
                                   "exception_dispositions ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(tuple(latest), ("PENDING", "Undo: cleared exception reopened (was: Paid by card)",
                                         "lead@vive.com"))

        # A second undo has nothing to undo.
        self.assertFalse(queries.undo_clear_exception("EXC-1", "STMT-1", "Conicelli Toyota", "lead@vive.com"))

    def test_clearing_again_after_an_undo_lists_it_once(self):
        queries.clear_exception(EXCEPTION, "Conicelli Toyota", "ap@vive.com", "first")
        queries.undo_clear_exception("EXC-1", "STMT-1", "Conicelli Toyota", "ap@vive.com")
        queries.clear_exception(EXCEPTION, "Conicelli Toyota", "ap@vive.com", "second")
        self.assertEqual([c["disposition_notes"] for c in queries.get_cleared_exceptions("STMT-1")], ["second"])

    def test_a_netsuite_failure_does_not_stop_the_clear(self):
        with mock.patch.object(ce, "_client", side_effect=RuntimeError("NetSuite down")):
            result = queries.clear_exception(EXCEPTION, "Conicelli Toyota", "ap@vive.com", "Paid by card")
        self.assertEqual(result["status"], mm.STATUS_FAILED)
        self.assertEqual(self.statuses()["L1"], "Cleared")
        self.assertEqual(len(queries.get_cleared_exceptions("STMT-1")), 1)

    def test_a_cleared_line_counts_as_resolved_on_the_reconciliation_tab(self):
        from web.statement_processing import _RECON_GROUPS
        self.assertEqual(_RECON_GROUPS["Cleared"], ("resolved", "Cleared"))


# ---------------------------------------------------------------------------
# Routes and page
# ---------------------------------------------------------------------------

class RouteTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="x")
        app.include_router(exceptions.router)
        app.dependency_overrides[require_login] = lambda: "ap@vive.com"
        self.client = TestClient(app)

    def _clear(self, note="Paid by card", exception=EXCEPTION):
        with mock.patch.object(exceptions.queries, "get_recon_exception", return_value=exception), \
             mock.patch.object(exceptions.queries, "clear_exception", return_value={"status": "written"}) as clear:
            resp = self.client.post("/exceptions/Conicelli%20Toyota/clear", follow_redirects=False, data={
                "exception_id": "EXC-1", "statement_id": "STMT-1", "note": note, "filter": "all", "sort": ""})
        return resp, clear

    def test_clearing_saves_the_note_and_says_what_happened(self):
        resp, clear = self._clear(note="  Paid by card  ")
        self.assertEqual(resp.status_code, 303)
        clear.assert_called_once_with(EXCEPTION, "Conicelli Toyota", "ap@vive.com", "Paid by card")
        self.assertIn("statement_id=STMT-1", resp.headers["location"])
        self.assertIn("Invoice+INV123+cleared", resp.headers["location"])

    def test_a_note_is_required(self):
        resp, clear = self._clear(note="   ")
        clear.assert_not_called()
        self.assertIn("add+a+note", resp.headers["location"])

    def test_an_already_resolved_exception_is_not_cleared(self):
        resp, clear = self._clear(exception=dict(EXCEPTION, exception_status="RESOLVED"))
        clear.assert_not_called()
        self.assertIn("already+resolved", resp.headers["location"])

    def test_undo(self):
        with mock.patch.object(exceptions.queries, "undo_clear_exception", return_value=True) as undo:
            resp = self.client.post("/exceptions/Conicelli%20Toyota/undo-clear", follow_redirects=False, data={
                "exception_id": "EXC-1", "statement_id": "STMT-1", "invoice_number": "INV123"})
        undo.assert_called_once_with("EXC-1", "STMT-1", "Conicelli Toyota", "ap@vive.com")
        self.assertIn("open+again", resp.headers["location"])

    def test_the_page_shows_the_button_and_the_cleared_list(self):
        statement = {"statement_id": "STMT-1", "vendor_name": "Conicelli Toyota"}
        open_exc = {"exception_id": "EXC-2", "statement_id": "STMT-1", "invoice_number": "INV7", "vendor_id": "V",
                    "exception_reason": "Not Found in NetSuite", "statement_amount": 10.0, "erp_amount": None,
                    "match_confidence": None, "date_raised": None, "days_open": None, "invoice_date": None}
        cleared = [{"exception_id": "EXC-1", "statement_id": "STMT-1", "invoice_number": "INV'123",
                    "disposition_notes": "Paid by card", "disposed_by": "ap@vive.com",
                    "disposed_at": "2026-11-04T10:00:00+00:00"}]
        with mock.patch.object(exceptions.queries, "get_statement_by_id", return_value=statement), \
             mock.patch.object(exceptions.queries, "get_open_exceptions", return_value=[open_exc]), \
             mock.patch.object(exceptions.queries, "get_exception_counts", return_value=(2, 1)), \
             mock.patch.object(exceptions.queries, "get_statement_shop", return_value=None), \
             mock.patch.object(exceptions.queries, "get_manual_matches", return_value=[]), \
             mock.patch.object(exceptions.queries, "get_cleared_exceptions", return_value=cleared), \
             mock.patch.object(exceptions, "_writeback_status", return_value=None), \
             mock.patch.object(exceptions, "_statement_pdf_url", return_value=None), \
             mock.patch.object(exceptions, "sidebar_context", return_value={}):
            resp = self.client.get("/exceptions/Conicelli%20Toyota?statement_id=STMT-1")
        self.assertEqual(resp.status_code, 200)
        html = resp.text
        self.assertIn('action="/exceptions/Conicelli%20Toyota/clear"', html)
        self.assertIn('name="exception_id" value="EXC-2"', html)
        self.assertIn('textarea id="clearExcNote" name="note" rows="3" required', html)
        self.assertIn("Cleared (1)", html)
        self.assertIn("Paid by card", html)
        self.assertIn('action="/exceptions/Conicelli%20Toyota/undo-clear"', html)
        self.assertIn("\\u0027", html)  # the invoice's quote can't break the confirm() text


if __name__ == "__main__":
    unittest.main()
