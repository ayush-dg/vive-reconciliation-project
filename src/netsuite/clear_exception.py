"""NetSuite SANDBOX write for "Clear exception" (and its undo).

When a person clears the exception on statement invoice INV123
(web/queries.py clear_exception()), the flag the write-back put in NetSuite
for it comes off, in the sandbox:

  * every bill/credit the write-back flagged for INV123 on this statement
    (custbody_reconciliation_exception set, custbody_statement_reference =
    this statement): exception cleared, NOT reconciled -- nothing else changes;
  * INV123's Statement Line, when the statement has one (a "No match found"
    line): exception type cleared and status "Cleared".

Each write records what it changed first (`before`) and is read back, exactly
as src/netsuite/manual_match.py does, so Undo reuses its
undo_manual_match_writes(): every field goes back only where NetSuite still
holds what we wrote. Only runs when NETSUITE_WRITEBACK_ENABLED=true; never
raises -- the outcome comes back as a status for the recon table.
"""
import json
import logging

from src.netsuite.fields import STATEMENT_LINE_RECORD
from src.netsuite.manual_match import (
    STATUS_FAILED, STATUS_OFF, STATUS_PARTLY, STATUS_PERIOD_LOCKED, STATUS_WRITTEN, _RECORD_TYPE, _bill_check,
    _client, _read_bill, _read_statement_line, _write, find_statement_line, undo_manual_match_writes,
    writeback_enabled,
)
from src.netsuite.writeback import fetch_sandbox_transactions

logger = logging.getLogger(__name__)

STATUS_NOTHING_FLAGGED = "nothing flagged"
STATEMENT_LINE_STATUS = "Cleared"


def _sl_cleared_check(ns):
    def check(record_id):
        row = _read_statement_line(ns, record_id)
        if not row:
            return "record not found on read-back"
        if row.get("custrecord_sl_exception_type"):
            return "read-back: exception type still set"
        return ""
    return check


def clear_exception_writes(statement_id: str, invoice_number: str, statement_entity_ids: list = None,
                           ns=None) -> dict:
    """Removes the NetSuite flag for one cleared exception. Returns
    {"status", "detail", "before" (JSON text for Undo)}. Never raises."""
    if not writeback_enabled():
        return {"status": STATUS_OFF, "detail": "NETSUITE_WRITEBACK_ENABLED is not true -- NetSuite not written",
                "before": None}
    try:
        ns = ns or _client()
        writes = []

        entities = [str(e) for e in (statement_entity_ids or []) if str(e).isdigit()]
        flagged = [r for r in fetch_sandbox_transactions(ns, entities, [invoice_number]).get(invoice_number.lower(), [])
                   if r.get("custbody_reconciliation_exception")
                   and r.get("custbody_statement_reference") == statement_id] if entities else []
        for txn in flagged:
            body = {"custbody_reconciliation_exception": None}
            before = _read_bill(ns, txn["id"])
            _write(ns, writes, "flag cleared", _RECORD_TYPE[txn["type"]], txn["id"], body, before,
                   _bill_check(ns, body, before))

        sl_id = find_statement_line(ns, statement_id, invoice_number)
        if sl_id:
            before = _read_statement_line(ns, sl_id)
            if before.get("custrecord_sl_exception_type") or before.get("custrecord_sl_status") != STATEMENT_LINE_STATUS:
                body = {"custrecord_sl_status": STATEMENT_LINE_STATUS, "custrecord_sl_exception_type": None}
                _write(ns, writes, "statement line", STATEMENT_LINE_RECORD, sl_id, body, before,
                       _sl_cleared_check(ns))

        if not writes:
            return {"status": STATUS_NOTHING_FLAGGED,
                    "detail": f"no flagged bill or Statement Line for {invoice_number} on {statement_id}",
                    "before": None}
        ok = [w for w in writes if w["ok"]]
        if len(ok) == len(writes):
            status = STATUS_WRITTEN
        elif any(w.get("period_locked") for w in writes):
            status = STATUS_PERIOD_LOCKED
        elif ok:
            status = STATUS_PARTLY
        else:
            status = STATUS_FAILED
        detail = "; ".join(f"{w['kind']} {w['record_id']}: {w['detail'].strip()}" for w in writes)
        return {"status": status, "detail": detail[:1900], "before": json.dumps({"writes": writes}, default=str)}
    except Exception as exc:
        logger.exception("Clear-exception NetSuite write failed for %s / %s", statement_id, invoice_number)
        return {"status": STATUS_FAILED, "detail": f"{type(exc).__name__}: {str(exc)[:300]}", "before": None}


def undo_clear_writes(before_json: str, ns=None) -> dict:
    """Puts the flag back (see undo_manual_match_writes()). Never raises."""
    return undo_manual_match_writes(before_json, ns=ns)
