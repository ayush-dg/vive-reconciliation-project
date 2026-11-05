"""NetSuite SANDBOX write for "Clear exception" (and its undo).

When a person clears the exception on statement invoice INV123
(web/queries.py clear_exception()), the flag the write-back put in NetSuite
for it comes off, in the sandbox:

  * every bill/credit the write-back flagged for INV123 on this statement
    (custbody_reconciliation_exception set, custbody_statement_reference =
    this statement): exception cleared, NOT reconciled -- nothing else changes;
  * INV123's Statement Line, when the statement has one: a line the
    write-back created because the invoice was NOT FOUND in NetSuite (status
    "No match found") is DELETED (2026-11-05), so it leaves NetSuite's
    not-found view -- a full copy is kept first and Undo re-creates it (with
    a new internal id). Any other Statement Line keeps the old behaviour:
    exception type cleared and status "Cleared".

Each write records what it changed first (`before`) and is read back, exactly
as src/netsuite/manual_match.py does, so Undo reuses its
undo_manual_match_writes(): every field goes back only where NetSuite still
holds what we wrote. Only runs when NETSUITE_WRITEBACK_ENABLED=true; never
raises -- the outcome comes back as a status for the recon table.
"""
import json
import logging
import re

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
# The status src/netsuite/writeback.py plan_not_found() gives the Statement
# Lines it creates -- only those are deleted when the exception is cleared.
NOT_FOUND_STATUS = "No match found"
DELETED_KIND = "statement line deleted"

# Every Statement Line field the create allowlist (guard.STATEMENT_LINE_FIELDS)
# knows, read before a delete so Undo can re-create the line as it was.
_COPY_FIELDS = (
    "name", "custrecord_sl_vendor", "custrecord_sl_statement_id", "custrecord_sl_invoice_number",
    "custrecord_sl_statement_amount", "custrecord_sl_status", "custrecord_sl_exception_type",
    "custrecord_sl_matched_bill", "custrecord_sl_shop", "custrecord_sl_statement_link",
    "custrecord_sl_location", "custrecord_sl_date", "custrecord_sl_reconciled", "custrecord_sl_reconciled_date",
)
_LINK_FIELDS = ("custrecord_sl_vendor", "custrecord_sl_matched_bill", "custrecord_sl_location")
_BOOL_FIELDS = ("custrecord_sl_reconciled",)
_DATE_FIELDS = ("custrecord_sl_date", "custrecord_sl_reconciled_date")
_NUMBER_FIELDS = ("custrecord_sl_statement_amount",)
_US_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def _iso(value):
    text = str(value or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    m = _US_DATE.match(text.split(" ")[0])
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else None


def _read_full_statement_line(ns, record_id) -> dict:
    rows = ns.suiteql(f"SELECT {', '.join(_COPY_FIELDS)} FROM {STATEMENT_LINE_RECORD} WHERE id = {int(record_id)}")
    return rows[0] if rows else {}


def recreate_body(copy: dict) -> dict:
    """The create body (guard.STATEMENT_LINE_FIELDS shapes) for a Statement
    Line from the copy read before it was deleted. Empty values are left out."""
    body = {}
    for key in _COPY_FIELDS:
        value = copy.get(key)
        if value is None or value == "":
            continue
        if key in _LINK_FIELDS:
            if str(value).strip().isdigit():
                body[key] = {"id": str(value).strip()}
        elif key in _BOOL_FIELDS:
            body[key] = str(value).strip().upper() in ("T", "TRUE", "Y", "YES")
        elif key in _DATE_FIELDS:
            iso = _iso(value)
            if iso:
                body[key] = iso
        elif key in _NUMBER_FIELDS:
            try:
                body[key] = float(value)
            except (TypeError, ValueError):
                pass
        else:
            body[key] = str(value)
    body.setdefault("custrecord_sl_reconciled", False)
    return body


def _delete_not_found_line(ns, writes: list, statement_id: str, sl_id, copy: dict) -> None:
    """Deletes one write-back-created "No match found" Statement Line (the
    client's delete re-reads it and refuses anything not on this statement),
    then checks it is gone. Appends the outcome, with the copy, to `writes`."""
    entry = {"kind": DELETED_KIND, "record_type": STATEMENT_LINE_RECORD, "record_id": sl_id, "sent": {},
             "before": copy, "deleted": True, "ok": False, "detail": ""}
    try:
        ns.delete_record(STATEMENT_LINE_RECORD, sl_id, statement_id=statement_id)
        gone = not _read_full_statement_line(ns, sl_id)
        entry["ok"], entry["detail"] = gone, "deleted" if gone else "read-back: still there after the delete"
    except Exception as exc:
        entry["detail"] = f"{type(exc).__name__}: {str(exc)[:200]} {str(getattr(exc, 'body', '') or '')[:300]}"
    writes.append(entry)


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
        copy = _read_full_statement_line(ns, sl_id) if sl_id else {}
        if sl_id and str(copy.get("custrecord_sl_status") or "").strip().lower() == NOT_FOUND_STATUS.lower():
            _delete_not_found_line(ns, writes, statement_id, sl_id, copy)
        elif sl_id:
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
    """Puts NetSuite back: a Statement Line the clear deleted is created
    again from its copy (a new internal id), and every patched field is
    restored by undo_manual_match_writes(). Never raises."""
    try:
        writes = json.loads(before_json).get("writes", []) if before_json else []
    except (TypeError, ValueError, AttributeError):
        writes = []
    deleted = [w for w in writes if w.get("deleted") and w.get("ok")]
    if not deleted:
        return undo_manual_match_writes(before_json, ns=ns)
    if not writeback_enabled():
        return {"status": STATUS_OFF, "detail": "NETSUITE_WRITEBACK_ENABLED is not true -- NetSuite not changed"}
    notes, failed = [], False
    try:
        ns = ns or _client()
        for entry in deleted:
            try:
                new_id = ns.create_record(STATEMENT_LINE_RECORD, recreate_body(entry["before"]))
                notes.append(f"statement line {entry['record_id']}: re-created as {new_id}")
            except Exception as exc:
                failed = True
                notes.append(f"statement line {entry['record_id']}: re-create failed "
                             f"({type(exc).__name__}: {str(exc)[:200]})")
        rest = [w for w in writes if not w.get("deleted")]
        if rest:
            other = undo_manual_match_writes(json.dumps({"writes": rest}, default=str), ns=ns)
            failed = failed or other.get("status") == STATUS_FAILED
            notes.append(other.get("detail") or "")
    except Exception as exc:
        logger.exception("Clear-exception NetSuite undo failed")
        return {"status": STATUS_FAILED, "detail": f"{type(exc).__name__}: {str(exc)[:300]}"}
    return {"status": STATUS_FAILED if failed else "undone", "detail": "; ".join(n for n in notes if n)[:1900]}
