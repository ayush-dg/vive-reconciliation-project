"""
tests/test_nashua_kia_van_bortel_setup.py

Two prod statements failed the Silver check on 2026-11-04 with "none matched
<vendor>'s field mapping": Nashua Kia (STMT-0EF51F90, the CDK layout Lia Auto
Group uses) and Van Bortel Motorcar, Inc. (STMT-EDF47B44, the REF NO. / APPLY
TO / SRC layout of Cherry Hill Triplex). Each listed field must be mapped, and
Van Bortel must resolve to Van Bortel Subaru of Victor (600978) only -- the
first-word lookup matched every NetSuite vendor starting "Van".
"""
import csv
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.matching.netsuite_vendor_resolver import resolve_entity_ids

ROOT = os.path.join(os.path.dirname(__file__), "..")

# The "Unmapped fields" each job reported.
EXTRACTED = {
    "NASHUA_KIA": {"BALANCE", "DATE", "DOCUMENT / TRANSACTION", "PAYMENTS & CREDITS", "PURCHASES"},
    "VAN_BORTEL_MOTORCAR_INC.": {"APPLY TO", "BALANCE", "CHARGES", "CREDITS", "DATE", "REF NO.", "SRC"},
    # Prod STMT-B96528F5 (80 Subaru Jasmin.pdf, 2026-11-05); resolves to 802 Subaru (496284) by name.
    "802_SUBARU": {"APPLY TO", "BALANCE", "CHARGES", "CREDITS", "DATE", "REF NO.", "SRC"},
    # Dev STMT-2F0ADBE9 (2026-11-04); resolves to Artioli Dodge Inc. (3997) by name.
    "ARTIOLI_DODGE": {"APPLY TO", "BALANCE", "CHARGES", "CREDITS", "DATE", "REF NO.", "SRC"},
    # Prod STMT-1C33163B / -697847A1 / -3106CCA6 (2026-11-05). JOURNAL ID and COMPANY ID are
    # internal codes (36; 12/13) and are deliberately left unmapped.
    "TOWNE_AUTOMOTIVE_GROUP": {"BALANCE DUE ($)", "DATE", "PAYMENTS & CREDITS ($)", "PURCHASES ($)", "REFERENCE #"},
    # Prod STMT-ADEF9707 (0_6ae898dc0e494.pdf, 2026-11-02); resolves to Elite Auto Glass Solutions LLC
    # (635711) by name. Transaction is the NetSuite bill number (43 of 48 charge rows); Reference is an
    # RO/claim number that repeats across invoices; Account (the shop name) is left unmapped.
    "ELITE_AUTO_GLASS_SOLUTIONS_LLC": {"Balance", "Date", "Invoiced", "Paid", "Reference", "Transaction"},
    # Prod STMT-517258E4 (AR Statement_94097_2026_OCT_Tekion.pdf, Vestal, 2026-11). The Tekion layout,
    # mapped as Casco Bay Ford / Asbury; '#' (a row counter) and 'section' are left unmapped.
    "MERCEDES-BENZ_OF_BUFFALO": {"Balance", "Invoice Date", "Invoice#", "PO Number", "Payments", "Purchases"},
}


def _mapping(vendor):
    with open(os.path.join(ROOT, "dbt", "vive_recon", "seeds", "vendor_field_mapping.csv"),
              encoding="utf-8", newline="") as f:
        return {r["raw_field_name"]: r["canonical_field_name"] for r in csv.DictReader(f) if r["vendor_id"] == vendor}


class TestMappings(unittest.TestCase):
    def test_every_extracted_field_is_mapped(self):
        for vendor, fields in EXTRACTED.items():
            self.assertEqual(set(_mapping(vendor)), fields, vendor)

    def test_invoice_number_and_amounts_are_mapped(self):
        for vendor in EXTRACTED:
            canon = set(_mapping(vendor).values())
            self.assertIn("original_invoice_number", canon, vendor)
            self.assertTrue({"charge_amount", "payment_amount"} <= canon, vendor)

    def test_van_bortel_credits_point_at_their_invoice(self):
        m = _mapping("VAN_BORTEL_MOTORCAR_INC.")
        self.assertEqual((m["REF NO."], m["APPLY TO"], m["SRC"]),
                         ("original_invoice_number", "invoice_number_ref", "transaction_code"))


class TestVanBortelEntity(unittest.TestCase):
    def test_resolves_to_van_bortel_subaru_only(self):
        self.assertEqual(resolve_entity_ids("VAN_BORTEL_MOTORCAR_INC.", "Van Bortel Motorcar, Inc."), ["600978"])


if __name__ == "__main__":
    unittest.main()
