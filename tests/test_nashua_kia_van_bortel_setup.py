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
    # Prod STMT-60893176 (Neets Auto AR Statement.pdf): Document is the NetSuite tranid, 4 of 4 under Northeast Acura (203608). Running Balance left unmapped.
    "NORTHEAST_ACURA": {"Charges", "Date", "Description", "Document", "JR", "Pymts /Credits", "Remaining Balance"},
    # Prod STMT-0B412CA0: INVOICE NUMBER 294309AH is bill 294309AH (49.59) under Honda of Abington (111132).
    "ABINGTON_AUTO_PARTS_HONDA": {"AMOUNT DUE", "CHARGES", "CREDITS", "DATE", "INVOICE NUMBER", "UNLABELED_TRANSACTION_CODE"},
    # Prod STMT-827723E7: REFERENCE prints INW + tranid, 4 of 5 under DOUGLAS INFINITI (37992) after the INW strip.
    "DOUGLAS_INFINITI": {"BALANCE", "CHARGES", "CREDITS", "DATE", "REFERENCE", "SOURCE"},
    # Prod STMT-A943E6FC: invoice 1073438 is not in NetSuite yet; ROA is a payment on account.
    "ALLIANCE_AUTO_PARTS_INC.": {"Amount Due", "Charges", "Credits", "Date", "Description", "Invoice#", "UNLABELED_TRANSACTION_CODE"},
    # Prod STMT-8B29FD13 / STMT-140EE6A0: Transaction prints 'INV #100850. Due ... PO #...'; token_after 'INV #' gives the tranid (100850 = 102.95 under ECS Automotive Concepts 120405). Balance is a running balance, left unmapped.
    "ECS_AUTOMOTIVE_CONCEPTS_LLC.": {"Amount", "Date", "Transaction"},
    # Prod STMT-CBE085E0: Transaction# is the tranid, 9 of 9 under Tire Town (11089).
    "TIRE_TOWN_WHOLESALE": {"Due Date", "Transaction Amount", "Transaction Balance", "Transaction Date", "Transaction Description", "Transaction#"},
    # Prod STMT-B2E978DF: one amount column (BALANCE, per invoice); invoice numbers 20 of 26 under Mr. Glass (9151).
    "MR._GLASS_OF_LONG_ISLAND": {"BALANCE", "DATE", "INVOICE NUMBER / DESCRIPTION OF WORK"},
    # Prod STMT-283CA171: DOCUMENT / TRANSACTION is the tranid, 17 of 21 under Rallye Mercedes Benz (8740).
    "RALLYE_MOTORS": {"BALANCE", "DATE", "DOCUMENT / TRANSACTION", "PAYMENTS & CREDITS", "PURCHASES", "UNLABELED_TRANSACTION_CODE"},
    # Prod STMT-85EFE0B2: DOCUMENT / TRANSACTION is the tranid, 2 of 2 under BMW of Freeport (241025).
    "BMW_OF_FREEPORT": {"BALANCE", "DATE", "DOCUMENT / TRANSACTION", "PAYMENTS & CREDITS", "PURCHASES"},
    # Prod STMT-791877D6: same Reynolds layout as ROHRICH_TOYOTA; REFERENCE prints HOW + tranid, 17 of 20 under Rohrich Automotive Group (643941) after the strip.
    "ROHRICH_HONDA": {"BALANCE", "CHARGES", "CREDITS", "DATE", "REFERENCE", "SOURCE"},
    # Prod STMT-087A6C59: REFERENCE prints FOW / CMFOW + tranid (credits CMFOW), INVOICE the invoice a credit applies to; 39 of 42 under Van Bortel Ford (626536) after the strip.
    "VAN_BORTEL_FORD_INC.": {"AGE IN DAYS", "AMOUNT", "DATE", "DESCRIPTION", "INVOICE", "REFERENCE", "SOURCE"},
    # Prod STMT-B0674DCD: INVOICE NUMBER 132752A is bill 132752A (844.72) under Kia of Abington (159742).
    "ABINGTON_AUTO_PARTS_KIA": {"AMOUNT DUE", "CHARGES", "CREDITS", "DATE", "INVOICE NUMBER", "UNLABELED_TRANSACTION_CODE"},
}


# Layouts with one amount column (credits print as negative amounts, or there
# are none): no payment_amount to map.
SINGLE_AMOUNT_COLUMN = {"ECS_AUTOMOTIVE_CONCEPTS_LLC.", "TIRE_TOWN_WHOLESALE", "MR._GLASS_OF_LONG_ISLAND",
                        "VAN_BORTEL_FORD_INC."}


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
            needed = {"charge_amount"} if vendor in SINGLE_AMOUNT_COLUMN else {"charge_amount", "payment_amount"}
            self.assertTrue(needed <= canon, vendor)

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
    # Prod STMT-91096ABB (VIVE.pdf, 2026-11-09): no column headings, so the fields are unlabeled.
    "COLONIE_GARAGE_INC.": {"UNLABELED_TRANSACTION_CODE", "UNLABELED_TRANSACTION_CODE_2", "UNLABELED_TRANSACTION_CODE_3"},
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

    def test_colonie_garage_takes_the_number_after_invoice_number(self):
        with open(os.path.join(ROOT, "dbt", "vive_recon", "seeds", "vendor_normalization_rule.csv"),
                  encoding="utf-8", newline="") as f:
            rules = [r for r in csv.DictReader(f) if r["vendor_id"] == "COLONIE_GARAGE_INC." and r["is_active"] == "1"]
        self.assertEqual([(r["rule_type"], r["pattern"]) for r in rules], [("token_after", "Invoice Number")])


class TestAutoZoneEntities(unittest.TestCase):
    """AutoZone has five NetSuite vendor records (2026-11-09); its statements'
    bills are mostly under 181322, which the old 10661-only override missed."""

    def test_resolves_to_all_five_records(self):
        self.assertEqual(sorted(resolve_entity_ids("AUTOZONE", "AutoZone, Inc.")),
                         sorted(["10661", "19292", "38516", "136921", "181322"]))


if __name__ == "__main__":
    unittest.main()
