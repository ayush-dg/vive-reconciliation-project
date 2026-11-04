"""VIVE shop list with lookups by name, phone, city and street.

The shops come from NetSuite's location list (config/netsuite_locations.json,
written by scripts/sync_netsuite_locations.py: name, street, city, state, zip,
phone). Until that file carries addresses -- it is read-only data refreshed
by hand -- config/vive_shops.json (scripts/build_vive_shops.py, from the VIVE
shop list sheet: name, phone, city, state; no street) is used instead.

config/location_mapping.json holds what NetSuite cannot say: locations that are
not shops ("excluded") and other names a statement uses for a shop
("aliases", keyed by the shop's name, e.g. "M3 Collision" for Highway 35).

src/validation/location_lookup.py uses these lookups to map an extracted
customer location onto a shop's canonical name. A phone belongs to one shop;
a city can belong to several (Bangor, Manchester, ...), so by_city() returns a
list.
"""
import json
import os
import re
from functools import lru_cache
from typing import Optional

_CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config")
SHOPS_PATH = os.path.join(_CONFIG_DIR, "vive_shops.json")
NETSUITE_LOCATIONS_PATH = os.path.join(_CONFIG_DIR, "netsuite_locations.json")
MAPPING_PATH = os.path.join(_CONFIG_DIR, "location_mapping.json")

# The columns a statement's location is stored in, wherever it is stored
# (document_intake_log, bronze.raw_statement, silver.statement): what
# extraction returned, the mapped shop name, and that shop's details.
LOCATION_COLUMNS = ("billing_location_extracted", "billing_location", "shop_phone", "shop_city", "shop_state")

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

# Words a statement abbreviates in a city name ("W Hartford", "Mt Holly").
_PLACE_WORDS = {"w": "west", "n": "north", "s": "south", "e": "east", "mt": "mount"}
# Words a statement adds to a city name that NetSuite leaves out ("Mt Laurel Twp").
_PLACE_SUFFIXES = {"township", "twp"}

_STATE_ABBREVIATIONS = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar", "california": "ca", "colorado": "co",
    "connecticut": "ct", "delaware": "de", "florida": "fl", "georgia": "ga", "hawaii": "hi", "idaho": "id",
    "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks", "kentucky": "ky", "louisiana": "la",
    "maine": "me", "maryland": "md", "massachusetts": "ma", "michigan": "mi", "minnesota": "mn",
    "mississippi": "ms", "missouri": "mo", "montana": "mt", "nebraska": "ne", "nevada": "nv",
    "new hampshire": "nh", "new jersey": "nj", "new mexico": "nm", "new york": "ny", "north carolina": "nc",
    "north dakota": "nd", "ohio": "oh", "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa",
    "rhode island": "ri", "south carolina": "sc", "south dakota": "sd", "tennessee": "tn", "texas": "tx",
    "utah": "ut", "vermont": "vt", "virginia": "va", "washington": "wa", "west virginia": "wv",
    "wisconsin": "wi", "wyoming": "wy", "district of columbia": "dc",
}


def normalize_text(text) -> str:
    """Lowercase letters and digits only, words separated by single spaces,
    "&" read as "and" -- "Coleman's" and "COLEMANS" compare equal, and so do
    "Maurice & Son" and "Maurice and Son"."""
    return _NON_ALNUM_RE.sub(" ", str(text or "").lower().replace("'", "").replace("&", " and ")).strip()


def normalize_place(text) -> str:
    """normalize_text() with the abbreviated place words spelled out and a
    trailing "Township" dropped: "W Hartford" and "West Hartford" compare
    equal, and so do "Mt Laurel Twp" and "Mount Laurel"."""
    words = [_PLACE_WORDS.get(word, word) for word in normalize_text(text).split()]
    if len(words) > 1 and words[-1] in _PLACE_SUFFIXES:
        words.pop()
    return " ".join(words)


def normalize_state(state) -> str:
    """Two lowercase letters: "ME" and "Maine" both give "me"."""
    text = normalize_text(state)
    return _STATE_ABBREVIATIONS.get(text, text)


def normalize_phone(phone) -> str:
    """Digits only, and a leading US country code dropped: "(207) 282-6860"
    and "1-207-282-6860" both give "2072826860"."""
    digits = re.sub(r"\D", "", str(phone or ""))
    return digits[1:] if len(digits) == 11 and digits.startswith("1") else digits


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


@lru_cache(maxsize=1)
def _mapping() -> dict:
    data = _read_json(MAPPING_PATH)
    data = data if isinstance(data, dict) else {}
    return {"excluded": set(data.get("excluded") or []), "aliases": data.get("aliases") or {}}


def _shops_from_netsuite() -> list:
    """The shops in NetSuite's location list, or [] while that file has no
    addresses (not yet synced with them)."""
    data = _read_json(NETSUITE_LOCATIONS_PATH)
    entries = [e for e in data.values() if isinstance(e, dict)] if isinstance(data, dict) else []
    if not any("city" in e for e in entries):
        return []
    excluded = _mapping()["excluded"]
    return [{"name": e["name"].strip(), "phone": e.get("phone") or "", "city": e.get("city") or "",
             "state": e.get("state") or "", "street": e.get("street") or "", "zip": e.get("zip") or "",
             "country": "US"}
            for e in entries if (e.get("name") or "").strip() and e["name"].strip() not in excluded]


@lru_cache(maxsize=1)
def _load() -> list:
    shops = _shops_from_netsuite()
    if shops:
        return shops
    data = _read_json(SHOPS_PATH)
    return data if isinstance(data, list) else []


@lru_cache(maxsize=1)
def _indexes() -> tuple:
    by_name, by_phone, by_city = {}, {}, {}
    for shop in _load():
        by_name[normalize_text(shop["name"])] = shop
        phone = normalize_phone(shop.get("phone"))
        if phone:
            by_phone[phone] = shop
        city = normalize_place(shop.get("city"))
        if city:
            by_city.setdefault((city, normalize_state(shop.get("state"))), []).append(shop)
    return by_name, by_phone, by_city


@lru_cache(maxsize=1)
def _forms() -> list:
    """[(normalized name or alias, shop)]: every way a statement may name a
    shop. An alias whose shop is not in the list is ignored."""
    forms = [(normalize_text(shop["name"]), shop) for shop in _load()]
    by_name = _indexes()[0]
    for name, aliases in _mapping()["aliases"].items():
        shop = by_name.get(normalize_text(name))
        if shop:
            forms.extend((normalize_text(alias), shop) for alias in aliases)
    return [(form, shop) for form, shop in forms if form]


@lru_cache(maxsize=1)
def _alias_forms() -> frozenset:
    """The normalized aliases that are not also a shop's own name."""
    shop_names = {normalize_text(shop["name"]) for shop in _load()}
    return frozenset(form for form, shop in _forms() if form not in shop_names)


def reload():
    """Forget everything read from disk (after the files or their paths change)."""
    for cached in (_mapping, _load, _indexes, _forms, _alias_forms):
        cached.cache_clear()


def is_alias(form) -> bool:
    """True when `form` (as normalized by normalize_text) is an alias from
    config/location_mapping.json rather than a shop's own name."""
    return form in _alias_forms()


def all_shops() -> list:
    return list(_load())


def names() -> list:
    return [shop["name"] for shop in _load()]


def name_forms() -> list:
    """[(normalized name or alias, shop)] for matching shop text against."""
    return list(_forms())


def shop_details(name) -> Optional[dict]:
    """{"phone", "city", "state"} straight from the shop list for a canonical
    shop name, or None when `name` is not a shop. Phone is as printed in the
    list ("(207) 282-6860"); a shop without one has "" for it."""
    shop = by_name(name)
    if not shop:
        return None
    return {"phone": shop.get("phone", ""), "city": shop.get("city", ""), "state": shop.get("state", "")}


def by_name(name) -> Optional[dict]:
    """The shop whose name equals `name` once normalized, or None."""
    return _indexes()[0].get(normalize_text(name))


def by_phone(phone) -> Optional[dict]:
    """The shop with this phone number, or None. Phones are unique."""
    return _indexes()[1].get(normalize_phone(phone))


def by_city(city, state) -> list:
    """Every shop in this city and state -- more than one is possible. With no
    state given, every shop in a city of that name, whatever its state."""
    wanted_city, wanted_state = normalize_place(city), normalize_state(state)
    if wanted_state:
        return list(_indexes()[2].get((wanted_city, wanted_state), []))
    return [shop for (shop_city, _), shops in _indexes()[2].items() if shop_city == wanted_city for shop in shops]
