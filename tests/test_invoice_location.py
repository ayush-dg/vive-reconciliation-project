"""
tests/test_invoice_location.py

src/validation/invoice_location.py and scripts/fill_location_from_invoices.py
against a migrated SQLite database: a statement the name/city mapping could not
place takes the shop of its matched bills; a confident one is left alone; undo
and re-run behave.
"""

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from src.lakehouse.migrations import apply_pending_migrations
from src.validation import invoice_location

spec = importlib.util.spec_from_file_location("fill", os.path.join(ROOT, "scripts", "fill_location_from_invoices.py"))
fill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fill)

# NetSuite location ids in config/netsuite_locations.json: 4 Hewitt's, 28 Highway 35, 44 Bangor, 65 Maine Collision.
STATEMENTS = {  # statement_id: (shop_or_entity, billing_location, source)
    "S-CONFLICT": (["CARONS BODY SHOP DBA HEWITTS AUTO B"], "AUBURN, ME", "conflict"),
    "S-UNMAPPED": (["BERNATCHE AUTO BODY"], "BANGOR ME", "unmapped"),
    "S-AMBIGUOUS": (["MIDDLETOWN"], "MIDDLETOWN", "ambiguous"),
    "S-SEVERAL": (["X"], "Somewhere, ME", "unmapped"),
    "S-NOBILL": (["Y"], "Elsewhere, ME", "unmapped"),
    "S-CONFIDENT": (["Coleman's Auto Body"], "Coleman's", "name_match"),
    "S-NOTSHOP": (["Z"], "Nowhere, ME", "unmapped"),
}
RECON = [  # (statement_id, netsuite_location, status, is_active)
    ("S-CONFLICT", "4", "Matched", 1), ("S-CONFLICT", "4", "Matched", 1),
    ("S-UNMAPPED", "44", "Matched manually", 1),
    ("S-AMBIGUOUS", "28", "Matched", 1),
    ("S-SEVERAL", "4", "Matched", 1), ("S-SEVERAL", "44", "Matched", 1),
    ("S-CONFIDENT", "44", "Matched", 1),   # a bill elsewhere must not change a confident mapping
    ("S-NOTSHOP", "9999", "Matched", 1),
]


class Database(unittest.TestCase):
    """A migrated SQLite database holding STATEMENTS and RECON."""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        apply_pending_migrations(conn)
        for n, (sid, (shop, location, source)) in enumerate(STATEMENTS.items()):
            conn.execute("INSERT INTO document_intake_log (document_id, source_file, ingestion_timestamp, statement_id, "
                         "shop_or_entity, billing_location, billing_location_extracted, billing_location_source) "
                         "VALUES (?,?,?,?,?,?,?,?)",
                         [f"d{n}", f"{sid}.pdf", "2026-10-01", sid, json.dumps(shop), location, location, source])
        for n, (sid, location, status, active) in enumerate(RECON):
            conn.execute("INSERT INTO recon (recon_id, statement_id, status, source, netsuite_location, is_active, created_at) "
                         "VALUES (?,?,?,?,?,?,?)", [f"r{n}", sid, status, "auto", location, active, "2026-10-02"])
        conn.commit()
        conn.close()
        self.backup = self.db + ".csv"
        self.addCleanup(lambda: os.path.exists(self.backup) and os.remove(self.backup))
        self.addCleanup(os.remove, self.db)
        for patcher in (mock.patch("src.lakehouse.connection.DB_PATH", self.db),
                        mock.patch.dict(os.environ, {"AZURE_SQL_SERVER": ""})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def row(self, statement_id):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        found = conn.execute("SELECT * FROM document_intake_log WHERE statement_id = ?", [statement_id]).fetchone()
        conn.close()
        return dict(found)

    def recon_set(self, statement_id, **values):
        conn = sqlite3.connect(self.db)
        conn.execute(f"UPDATE recon SET {', '.join(f'{k} = ?' for k in values)} WHERE statement_id = ?",
                     [*values.values(), statement_id])
        conn.commit()
        conn.close()


class InvoiceLocation(Database):
    def test_a_conflict_takes_the_bills_shop(self):
        self.assertEqual(invoice_location.refresh_statement_location("S-CONFLICT"), "Hewitt's")
        row = self.row("S-CONFLICT")
        self.assertEqual((row["billing_location"], row["billing_location_source"], row["billing_location_extracted"],
                          row["shop_city"], row["shop_state"]), ("Hewitt's", "invoice_match", "AUBURN, ME", "Yarmouth", "ME"))

    def test_an_unmapped_row_takes_a_manually_matched_bills_shop(self):
        self.assertEqual(invoice_location.refresh_statement_location("S-UNMAPPED"), "Bangor")
        self.assertEqual(self.row("S-UNMAPPED")["billing_location_source"], "invoice_match")

    def test_several_locations_no_bill_or_an_unknown_location_change_nothing(self):
        for sid in ("S-SEVERAL", "S-NOBILL", "S-NOTSHOP"):
            before = self.row(sid)
            self.assertIsNone(invoice_location.refresh_statement_location(sid))
            self.assertEqual(self.row(sid), before, sid)

    def test_a_confident_mapping_is_never_overridden(self):
        before = self.row("S-CONFIDENT")
        self.assertIsNone(invoice_location.refresh_statement_location("S-CONFIDENT"))
        self.assertEqual(self.row("S-CONFIDENT"), before)

    def test_an_inactive_or_unmatched_bill_does_not_count(self):
        self.recon_set("S-CONFLICT", is_active=0)
        self.assertIsNone(invoice_location.refresh_statement_location("S-CONFLICT"))
        self.recon_set("S-CONFLICT", is_active=1, status="Amount mismatch")
        self.assertIsNone(invoice_location.refresh_statement_location("S-CONFLICT"))
        self.assertEqual(self.row("S-CONFLICT")["billing_location_source"], "conflict")

    def test_when_the_match_goes_the_row_is_mapped_again_from_its_text(self):
        invoice_location.refresh_statement_location("S-UNMAPPED")
        self.recon_set("S-UNMAPPED", is_active=0)
        invoice_location.refresh_statement_location("S-UNMAPPED")
        row = self.row("S-UNMAPPED")
        # "BERNATCHE AUTO BODY" is an alias of Bangor, so the text alone maps it now.
        self.assertEqual((row["billing_location"], row["billing_location_source"]), ("Bangor", "name_match"))
        invoice_location.refresh_statement_location("S-CONFLICT")
        self.recon_set("S-CONFLICT", is_active=0)
        invoice_location.refresh_statement_location("S-CONFLICT")
        self.assertEqual(self.row("S-CONFLICT")["billing_location_source"], "name_match")  # alias for Hewitt's

    def test_a_failure_is_swallowed_by_the_quiet_wrapper(self):
        with mock.patch.object(invoice_location, "refresh_statement_location", side_effect=RuntimeError("db down")):
            self.assertIsNone(invoice_location.refresh_quietly("S-CONFLICT"))


class FillScript(Database):
    def run_main(self, *args):
        with mock.patch.object(sys, "argv", ["fill", *args]), mock.patch("builtins.print"):
            fill.main()

    def test_a_dry_run_changes_nothing(self):
        self.run_main()
        self.assertEqual(self.row("S-CONFLICT")["billing_location_source"], "conflict")
        self.assertFalse(os.path.exists(self.backup))

    def test_apply_updates_only_the_fallback_rows_with_one_bill_shop(self):
        self.run_main("--apply", "--backup", self.backup)
        self.assertEqual(self.row("S-CONFLICT")["billing_location"], "Hewitt's")
        self.assertEqual(self.row("S-UNMAPPED")["billing_location"], "Bangor")
        # Highway 35's bill sits on an ambiguous Middletown row: it is a shop, so it is taken.
        self.assertEqual(self.row("S-AMBIGUOUS")["billing_location"], "Highway 35")
        for sid in ("S-SEVERAL", "S-NOBILL", "S-NOTSHOP", "S-CONFIDENT"):
            self.assertNotEqual(self.row(sid)["billing_location_source"], "invoice_match", sid)

    def test_running_it_again_finds_nothing_to_do(self):
        self.run_main("--apply", "--backup", self.backup)
        rows = fill.fallback_rows()
        plan, _ = fill.plan_updates(rows, invoice_location.bill_locations())
        self.assertEqual(plan, [])

    def test_undo_puts_the_old_values_back(self):
        before = {sid: self.row(sid) for sid in STATEMENTS}
        self.run_main("--apply", "--backup", self.backup)
        self.run_main("--undo", self.backup)
        for sid in STATEMENTS:
            self.assertEqual(self.row(sid), before[sid], sid)


if __name__ == "__main__":
    unittest.main()
