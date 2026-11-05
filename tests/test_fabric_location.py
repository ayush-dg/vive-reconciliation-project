"""
tests/test_fabric_location.py

src/lakehouse/fabric_location.py: Azure SQL's location for a statement is copied
to Fabric -- bronze first, then silver -- only when silver differs; nothing
raises. Fabric itself is replaced by mocks.
"""

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from src.lakehouse import fabric_location
from src.validation import invoice_location
from src.validation.shop_list import LOCATION_COLUMNS

WANTED = {"billing_location_extracted": "AUBURN, ME", "billing_location": "Hewitt's", "shop_phone": "207-555-0100",
          "shop_city": "Auburn", "shop_state": "ME"}
STALE = {**WANTED, "billing_location": "AUBURN, ME", "shop_phone": None, "shop_city": None, "shop_state": None}
CONFIGURED = "src.lakehouse.bronze_raw._fabric_configured"


class Cursor:
    def __init__(self, silver):
        self.silver, self.executed = silver, []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return tuple(self.silver[c] for c in LOCATION_COLUMNS) if self.silver else None


class Connection:
    def __init__(self, silver):
        self.cur, self.committed, self.closed = Cursor(silver), 0, False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed += 1

    def close(self):
        self.closed = True


class Sync(unittest.TestCase):
    def run_sync(self, silver, azure=WANTED, configured=True):
        conn, order = Connection(silver), []
        with mock.patch(CONFIGURED, return_value=configured), \
                mock.patch.object(fabric_location, "_azure_values", return_value=azure), \
                mock.patch("src.lakehouse.fabric_sql.get_warehouse_connection", return_value=conn), \
                mock.patch.object(fabric_location, "_update_bronze", side_effect=lambda *a: order.append("bronze")), \
                mock.patch.object(fabric_location, "_update_silver", side_effect=lambda *a: order.append("silver")):
            return fabric_location.sync_statement_location("S-1"), order, conn

    def test_a_stale_silver_row_is_updated_bronze_first(self):
        changed, order, conn = self.run_sync(STALE)
        self.assertTrue(changed)
        self.assertEqual(order, ["bronze", "silver"])
        self.assertTrue(conn.closed)

    def test_nothing_is_written_when_silver_already_agrees(self):
        changed, order, _ = self.run_sync(WANTED)
        self.assertFalse(changed)
        self.assertEqual(order, [])

    def test_a_statement_not_in_silver_yet_is_left_to_its_build(self):
        changed, order, _ = self.run_sync(None)
        self.assertFalse(changed)
        self.assertEqual(order, [])

    def test_nothing_happens_without_fabric_or_without_an_azure_row(self):
        self.assertEqual(self.run_sync(STALE, configured=False)[:2], (False, []))
        self.assertEqual(self.run_sync(STALE, azure=None)[:2], (False, []))

    def test_a_failure_in_bronze_is_logged_not_raised_and_silver_is_not_touched(self):
        order = []
        with mock.patch(CONFIGURED, return_value=True), \
                mock.patch.object(fabric_location, "_azure_values", return_value=WANTED), \
                mock.patch("src.lakehouse.fabric_sql.get_warehouse_connection", return_value=Connection(STALE)), \
                mock.patch.object(fabric_location, "_update_bronze", side_effect=RuntimeError("lock timeout")), \
                mock.patch.object(fabric_location, "_update_silver", side_effect=lambda *a: order.append("silver")):
            self.assertFalse(fabric_location.sync_statement_location("S-1"))
        self.assertEqual(order, [])

    def test_the_silver_update_sets_every_location_column_for_the_statement(self):
        conn = Connection(STALE)
        fabric_location._update_silver(conn, conn.cur, "S-1", WANTED)
        sql, params = conn.cur.executed[0]
        self.assertTrue(sql.startswith("UPDATE silver.statement SET "))
        for column in LOCATION_COLUMNS:
            self.assertIn(f"{column} = ?", sql)
        self.assertEqual(params, [WANTED[c] for c in LOCATION_COLUMNS] + ["S-1"])
        self.assertEqual(conn.committed, 1)

    def test_the_bronze_update_quotes_values_and_nulls(self):
        table = mock.Mock()
        with mock.patch("deltalake.DeltaTable", return_value=table), \
                mock.patch("src.lakehouse.bronze_raw._table_uri", return_value="uri"), \
                mock.patch("src.lakehouse.bronze_raw._storage_options", return_value={}), \
                mock.patch("src.lakehouse.fabric_dbt_runner.fabric_pipeline_lock"):
            fabric_location._update_bronze("S'1", {**WANTED, "billing_location": "Dunkin's", "shop_phone": None})
        kwargs = table.update.call_args.kwargs
        self.assertEqual(kwargs["predicate"], "statement_id = 'S''1'")
        self.assertEqual(kwargs["updates"]["billing_location"], "'Dunkin''s'")
        self.assertEqual(kwargs["updates"]["shop_phone"], "NULL")


class SilverRows(Cursor):
    """A cursor whose SELECT of the whole silver.statement table returns `rows`."""

    def __init__(self, rows):
        super().__init__(None)
        self.rows = rows

    def fetchall(self):
        return self.rows


class BulkConnection(Connection):
    def __init__(self, rows):
        super().__init__(None)
        self.cur = SilverRows(rows)


def silver_row(sid, values):
    return (sid, *[values[c] for c in LOCATION_COLUMNS])


class Bulk(unittest.TestCase):
    AZURE = {"S-STALE": WANTED, "S-SAME": WANTED, "S-NOSILVER": WANTED, "S-OTHER": WANTED}

    def plan(self, only=None):
        conn = BulkConnection([silver_row("S-STALE", STALE), silver_row("S-SAME", WANTED),
                               silver_row("S-OTHER", STALE)])
        with mock.patch.object(fabric_location, "_azure_values_by_statement",
                               side_effect=lambda ids=None: {s: v for s, v in self.AZURE.items()
                                                             if ids is None or s in ids}), \
                mock.patch("src.lakehouse.fabric_sql.get_warehouse_connection", return_value=conn):
            return fabric_location.plan_sync(only), conn

    def test_the_plan_lists_only_statements_whose_silver_row_differs(self):
        plan, conn = self.plan()
        self.assertEqual(sorted(plan), ["S-OTHER", "S-STALE"])   # S-SAME agrees, S-NOSILVER has no row
        self.assertTrue(conn.closed)

    def test_the_plan_can_be_limited_to_some_statements(self):
        self.assertEqual(list(self.plan({"S-STALE"})[0]), ["S-STALE"])

    def test_sync_many_merges_all_of_bronze_before_updating_silver(self):
        order = []
        with mock.patch.object(fabric_location, "_merge_bronze", side_effect=lambda p: order.append(("bronze", len(p)))), \
                mock.patch.object(fabric_location, "_update_silver_many",
                                  side_effect=lambda p: order.append(("silver", len(p))) or len(p)):
            result = fabric_location.sync_many({"S-1": WANTED, "S-2": WANTED}, log=lambda *_: None)
        self.assertEqual(order, [("bronze", 2), ("silver", 2)])
        self.assertEqual(result, {"bronze": 2, "silver": 2})

    def test_sync_many_does_nothing_for_an_empty_plan(self):
        with mock.patch.object(fabric_location, "_merge_bronze") as bronze:
            self.assertEqual(fabric_location.sync_many({}), {"bronze": 0, "silver": 0})
        bronze.assert_not_called()

    def test_a_bronze_failure_leaves_silver_untouched(self):
        with mock.patch.object(fabric_location, "_merge_bronze", side_effect=RuntimeError("lock")), \
                mock.patch.object(fabric_location, "_update_silver_many") as silver:
            with self.assertRaises(RuntimeError):
                fabric_location.sync_many({"S-1": WANTED}, log=lambda *_: None)
        silver.assert_not_called()

    def merge_with(self, table, plan):
        lock = mock.MagicMock()
        with mock.patch("deltalake.DeltaTable", return_value=table), \
                mock.patch("src.lakehouse.bronze_raw._table_uri", return_value="uri"), \
                mock.patch("src.lakehouse.bronze_raw._storage_options", return_value={}), \
                mock.patch("src.lakehouse.fabric_dbt_runner.fabric_pipeline_lock", lock):
            fabric_location._merge_bronze(plan)
        return lock

    def test_a_conflicting_commit_is_retried_but_other_errors_are_not(self):
        table = mock.MagicMock()
        execute = table.merge.return_value.when_matched_update.return_value.execute
        execute.side_effect = [RuntimeError("Commit failed: a concurrent transactions added new data"), None]
        self.merge_with(table, {"S-1": WANTED})
        self.assertEqual(execute.call_count, 2)
        execute.reset_mock()
        execute.side_effect = RuntimeError("access denied")
        with self.assertRaises(RuntimeError):
            self.merge_with(table, {"S-1": WANTED})
        self.assertEqual(execute.call_count, 1)

    def test_the_bronze_merge_is_one_merge_for_every_statement_under_the_lock(self):
        table = mock.MagicMock()
        lock = self.merge_with(table, {f"S-{n}": WANTED for n in range(1200)})
        self.assertEqual(lock.call_count, 1)
        self.assertEqual(len(table.merge.call_args.kwargs["source"]), 1200)
        merge = table.merge.return_value
        self.assertEqual(merge.when_matched_update.call_args.kwargs["updates"]["billing_location"], "s.billing_location")
        self.assertEqual(table.merge.call_args.kwargs["predicate"], "t.statement_id = s.statement_id")

    def test_silver_is_updated_per_statement_and_committed_in_batches(self):
        conn = BulkConnection([])
        plan = {f"S-{n}": WANTED for n in range(fabric_location.SILVER_COMMIT_EVERY + 1)}
        with mock.patch("src.lakehouse.fabric_sql.get_warehouse_connection", return_value=conn):
            done = fabric_location._update_silver_many(plan)
        self.assertEqual(done, len(plan))
        self.assertEqual(len(conn.cur.executed), len(plan))
        self.assertEqual(conn.committed, 2)    # after the first full batch, and the final one
        self.assertTrue(conn.closed)


class Callers(unittest.TestCase):
    def test_a_manual_match_refreshes_then_copies_in_the_background(self):
        with mock.patch.object(invoice_location, "refresh_quietly") as refresh, \
                mock.patch("src.lakehouse.fabric_location.sync_in_background") as background:
            invoice_location.refresh_and_sync_quietly("S-1")
        refresh.assert_called_once_with("S-1")
        background.assert_called_once_with("S-1")

    def test_the_matching_hook_does_not_touch_fabric(self):
        with mock.patch("src.lakehouse.fabric_location.sync_statement_location") as sync, \
                mock.patch("src.lakehouse.fabric_location.sync_in_background") as background, \
                mock.patch.object(invoice_location, "refresh_statement_location", return_value=None):
            invoice_location.refresh_quietly("S-1")
        sync.assert_not_called()
        background.assert_not_called()

    def test_a_failure_starting_the_copy_never_propagates(self):
        with mock.patch.object(invoice_location, "refresh_quietly"), \
                mock.patch("src.lakehouse.fabric_location.sync_in_background", side_effect=RuntimeError("x")):
            invoice_location.refresh_and_sync_quietly("S-1")


if __name__ == "__main__":
    unittest.main()
