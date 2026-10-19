"""
recon_table.py

The `recon` table (Azure SQL; migrations/021_add_recon_table.sql and
src/lakehouse/azure_sql_migrations.py): one row per statement line with its
reconciliation status, plus the NetSuite bill/credit the line is linked to.

  * The matching run (src/matching/fabric_matching.py) writes the "auto" rows
    for every line of the statement -- replace_auto_rows() replaces only that
    statement's auto rows on a re-run, so a person's manual matches survive.
  * Accept / Reject on an exception (web/queries.py's resolve_exception())
    set that invoice's lines to Accepted / Rejected (mark_resolved()).
  * A manual "Accept as match" adds "manual" rows (the next step).

Status values are the STATUS_* constants below. Best-effort for callers:
writing here must never fail matching or an exception's resolution -- the
callers catch and log.
"""

import uuid
from datetime import datetime, timezone

from src.lakehouse.connection import execute_query, execute_sql, get_connection

STATUS_MATCHED = "Matched"
STATUS_MATCHED_MANUALLY = "Matched manually"
STATUS_ACCEPTED = "Accepted"
STATUS_REJECTED = "Rejected"
STATUS_NOT_RECONCILED = "Not reconciled"

# The matcher's exception_reason -> the status shown in recon.
STATUS_BY_REASON = {
    "Amount Mismatch": "Amount mismatch",
    "Not Found in NetSuite": "Not found in NetSuite",
    "Invoice Missing": "Not found in NetSuite",
    "Possible Duplicate in NetSuite": "Possible duplicate",
    "Vendor Not Resolved in NetSuite": "Vendor not resolved",
}

# exception_dispositions.disposition_status -> recon status.
STATUS_BY_DISPOSITION = {"ACCEPTED": STATUS_ACCEPTED, "DISPUTED": STATUS_REJECTED}

SOURCE_AUTO, SOURCE_MANUAL = "auto", "manual"

COLUMNS = (
    "recon_id", "statement_id", "vendor_id", "vendor_name", "statement_period",
    "line_number", "statement_line_id", "invoice_number", "original_invoice_number",
    "line_date", "line_amount", "status", "exception_id", "exception_reason",
    "netsuite_record_type", "netsuite_internal_id", "netsuite_tranid",
    "netsuite_transaction_number", "netsuite_amount", "difference",
    "netsuite_entity_id", "netsuite_location", "source", "match_rule",
    "matched_by", "matched_at", "note", "is_active", "created_at",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float(value):
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def line_amount(line: dict):
    """A Silver line's own signed amount: charge, else minus payment."""
    charge, payment = _float(line.get("charge_amount")), _float(line.get("payment_amount"))
    if charge is not None:
        return charge
    return None if payment is None else -payment


def status_for_reason(reason: str) -> str:
    return STATUS_BY_REASON.get(reason, reason or STATUS_NOT_RECONCILED)


def build_auto_rows(statement: dict, lines: list, results: dict, now: str = None) -> list:
    """One "auto" row per Silver line.

    statement: {"statement_id", "vendor_id", "vendor_name", "statement_period"}
    lines:     every line of the statement as the matcher fetched it, BEFORE
               any line was dropped or deduplicated
    results:   {statement_line_id: result} for the lines the matcher decided
               on, where result is {"status", "exception_id", "exception_reason",
               "match_rule", "statement_amount", "netsuite": {...} or None};
               a line with no result is "Not reconciled" (no invoice number,
               or set aside by line selection -- its "note" says which).
    """
    now = now or _now()
    rows = []
    for line in lines:
        result = results.get(line.get("statement_line_id")) or {}
        ns = result.get("netsuite") or {}
        ns_amount = _float(ns.get("amount"))
        stmt_amount = _float(result.get("statement_amount"))
        difference = (round(stmt_amount - ns_amount, 2)
                      if stmt_amount is not None and ns_amount is not None else None)
        rows.append({
            "recon_id": str(uuid.uuid4()),
            "statement_id": statement.get("statement_id"),
            "vendor_id": statement.get("vendor_id"),
            "vendor_name": statement.get("vendor_name"),
            "statement_period": statement.get("statement_period"),
            "line_number": line.get("line_number"),
            "statement_line_id": line.get("statement_line_id"),
            "invoice_number": result.get("invoice_number") or line.get("invoice_number"),
            "original_invoice_number": line.get("document_number"),
            "line_date": None if line.get("line_date") is None else str(line.get("line_date"))[:10],
            "line_amount": line_amount(line),
            "status": result.get("status") or STATUS_NOT_RECONCILED,
            "exception_id": result.get("exception_id"),
            "exception_reason": result.get("exception_reason"),
            "netsuite_record_type": ns.get("record_type"),
            "netsuite_internal_id": None if ns.get("id") is None else str(ns.get("id")),
            "netsuite_tranid": ns.get("tranid"),
            "netsuite_transaction_number": ns.get("transaction_number"),
            "netsuite_amount": ns_amount,
            "difference": difference,
            "netsuite_entity_id": None if ns.get("entity") is None else str(ns.get("entity")),
            "netsuite_location": None if ns.get("location") is None else str(ns.get("location")),
            "source": SOURCE_AUTO,
            "match_rule": result.get("match_rule"),
            "matched_by": "system",
            "matched_at": now,
            "note": result.get("note") or (None if result else line.get("_recon_note")),
            "is_active": 1,
            "created_at": now,
        })
    return rows


def _manual_invoices(statement_id: str) -> set:
    rows = execute_query(
        "SELECT DISTINCT invoice_number FROM recon WHERE statement_id = ? AND source = ? AND is_active = 1",
        [statement_id, SOURCE_MANUAL],
    )
    return {r["invoice_number"] for r in rows if r.get("invoice_number")}


def replace_auto_rows(statement_id: str, rows: list) -> int:
    """Replaces this statement's "auto" rows with `rows`, in one transaction
    on one connection (a statement can have hundreds of lines). Lines whose
    invoice has an active manual match keep their manual rows and get no
    auto row. Returns the number of rows written."""
    manual = _manual_invoices(statement_id)
    keep = [row for row in rows if row.get("invoice_number") not in manual]
    placeholders = ",".join("?" * len(COLUMNS))
    insert = f"INSERT INTO recon ({', '.join(COLUMNS)}) VALUES ({placeholders})"
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM recon WHERE statement_id = ? AND source = ?", [statement_id, SOURCE_AUTO])
        if keep:
            if hasattr(cur, "fast_executemany"):
                cur.fast_executemany = True
            cur.executemany(insert, [[row.get(c) for c in COLUMNS] for row in keep])
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()
    return len(keep)


def mark_resolved(statement_id: str, invoice_number: str, disposition_status: str,
                  resolved_by: str = None, note: str = None) -> None:
    """Accept / Reject (and bulk approve) on an exception: that invoice's
    active auto lines become Accepted / Rejected. Lines with no exception
    status (a matched line sharing the invoice number) are left as they are."""
    status = STATUS_BY_DISPOSITION.get(disposition_status, (disposition_status or "").title())
    exception_statuses = tuple(set(STATUS_BY_REASON.values()))
    placeholders = ",".join("?" * len(exception_statuses))
    execute_sql(
        f"UPDATE recon SET status = ?, matched_by = ?, matched_at = ?, note = ?, updated_at = ? "
        f"WHERE statement_id = ? AND invoice_number = ? AND source = ? AND is_active = 1 "
        f"AND status IN ({placeholders})",
        [status, resolved_by, _now(), note, _now(), statement_id, invoice_number, SOURCE_AUTO,
         *exception_statuses],
    )


def rows_for_statement(statement_id: str) -> list:
    """Active rows for one statement, in line order."""
    return execute_query(
        "SELECT * FROM recon WHERE statement_id = ? AND is_active = 1 ORDER BY line_number, id",
        [statement_id],
    )
