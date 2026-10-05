"""
dashboard.py

Home page — KPI cards and the "Reconciliation runs" table, both from
silver.recon_summary and both scoped by one time filter (?range=...,
see web/time_window.py), plus the jobs and recent-batches panels.
"""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request

from web.deps import render, require_login, sidebar_context
from web import queries
from web import time_window as tw

router = APIRouter()

# Time-window chips, in display order. The "Past Outlook syncs" select and
# the calendar-icon button are their own controls, not plain chips. The
# "This month"/"All time" chips were removed 2026-09-30 and the Month
# select (whose blank option doubled as "All time") 2026-10-01, but
# all/month/month_current stay valid resolve_window() values, so an old
# bookmarked ?range=all, ?month= or ?range=month_current link still works
# -- it just has no control.
RANGE_CHIPS = (("today", "Today"), ("last", "Last run"))


def home_url(filters: dict, **changes) -> str:
    """"/?..." for the current filters with `changes` applied. Defaults
    (range=last, status=all) and blanks are left out, so the plain "/"
    stays canonical."""
    merged = {**filters, **changes}
    params = []
    if merged.get("range") and merged["range"] != tw.DEFAULT_RANGE:
        params.append(("range", merged["range"]))
    if merged.get("range") == "date" and merged.get("date"):
        params.append(("date", merged["date"]))
    if merged.get("range") == "month" and merged.get("month"):
        params.append(("month", merged["month"]))
    if merged.get("sync"):
        # "range=last" is the default and so is normally left out above,
        # but a ?sync= is meaningless without it once a non-last range is
        # ever the default, so it's always spelled out explicitly here --
        # see web/time_window.py's outlook_sync_options().
        if not any(p[0] == "range" for p in params):
            params.append(("range", "last"))
        params.append(("sync", merged["sync"]))
    if merged.get("status") and merged["status"] != "all":
        params.append(("status", merged["status"]))
    if merged.get("period"):
        params.append(("period", merged["period"]))
    return "/" + (f"?{urlencode(params)}" if params else "")


@router.get("/")
def home(request: Request, user: str = Depends(require_login),
         range: str = "", date: str = "", month: str = "", sync: str = "",
         status: str = "all", period: str = ""):
    # Re-enabled 2026-08-26 -- wired to the NEW NetSuite matching flow's
    # results (silver.recon_summary, Fabric), not
    # queries.get_recent_runs()'s gold_reconciliation_summary (a
    # different, voucher-based flow, still deliberately not shown here).
    #
    # The time window drives the KPI cards, the "N of M" line and the runs
    # table together (one query -- see get_home_dashboard()); status and
    # period only narrow the table and its N of M. Unknown or malformed
    # values fall back to the defaults (range=last, status=all).
    #
    # timestamps (recon_summary run times) only feeds the Month dropdown's
    # options; outlook_jobs (source_blob_path IS NOT NULL jobs) is what
    # "last" is actually built from now -- see time_window.outlook_last_sync().
    timestamps = queries.get_run_timestamps()
    outlook_jobs = queries.get_outlook_synced_jobs()
    window = tw.resolve_window(range or None, date or None, month or None,
                               timestamps=timestamps, outlook_jobs=outlook_jobs, sync_=sync or None)
    if status not in queries.RECON_RUN_STATUS_FILTERS:
        status = "all"
    data = queries.get_home_dashboard(window=window, status=status, period=period or None, limit=10)

    filters = {"range": window.range, "date": window.date, "month": window.month,
               "sync": sync or "", "status": status, "period": period or ""}
    # Changing the time window clears the statement period (its options
    # change with the window) but keeps the status; the status chips and
    # the period select keep the window. Picking Today/Month/a calendar
    # day also clears any explicitly-chosen sync (each is its own <form>
    # in home.html, so this only matters for the *_url() helpers below).
    new_window = {"date": None, "month": None, "sync": None, "period": ""}
    sync_options, sync_truncated = tw.outlook_sync_options(outlook_jobs)
    selected_sync = (window.sync_time_utc.isoformat() + "Z") if (window.range == "last" and not window.empty) else ""
    # The sync picker's button is highlighted (and the Last run chip isn't)
    # only when the URL names a sync with ?sync=; a plain Last run window
    # is not an explicit pick -- see home.html.
    explicit_sync = selected_sync if sync and sync == selected_sync else ""
    period_options = list(data["period_options"])
    if period and period not in period_options:
        # Keep a selected-but-absent period visible, so an empty table is
        # explained by the dropdown rather than looking broken.
        period_options.append(period)

    # The review-queue line under the cards is extraction backlog, not run
    # data, so it is not scoped by the time window.
    kpis = {**data["kpis"], "pending_review_count": queries.get_pending_review_count()}

    ctx = {
        "active_page": "home",
        "kpis": kpis,
        "active_jobs": queries.get_active_jobs(),
        "failed_jobs": queries.get_failed_jobs(),
        "runs": data["runs"],
        "runs_total": data["total"],
        "runs_reconciled": data["reconciled"],
        "period_options": period_options,
        "run_status": status,
        "run_period": period or "",
        "window": window,
        "window_label": tw.window_label(window, data["statement_count"]),
        "window_short": tw.window_short(window),
        "window_statement_count": data["statement_count"],
        "window_empty_message": tw.empty_message(window),
        "range_chips": [(key, label, home_url(filters, range=key, **new_window)) for key, label in RANGE_CHIPS],
        "month_options": tw.month_options(timestamps),
        "sync_options": sync_options,
        "sync_truncated": sync_truncated,
        "selected_sync": selected_sync,
        "explicit_sync": explicit_sync,
        "status_urls": {s: home_url(filters, status=s) for s in queries.RECON_RUN_STATUS_FILTERS},
        "clear_table_url": home_url(filters, status="all", period=""),
        "last_run_url": home_url(filters, range="last", **new_window),
        "all_time_url": home_url(filters, range="all", **new_window),
        "recent_batches": queries.get_recent_completed_batches(limit=3),
        "netsuite_last_sync": queries.get_last_netsuite_sync(),
        "outlook_last_sync": queries.get_last_outlook_sync(),
        **sidebar_context(request),
    }
    return render(request, "home.html", ctx)
