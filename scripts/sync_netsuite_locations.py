"""Saves NetSuite's location list to config/netsuite_locations.json:
code -> name, inactive flag, and the location's main address (street, city,
state, zip) and phone.

READ-ONLY against NetSuite: SuiteQL SELECTs, no writes. The Exceptions page's
"Find in NetSuite" Shop filter (2026-10-16) offers these names and filters
bronze.netsuite_vendorbill/vendorcredit.location by their codes -- Fabric's
NetSuite copy has the codes but no location table. The address and phone are
what src/validation/shop_list.py maps a statement's customer location onto
(by name, street, city or phone). Locations rarely change; re-run this when one
is added, renamed or moved, then commit the file.

A location with no main address gets no street/city/state/zip/phone keys'
values (empty strings), and still keeps its name.

Run:  python scripts/sync_netsuite_locations.py              (writes the config file)
      python scripts/sync_netsuite_locations.py --out PATH   (writes PATH instead, e.g. to compare first)
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

QUERY = (
    "SELECT l.id, l.name, l.isinactive, a.addr1, a.city, a.state, a.zip, a.addrphone "
    "FROM location l LEFT JOIN locationMainAddress a ON a.nkey = l.mainaddress ORDER BY l.id"
)


def _text(value) -> str:
    return (value or "").strip()


def location_entry(row: dict) -> dict:
    return {
        "name": _text(row.get("name")),
        "inactive": row.get("isinactive") == "T",
        "street": _text(row.get("addr1")),
        "city": _text(row.get("city")),
        "state": _text(row.get("state")),
        "zip": _text(row.get("zip")),
        "phone": _text(row.get("addrphone")),
    }


def main():
    out_path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else LOCATIONS_PATH
    rows = NetSuiteClient().suiteql(QUERY)
    locations = {str(r["id"]): location_entry(r) for r in rows if r.get("id") is not None}
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(locations, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with_address = sum(1 for e in locations.values() if e["city"])
    print(f"{len(locations)} locations ({with_address} with an address) written to {out_path}")


if __name__ == "__main__":
    main()
