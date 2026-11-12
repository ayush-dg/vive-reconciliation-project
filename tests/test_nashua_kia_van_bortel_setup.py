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
    # Prod STMT-01105ED3 (UPPER VALLEY HONDA JASMIN 1026.pdf): CDK layout; DOCUMENT / TRANSACTION is the tranid (credits CM + number), 25 of 26 under Upper Valley Honda (486930).
    "UPPER_VALLEY_HONDA_(GHNH_INC._DBA_UPPER_VALLEY_HON": {"BALANCE", "DATE", "DOCUMENT / TRANSACTION", "PAYMENTS & CREDITS", "PURCHASES"},
    # Prod STMT-82437EF2 (MCGEES JASMIN 1026.pdf): DOCUMENT is the tranid, 33 of 35 under McGee Hyundai of Lebanon (677195); 'Last payment ... received' has no document or amount.
    "MCGEE_HYUNDAI_OF_LEBANON": {"AMOUNT", "DATE", "DESCRIPTION", "DOCUMENT"},
    # Prod STMT-17D00055 (Statement.pdf): same layout as 1800_RADIATOR; Ref# is the tranid, 4 of 4 under 1-800-Radiator (8214).
    "1-800-RADIATOR_OF_SYRACUSE": {"Amount", "Balance", "Date", "Description", "Item", "Ref#"},
    # Prod STMT-C336D048: Lithia Driveway layout; Reference/Invoice is the tranid as printed (165784X1 is its own bill), 30 of 31 under Subaru of Utica (379119). Purchase Location (the rooftop) is left unmapped.
    "LITHIA_DRIVEWAY_/_CARBONE_UTICA_SUBARU": {"Balance Due", "Date", "Purchase/Payments Amount", "Reference/Invoice", "Transaction Type"},
    # Prod STMT-2917E429: the same Carbone Utica Subaru account read with its '744-' rooftop prefix; 3 of 4 under Subaru of Utica (379119), the 4th is a payment (OP092926!).
    "LITHIA_DRIVEWAY_/_744-CARBONE_UTICA_SUBARU": {"Balance Due", "Date", "Purchase/Payments Amount", "Reference/Invoice", "Transaction Type"},
    # Prod STMT-887FF185: Lithia Driveway layout; 3 of 4 under BMW of Bloomfield (518013).
    "LITHIA_DRIVEWAY_/_710-BMW_OF_BLOOMFIELD": {"Balance Due", "Date", "Purchase/Payments Amount", "Reference/Invoice", "Transaction Type"},
    # Prod STMT-7E28AD08 (Mastrovito.pdf): same layout as TOWNE_AUTOMOTIVE_GROUP; REFERENCE # is the tranid, 7 of 7 under Mastrovito Hyundai (423136). COMPANY ID / JOURNAL ID left unmapped.
    "MASTROVITO_HYUNDAI": {"BALANCE DUE ($)", "DATE", "PAYMENTS & CREDITS ($)", "PURCHASES ($)", "REFERENCE #"},
    # Prod STMT-F20AC4CD (Matthews 11092026.pdf): another name for MATTHEWS_OF_SCHENECTADY_K_INC._/_MATTHEWS_KIA_OF_S; REFERENCE prints K1W + tranid, 5 of 5 under 383462 after the strip.
    "MATTHEWS_KIA_OF_SCHENECTADY": {"AGE IN DAYS", "AMOUNT", "DATE", "DESCRIPTION", "INVOICE", "REFERENCE", "SOURCE"},
}


# Layouts with one amount column (credits print as negative amounts, or there
# are none): no payment_amount to map.
SINGLE_AMOUNT_COLUMN = {"ECS_AUTOMOTIVE_CONCEPTS_LLC.", "TIRE_TOWN_WHOLESALE", "MR._GLASS_OF_LONG_ISLAND",
                        "MCGEE_HYUNDAI_OF_LEBANON", "1-800-RADIATOR_OF_SYRACUSE", "LITHIA_DRIVEWAY_/_CARBONE_UTICA_SUBARU",
                        "LITHIA_DRIVEWAY_/_744-CARBONE_UTICA_SUBARU", "LITHIA_DRIVEWAY_/_710-BMW_OF_BLOOMFIELD", "MATTHEWS_KIA_OF_SCHENECTADY",
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
