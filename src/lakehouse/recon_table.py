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


MANUAL_RULE = "picked in Find in NetSuite"
_MATCHED_STATUSES = (STATUS_MATCHED, STATUS_MATCHED_MANUALLY)


class MatchConflict(Exception):
    """The picked bill/credit is already reconciled to another statement line."""


def _rows(cur, sql, params):
    cur.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def accept_manual_match(statement_id: str, invoice_number: str, exception_id: str,
                        exception_reason: str, statement_amount, record: dict, matched_by: str,
                        note: str = None, vendor_id: str = None, vendor_name: str = None) -> int:
    """A person accepted a NetSuite bill/credit for one statement invoice
    ("Accept as match"). Adds a "manual" Matched-manually row for each of the
    invoice's lines -- linked to `record` (a netsuite_search row: internal_id,
    tranid, record_type, total, ...), difference = statement amount minus the
    record's total -- and sets the invoice's auto rows inactive, in one
    transaction. Raises MatchConflict when that record is already matched to
    another statement line, ValueError when this invoice already has an
    active manual match. Returns the number of rows added."""
    now = _now()
    conn = get_connection()
    try:
        cur = conn.cursor()
        if _rows(cur, "SELECT recon_id FROM recon WHERE statement_id = ? AND invoice_number = ? "
                      "AND source = ? AND is_active = 1", [statement_id, invoice_number, SOURCE_MANUAL]):
            raise ValueError(f"Invoice {invoice_number} already has a manual match on this statement.")
        taken = _rows(cur, "SELECT statement_id, invoice_number FROM recon WHERE netsuite_internal_id = ? "
                           "AND netsuite_record_type = ? AND is_active = 1 AND status IN (?, ?) "
                           "AND NOT (statement_id = ? AND invoice_number = ?)",
                      [str(record["internal_id"]), record["record_type"].lower(), *_MATCHED_STATUSES,
                       statement_id, invoice_number])
        if taken:
            raise MatchConflict(f"NetSuite {record['record_type'].lower()} {record.get('tranid')} is already "
                                f"matched to invoice {taken[0]['invoice_number']} on {taken[0]['statement_id']}.")
        auto = _rows(cur, "SELECT * FROM recon WHERE statement_id = ? AND invoice_number = ? AND source = ? "
                          "AND is_active = 1 ORDER BY line_number", [statement_id, invoice_number, SOURCE_AUTO])
        lines = auto or [{"vendor_id": vendor_id, "vendor_name": vendor_name, "line_amount": _float(statement_amount)}]
        ns_amount, stmt_amount = _float(record.get("total")), _float(statement_amount)
        difference = (round(abs(stmt_amount) - ns_amount, 2)
                      if stmt_amount is not None and ns_amount is not None else None)
        rows = []
        for line in lines:
            rows.append({
                "recon_id": str(uuid.uuid4()), "statement_id": statement_id,
                "vendor_id": line.get("vendor_id") or vendor_id, "vendor_name": line.get("vendor_name") or vendor_name,
                "statement_period": line.get("statement_period"), "line_number": line.get("line_number"),
                "statement_line_id": line.get("statement_line_id"), "invoice_number": invoice_number,
                "original_invoice_number": line.get("original_invoice_number"), "line_date": line.get("line_date"),
                "line_amount": line.get("line_amount"), "status": STATUS_MATCHED_MANUALLY,
                "exception_id": exception_id, "exception_reason": exception_reason,
                "netsuite_record_type": record["record_type"].lower(), "netsuite_internal_id": str(record["internal_id"]),
                "netsuite_tranid": record.get("tranid"), "netsuite_transaction_number": record.get("transaction_number"),
                "netsuite_amount": ns_amount, "difference": difference,
                "netsuite_entity_id": None if record.get("entity_id") is None else str(record.get("entity_id")),
                "netsuite_location": None if record.get("location_code") is None else str(record.get("location_code")),
                "source": SOURCE_MANUAL, "match_rule": MANUAL_RULE, "matched_by": matched_by,
                "matched_at": now, "note": note or None, "is_active": 1, "created_at": now,
            })
        insert = f"INSERT INTO recon ({', '.join(COLUMNS)}) VALUES ({','.join('?' * len(COLUMNS))})"
        cur.executemany(insert, [[row.get(c) for c in COLUMNS] for row in rows])
        cur.execute("UPDATE recon SET is_active = 0, updated_at = ? WHERE statement_id = ? AND invoice_number = ? "
                    "AND source = ? AND is_active = 1", [now, statement_id, invoice_number, SOURCE_AUTO])
        conn.commit()
        return len(rows)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def undo_manual_match(statement_id: str, invoice_number: str, undone_by: str) -> dict:
    """Undo of a manual match: its rows stay as history (inactive, undone by /
    at) and the invoice's auto rows come back with their exception status.
    Returns {"exception_ids": [...], "tranid": ...} of what was undone, or
    {} when there was no active manual match."""
    now = _now()
    conn = get_connection()
    try:
        cur = conn.cursor()
        manual = _rows(cur, "SELECT * FROM recon WHERE statement_id = ? AND invoice_number = ? AND source = ? "
                            "AND is_active = 1", [statement_id, invoice_number, SOURCE_MANUAL])
        if not manual:
            return {}
        cur.execute("UPDATE recon SET is_active = 0, undone_by = ?, undone_at = ?, updated_at = ? "
                    "WHERE statement_id = ? AND invoice_number = ? AND source = ? AND is_active = 1",
                    [undone_by, now, now, statement_id, invoice_number, SOURCE_MANUAL])
        for row in _rows(cur, "SELECT recon_id, exception_reason FROM recon WHERE statement_id = ? AND "
                              "invoice_number = ? AND source = ?", [statement_id, invoice_number, SOURCE_AUTO]):
            status = status_for_reason(row["exception_reason"]) if row.get("exception_reason") else STATUS_MATCHED
            cur.execute("UPDATE recon SET is_active = 1, status = ?, updated_at = ? WHERE recon_id = ?",
                        [status, now, row["recon_id"]])
        conn.commit()
        return {"exception_ids": sorted({m["exception_id"] for m in manual if m.get("exception_id")}),
                "tranid": manual[0].get("netsuite_tranid")}
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def manual_matches(statement_id: str) -> list:
    """Active manual matches on one statement, one per invoice (its first
    line's row), for the review page's "Matched manually" list."""
    rows = execute_query(
        "SELECT * FROM recon WHERE statement_id = ? AND source = ? AND is_active = 1 ORDER BY invoice_number, line_number",
        [statement_id, SOURCE_MANUAL],
    )
    seen, out = set(), []
    for row in rows:
        if row["invoice_number"] not in seen:
            seen.add(row["invoice_number"])
            out.append(row)
    return out
