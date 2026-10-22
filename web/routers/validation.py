"""
validation.py

Statement Processing (was "Validation", renamed 2026-10-16; the /validation
URLs are kept so existing links work). The list shows every intake attempt
as a card with its Extraction -> Validation -> Reconciliation stages; the
detail page shows one statement with a tab per stage. Read-only. The stage
rules live in web/statement_processing.py; the Arithmetic Validation Gate
itself is src/validation/arithmetic_gate.py.
"""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, Request

from web.deps import render, require_login, sidebar_context, smart_title
from web import queries
from web import statement_processing as sp
from web import time_window as tw
from src.vendor_identity import display_name as vendor_display_name

router = APIRouter()


def _alongside(fabric_call, *azure_sql_calls):
    """Runs the Fabric Warehouse read in a second thread while the Azure SQL
    reads run here one after another, as they always have -- the page waits
    for the slower lane instead of both. Azure SQL never sees more than one
    of these connections at a time. Returns (fabric_result, [azure results])."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        fabric = pool.submit(fabric_call)
        azure = [call() for call in azure_sql_calls]
        return fabric.result(), azure


@router.get("/validation")
def validation_list(request: Request, user: str = Depends(require_login)):
    recon, (intake_rows, jobs, outlook_jobs) = _alongside(
        queries.get_recon_status,
        queries.get_validation_report, queries.get_processing_jobs, queries.get_outlook_synced_jobs)
    cards = sp.build_cards(intake_rows, jobs, recon)

    # "Last run" dropdown (2026-09-30) -- same Outlook-sync definitions as
    # Home/Exceptions (web/time_window.py's outlook_all_syncs()), applied
    # here to intake attempts instead of reconciliation runs. Entirely
    # client-side (this page never round-trips a range/sync param to the
    # server) -- each card gets the UTC ISO "value" (outlook_sync_options())
    # of whichever sync its statement_id (or, for a failed extraction with
    # no statement_id, its job) belongs to, or "" if none, so the select's
    # JS filter can do a plain string-equality match against data-sync,
    # same pattern as the existing vendor/shop/period filters.
    all_syncs = tw.outlook_all_syncs(outlook_jobs)
    sync_by_statement, sync_by_job = {}, {}
    for chain in all_syncs:
        sync_value = chain[0]["submitted_at"].isoformat() + "Z"
        for j in chain:
            if j.get("statement_id"):
                sync_by_statement[j["statement_id"]] = sync_value
            if j.get("job_id"):
                sync_by_job[j["job_id"]] = sync_value
    sync_options, sync_truncated = tw.outlook_sync_options(outlook_jobs)

    for card in cards:
        # Display-only casing normalization, same reasoning as
        # exceptions.py's exceptions_vendors() -- keeps the filter
        # dropdown options and each card's data-vendor/data-shop
        # attributes in sync with what's actually shown.
        card["vendor_display_name"] = smart_title(vendor_display_name(card.get("vendor_name")))
        card["shop"] = smart_title(card.get("shop"))
        card["sync_time"] = (sync_by_statement.get(card.get("statement_id"))
                             or sync_by_job.get(card.get("job_id")) or "")

    vendor_options = sorted({c["vendor_display_name"] for c in cards if c.get("vendor_display_name")})
    shop_options = sorted({c["shop"] for c in cards if c.get("shop")})
    # Newest first -- statement_period is "YYYY-MM" (see deps.period_label),
    # so a reverse string sort is a reverse date sort.
    period_options = sorted({c["statement_period"] for c in cards if c.get("statement_period")}, reverse=True)

    ctx = {
        "active_page": "validation",
        "runs": cards,
        "vendor_options": vendor_options,
        "shop_options": shop_options,
        "period_options": period_options,
        "sync_options": sync_options,
        "sync_truncated": sync_truncated,
        # The "Today" chip's day -- same US Eastern "today" as Home's own
        # Today chip, in the same "YYYY-MM-DD" shape as each card's data-day.
        "today_eastern": tw.resolve_window("today").date,
        **sidebar_context(request),
    }
    return render(request, "validation.html", ctx)


@router.get("/validation/{statement_id}")
def validation_detail(statement_id: str, request: Request, user: str = Depends(require_login),
                      tab: str = ""):
    # One statement, one tab per stage (2026-10-16): Extraction (Bronze rows
    # as printed -- there even when the validation gate stopped it before
    # Silver), Validation (the gate's inputs and the checks it tried) and
    # Reconciliation (each Silver line against its invoice's NetSuite
    # result). Opens on the stage that needs attention (sp.default_tab()).
    # get_statement_report() is mostly Fabric (summary, matched,
    # exceptions); the other three are mostly Azure SQL.
    report, (data, job, extracted, set_aside, recon_rows) = _alongside(
        lambda: queries.get_statement_report(statement_id),
        lambda: queries.get_extraction_validation_detail(statement_id),
        lambda: queries.get_latest_job_for_statement(statement_id),
        lambda: queries.get_extracted_rows_for_statement(statement_id),
        lambda: queries.get_set_aside_lines(statement_id),
        lambda: queries.get_recon_rows(statement_id))
    intake = data.get("intake")
    summary, matched, exceptions = report.get("summary"), report.get("matched") or [], report.get("exceptions") or []

    # The Reconciliation tab reads the recon table when the statement has
    # rows there (2026-10-22) -- every number and status from one source --
    # else the stored matching results as before.
    lines_view = None
    if summary is not None:
        lines_view = (sp.recon_view(recon_rows) if recon_rows
                      else sp.line_results(data.get("lines") or [], matched, exceptions, set_aside))

    card = None
    if intake:
        recon = None
        if summary is not None and recon_rows:
            recon = {"exceptions": lines_view["tiles"]["open"], "reasons": lines_view["open_reasons"]}
        elif summary is not None:
            recon = {"exceptions": summary.get("exception_count") or 0,
                     "reasons": dict(Counter(e.get("exception_reason") or "Other" for e in exceptions))}
        card = sp.intake_card(intake, job, recon)
    elif job:
        card = sp.job_card(job)
    if card:
        card["vendor_display_name"] = smart_title(vendor_display_name(card.get("vendor_name")))

    tabs = ("extraction", "validation", "reconciliation")
    ctx = {
        "active_page": "validation",
        "statement_id": statement_id,
        **data,
        "card": card,
        "job": job,
        "summary": summary,
        "extracted": extracted if card else [],
        "recon": lines_view,
        "active_tab": tab if tab in tabs else (sp.default_tab(card) if card else "validation"),
        **sidebar_context(request),
    }
    return render(request, "validation_detail.html", ctx)
