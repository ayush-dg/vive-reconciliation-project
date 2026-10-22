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
from collections import Counter

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
        # recon["resolved"] (2026-10-22, from the recon table): exceptions a
        # reviewer already accepted/rejected -- then "exceptions" and
        # "reasons" are the OPEN ones only, and the card says both.
        n, resolved = recon.get("exceptions") or 0, recon.get("resolved") or 0
        done = f"{resolved} resolved"
        if n:
            label = f"{n} open · {done}" if resolved else _plural(n, "exception")
            reconciliation = _stage("Reconciliation", "warn", label)
            note = reason_summary(recon.get("reasons")) or f"{_plural(n, 'exception')}."
            if resolved:
                note = f"{note[:-1]} ({done})." if note.endswith(".") else f"{note} ({done})"
            tone = "w"
        else:
            reconciliation = _stage("Reconciliation", "ok", f"Done · {done}" if resolved else "Done")
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


def _line_amount(line: dict):
    """A Silver line's own amount: line_net_amount, else charge - payment."""
    amount = _num(line.get("line_net_amount"))
    if amount is None:
        charge, payment = _num(line.get("charge_amount")), _num(line.get("payment_amount"))
        amount = None if charge is None and payment is None else (charge or 0) - (payment or 0)
    return amount


def _same_invoice(line_inv, result_inv, exact_only=False) -> bool:
    """A result belongs to a line's invoice: the same number, or (unless
    exact_only) the matcher's '-N' ordinal form of it (Nucar CM6303960 ->
    CM6303960-1)."""
    if not line_inv or not result_inv:
        return False
    a, b = str(line_inv).lower(), str(result_inv).lower()
    return a == b or (not exact_only and b.startswith(a + "-"))


# recon table status -> (filter group, label) for the Reconciliation tab.
_RECON_GROUPS = {
    "Matched": ("matched", "Matched"),
    "Matched manually": ("matched", "Matched manually"),
    "Amount mismatch": ("mismatch", "Amount mismatch"),
    "Not found in NetSuite": ("missing", "Not in NetSuite"),
    "Accepted": ("resolved", "Accepted"),
    "Rejected": ("resolved", "Rejected"),
}
_REASON_LABEL = {MISMATCH: "amount mismatch", NOT_FOUND: "not in NetSuite"}


def recon_view(recon_rows: list) -> dict:
    """The Reconciliation tab from the recon table ONLY (2026-10-22): one
    active row per statement line with its CURRENT status -- so a manual
    Accept / Reject / Accept-as-match shows on the line, the tiles, the
    filters and the header at once, and they can't disagree. Exceptions are
    counted once each (by exception id) in the tiles and header, as on the
    Exceptions page; the filters count lines. Same shape as line_results()."""
    rows, open_ids, resolved_ids = [], {}, set()
    for r in recon_rows:
        status = r.get("status") or ""
        group, label = _RECON_GROUPS.get(status, (None, status))
        if group is None:
            group = "set_aside" if status == "Not reconciled" and r.get("note") else (
                "none" if status in ("", "Not reconciled") else "other")
            label = "Set aside" if group == "set_aside" else (label or "Not reconciled")
        if group == "resolved":
            was = _REASON_LABEL.get(r.get("exception_reason"), (r.get("exception_reason") or "").lower())
            label = f"{label}{' (was ' + was + ')' if was else ''}"
            if r.get("exception_id"):
                resolved_ids.add(r["exception_id"])
        elif group in ("mismatch", "missing", "other") and r.get("exception_id"):
            open_ids.setdefault(r["exception_id"], (group, r))
        if status == "Matched manually" and r.get("netsuite_tranid"):
            label = f"Matched manually to {r['netsuite_tranid']}"
        who = r.get("matched_by") if r.get("source") == "manual" or group == "resolved" else None
        rows.append({
            "line_number": r.get("line_number"), "invoice_number": r.get("invoice_number"),
            "amount": _num(r.get("line_amount")), "netsuite_amount": _num(r.get("netsuite_amount")),
            "difference": _num(r.get("difference")), "status": group, "label": label,
            "note": r.get("note") if group in ("set_aside", "resolved") or r.get("source") == "manual" else None,
            "by": who, "at": str(r.get("matched_at") or "")[:10] if who else None,
            "shared": False, "invoice_lines": 1,
        })
    rows.sort(key=lambda x: (x["line_number"] is None, x["line_number"] or 0))

    def open_of(group):
        return [r for g, r in open_ids.values() if g == group]
    matched = [r for r in rows if r["status"] == "matched"]
    checked = [r for r in rows if r["status"] not in ("set_aside", "none")]
    mismatches, missing, other = open_of("mismatch"), open_of("missing"), open_of("other")
    tiles = {
        "matched": len(matched), "matched_amount": round(sum(abs(r["amount"] or 0) for r in matched), 2),
        "mismatch": len(mismatches),
        "mismatch_amount": round(sum(abs(_num(r.get("difference")) or 0) for r in mismatches), 2),
        "missing": len(missing), "missing_amount": round(sum(abs(_num(r.get("line_amount")) or 0) for r in missing), 2),
        "other": len(other), "invoices": len(checked),
        "open": len(open_ids), "resolved": len(resolved_ids),
    }
    counts = {s: sum(1 for r in rows if r["status"] == s)
              for s in ("matched", "mismatch", "missing", "other", "resolved", "set_aside", "none")}
    reasons = Counter({"mismatch": MISMATCH, "missing": NOT_FOUND}.get(g, "Other") for g, _ in open_ids.values())
    return {"rows": rows, "tiles": tiles, "counts": counts, "source": "recon",
            "open_reasons": dict(reasons)}


def line_results(lines: list, matched: list, exceptions: list, set_aside: dict = None) -> dict:
    """Each Silver line next to ITS OWN reconciliation result (2026-10-21).
    Matching decides line by line, so each match/exception row belongs to the
    line on that invoice with the same amount -- paired here first, so an
    invoice whose charge matched and whose payment line did not shows one
    Matched line and one exception line, never both as Matched (Gates GMC,
    Nucar). Only a line no row pairs with falls back to its invoice's result
    (`shared`: a vendor matched per invoice), or to "Set aside" when matching
    set it aside (`set_aside`: {line_number: note}, from the recon table).
    Also the summary tiles."""
    set_aside = set_aside or {}
    results = [("match", m) for m in matched] + [("exception", e) for e in exceptions]
    used = set()
    own = {}
    # Exact invoice number first, the '-N' form only for lines still unpaired
    # -- else '563967E' takes '563967E-1''s result (Quirk, 2026-10-22).
    for exact_only in (True, False):
        for idx, line in enumerate(lines):
            amount = _line_amount(line)
            if amount is None or idx in own:
                continue
            for rid, (kind, result) in enumerate(results):
                stmt = _num(result.get("statement_amount"))
                if (rid not in used and stmt is not None and abs(abs(stmt) - abs(amount)) < 0.005
                        and _same_invoice(line.get("invoice_number"), result.get("invoice_number"), exact_only)):
                    used.add(rid)
                    own[idx] = (kind, result)
                    break

    by_match, by_exc = {}, {}
    for m in matched:
        by_match.setdefault(m.get("invoice_number"), m)
    for e in exceptions:
        by_exc.setdefault(e.get("invoice_number"), e)
    per_invoice = {}
    for line in lines:
        per_invoice[line.get("invoice_number")] = per_invoice.get(line.get("invoice_number"), 0) + 1

    rows = []
    for idx, line in enumerate(lines):
        inv = line.get("invoice_number")
        amount = _line_amount(line)
        shared = False
        if idx in own:
            kind, result = own[idx]
        elif line.get("line_number") in set_aside:
            kind, result = "set_aside", None
        elif inv in by_exc:
            kind, result, shared = "exception", by_exc[inv], True
        elif inv in by_match:
            kind, result, shared = "match", by_match[inv], True
        else:
            kind, result = None, None
        if kind == "match":
            status, label = "matched", "Matched"
        elif kind == "exception":
            reason = result.get("exception_reason")
            status = {MISMATCH: "mismatch", NOT_FOUND: "missing"}.get(reason, "other")
            label = {MISMATCH: "Amount mismatch", NOT_FOUND: "Not in NetSuite"}.get(reason, reason or "Exception")
        elif kind == "set_aside":
            status, label = "set_aside", "Set aside"
        else:
            status, label = "none", "Not reconciled"
        stmt, ns = _num((result or {}).get("statement_amount")), _num((result or {}).get("erp_amount"))
        rows.append({
            "line_number": line.get("line_number"), "invoice_number": inv, "amount": amount,
            "netsuite_amount": ns, "difference": round(stmt - ns, 2) if stmt is not None and ns is not None else None,
            "status": status, "label": label, "note": set_aside.get(line.get("line_number")),
            "shared": shared and bool(inv) and per_invoice.get(inv, 0) > 1, "invoice_lines": per_invoice.get(inv, 0),
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
    counts = {s: sum(1 for r in rows if r["status"] == s)
              for s in ("matched", "mismatch", "missing", "other", "set_aside", "none")}
    return {"rows": rows, "tiles": tiles, "counts": counts}
