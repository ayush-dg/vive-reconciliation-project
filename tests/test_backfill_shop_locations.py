"""
tests/test_backfill_shop_locations.py

scripts/backfill_shop_locations.py against a migrated SQLite database: it maps
old rows, leaves new and unmapped ones alone, can be re-run, and can be undone.
"""

import csv
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

spec = importlib.util.spec_from_file_location("backfill", os.path.join(ROOT, "scripts", "backfill_shop_locations.py"))
backfill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backfill)

ROWS = {  # statement_id: (shop_or_entity, billing_location, billing_location_source)
    "OLD-MAPS": (["VIVE COLLISION- RP BELL"], "MECHANIC FALLS ME", None),
    "OLD-CITY": ([], "Auburn, ME", "printed"),
    "OLD-UNMAPPED": (["Mystery Body Shop"], "Scarborough, ME", "shop_name_fallback"),
    "OLD-LOOKUP": (["Natick Collision"], "Natick, MA", "lookup_table"),
    "NEW-DONE": (["Coleman's Auto Body"], "Coleman's", "name_match"),
    "REDO-ALIAS": (["BERNATCHE AUTO BODY"], "BANGOR ME", "unmapped"),
    "REDO-CONFLICT": (["CARONS BODY SHOP DBA HEWITTS AUTO B"], "AUBURN, ME", "conflict"),
    "REDO-STILL": (["Mystery Body Shop"], "Scarborough, ME", "unmapped"),
}


class Backfill(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        apply_pending_migrations(conn)
        for n, (sid, (shop, location, source)) in enumerate(ROWS.items()):
            conn.execute("INSERT INTO document_intake_log (document_id, source_file, ingestion_timestamp, statement_id, "
                         "shop_or_entity, billing_location, billing_location_source, billing_location_extracted) "
                         "VALUES (?,?,?,?,?,?,?,?)",
                         [f"d{n}", f"{sid}.pdf", "2026-10-01", sid, json.dumps(shop), location, source,
                          location if source in ("unmapped", "conflict") else None])
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

    def run_main(self, *args):
        with mock.patch.object(sys, "argv", ["backfill", *args]), mock.patch("builtins.print"):
            backfill.main()

    def test_only_old_rows_are_selected(self):
        self.assertEqual({r["statement_id"] for r in backfill.old_rows()},
                         {"OLD-MAPS", "OLD-CITY", "OLD-UNMAPPED", "OLD-LOOKUP"})

    def test_a_dry_run_changes_nothing(self):
        self.run_main()
        self.assertEqual(self.row("OLD-MAPS")["billing_location"], "MECHANIC FALLS ME")
        self.assertIsNone(self.row("OLD-MAPS")["billing_location_extracted"])
        self.assertFalse(os.path.exists(self.backup))

    def test_apply_maps_the_old_rows(self):
        self.run_main("--apply", "--backup", self.backup)
        mapped = self.row("OLD-MAPS")
        self.assertEqual((mapped["billing_location"], mapped["billing_location_source"], mapped["billing_location_extracted"],
                          mapped["shop_city"], mapped["shop_state"]),
                         ("RP Bell", "name_match", "MECHANIC FALLS ME", "Saco", "ME"))
        by_city = self.row("OLD-CITY")
        self.assertEqual((by_city["billing_location"], by_city["billing_location_source"], by_city["shop_city"]),
                         ("Coleman's", "city_match", "Auburn"))

    def test_an_unmapped_row_keeps_its_raw_text(self):
        self.run_main("--apply", "--backup", self.backup)
        row = self.row("OLD-UNMAPPED")
        self.assertEqual((row["billing_location"], row["billing_location_source"], row["billing_location_extracted"],
                          row["shop_city"]), ("Scarborough, ME", "unmapped", "Scarborough, ME", None))

    def test_a_row_already_mapped_is_not_touched(self):
        before = self.row("NEW-DONE")
        self.run_main("--apply", "--backup", self.backup)
        self.assertEqual(self.row("NEW-DONE"), before)

    def test_running_it_again_finds_nothing_to_do(self):
        self.run_main("--apply", "--backup", self.backup)
        self.assertEqual([r for r in backfill.old_rows() if r["billing_location_source"] in (None, *backfill.OLD_SOURCES)], [])

    def test_undo_puts_the_old_values_back(self):
        before = {sid: self.row(sid) for sid in ROWS}
        self.run_main("--apply", "--backup", self.backup)
        self.run_main("--undo", self.backup)
        for sid in ROWS:
            after = self.row(sid)
            for column in ("billing_location", "billing_location_source", "billing_location_extracted", "shop_phone",
                           "shop_city", "shop_state"):
                self.assertEqual(after[column], before[sid][column], (sid, column))
        self.assertEqual(self.row("NEW-DONE"), before["NEW-DONE"])


    def test_redo_selects_only_the_rows_without_a_shop(self):
        self.assertEqual({r["statement_id"] for r in backfill.redo_rows()}, {"REDO-ALIAS", "REDO-CONFLICT", "REDO-STILL"})

    def test_a_redo_dry_run_changes_nothing(self):
        self.run_main("--redo")
        self.assertEqual(self.row("REDO-ALIAS")["billing_location_source"], "unmapped")
        self.assertFalse(os.path.exists(self.backup))

    def test_redo_maps_the_rows_that_now_map_and_leaves_the_rest(self):
        before = {sid: self.row(sid) for sid in ROWS}
        self.run_main("--redo", "--apply", "--backup", self.backup)
        alias = self.row("REDO-ALIAS")
        self.assertEqual((alias["billing_location"], alias["billing_location_source"], alias["billing_location_extracted"],
                          alias["shop_city"]), ("Bangor", "name_match", "BANGOR ME", "Bangor"))
        conflict = self.row("REDO-CONFLICT")
        self.assertEqual((conflict["billing_location"], conflict["billing_location_source"],
                          conflict["billing_location_extracted"]), ("Hewitt's", "name_match", "AUBURN, ME"))
        for sid in ("REDO-STILL", "OLD-MAPS", "NEW-DONE"):  # still unmapped / not a redo row
            self.assertEqual(self.row(sid), before[sid], sid)

    def test_redo_can_be_undone_and_run_again(self):
        before = {sid: self.row(sid) for sid in ROWS}
        self.run_main("--redo", "--apply", "--backup", self.backup)
        self.assertEqual(backfill.plan_updates(backfill.redo_rows(), only_mapped=True), [])
        self.run_main("--undo", self.backup)
        for sid in ("REDO-ALIAS", "REDO-CONFLICT", "REDO-STILL"):
            self.assertEqual(self.row(sid), before[sid], sid)

    def test_an_undo_of_a_backup_from_before_redo_existed_still_works(self):
        before = self.row("OLD-MAPS")
        self.run_main("--apply", "--backup", self.backup)
        with open(self.backup, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        with open(self.backup, "w", encoding="utf-8", newline="") as f:  # the old four-column format
            writer = csv.writer(f)
            writer.writerow(("id", "statement_id", "billing_location", "billing_location_source"))
            for row in rows:
                writer.writerow([row["id"], row["statement_id"], row["billing_location"], row["billing_location_source"]])
        self.run_main("--undo", self.backup)
        self.assertEqual(self.row("OLD-MAPS"), before)


if __name__ == "__main__":
    unittest.main()
