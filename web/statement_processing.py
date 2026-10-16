"""
statement_processing.py

Statement Processing (2026-10-16, was the Validation page): every intake
attempt as a card with its three stages -- Extraction, Validation,
Reconciliation -- and a one-line reason, plus the detail page's
line-by-line NetSuite comparison. Pure functions over rows the router reads
(queries.get_validation_report(), get_processing_jobs(), get_recon_status()),
so the stage rules are testable without a database.

Stage states: "ok", "fail", "warn" (reconciled with exceptions), "run"
(queued / running) and "skip" (not reached).
"""

import re

from web.deps import friendly_error

VALIDATION_NOTES = {
    "mismatch": "Extracted total doesn't match printed total.",
    "total_not_found": "No printed total found to check the extracted lines against.",
    "no_line_items": "No line items were extracted.",
    "not_a_statement": "Doesn't look like a vendor statement.",
}

MISMATCH, NOT_FOUND, DUPLICATE = "Amount Mismatch", "Not Found in NetSuite", "Possible Duplicate in NetSuite"
ACTIVE_JOB = ("PENDING", "PROCESSING")


def _stage(name, state, label):
    return {"name": name, "state": state, "label": label}


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def reason_summary(reasons: dict) -> str:
    """{"Amount Mismatch": 3, "Not Found in NetSuite": 2} ->
    "Amount mismatch on 3 invoices, 2 not found in NetSuite." """
    reasons = {k: v for k, v in (reasons or {}).items() if v}
    if not reasons:
        return ""
    parts = []
    if reasons.get(MISMATCH):
        parts.append(f"amount mismatch on {_plural(reasons[MISMATCH], 'invoice')}")
    if reasons.get(NOT_FOUND):
        n = reasons[NOT_FOUND]
        parts.append(f"{_plural(n, 'invoice')} not found in NetSuite" if not parts else f"{n} not found in NetSuite")
    if reasons.get(DUPLICATE):
        parts.append(f"{_plural(reasons[DUPLICATE], 'possible duplicate')} in NetSuite")
    for reason, n in sorted(reasons.items()):
        if reason not in (MISMATCH, NOT_FOUND, DUPLICATE):
            parts.append(f"{n} {reason.lower()}")
    text = ", ".join(parts)
    return text[0].upper() + text[1:] + "."


def _finish(card, extraction, validation, reconciliation, note, tone):
    card["stages"] = [extraction, validation, reconciliation]
    card["note"], card["note_tone"] = note, tone
    states = [s["state"] for s in card["stages"]]
    if "fail" in states:
        card["status"] = "failed"
    elif "run" in states:
        card["status"] = "running"
    elif "warn" in states:
        card["status"] = "review"
    else:
        card["status"] = "ok"
    card["failed"] = card["status"] == "failed"
    card["has_exceptions"] = reconciliation["state"] == "warn"
    return card


def intake_card(intake: dict, job: dict = None, recon: dict = None) -> dict:
    """A statement that got through extraction (it has an intake row)."""
    passed = intake.get("validation_status") == "matches"
    card = {
        "statement_id": intake.get("statement_id"), "job_id": (job or {}).get("job_id"),
        "vendor_name": intake.get("vendor_name"), "shop": intake.get("shop"),
        "source_file": intake.get("source_file"), "statement_period": intake.get("statement_period"),
        "printed_total": intake.get("statement_total_as_printed"),
        "difference": intake.get("validation_difference"), "method": intake.get("validation_method"),
        "validation_status": intake.get("validation_status"),
        "timestamp": intake.get("ingestion_timestamp"),
        "validation_passed": passed, "checked": True,
    }
    extraction = _stage("Extraction", "ok", "Done")
    validation = _stage("Validation", "ok", "Passed") if passed else _stage("Validation", "fail", "Failed")
    job_status = (job or {}).get("status")
    note, tone = "", None
    if recon is not None:
        n = recon.get("exceptions") or 0
        reconciliation = (_stage("Reconciliation", "warn", _plural(n, "exception")) if n
                          else _stage("Reconciliation", "ok", "Done"))
        if n:
            note, tone = reason_summary(recon.get("reasons")) or f"{_plural(n, 'exception')}.", "w"
    elif passed and job_status in ACTIVE_JOB:
        reconciliation = _stage("Reconciliation", "run", "Running")
        note, tone = "Reconciling against NetSuite.", "r"
    elif passed and job_status == "FAILED":
        reconciliation = _stage("Reconciliation", "fail", "Failed")
        note, tone = friendly_error(job.get("error_message")), "f"
    elif not passed:
        reconciliation = _stage("Reconciliation", "skip", "Not reached")
    else:
        reconciliation = _stage("Reconciliation", "skip", "Not run")
    if not passed:
        # A pre-gate statement could be reconciled despite failing
        # validation; the validation failure is still what needs a look.
        note = VALIDATION_NOTES.get(intake.get("validation_status"),
                                    f"Validation: {intake.get('validation_status')}.")
        tone = "f"
    return _finish(card, extraction, validation, reconciliation, note, tone)


def job_card(job: dict) -> dict:
    """A job with no intake row: extraction failed, or it hasn't finished."""
    status = job.get("status")
    card = {
        "statement_id": job.get("statement_id"), "job_id": job.get("job_id"),
        "vendor_name": job.get("vendor_name"), "shop": None, "source_file": job.get("pdf_filename"),
        "statement_period": None, "printed_total": None, "difference": None, "method": None,
        "validation_status": None, "timestamp": job.get("submitted_at"),
        "validation_passed": False, "checked": status == "FAILED",
    }
    if status == "FAILED":
        return _finish(card, _stage("Extraction", "fail", "Failed"), _stage("Validation", "skip", "Not reached"),
                       _stage("Reconciliation", "skip", "Not reached"),
                       friendly_error(job.get("error_message")) or "Extraction failed.", "f")
    label = "Running" if status == "PROCESSING" else "Queued"
    return _finish(card, _stage("Extraction", "run", label), _stage("Validation", "skip", "Not yet"),
                   _stage("Reconciliation", "skip", "Not yet"),
                   "Extracting the statement." if status == "PROCESSING" else "Waiting to be processed.", "r")


def _sort_key(card):
    return str(card.get("timestamp") or "").replace("T", " ")[:19]


_STATEMENT_IN_MESSAGE = re.compile(r"\(statement_id (STMT-[A-Za-z0-9-]+)\)")


def job_statement_id(job: dict):
    """The job's statement_id, or the one its failure message names: a job
    that failed after intake (the Silver check, or the validation gate's
    first version, 2026-10-15) can carry "(statement_id STMT-...)" in its
    error_message without the column set -- it belongs to that statement's
    card, not a card of its own."""
    if job.get("statement_id"):
        return job["statement_id"]
    found = _STATEMENT_IN_MESSAGE.search(str(job.get("error_message") or ""))
    return found.group(1) if found else None


def build_cards(intake_rows: list, jobs: list, recon: dict) -> list:
    """Every intake attempt, plus every failed / unfinished job that never
    produced an intake row; duplicate uploads (nothing new extracted) and
    completed jobs whose rows are gone are left out. Newest first."""
    latest_job = {}
    for job in jobs:  # newest first, so the first one per statement wins
        sid = job_statement_id(job)
        if sid and sid not in latest_job:
            latest_job[sid] = job
    cards = [intake_card(r, latest_job.get(r.get("statement_id")), recon.get(r.get("statement_id")))
             for r in intake_rows]
    have = {r.get("statement_id") for r in intake_rows}
    for job in jobs:
        if job_statement_id(job) in have or job.get("status") not in ("FAILED",) + ACTIVE_JOB:
            continue
        if str(job.get("error_message") or "").startswith("Duplicate of"):
            continue
        cards.append(job_card(job))
    cards.sort(key=_sort_key, reverse=True)
    return cards


def default_tab(card: dict) -> str:
    """The stage that needs attention: a failed one, else Reconciliation
    when it found exceptions, else Validation."""
    for stage in card["stages"]:
        if stage["state"] == "fail":
            return stage["name"].lower()
    if card["stages"][2]["state"] == "warn":
        return "reconciliation"
    return "validation"


def _num(v):
    return float(v) if v is not None else None


def line_results(lines: list, matched: list, exceptions: list) -> dict:
    """Each Silver line next to its invoice's reconciliation result.
    Matching works per invoice, so every line of one invoice shows that
    invoice's result; `shared` marks those lines. Also the summary tiles."""
    by_match = {}
    for m in matched:
        by_match.setdefault(m.get("invoice_number"), m)
    by_exc = {}
    for e in exceptions:
        by_exc.setdefault(e.get("invoice_number"), e)
    per_invoice = {}
    for line in lines:
        per_invoice[line.get("invoice_number")] = per_invoice.get(line.get("invoice_number"), 0) + 1

    rows = []
    for line in lines:
        inv = line.get("invoice_number")
        amount = _num(line.get("line_net_amount"))
        if amount is None:
            charge, payment = _num(line.get("charge_amount")), _num(line.get("payment_amount"))
            amount = None if charge is None and payment is None else (charge or 0) - (payment or 0)
        result, status, label = by_match.get(inv), "matched", "Matched"
        if result is None:
            result = by_exc.get(inv)
            reason = (result or {}).get("exception_reason")
            status = {MISMATCH: "mismatch", NOT_FOUND: "missing"}.get(reason, "other" if result else "none")
            label = {MISMATCH: "Amount mismatch", NOT_FOUND: "Not in NetSuite"}.get(
                reason, reason or "Not reconciled")
        stmt, ns = _num((result or {}).get("statement_amount")), _num((result or {}).get("erp_amount"))
        rows.append({
            "line_number": line.get("line_number"), "invoice_number": inv, "amount": amount,
            "netsuite_amount": ns, "difference": round(stmt - ns, 2) if stmt is not None and ns is not None else None,
            "status": status, "label": label,
            "shared": bool(inv) and per_invoice.get(inv, 0) > 1, "invoice_lines": per_invoice.get(inv, 0),
        })

    def total(items, fn):
        return round(sum(fn(i) or 0 for i in items), 2)
    mismatches = [e for e in exceptions if e.get("exception_reason") == MISMATCH]
    missing = [e for e in exceptions if e.get("exception_reason") == NOT_FOUND]
    other = [e for e in exceptions if e.get("exception_reason") not in (MISMATCH, NOT_FOUND)]
    tiles = {
        "matched": len(matched), "matched_amount": total(matched, lambda r: _num(r.get("statement_amount"))),
        "mismatch": len(mismatches),
        "mismatch_amount": total(mismatches, lambda r: abs((_num(r.get("statement_amount")) or 0)
                                                           - (_num(r.get("erp_amount")) or 0))),
        "missing": len(missing), "missing_amount": total(missing, lambda r: _num(r.get("statement_amount"))),
        "other": len(other), "invoices": len(matched) + len(exceptions),
    }
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("matched", "mismatch", "missing", "other", "none")}
    return {"rows": rows, "tiles": tiles, "counts": counts}
