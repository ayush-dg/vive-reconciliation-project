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



# Prod 2026-11-09 "No lines read" failures, each a layout already mapped for
# another dealer (Rohrich Cadillac timed out before extraction; mapped as
# Rohrich Toyota, its sister store). The INVOICE / AGE IN DAYS layout has one
# AMOUNT column, so no payment_amount.
NEW_2026_11_09 = {
    "LEXUS_OF_BEDFORD": {"BALANCE", "DATE", "DOCUMENT / TRANSACTION", "PAYMENTS & CREDITS", "PURCHASES"},
    "MARTIN_NEMER_VOLKSWAGEN_CORP": {"BALANCE", "DATE", "DOCUMENT / TRANSACTION", "PAYMENTS & CREDITS", "PURCHASES"},
    "KEELER_UPSTATE_DEALERSHIP_HOLDINGS_LLC": {"BALANCE", "DATE", "DOCUMENT / TRANSACTION", "PAYMENTS & CREDITS",
                                               "PURCHASES"},
    "ROHRICH_TOYOTA": {"BALANCE", "CHARGES", "CREDITS", "DATE", "REFERENCE", "SOURCE"},
    "ROHRICH_CADILLAC": {"BALANCE", "CHARGES", "CREDITS", "DATE", "REFERENCE", "SOURCE"},
    "SHULTS_FORD_LINCOLN": {"BALANCE", "CHARGES", "CREDITS", "DATE", "REFERENCE", "SOURCE"},
    "MATTHEWS_OF_SCHENECTADY_K_INC._/_MATTHEWS_KIA_OF_S": {"AGE IN DAYS", "AMOUNT", "DATE", "DESCRIPTION", "INVOICE",
                                                          "REFERENCE", "SOURCE"},
    "DENOOYER": {"AGE IN DAYS", "AMOUNT", "DATE", "DESCRIPTION", "INVOICE", "REFERENCE", "SOURCE"},
}


class TestNov9Mappings(unittest.TestCase):
    def test_every_extracted_field_is_mapped(self):
        for vendor, fields in NEW_2026_11_09.items():
            self.assertEqual(set(_mapping(vendor)), fields, vendor)

    def test_invoice_number_and_charges_are_mapped(self):
        for vendor in NEW_2026_11_09:
            canon = set(_mapping(vendor).values())
            self.assertIn("original_invoice_number", canon, vendor)
            self.assertIn("charge_amount", canon, vendor)


class TestNov9Entities(unittest.TestCase):
    """NetSuite vendors traced from the prod statements' invoice numbers (2026-11-10)."""

    def test_overrides(self):
        self.assertEqual(resolve_entity_ids("MARTIN_NEMER_VOLKSWAGEN_CORP", "Martin Nemer Volkswagen Corp"), ["187347"])
        self.assertEqual(resolve_entity_ids("ROHRICH_TOYOTA", "Rohrich Toyota"), ["643941", "638095"])
        self.assertEqual(resolve_entity_ids("MATTHEWS_OF_SCHENECTADY_K_INC._/_MATTHEWS_KIA_OF_S", "Matthews"),
                         ["383462"])

    def test_reynolds_prefixes_are_stripped(self):
        with open(os.path.join(ROOT, "dbt", "vive_recon", "seeds", "vendor_normalization_rule.csv"),
                  encoding="utf-8", newline="") as f:
            rules = {(r["vendor_id"], r["prefix_pattern"]): (r["pattern"], r["reconstruct_template"])
                     for r in csv.DictReader(f) if r["is_active"] == "1"}
        self.assertEqual(rules[("ROHRICH_TOYOTA", "TOW")], ("3", ""))
        self.assertEqual(rules[("ROHRICH_TOYOTA", "CMTOW")], ("5", "CM{invoice}"))
        self.assertEqual(rules[("SHULTS_FORD_LINCOLN", "FOW")], ("3", ""))
        self.assertEqual(rules[("SHULTS_FORD_LINCOLN", "CMFOW")], ("5", "CM{invoice}"))
        self.assertEqual(rules[("MATTHEWS_OF_SCHENECTADY_K_INC._/_MATTHEWS_KIA_OF_S", "K1W")], ("3", ""))
        self.assertEqual(rules[("DENOOYER", "CVW")], ("3", ""))


class TestAutoZoneEntities(unittest.TestCase):
    """AutoZone has five NetSuite vendor records (2026-11-09); its statements'
    bills are mostly under 181322, which the old 10661-only override missed."""

    def test_resolves_to_all_five_records(self):
        self.assertEqual(sorted(resolve_entity_ids("AUTOZONE", "AutoZone, Inc.")),
                         sorted(["10661", "19292", "38516", "136921", "181322"]))


if __name__ == "__main__":
    unittest.main()
