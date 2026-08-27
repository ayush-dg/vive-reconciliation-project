"""
shop_owners.py

vendor_id -> shop owner routing for gold_exceptions.shop_owner (see
config/shop_owners.json, migrations/009_add_routing_aging.sql). Called
by every gold_exceptions write site (src/matching/engine.py's
run_matching(), notebooks/01_document_intake.py's write_skip_exception(),
web/queries.py's action_review_item()) so a new exception always gets a
shop_owner looked up at write time, not backfilled later.

config/shop_owners.json is a placeholder mapping -- VIVE will provide the
real vendor_id -> shop owner mapping later. Most vendor_ids won't be in
it yet, which is expected: get_shop_owner() returns None for any miss,
same as for a missing/empty vendor_id.
"""

import json
import os

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "shop_owners.json"
)

_cache = None


def _load_shop_owners() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(CONFIG_PATH, "r") as f:
                _cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _cache = {}
    return _cache


def get_shop_owner(vendor_id) -> str:
    """Returns a "Name <email>" display string for vendor_id, or None if
    vendor_id is falsy or isn't in config/shop_owners.json."""
    if not vendor_id:
        return None
    entry = _load_shop_owners().get(vendor_id)
    if not entry:
        return None
    name = entry.get("name")
    email = entry.get("email")
    if name and email:
        return f"{name} <{email}>"
    return name or email or None
