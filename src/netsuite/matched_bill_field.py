"""The Statement Line's "Matched Bill" (custrecord_sl_matched_bill): one bill
link today, about to become a Multiple Select (2026-11-06) so one statement
invoice can point at several bills (a split payment).

NetSuite wants a different shape for each type, and the switch happens in
NetSuite on its own schedule, so every write, read-back, undo and re-create
goes through here and works with BOTH:

    single:   {"id": "48213"}
    multiple: {"items": [{"id": "48213"}, {"id": "48214"}]}

SuiteQL reads either one back as text: "48213" or "48213, 48214".

Which one is live is read from NetSuite's record metadata and remembered for
MODE_CACHE_SECONDS (so the switch is picked up without a restart). The
setting STATEMENT_LINE_MATCHED_BILL_MODE=single|multiple overrides it; if the
metadata can't be read, it falls back to single (today's behaviour).
"""
import logging
import os
import re
import time

logger = logging.getLogger(__name__)

FIELD = "custrecord_sl_matched_bill"
STATEMENT_LINE_RECORD = "customrecord_statement_line"
SINGLE, MULTIPLE = "single", "multiple"
ENV_MODE = "STATEMENT_LINE_MATCHED_BILL_MODE"
MODE_CACHE_SECONDS = 300
MAX_BILLS = 50

_cache = {"mode": None, "at": 0.0}


def ids_from(value) -> list:
    """Bill internal ids from anything this field can hold: SuiteQL text
    ("48213" / "48213, 48214"), a number, {"id"} or {"items": [{"id"}, ...]}."""
    if value is None or value == "":
        return []
    if isinstance(value, dict):
        if "items" in value:
            return [i for item in value.get("items") or [] for i in ids_from(item)]
        return ids_from(value.get("id"))
    if isinstance(value, (list, tuple)):
        return [i for item in value for i in ids_from(item)]
    return [part for part in re.split(r"[,\s]+", str(value).strip()) if part.isdigit()]


def same_bills(a, b) -> bool:
    """Do two values of this field name the same bills (order ignored)?"""
    return sorted(set(ids_from(a))) == sorted(set(ids_from(b)))


def _mode_from_schema(schema: dict) -> str:
    prop = ((schema or {}).get("properties") or {}).get(FIELD)
    if not isinstance(prop, dict):
        raise LookupError(f"{FIELD} not in the {STATEMENT_LINE_RECORD} metadata")
    # A Multiple Select is a collection: {"type": "object", "properties": {"items": {"type": "array", ...}}}
    items = (prop.get("properties") or {}).get("items")
    if prop.get("type") == "array" or (isinstance(items, dict) and items.get("type") == "array"):
        return MULTIPLE
    return SINGLE


def field_mode(ns=None, now=time.monotonic) -> str:
    """SINGLE or MULTIPLE: the setting if set, else NetSuite's metadata
    (cached), else SINGLE. Never raises."""
    forced = os.getenv(ENV_MODE, "").strip().lower()
    if forced in (SINGLE, MULTIPLE):
        return forced
    if _cache["mode"] and now() - _cache["at"] < MODE_CACHE_SECONDS:
        return _cache["mode"]
    mode = SINGLE
    if ns is not None:
        try:
            mode = _mode_from_schema(ns.get_record_schema(STATEMENT_LINE_RECORD))
        except Exception as exc:
            logger.warning("Could not tell whether %s is a Multiple Select (%s); treating it as a single link",
                           FIELD, exc)
            return SINGLE   # not cached: try again next time
    _cache.update(mode=mode, at=now())
    return mode


def reset_cache() -> None:
    _cache.update(mode=None, at=0.0)


def value_for(mode: str, bill_ids) -> object:
    """What to send NetSuite for these bills. No bills -> None (single) or an
    empty list (multiple). A single link can only hold the first bill."""
    ids = list(dict.fromkeys(ids_from(bill_ids)))
    if mode == MULTIPLE:
        return {"items": [{"id": i} for i in ids]}
    return {"id": ids[0]} if ids else None
