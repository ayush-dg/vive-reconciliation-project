"""VIVE shop list (config/vive_shops.json) with lookups by name, phone and city.

The list is written by scripts/build_vive_shops.py from VIVE_Shop_List.xlsx.
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

SHOPS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          "config", "vive_shops.json")

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_text(text) -> str:
    """Lowercase letters and digits only, words separated by single spaces --
    "Coleman's" and "COLEMANS" both become a form that compares equal after
    the apostrophe is dropped."""
    return _NON_ALNUM_RE.sub(" ", str(text or "").lower().replace("'", "")).strip()


def normalize_phone(phone) -> str:
    """Digits only, and a leading US country code dropped: "(207) 282-6860"
    and "1-207-282-6860" both give "2072826860"."""
    digits = re.sub(r"\D", "", str(phone or ""))
    return digits[1:] if len(digits) == 11 and digits.startswith("1") else digits


@lru_cache(maxsize=1)
def _load() -> list:
    try:
        with open(SHOPS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


@lru_cache(maxsize=1)
def _indexes() -> tuple:
    by_name, by_phone, by_city = {}, {}, {}
    for shop in _load():
        by_name[normalize_text(shop["name"])] = shop
        phone = normalize_phone(shop.get("phone"))
        if phone:
            by_phone[phone] = shop
        city = normalize_text(shop.get("city"))
        if city:
            by_city.setdefault((city, shop.get("state", "").lower()), []).append(shop)
    return by_name, by_phone, by_city


def all_shops() -> list:
    return list(_load())


def names() -> list:
    return [shop["name"] for shop in _load()]


def by_name(name) -> Optional[dict]:
    """The shop whose name equals `name` once normalized, or None."""
    return _indexes()[0].get(normalize_text(name))


def by_phone(phone) -> Optional[dict]:
    """The shop with this phone number, or None. Phones are unique."""
    return _indexes()[1].get(normalize_phone(phone))


def by_city(city, state) -> list:
    """Every shop in this city and state -- more than one is possible."""
    return list(_indexes()[2].get((normalize_text(city), str(state or "").lower()), []))
