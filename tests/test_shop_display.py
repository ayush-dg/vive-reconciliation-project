"""
tests/test_shop_display.py

The Shop and Location the Statement Processing and Exceptions cards show and
filter by (web/shop_display.py): a mapped statement shows its NetSuite shop
name and the shop's "City, ST"; every other statement shows the raw extracted
text. Runs the real query functions against a migrated SQLite database.
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.lakehouse.migrations import apply_pending_migrations
from web import queries
from web.shop_display import SHOP_COLUMNS_TOKEN, display_shop, query_with_shop_columns, shop_and_location

MAPPED = {"shop_or_entity": json.dumps(["VIVE COLLISION- RP BELL"]), "billing_location": "RP Bell",
          "billing_location_source": "name_match", "shop_city": "Saco", "shop_state": "ME"}
UNMAPPED = {"shop_or_entity": json.dumps(["Mystery Body Shop"]), "billing_location": "Scarborough, ME",
            "billing_location_source": "unmapped", "shop_city": None, "shop_state": None}
LEGACY = {"shop_or_entity": json.dumps(["Ben's Autobody--Vive Collision"]), "billing_location": "Portsmouth NH",
          "billing_location_source": None, "shop_city": None, "shop_state": None}


class ShopAndLocation(unittest.TestCase):
    def test_a_mapped_statement_shows_the_shop_name_and_its_city_and_state(self):
        self.assertEqual(shop_and_location(MAPPED),
                         {"shop": "RP Bell", "billing_location": "Saco, ME", "shop_canonical": True})

    def test_every_mapped_source_counts(self):
        for source in ("name_match", "fuzzy_match", "phone_match", "street_match", "city_match"):
            with self.subTest(source=source):
                self.assertTrue(shop_and_location({**MAPPED, "billing_location_source": source})["shop_canonical"])

    def test_an_unmapped_statement_shows_the_raw_text(self):
        self.assertEqual(shop_and_location(UNMAPPED),
                         {"shop": "Mystery Body Shop", "billing_location": "Scarborough, ME", "shop_canonical": False})

    def test_a_statement_stored_before_the_mapping_shows_the_raw_text(self):
        self.assertEqual(shop_and_location(LEGACY),
                         {"shop": "Ben's Autobody--Vive Collision", "billing_location": "Portsmouth NH",
                          "shop_canonical": False})

    def test_ambiguous_and_conflict_are_not_mapped(self):
        for source in ("ambiguous", "conflict"):
            with self.subTest(source=source):
                self.assertFalse(shop_and_location({**UNMAPPED, "billing_location_source": source})["shop_canonical"])

    def test_a_mapped_shop_with_no_address_has_no_location(self):
        row = {**MAPPED, "billing_location": "Corporate", "shop_city": "", "shop_state": None}
        self.assertEqual(shop_and_location(row), {"shop": "Corporate", "billing_location": None, "shop_canonical": True})

    def test_no_intake_row(self):
        self.assertEqual(shop_and_location(None), {"shop": None, "billing_location": None, "shop_canonical": False})

    def test_a_malformed_shop_list_is_no_shop(self):
        self.assertIsNone(shop_and_location({**LEGACY, "shop_or_entity": "not json"})["shop"])


class DisplayShop(unittest.TestCase):
    def test_a_netsuite_name_keeps_its_casing(self):
        for name in ("RP Bell", "JC Auto", "NEK", "Coleman's", "J.A.S. Auto"):
            with self.subTest(name=name):
                self.assertEqual(display_shop({"shop": name, "shop_canonical": True}), name)

    def test_raw_text_is_title_cased(self):
        self.assertEqual(display_shop({"shop": "VIVE COLLISION- RP BELL", "shop_canonical": False}), "Vive Collision- Rp Bell")
        self.assertIsNone(display_shop({"shop": None, "shop_canonical": False}))


class QueriesUseIt(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        apply_pending_migrations(conn)
        for n, (sid, row) in enumerate((("STMT-M", MAPPED), ("STMT-U", UNMAPPED), ("STMT-L", LEGACY))):
            columns = {"document_id": f"d{n}", "source_file": f"{sid}.pdf", "ingestion_timestamp": f"2026-10-2{n}",
                       "statement_id": sid, "vendor_name": "V", "statement_period": "2026-10",
                       "validation_status": "matches", **row}
            conn.execute(f"INSERT INTO document_intake_log ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                         list(columns.values()))
        conn.commit()
        conn.close()
        self.addCleanup(os.remove, self.db)
        for patcher in (mock.patch("src.lakehouse.connection.DB_PATH", self.db),
                        mock.patch.dict(os.environ, {"AZURE_SQL_SERVER": ""})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_statement_processing_cards(self):
        shops = {r["statement_id"]: (r["shop"], r["shop_canonical"]) for r in queries.get_validation_report()}
        self.assertEqual(shops, {"STMT-M": ("RP Bell", True), "STMT-U": ("Mystery Body Shop", False),
                                 "STMT-L": ("Ben's Autobody--Vive Collision", False)})

    def test_the_review_header_shop(self):
        self.assertEqual(queries.get_statement_shop("STMT-M"), "RP Bell")
        self.assertEqual(queries.get_statement_shop("STMT-L"), "Ben's Autobody--Vive Collision")

    def test_the_exceptions_cards_shop_and_location(self):
        summary = [{"statement_id": sid, "vendor_name": "V", "total_invoice_count": 1, "matched_count": 1,
                    "exception_count": 0, "statement_total": 1.0, "overall_status": "RECONCILED",
                    "reconciliation_timestamp": None} for sid in ("STMT-M", "STMT-U", "STMT-L")]
        with mock.patch.object(queries, "recon_query", side_effect=[summary, []]), \
                mock.patch.object(queries, "_get_exceptions_only_vendors", return_value=[]), \
                mock.patch.object(queries, "_attach_aging_summaries"):
            runs = {r["statement_id"]: r for r in queries.get_exception_runs()}
        self.assertEqual((runs["STMT-M"]["shop"], runs["STMT-M"]["billing_location"], runs["STMT-M"]["shop_canonical"]),
                         ("RP Bell", "Saco, ME", True))
        self.assertEqual((runs["STMT-U"]["shop"], runs["STMT-U"]["billing_location"]), ("Mystery Body Shop", "Scarborough, ME"))
        self.assertEqual((runs["STMT-L"]["shop"], runs["STMT-L"]["billing_location"]),
                         ("Ben's Autobody--Vive Collision", "Portsmouth NH"))


class WithoutTheNewColumns(unittest.TestCase):
    """A database the schema migration has not reached yet: no billing_location_source,
    shop_city or shop_state. The pages fall back to the raw text instead of failing."""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE document_intake_log (id INTEGER PRIMARY KEY, statement_id TEXT, source_file TEXT, "
                     "vendor_name TEXT, statement_period TEXT, statement_total_as_printed REAL, validation_status TEXT, "
                     "validation_difference REAL, validation_method TEXT, ingestion_timestamp TEXT, shop_or_entity TEXT, "
                     "billing_location TEXT, original_filename TEXT)")
        conn.execute("INSERT INTO document_intake_log (statement_id, source_file, vendor_name, statement_period, "
                     "validation_status, ingestion_timestamp, shop_or_entity, billing_location) VALUES (?,?,?,?,?,?,?,?)",
                     ["STMT-L", "STMT-L.pdf", "V", "2026-10", "matches", "2026-10-01",
                      json.dumps(["Ben's Autobody--Vive Collision"]), "Portsmouth NH"])
        conn.commit()
        conn.close()
        self.addCleanup(os.remove, self.db)
        for patcher in (mock.patch("src.lakehouse.connection.DB_PATH", self.db),
                        mock.patch.dict(os.environ, {"AZURE_SQL_SERVER": ""})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_statement_processing_cards_show_the_raw_shop_and_warn(self):
        with self.assertLogs("web.shop_display", level="WARNING") as logs:
            rows = queries.get_validation_report()
        self.assertEqual([(r["shop"], r["shop_canonical"]) for r in rows], [("Ben's Autobody--Vive Collision", False)])
        self.assertIn("run the schema migration", logs.output[0])

    def test_the_review_header_shop(self):
        self.assertEqual(queries.get_statement_shop("STMT-L"), "Ben's Autobody--Vive Collision")

    def test_the_exceptions_cards_show_the_raw_shop_and_location(self):
        summary = [{"statement_id": "STMT-L", "vendor_name": "V", "total_invoice_count": 1, "matched_count": 1,
                    "exception_count": 0, "statement_total": 1.0, "overall_status": "RECONCILED",
                    "reconciliation_timestamp": None}]
        with mock.patch.object(queries, "recon_query", side_effect=[summary, []]),                 mock.patch.object(queries, "_get_exceptions_only_vendors", return_value=[]),                 mock.patch.object(queries, "_attach_aging_summaries"):
            run = queries.get_exception_runs()[0]
        self.assertEqual((run["shop"], run["billing_location"]), ("Ben's Autobody--Vive Collision", "Portsmouth NH"))


class QueryWithShopColumns(unittest.TestCase):
    SQL = f"SELECT {SHOP_COLUMNS_TOKEN} FROM document_intake_log"

    def test_tries_the_new_columns_first(self):
        seen = []
        query_with_shop_columns(lambda sql, params=None: seen.append(sql) or [], self.SQL)
        self.assertEqual(len(seen), 1)
        self.assertIn("shop_city", seen[0])
        self.assertNotIn(SHOP_COLUMNS_TOKEN, seen[0])

    def test_a_missing_column_error_retries_with_the_old_columns(self):
        for message in ("no such column: shop_city", "[42S22] Invalid column name 'shop_state'."):
            with self.subTest(message=message):
                seen = []

                def execute(sql, params=None):
                    seen.append(sql)
                    if "shop_city" in sql:
                        raise RuntimeError(message)
                    return ["ok"]
                with self.assertLogs("web.shop_display", level="WARNING"):
                    self.assertEqual(query_with_shop_columns(execute, self.SQL, [1]), ["ok"])
                self.assertEqual(len(seen), 2)
                self.assertNotIn("shop_city", seen[1])

    def test_any_other_error_is_raised(self):
        for message in ("no such table: document_intake_log", "connection timed out"):
            with self.subTest(message=message):
                def execute(sql, params=None):
                    raise RuntimeError(message)
                with self.assertRaises(RuntimeError):
                    query_with_shop_columns(execute, self.SQL)

    def test_parameters_are_passed_through(self):
        seen = []
        query_with_shop_columns(lambda sql, params=None: seen.append(params) or [], self.SQL, ["S1", "S2"])
        self.assertEqual(seen, [["S1", "S2"]])


if __name__ == "__main__":
    unittest.main()
