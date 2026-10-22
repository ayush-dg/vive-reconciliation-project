"""
tests/test_recon_table.py

The recon table (src/lakehouse/recon_table.py, 2026-10-19): one row per
statement line with its reconciliation status and the NetSuite record it is
linked to. Rows are built from the matcher's per-line results, replace only
a statement's "auto" rows on a re-run (manual matches survive), and Accept /
Reject on an exception set its lines to Accepted / Rejected.

Runs against an in-memory SQLite database built by the real migrations.
"""

import os
import re
import sqlite3
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.lakehouse import recon_table as rt
from src.lakehouse.azure_sql_migrations import TABLES
from src.lakehouse.migrations import apply_pending_migrations
from src.matching import fabric_matching as fm

STATEMENT = {"statement_id": "STMT-1", "vendor_id": "CONICELLI_TOYOTA", "vendor_name": "Conicelli Toyota",
             "statement_period": "2026-10"}
BILL_23 = {"record_type": "bill", "id": 9123, "tranid": "23", "transaction_number": "VENDBILL23",
           "entity": 81667, "location": "64", "amount": 57.54}


def _lines():
    return [
        {"statement_line_id": "L0", "line_number": 0, "invoice_number": "INV100", "document_number": "INV100",
         "line_date": "2026-09-01", "charge_amount": 10.0},
        {"statement_line_id": "L1", "line_number": 1, "invoice_number": "INV123", "document_number": "TOWINV123",
         "line_date": "2026-09-02", "charge_amount": 50.51},
        {"statement_line_id": "L2", "line_number": 2, "invoice_number": "INV123", "document_number": "TOWINV123",
         "line_date": "2026-09-03", "payment_amount": 5.0},
        {"statement_line_id": "L3", "line_number": 3, "invoice_number": None, "payment_amount": 100.0},
        {"statement_line_id": "L4", "line_number": 4, "invoice_number": "INV200", "charge_amount": 7.0,
         "_recon_note": "set aside by this vendor's line selection rule (reprint/duplicate)"},
    ]


def _results():
    return {
        "L0": {"invoice_number": "INV100", "status": "Matched", "statement_amount": 10.0,
               "netsuite": dict(BILL_23, tranid="INV100", amount=10.0, id=9100), "match_rule": "invoice number"},
        "L1": {"invoice_number": "INV123", "status": "Amount mismatch", "statement_amount": 50.51,
               "exception_id": "EXC-1", "exception_reason": "Amount Mismatch", "netsuite": BILL_23,
               "match_rule": "invoice number"},
        "L2": {"invoice_number": "INV123", "status": "Amount mismatch", "statement_amount": 50.51,
               "exception_id": "EXC-1", "exception_reason": "Amount Mismatch", "netsuite": BILL_23,
               "match_rule": "invoice number"},
    }


class TestBuildAutoRows(unittest.TestCase):

    def setUp(self):
        self.rows = rt.build_auto_rows(STATEMENT, _lines(), _results(), now="2026-10-19T00:00:00+00:00")

    def test_one_row_per_line_with_statement_and_vendor(self):
        self.assertEqual(len(self.rows), 5)
        for row in self.rows:
            self.assertEqual((row["statement_id"], row["vendor_id"], row["source"]), ("STMT-1", "CONICELLI_TOYOTA", "auto"))

    def test_statuses_and_netsuite_link(self):
        by_line = {r["line_number"]: r for r in self.rows}
        self.assertEqual(by_line[0]["status"], "Matched")
        self.assertEqual((by_line[0]["netsuite_tranid"], by_line[0]["netsuite_internal_id"], by_line[0]["difference"]),
                         ("INV100", "9100", 0.0))
        mismatch = by_line[1]
        self.assertEqual((mismatch["status"], mismatch["exception_id"], mismatch["netsuite_tranid"],
                          mismatch["netsuite_record_type"], mismatch["netsuite_location"]),
                         ("Amount mismatch", "EXC-1", "23", "bill", "64"))
        self.assertEqual(mismatch["difference"], -7.03)
        self.assertEqual(mismatch["original_invoice_number"], "TOWINV123")
        # Both lines of INV123 share the invoice's result; each keeps its own amount.
        self.assertEqual((by_line[2]["status"], by_line[2]["line_amount"]), ("Amount mismatch", -5.0))

    def test_lines_without_a_result_are_not_reconciled_with_a_reason(self):
        by_line = {r["line_number"]: r for r in self.rows}
        self.assertEqual(by_line[3]["status"], "Not reconciled")
        self.assertIsNone(by_line[3]["netsuite_tranid"])
        self.assertEqual(by_line[4]["status"], "Not reconciled")
        self.assertIn("line selection rule", by_line[4]["note"])


class _Shared:
    """A shared in-memory connection whose close() is a no-op, so code that
    opens and closes its own connection keeps using the same database."""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        pass


class _DbTest(unittest.TestCase):

    def setUp(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        apply_pending_migrations(conn)
        self.conn = conn
        shared = _Shared(conn)

        def execute_sql(sql, params=None):
            cur = conn.execute(sql, params or [])
            conn.commit()
            return cur

        def execute_query(sql, params=None):
            return [dict(r) for r in conn.execute(sql, params or []).fetchall()]

        for name, fn in (("get_connection", lambda: shared), ("execute_sql", execute_sql),
                         ("execute_query", execute_query)):
            patcher = mock.patch.object(rt, name, fn)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(conn.close)

    def _rows(self, **where):
        sql = "SELECT * FROM recon"
        if where:
            sql += " WHERE " + " AND ".join(f"{k} = ?" for k in where)
        return [dict(r) for r in self.conn.execute(sql + " ORDER BY line_number, id", list(where.values()))]


class TestReplaceAutoRows(_DbTest):

    def test_rerun_replaces_only_auto_rows_and_keeps_manual_matches(self):
        rows = rt.build_auto_rows(STATEMENT, _lines(), _results())
        self.assertEqual(rt.replace_auto_rows("STMT-1", rows), 5)
        self.assertEqual(len(self._rows(statement_id="STMT-1")), 5)

        # A person manually matched INV123 (step b writes these).
        for line_number in (1, 2):
            self.conn.execute(
                "INSERT INTO recon (recon_id, statement_id, line_number, invoice_number, status, source, "
                "netsuite_tranid, created_at) VALUES (?, 'STMT-1', ?, 'INV123', 'Matched manually', 'manual', '23', 'x')",
                [f"M{line_number}", line_number])
        self.conn.execute("DELETE FROM recon WHERE source = 'auto' AND invoice_number = 'INV123'")
        self.conn.commit()

        # Re-run: auto rows are replaced; INV123's active rows stay the manual
        # ones, its auto rows are kept inactive so an Undo can bring them back.
        rerun = rt.build_auto_rows(STATEMENT, _lines(), _results())
        self.assertEqual(rt.replace_auto_rows("STMT-1", rerun), 3)
        inv123 = self._rows(statement_id="STMT-1", invoice_number="INV123")
        self.assertEqual({(r["source"], r["status"]) for r in inv123 if r["is_active"]},
                         {("manual", "Matched manually")})
        self.assertEqual({r["source"] for r in inv123 if not r["is_active"]}, {"auto"})
        self.assertEqual(len([r for r in self._rows(statement_id="STMT-1") if r["is_active"]]), 5)

    def test_other_statements_are_untouched(self):
        rt.replace_auto_rows("STMT-1", rt.build_auto_rows(STATEMENT, _lines(), _results()))
        other = dict(STATEMENT, statement_id="STMT-2")
        rt.replace_auto_rows("STMT-2", rt.build_auto_rows(other, _lines()[:1], {}))
        self.assertEqual(len(self._rows(statement_id="STMT-1")), 5)
        self.assertEqual(len(self._rows(statement_id="STMT-2")), 1)


class TestMarkResolved(_DbTest):

    def setUp(self):
        super().setUp()
        rt.replace_auto_rows("STMT-1", rt.build_auto_rows(STATEMENT, _lines(), _results()))

    def test_accept_sets_the_invoices_exception_lines_to_accepted(self):
        rt.mark_resolved("STMT-1", "INV123", "ACCEPTED", "ap@vive.com", "posted late")
        inv123 = self._rows(statement_id="STMT-1", invoice_number="INV123")
        self.assertEqual({r["status"] for r in inv123}, {"Accepted"})
        self.assertEqual({(r["matched_by"], r["note"]) for r in inv123}, {("ap@vive.com", "posted late")})
        # Other invoices are untouched.
        self.assertEqual(self._rows(statement_id="STMT-1", invoice_number="INV100")[0]["status"], "Matched")

    def test_reject_is_rejected_and_a_matched_line_is_never_overwritten(self):
        rt.mark_resolved("STMT-1", "INV123", "DISPUTED", "ap@vive.com")
        self.assertEqual({r["status"] for r in self._rows(invoice_number="INV123")}, {"Rejected"})
        rt.mark_resolved("STMT-1", "INV100", "ACCEPTED", "ap@vive.com")
        self.assertEqual(self._rows(invoice_number="INV100")[0]["status"], "Matched")


class TestMatcherHelpers(unittest.TestCase):

    def test_candidates_remember_which_record_each_total_came_from(self):
        cands = fm._Candidates()
        cands.setdefault("26-36498", []).append(400.0)
        cands.records[("26-36498", 400.0)] = [dict(BILL_23, tranid="26-36498", amount=400.0)]
        self.assertEqual(cands["26-36498"], [400.0])
        self.assertEqual(cands.record_for("26-36498", 400.0)["tranid"], "26-36498")
        self.assertIsNone(cands.record_for("26-36498", 1.0))
        self.assertIsNone(cands.record_for(None, 400.0))

    def test_set_aside_lines_get_a_note(self):
        lines = _lines()[:3]
        fm._note_set_aside(lines, lines[:1], "why")
        self.assertEqual([l.get("_recon_note") for l in lines], [None, "why", "why"])

    def test_keystone_credit_record(self):
        credits = fm._Candidates()
        credits.records[("cmz1451096", 12.5)] = [{"tranid": "CMZ1451096", "id": 7}]
        found = fm._keystone_credit_record(credits, [("cmz1451096", 12.5), ("other", 12.5)], "Z1451096", 12.5)
        self.assertEqual(found["id"], 7)
        self.assertIsNone(fm._keystone_credit_record(credits, [("cmz1451096", 12.5)], "Z1451096", None))

    def test_exception_writer_returns_the_new_exception_id(self):
        writes = fm._PendingWrites()
        exception_id = fm._write_exception(writes, "S", "V", None, None, "INV1", None, 1.0, None,
                                           "Not Found in NetSuite", "now")
        self.assertRegex(exception_id, r"^[0-9a-f-]{36}$")
        self.assertEqual(writes._rows["silver.recon_exceptions"][1][0][0], exception_id)

    def test_status_for_reason(self):
        self.assertEqual(rt.status_for_reason("Not Found in NetSuite"), "Not found in NetSuite")
        self.assertEqual(rt.status_for_reason("Possible Duplicate in NetSuite"), "Possible duplicate")

    def test_a_recon_failure_never_fails_matching(self):
        with mock.patch.object(fm, "replace_auto_rows", side_effect=RuntimeError("db down")):
            self.assertIsNone(fm._write_recon_rows(STATEMENT, _lines(), _results(), "now"))


class TestResolveExceptionUpdatesRecon(unittest.TestCase):

    def _resolve(self, mark):
        from web import queries
        with mock.patch.object(queries, "execute_sql"), mock.patch.object(queries, "recon_sql"), \
                mock.patch.object(queries, "_recompute_summary_counts"), \
                mock.patch("src.lakehouse.recon_table.mark_resolved", mark):
            queries.resolve_exception("EXC-1", "STMT-1", "Conicelli Toyota", "INV123", "Amount Mismatch",
                                      "ACCEPTED", "note", "ap@vive.com")

    def test_accept_marks_the_recon_lines(self):
        mark = mock.Mock()
        self._resolve(mark)
        mark.assert_called_once_with("STMT-1", "INV123", "ACCEPTED", "ap@vive.com", "note")

    def test_a_recon_failure_never_blocks_resolving(self):
        self._resolve(mock.Mock(side_effect=RuntimeError("db down")))  # must not raise


class TestSchema(unittest.TestCase):

    def test_azure_table_has_every_column_the_code_writes(self):
        ddl = TABLES["recon"]
        for column in rt.COLUMNS:
            self.assertRegex(ddl, rf"\b{column}\b", column)
        for column in ("statement_id", "vendor_id", "status", "netsuite_tranid", "writeback_status",
                       "netsuite_before", "is_active", "undone_by"):
            self.assertIn(column, ddl)
        # No shop column (2026-10-19, per the user).
        self.assertNotRegex(ddl, r"\bshop\b")
        self.assertNotIn("shop", rt.COLUMNS)


if __name__ == "__main__":
    unittest.main()
