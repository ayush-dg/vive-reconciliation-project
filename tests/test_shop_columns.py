"""
tests/test_shop_columns.py

Where a statement's customer location is stored (src/validation/shop_list.py
LOCATION_COLUMNS): document_intake_log (SQLite migration 026 and the Azure
SQL column list), bronze.raw_statement (write_raw_statement) and
silver.statement (the dbt model, plus the script that adds the Warehouse
columns). No network, Fabric or database beyond an in-memory SQLite one.
"""

import contextlib
import importlib.util
import os
import sqlite3
import sys
import types
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import pandas  # noqa: F401 -- imported before sys.modules is patched, or the patch's exit un-imports it

from src.lakehouse import bronze_raw
from src.lakehouse.azure_sql_migrations import COLUMNS as AZURE_COLUMNS
from src.lakehouse.migrations import apply_pending_migrations
from src.validation.shop_list import LOCATION_COLUMNS

NEW_INTAKE_COLUMNS = ("billing_location_extracted", "shop_phone", "shop_city", "shop_state")


class IntakeLogColumns(unittest.TestCase):
    def test_sqlite_migration_adds_the_columns(self):
        conn = sqlite3.connect(":memory:")
        apply_pending_migrations(conn)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(document_intake_log)")}
        self.assertTrue(set(LOCATION_COLUMNS) <= columns, set(LOCATION_COLUMNS) - columns)

    def test_azure_sql_adds_the_columns_billing_location_already_exists(self):
        added = {name for name, _ in AZURE_COLUMNS["document_intake_log"]}
        self.assertTrue(set(NEW_INTAKE_COLUMNS) <= added)
        self.assertIn("billing_location", added)  # migration 017, unchanged


class IntakeWritesTheLocation(unittest.TestCase):
    """intake_log_values() carries the five fields into document_intake_log."""

    def setUp(self):
        from src.rerun.in_place import load_intake
        self.intake = load_intake()

    def schema(self):
        return {"document_metadata": {"document_type": "VENDOR_STATEMENT"},
                "vendor_metadata": self.intake.apply_location(
                    {"vendor_name": "Quirk", "shop_or_entity": ["VIVE COLLISION- RP BELL"],
                     "billing_location": "Mechanic Falls, ME"}, self.intake.resolve_billing_location),
                "statement_metadata": {"statement_date": "09/30/2026"}}

    def test_the_values_carry_the_mapped_location_and_the_shop_details(self):
        values = self.intake.intake_log_values("d", "x.pdf", "h", self.schema(), "STMT-1", "2026-09", 1, "RECONCILIATION")
        self.assertEqual(
            {c: values[c] for c in LOCATION_COLUMNS},
            {"billing_location_extracted": "Mechanic Falls, ME", "billing_location": "RP Bell",
             "shop_phone": "(207) 282-6860", "shop_city": "Saco", "shop_state": "ME"})
        self.assertEqual(values["billing_location_source"], "name_match")

    def test_the_values_insert_into_the_intake_log(self):
        values = self.intake.intake_log_values("d", "x.pdf", "h", self.schema(), "STMT-1", "2026-09", 1, "RECONCILIATION")
        conn = sqlite3.connect(":memory:")
        apply_pending_migrations(conn)
        conn.execute(f"INSERT INTO document_intake_log ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
                     list(values.values()))
        row = conn.execute("SELECT billing_location, shop_city, shop_state, shop_phone, billing_location_extracted "
                           "FROM document_intake_log").fetchone()
        self.assertEqual(row, ("RP Bell", "Saco", "ME", "(207) 282-6860", "Mechanic Falls, ME"))


class RawStatementWrite(unittest.TestCase):
    """write_raw_statement() puts the location on the statement's one row."""

    def write(self, **kwargs):
        written = []
        fake = types.ModuleType("deltalake")
        fake.write_deltalake = lambda uri, df, **kw: written.append((uri, df, kw))
        with mock.patch.dict(sys.modules, {"deltalake": fake}), \
                mock.patch.object(bronze_raw, "_fabric_configured", return_value=True), \
                mock.patch.object(bronze_raw, "_staging_table_uri", return_value="staging"), \
                mock.patch.object(bronze_raw, "_storage_options", return_value={}), \
                mock.patch.object(bronze_raw, "fabric_pipeline_lock", contextlib.nullcontext):
            result = bronze_raw.write_raw_statement([{"_raw_row": {"a": 1}}], "V1", "STMT-1", "f.pdf", "claude", **kwargs)
        return result, written

    def test_location_columns_are_written_on_the_row(self):
        location = {"billing_location_extracted": "Mechanic Falls, ME", "billing_location": "RP Bell",
                    "shop_phone": "(207) 282-6860", "shop_city": "Saco", "shop_state": "ME"}
        result, written = self.write(location=location)
        self.assertEqual(result, 1)
        row = written[0][1].iloc[0]
        for column, value in location.items():
            self.assertEqual(row[column], value)
        self.assertEqual(written[0][2]["schema_mode"], "merge")

    def test_without_a_location_the_columns_are_null(self):
        result, written = self.write()
        self.assertEqual(result, 1)
        df = written[0][1]
        for column in LOCATION_COLUMNS:
            self.assertIn(column, df.columns)
            self.assertTrue(df[column].isna().all(), column)

    def test_a_partial_location_leaves_the_rest_null(self):
        _, written = self.write(location={"billing_location_extracted": "Scarborough, ME"})
        row = written[0][1].iloc[0]
        self.assertEqual(row["billing_location_extracted"], "Scarborough, ME")
        self.assertTrue(row["shop_city"] is None or str(row["shop_city"]) == "<NA>")


class SilverColumns(unittest.TestCase):
    def test_the_dbt_model_selects_every_location_column(self):
        with open(os.path.join(ROOT, "dbt", "vive_recon", "models", "silver", "statement.sql"), encoding="utf-8") as f:
            sql = f.read()
        for column in LOCATION_COLUMNS:
            self.assertGreaterEqual(sql.count(column), 3, column)  # bronze select, header, final select

    def test_the_lakehouse_schema_script_has_every_location_column(self):
        with open(os.path.join(ROOT, "scripts", "create_fabric_lakehouse_schema.py"), encoding="utf-8") as f:
            source = f.read()
        for column in LOCATION_COLUMNS:
            self.assertIn(f'"{column}"', source)

    def test_the_warehouse_script_types_every_location_column(self):
        spec = importlib.util.spec_from_file_location(
            "add_shop_columns_warehouse", os.path.join(ROOT, "scripts", "add_shop_columns_warehouse.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(set(module.COLUMN_TYPES), set(LOCATION_COLUMNS))


if __name__ == "__main__":
    unittest.main()
