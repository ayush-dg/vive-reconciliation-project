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
import threading
import time

from src.lakehouse.fabric_sql import get_lakehouse_connection
from src.netsuite import connect_source

logger = logging.getLogger(__name__)

OVERRIDES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "netsuite_entity_overrides.json",
)

_overrides_cache = None

MIN_FIRST_WORD_LEN = 3

# Vendor-list cache (2026-11-13): the whole active-vendor list is the same for
# every search and every statement, but it used to be fetched -- live from
# NetSuite when NETSUITE_SOURCE=connect, with no time limit -- on almost every
# lookup, holding the one shared Connect connection while other searches
# waited. It is now fetched at most once per NETSUITE_VENDOR_CACHE_SECONDS
# (default 30 min) and shared by every thread; name searches run on that copy.
# A vendor created in NetSuite since the last fetch: resolve_entity_ids()
# refreshes once when nothing resolves (see REFRESH_ON_MISS_AFTER_SECONDS).
DEFAULT_VENDOR_CACHE_SECONDS = 1800
REFRESH_ON_MISS_AFTER_SECONDS = 60
_vendor_cache = {"rows": None, "at": 0.0, "source": None}
_vendor_cache_lock = threading.Lock()
_clock = time.monotonic


def _vendor_cache_seconds() -> float:
    try:
        value = float(os.getenv("NETSUITE_VENDOR_CACHE_SECONDS") or DEFAULT_VENDOR_CACHE_SECONDS)
    except ValueError:
        return DEFAULT_VENDOR_CACHE_SECONDS
    return value if value >= 0 else DEFAULT_VENDOR_CACHE_SECONDS


def reset_vendor_cache() -> None:
    """Forget the cached vendor list (tests; a forced refresh)."""
    with _vendor_cache_lock:
        _vendor_cache.update(rows=None, at=0.0, source=None)


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


def _active_vendor_rows(force_refresh: bool = False) -> list:
    """(id, companyname, entityid, altname) of every active vendor, from the
    shared cache (see DEFAULT_VENDOR_CACHE_SECONDS). Only one thread fetches
    at a time; while it does, others keep using the previous copy. If a fetch
    fails, the previous copy is kept; with no copy at all the error is raised
    as before (callers treat it as not resolved)."""
    rows, at, source = _vendor_cache["rows"], _vendor_cache["at"], _vendor_cache["source"]
    fresh = rows is not None and _clock() - at < _vendor_cache_seconds()
    if fresh and not force_refresh:
        _note_source(source)
        return rows
    if rows is not None and not _vendor_cache_lock.acquire(blocking=False):
        _note_source(source)
        return rows  # another thread is refreshing: use the current copy
    if rows is None:
        _vendor_cache_lock.acquire()
    try:
        if _vendor_cache["rows"] is not None and _vendor_cache["at"] > at:
            _note_source(_vendor_cache["source"])
            return _vendor_cache["rows"]  # refreshed while we waited
        try:
            fetched, used = _fetch_active_vendor_rows()
        except Exception:
            if rows is None:
                raise
            logger.exception("Refreshing the NetSuite vendor list failed; using the copy from %.0fs ago",
                             _clock() - at)
            _note_source(source)
            return rows
        _vendor_cache.update(rows=list(fetched), at=_clock(), source=used)
        return _vendor_cache["rows"]
    finally:
        _vendor_cache_lock.release()


def _note_source(source) -> None:
    if source == connect_source.SOURCE_CONNECT:
        connect_source.note_used(connect_source.SOURCE_CONNECT)


def _fetch_active_vendor_rows() -> tuple:
    """(rows, source): live from NetSuite when NETSUITE_SOURCE=connect
    (src/netsuite/connect_source.py), else (or if that read fails) from the
    Fabric copy."""
    if connect_source.use_connect():
        try:
            rows = connect_source.active_vendor_rows()
            connect_source.note_used(connect_source.SOURCE_CONNECT)
            return rows, connect_source.SOURCE_CONNECT
        except Exception:
            connect_source.note_fallback("vendor list")
    cur = get_lakehouse_connection().cursor()
    cur.execute("SELECT id, companyname, entityid, altname FROM bronze.netsuite_vendor WHERE isinactive = 'F'")
    return [tuple(row) for row in cur.fetchall()], "fabric"


def _active_vendor_ids_like(pattern: str) -> list:
    """Ids of active vendors whose companyname/entityid/altname contains
    `pattern` (lowercase, with % wildcards). A plain '%word%' (all the
    first-word lookup ever sends) runs on the cached vendor list (2026-11-13);
    anything else still asks the source directly."""
    needle = pattern[1:-1] if len(pattern) > 2 and pattern[0] == pattern[-1] == "%" else None
    if needle and "%" not in needle and "_" not in needle:
        rows = _active_vendor_rows()
        return list(dict.fromkeys(
            row[0] for row in rows
            if any(needle in str(value or "").lower() for value in (row[1], row[2], row[3]))
        ))
    return _fetch_active_vendor_ids_like(pattern)


def _fetch_active_vendor_ids_like(pattern: str) -> list:
    """_active_vendor_ids_like() asked of the source itself (live NetSuite or
    the Fabric copy) -- same source rule as _fetch_active_vendor_rows()."""
    if connect_source.use_connect():
        try:
            ids = connect_source.active_vendor_ids_like(pattern)
            connect_source.note_used(connect_source.SOURCE_CONNECT)
            return ids
        except Exception:
            connect_source.note_fallback("vendor name search")
    cur = get_lakehouse_connection().cursor()
    cur.execute(
        "SELECT id FROM bronze.netsuite_vendor WHERE isinactive = 'F' AND "
        "(LOWER(companyname) LIKE ? OR LOWER(entityid) LIKE ? OR LOWER(altname) LIKE ?)",
        [pattern, pattern, pattern],
    )
    return [row[0] for row in cur.fetchall()]


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
        matches = {
            row[0] for row in _active_vendor_rows()
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
        return _active_vendor_ids_like(pattern)
    except Exception:
        logger.exception("First-word LIKE NetSuite vendor lookup failed for %r (non-fatal)", vendor_name)
        return []


def resolve_entity_ids(vendor_id: str, vendor_name: str) -> list:
    """Returns a list of NetSuite entity ids to match this vendor's
    statement against, or None if unresolved."""
    override = _load_overrides().get(vendor_id)
    if override and override.get("entity_ids"):
        return override["entity_ids"]

    for attempt in (1, 2):
        dynamic = _dynamic_lookup(vendor_name)
        if dynamic:
            return dynamic

        like_matches = _first_word_like_lookup(vendor_name)
        if like_matches:
            return like_matches

        # Nothing resolved: perhaps a vendor created in NetSuite after the
        # cached list was fetched -- refresh once (not more than once a
        # minute, so a name that never resolves can't refetch on every call).
        age = _clock() - _vendor_cache["at"]
        if attempt == 1 and _vendor_cache["rows"] is not None and age >= REFRESH_ON_MISS_AFTER_SECONDS:
            try:
                _active_vendor_rows(force_refresh=True)
            except Exception:
                logger.exception("Vendor list refresh after a miss failed (non-fatal)")
                return None
            continue
        return None
