"""
jobs.py

GET /jobs — current job queue status as JSON, polled by the home page's
auto-refresh (see web/static/app.js) to decide whether to reload while
jobs are still active. GET /jobs/history — every job ever submitted,
completed and failed included. GET /jobs/{job_id}/extracted — plain
extraction-only view (invoice_number/charges/credits/amount_due) for one
completed job, nothing about matching/reconciliation.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from web.deps import render, require_login, sidebar_context
from web import queries

router = APIRouter()

_JOB_FIELDS = (
    "job_id", "pdf_filename", "status", "submitted_by", "submitted_at",
    "started_at", "completed_at", "error_message", "statement_id", "vendor_name",
)


def _job_json(job: dict) -> dict:
    return {field: job.get(field) for field in _JOB_FIELDS}


@router.get("/jobs")
def jobs_status(request: Request, user: str = Depends(require_login)):
    return [_job_json(j) for j in queries.get_active_jobs()]


@router.get("/jobs/_debug/kpi-state")
def kpi_debug_state(request: Request, user: str = Depends(require_login)):
    """TEMPORARY read-only diagnostic -- see queries.get_kpi_debug_state()
    docstring. Remove once the Total invoices/Statement total KPI
    investigation is closed."""
    return queries.get_kpi_debug_state()


@router.get("/jobs/history")
def jobs_history(request: Request, user: str = Depends(require_login)):
    ctx = {
        "active_page": "upload",
        "jobs": queries.get_job_history(),
        **sidebar_context(request),
    }
    return render(request, "jobs_history.html", ctx)


@router.get("/jobs/{job_id}/extracted")
def job_extracted_data(job_id: str, request: Request, user: str = Depends(require_login)):
    job = queries.get_job_by_id(job_id)
    if not job or job.get("status") != "COMPLETED":
        return RedirectResponse("/jobs/history", status_code=303)
    ctx = {
        "active_page": "upload",
        "job": job,
        "rows": queries.get_extracted_rows_for_job(job_id),
        **sidebar_context(request),
    }
    return render(request, "extracted_data.html", ctx)
