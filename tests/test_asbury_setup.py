"""
tests/test_asbury_setup.py

Asbury Automotive Group's statement (HEBWorc0926.pdf, Tekion layout) failed
the Silver build on 2026-10-16 with "none matched ASBURY_AUTOMOTIVE_GROUP's
field mapping": the vendor had no mapping rows at all, so every extracted
field counted as unmapped. These tests keep the three config pieces that make
the vendor work in place. Reads the real config and seed files.
"""

import csv
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.matching.netsuite_vendor_resolver import resolve_entity_ids
from src.vendor_identity import resolve_vendor_id

ROOT = os.path.join(os.path.dirname(__file__), "..")
VENDOR = "ASBURY_AUTOMOTIVE_GROUP"

# The fields the extractor produced for the Oct 16 statement (from the job's
# "Unmapped fields" message). '#' is the row number and 'section' the
# franchise heading; neither feeds a canonical field.
EXTRACTED = {"#", "Balance", "Invoice Date", "Invoice#", "PO Number", "Payments", "Purchases", "section"}
DELIBERATELY_UNMAPPED = {"#", "section"}


def _mapping_rows():
    path = os.path.join(ROOT, "dbt", "vive_recon", "seeds", "vendor_field_mapping.csv")
    with open(path, encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f) if r["vendor_id"] == VENDOR]


class TestAsburyAliases(unittest.TestCase):
    def test_the_letterhead_and_payee_names_resolve_to_the_vendor(self):
        for name in ("Asbury Automotive Group", "ASBURY AUTOMOTIVE GROUP", "Asbury Automotive Management",
                     "Asbury Automotive Management L.L.C", "Asbury Automotive Management LLC"):
            with self.subTest(name=name):
                self.assertEqual(resolve_vendor_id(name), VENDOR)


class TestAsburyMapping(unittest.TestCase):
    def test_every_field_the_extractor_produced_is_mapped_or_deliberately_left_out(self):
        mapped = {r["raw_field_name"] for r in _mapping_rows()}
        self.assertEqual(EXTRACTED - mapped, DELIBERATELY_UNMAPPED)

    def test_the_core_fields_map_to_the_canonical_names_other_tekion_vendors_use(self):
        got = {r["raw_field_name"]: r["canonical_field_name"] for r in _mapping_rows()}
        self.assertEqual(got["Invoice#"], "original_invoice_number")
        self.assertEqual(got["Invoice Date"], "line_date")
        self.assertEqual(got["Purchases"], "charge_amount")
        self.assertEqual(got["Payments"], "payment_amount")
        self.assertEqual(got["Balance"], "amount_remaining")
        self.assertEqual(got["PO Number"], "po_number")

    def test_each_row_has_the_version_and_priority_the_silver_model_expects(self):
        for row in _mapping_rows():
            with self.subTest(field=row["raw_field_name"]):
                self.assertEqual((row["mapping_config_version"], row["mapping_priority"]), ("v1", "1"))

    def test_the_seed_has_no_duplicate_rows_for_the_vendor(self):
        fields = [r["raw_field_name"] for r in _mapping_rows()]
        self.assertEqual(len(fields), len(set(fields)))


class TestAsburyNetSuiteEntity(unittest.TestCase):
    def test_the_override_points_at_jaguar_land_rover_sudbury(self):
        with open(os.path.join(ROOT, "config", "netsuite_entity_overrides.json"), encoding="utf-8") as f:
            entry = json.load(f)[VENDOR]
        self.assertEqual(entry["entity_ids"], ["203119"])
        self.assertIn("Land Rover Sudbury", entry["note"])

    def test_the_matcher_resolves_the_vendor_from_the_override_without_a_name_lookup(self):
        self.assertEqual([str(e) for e in resolve_entity_ids(VENDOR, "Asbury Automotive Group")], ["203119"])


if __name__ == "__main__":
    unittest.main()
