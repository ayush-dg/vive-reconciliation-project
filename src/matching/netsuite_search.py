"""Read-only, user-driven search across NetSuite open AP
(bronze.netsuite_vendorbill / bronze.netsuite_vendorcredit, Fabric
Lakehouse), for the Exceptions review page's "Search NetSuite" panel.

This is a RESEARCH tool, deliberately separate from matching. The
matching engine (src/matching/fabric_matching.py) answers "does this
statement line tie out to NetSuite?" with fixed, automatic rules. This
answers "where else could this invoice have been entered?" with filters
the AP user relaxes by hand -- the shop may have booked a Keystone
invoice under LKQ, with a typo'd invoice number, or at a different
amount, and none of those are things the matching engine can or should
guess at. Nothing here feeds a match, a confidence score, or any write.

Everything is optional and independent, because the whole point is
dropping one filter at a time. That's why the WHERE clause is assembled
from a list of (sql_fragment, params) pairs rather than written out per
combination: a shop/location filter is one more pair appended to that
list, with no restructuring. Location is deliberately NOT filterable in
this version -- bronze.netsuite_vendorbill.location is a bare NetSuite
internal code (e.g. "65", 86 distinct values) and nothing in this repo
maps a code to a shop name, so a "JAS Auto" filter would have nothing
to resolve against. The raw code is returned for display only.

Facts this module relies on, all confirmed live against Fabric
2026-09-25 (re-check before changing any of them):

- EVERY column in both tables is stored as a string, including total
  ("114.54") and trandate ("6/9/2026"). Amount comparisons therefore go
  through TRY_CAST(... AS DECIMAL(18,2)), confirmed supported by the
  Lakehouse SQL endpoint in a WHERE clause (38 rows in 0.71s for a
  BETWEEN on 1.37M rows). TRY_CAST rather than CAST so one unparseable
  value can never fail the whole query -- currently 0 rows fail to cast
  in either table, but that's a property of today's data, not a
  guarantee from the source.

- Totals are stored POSITIVE on both tables (0 negative bill totals, 0
  negative credit totals out of 238,497). The statement side can carry a
  negative amount for a credit line, so the caller's target amount is
  compared on ABS().

- Bill status: 'A' = Open, 'B' = Paid In Full (see
  src/matching/netsuite_status_codes.py). Both tables are entirely
  voided = 'F', but that predicate is kept anyway -- matching applies it
  too, and a future load could introduce voided rows.

- vendorcredit has no status column. `unapplied` carries the credit's
  still-open amount: never NULL, always castable, and bounded by
  0 <= unapplied <= total (0 rows violate it). 14,333 of 239,820 rows
  have unapplied > 0, of which 14,283 are fully unapplied and 50 are
  partially applied. That is a coherent enough picture to treat
  `unapplied > 0` as "this credit is still open", which is what the
  open-only filter uses.
"""
import logging
import os

from src.lakehouse.fabric_sql import execute_lakehouse_query

logger = logging.getLogger(__name__)

BILL_TABLE = "netsuite_vendorbill"
CREDIT_TABLE = "netsuite_vendorcredit"

DEFAULT_LIMIT = 100

# "exact" is 0.01 rather than 0 because the amounts being compared came
# off a PDF and through a float, and an exact equality on a decimal cast
# would drop a legitimate tie-out for a half-cent of representation
# noise. Mirrors fabric_matching.EXACT_AMOUNT_EPSILON's reasoning.
TOLERANCES = ("exact", "1_dollar", "5_percent", "any")

# LIKE metacharacters for SQL Server. ']' is deliberately absent: it is
# only special INSIDE a [...] set, and escaping the '[' that opens one
# already defuses it. '^' and '-' are likewise only special inside a set.
_LIKE_SPECIALS = ("%", "_", "[")
_LIKE_ESCAPE = "\\"


def _fabric_configured() -> bool:
    """Same env gate fabric_matching._fabric_configured() uses, minus the
    Warehouse (this module only ever touches the Lakehouse)."""
    return bool(
        os.getenv("FABRIC_TENANT_ID")
        and os.getenv("FABRIC_CLIENT_ID")
        and os.getenv("FABRIC_CLIENT_SECRET")
        and os.getenv("FABRIC_SQL_ENDPOINT")
        and os.getenv("FABRIC_LAKEHOUSE_NAME")
    )


def escape_like(text: str) -> str:
    """Escapes LIKE metacharacters so the user's text matches literally.

    Without this, an invoice number containing '%' or '_' (both appear in
    real vendor numbering) silently becomes a wildcard, and a stray '['
    opens a character-class the user never intended. The backslash is
    declared to SQL Server via ESCAPE in the fragment that uses this."""
    escaped = text.replace(_LIKE_ESCAPE, _LIKE_ESCAPE + _LIKE_ESCAPE)
    for special in _LIKE_SPECIALS:
        escaped = escaped.replace(special, _LIKE_ESCAPE + special)
    return escaped


def amount_bounds(amount, tolerance: str):
    """Returns (low, high) for the target amount, or None when no amount
    filter applies. Compares on ABS(amount): a statement credit line
    carries a negative amount while NetSuite stores every total
    positive."""
    if amount is None or tolerance == "any":
        return None
    target = abs(float(amount))
    if tolerance == "1_dollar":
        margin = 1.00
    elif tolerance == "5_percent":
        margin = target * 0.05
    else:
        margin = 0.01
    return round(target - margin, 2), round(target + margin, 2)


def _entity_condition(entity_ids) -> tuple:
    placeholders = ",".join("?" * len(entity_ids))
    return (f"t.entity IN ({placeholders})", list(entity_ids))


def _amount_condition(bounds) -> tuple:
    return ("TRY_CAST(t.total AS DECIMAL(18,2)) BETWEEN ? AND ?", [bounds[0], bounds[1]])


def _invoice_condition(invoice_contains: str) -> tuple:
    pattern = f"%{escape_like(invoice_contains.strip())}%"
    return (f"LOWER(t.tranid) LIKE LOWER(?) ESCAPE '{_LIKE_ESCAPE}'", [pattern])


def _open_condition(table: str) -> tuple:
    """The "still open" predicate, which differs per table: bills carry a
    status code, credits carry a remaining-balance amount instead (see
    the module docstring's confirmed findings)."""
    if table == BILL_TABLE:
        return ("t.status = ?", ["A"])
    return ("TRY_CAST(t.unapplied AS DECIMAL(18,2)) > ?", [0])


def build_conditions(table: str, entity_ids=None, bounds=None,
                     invoice_contains=None, include_paid=False) -> list:
    """Assembles the WHERE clause as a list of (sql_fragment, params)
    pairs -- one pair per active filter, each independent of the others.

    A location/shop filter slots in here as one more append once a
    code-to-shop-name mapping exists; nothing else in this module needs
    to change for that."""
    conditions = [("t.voided = ?", ["F"]), ("t.tranid IS NOT NULL", [])]
    if entity_ids:
        conditions.append(_entity_condition(entity_ids))
    if bounds:
        conditions.append(_amount_condition(bounds))
    if invoice_contains and invoice_contains.strip():
        conditions.append(_invoice_condition(invoice_contains))
    if not include_paid:
        conditions.append(_open_condition(table))
    return conditions


def _select_for(table: str, conditions: list, limit: int) -> tuple:
    """Builds one table's SELECT. The only interpolated values are the
    module's own table-name constants and placeholder counts -- every
    user-supplied value travels as a bound parameter."""
    where_sql = " AND ".join(fragment for fragment, _ in conditions)
    params = [p for _, values in conditions for p in values]
    status_expr = "t.status" if table == BILL_TABLE else "NULL"
    unapplied_expr = "t.unapplied" if table == CREDIT_TABLE else "NULL"
    sql = f"""
        SELECT TOP {int(limit)}
            '{table}' AS source_table,
            t.tranid, t.entity, t.total, t.trandate, t.transactionnumber,
            t.custbody_cgh_ro, t.location,
            {status_expr} AS status_code,
            {unapplied_expr} AS unapplied_amount,
            v.companyname, v.entityid
        FROM bronze.{table} t
        LEFT JOIN bronze.netsuite_vendor v ON v.id = t.entity
        WHERE {where_sql}
    """
    return sql, params


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _status_label(row: dict) -> str:
    """Bill status codes decode via the shared NetSuite mapping. Credits
    have no status column, so their openness is stated in terms of the
    `unapplied` balance the open-filter itself keys on."""
    if row["source_table"] == BILL_TABLE:
        from src.matching.netsuite_status_codes import decode_netsuite_status

        return decode_netsuite_status(BILL_TABLE, row.get("status_code")) or (
            row.get("status_code") or "Unknown"
        )
    unapplied = _to_float(row.get("unapplied_amount"))
    if unapplied is None:
        return "Unknown"
    return "Open" if unapplied > 0 else "Fully Applied"


def _shape_row(row: dict) -> dict:
    """One raw Lakehouse row -> one display row for the results table."""
    return {
        "record_type": "Bill" if row["source_table"] == BILL_TABLE else "Credit",
        "tranid": row.get("tranid"),
        "vendor_name": row.get("companyname") or row.get("entityid") or "—",
        "entity_id": row.get("entity"),
        "total": _to_float(row.get("total")),
        "trandate": row.get("trandate"),
        "status_label": _status_label(row),
        "ro_number": row.get("custbody_cgh_ro"),
        "location_code": row.get("location"),
        "transaction_number": row.get("transactionnumber"),
    }


def _sort_key_by_amount(target: float):
    """Closest-to-target first. A row whose total didn't cast sorts last
    rather than crashing the comparison."""
    def key(row):
        if row["total"] is None:
            return (1, 0.0)
        return (0, abs(abs(row["total"]) - target))
    return key


def _sort_rows(rows: list, amount, bounds) -> list:
    """By closeness to the target amount when one was given, otherwise
    newest first. trandate is an unpadded M/D/YYYY string, so it is
    sorted on a parsed date -- a string sort would put "9/3/2026" before
    "10/1/2025"."""
    if amount is not None and bounds:
        return sorted(rows, key=_sort_key_by_amount(abs(float(amount))))
    return sorted(rows, key=_trandate_sort_key, reverse=True)


def _trandate_sort_key(row):
    from datetime import date, datetime

    raw = row.get("trandate")
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(raw).strip(), fmt).date()
        except (ValueError, TypeError):
            continue
    return date.min


# An invoice fragment this long or longer is selective enough to stand on
# its own as the only filter. Shorter than this it is not: "12" matches a
# large fraction of 1.37M tranids, which is the unscoped scan the
# guardrail exists to prevent. Counted on non-space characters so a
# padded "  12  " can't pass by virtue of its whitespace.
MIN_INVOICE_SEARCH_CHARS = 4


def _is_selective_invoice(invoice_contains) -> bool:
    """True when invoice_contains is specific enough to be the ONLY
    filter on a search."""
    if not invoice_contains:
        return False
    return len("".join(str(invoice_contains).split())) >= MIN_INVOICE_SEARCH_CHARS


def _needs_narrowing(entity_ids, bounds, invoice_contains=None) -> bool:
    """A search with no vendor, no amount and no usable invoice fragment
    would scan all 1.37M bill rows and return a meaningless slice of
    them. Refused before any query runs.

    A long-enough invoice fragment counts as narrowing on its own: an AP
    user hunting a specific number ("was this booked anywhere at all?")
    legitimately has neither a vendor nor an amount to offer, and that is
    exactly the "entered under a different vendor" case this panel
    exists for."""
    return not entity_ids and not bounds and not _is_selective_invoice(invoice_contains)


def _empty_result(**extra) -> dict:
    base = {"rows": [], "row_count": 0, "truncated": False, "error": False,
            "needs_filter": False, "message": None}
    base.update(extra)
    return base


def search_open_ap(entity_ids=None, amount=None, amount_tolerance="exact",
                   invoice_contains=None, include_paid=False,
                   limit=DEFAULT_LIMIT) -> dict:
    """Searches NetSuite bills and credits. Best-effort, like the rest of
    the Fabric code: never raises to the caller -- on failure it returns
    error=True and the UI shows "search unavailable".

    Every filter is optional. Returns a dict with rows (display-shaped,
    see _shape_row), row_count, truncated, error, needs_filter, message.
    """
    if amount_tolerance not in TOLERANCES:
        return _empty_result(error=True, message=f"Unknown amount tolerance: {amount_tolerance}")
    if not _fabric_configured():
        return _empty_result(error=True, message="NetSuite search is not configured.")

    bounds = amount_bounds(amount, amount_tolerance)
    if _needs_narrowing(entity_ids, bounds, invoice_contains):
        return _empty_result(
            needs_filter=True,
            message=(
                "Add a vendor, an amount, or at least "
                f"{MIN_INVOICE_SEARCH_CHARS} characters of an invoice number — "
                "searching all of NetSuite at once isn't possible."
            ),
        )

    try:
        rows = _run_search(entity_ids, bounds, invoice_contains, include_paid, limit)
    except Exception:
        logger.exception(
            "NetSuite open-AP search failed (entity_ids=%s amount=%s tolerance=%s invoice_contains=%r include_paid=%s)",
            entity_ids, amount, amount_tolerance, invoice_contains, include_paid,
        )
        return _empty_result(error=True, message="NetSuite search is unavailable right now.")

    ordered = _sort_rows(rows, amount, bounds)
    truncated = len(ordered) > limit
    return _empty_result(
        rows=ordered[:limit],
        row_count=min(len(ordered), limit),
        truncated=truncated,
    )


def _run_search(entity_ids, bounds, invoice_contains, include_paid, limit) -> list:
    """Queries both tables and returns the combined display rows.

    Two separate round-trips rather than a SQL UNION: the two tables have
    different open-ness predicates and different column sets, so a UNION
    would need the same NULL-padding done here anyway, and keeping them
    apart means a schema change to one table can't break the other's
    query. Each side is capped at `limit`, so the combined set is capped
    at 2x limit before sorting -- enough to sort meaningfully, and the
    caller trims to `limit` after.
    """
    rows = []
    for table in (BILL_TABLE, CREDIT_TABLE):
        conditions = build_conditions(
            table, entity_ids=entity_ids, bounds=bounds,
            invoice_contains=invoice_contains, include_paid=include_paid,
        )
        sql, params = _select_for(table, conditions, limit)
        rows.extend(_shape_row(raw) for raw in execute_lakehouse_query(sql, params))
    return rows
