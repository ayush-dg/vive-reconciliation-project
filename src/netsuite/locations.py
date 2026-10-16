"""NetSuite location codes -> names (config/netsuite_locations.json).

NetSuite bills and credits carry a bare location code ("64"); this is what
turns it into the shop name NetSuite itself uses ("Lamon") for the
"Find in NetSuite" Shop filter and the results' details. The file is written
by scripts/sync_netsuite_locations.py (read-only against NetSuite).
"""
import json
import os
from functools import lru_cache

LOCATIONS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                              "config", "netsuite_locations.json")


@lru_cache(maxsize=1)
def _load() -> dict:
    try:
        with open(LOCATIONS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def location_names() -> dict:
    """{"64": "Lamon", ...} for every location, active or not (an old bill
    can still sit at an inactive one)."""
    return {code: info.get("name") or code for code, info in _load().items()}


def shop_options() -> list:
    """[{"code", "name"}] for the Shop filter: active locations, by name."""
    return sorted(({"code": code, "name": info.get("name") or code}
                   for code, info in _load().items() if not info.get("inactive")),
                  key=lambda o: o["name"].lower())


def known_codes(codes) -> list:
    """The codes that exist in the list, in the order given, without repeats
    -- anything else a request sends is dropped rather than queried."""
    names, seen = location_names(), set()
    out = []
    for code in codes:
        code = str(code).strip()
        if code in names and code not in seen:
            seen.add(code)
            out.append(code)
    return out
