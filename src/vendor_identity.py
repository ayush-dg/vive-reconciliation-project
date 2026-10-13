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
    """Strips punctuation, uppercases, and sorts words alphabetically --
    the sort makes matching insensitive to word order, which real
    extractions vary on for the same vendor (e.g. "Nucar (DCD Automotive
    Holdings)" on one statement vs "DCD Automotive Holdings / Nucar" on
    another -- same legal entity, different letterhead phrasing). Doesn't
    help with genuinely different word sets for the same vendor (e.g. a
    shortened "Bald Hill Dodge Chrysler" vs the full "Bald Hill Dodge
    Chrysler Jeep Kia") -- those still need an explicit alias entry."""
    cleaned = re.sub(r"[^A-Za-z0-9 ]", "", name).upper()
    words = re.sub(r"\s+", " ", cleaned).strip().split(" ")
    return " ".join(sorted(words))


def _normalize_split(name: str) -> str:
    """_normalize() with hyphens and slashes read as word breaks
    (2026-10-13): "Goodwin's Chevrolet-Mazda" must match the alias
    "Goodwins Chevrolet Mazda" -- _normalize() drops the hyphen outright and
    glues it into one word, CHEVROLETMAZDA, so the prod job got an unmapped
    fallback vendor_id ("No lines read"). Used ALONGSIDE _normalize(), never
    instead of it: aliases are registered under both forms and a name is
    tried in both, so every name that matched before still does (e.g.
    "1800 Radiator" vs the alias "1-800 Radiator")."""
    return _normalize(re.sub(r"[-/]", " ", name))


def _load_lookup() -> dict:
    global _lookup_cache
    if _lookup_cache is not None:
        return _lookup_cache
    try:
        with open(CONFIG_PATH, "r") as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        raw = {}
    lookup = {}
    for vendor_id, aliases in raw.items():
        for alias in aliases:
            lookup.setdefault(_normalize(alias), vendor_id)
    # Hyphen/slash-split forms second, so they never override a plain key.
    for vendor_id, aliases in raw.items():
        for alias in aliases:
            lookup.setdefault(_normalize_split(alias), vendor_id)
    _lookup_cache = lookup
    return _lookup_cache


def resolve_vendor_id(vendor_name) -> str:
    """Returns the canonical vendor_id for vendor_name per
    config/vendor_aliases.json, or None if vendor_name is falsy or has no
    known alias entry."""
    if not vendor_name or not str(vendor_name).strip():
        return None
    lookup = _load_lookup()
    for key in _candidate_keys(str(vendor_name)):
        if key in lookup:
            return lookup[key]
    return None


# Company-type words dropped by the fallback forms below (whole words only).
_COMPANY_SUFFIXES = {"INC", "INCORPORATED", "LLC", "CO", "CORP", "CORPORATION", "LTD", "COMPANY"}


def _without_suffixes(key: str) -> str:
    words = [w for w in key.split(" ") if w not in _COMPANY_SUFFIXES]
    return " ".join(words) if words else key


def _candidate_keys(name: str):
    """Lookup keys to try for a printed vendor name, in order. The first two
    are what resolve_vendor_id() has always tried (plain, then hyphen/slash
    split); the rest are fallbacks added 2026-10-13 for prod statements that
    printed extra text around a known vendor's name -- they're only reached
    when everything before them missed, so no name that resolved before
    resolves differently:
      - without company suffixes: "Lia Group Payables LLC" -> "Lia Group Payables"
      - without bracketed text: "Nucar (The Reynolds and Reynolds Company)" -> "Nucar"
      - only the part before " - ": "TechZone - Note our new address" -> "TechZone"
    """
    forms = [name]
    no_brackets = re.sub(r"\([^)]*\)", " ", name).strip()
    if no_brackets and no_brackets != name:
        forms.append(no_brackets)
    before_dash = re.split(r"\s+-\s+", name)[0].strip()
    if before_dash and before_dash != name:
        forms.append(before_dash)
    seen = []
    for i, form in enumerate(forms):
        keys = [_normalize(form), _normalize_split(form)]
        for key in keys + [_without_suffixes(k) for k in keys]:
            if key not in seen:
                seen.append(key)
                yield key


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
