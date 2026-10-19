"""Alias "Fred Beans Rockland" -> FRED_BEANS_PARTS (2026-10-19).

Fred Beans Rockland (STMT-6A9842BA) is stored under the vendor name "Fred Beans  Rockland" -- taken from
its file name "Fred Beans- Rockland.pdf" because its Oct 1 extraction failed -- which resolved to no
vendor id, so per-vendor config (validation_invoice_balance.json, validation_total_columns.json, the field
mapping) never applied to it. TestOnlyThisNameChanges compares every vendor name in the saved replay data
(scratchpad/, git-ignored -- skipped where absent) with and without the new alias."""
import glob
import json
import os
import re
import unittest
from unittest import mock

import src.vendor_identity as vi

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUTS = os.path.join(REPO, "scratchpad", "saved_from_temp_20261019", "replay_inputs")
NEW_ALIAS = "Fred Beans Rockland"


class TestRocklandAlias(unittest.TestCase):

    def test_the_stored_rockland_name_resolves(self):
        for name in ("Fred Beans  Rockland", "Fred Beans Rockland", "FRED BEANS - ROCKLAND"):
            self.assertEqual(vi.resolve_vendor_id(name), "FRED_BEANS_PARTS", name)

    def test_existing_fred_beans_names_unchanged(self):
        for name in ("Fred Beans Parts", "Fred Beans Parts, Inc.", "Fred Beans Parts Inc."):
            self.assertEqual(vi.resolve_vendor_id(name), "FRED_BEANS_PARTS", name)

    def test_rockland_alone_is_not_fred_beans(self):
        self.assertNotEqual(vi.resolve_vendor_id("Rockland"), "FRED_BEANS_PARTS")
        self.assertNotEqual(vi.resolve_vendor_id("Rockland Opco LLC"), "FRED_BEANS_PARTS")


def saved_vendor_names():
    names = set()
    with open(os.path.join(INPUTS, "q10_rows.json"), encoding="utf-8") as f:
        names |= {st.get("vendor") for st in json.load(f).values()}
    for name in ("q52_data.json", "oct1_raw.json"):
        with open(os.path.join(INPUTS, name), encoding="utf-8") as f:
            names |= set(re.findall(r'"vendor_name": "([^"]{2,80})"', f.read()))
    for path in glob.glob(os.path.join(REPO, "scratchpad", "rerun_ai", "ai_extraction_*.json")):
        with open(path, encoding="utf-8") as f:
            names.add(json.load(f)["schema_result"]["vendor_metadata"].get("vendor_name"))
    names.discard(None)
    return names


@unittest.skipUnless(os.path.exists(os.path.join(INPUTS, "q10_rows.json")), "saved replay data not present")
class TestOnlyThisNameChanges(unittest.TestCase):

    def resolve_all(self, names, raw):
        vi._lookup_cache = None
        try:
            with mock.patch.object(vi.json, "load", lambda f: raw):
                return {n: vi.resolve_vendor_id(n) for n in names}
        finally:
            vi._lookup_cache = None

    def test_over_all_saved_vendor_names_only_the_rockland_record_changes(self):
        with open(vi.CONFIG_PATH, encoding="utf-8") as f:
            with_alias = json.load(f)
        without = {k: [a for a in v if a != NEW_ALIAS] for k, v in with_alias.items()}
        names = saved_vendor_names()
        self.assertGreaterEqual(len(names), 218)
        before, after = self.resolve_all(names, without), self.resolve_all(names, with_alias)
        changed = {n: (before[n], after[n]) for n in names if before[n] != after[n]}
        self.assertEqual(changed, {"Fred Beans  Rockland": (None, "FRED_BEANS_PARTS")})


if __name__ == "__main__":
    unittest.main()
