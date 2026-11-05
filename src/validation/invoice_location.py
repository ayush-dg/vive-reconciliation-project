"""A statement's shop from the NetSuite bills it is matched to.

Name, alias, street and city (src/validation/location_lookup.py) decide a
statement's shop when it is processed. When they cannot -- the result is
"ambiguous", "conflict" or "unmapped" -- the shop of its matched bills can: the
recon table keeps each matched bill's NetSuite location. When every matched
bill and credit of a statement sits at one location, that shop is used and the
source becomes "invoice_match". A confident result is never looked at again.

The bills are only known after the matching run, so this runs then
(refresh_statement_location(), after the run and after a manual match or its
undo). With no matched bill, or bills at several locations, the statement
keeps what it had. If a manual match is undone and no other bill is left, an
"invoice_match" row is mapped again from its stored text (without the street
lines, which are not stored).

Azure SQL (SQLite locally): document_intake_log and recon.
"""
import json
import logging
from collections import defaultdict
from typing import Optional

from src.lakehouse.connection import execute_query, execute_sql
from src.lakehouse.recon_table import STATUS_MATCHED, STATUS_MATCHED_MANUALLY
from src.netsuite.locations import location_names
from src.validation.location_lookup import (SOURCE_AMBIGUOUS, SOURCE_CONFLICT, SOURCE_INVOICE, SOURCE_UNMAPPED,
                                            apply_location)
from src.validation.shop_list import by_name, shop_details

logger = logging.getLogger(__name__)

# The results that leave a statement without a shop.
FALLBACK_SOURCES = (SOURCE_AMBIGUOUS, SOURCE_CONFLICT, SOURCE_UNMAPPED)
LOCATION_VALUE_COLUMNS = ("billing_location", "billing_location_source", "billing_location_extracted",
                          "shop_phone", "shop_city", "shop_state")


def bill_locations(statement_id: str = None) -> dict:
    """{statement_id: {NetSuite location ids}} of the active matched bills and
    credits: one statement, or every statement whose source is a fallback one."""
    if statement_id:
        scope, params = "statement_id = ?", [statement_id]
    else:
        scope = ("statement_id IN (SELECT statement_id FROM document_intake_log WHERE billing_location_source IN "
                 f"({', '.join('?' for _ in FALLBACK_SOURCES)}))")
        params = list(FALLBACK_SOURCES)
    rows = execute_query(
        "SELECT DISTINCT statement_id, netsuite_location FROM recon WHERE is_active = 1 "
        f"AND netsuite_location IS NOT NULL AND status IN (?, ?) AND {scope}",
        [STATUS_MATCHED, STATUS_MATCHED_MANUALLY, *params])
    found = defaultdict(set)
    for row in rows:
        code = str(row["netsuite_location"]).strip()
        if code:
            found[row["statement_id"]].add(code)
    return found


def shop_for(codes) -> Optional[dict]:
    """The shop (as in shop_list) at the one location in `codes`; None for
    none, several, or a location that is not a VIVE shop."""
    if len(codes) != 1:
        return None
    name = location_names().get(next(iter(codes)))
    return by_name(name) if name else None


def invoice_values(shop: dict, row: dict) -> dict:
    """The location columns for a statement that takes `shop` from its bills.
    What extraction returned is kept as it was."""
    details = shop_details(shop["name"]) or {}
    return {
        "billing_location": shop["name"],
        "billing_location_source": SOURCE_INVOICE,
        "billing_location_extracted": row.get("billing_location_extracted") or row.get("billing_location"),
        "shop_phone": details.get("phone"),
        "shop_city": details.get("city"),
        "shop_state": details.get("state"),
    }


def remapped_values(row: dict, shop_names: list) -> dict:
    """The location columns from name, alias and city alone, as at intake."""
    meta = apply_location({"shop_or_entity": shop_names,
                           "billing_location": row.get("billing_location_extracted") or row.get("billing_location")})
    return {column: meta.get(column) for column in LOCATION_VALUE_COLUMNS}


def write_values(row_id, values: dict) -> None:
    assignments = ", ".join(f"{column} = ?" for column in LOCATION_VALUE_COLUMNS)
    execute_sql(f"UPDATE document_intake_log SET {assignments} WHERE id = ?",
                [values[column] for column in LOCATION_VALUE_COLUMNS] + [row_id])


def shop_names_of(row: dict) -> list:
    try:
        names = json.loads(row["shop_or_entity"]) if row.get("shop_or_entity") else []
    except (TypeError, ValueError):
        names = []
    return names if isinstance(names, list) else []


def refresh_statement_location(statement_id: str) -> Optional[str]:
    """Brings one statement's location in line with its matched bills (see the
    module docstring). Returns the shop name it set, or None when nothing
    changed."""
    if not statement_id:
        return None
    rows = execute_query(
        "SELECT id, shop_or_entity, billing_location, billing_location_extracted, billing_location_source "
        "FROM document_intake_log WHERE statement_id = ?", [statement_id])
    shop = shop_for(bill_locations(statement_id).get(statement_id, set()))
    changed = None
    for row in rows:
        source = row.get("billing_location_source")
        if shop and (source in FALLBACK_SOURCES or (source == SOURCE_INVOICE and row.get("billing_location") != shop["name"])):
            write_values(row["id"], invoice_values(shop, row))
            changed = shop["name"]
        elif source == SOURCE_INVOICE and not shop:
            write_values(row["id"], remapped_values(row, shop_names_of(row)))
    return changed


def refresh_quietly(statement_id: str) -> Optional[str]:
    """refresh_statement_location() for the callers that must never fail
    because of it (the matching run, a person's Accept as match)."""
    try:
        return refresh_statement_location(statement_id)
    except Exception:
        logger.exception("taking the location from the matched bills failed for %s (non-fatal)", statement_id)
        return None


def refresh_and_sync_quietly(statement_id: str) -> None:
    """refresh_quietly(), then the copy to Fabric (src/lakehouse/fabric_location.py)
    on a background thread: for a person's Accept as match or its undo, which
    must not wait for the Fabric lock. Not for the matching run, which can hold it."""
    refresh_quietly(statement_id)
    try:
        from src.lakehouse.fabric_location import sync_in_background
        sync_in_background(statement_id)
    except Exception:
        logger.exception("starting the Fabric location copy failed for %s (non-fatal)", statement_id)
