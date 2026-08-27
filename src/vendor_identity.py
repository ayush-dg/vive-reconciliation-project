"""
vendor_identity.py

Resolves a raw vendor_name string (AI-extracted from a statement, or read
off a voucher's "Paid To" field) to one canonical vendor_id, for vendors
listed in config/vendor_aliases.json.

Needed because notebooks/01_document_intake.py's default vendor_id
derivation (vendor_name.upper().replace(" ","_").replace(",","")[:50]) is
a raw string transform with no canonicalization: the same real vendor
can legally print its name differently across documents -- e.g. "asTech"
on one statement's letterhead vs "Repairify, Inc. dba asTech" in its
remittance block vs "Repairify, Inc dba asTech" (no period) on a payment
voucher -- which the default transform would turn into three different
vendor_ids for one vendor. config/vendor_aliases.json records the known
name variants seen for a vendor so they all resolve to the same id.

config/vendor_aliases.json is a placeholder, hand-curated from documents
seen so far -- like config/shop_owners.json, most vendors won't be in it
yet, which is expected: resolve_vendor_id() returns None for any miss so
callers fall back to the default transform.
"""

import json
import os
import re

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "vendor_aliases.json"
)

_lookup_cache = None


def _normalize(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 ]", "", name).upper()
    return re.sub(r"\s+", " ", cleaned).strip()


def _load_lookup() -> dict:
    global _lookup_cache
    if _lookup_cache is not None:
        return _lookup_cache
    try:
        with open(CONFIG_PATH, "r") as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        raw = {}
    _lookup_cache = {
        _normalize(alias): vendor_id
        for vendor_id, aliases in raw.items()
        for alias in aliases
    }
    return _lookup_cache


def resolve_vendor_id(vendor_name) -> str:
    """Returns the canonical vendor_id for vendor_name per
    config/vendor_aliases.json, or None if vendor_name is falsy or has no
    known alias entry."""
    if not vendor_name or not str(vendor_name).strip():
        return None
    return _load_lookup().get(_normalize(vendor_name))


def display_name(vendor_name) -> str:
    """Best-effort clean display label for a vendor: resolves vendor_name
    to its canonical vendor_id (config/vendor_aliases.json) and prettifies
    that -- e.g. "Bald Hill Dodge Chrysler Jeep Kia" (the full legal name
    as extracted off that statement's letterhead) resolves to vendor_id
    BALD_HILL, displayed as "Bald Hill" -- rather than showing whatever
    long-form name happens to be printed on any one PDF. Falls back to
    vendor_name itself, unchanged, when there's no alias entry (most
    vendors don't have one yet) or vendor_name is falsy.

    This is purely a display transform -- callers that need the real
    identity (routing, DB lookups keyed on vendor_name) must keep using
    vendor_name/vendor_id directly, not this."""
    if not vendor_name or not str(vendor_name).strip():
        return vendor_name
    vendor_id = resolve_vendor_id(vendor_name)
    if not vendor_id:
        return vendor_name
    return vendor_id.replace("_", " ").title()
