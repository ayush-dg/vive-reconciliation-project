"""Write guardrails for NetSuite: the code may only ever write OUR custom fields.

Every write goes through NetSuiteClient.patch_record / create_record /
delete_record, and each of those calls a check here BEFORE any request is
sent. A write that is not on the allowlist raises WriteBlocked and nothing
leaves the machine. The rules (see docs/NETSUITE_WRITEBACK.md):

  * Bills and credits (vendorbill, vendorcredit): PATCH only, and only the six
    custbody_* fields below. Never created, never deleted.
  * Statement Lines (customrecord_statement_line): create, patch and delete,
    only the custrecord_sl_* fields below (+ name). A delete also needs the
    statement id the row must belong to; the client reads the row and refuses
    to delete one that belongs to another statement.
  * Any other record type, or any other field (including a nested key), is
    refused, and every value is checked for shape before it is sent.

The second half is the "nothing else changed" check: a bill's key fields (see
KEY_FIELDS) are read when the write is planned and again right after it, and a
difference means something outside our fields moved (for example a NetSuite
workflow reacting to the save).
"""
import re
from decimal import Decimal, InvalidOperation

BILL_RECORD_TYPES = ("vendorbill", "vendorcredit")
STATEMENT_LINE_RECORD = "customrecord_statement_line"

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DIGITS = re.compile(r"^\d+$")


class WriteBlocked(Exception):
    """A write the guard refuses. Raised before anything is sent to NetSuite."""


# ----------------------------------------------------------------------
# Value checks: each returns "" when fine, else why not
# ----------------------------------------------------------------------

def _optional(check):
    return lambda value: "" if value is None else check(value)


def _boolean(value):
    return "" if isinstance(value, bool) else "must be true or false"


def _text(max_len):
    def check(value):
        if not isinstance(value, str):
            return "must be text"
        if len(value) > max_len:
            return f"longer than {max_len} characters"
        return ""
    return check


def _iso_date(value):
    return "" if isinstance(value, str) and _ISO_DATE.match(value) else "must be YYYY-MM-DD"


def _url(max_len):
    def check(value):
        if not isinstance(value, str) or not value.startswith("https://"):
            return "must be an https:// address"
        if len(value) > max_len or any(ch.isspace() for ch in value):
            return f"must be one line of at most {max_len} characters"
        return ""
    return check


def _number(value):
    if isinstance(value, bool):
        return "must be a number"
    if isinstance(value, (int, float, Decimal)):
        return ""
    return "must be a number"


def _record_link(value):
    """{"id": "123"} -- optionally with a refName label -- and nothing else."""
    if not isinstance(value, dict) or not set(value) <= {"id", "refName"}:
        return 'must be {"id": "<digits>"}'
    if not isinstance(value.get("id"), (str, int)) or not _DIGITS.match(str(value["id"])):
        return "id must be digits"
    if "refName" in value and not isinstance(value["refName"], str):
        return "refName must be text"
    return ""


# ----------------------------------------------------------------------
# The allowlists
# ----------------------------------------------------------------------

BILL_FIELDS = {
    "custbody_reconciled": _boolean,
    "custbody_reconciled_date": _optional(_iso_date),
    "custbody_statement_reference": _optional(_text(100)),
    "custbody_statement_link": _optional(_url(999)),
    "custbody_reconciliation_exception": _optional(_record_link),
    "custbody_matched_bill": _optional(_text(200)),
}

STATEMENT_LINE_FIELDS = {
    "name": _text(300),
    "custrecord_sl_vendor": _optional(_record_link),
    "custrecord_sl_statement_id": _text(100),
    "custrecord_sl_invoice_number": _text(200),
    "custrecord_sl_statement_amount": _optional(_number),
    "custrecord_sl_status": _optional(_text(100)),
    "custrecord_sl_exception_type": _optional(_text(100)),
    "custrecord_sl_matched_bill": _optional(_record_link),
    "custrecord_sl_shop": _optional(_text(300)),
    "custrecord_sl_statement_link": _optional(_url(999)),
    "custrecord_sl_location": _optional(_record_link),
    "custrecord_sl_date": _optional(_iso_date),
    "custrecord_sl_reconciled": _boolean,
    "custrecord_sl_reconciled_date": _optional(_iso_date),
}

# A new Statement Line must at least say which statement and invoice it is for.
_REQUIRED_ON_CREATE = ("name", "custrecord_sl_statement_id", "custrecord_sl_invoice_number")


def _fields_for(record_type: str) -> dict:
    if record_type in BILL_RECORD_TYPES:
        return BILL_FIELDS
    if record_type == STATEMENT_LINE_RECORD:
        return STATEMENT_LINE_FIELDS
    raise WriteBlocked(f"record type {record_type!r} is not one this tool may write to")


def _check_id(record_id):
    if not isinstance(record_id, (str, int)) or isinstance(record_id, bool) or not _DIGITS.match(str(record_id)):
        raise WriteBlocked(f"record id {record_id!r} is not a number")


def _check_body(record_type: str, body):
    allowed = _fields_for(record_type)
    if not isinstance(body, dict) or not body:
        raise WriteBlocked("the write has no fields")
    extra = sorted(set(body) - set(allowed))
    if extra:
        raise WriteBlocked(f"{record_type}: field(s) not on the allowlist: {', '.join(map(str, extra))}")
    for key, value in body.items():
        problem = allowed[key](value)
        if problem:
            raise WriteBlocked(f"{record_type}.{key}: {problem}")


def check_patch(record_type: str, record_id, body):
    _fields_for(record_type)
    _check_id(record_id)
    _check_body(record_type, body)


def check_create(record_type: str, body):
    if record_type != STATEMENT_LINE_RECORD:
        raise WriteBlocked(f"{record_type!r}: only Statement Lines may be created")
    _check_body(record_type, body)
    missing = [key for key in _REQUIRED_ON_CREATE if not body.get(key)]
    if missing:
        raise WriteBlocked(f"a new Statement Line needs: {', '.join(missing)}")


def check_delete(record_type: str, record_id, statement_id):
    if record_type != STATEMENT_LINE_RECORD:
        raise WriteBlocked(f"{record_type!r}: only Statement Lines may be deleted")
    _check_id(record_id)
    if not statement_id or not isinstance(statement_id, str):
        raise WriteBlocked("a Statement Line can only be deleted for a named statement")


def check_delete_target(row_statement_id, statement_id):
    """The Statement Line really belongs to the statement being undone."""
    if row_statement_id != statement_id:
        raise WriteBlocked(
            f"Statement Line belongs to {row_statement_id!r}, not {statement_id!r}; not deleted")


# ----------------------------------------------------------------------
# "Nothing else changed": the key fields of a bill or credit
# ----------------------------------------------------------------------

# SuiteQL column -> how it is compared. Read when the write is planned and again
# after it; a change in any of them means a field outside ours moved.
KEY_FIELDS = ("tranid", "entity", "foreigntotal", "trandate", "postingperiod", "status", "approvalstatus", "currency")
KEY_FIELD_COLUMNS = ", ".join(f"t.{name}" for name in KEY_FIELDS)


def _same(a, b) -> bool:
    if a == b:
        return True
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except (InvalidOperation, ValueError):
        return str(a).strip().lower() == str(b).strip().lower()


def key_snapshot(row: dict) -> dict:
    """The key fields of a SuiteQL row (only those the row actually has)."""
    return {name: row.get(name) for name in KEY_FIELDS if row.get(name) is not None}


def key_field_changes(before: dict, after: dict) -> list:
    """Names of key fields whose value differs between two snapshots/rows.
    A field missing from either side cannot be compared and is skipped."""
    changed = []
    for name in KEY_FIELDS:
        old, new = (before or {}).get(name), (after or {}).get(name)
        if old is None or new is None:
            continue
        if not _same(old, new):
            changed.append(name)
    return changed
