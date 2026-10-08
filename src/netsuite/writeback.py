"""Plans (and, in a later phase, applies) the write-back of one statement's
reconciliation result into the NetSuite SANDBOX.

PHASE 1 = DRY-RUN ONLY. Nothing in this module calls PATCH or POST. It
reads the statement's results out of the Warehouse (silver.recon_matched_
invoices / silver.recon_exceptions), looks each invoice up in the sandbox
by tranid, and produces a list of Plan objects describing exactly what
WOULD be written. build_plans() never mutates anything.

Why the sandbox is looked up again instead of trusting the matcher: the
matcher (src/matching/fabric_matching.py) compares against the Lakehouse
copy of NetSuite and keeps no internal record id, so the write-back has to
find the real bill/credit itself. The matcher's outcome (matched /
mismatch / not found) stays the source of truth for WHAT to write; the
sandbox lookup only decides WHERE, and flags any line where the sandbox
disagrees with the matcher (data drift) instead of writing blindly.

Facts confirmed live against the sandbox 2026-10-07:
- transaction.foreigntotal is NEGATIVE for vendor bills and POSITIVE for
  vendor credits, so every comparison uses abs().
- The same tranid can exist as either record type; the type comes from
  the sandbox row, not from the statement line.
- SuiteQL omits null columns from a row, so absent keys mean "empty".
"""
import json
import logging
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from src.lakehouse.fabric_sql import get_warehouse_connection
from src.matching.netsuite_vendor_resolver import resolve_entity_ids
from src.netsuite.fields import BODY_FIELDS, STATEMENT_LINE_RECORD

logger = logging.getLogger(__name__)

AMOUNT_EPSILON = Decimal("0.005")
_TRANID_CHUNK = 150
_RECORD_TYPE_BY_NS_TYPE = {"VendBill": "vendorbill", "VendCred": "vendorcredit"}

# Matcher exception_reason values (src/matching/fabric_matching.py).
REASON_AMOUNT_MISMATCH = "Amount Mismatch"
REASON_NOT_FOUND = "Not Found in NetSuite"
REASON_DUPLICATE = "Possible Duplicate in NetSuite"

# Plan actions.
PATCH_MATCHED = "PATCH_MATCHED"
PATCH_EXCEPTION = "PATCH_EXCEPTION"
CREATE_STATEMENT_LINE = "CREATE_STATEMENT_LINE"
SKIP_UP_TO_DATE = "SKIP_UP_TO_DATE"
SKIP_RECONCILED_EARLIER = "SKIP_RECONCILED_EARLIER"
SKIP_REVIEW = "SKIP_REVIEW"

# Why a line was NOT written. Shown in the job output and the apply log, so
# the reason an invoice was left out is never a mystery after an automatic run.
CAT_NOT_IN_SANDBOX = "not in sandbox"
CAT_AMOUNT_NOT_TIED = "amount does not tie sandbox"
CAT_AMBIGUOUS = "several matching records"
CAT_LIST_VALUE_MISSING = "exception value missing in NetSuite list"
CAT_NO_BILL_TO_WRITE = "no bill to write to"
CAT_VENDOR_UNRESOLVED = "vendor not resolved"
CAT_UP_TO_DATE = "already up to date"
CAT_RECONCILED_EARLIER = "reconciled by an earlier statement"
CAT_NEEDS_REVIEW = "needs review"

EXCEPTION_AMOUNT_DIFFERS = "Amount differs"
EXCEPTION_DUPLICATE = "Duplicate"

# Matcher reason -> value in NetSuite's Reconciliation Exception custom list.
# "Wrong shop" also exists in that list, but the matcher never produces it
# today, so nothing maps to it yet. Reasons with no bill to write to
# (Not Found, Vendor Not Resolved, EXTRACTION_INCOMPLETE) are absent on purpose.
EXCEPTION_BY_REASON = {
    "Amount Mismatch": EXCEPTION_AMOUNT_DIFFERS,
    "Possible Duplicate in NetSuite": EXCEPTION_DUPLICATE,
}


@dataclass
class StatementContext:
    statement_id: str
    vendor_id: str
    vendor_name: str
    shop: str
    entity_ids: list
    link: str
    link_note: str
    today: str
    exception_ids: dict = field(default_factory=dict)
    primary_entity: str = None
    primary_location: str = None

    @property
    def reference(self) -> str:
        return self.statement_id


@dataclass
class Plan:
    invoice_number: str
    statement_amount: Decimal
    action: str
    record_type: str = None
    record_id: str = None
    sandbox_tranid: str = None
    sandbox_amount: Decimal = None
    fields: dict = field(default_factory=dict)
    note: str = ""
    previous: dict = field(default_factory=dict)
    category: str = ""


# ----------------------------------------------------------------------
# Reading the matcher's results
# ----------------------------------------------------------------------

def _rows_as_dicts(cur) -> list:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def load_statement_results(statement_id: str) -> dict:
    """Returns {"header": dict|None, "matched": [...], "exceptions": [...]}
    for one statement from the Warehouse. Read-only."""
    conn = get_warehouse_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT statement_id, vendor_id, vendor_name_raw, shop_name_raw "
            "FROM silver.statement WHERE statement_id = ?", [statement_id])
        headers = _rows_as_dicts(cur)
        cur.execute(
            "SELECT invoice_number, original_invoice_number, statement_amount, erp_amount "
            "FROM silver.recon_matched_invoices WHERE statement_id = ?", [statement_id])
        matched = _rows_as_dicts(cur)
        cur.execute(
            "SELECT invoice_number, original_invoice_number, statement_amount, erp_amount, "
            "exception_reason, shop FROM silver.recon_exceptions WHERE statement_id = ?",
            [statement_id])
        exceptions = _rows_as_dicts(cur)
    finally:
        conn.close()
    return {"header": headers[0] if headers else None, "matched": matched, "exceptions": exceptions}


def resolve_pdf_link(statement_id: str) -> tuple:
    """Returns (url_or_None, note). The link needs the statement's
    document_hash, which lives on the jobs / extraction_cache rows of the
    app database. The local dev database often has no such row (jobs live
    in the deployed app's DB), so a missing hash is reported, not fatal.

    OFF by default: the link fields are only written when
    NETSUITE_WRITEBACK_PDF_LINK=true (deferred 2026-10-08 -- the link has
    not been verified end to end yet)."""
    if os.getenv("NETSUITE_WRITEBACK_PDF_LINK", "").strip().lower() != "true":
        return None, "PDF link is switched off (NETSUITE_WRITEBACK_PDF_LINK is not true)"
    base = (os.getenv("APP_PUBLIC_BASE_URL") or "").rstrip("/")
    if not base:
        return None, "APP_PUBLIC_BASE_URL is not set"
    try:
        from src.lakehouse.connection import execute_query
        rows = execute_query(
            "SELECT document_hash FROM jobs WHERE statement_id = ? AND document_hash IS NOT NULL",
            [statement_id])
        if not rows:
            rows = execute_query(
                "SELECT document_hash FROM extraction_cache WHERE statement_id = ? "
                "AND document_hash IS NOT NULL", [statement_id])
    except Exception as exc:  # best-effort lookup; the preview must still run
        return None, f"document_hash lookup failed ({type(exc).__name__})"
    if not rows:
        return None, "no document_hash found for this statement in the local app DB"
    return f"{base}/statements/{rows[0]['document_hash']}/pdf", ""


# ----------------------------------------------------------------------
# Reading the sandbox
# ----------------------------------------------------------------------

def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def fetch_sandbox_transactions(ns, entity_ids: list, tranids: list) -> dict:
    """{lowercased tranid: [txn rows]} for non-voided vendor bills and
    credits of these entities. Entity ids are validated as digits-only
    before being inlined into the SuiteQL text. `location` is read from the
    transaction's main line -- it is not a header column, so a plain
    transaction.location query fails in SuiteQL."""
    safe_entities = [e for e in entity_ids if str(e).isdigit()]
    if not safe_entities or not tranids:
        return {}
    entity_list = ",".join(safe_entities)
    by_tranid = {}
    unique = sorted({t.lower() for t in tranids if t})
    for start in range(0, len(unique), _TRANID_CHUNK):
        chunk = ",".join(_sql_literal(t) for t in unique[start:start + _TRANID_CHUNK])
        rows = ns.suiteql(
            "SELECT t.id, t.tranid, t.entity, t.type, t.foreigntotal, tl.location, "
            "t.custbody_reconciled, t.custbody_statement_reference, t.custbody_statement_link, "
            "t.custbody_reconciled_date, t.custbody_reconciliation_exception "
            "FROM transaction t LEFT JOIN transactionline tl "
            "ON tl.transaction = t.id AND tl.mainline = 'T' "
            "WHERE t.type IN ('VendBill','VendCred') AND t.voided = 'F' "
            f"AND t.entity IN ({entity_list}) AND LOWER(t.tranid) IN ({chunk})")
        for row in rows:
            by_tranid.setdefault(row["tranid"].lower(), []).append(row)
    return by_tranid


def fetch_exception_list_ids(ns) -> dict:
    """{value name: internal id} for the Reconciliation Exception list, so
    the plan can show (and Phase 2 can send) the right list value."""
    rows = ns.suiteql("SELECT id, name FROM customlist_exception")
    return {r["name"]: r["id"] for r in rows}


def _line_key(invoice, amount) -> tuple:
    """Identity of a Statement Line within one statement: invoice number
    plus amount, because one invoice can legitimately appear twice with
    different amounts (e.g. an invoice's charge and a separate credit)."""
    amt = _amount(amount)
    return ((invoice or "").lower(), None if amt is None else str(amt.quantize(Decimal("0.01"))))


def fetch_existing_statement_lines(ns, statement_id: str) -> set:
    """(invoice, amount) keys that already have a Statement Line for this
    statement -- the idempotency check for re-runs."""
    rows = ns.suiteql(
        "SELECT custrecord_sl_invoice_number AS inv, custrecord_sl_statement_amount AS amt "
        f"FROM customrecord_statement_line WHERE custrecord_sl_statement_id = {_sql_literal(statement_id)}")
    return {_line_key(r.get("inv"), r.get("amt")) for r in rows}


# ----------------------------------------------------------------------
# Classification (pure -- no I/O)
# ----------------------------------------------------------------------

def _amount(value):
    """abs(value) as a Decimal, or None for a blank amount. Blank statement
    amounts are legitimate (INV-04 lets a row with no amount through), so
    they must be carried as None, never coerced."""
    if value is None or str(value).strip() == "":
        return None
    return abs(Decimal(str(value)))


def _ties(a, b) -> bool:
    """False whenever either side is blank -- nothing to compare."""
    left, right = _amount(a), _amount(b)
    if left is None or right is None:
        return False
    return abs(left - right) <= AMOUNT_EPSILON


def _is_true(value) -> bool:
    return str(value).upper() in ("T", "TRUE")


def _txn_plan_base(invoice, amount, txn, action, fields=None, note="") -> Plan:
    # What the record held BEFORE we write, kept so a write can be undone
    # exactly (see build_revert_actions()).
    previous = {key: txn.get(key) for key in BODY_FIELDS if key in txn or key in (fields or {})}
    return Plan(
        invoice_number=invoice, statement_amount=_amount(amount), action=action,
        record_type=_RECORD_TYPE_BY_NS_TYPE[txn["type"]], record_id=txn["id"],
        sandbox_tranid=txn["tranid"], sandbox_amount=_amount(txn["foreigntotal"]),
        fields=fields or {}, note=note, previous=previous,
    )


def _skip(invoice, amount, note, action=SKIP_REVIEW, category=CAT_NEEDS_REVIEW) -> Plan:
    return Plan(invoice_number=invoice, statement_amount=_amount(amount), action=action,
                note=note, category=category)


_CATEGORY_BY_ACTION = {
    SKIP_UP_TO_DATE: CAT_UP_TO_DATE,
    SKIP_RECONCILED_EARLIER: CAT_RECONCILED_EARLIER,
}


def skip_category(plan: Plan) -> str:
    """Short reason a plan was not written (used for counts and the log)."""
    return _CATEGORY_BY_ACTION.get(plan.action) or plan.category or CAT_NEEDS_REVIEW


def skip_counts(plans: list) -> dict:
    """{reason: count} over every plan that is not a write."""
    counts = {}
    for plan in plans:
        if plan.action not in WRITE_ACTIONS:
            counts[skip_category(plan)] = counts.get(skip_category(plan), 0) + 1
    return counts


def _already_handled(txn, ctx: StatementContext, desired_reconciled: bool, desired_exception_id) -> str:
    """Returns "" if the bill still needs writing, else the skip action."""
    reconciled = _is_true(txn.get("custbody_reconciled"))
    reference = txn.get("custbody_statement_reference")
    if reconciled and reference and reference != ctx.reference:
        return SKIP_RECONCILED_EARLIER
    same_state = (
        reconciled == desired_reconciled
        and reference == ctx.reference
        and str(txn.get("custbody_reconciliation_exception") or "") == str(desired_exception_id or "")
    )
    return SKIP_UP_TO_DATE if same_state else ""


def _matched_fields(ctx: StatementContext) -> dict:
    fields = {
        "custbody_reconciled": True,
        "custbody_reconciled_date": ctx.today,
        "custbody_statement_reference": ctx.reference,
        "custbody_reconciliation_exception": None,
    }
    if ctx.link:
        fields["custbody_statement_link"] = ctx.link
    return fields


def _exception_fields(ctx: StatementContext, exception_name: str) -> dict:
    fields = {
        "custbody_reconciled": False,
        "custbody_reconciliation_exception": {"id": ctx.exception_ids.get(exception_name),
                                              "refName": exception_name},
        "custbody_statement_reference": ctx.reference,
    }
    if ctx.link:
        fields["custbody_statement_link"] = ctx.link
    return fields


def _skip_message(action: str) -> str:
    if action == SKIP_RECONCILED_EARLIER:
        return "already reconciled by an earlier statement -- left untouched"
    return "already carries this statement's result -- nothing to write"


def plan_matched(row, candidates, ctx) -> Plan:
    invoice, amount = row["invoice_number"], row["statement_amount"]
    if not candidates:
        return _skip(invoice, amount, "matcher says matched, but no bill/credit with this tranid in the sandbox",
                     category=CAT_NOT_IN_SANDBOX)
    tying = [c for c in candidates if _ties(c["foreigntotal"], amount)]
    if len(tying) != 1:
        why = "several sandbox records tie" if tying else "no sandbox record ties the amount (or the statement amount is blank)"
        category = CAT_AMBIGUOUS if tying else CAT_AMOUNT_NOT_TIED
        return _skip(invoice, amount, f"matcher says matched, but {why}", category=category)
    txn = tying[0]
    skip = _already_handled(txn, ctx, True, None)
    if skip:
        return _txn_plan_base(invoice, amount, txn, skip, note=_skip_message(skip))
    return _txn_plan_base(invoice, amount, txn, PATCH_MATCHED, _matched_fields(ctx))


def plan_exception_on_bills(row, candidates, ctx, exception_name: str) -> list:
    """Flags existing sandbox bills/credits with an exception list value.
    A duplicate flags EVERY record sharing the tranid; any other exception
    needs exactly one record to be unambiguous."""
    invoice, amount = row["invoice_number"], row["statement_amount"]
    if not candidates:
        return [_skip(invoice, amount, f"matcher flagged '{exception_name}', but no record with this "
                                       "tranid in the sandbox -- nothing to write to",
                      category=CAT_NOT_IN_SANDBOX)]
    if not ctx.exception_ids.get(exception_name):
        return [_skip(invoice, amount, f"'{exception_name}' is not in the sandbox exception list",
                      category=CAT_LIST_VALUE_MISSING)]
    if exception_name != EXCEPTION_DUPLICATE and len(candidates) > 1:
        return [_skip(invoice, amount, "several sandbox records share this tranid -- needs a human pick",
                      category=CAT_AMBIGUOUS)]
    return [_plan_one_exception(row, txn, ctx, exception_name) for txn in candidates]


def _plan_one_exception(row, txn, ctx, exception_name: str) -> Plan:
    invoice, amount = row["invoice_number"], row["statement_amount"]
    if exception_name == EXCEPTION_AMOUNT_DIFFERS and _ties(txn["foreigntotal"], amount):
        return _skip(invoice, amount, "sandbox amount now ties the statement (data drift) -- not flagged",
                     category=CAT_AMOUNT_NOT_TIED)
    skip = _already_handled(txn, ctx, False, ctx.exception_ids.get(exception_name))
    if skip:
        return _txn_plan_base(invoice, amount, txn, skip, note=_skip_message(skip))
    return _txn_plan_base(invoice, amount, txn, PATCH_EXCEPTION, _exception_fields(ctx, exception_name),
                          note=exception_name)


def plan_not_found(row, ctx, existing_lines: set) -> Plan:
    """The only case that creates a Statement Line: the matcher found no
    NetSuite record for this line. The matcher's result is taken as given;
    no second lookup second-guesses it. Filed under the vendor most of
    this statement's matched bills belong to (ctx.primary_entity)."""
    invoice = row["invoice_number"]
    amount = row["statement_amount"]
    if _line_key(invoice, amount) in existing_lines:
        return _skip(invoice, amount, "Statement Line already exists for this statement", SKIP_UP_TO_DATE)
    vendor = ctx.primary_entity or (ctx.entity_ids[0] if ctx.entity_ids else None)
    fields = {
        "name": f"{ctx.statement_id} {invoice}",
        "custrecord_sl_vendor": {"id": vendor} if vendor else None,
        "custrecord_sl_statement_id": ctx.statement_id,
        "custrecord_sl_invoice_number": invoice,
        "custrecord_sl_statement_amount": None if _amount(amount) is None else float(_amount(amount)),
        "custrecord_sl_status": "No match found",
        "custrecord_sl_exception_type": "No match found",
        "custrecord_sl_shop": row.get("shop") or ctx.shop,
    }
    if fields["custrecord_sl_statement_amount"] is None:
        del fields["custrecord_sl_statement_amount"]
    if ctx.primary_location:
        fields["custrecord_sl_location"] = {"id": ctx.primary_location}
    if ctx.link:
        fields["custrecord_sl_statement_link"] = ctx.link
    return Plan(invoice_number=invoice, statement_amount=_amount(amount),
                action=CREATE_STATEMENT_LINE, fields=fields)


def plan_exception_row(row, candidates, ctx, existing_lines: set) -> list:
    """Returns a LIST of plans: a duplicate can flag several bills."""
    reason = row["exception_reason"]
    if reason == REASON_NOT_FOUND:
        return [plan_not_found(row, ctx, existing_lines)]
    exception_name = EXCEPTION_BY_REASON.get(reason)
    if exception_name:
        return plan_exception_on_bills(row, candidates, ctx, exception_name)
    return [_skip(row["invoice_number"], row["statement_amount"], f"'{reason}' is not written back",
                  category=CAT_NO_BILL_TO_WRITE)]


def _primary_entity(matched_rows, sandbox) -> str:
    """The NetSuite entity most of this statement's matched bills belong
    to -- the vendor that Statement Lines are filed under."""
    counts = Counter()
    for row in matched_rows:
        for txn in sandbox.get(row["invoice_number"].lower(), []):
            if _ties(txn["foreigntotal"], row["statement_amount"]):
                counts[str(txn["entity"])] += 1
    return counts.most_common(1)[0][0] if counts else None


def _statement_location(sandbox) -> str:
    """The NetSuite location id this statement's bills and credits share,
    or None. Every statement checked so far sits at one location, so a
    Statement Line (which has no bill of its own to read it from) takes it
    from the statement's other records. If they disagree, or none were
    found, it stays blank rather than guessing."""
    locations = {str(txn["location"]) for txns in sandbox.values() for txn in txns if txn.get("location")}
    return locations.pop() if len(locations) == 1 else None


def build_plans(statement_id: str, ns, today: str = None) -> tuple:
    """Returns (StatementContext, [Plan]) for one statement. Performs
    sandbox READS only."""
    results = load_statement_results(statement_id)
    header = results["header"]
    if not header:
        raise ValueError(f"No silver.statement row for {statement_id}")
    entity_ids = resolve_entity_ids(header["vendor_id"], header["vendor_name_raw"]) or []
    link, link_note = resolve_pdf_link(statement_id)
    ctx = StatementContext(
        statement_id=statement_id, vendor_id=header["vendor_id"],
        vendor_name=header["vendor_name_raw"], shop=header.get("shop_name_raw"),
        entity_ids=[str(e) for e in entity_ids], link=link, link_note=link_note,
        today=today or date.today().isoformat(),
        exception_ids=fetch_exception_list_ids(ns),
    )
    if not ctx.entity_ids:
        return ctx, [_skip(r["invoice_number"], r["statement_amount"], "vendor not resolved to NetSuite entities",
                     category=CAT_VENDOR_UNRESOLVED)
                     for r in results["matched"] + results["exceptions"]]

    tranids = [r["invoice_number"] for r in results["matched"] + results["exceptions"]]
    sandbox = fetch_sandbox_transactions(ns, ctx.entity_ids, tranids)
    existing_lines = fetch_existing_statement_lines(ns, statement_id)
    ctx.primary_entity = _primary_entity(results["matched"], sandbox)
    ctx.primary_location = _statement_location(sandbox)

    plans = [plan_matched(r, sandbox.get(r["invoice_number"].lower(), []), ctx) for r in results["matched"]]
    for r in results["exceptions"]:
        plans.extend(plan_exception_row(r, sandbox.get(r["invoice_number"].lower(), []), ctx, existing_lines))
    return ctx, plans


# ----------------------------------------------------------------------
# Applying a plan (live writes -- sandbox only, enforced by NetSuiteClient)
# ----------------------------------------------------------------------

WRITE_ACTIONS = (PATCH_MATCHED, PATCH_EXCEPTION, CREATE_STATEMENT_LINE)


@dataclass
class ApplyResult:
    plan: Plan
    ok: bool
    detail: str = ""
    new_record_id: str = None
    seconds: float = 0.0


def _read_back_bill(ns, plan: Plan) -> str:
    """Re-reads the bill/credit and returns "" if it carries what we sent,
    else a description of the first difference."""
    rows = ns.suiteql(
        "SELECT custbody_reconciled, custbody_statement_reference, custbody_reconciliation_exception "
        f"FROM transaction WHERE id = {int(plan.record_id)}")
    if not rows:
        return "record not found on read-back"
    row = rows[0]
    wanted_exception = plan.fields.get("custbody_reconciliation_exception")
    wanted_id = str(wanted_exception["id"]) if wanted_exception else ""
    checks = (
        ("reconciled", _is_true(row.get("custbody_reconciled")), plan.fields["custbody_reconciled"]),
        ("statement reference", row.get("custbody_statement_reference"), plan.fields["custbody_statement_reference"]),
        ("exception", str(row.get("custbody_reconciliation_exception") or ""), wanted_id),
    )
    for label, actual, wanted in checks:
        if actual != wanted:
            return f"read-back mismatch on {label}: got {actual!r}, expected {wanted!r}"
    return ""


def _read_back_statement_line(ns, record_id: str, plan: Plan) -> str:
    rows = ns.suiteql(
        "SELECT custrecord_sl_statement_id AS sid FROM customrecord_statement_line "
        f"WHERE id = {int(record_id)}")
    if not rows:
        return "record not found on read-back"
    if rows[0].get("sid") != plan.fields["custrecord_sl_statement_id"]:
        return "read-back mismatch on statement id"
    return ""


def apply_plan(ns, plan: Plan) -> ApplyResult:
    """Performs ONE plan's write, then reads it back. Never raises: a
    failure is returned so the caller can carry on with the next record."""
    started = time.monotonic()
    result = _apply_plan_untimed(ns, plan)
    result.seconds = round(time.monotonic() - started, 2)
    return result


def _apply_plan_untimed(ns, plan: Plan) -> ApplyResult:
    try:
        if plan.action == CREATE_STATEMENT_LINE:
            new_id = ns.create_record(STATEMENT_LINE_RECORD, plan.fields)
            problem = _read_back_statement_line(ns, new_id, plan)
            return ApplyResult(plan, not problem, problem or "created", new_id)
        ns.patch_record(plan.record_type, plan.record_id, plan.fields)
        problem = _read_back_bill(ns, plan)
        return ApplyResult(plan, not problem, problem or "updated", plan.record_id)
    except Exception as exc:  # report and move on -- one bad record must not stop the batch
        body = getattr(exc, "body", "") or ""
        return ApplyResult(plan, False, f"{type(exc).__name__}: {exc} {body[:300]}")


def apply_plans(ns, plans: list) -> list:
    """Applies every write plan in order. If the VERY FIRST write fails the
    run stops there: a first failure usually means a systematic problem
    (permissions, a field format) that would otherwise repeat on every
    record."""
    results = []
    for plan in (p for p in plans if p.action in WRITE_ACTIONS):
        result = apply_plan(ns, plan)
        results.append(result)
        if not result.ok and len(results) == 1:
            break
    return results


# ----------------------------------------------------------------------
# Undoing a write (driven by the JSON log an apply run saved)
# ----------------------------------------------------------------------

def _previous_date_as_iso(value):
    """SuiteQL returns dates as M/D/YYYY; the REST API takes ISO."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def _restore_value(key: str, previous: dict):
    """The value to put back in one body field. With no recorded previous
    value (older logs) the field goes back to empty/unchecked -- right for
    a bill that was only ever written when it carried no earlier result."""
    prev = previous.get(key)
    if key == "custbody_reconciled":
        return _is_true(prev)
    if key == "custbody_reconciliation_exception":
        return {"id": str(prev)} if prev else None
    if key == "custbody_reconciled_date":
        return _previous_date_as_iso(prev)
    return prev or None


def build_revert_actions(log: dict) -> list:
    """From a saved write log, the list of undo actions: bills/credits get
    their fields restored, Statement Lines get deleted. Only writes that
    succeeded are undone."""
    actions = []
    for entry in log["writes"]:
        if not entry["ok"]:
            continue
        if entry["action"] == CREATE_STATEMENT_LINE:
            actions.append({"op": "DELETE", "record_type": entry["record_type"],
                            "record_id": entry["record_id"], "invoice_number": entry["invoice_number"]})
            continue
        previous = entry.get("previous") or {}
        body = {key: _restore_value(key, previous) for key in entry["fields_sent"]}
        actions.append({"op": "PATCH", "record_type": entry["record_type"],
                        "record_id": entry["record_id"], "invoice_number": entry["invoice_number"],
                        "body": body})
    return actions


_STATEMENT_ID_SAFE = re.compile(r"^[A-Za-z0-9_-]+$")
_RESET_BODY = {
    "custbody_reconciled": False,
    "custbody_reconciled_date": None,
    "custbody_statement_reference": None,
    "custbody_reconciliation_exception": None,
}


def find_revert_actions_for_statement(ns, statement_id: str) -> list:
    """Undo actions for everything the write-back stamped with this
    statement id, found in NetSuite itself -- so a run can be reverted
    without its log file (e.g. one made by the deployed app). Bills and
    credits carry the id in custbody_statement_reference, Statement Lines
    in custrecord_sl_statement_id.

    With no log there is no record of earlier values, so the fields go back
    to empty/unchecked -- right in practice, because the write-back never
    writes a bill that already carries another statement's result."""
    if not _STATEMENT_ID_SAFE.match(statement_id or ""):
        raise ValueError(f"Not a valid statement id: {statement_id!r}")
    literal = _sql_literal(statement_id)
    actions = []
    for row in ns.suiteql(
            "SELECT t.id, t.tranid, t.type, t.custbody_statement_link FROM transaction t "
            "WHERE t.type IN ('VendBill','VendCred') "
            f"AND t.custbody_statement_reference = {literal}"):
        body = dict(_RESET_BODY)
        if row.get("custbody_statement_link"):
            body["custbody_statement_link"] = None
        actions.append({"op": "PATCH", "record_type": _RECORD_TYPE_BY_NS_TYPE[row["type"]],
                        "record_id": row["id"], "invoice_number": row["tranid"], "body": body})
    for row in ns.suiteql(
            "SELECT id, custrecord_sl_invoice_number AS inv FROM customrecord_statement_line "
            f"WHERE custrecord_sl_statement_id = {literal}"):
        actions.append({"op": "DELETE", "record_type": STATEMENT_LINE_RECORD,
                        "record_id": row["id"], "invoice_number": row.get("inv") or ""})
    return actions


def apply_revert(ns, actions: list) -> list:
    """Performs each undo action. Never raises; returns (action, ok, detail)."""
    results = []
    for action in actions:
        try:
            if action["op"] == "DELETE":
                ns.delete_record(action["record_type"], action["record_id"])
            else:
                ns.patch_record(action["record_type"], action["record_id"], action["body"])
            results.append((action, True, "reverted"))
        except Exception as exc:  # report and keep going
            body = getattr(exc, "body", "") or ""
            results.append((action, False, f"{type(exc).__name__}: {exc} {body[:300]}"))
    return results


# ----------------------------------------------------------------------
# Audit log of an apply run
# ----------------------------------------------------------------------

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "logs", "netsuite_writeback")


def write_apply_log(ns, statement_id: str, results: list, plans: list = None) -> str:
    """Saves exactly what was sent to NetSuite, record by record, so a
    write can be audited -- and undone (build_revert_actions) -- later.
    With `plans`, every line that was NOT written is recorded too, with
    its reason. One JSON file per apply run; returns its path."""
    os.makedirs(_LOG_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(_LOG_DIR, f"{statement_id}_{stamp}.json")
    entries = [{
        "action": r.plan.action, "invoice_number": r.plan.invoice_number,
        "record_type": r.plan.record_type or STATEMENT_LINE_RECORD,
        "record_id": r.new_record_id or r.plan.record_id,
        "fields_sent": r.plan.fields, "previous": r.plan.previous,
        "ok": r.ok, "detail": r.detail, "seconds": r.seconds,
    } for r in results]
    not_written = [{
        "action": p.action, "invoice_number": p.invoice_number,
        "statement_amount": None if p.statement_amount is None else str(p.statement_amount),
        "record_type": p.record_type, "record_id": p.record_id,
        "reason": skip_category(p), "detail": p.note,
    } for p in (plans or []) if p.action not in WRITE_ACTIONS]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"statement_id": statement_id, "sandbox": ns.domain_id,
                   "applied_at": datetime.now().isoformat(timespec="seconds"),
                   "writes": entries, "not_written": not_written,
                   "not_written_counts": skip_counts(plans or [])}, f, indent=2, default=str)
    return path
