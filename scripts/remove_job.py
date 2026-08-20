"""
remove_job.py

Deletes one row from the jobs table by job_id -- for a stale/orphaned job
that isn't going to be picked up or retried (e.g. one manually terminated
during troubleshooting, stuck in PROCESSING with no Bronze/Silver written).

There's no dismiss/cancel mechanism in the app (see web/routers/jobs.py --
only GET routes) and the jobs table's CHECK constraint only allows
PENDING/PROCESSING/COMPLETED/FAILED, so there's no "hidden" status to set
either -- marking a failed job COMPLETED would misrepresent it in
/jobs/history. Deleting the row is the correct, honest fix, safe as long
as the job never reached COMPLETED (i.e. statement_id is NULL -- see
migrations/005_add_jobs_table.sql's docstring: statement_id is only ever
filled in once the pipeline determines it, so a job that failed before
that point has nothing else in Bronze/Silver/Gold referencing it).

Idempotent: does nothing (prints a message, doesn't error) if the job_id
is already gone -- safe to invoke unconditionally on every container
start (see deploy/azure-app-service-demo/container-start.sh).

Usage:
    python scripts/remove_job.py --job-id <uuid>
"""

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from src.lakehouse.connection import execute_query, execute_sql


def remove_job(job_id: str) -> bool:
    rows = execute_query(
        "SELECT job_id, pdf_filename, status, statement_id FROM jobs WHERE job_id = ?",
        [job_id],
    )
    if not rows:
        print(f"No job found with job_id={job_id!r} -- nothing to do.")
        return False

    job = rows[0]
    if job.get("statement_id"):
        raise SystemExit(
            f"Refusing to delete job_id={job_id!r}: it has statement_id="
            f"{job['statement_id']!r} -- it reached COMPLETED and has real "
            f"Bronze/Silver/Gold data tied to it. Only a job that never "
            f"completed (statement_id IS NULL) is safe to delete here."
        )

    print(f"Deleting job_id={job_id!r} ({job['pdf_filename']!r}, status={job['status']!r})...")
    execute_sql("DELETE FROM jobs WHERE job_id = ?", [job_id])
    print("Deleted.")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Delete one stale jobs-table row by job_id")
    parser.add_argument("--job-id", required=True, help="job_id (UUID) of the row to delete")
    args = parser.parse_args()
    remove_job(args.job_id)
