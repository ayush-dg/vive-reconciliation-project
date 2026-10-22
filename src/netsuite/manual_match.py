"""NetSuite SANDBOX write for a manual "Accept as match" (and its undo).

When a person accepts NetSuite bill/credit 23 for statement invoice INV123
(web/queries.py accept_manual_match()), this writes, in the sandbox:

  * bill 23: reconciled, reconciled date, statement reference, exception
    cleared, "Matched Bill" (custbody_matched_bill) = INV123, and the
    statement PDF link when that's switched on;
  * INV123's Statement Line: status "Matched", matched bill = 23, reconciled
    and its date -- updated if the statement already has one for INV123
    (a "Not found" line), created otherwise;
  * a different bill the write-back had flagged for INV123 (e.g. "Amount
    differs"): that flag cleared, NOT reconciled.

Everything a write changes is recorded first (`before`), and each write is
read back. undo_manual_match_writes() puts every field back -- but only where
NetSuite still holds what we wrote, so a later edit by someone else is left
alone and reported -- and deletes a Statement Line this created.

The sandbox is looked up by tranid + vendor entity (+ amount), never by the
Lakehouse internal id: that copy is live NetSuite, and the sandbox's ids can
differ. Only runs when NETSUITE_WRITEBACK_ENABLED=true; never raises -- the
outcome comes back as a status for the recon table.
"""
import json
import logging
import os
from datetime import date

from src.netsuite.fields import MATCHED_BILL_FIELD, STATEMENT_LINE_RECORD
from src.netsuite.writeback import (
    _is_period_locked, _is_true, _sql_literal, _ties, fetch_sandbox_transactions, resolve_pdf_link,
)

logger = logging.getLogger(__name__)

STATUS_WRITTEN = "written"
STATUS_PARTLY = "partly written"
STATUS_PERIOD_LOCKED = "period locked"
STATUS_NOT_IN_SANDBOX = "not in sandbox"
STATUS_AMBIGUOUS = "several matching records"
STATUS_RECONCILED_ELSEWHERE = "reconciled by another statement"
STATUS_FAILED = "failed"
STATUS_OFF = "write-back off"

_NS_TYPE = {"bill": "VendBill", "credit": "VendCred"}
_RECORD_TYPE = {"VendBill": "vendorbill", "VendCred": "vendorcredit"}
_BILL_FIELDS = ("custbody_reconciled", "custbody_reconciled_date", "custbody_statement_reference",
                "custbody_reconciliation_exception", MATCHED_BILL_FIELD, "custbody_statement_link")
_SL_FIELDS = ("custrecord_sl_status", "custrecord_sl_exception_type", "custrecord_sl_matched_bill",
              "custrecord_sl_reconciled", "custrecord_sl_reconciled_date")


def writeback_enabled() -> bool:
    return os.getenv("NETSUITE_WRITEBACK_ENABLED", "").strip().lower() == "true"


def _client():
    from src.netsuite.client import NetSuiteClient
    return NetSuiteClient()


def _read_bill(ns, record_id) -> dict:
    rows = ns.suiteql(f"SELECT {', '.join(_BILL_FIELDS)} FROM transaction WHERE id = {int(record_id)}")
    return rows[0] if rows else {}


def _read_statement_line(ns, record_id) -> dict:
    rows = ns.suiteql(f"SELECT {', '.join(_SL_FIELDS)} FROM {STATEMENT_LINE_RECORD} WHERE id = {int(record_id)}")
    return rows[0] if rows else {}


def find_statement_line(ns, statement_id: str, invoice_number: str):
    """The Statement Line this statement already has for the invoice, or None."""
    rows = ns.suiteql(
        f"SELECT id FROM {STATEMENT_LINE_RECORD} WHERE custrecord_sl_statement_id = {_sql_literal(statement_id)} "
        f"AND LOWER(custrecord_sl_invoice_number) = {_sql_literal(invoice_number.lower())}")
    return rows[0]["id"] if rows else None


def find_sandbox_record(ns, record: dict):
    """(sandbox txn, status) for the picked bill/credit: same tranid, type and
    vendor entity, amount tying. status is "" when exactly one was found."""
    entity = str(record.get("entity_id") or "")
    if not entity.isdigit() or not record.get("tranid"):
        return None, STATUS_NOT_IN_SANDBOX
    rows = fetch_sandbox_transactions(ns, [entity], [record["tranid"]]).get(record["tranid"].lower(), [])
    wanted_type = _NS_TYPE.get(str(record.get("record_type", "")).lower())
    rows = [r for r in rows if r.get("type") == wanted_type and _ties(r.get("foreigntotal"), record.get("total"))]
    if not rows:
        return None, STATUS_NOT_IN_SANDBOX
    if len(rows) > 1:
        return None, STATUS_AMBIGUOUS
    return rows[0], ""


def _write(ns, writes: list, kind: str, record_type: str, record_id, body: dict, before: dict, check) -> None:
    """One PATCH (or POST when record_id is None) + read-back; appends the
    outcome to `writes`. Never raises."""
    entry = {"kind": kind, "record_type": record_type, "record_id": record_id, "sent": body,
             "before": before, "ok": False, "detail": ""}
    try:
        if record_id is None:
            entry["record_id"] = ns.create_record(record_type, body)
            entry["created"] = True
        else:
            ns.patch_record(record_type, record_id, body)
        problem = check(entry["record_id"])
        entry["ok"], entry["detail"] = not problem, problem or "ok"
    except Exception as exc:  # one record failing must not stop the others
        entry["detail"] = f"{type(exc).__name__}: {str(exc)[:200]} {str(getattr(exc, 'body', '') or '')[:300]}"
        entry["period_locked"] = _is_period_locked(exc)
    writes.append(entry)


def _bill_check(ns, body):
    def check(record_id):
        row = _read_bill(ns, record_id)
        if not row:
            return "record not found on read-back"
        if "custbody_reconciled" in body and _is_true(row.get("custbody_reconciled")) != body["custbody_reconciled"]:
            return "read-back mismatch on reconciled"
        for key in ("custbody_statement_reference", MATCHED_BILL_FIELD):
            if key in body and (row.get(key) or None) != body[key]:
                return f"read-back mismatch on {key}"
        if "custbody_reconciliation_exception" in body and row.get("custbody_reconciliation_exception"):
            return "read-back: exception still set"
        return ""
    return check


def _sl_check(ns, body):
    def check(record_id):
        row = _read_statement_line(ns, record_id)
        if not row:
            return "record not found on read-back"
        if str(row.get("custrecord_sl_matched_bill") or "") != str(body["custrecord_sl_matched_bill"]["id"]):
            return "read-back mismatch on matched bill"
        return ""
    return check


def write_manual_match(statement_id: str, invoice_number: str, statement_amount, record: dict,
                       statement_entity_ids: list = None, shop: str = None, ns=None, today: str = None) -> dict:
    """Writes one accepted manual match to the sandbox. Returns
    {"status", "detail", "statement_line_id", "before" (JSON text for undo)}.
    Never raises."""
    if not writeback_enabled():
        return {"status": STATUS_OFF, "detail": "NETSUITE_WRITEBACK_ENABLED is not true -- NetSuite not written",
                "statement_line_id": None, "before": None}
    today = today or date.today().isoformat()
    try:
        ns = ns or _client()
        txn, problem = find_sandbox_record(ns, record)
        if not txn:
            return {"status": problem, "detail": f"{record.get('record_type')} {record.get('tranid')}: {problem}",
                    "statement_line_id": None, "before": None}
        reference = txn.get("custbody_statement_reference")
        if _is_true(txn.get("custbody_reconciled")) and reference and reference != statement_id:
            return {"status": STATUS_RECONCILED_ELSEWHERE,
                    "detail": f"{txn['tranid']} is already reconciled by {reference} -- not changed",
                    "statement_line_id": None, "before": None}

        record_type = _RECORD_TYPE[txn["type"]]
        writes = []
        link, _ = resolve_pdf_link(statement_id)

        # 1. The picked bill/credit.
        bill_body = {"custbody_reconciled": True, "custbody_reconciled_date": today,
                     "custbody_statement_reference": statement_id, "custbody_reconciliation_exception": None,
                     MATCHED_BILL_FIELD: invoice_number}
        if link:
            bill_body["custbody_statement_link"] = link
        _write(ns, writes, "bill", record_type, txn["id"], bill_body, _read_bill(ns, txn["id"]),
               _bill_check(ns, bill_body))

        # 2. A different bill the write-back flagged for this invoice: clear the flag only.
        flagged = [r for r in fetch_sandbox_transactions(ns, [e for e in (statement_entity_ids or []) if str(e).isdigit()],
                                                         [invoice_number]).get(invoice_number.lower(), [])
                   if str(r["id"]) != str(txn["id"]) and r.get("custbody_reconciliation_exception")
                   and r.get("custbody_statement_reference") == statement_id]
        for old in flagged:
            body = {"custbody_reconciliation_exception": None}
            _write(ns, writes, "flag cleared", _RECORD_TYPE[old["type"]], old["id"], body,
                   _read_bill(ns, old["id"]), _bill_check(ns, body))

        # 3. The Statement Line for the invoice: update it, or create it.
        sl_body = {"custrecord_sl_status": "Matched", "custrecord_sl_exception_type": None,
                   "custrecord_sl_matched_bill": {"id": str(txn["id"])},
                   "custrecord_sl_reconciled": True, "custrecord_sl_reconciled_date": today}
        sl_id = find_statement_line(ns, statement_id, invoice_number)
        if sl_id:
            _write(ns, writes, "statement line", STATEMENT_LINE_RECORD, sl_id, sl_body,
                   _read_statement_line(ns, sl_id), _sl_check(ns, sl_body))
        else:
            amount = None if statement_amount is None else abs(float(statement_amount))
            create_body = dict(sl_body, name=f"{statement_id} {invoice_number}",
                               custrecord_sl_vendor={"id": str(txn["entity"])},
                               custrecord_sl_statement_id=statement_id, custrecord_sl_invoice_number=invoice_number,
                               custrecord_sl_date=today)
            if amount is not None:
                create_body["custrecord_sl_statement_amount"] = amount
            if shop:
                create_body["custrecord_sl_shop"] = shop
            if txn.get("location"):
                create_body["custrecord_sl_location"] = {"id": str(txn["location"])}
            if link:
                create_body["custrecord_sl_statement_link"] = link
            _write(ns, writes, "statement line", STATEMENT_LINE_RECORD, None, create_body, {},
                   _sl_check(ns, create_body))

        ok = [w for w in writes if w["ok"]]
        if len(ok) == len(writes):
            status = STATUS_WRITTEN
        elif any(w.get("period_locked") for w in writes):
            status = STATUS_PERIOD_LOCKED
        elif ok:
            status = STATUS_PARTLY
        else:
            status = STATUS_FAILED
        sl_written = next((w for w in writes if w["kind"] == "statement line" and w["ok"]), None)
        detail = "; ".join(f"{w['kind']} {w['record_id']}: {w['detail'].strip()}" for w in writes)
        return {"status": status, "detail": detail[:1900],
                "statement_line_id": None if not sl_written else str(sl_written["record_id"]),
                "before": json.dumps({"writes": writes}, default=str)}
    except Exception as exc:
        logger.exception("Manual-match NetSuite write failed for %s / %s", statement_id, invoice_number)
        return {"status": STATUS_FAILED, "detail": f"{type(exc).__name__}: {str(exc)[:300]}",
                "statement_line_id": None, "before": None}


def _restore(key, value):
    """A value read by SuiteQL, in the shape the REST PATCH takes."""
    from src.netsuite.writeback import _previous_date_as_iso
    if key in ("custbody_reconciled", "custrecord_sl_reconciled"):
        return _is_true(value)
    if key in ("custbody_reconciliation_exception", "custrecord_sl_matched_bill"):
        return {"id": str(value)} if value else None
    if key in ("custbody_reconciled_date", "custrecord_sl_reconciled_date"):
        return _previous_date_as_iso(value)
    return value or None


def _still_ours(current: dict, sent: dict) -> list:
    """The fields that no longer hold what we wrote (someone changed them since)."""
    changed = []
    for key, value in sent.items():
        now = current.get(key)
        if isinstance(value, bool):
            same = _is_true(now) == value
        elif isinstance(value, dict):
            same = str(now or "") == str(value.get("id") or "")
        elif key.endswith("_date"):
            same = True  # SuiteQL and REST spell dates differently; the date alone never blocks an undo
        else:
            same = (now or None) == value
        if not same:
            changed.append(key)
    return changed


def undo_manual_match_writes(before_json: str, ns=None) -> dict:
    """Puts NetSuite back as it was before write_manual_match(): each field
    we wrote is restored only if it still holds our value (anything changed
    since is left alone and listed), and a Statement Line we created is
    deleted. Returns {"status", "detail"}. Never raises."""
    if not before_json:
        return {"status": "nothing to undo", "detail": "no NetSuite write was recorded"}
    if not writeback_enabled():
        return {"status": STATUS_OFF, "detail": "NETSUITE_WRITEBACK_ENABLED is not true -- NetSuite not changed"}
    try:
        ns = ns or _client()
        notes, failed = [], False
        for entry in json.loads(before_json).get("writes", []):
            if not entry.get("ok"):
                continue
            rid, rtype = entry["record_id"], entry["record_type"]
            try:
                if entry.get("created"):
                    ns.delete_record(rtype, rid)
                    notes.append(f"{entry['kind']} {rid}: deleted")
                    continue
                current = _read_statement_line(ns, rid) if rtype == STATEMENT_LINE_RECORD else _read_bill(ns, rid)
                changed = _still_ours(current, entry["sent"])
                body = {k: _restore(k, entry["before"].get(k)) for k in entry["sent"] if k not in changed}
                if body:
                    ns.patch_record(rtype, rid, body)
                notes.append(f"{entry['kind']} {rid}: restored" +
                             (f" (left alone, changed since: {', '.join(changed)})" if changed else ""))
            except Exception as exc:
                failed = True
                notes.append(f"{entry['kind']} {rid}: undo failed ({type(exc).__name__})")
        return {"status": STATUS_FAILED if failed else "undone", "detail": "; ".join(notes)[:1900]}
    except Exception as exc:
        logger.exception("Manual-match NetSuite undo failed")
        return {"status": STATUS_FAILED, "detail": f"{type(exc).__name__}: {str(exc)[:300]}"}
