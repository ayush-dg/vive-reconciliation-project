"""Resolves a vendor_id (and its extracted statement vendor_name) to the
NetSuite entity id(s) whose vendorbill rows should be matched against that
vendor's statement.

Three paths, checked in this order:
1. config/netsuite_entity_overrides.json -- hand-confirmed mappings. Wins
   over dynamic lookup always: it's the only way to express a vendor that
   needs MULTIPLE NetSuite entities (e.g. Bald Hill Dodge + Bald Hill Kia
   billing through one consolidated statement, two separate NetSuite vendor
   records with different company names -- no name-based query finds both
   from the statement's one vendor name).
2. Dynamic lookup against bronze.netsuite_vendor by exact normalized
   company name -- used only when it finds exactly one ACTIVE match. Zero
   matches or multiple matches fall through to the next path rather than
   guessing.
3. First-word LIKE fallback: case-insensitive substring search on
   companyname/entityid/altname using just the first word of the vendor
   name (e.g. "Bald Hill Dodge..." -> "%bald%"), active entities only.
   Broader than exact match, so riskier by nature -- but validated against
   4 real vendors (KSI, Bald Hill, Berlin City, Nucar) with zero false-
   positive tranid collisions on their real statements before being wired
   in. Its safety depends entirely on the first word being distinctive
   (short/generic first words are skipped -- see MIN_FIRST_WORD_LEN).
   Every entity this path returns is unconfirmed by design; if a wrong
   one ever causes a bad match, prefer adding a proper override entry
   over tightening this path.

Returns None (never raises) when nothing resolves -- callers treat that as
"this vendor's statement can't be matched yet" and should raise all its
lines as a single "Vendor Not Resolved in NetSuite" exception rather than
attempting to match.
"""
import json
import logging
import os
import re

from src.lakehouse.fabric_sql import get_lakehouse_connection

logger = logging.getLogger(__name__)

OVERRIDES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "netsuite_entity_overrides.json",
)

_overrides_cache = None

MIN_FIRST_WORD_LEN = 3


def _normalize(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 ]", "", name or "").upper()
    return re.sub(r"\s+", " ", cleaned).strip()


def _load_overrides() -> dict:
    global _overrides_cache
    if _overrides_cache is not None:
        return _overrides_cache
    try:
        with open(OVERRIDES_PATH, "r") as f:
            _overrides_cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _overrides_cache = {}
    return _overrides_cache


def _dynamic_lookup(vendor_name: str) -> list:
    """Exact normalized name match against bronze.netsuite_vendor, active
    only. Checks companyname, entityid, and altname -- companyname is NULL
    for many individual-location dealer records (the real name only lives
    in entityid/altname there), confirmed by inspecting real rows. Returns
    [entity_id] on exactly one distinct matching id, [] otherwise."""
    if not vendor_name or not vendor_name.strip():
        return []
    target = _normalize(vendor_name)
    try:
        conn = get_lakehouse_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, companyname, entityid, altname FROM bronze.netsuite_vendor "
            "WHERE isinactive = 'F'"
        )
        matches = {
            row[0] for row in cur.fetchall()
            if target in (_normalize(row[1]), _normalize(row[2]), _normalize(row[3]))
        }
        return list(matches) if len(matches) == 1 else []
    except Exception:
        logger.exception("Dynamic NetSuite vendor lookup failed for %r (non-fatal)", vendor_name)
        return []


def _first_word_like_lookup(vendor_name: str) -> list:
    """Case-insensitive substring match on companyname/entityid/altname
    using just the first word of vendor_name. Active entities only. Skips
    first words shorter than MIN_FIRST_WORD_LEN -- a 1-2 character word
    (or a blank/punctuation-only one) would match too broadly to be a
    useful signal. Returns every matching entity id (can be several);
    unlike _dynamic_lookup, ambiguity here is expected and not a reason
    to bail -- the tranid-level lookup that consumes this list is what
    actually filters out any unrelated entity that has no matching line."""
    if not vendor_name or not vendor_name.strip():
        return []
    first_word = re.sub(r"[^A-Za-z0-9]", "", re.split(r"\s+", vendor_name.strip())[0])
    if len(first_word) < MIN_FIRST_WORD_LEN:
        return []
    pattern = f"%{first_word.lower()}%"
    try:
        conn = get_lakehouse_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM bronze.netsuite_vendor WHERE isinactive = 'F' AND "
            "(LOWER(companyname) LIKE ? OR LOWER(entityid) LIKE ? OR LOWER(altname) LIKE ?)",
            [pattern, pattern, pattern],
        )
        return [row[0] for row in cur.fetchall()]
    except Exception:
        logger.exception("First-word LIKE NetSuite vendor lookup failed for %r (non-fatal)", vendor_name)
        return []


def resolve_entity_ids(vendor_id: str, vendor_name: str) -> list:
    """Returns a list of NetSuite entity ids to match this vendor's
    statement against, or None if unresolved."""
    override = _load_overrides().get(vendor_id)
    if override and override.get("entity_ids"):
        return override["entity_ids"]

    dynamic = _dynamic_lookup(vendor_name)
    if dynamic:
        return dynamic

    like_matches = _first_word_like_lookup(vendor_name)
    if like_matches:
        return like_matches

    return None
