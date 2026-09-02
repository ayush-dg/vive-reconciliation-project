"""
backfill_job_document_hashes.py

One-time backfill for jobs.document_hash (added 2026-09-03, see
web/queries.py's update_job_status()/_resolve_bronze_statement_id()).

Every COMPLETED job before this date has document_hash = NULL, so
_resolve_bronze_statement_id() can't use the new fast path for them and
falls back to re-reading the original PDF from local disk -- which is
gone (WEBSITES_ENABLE_APP_SERVICE_STORAGE is false, so local disk is
wiped on every container restart), so "View extracted data" shows
nothing for any cache-hit job among them.

This does NOT re-read any file (local disk or Blob). For each affected
job (status COMPLETED, statement_id present, zero rows in
bronze_vendor_statement_raw under its own statement_id), it finds the
extraction_cache row whose source_file matches the job's pdf_filename,
has the newest ingestion_timestamp, and whose statement_id has live
Bronze rows -- then backfills the job's document_hash to that cache
row's document_hash. That hash is exactly what re-hashing the file
would produce (extraction_cache's row was itself written by hashing
this same file at ingestion time), so this is not a guess.

Jobs with no such matching cache row are left untouched -- their Bronze
was deliberately purged in the 2026-09-01/02 vendor cleanup, or they
never had Bronze to begin with; backfilling a hash for them would be
fabricating provenance, not recovering it.
"""
import pyodbc

CONN_STR = (
    "Driver={ODBC Driver 18 for SQL Server};"
    "Server=tcp:viverecondemo-sql.database.windows.net,1433;"
    "Database=viverecondemo-db;"
    "Uid=viveadmin;"
    "Pwd=vive@2026;"
    "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
)


def backfill_job_document_hashes(dry_run: bool = True) -> dict:
    conn = pyodbc.connect(CONN_STR)
    cur = conn.cursor()

    cur.execute(
        "SELECT job_id, pdf_filename, statement_id FROM jobs "
        "WHERE status = 'COMPLETED' AND statement_id IS NOT NULL AND document_hash IS NULL"
    )
    jobs = cur.fetchall()

    updates = []
    skipped_already_direct = 0
    skipped_no_target = 0

    for job_id, pdf_filename, statement_id in jobs:
        cur.execute(
            "SELECT COUNT(*) FROM bronze_vendor_statement_raw WHERE statement_id = ?",
            [statement_id],
        )
        if cur.fetchone()[0] > 0:
            skipped_already_direct += 1
            continue

        cur.execute(
            "SELECT document_hash, statement_id FROM extraction_cache "
            "WHERE source_file = ? ORDER BY ingestion_timestamp DESC",
            [pdf_filename],
        )
        candidates = cur.fetchall()
        found_hash = None
        for document_hash, cand_sid in candidates:
            cur.execute(
                "SELECT COUNT(*) FROM bronze_vendor_statement_raw WHERE statement_id = ?",
                [cand_sid],
            )
            if cur.fetchone()[0] > 0:
                found_hash = document_hash
                break

        if found_hash:
            updates.append((job_id, pdf_filename, statement_id, found_hash))
        else:
            skipped_no_target += 1

    print(f"COMPLETED jobs with statement_id, document_hash still NULL: {len(jobs)}")
    print(f"  Already have direct Bronze (shouldn't need backfill, skipped): {skipped_already_direct}")
    print(f"  No live cache target found (left alone, per instruction): {skipped_no_target}")
    print(f"  To backfill: {len(updates)}")

    if dry_run:
        print("\nDRY RUN -- no writes made. Re-run with dry_run=False to apply.")
        conn.close()
        return {"would_update": len(updates), "updates": updates}

    for job_id, pdf_filename, statement_id, found_hash in updates:
        cur.execute(
            "UPDATE jobs SET document_hash = ? WHERE job_id = ?",
            [found_hash, job_id],
        )
    conn.commit()

    cur.execute(
        "SELECT COUNT(*) FROM jobs WHERE status = 'COMPLETED' AND statement_id IS NOT NULL AND document_hash IS NOT NULL"
    )
    total_with_hash = cur.fetchone()[0]
    print(f"\nApplied {len(updates)} update(s). Total COMPLETED jobs with document_hash set: {total_with_hash}")

    conn.close()
    return {"updated": len(updates), "updates": updates}


if __name__ == "__main__":
    import sys
    dry_run = "--apply" not in sys.argv
    backfill_job_document_hashes(dry_run=dry_run)
