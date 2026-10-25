"""
tests/test_silver_mapping_oct25.py

vendor_field_mapping.csv rows for Northeast Coffee Company and RL Auto Group
(Speedcraft Volkswagen) (2026-10-25): both statements failed on dev after
extraction with "No lines read: ... none matched the vendor's field mapping"
-- neither vendor had any mapping rows. The rows follow the columns the
other vendors with the same layouts use (BOWSER for Northeast's headerless
transaction code, BALD_HILL / SPEEDCRAFT for SRC / REF NO.). The field names
below are the ones the AI path stored for those statements; the values are
made up.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.lakehouse import silver_check
from src.lakehouse.field_names import normalize_field_name

CASES = {
    "NORTHEAST_COFFEE_COMPANY": [
        {"DATE": "08/04/2026", "UNLABELED_TRANSACTION_CODE": "INV", "DETAIL": "100001", "CHARGES": 120.0,
         "CREDITS": None, "BALANCE": 120.0},
        {"DATE": "08/11/2026", "UNLABELED_TRANSACTION_CODE": "INV", "DETAIL": "100002", "CHARGES": 80.0,
         "CREDITS": None, "BALANCE": 200.0},
        {"DATE": "08/20/2026", "UNLABELED_TRANSACTION_CODE": "PMT", "DETAIL": None, "CHARGES": None,
         "CREDITS": 120.0, "BALANCE": 80.0},
    ],
    "RL_AUTO_GROUP_INC_DBA_SPEEDCRAFT_VOLKSWAGEN": [
        {"DATE": "09/02/2026", "SRC": "PS", "REF NO.": "200001", "APPLY TO": "200001", "CHARGES": 55.0,
         "CREDITS": None, "BALANCE": 55.0},
        {"DATE": "09/09/2026", "SRC": "PS", "REF NO.": "200002", "APPLY TO": "200002", "CHARGES": 12.5,
         "CREDITS": None, "BALANCE": 67.5},
    ],
}
NEEDED = {"line_date", "original_invoice_number", "charge_amount", "payment_amount", "amount_remaining"}


class TestOct25MappingRows(unittest.TestCase):
    def setUp(self):
        silver_check._mapped_cache = None
        self.addCleanup(setattr, silver_check, "_mapped_cache", None)

    def _mapping(self, vendor_id):
        import csv
        with open(silver_check._SEED, newline="", encoding="utf-8") as f:
            return {normalize_field_name(r["raw_field_name"]): r["canonical_field_name"]
                    for r in csv.DictReader(f) if r["vendor_id"] == vendor_id}

    def test_every_stored_field_is_mapped(self):
        for vendor_id, rows in CASES.items():
            mapped = silver_check._mapped_names().get(vendor_id, set())
            fields = {k for r in rows for k in r}
            self.assertEqual({f for f in fields if normalize_field_name(f) not in mapped}, set(), vendor_id)
            self.assertTrue(NEEDED <= set(self._mapping(vendor_id).values()), vendor_id)

    def test_silver_check_passes_on_the_mapped_lines(self):
        for vendor_id, rows in CASES.items():
            mp = self._mapping(vendor_id)
            lines = with_invoice = with_amount = 0
            for r in rows:
                m = {mp[normalize_field_name(k)]: v for k, v in r.items()
                     if normalize_field_name(k) in mp and v not in (None, "")}
                lines += bool(m)
                with_invoice += bool(m.get("original_invoice_number"))
                with_amount += any(m.get(c) not in (None, "") for c in ("charge_amount", "payment_amount",
                                                                        "amount_remaining"))
            self.assertEqual(silver_check.describe_problem(0, 0, 0, len(rows)) is not None, True)
            self.assertIsNone(silver_check.describe_problem(lines, with_invoice, with_amount, len(rows)), vendor_id)


if __name__ == "__main__":
    unittest.main()
