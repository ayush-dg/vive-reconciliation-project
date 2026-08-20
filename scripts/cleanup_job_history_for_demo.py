"""
cleanup_job_history_for_demo.py

One-time cleanup for the extraction demo: keeps exactly one jobs-table
row -- job_id e5a24e5c-92ed-4708-963f-cfe56dd7ed1a ("Fred Beans Lee's.pdf",
completed 2026-08-20, displayed as "Today, 3:39 PM" IST on the live
/jobs/history page -- confirmed as the unique match for that exact
filename + timestamp, cross-checked against all 18 other rows sharing the
same filename, before writing this script) -- and deletes every other row.

Does NOT touch Bronze/Silver/Gold data. jobs is a standalone operational
table with no foreign-key relationship to silver_reconciliation_standard/
gold_matched_invoices/gold_exceptions/gold_reconciliation_summary --
deleting a job row only removes that row from Job History and breaks its
own "View extracted data" link (web/routers/jobs.py's job_extracted_data()
looks the job up by job_id first, and already redirects gracefully if the
job_id is gone -- no crash). The underlying statement's data stays fully
intact in Silver/Gold either way, just unreachable via that job_id link.
The Reports page reads gold_reconciliation_summary directly and is
entirely unaffected.

This is a genuine ONE-TIME operation -- NOT meant to run on every future
container start the way scripts/remove_job.py's targeted single-job_id
cleanup safely is. The container-start.sh wiring for this script must be
removed again in a follow-up commit immediately after confirming it ran
once, or it would keep deleting every future legitimate job that isn't
this one specific row.

Prints the full pre-deletion jobs table as JSON (one row per line,
prefixed JOBS_BACKUP_ROW:) to stdout, captured in container logs as a
recoverable backup.
"""

import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from src.lakehouse.connection import execute_query, execute_sql

KEEP_JOB_ID = "e5a24e5c-92ed-4708-963f-cfe56dd7ed1a"


def run():
    rows = execute_query("SELECT * FROM jobs ORDER BY submitted_at DESC")
    print(f"JOBS_BACKUP_COUNT: {len(rows)}")
    for row in rows:
        print("JOBS_BACKUP_ROW: " + json.dumps(row, default=str))

    kept = [r for r in rows if r["job_id"] == KEEP_JOB_ID]
    if not kept:
        print(f"ERROR: KEEP_JOB_ID {KEEP_JOB_ID!r} not found among current jobs -- aborting, deleting nothing.")
        return

    to_delete = [r for r in rows if r["job_id"] != KEEP_JOB_ID]
    print(f"Deleting {len(to_delete)} job row(s), keeping job_id={KEEP_JOB_ID!r} "
          f"({kept[0].get('pdf_filename')!r}, completed_at={kept[0].get('completed_at')!r})")
    for row in to_delete:
        execute_sql("DELETE FROM jobs WHERE job_id = ?", [row["job_id"]])
    print("Done.")


if __name__ == "__main__":
    run()
