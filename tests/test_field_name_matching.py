"""
tests/test_field_name_matching.py

Extracted field names are compared with vendor_field_mapping case- and
punctuation-insensitively (src/lakehouse/field_names.py in Python,
dbt/vive_recon/macros/normalize_field_name.sql in the Silver build). These
tests pin the spellings that failed prod jobs on 2026-10-14 and keep the
SQL macro and the Python rule stripping the same characters.
"""

import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import jinja2

from src.lakehouse import silver_check
from src.lakehouse.field_names import FIELD_NAME_STRIP_CHARS, normalize_field_name

MACRO = os.path.join(os.path.dirname(__file__), "..", "dbt", "vive_recon", "macros", "normalize_field_name.sql")


class TestNormalizeFieldName(unittest.TestCase):

    def test_spellings_seen_in_prod_compare_equal(self):
        for a, b in (("DOCUMENT/TRANSACTION", "DOCUMENT / TRANSACTION"),     # Lexus of Edison
                     ("Reference Number", "reference_number"),              # Keystone, Claude vs parser
                     ("Balance Due", "balance_due"),
                     ("Invoice Number", "INVOICE NUMBER"),                  # Sullivan Tire
                     ("REF NO.", "Ref No"), ("Call #", "CALL#"), ("PAYMENTS & CREDITS", "Payments&Credits")):
            with self.subTest(a=a, b=b):
                self.assertEqual(normalize_field_name(a), normalize_field_name(b))

    def test_different_columns_stay_different(self):
        self.assertNotEqual(normalize_field_name("Invoice Number"), normalize_field_name("Invoice Amount"))
        self.assertNotEqual(normalize_field_name("UNLABELED_TRANSACTION_CODE"), normalize_field_name("UNLABELED_TRANSACTION_CODE_2"))

    def test_blank(self):
        self.assertEqual(normalize_field_name(None), "")


class TestMacroMatchesPython(unittest.TestCase):

    def _render(self, col):
        with open(MACRO, encoding="utf-8") as f:
            src = f.read()
        return jinja2.Environment(extensions=["jinja2.ext.do"]).from_string(
            src + "{{ normalize_field_name('" + col + "') }}").render().strip()

    def test_macro_strips_the_same_characters(self):
        sql = self._render("f.raw_field_name")
        self.assertTrue(sql.startswith("replace("), sql)
        self.assertIn("lower(f.raw_field_name)", sql)
        stripped = re.findall(r", '((?:''|[^'])+)', ''\)", sql)
        self.assertEqual([c.replace("''", "'") for c in stripped], list(FIELD_NAME_STRIP_CHARS))


class TestSilverCheckUsesNormalizedNames(unittest.TestCase):

    def test_claude_spelling_of_mapped_parser_field_is_not_reported_unmapped(self):
        cur = mock.Mock()
        cur.fetchall.return_value = [("Reference Number",), ("Balance Due",), ("Brand New Column",), ("confidence",)]
        conn = mock.Mock(); conn.cursor.return_value = cur
        with mock.patch.object(silver_check, "_mapped_names",
                               return_value={"KEYSTONE": {normalize_field_name("reference_number"), normalize_field_name("balance_due")}}), \
                mock.patch("src.lakehouse.fabric_sql.get_lakehouse_connection", return_value=conn):
            self.assertEqual(silver_check._unmapped_fields("STMT-1", "KEYSTONE"), ["Brand New Column"])


if __name__ == "__main__":
    unittest.main()
