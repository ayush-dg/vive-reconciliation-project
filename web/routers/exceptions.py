"""
exceptions.py

Exceptions vendors overview (/exceptions) and per-vendor review
(/exceptions/{vendor_name}). Actioning an exception writes a row to
exception_dispositions and marks the gold_exceptions row RESOLVED, then
redirects back to the same vendor so the next open exception is shown.

Also hosts GET /netsuite-search, the review page's open-AP search panel
(read-only -- see src/matching/netsuite_search.py). That route lives at
the top level, NOT under /exceptions/, because
/exceptions/{vendor_name:path} is a catch-all that would otherwise
swallow it whole (a :path converter matches slashes too, so no sub-path
under /exceptions/ is safe from it).
"""

from urllib.parse import quote, unquote, urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from web.deps import render, require_login, sidebar_context, smart_title, location_group_key
from web import queries
from web import time_window as tw
from src.vendor_identity import display_name as vendor_display_name
from src.matching.fabric_matching import fetch_netsuite_record_for_invoice
from src.matching.netsuite_search import TOLERANCES, REMOVED_TOLERANCES, STATUSES, search_open_ap
from src.matching.netsuite_status_codes import decode_netsuite_status
from src.matching.netsuite_vendor_resolver import resolve_entity_ids

router = APIRouter()

# The exception reasons that mean "this line did not tie out to a
# NetSuite record", which are exactly the cases worth hand-searching for.
# "Invoice Missing" is the legacy gold_exceptions spelling of "Not Found
# in NetSuite" -- both kept for the same reason queries._REASON_FILTER_SQL
# keeps both. "Vendor Not Resolved in NetSuite" is deliberately absent:
# with no entity ids there is no vendor filter to pre-fill, so the search
# would open unscoped and immediately hit the no-filter guardrail.
SEARCHABLE_REASONS = ("Not Found in NetSuite", "Invoice Missing", "Amount Mismatch")

REASON_BADGE = {
    "Invoice Missing": {"label": "Missing in ERP", "css": "exception"},
    "Amount Mismatch": {"label": "Amount mismatch", "css": "review"},
    "EXTRACTION_INCOMPLETE": {"label": "Extraction incomplete", "css": "grey"},
    "DUPLICATE_RECORD": {"label": "Duplicate record", "css": "exception"},
    # New reasons from src/matching/fabric_matching.py's NetSuite matching.
    "Not Found in NetSuite": {"label": "Not found in NetSuite", "css": "exception"},
    "Vendor Not Resolved in NetSuite": {"label": "Vendor not resolved", "css": "grey"},
}

# Bulk approve only ever targets exceptions the matching engine scored
# very high confidence — see queries.get_high_confidence_exception_count()
# and src/matching/engine.py's EXCEPTION_MATCH_CONFIDENCE. Deliberately
# the highest possible bar: today's highest-scoring exception type
# (Invoice Missing) tops out at 0.90, so at 0.99 nothing currently
# qualifies — that's intentional, not a bug; see
# get_high_confidence_exception_count()'s docstring.
BULK_APPROVE_THRESHOLD = 0.99

# Exceptions overview's time filter (2026-09-30) -- same controls, the
# same web/time_window.py definitions and (since 2026-10-01) the same
# "last" default as Home (see dashboard.py's own RANGE_CHIPS).
EXCEPTIONS_RANGE_CHIPS = (("today", "Today"), ("last", "Last run"))


def exceptions_url(filters: dict, **changes) -> str:
    """"/exceptions?..." for the current time-window filters with
    `changes` applied -- vendor/shop/location stay purely client-side
    (see exceptions_vendors.html), so this only ever carries range/date/
    month. "last" is this page's default, same as Home's, and so is left
    out of the URL."""
    merged = {**filters, **changes}
    params = []
    if merged.get("range") and merged["range"] != tw.DEFAULT_RANGE:
        params.append(("range", merged["range"]))
    if merged.get("range") == "date" and merged.get("date"):
        params.append(("date", merged["date"]))
    if merged.get("range") == "month" and merged.get("month"):
        params.append(("month", merged["month"]))
    if merged.get("sync"):
        # Same as dashboard.py's home_url(): spell "range=last" out
        # explicitly whenever a sync is chosen.
        if not any(p[0] == "range" for p in params):
            params.append(("range", "last"))
        params.append(("sync", merged["sync"]))
    return "/exceptions" + (f"?{urlencode(params)}" if params else "")


@router.get("/exceptions")
def exceptions_vendors(request: Request, user: str = Depends(require_login),
                       range: str = "", date: str = "", month: str = "", sync: str = ""):
    timestamps = queries.get_run_timestamps()
    outlook_jobs = queries.get_outlook_synced_jobs()
    sync_options, sync_truncated = tw.outlook_sync_options(outlook_jobs)
    # Time filter (2026-09-30) -- same controls/definitions as Home, and
    # (since 2026-10-01) the same "last" default: the most recent Outlook
    # sync, not the full backlog. But "Last run" means nothing when there's
    # never been a run, so an empty sync history falls back to "all" --
    # showing everything instead of an effectively-empty page (found on
    # dev, which had no Outlook syncs yet). ?date=/?month= alone still
    # imply their own range, same as Home; anything else unrecognised
    # falls back to the same default.
    default_range = "last" if sync_options else "all"
    range_param = range or None
    if range_param and range_param not in tw.RANGES:
        range_param = default_range
    if not range_param and not date and not month:
        range_param = default_range
    window = tw.resolve_window(range_param, date or None, month or None,
                               timestamps=timestamps, outlook_jobs=outlook_jobs, sync_=sync or None)

    # get_exception_runs() -- one card per statement RUN (every PDF ever
    # reconciled), not one per vendor -- see its docstring. Already
    # attaches "aging"/"reason_breakdown" via batched queries the same way
    # get_vendor_summaries() used to for the old vendor-rollup version.
    # Exceptions-only vendors (no run timestamp/statement_id at all) are
    # appended inside get_exception_runs() AFTER the window filter, so
    # they always show and always count below, regardless of `window`.
    runs = queries.get_exception_runs(window)
    summary_backed_count = sum(1 for v in runs if v.get("statement_id"))
    for v in runs:
        v["url_name"] = quote(v["vendor_name"] or "", safe="")
        # Display-only casing normalization -- vendor_name (the canonical
        # identifier used for routing/lookups above) is left untouched;
        # only the human-facing display fields are reshaped, so every
        # vendor/shop/location renders in consistent Title Case
        # regardless of how that vendor's own PDF happened to print it
        # (ALL CAPS, all lowercase, etc.) -- confirmed 2026-09-21 this
        # varied wildly card to card. Applied here (not in the query
        # layer) so it also normalizes the filter dropdown options and
        # data-* attributes built from these same fields below, keeping
        # filtering and display in sync.
        v["vendor_display_name"] = smart_title(v.get("vendor_display_name"))
        v["shop"] = smart_title(v.get("shop"))
        v["billing_location"] = smart_title(v.get("billing_location"))

    # Location canonicalization -- billing_location has no alias system
    # the way vendor_name does (config/vendor_aliases.json), so the exact
    # same place extracted as "Springfield, MA" on one statement and
    # "Springfield MA" on another (confirmed live 2026-09-22) would
    # otherwise show up as two separate filter options and two different
    # card labels. Groups every run's already-smart_title'd billing_location
    # by location_group_key() (case/comma/whitespace-insensitive) and
    # reassigns all of them to one canonical display string per group --
    # done here (not in the query layer) so the filter dropdown options and
    # each card's data-location attribute (built from these same values
    # below) stay in sync, same reasoning as the vendor/shop normalization
    # above.
    canonical_location_by_key = {}
    for v in runs:
        key = location_group_key(v.get("billing_location"))
        if key and key not in canonical_location_by_key:
            canonical_location_by_key[key] = v["billing_location"]
    for v in runs:
        key = location_group_key(v.get("billing_location"))
        if key:
            v["billing_location"] = canonical_location_by_key[key]

    runs_with_ex = [v for v in runs if v["exception_count"] > 0]
    total_open = sum(v["exception_count"] for v in runs_with_ex)

    # Filter dropdown options -- distinct vendor/shop/location values
    # actually present, so the <select>s never offer a choice with zero
    # cards behind it. Sorted, blanks/None excluded (a run can genuinely
    # have no shop yet -- see fabric_matching.py's header["shop_name_raw"] --
    # or no billing_location, e.g. anything routed through Foundry/Claude
    # Sonnet extraction rather than pdfplumber -- see get_exception_runs()).
    vendor_options = sorted({v["vendor_display_name"] for v in runs if v.get("vendor_display_name")})
    shop_options = sorted({v["shop"] for v in runs if v.get("shop")})
    location_options = sorted({v["billing_location"] for v in runs if v.get("billing_location")})

    filters = {"range": window.range, "date": window.date, "month": window.month, "sync": sync or ""}
    new_window = {"date": None, "month": None, "sync": None}
    selected_sync = (window.sync_time_utc.isoformat() + "Z") if (window.range == "last" and not window.empty) else ""
    # Same as dashboard.py: the sync picker's button is highlighted (and
    # the Last run chip isn't) only when the URL names a sync with ?sync=;
    # a plain Last run window is not an explicit pick.
    explicit_sync = selected_sync if sync and sync == selected_sync else ""

    ctx = {
        "active_page": "exceptions",
        "vendors": runs,
        "vendor_options": vendor_options,
        "shop_options": shop_options,
        "location_options": location_options,
        "total_open": total_open,
        "vendor_count_with_ex": len(runs_with_ex),
        "reason_badge": REASON_BADGE,
        "window": window,
        "window_label": tw.window_label(window, summary_backed_count),
        "window_summary_backed_count": summary_backed_count,
        "window_empty_message": tw.empty_message(window),
        "range_chips": [(key, label, exceptions_url(filters, range=key, **new_window))
                        for key, label in EXCEPTIONS_RANGE_CHIPS],
        "month_options": tw.month_options(timestamps),
        "sync_options": sync_options,
        "sync_truncated": sync_truncated,
        "selected_sync": selected_sync,
        "explicit_sync": explicit_sync,
        "last_run_url": exceptions_url(filters, range="last", **new_window),
        "all_time_url": exceptions_url(filters, range="all", **new_window),
        **sidebar_context(request),
    }
    return render(request, "exceptions_vendors.html", ctx)


@router.get("/exceptions/{vendor_name:path}")
def exceptions_review(vendor_name: str, request: Request, user: str = Depends(require_login),
                       filter: str = "all", selected: str = None, statement_id: str = None,
                       sort: str = None):
    vendor_name = unquote(vendor_name)
    # Unrecognised values collapse to the default order here, so every
    # link/redirect built from `sort` below carries only a known value.
    sort = sort if sort in queries.EXCEPTION_SORTS else None

    # A specific run's card (see get_exception_runs()) links here with its
    # own statement_id -- look that exact run up instead of falling back
    # to "the vendor's latest", or an older run's card would always open
    # whatever the vendor's newest run happens to be instead of itself.
    statement = queries.get_statement_by_id(statement_id) if statement_id else None
    if not statement and not statement_id:
        statement = queries.get_vendor_latest_statement(vendor_name)

    # Vendors with OPEN gold_exceptions rows but no gold_reconciliation_summary
    # row at all (e.g. a flagged review-queue row raised before this
    # vendor's PDF got a full pipeline run — see queries.get_vendor_summaries())
    # have no statement to look up here; fall back to deriving one straight
    # from their gold_exceptions rows instead of 404ing.
    exceptions_only = False
    if not statement:
        statement = queries.get_exceptions_only_vendor(vendor_name)
        exceptions_only = statement is not None

    if not statement:
        ctx = {
            "active_page": "exceptions",
            "vendor_name": vendor_name,
            "vendor_display_name": vendor_display_name(vendor_name),
            "not_found": True,
            **sidebar_context(request),
        }
        return render(request, "exceptions_review.html", ctx, status_code=404)

    if exceptions_only:
        source_file = statement["source_file"]
        open_list = queries.get_open_exceptions_for_source_file(source_file, None if filter == "all" else filter, sort)
        total, resolved = queries.get_exception_counts_for_source_file(source_file)
    else:
        statement_id = statement["statement_id"]
        open_list = queries.get_open_exceptions(statement_id, None if filter == "all" else filter, sort)
        total, resolved = queries.get_exception_counts(statement_id)

    selected_exc = None
    if selected:
        selected_exc = next((e for e in open_list if e["exception_id"] == selected), None)
    if not selected_exc and open_list:
        selected_exc = open_list[0]

    progress_pct = round((resolved / total) * 100) if total else 0

    # Amount Mismatch only -- every other reason has no NetSuite record
    # worth showing (Invoice Missing means nothing was found there at
    # all; the others aren't about a specific transaction). A live Fabric
    # query, once per page view of this one exception -- see
    # fetch_netsuite_record_for_invoice()'s own docstring for why this
    # isn't cached.
    netsuite_record = None
    if selected_exc and selected_exc.get("exception_reason") == "Amount Mismatch":
        netsuite_record = fetch_netsuite_record_for_invoice(
            selected_exc.get("vendor_id"), vendor_name, selected_exc.get("invoice_number")
        )
        if netsuite_record:
            # Display-only decode of NetSuite's internal status code (e.g.
            # vendor bill "A"/"B") into its actual business meaning -- see
            # netsuite_status_codes.py. Falls back to the raw code when
            # unmapped, so nothing is ever hidden, just possibly undecoded.
            netsuite_record["status_label"] = decode_netsuite_status(
                netsuite_record.get("_source_table"), netsuite_record.get("status")
            ) or netsuite_record.get("status")

    ctx = {
        "active_page": "exceptions",
        "vendor_name": vendor_name,
        "vendor_display_name": vendor_display_name(vendor_name),
        "vendor_url_name": quote(vendor_name, safe=""),
        "not_found": False,
        "statement": statement,
        "exceptions": open_list,
        "selected": selected_exc,
        "total": total,
        "resolved": resolved,
        "progress_pct": progress_pct,
        "filter": filter,
        "sort": sort or "",
        "reason_badge": REASON_BADGE,
        "high_confidence_count": queries.get_high_confidence_exception_count(vendor_name, BULK_APPROVE_THRESHOLD),
        "bulk_approve_threshold": BULK_APPROVE_THRESHOLD,
        "netsuite_record": netsuite_record,
        "searchable_reasons": SEARCHABLE_REASONS,
        **sidebar_context(request),
    }
    return render(request, "exceptions_review.html", ctx)


@router.post("/exceptions/{vendor_name}/bulk-approve")
def exceptions_bulk_approve(vendor_name: str, request: Request, user: str = Depends(require_login),
                             threshold: float = BULK_APPROVE_THRESHOLD):
    """Approves every OPEN exception for this vendor with
    match_confidence >= threshold in one pass — see
    queries.bulk_approve_exceptions(). Registered ahead of the
    {vendor_name:path} POST action route below: Starlette's "path"
    converter matches greedily (regex .*), so if that route were checked
    first it would swallow "/bulk-approve" into vendor_name itself and
    this route would never be reached. A plain (non-":path") converter is
    safe here because every link to this route is built from
    quote(vendor_name, safe="") (see vendor_url_name below), which never
    leaves a literal "/" in the URL segment."""
    vendor_name = unquote(vendor_name)
    approved = queries.bulk_approve_exceptions(vendor_name, threshold, reviewed_by=user)
    return {"approved": approved}


def _filter_redirect_suffix(filter: str, statement_id: str = None, sort: str = None) -> str:
    """Builds the query string a post-action redirect back to
    /exceptions/{vendor_name} needs to stay on the same statement/filter
    the user was reviewing -- dropping statement_id here (as this used to)
    silently bounces the redirect to get_vendor_latest_statement()'s "the
    vendor's latest run" instead, which can be a completely different
    statement_id than the one just acted on (confirmed live 2026-09-22:
    Rh Long Motor Sales has 7 separate runs). `sort` is kept for the same
    reason -- acting on an exception should not reset the list's order."""
    params = []
    if filter and filter != "all":
        params.append(f"filter={filter}")
    if statement_id:
        params.append(f"statement_id={statement_id}")
    if sort in queries.EXCEPTION_SORTS:
        params.append(f"sort={sort}")
    return f"?{'&'.join(params)}" if params else ""


@router.post("/exceptions/{vendor_name}/escalate")
def exceptions_escalate(vendor_name: str, request: Request, user: str = Depends(require_login),
                         exception_id: str = Form(...), filter: str = Form("all"),
                         statement_id: str = Form(""), sort: str = Form("")):
    """Flags a single exception ESCALATED (see queries.escalate_exception())
    and redirects back to the same vendor/filter/statement. Registered
    ahead of the {vendor_name:path} POST action route below for the same
    greedy-path-converter reason as exceptions_bulk_approve() above."""
    vendor_name = unquote(vendor_name)
    queries.escalate_exception(exception_id, escalated_by=user)
    suffix = _filter_redirect_suffix(filter, statement_id, sort)
    return RedirectResponse(f"/exceptions/{quote(vendor_name, safe='')}{suffix}", status_code=303)


@router.post("/exceptions/{vendor_name:path}")
def exceptions_action(vendor_name: str, request: Request, user: str = Depends(require_login),
                       exception_id: str = Form(...), statement_id: str = Form(...),
                       invoice_number: str = Form(...), reason_code: str = Form(...),
                       action: str = Form(...), note: str = Form(""),
                       filter: str = Form("all"), sort: str = Form("")):
    vendor_name = unquote(vendor_name)
    queries.resolve_exception(
        exception_id=exception_id,
        statement_id=statement_id,
        vendor_name=vendor_name,
        invoice_number=invoice_number,
        reason_code=reason_code,
        disposition_status=action,
        notes=note or None,
        disposed_by=user,
    )
    suffix = _filter_redirect_suffix(filter, statement_id, sort)
    return RedirectResponse(f"/exceptions/{quote(vendor_name, safe='')}{suffix}", status_code=303)


def _parse_amount(raw):
    """Returns (amount, error_message). An empty box is a legitimate "no
    amount filter", not an error -- only a non-empty unparseable value is."""
    if raw is None or str(raw).strip() == "":
        return None, None
    try:
        return float(str(raw).replace(",", "").replace("$", "").strip()), None
    except ValueError:
        return None, f"“{raw}” isn’t a number — enter an amount like 195.65."


def _search_entity_ids(use_vendor: bool, vendor_id: str, vendor_name: str):
    """Entity ids for the vendor filter, or None when the user has
    toggled the vendor filter off (the "maybe it was booked under a
    different vendor" case this panel exists for). Uses the same
    resolution the matching engine uses, so "vendor on" here means
    exactly what it meant at match time."""
    if not use_vendor:
        return None
    return resolve_entity_ids(vendor_id or "", vendor_name or "")


def _parse_statuses(raw: str) -> frozenset:
    """"open,paid" (as sent by the Status popover's two checkboxes) ->
    a validated frozenset. Empty or entirely invalid input defaults to
    {"open"} -- the UI itself never lets both boxes end up unticked, but
    a hand-edited/old URL might, and this must not silently search every
    status as a result."""
    statuses = frozenset(s.strip() for s in (raw or "").split(",") if s.strip() in STATUSES)
    return statuses or frozenset({"open"})


def _error_partial(request: Request, message: str):
    """A results fragment carrying nothing but a friendly message, so a
    bad input renders in place instead of 500-ing the modal."""
    return render(request, "_netsuite_search_results.html",
                  {"result": {"rows": [], "row_count": 0, "truncated": False,
                              "error": True, "needs_filter": False,
                              "message": message}})


@router.get("/netsuite-search")
def netsuite_search(request: Request, user: str = Depends(require_login),
                    vendor_id: str = "", vendor_name: str = "",
                    use_vendor: bool = True, amount: str = "",
                    tolerance: str = "exact", invoice_contains: str = "",
                    statuses: str = "open", sort_amount: str = "",
                    date_from: str = "", date_to: str = ""):
    """Open-AP search partial for the "Find in NetSuite" modal.

    STRICTLY READ-ONLY: this issues SELECTs against the Fabric Lakehouse
    and nothing else. It writes to NetSuite, Fabric and Azure SQL never,
    resolves no exception, and has no POST counterpart -- closing an
    exception stays with the existing Accept/Dispute/Escalate forms.

    Returns an HTML fragment rather than a full page so changing a filter
    re-renders only the results, not the exception under review."""
    parsed_amount, amount_error = _parse_amount(amount)
    if amount_error:
        return _error_partial(request, amount_error)

    parsed_sort, sort_error = _parse_amount(sort_amount)
    if sort_error:
        return _error_partial(request, sort_error)

    # "1_dollar"/"5_percent" are no longer popover options, but an old
    # request/bookmark using either must still work, not error -- both
    # behave exactly like "any" (search_open_ap() does the same
    # normalization for its other, non-HTTP callers).
    if tolerance in REMOVED_TOLERANCES:
        tolerance = "any"
    if tolerance not in TOLERANCES:
        return _error_partial(request, "Pick one of the listed amount tolerances.")

    result = search_open_ap(
        entity_ids=_search_entity_ids(use_vendor, vendor_id, vendor_name),
        amount=parsed_amount,
        amount_tolerance=tolerance,
        invoice_contains=invoice_contains,
        statuses=_parse_statuses(statuses),
        sort_amount=parsed_sort,
        date_from=date_from,
        date_to=date_to,
    )
    return render(request, "_netsuite_search_results.html",
                  {"result": result, "last_sync": queries.get_last_netsuite_sync()})
