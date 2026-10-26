"""How long did the last uploads take, and where did the time go? Read-only.

  python scripts/job_timing.py          # the last 5 jobs
  python scripts/job_timing.py 2        # the last 2

Per job: queued (upload -> processing started), run (started -> finished), total, then the time of each
step. The steps come from the job_step_timing table, which the worker fills after every job while
JOB_TIMING_LOG_ENABLED=true (see .env.example); jobs run without it have no breakdown. It reads whichever
database the app is configured for (Azure SQL when AZURE_SQL_* is set, else the local SQLite file).
Times are UTC; only the differences matter.

The same data in plain SQL:
  SELECT job_id, pdf_filename, step, seconds FROM job_step_timing ORDER BY job_id, step_order
"""
import os
import sys
from datetime import datetime, timedelta, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# What a reader wants to see, in order -> the pipeline step names that make it up.
GROUPS = (
    ("Starting up (imports)", ("notebook_import",)),
    ("Extraction", ("extraction",)),
    ("Validation (total check)", ("validation",)),
    ("Writing extracted data", ("bronze_raw_write", "bronze_promote", "promote_lock_wait",
                                "bronze_unnested_write", "sql_endpoint_refresh")),
    ("Blob upload", ("blob_upload",)),
    ("SharePoint archive", ("sharepoint_archive",)),
    ("Silver build (incl. waits)", ("visibility_wait", "lock_wait", "silver_build", "dbt_silver")),
    ("Silver check", ("silver_check",)),
    ("Reconciliation (matching)", ("matching",)),
    ("NetSuite write-back", ("netsuite_writeback",)),
)
# Summary lines that CONTAIN other steps: shown for reference, never added up.
CONTAINERS = ("intake_total", "fabric_pipeline_total")
LOOK_BACK_DAYS = 14


def _parse(value):
    return datetime.fromisoformat(str(value).replace("Z", "").split("+")[0]) if value else None


def _secs(a, b):
    a, b = _parse(a), _parse(b)
    return None if a is None or b is None else round((b - a).total_seconds())


def _fmt(seconds):
    if seconds is None:
        return "-"
    seconds = round(seconds)
    return f"{seconds // 60}m {seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


def _steps_summed(steps: list) -> dict:
    totals = {}
    for name, seconds in steps:
        totals[name] = totals.get(name, 0.0) + float(seconds)
    return totals


def _recent_jobs(limit: int) -> list:
    from src.lakehouse.connection import execute_query
    since = (datetime.now(timezone.utc) - timedelta(days=LOOK_BACK_DAYS)).isoformat()
    rows = execute_query(
        "SELECT job_id, pdf_filename, status, statement_id, submitted_at, started_at, completed_at "
        "FROM jobs WHERE submitted_at >= ? ORDER BY submitted_at DESC", [since])
    return rows[:limit]


def _steps_by_job(job_ids: list) -> dict:
    if not job_ids:
        return {}
    from src.lakehouse.connection import execute_query
    marks = ", ".join("?" * len(job_ids))
    rows = execute_query(
        f"SELECT job_id, step, seconds FROM job_step_timing WHERE job_id IN ({marks}) "
        "ORDER BY job_id, id", list(job_ids))
    out = {}
    for row in rows:
        out.setdefault(row["job_id"], []).append((row["step"], row["seconds"]))
    return out


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    jobs = _recent_jobs(limit)
    try:
        timings = _steps_by_job([j["job_id"] for j in jobs])
    except Exception as exc:
        print(f"(could not read job_step_timing: {exc})")
        timings = {}
    for job in jobs:
        run = _secs(job["started_at"], job["completed_at"])
        print(f"\n{job['pdf_filename']}   [{job['status']}]   {job['statement_id'] or ''}")
        print(f"  queued {_fmt(_secs(job['submitted_at'], job['started_at']))}   run {_fmt(run)}   "
              f"total {_fmt(_secs(job['submitted_at'], job['completed_at']))}")
        steps = timings.get(job["job_id"])
        if not steps:
            print("  (no step breakdown saved for this job)")
            continue
        totals = _steps_summed(steps)
        listed = 0.0
        for label, names in GROUPS:
            seconds = sum(totals.get(n, 0.0) for n in names)
            if any(n in totals for n in names):
                print(f"  {label:<30}{_fmt(seconds):>9}")
                listed += seconds
        if run is not None:
            print(f"  {'Everything else (startup, db)':<30}{_fmt(max(run - listed, 0)):>9}")
        for container in CONTAINERS:
            if container in totals:
                print(f"  {'(' + container + ')':<30}{_fmt(totals[container]):>9}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
