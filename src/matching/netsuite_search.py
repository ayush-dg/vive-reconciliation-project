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
list, with no restructuring. Location is filterable since 2026-10-16:
bronze.netsuite_vendorbill.location is a bare NetSuite internal code
(e.g. "65"), and config/netsuite_locations.json -- NetSuite's own
location list, see src/netsuite/locations.py -- names each code, so the
Shop filter offers NetSuite's names and filters by code.

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
import time

from src.lakehouse.fabric_sql import execute_lakehouse_query
from src.netsuite.locations import location_names

logger = logging.getLogger(__name__)

BILL_TABLE = "netsuite_vendorbill"
CREDIT_TABLE = "netsuite_vendorcredit"

DEFAULT_LIMIT = 100

# "exact" is 0.01 rather than 0 because the amounts being compared came
# off a PDF and through a float, and an exact equality on a decimal cast
# would drop a legitimate tie-out for a half-cent of representation
# noise. Mirrors fabric_matching.EXACT_AMOUNT_EPSILON's reasoning.
#
# "any" is not offered as its own popover button any more (2026-09-30) --
# an EMPTY amount box means "no amount filter" regardless of which of the
# three buttons (Exact/Up to/At least) is selected -- but it stays the
# internal value amount_bounds() short-circuits on, since amount=None
# always resolves to "any" behaviour whatever `tolerance` string is
# passed in.
TOLERANCES = ("exact", "up_to", "at_least", "any")

# "1_dollar"/"5_percent" were removed from the popover 2026-09-30 (three
# buttons now: Exact/Up to/At least, plus an editable amount box). An
# old request or bookmark still using either must not error -- both
# behave exactly like "any" (see search_open_ap()'s own normalization).
REMOVED_TOLERANCES = ("1_dollar", "5_percent")

# M/D/YYYY -- trandate/duedate are stored as unpadded US-format strings,
# so every date comparison goes through TRY_CONVERT(..., 101). Confirmed
# live 2026-09-28: 0 unconvertible non-null values across both tables
# (1,373,553 bills + 240,175 credits), and the expression is accepted in
# both WHERE and ORDER BY on the Lakehouse SQL endpoint.
_DATE_STYLE = 101
_DATE_EXPR = "TRY_CONVERT(date, {col}, 101)"

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
    """Returns (low, high) for the target amount -- high=None means
    open-ended ("at least") -- or None when no amount filter applies at
    all. That's either because the box is empty (amount is None, checked
    first and short-circuiting regardless of which tolerance button is
    selected) or tolerance == "any" (kept as the internal "no filter"
    value; not offered as its own popover button any more -- see
    TOLERANCES). Compares on ABS(amount): a statement credit line carries
    a negative amount while NetSuite stores every total positive.

    "up_to" is Ramp's "<= $199" shape -- an open-ended lower bound, for
    "this invoice is somewhere at or below the statement amount, possibly
    split across bills". "at_least" is its mirror, ">= $199" -- for when
    the real NetSuite total turned out to be HIGHER than the statement
    amount (confirmed live 2026-09-30: a real Amount Mismatch exception
    whose actual bill total exceeded the statement amount -- "up_to"
    alone could never have surfaced it)."""
    if amount is None or tolerance == "any" or tolerance in REMOVED_TOLERANCES:
        return None
    target = abs(float(amount))
    if tolerance == "up_to":
        return 0.0, round(target, 2)
    if tolerance == "at_least":
        return round(target, 2), None
    # "exact" -- 0.01 rather than 0 because the amount being compared came
    # off a PDF and through a float, and an exact equality on a decimal
    # cast would drop a legitimate tie-out for a half-cent of
    # representation noise. Mirrors fabric_matching.EXACT_AMOUNT_EPSILON's
    # reasoning.
    return round(target - 0.01, 2), round(target + 0.01, 2)


def _entity_condition(entity_ids) -> tuple:
    placeholders = ",".join("?" * len(entity_ids))
    return (f"t.entity IN ({placeholders})", list(entity_ids))


def _location_condition(locations) -> tuple:
    """The Shop filter (2026-10-16): NetSuite location codes, as the
    Lakehouse stores them (strings like "64") -- see src/netsuite/locations.py."""
    placeholders = ",".join("?" * len(locations))
    return (f"t.location IN ({placeholders})", [str(code) for code in locations])


def _amount_condition(bounds) -> tuple:
    low, high = bounds
    if high is None:
        # "at_least" -- open-ended upper bound.
        return ("TRY_CAST(t.total AS DECIMAL(18,2)) >= ?", [low])
    return ("TRY_CAST(t.total AS DECIMAL(18,2)) BETWEEN ? AND ?", [low, high])


def _invoice_condition(invoice_contains: str) -> tuple:
    pattern = f"%{escape_like(invoice_contains.strip())}%"
    return (f"LOWER(t.tranid) LIKE LOWER(?) ESCAPE '{_LIKE_ESCAPE}'", [pattern])


def _date_condition(date_from, date_to) -> tuple:
    """Inclusive trandate range. One more (fragment, params) pair, exactly
    like every other filter -- both ends are optional and independent."""
    fragments, params = [], []
    expr = _DATE_EXPR.format(col="t.trandate")
    if date_from:
        fragments.append(f"{expr} >= ?")
        params.append(date_from)
    if date_to:
        fragments.append(f"{expr} <= ?")
        params.append(date_to)
    return (" AND ".join(fragments), params)


def _open_condition(table: str) -> tuple:
    """The "still open" predicate, which differs per table: bills carry a
    status code, credits carry a remaining-balance amount instead (see
    the module docstring's confirmed findings)."""
    if table == BILL_TABLE:
        return ("t.status = ?", ["A"])
    return ("TRY_CAST(t.unapplied AS DECIMAL(18,2)) > ?", [0])


def _paid_condition(table: str) -> tuple:
    """The "paid" predicate -- bill status 'B' ("Paid In Full"); a
    credit's remaining balance at or below zero (never negative --
    confirmed live: 0 rows violate 0 <= unapplied <= total)."""
    if table == BILL_TABLE:
        return ("t.status = ?", ["B"])
    return ("TRY_CAST(t.unapplied AS DECIMAL(18,2)) <= ?", [0])


# The Status chip's two checkboxes. Confirmed live 2026-09-30: real bill
# status codes are NOT limited to A (Open, 57,196 rows)/B (Paid In Full,
# 1,319,634 rows) -- 19 rows carry 'C' and 6 carry 'E', neither mapped in
# netsuite_status_codes.py, shown with their raw code via the results
# table's "other" pill. Credits have no third state (always Open or
# Paid, by construction of the unapplied-balance predicate above).
STATUSES = ("open", "paid")


def _status_condition(table: str, statuses):
    """Returns a (fragment, params) pair for the ticked status set, or
    None for no predicate at all. Ticking BOTH Open and Paid is
    deliberately treated as "no predicate" (identical to the old
    include_paid=True), not "status IN (open, paid)" -- the latter would
    newly exclude the handful of real C/E-status bills above, silently
    narrowing what "both boxes ticked" has always shown. An
    empty/unrecognised set defaults to Open only, same as no boxes ever
    being ticked wasn't a real state the UI allows (see
    web/routers/exceptions.py's _parse_statuses())."""
    statuses = frozenset(s for s in (statuses or ()) if s in STATUSES)
    if statuses == frozenset(STATUSES):
        return None
    if statuses == {"paid"}:
        return _paid_condition(table)
    return _open_condition(table)  # {"open"} or empty/unrecognised


def build_conditions(table: str, entity_ids=None, bounds=None,
                     invoice_contains=None, statuses=None,
                     date_from=None, date_to=None, locations=None) -> list:
    """Assembles the WHERE clause as a list of (sql_fragment, params)
    pairs -- one pair per active filter, each independent of the others.
    `locations` (NetSuite location codes, the Shop filter) is one more
    such pair since 2026-10-16."""
    conditions = [("t.voided = ?", ["F"]), ("t.tranid IS NOT NULL", [])]
    if entity_ids:
        conditions.append(_entity_condition(entity_ids))
    if locations:
        conditions.append(_location_condition(locations))
    if bounds:
        conditions.append(_amount_condition(bounds))
    if invoice_contains and invoice_contains.strip():
        conditions.append(_invoice_condition(invoice_contains))
    if date_from or date_to:
        conditions.append(_date_condition(date_from, date_to))
    status_condition = _status_condition(table, statuses)
    if status_condition:
        conditions.append(status_condition)
    return conditions


def build_order_by(sort_amount) -> tuple:
    """Returns (order_by_sql, params) -- the ORDER BY that must be applied
    IN SQL, before TOP.

    This exists because of a real bug: the query used to be `SELECT TOP
    100 ... WHERE ...` with NO ORDER BY, and the ranking was done in
    Python on whatever 100 rows came back. With no ORDER BY, SQL Server
    is free to return ANY 100 matching rows, so the ranking only ever
    reordered an arbitrary sample. Confirmed live 2026-09-28 on a real
    search (Keystone, vendor ON, amount ANY, open only): 4,247 rows match
    but only 100 are returned, and 19 of the 20 genuinely-closest bills
    were absent from that 100 -- the closest the UI could show was $3.29
    away from the statement amount when a bill $0.03 away existed.

    sort_amount is deliberately separate from the amount FILTER: the
    modal ranks by closeness to the statement amount even when the user
    has widened the amount filter to "any", which is the whole point of
    being able to widen it."""
    if sort_amount is not None:
        return ("ABS(ABS(TRY_CAST(t.total AS DECIMAL(18,2))) - ?) ASC", [abs(float(sort_amount))])
    return (f"{_DATE_EXPR.format(col='t.trandate')} DESC", [])


def _select_for(table: str, conditions: list, limit: int, order_by: tuple) -> tuple:
    """Builds one table's SELECT. The only interpolated values are the
    module's own table-name constants, the ORDER BY expression this
    module itself built, and placeholder counts -- every user-supplied
    value travels as a bound parameter.

    ORDER BY is applied here, in SQL, so TOP selects the best N rather
    than an arbitrary N -- see build_order_by() for the bug this fixes."""
    where_sql = " AND ".join(fragment for fragment, _ in conditions)
    params = [p for _, values in conditions for p in values]
    order_sql, order_params = order_by
    status_expr = "t.status" if table == BILL_TABLE else "NULL"
    unapplied_expr = "t.unapplied" if table == CREDIT_TABLE else "NULL"
    sql = f"""
        SELECT TOP {int(limit)}
            '{table}' AS source_table,
            t.id, t.tranid, t.entity, t.total, t.trandate, t.duedate, t.transactionnumber,
            t.custbody_cgh_ro, t.location,
            {status_expr} AS status_code,
            {unapplied_expr} AS unapplied_amount,
            v.companyname, v.entityid
        FROM bronze.{table} t
        LEFT JOIN bronze.netsuite_vendor v ON v.id = t.entity
        WHERE {where_sql}
        ORDER BY {order_sql}
    """
    # ORDER BY parameters bind AFTER the WHERE ones -- pyodbc binds "?" by
    # position, and the WHERE clause is emitted first.
    return sql, params + order_params


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
        "is_credit": row["source_table"] == CREDIT_TABLE,
        "tranid": row.get("tranid"),
        # NetSuite internal id (2026-10-19): what "Accept as match" sends
        # back, so the server re-reads the exact record (fetch_record()).
        "internal_id": None if row.get("id") is None else str(row.get("id")),
        "vendor_name": row.get("companyname") or row.get("entityid") or "—",
        "entity_id": row.get("entity"),
        "total": _to_float(row.get("total")),
        "trandate": row.get("trandate"),
        "trandate_display": _display_date(row.get("trandate")),
        # Credits almost never carry one -- confirmed live 2026-09-28:
        # non-null on 74 of 240,175 credit rows (0.03%) vs essentially
        # every bill. The template omits the "Due ..." clause when this
        # is empty rather than printing a bare label.
        "duedate": row.get("duedate"),
        "duedate_display": _display_date(row.get("duedate")),
        "status_label": _status_label(row),
        "ro_number": row.get("custbody_cgh_ro"),
        "location_code": row.get("location"),
        "location_name": location_names().get(str(row.get("location"))) if row.get("location") is not None else None,
        "transaction_number": row.get("transactionnumber"),
    }


def _parse_us_date(raw):
    """Parses NetSuite's unpadded M/D/YYYY (or an ISO date) into a date,
    or None. Display and sorting both go through this rather than string
    comparison -- "9/3/2026" sorts before "10/1/2025" as a string."""
    from datetime import datetime

    if raw is None:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(raw).strip(), fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def _display_date(raw):
    """"9/23/2026" -> "Sep 23, 2026". Falls back to the raw string when it
    can't be parsed, so nothing is ever hidden from the user. This is a
    NetSuite business date, not a system timestamp -- no timezone
    conversion applies (see web/deps.py's friendly_date for the same
    distinction)."""
    parsed = _parse_us_date(raw)
    if parsed is None:
        return str(raw) if raw else ""
    return parsed.strftime("%b %d, %Y").replace(" 0", " ")


def _sort_key_by_amount(target: float):
    """Closest-to-target first. A row whose total didn't cast sorts last
    rather than crashing the comparison."""
    def key(row):
        if row["total"] is None:
            return (1, 0.0)
        return (0, abs(abs(row["total"]) - target))
    return key


def _trandate_sort_key(row):
    from datetime import date

    return _parse_us_date(row.get("trandate")) or date.min


def _sort_rows(rows: list, sort_amount) -> list:
    """Re-applies the SQL ORDER BY across the MERGED bill+credit result.

    The ordering that matters for correctness is the one in SQL (see
    build_order_by) -- that decides WHICH rows come back. This second
    pass only interleaves the two already-correct per-table lists, which
    SQL can't do for us because they are two separate queries."""
    if sort_amount is not None:
        return sorted(rows, key=_sort_key_by_amount(abs(float(sort_amount))))
    return sorted(rows, key=_trandate_sort_key, reverse=True)


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
            "needs_filter": False, "message": None, "source": SOURCE_FABRIC}
    base.update(extra)
    return base


def parse_iso_date(value, label: str):
    """Returns (yyyy_mm_dd_or_None, error_message_or_None). An empty value
    is a legitimate "no bound", not an error."""
    from datetime import datetime

    if value is None or str(value).strip() == "":
        return None, None
    text = str(value).strip()
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat(), None
    except ValueError:
        return None, f"{label} must look like 2026-09-28."


def _validate_dates(date_from, date_to):
    """Returns (from, to, error_message_or_None), including the
    from-after-to case, which is a user mistake rather than a query that
    should silently return nothing."""
    parsed_from, err = parse_iso_date(date_from, "Date from")
    if err:
        return None, None, err
    parsed_to, err = parse_iso_date(date_to, "Date to")
    if err:
        return None, None, err
    if parsed_from and parsed_to and parsed_from > parsed_to:
        return None, None, "The start date is after the end date."
    return parsed_from, parsed_to, None


def search_open_ap(entity_ids=None, amount=None, amount_tolerance="exact",
                   invoice_contains=None, statuses=None,
                   sort_amount=None, date_from=None, date_to=None,
                   locations=None, limit=DEFAULT_LIMIT) -> dict:
    """Searches NetSuite bills and credits. Best-effort, like the rest of
    the Fabric code: never raises to the caller -- on failure it returns
    error=True and the UI shows "search unavailable".

    `amount` + `amount_tolerance` FILTER; `sort_amount` only RANKS. They
    are separate because the modal keeps ranking by closeness to the
    statement amount even once the user widens the amount filter to
    "any" -- which is exactly when good ranking matters most. Ranking is
    therefore NOT narrowing, and sort_amount alone does not satisfy the
    guardrail.

    `statuses` (STATUSES membership, e.g. {"open"}/{"paid"}/{"open","paid"})
    replaced the old include_paid bool 2026-09-30 -- see
    _status_condition()'s own docstring for what each combination means.

    `locations` (NetSuite location codes) narrows to those shops but, like
    sorting, doesn't satisfy the guardrail on its own: one shop can hold
    tens of thousands of bills.

    Every filter is optional. Returns a dict with rows (display-shaped,
    see _shape_row), row_count, truncated, error, needs_filter, message.
    """
    # "1_dollar"/"5_percent" no longer exist as popover options, but an
    # old request/bookmark using either must still work, behaving exactly
    # like "any" (no amount filter) rather than erroring.
    if amount_tolerance in REMOVED_TOLERANCES:
        amount_tolerance = "any"
    if amount_tolerance not in TOLERANCES:
        return _empty_result(error=True, message=f"Unknown amount tolerance: {amount_tolerance}")
    source = search_source()
    if source == SOURCE_FABRIC and not _fabric_configured():
        return _empty_result(error=True, message="NetSuite search is not configured.")

    parsed_from, parsed_to, date_error = _validate_dates(date_from, date_to)
    if date_error:
        return _empty_result(error=True, message=date_error)

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

    args = (entity_ids, bounds, invoice_contains, statuses, sort_amount, parsed_from, parsed_to, limit, locations)
    rows = None
    if source == SOURCE_CONNECT:
        try:
            rows = _run_search_connect(*args)
        except Exception:
            # Live NetSuite failed: answer from the nightly copy and say so.
            logger.warning("Live NetSuite search failed -- using the Fabric copy", exc_info=True)
            source = SOURCE_FALLBACK
    try:
        if rows is None:
            if not _fabric_configured():
                return _empty_result(error=True, message="NetSuite search is unavailable right now.", source=source)
            rows = _run_search(*args)
    except Exception:
        logger.exception(
            "NetSuite open-AP search failed (entity_ids=%s amount=%s tolerance=%s "
            "invoice_contains=%r statuses=%s sort_amount=%s date_from=%s date_to=%s locations=%s)",
            entity_ids, amount, amount_tolerance, invoice_contains, statuses,
            sort_amount, parsed_from, parsed_to, locations,
        )
        return _empty_result(error=True, message="NetSuite search is unavailable right now.", source=source)

    ordered = _sort_rows(rows, sort_amount)
    truncated = len(ordered) > limit
    return _empty_result(
        rows=ordered[:limit],
        row_count=min(len(ordered), limit),
        truncated=truncated,
        source=source,
    )


def _run_search(entity_ids, bounds, invoice_contains, statuses,
                sort_amount, date_from, date_to, limit, locations=None) -> list:
    """Queries both tables and returns the combined display rows.

    Two separate round-trips rather than a SQL UNION: the two tables have
    different open-ness predicates and different column sets, so a UNION
    would need the same NULL-padding done here anyway, and keeping them
    apart means a schema change to one table can't break the other's
    query. Each side is ordered and capped in SQL, so the combined set is
    the best `limit` from each table; _sort_rows() then interleaves them
    and the caller trims to `limit`.
    """
    order_by = build_order_by(sort_amount)
    rows = []
    for table in (BILL_TABLE, CREDIT_TABLE):
        conditions = build_conditions(
            table, entity_ids=entity_ids, bounds=bounds,
            invoice_contains=invoice_contains, statuses=statuses,
            date_from=date_from, date_to=date_to, locations=locations,
        )
        sql, params = _select_for(table, conditions, limit, order_by)
        rows.extend(_shape_row(raw) for raw in execute_lakehouse_query(sql, params))
    return rows


def fetch_record(record_type: str, internal_id: str):
    """One NetSuite bill or credit by internal id, display-shaped like a
    search row (_shape_row()), or None -- what "Accept as match" re-reads so
    the match is saved from the record itself, not from what the page sent.
    Read-only; raises on a Fabric error (the caller reports it)."""
    table = {"bill": BILL_TABLE, "credit": CREDIT_TABLE}.get((record_type or "").lower())
    if not table or not str(internal_id or "").isdigit():
        return None
    if search_source() == SOURCE_CONNECT:
        # The record as NetSuite has it now (2026-10-27); the Fabric copy
        # only if the live read fails.
        try:
            return _fetch_record_connect(table, internal_id)
        except Exception:
            logger.warning("Live NetSuite read of %s %s failed -- using the Fabric copy",
                           record_type, internal_id, exc_info=True)
    status_expr = "t.status" if table == BILL_TABLE else "NULL"
    unapplied_expr = "t.unapplied" if table == CREDIT_TABLE else "NULL"
    rows = execute_lakehouse_query(
        f"""
        SELECT '{table}' AS source_table,
            t.id, t.tranid, t.entity, t.total, t.trandate, t.duedate, t.transactionnumber,
            t.custbody_cgh_ro, t.location,
            {status_expr} AS status_code,
            {unapplied_expr} AS unapplied_amount,
            v.companyname, v.entityid
        FROM bronze.{table} t
        LEFT JOIN bronze.netsuite_vendor v ON v.id = t.entity
        WHERE t.id = ? AND t.voided = 'F'
        """,
        [str(internal_id)],
    )
    return _shape_row(rows[0]) if rows else None


# --- Live NetSuite (SuiteAnalytics Connect), 2026-10-27 ----------------------
#
# NETSUITE_SEARCH_SOURCE=connect|fabric picks where this search reads from;
# unset, it follows NETSUITE_SOURCE (the matching switch). Live rows come
# from NetSuite2.com through src/netsuite/connect_client.py (read-only), in
# the same row shape as the Fabric copy, so _shape_row() and everything
# after it are unchanged. Confirmed live 2026-10-27 against production:
#   - one `transaction` table, type 'VendBill' / 'VendCred'; amounts are
#     ABS(foreigntotal); bill status codes A/B (+ a few C/E, as in Fabric),
#     which a WHERE must spell 'VendBill:A' / 'VendBill:B';
#   - the shop is on the main line (transactionline.mainline = 'T');
#   - a credit's still-open amount is that main line's
#     foreignpaymentamountunused (the Fabric copy's `unapplied`: 17.63 on
#     MN847143 in both) -- every credit's own status is just 'Y';
#   - TOP, ? parameters, LOWER(...) LIKE ... ESCAPE '\\' and
#     TO_DATE(?, 'YYYY-MM-DD') all work; a bare date string does not.
# A failed live search falls back to the Fabric copy and says so.

SOURCE_FABRIC, SOURCE_CONNECT, SOURCE_FALLBACK = "fabric", "connect", "fabric_fallback"
# A live search gets this many seconds in all (both tables, and any wait for
# the shared connection) before it falls back to the Fabric copy (2026-10-29)
# -- it used to wait as long as NetSuite did, past Azure's ~4 min request
# limit (504). NETSUITE_SEARCH_TIMEOUT_SECONDS overrides it.
DEFAULT_SEARCH_TIMEOUT_SECONDS = 25
_TYPE_BY_TABLE = {BILL_TABLE: "VendBill", CREDIT_TABLE: "VendCred"}
_CONNECT_LIKE_SPECIALS = ("%", "_")


def search_source() -> str:
    """'connect' or 'fabric' for this search (see the block comment above)."""
    value = (os.getenv("NETSUITE_SEARCH_SOURCE") or "").strip().lower()
    if value in (SOURCE_FABRIC, SOURCE_CONNECT):
        return value
    from src.netsuite.connect_source import netsuite_source
    return netsuite_source()


def search_timeout() -> float:
    try:
        value = float(os.getenv("NETSUITE_SEARCH_TIMEOUT_SECONDS") or DEFAULT_SEARCH_TIMEOUT_SECONDS)
    except ValueError:
        return DEFAULT_SEARCH_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_SEARCH_TIMEOUT_SECONDS


def _connect_escape_like(text: str) -> str:
    """LIKE escaping for Connect: only % and _ are special there."""
    escaped = text.replace(_LIKE_ESCAPE, _LIKE_ESCAPE + _LIKE_ESCAPE)
    for special in _CONNECT_LIKE_SPECIALS:
        escaped = escaped.replace(special, _LIKE_ESCAPE + special)
    return escaped


def _digits(values) -> list:
    """Ids for Connect (numbers there): digits only, anything else dropped."""
    return [int(str(v).strip()) for v in values or [] if str(v).strip().isdigit()]


def build_connect_select(table: str, entity_ids=None, bounds=None, invoice_contains=None,
                         statuses=None, date_from=None, date_to=None, locations=None,
                         limit: int = DEFAULT_LIMIT, sort_amount=None) -> tuple:
    """(sql, params) for one table on live NetSuite, the same filters as
    build_conditions(). Every user value is a bound parameter except the
    sort amount, which is formatted from a float here (Connect does not take
    parameters in ORDER BY)."""
    where = ["t.type = ?", "t.voided = 'F'", "t.tranid IS NOT NULL"]
    params = [_TYPE_BY_TABLE[table]]
    entities = _digits(entity_ids)
    if entity_ids is not None and entity_ids and not entities:
        where.append("1 = 0")  # ids given but none usable -> nothing, never everything
    elif entities:
        where.append(f"t.entity IN ({','.join('?' * len(entities))})")
        params += entities
    codes = _digits(locations)
    if codes:
        where.append(f"tl.location IN ({','.join('?' * len(codes))})")
        params += codes
    if bounds:
        low, high = bounds
        if high is None:
            where.append("ABS(t.foreigntotal) >= ?")
            params.append(low)
        else:
            where.append("ABS(t.foreigntotal) BETWEEN ? AND ?")
            params += [low, high]
    if invoice_contains and invoice_contains.strip():
        where.append(f"LOWER(t.tranid) LIKE LOWER(?) ESCAPE '{_LIKE_ESCAPE}'")
        params.append(f"%{_connect_escape_like(invoice_contains.strip())}%")
    if date_from:
        where.append("t.trandate >= TO_DATE(?, 'YYYY-MM-DD')")
        params.append(date_from)
    if date_to:
        where.append("t.trandate <= TO_DATE(?, 'YYYY-MM-DD')")
        params.append(date_to)
    chosen = frozenset(s for s in (statuses or ()) if s in STATUSES)
    if chosen != frozenset(STATUSES):
        paid = chosen == {"paid"}
        if table == BILL_TABLE:
            # Filtered as "VendBill:A" / "VendBill:B"; a bare "A" matches
            # nothing, though rows display as "A" (confirmed live 2026-10-27).
            where.append("t.status = ?")
            params.append("VendBill:B" if paid else "VendBill:A")
        elif paid:
            where.append("(tl.foreignpaymentamountunused IS NULL OR tl.foreignpaymentamountunused <= 0)")
        else:
            where.append("tl.foreignpaymentamountunused > 0")
    if sort_amount is not None:
        order = f"ABS(ABS(t.foreigntotal) - {abs(float(sort_amount)):.2f}) ASC"
    else:
        order = "t.trandate DESC"
    status_expr = "t.status" if table == BILL_TABLE else "NULL"
    unapplied_expr = "tl.foreignpaymentamountunused" if table == CREDIT_TABLE else "NULL"
    sql = (
        f"SELECT TOP {int(limit)} t.id, t.tranid, t.entity, ABS(t.foreigntotal) AS total, t.trandate, t.duedate, "
        f"t.transactionnumber, t.custbody_cgh_ro, tl.location, {status_expr} AS status_code, "
        f"{unapplied_expr} AS unapplied_amount, v.companyname, v.entityid "
        "FROM transaction t "
        "LEFT JOIN transactionline tl ON tl.transaction = t.id AND tl.mainline = 'T' "
        "LEFT JOIN vendor v ON v.id = t.entity "
        f"WHERE {' AND '.join(where)} ORDER BY {order}"
    )
    return sql, params


def _connect_rows(sql: str, params: list, table: str, deadline: float = None) -> list:
    """Rows from live NetSuite, given until `deadline` (time.monotonic()) --
    QueryTimeout past it, which the callers turn into the Fabric fallback."""
    from src.netsuite.connect_client import QueryTimeout, get_shared_client
    if deadline is None:
        deadline = time.monotonic() + search_timeout()
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise QueryTimeout("NetSuite search ran out of time")
    rows = []
    for raw in get_shared_client().query(sql, params, timeout=remaining):
        row = dict(raw, source_table=table)
        for key in ("trandate", "duedate"):
            if hasattr(row.get(key), "strftime"):
                row[key] = row[key].strftime("%Y-%m-%d")
        rows.append(row)
    return rows


def _run_search_connect(entity_ids, bounds, invoice_contains, statuses,
                        sort_amount, date_from, date_to, limit, locations=None) -> list:
    """_run_search() on live NetSuite: one capped, ordered query per table,
    both within one search_timeout()."""
    deadline = time.monotonic() + search_timeout()
    rows = []
    for table in (BILL_TABLE, CREDIT_TABLE):
        sql, params = build_connect_select(table, entity_ids, bounds, invoice_contains, statuses,
                                           date_from, date_to, locations, limit, sort_amount)
        rows.extend(_shape_row(raw) for raw in _connect_rows(sql, params, table, deadline))
    return rows


def _fetch_record_connect(table: str, internal_id: str):
    sql = (
        f"SELECT t.id, t.tranid, t.entity, ABS(t.foreigntotal) AS total, t.trandate, t.duedate, "
        f"t.transactionnumber, t.custbody_cgh_ro, tl.location, "
        f"{'t.status' if table == BILL_TABLE else 'NULL'} AS status_code, "
        f"{'tl.foreignpaymentamountunused' if table == CREDIT_TABLE else 'NULL'} AS unapplied_amount, "
        "v.companyname, v.entityid "
        "FROM transaction t "
        "LEFT JOIN transactionline tl ON tl.transaction = t.id AND tl.mainline = 'T' "
        "LEFT JOIN vendor v ON v.id = t.entity "
        "WHERE t.id = ? AND t.type = ? AND t.voided = 'F'"
    )
    rows = _connect_rows(sql, [int(internal_id), _TYPE_BY_TABLE[table]], table)
    return _shape_row(rows[0]) if rows else None
