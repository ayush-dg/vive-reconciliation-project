"""Saves NetSuite's location list (code -> name) to config/netsuite_locations.json.

READ-ONLY against NetSuite: one SuiteQL SELECT, no writes. The Exceptions page's
"Find in NetSuite" Shop filter (2026-10-16) offers these names and filters
bronze.netsuite_vendorbill/vendorcredit.location by their codes -- Fabric's
NetSuite copy has the codes but no location table. Locations rarely change;
re-run this when one is added or renamed, then commit the file.

Run:  python scripts/sync_netsuite_locations.py
"""
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from src.netsuite.client import NetSuiteClient  # noqa: E402
from src.netsuite.locations import LOCATIONS_PATH  # noqa: E402


def main():
    rows = NetSuiteClient().suiteql("SELECT id, name, isinactive FROM location ORDER BY id")
    locations = {
        str(r["id"]): {"name": (r.get("name") or "").strip(), "inactive": r.get("isinactive") == "T"}
        for r in rows if r.get("id") is not None
    }
    with open(LOCATIONS_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(locations, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"{len(locations)} locations written to {LOCATIONS_PATH}")


if __name__ == "__main__":
    main()
