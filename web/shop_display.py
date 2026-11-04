"""The shop and location a statement card shows and filters by.

A statement whose customer location was mapped to a VIVE shop
(src/validation/location_lookup.py; billing_location_source one of
MAPPED_SOURCES) shows that shop's NetSuite name as its Shop and the shop's
"City, ST" as its Location -- one entry per shop in the filters, not one per
spelling on the vendors' PDFs. Any other statement (not mapped, or stored
before the mapping existed) shows the raw text as extracted: shop_or_entity
as its Shop and billing_location as its Location.

Each card's data-shop / data-location, the card text and the filter
dropdowns are all built from these values, so they always agree.
"""
import json
import logging

from src.validation.location_lookup import MAPPED_SOURCES
from web.deps import smart_title

logger = logging.getLogger(__name__)

# The document_intake_log columns shop_and_location() reads.
INTAKE_SHOP_COLUMNS = "shop_or_entity, billing_location, billing_location_source, shop_city, shop_state"
# What those pages read before shop_city / shop_state / the mapped sources existed.
LEGACY_SHOP_COLUMNS = "shop_or_entity, billing_location"
# Where a query puts INTAKE_SHOP_COLUMNS; query_with_shop_columns() fills it in.
SHOP_COLUMNS_TOKEN = "@@SHOP_COLUMNS@@"
_MISSING_COLUMN_MARKERS = ("no such column", "invalid column name")  # SQLite, SQL Server


def _raw_shop(intake_row: dict):
    try:
        names = json.loads(intake_row["shop_or_entity"]) if intake_row.get("shop_or_entity") else []
    except (TypeError, ValueError):
        names = []
    return ", ".join(names) if names else None


def shop_and_location(intake_row) -> dict:
    """{"shop", "billing_location", "shop_canonical"} for one document_intake_log
    row (None for a statement with no row). shop_canonical is True when shop
    is a NetSuite shop name, which must not be re-cased by smart_title()
    ("RP Bell", "JC Auto")."""
    row = intake_row or {}
    if row.get("billing_location_source") in MAPPED_SOURCES and row.get("billing_location"):
        place = ", ".join(part.strip() for part in (row.get("shop_city"), row.get("shop_state")) if part and part.strip())
        return {"shop": row["billing_location"], "billing_location": place or None, "shop_canonical": True}
    return {"shop": _raw_shop(row), "billing_location": row.get("billing_location") or None, "shop_canonical": False}


def query_with_shop_columns(execute, sql: str, params=None) -> list:
    """Runs `sql` (with SHOP_COLUMNS_TOKEN where the shop columns go) through
    `execute`, the caller's execute_query. If the database does not have the
    newer columns yet (a deploy where the migration has not run), it runs again
    with the old ones, so the cards and filters show the raw text instead of the
    page failing. Any other error is raised as it was."""
    try:
        return execute(sql.replace(SHOP_COLUMNS_TOKEN, INTAKE_SHOP_COLUMNS), params)
    except Exception as error:
        if not any(marker in str(error).lower() for marker in _MISSING_COLUMN_MARKERS):
            raise
        logger.warning("document_intake_log lacks the shop columns (%s) -- showing the raw shop and location; "
                       "run the schema migration", str(error)[:200])
        return execute(sql.replace(SHOP_COLUMNS_TOKEN, LEGACY_SHOP_COLUMNS), params)


def display_shop(card: dict):
    """The card's shop as displayed: a NetSuite name as it is, raw text title-cased."""
    return card.get("shop") if card.get("shop_canonical") else smart_title(card.get("shop"))
