"""
location_lookup.py

Three-tier fallback for billing_location, used when extraction (either
path) didn't find a printed customer address on the document itself
(see this session's investigation: some vendor templates -- e.g. the
lowercase-"nucar"/Reynolds & Reynolds statements -- never print a
separate customer city/state at all, only the shop name). Each tier is
progressively less trustworthy than the last, so the SOURCE of a
result is tracked alongside it (resolve_billing_location()'s second
return value) rather than ever being silently indistinguishable from a
genuinely printed address.
"""

import re
from typing import Optional

# 38 confirmed real shop-name-keyword -> "City, State" mappings, built
# from this session's real-file investigation (final_results_117.json /
# batch_fields_results.jsonl) -- not guessed or invented.
SHOP_LOCATION_LOOKUP = {
    "Cherry Hill": "Cherry Hill, NJ",
    "Lyndhurst": "Lyndhurst, NJ",
    "Nutley": "Nutley, NJ",
    "Owego": "Owego, NY",
    "Bristol": "Bristol, RI",
    "Middletown": "Middletown, RI",
    "Pawtucket": "Pawtucket, RI",
    "Watertown": "Watertown, MA",
    "Worcester": "Worcester, MA",
    "Natick": "Natick, MA",
    "Springfield": "Springfield, MA",
    "Holyoke": "Holyoke, MA",
    "Klapec": "Cranberry, PA",
    "Clarks Summit": "Clarks Summit, PA",
    "Clark's": "Clarks Summit, PA",
    "Montoursville": "Montoursville, PA",
    "Duncansville": "Duncansville, PA",
    "Keene": "Keene, NH",
    "Ben's": "Portsmouth, NH",
    "Vestal": "Vestal, NY",
    "Binghamton": "Binghamton, NY",
    "Quonset": "North Kingstown, RI",
    "Harbour": "Portland, ME",
    "JC Auto": "Veazie, ME",
    "Maurice & Son": "Waterville, ME",
    "Seacoast": "Brunswick, ME",
    "Newington": "Newington, CT",
    "Rotunda": "Essex Junction, VT",
    "Xtreme": "Morristown, VT",
    "J.A.S. Auto": "White River Junction, VT",
    "Crossroads": "Manchester, NH",
    "Collex": "Shrewsbury, NJ",
    "Modern": "South Orange, NJ",
    "Collision Restoration": "Fairfield, NJ",
    "Thru It All": "Mount Joy, PA",
    "Lee's": "Avenel, NJ",
    "Evolve": "New Castle, DE",
    "Acme": "Northampton, MA",
}

_BRAND_PREFIX_RE = re.compile(r"^\s*(VIVE COLLISION\s*-?\s*|EVOLVE\s*-\s*)", re.IGNORECASE)
_PARENTHETICAL_CODE_RE = re.compile(r"\s*\([A-Za-z0-9]+\)\s*")


def _shop_text(shop_or_entity) -> Optional[str]:
    """Normalizes the list-shaped shop_or_entity format this codebase
    uses (see adapter.py / claude_sonnet_client.py's vendor_metadata)
    into a single string, or returns None if empty."""
    if isinstance(shop_or_entity, list):
        shop_or_entity = shop_or_entity[0] if shop_or_entity else None
    if not shop_or_entity:
        return None
    return str(shop_or_entity)


def lookup_location_by_shop_keyword(shop_or_entity) -> Optional[str]:
    """Tier 2: case-insensitive substring match of shop_or_entity against
    SHOP_LOCATION_LOOKUP's keywords. Returns the first match's "City,
    State" value, or None if no keyword matches."""
    text = _shop_text(shop_or_entity)
    if not text:
        return None
    text_lower = text.lower()
    for keyword, location in SHOP_LOCATION_LOOKUP.items():
        if keyword.lower() in text_lower:
            return location
    return None


def guess_location_from_shop_name(shop_or_entity) -> Optional[str]:
    """Tier 3 (last resort): strips known brand prefixes, trailing
    parenthetical codes (e.g. "(W60)"), and the duplicated/truncated
    repeated-text pattern already observed in Fred Beans shop names
    (e.g. "VIVE COLLISION - CHERRY HILL (W60) VIVE COLLISION - CHERR" --
    the text repeats itself, truncated, so only the first clean
    occurrence before the repeat starts is kept). This is explicitly a
    low-confidence business-name fragment, not a verified city/state --
    returned as-is, not formatted like a "City, State" pair."""
    text = _shop_text(shop_or_entity)
    if not text:
        return None

    text = _PARENTHETICAL_CODE_RE.sub(" ", text).strip()
    text = _BRAND_PREFIX_RE.sub("", text).strip()

    # Duplicated/truncated repeat: if the brand prefix (or the cleaned
    # text's own start) reappears later in the string, only the first
    # occurrence is real content -- everything from the second
    # occurrence onward is the same statement's truncated repeat.
    match = re.search(r"(VIVE COLLISION|EVOLVE)", text, re.IGNORECASE)
    if match and match.start() > 0:
        text = text[:match.start()].strip()

    text = text.strip(" -")
    return text or None


def resolve_billing_location(printed_location, shop_or_entity):
    """Three-tier fallback: (1) a genuinely printed address always wins,
    (2) a confirmed real shop-keyword lookup, (3) a low-confidence guess
    parsed out of the shop name itself. Returns (location, source) where
    source is "printed" / "lookup_table" / "shop_name_fallback" / None --
    never leaves the caller unable to tell tier 1 from tiers 2-3."""
    if printed_location:
        return printed_location, "printed"

    looked_up = lookup_location_by_shop_keyword(shop_or_entity)
    if looked_up:
        return looked_up, "lookup_table"

    guessed = guess_location_from_shop_name(shop_or_entity)
    if guessed:
        return guessed, "shop_name_fallback"

    return None, None
