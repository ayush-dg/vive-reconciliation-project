"""
full_match_no_total.py

pdf_full_match for a statement with no printed total (method "pdf_full_match_no_total", 2026-10-22,
user decision): when every extracted row and every cell matches the PDF one to one -- exactly the
pdf_full_match standard (pdf_row_match.check_pdf_full_match, run unchanged) -- a statement whose
status is still "total_not_found" after the no-total rule (pdf_rows_no_total) and the account-blocks
check (pdf_account_blocks) may pass too, as long as nothing the PDF prints contradicts the rows.

It passes only if ALL of this holds:
  - the statement has rows (informational rows left out) and a PDF; the same page cap and OCR time
    budget as pdf_full_match (pdf_row_match.max_pages(), ocr_time_budget_seconds()); over the cap / budget, unreadable, or a page from which no printed
    transaction line could be read = not verified, never a pass;
  - check_pdf_full_match passes: every row matches exactly one printed line and every printed
    transaction line exactly one row; every printed column is in the extraction; every cell (amounts
    to the cent with sign, dates, references, text) in its own column; no unused printed word;
  - the matched lines' printed amounts add up to the rows' charges - credits to the cent;
  - SAFETY: every total-like amount the PDF prints and the readers can read -- on a total-labelled
    text line (printed_total's labels: total due, balance due, amount due, total amount due, new
    balance, pay this amount, ...), or on the label's own line / directly under it on the PDF's
    positioned lines (total amount due, total due, balance due, amount due, new balance, pay this
    amount, please pay, net due, and bare BALANCE boxes, with the same box-not-column rule and the
    same one focused re-read on a scan as find_box_total) -- equals the rows' charges - credits to
    the cent. One amount that differs refuses, naming label, page and amount; none printed is fine;
  - the PDF does not print two or more account blocks with their own totals (account_blocks).
Nothing is derived from the rows to fill a total: on a pass the result's printed total and difference
stay None (exactly like pdf_rows_no_total) and computed is the rows' charges - credits.

FULL_MATCH_NO_TOTAL_ENABLED=false switches it off (default on).
"""

import os
import time
from typing import Optional

METHOD = "pdf_full_match_no_total"
ENV_FLAG = "FULL_MATCH_NO_TOTAL_ENABLED"
_CENT = 0.005
# Multi-word total labels read positionally (longest first, so "total amount due" is not also read as
# "amount due"); a bare "balance" / "net due" box is read with printed_total's own box rules.
POSITIONAL_LABELS = (("total", "amount", "due"), ("pay", "this", "amount"), ("total", "due"), ("balance", "due"),
                     ("amount", "due"), ("new", "balance"), ("please", "pay"))
_BELOW_HEIGHTS = 4.0


def enabled() -> bool:
    return os.getenv(ENV_FLAG, "true").strip().lower() != "false"


def _not_applicable(reason: str) -> dict:
    return {"applicable": False, "passed": False, "reason": reason}


def _key(word) -> str:
    return word["text"].strip().rstrip(":.").lower()


def _label_runs(words, labels):
    """[(label, first index, last index)] -- each word belongs to at most one (the longest) label."""
    taken, runs = set(), []
    for label in labels:
        for k in range(len(words) - len(label) + 1):
            span = range(k, k + len(label))
            if any(i in taken for i in span) or [_key(words[i]) for i in span] != list(label):
                continue
            taken.update(span)
            runs.append((" ".join(label).upper(), k, k + len(label) - 1))
    return runs


def total_like_amounts(pages: list, text: Optional[str], pdf_path: Optional[str]) -> list:
    """Every non-zero total-like amount the PDF prints that the readers can read:
    [{"page", "label", "amount", "read"}]. page None = read from the text's total-labelled lines."""
    from src.validation import pdf_row_match as prm
    from src.validation import printed_total as pt
    found = []
    for line in (text or "").splitlines():
        if pt._is_total_line(line):
            for amount in pt._line_amounts(line):
                found.append({"page": None, "label": line.strip()[:70], "amount": amount, "read": "on the label's line"})
    rereader = None
    for page in pages:
        lines = page["lines"]
        for i, line in enumerate(lines):
            words = sorted(line["words"], key=lambda w: w["x0"])
            height = max(line["bottom"] - line["top"], 1.0)
            for label, first, last in _label_runs(words, POSITIONAL_LABELS):
                x0, x1 = words[first]["x0"], words[last]["x1"]
                where = {"page": page["page"], "label": label}
                after = [w for w in words[last + 1:] if prm.parse_money(w["text"]) is not None]
                if after and after[0]["x0"] - x1 < 3 * height:
                    found.append({**where, "amount": prm.parse_money(after[0]["text"]), "read": "on the label's line"})
                    continue
                j, hits = pt._money_under(lines, i, x0, x1, line["bottom"] + _BELOW_HEIGHTS * height)
                if not hits:
                    continue
                _, again = pt._money_under(lines, j, x0, x1, lines[j]["bottom"] + _BELOW_HEIGHTS * height)
                if again:
                    continue  # a column of amounts under a table header, not a total
                for w in hits:
                    found.append({**where, "amount": prm.parse_money(w["text"]), "read": "printed under the label"})
            # Bare BALANCE / NET DUE boxes: printed_total's own stand-alone and box rules.
            for label, x0, x1, top, bottom, value_word in pt._bare_labels(line):
                where = {"page": page["page"], "label": label}
                box_height = max(bottom - top, 1.0)
                if value_word is not None:
                    found.append({**where, "amount": prm.parse_money(value_word["text"]), "read": "on the label's line"})
                    continue
                j, hits = pt._money_under(lines, i, x0, x1, bottom + pt._BOX_BELOW_HEIGHTS * box_height)
                if hits:
                    _, again = pt._money_under(lines, j, x0, x1, lines[j]["bottom"] + pt._BOX_BELOW_HEIGHTS * box_height)
                    if not again:
                        for w in hits:
                            found.append({**where, "amount": prm.parse_money(w["text"]), "read": "printed under the label"})
                    continue
                if page["source"] != "ocr" or page.get("rotation") or not pdf_path:
                    continue
                rereader = rereader or prm._Rereader(pdf_path, time.monotonic() + prm.ocr_time_budget_seconds())
                width = x1 - x0
                got = rereader._ocr(page["page"], (x0 - width, bottom + 1, x1 + 1.75 * width, bottom + 2.6 * box_height),
                                    "0123456789.,$-", 7) or []
                if len(got) == 1 and prm.parse_money(got[0]["text"]) is not None:
                    found.append({**where, "amount": prm.parse_money(got[0]["text"]), "read": "re-read under the label"})
    return [f for f in found if f["amount"] is not None and abs(f["amount"]) >= _CENT]


def check_full_match_no_total(rows: list, pdf_path: Optional[str], computed, text: Optional[str] = None) -> dict:
    """{"applicable", "passed", "reason", ...}; see the module docstring. rows: the statement's
    non-informational rows; computed: their charges - credits; text: the text the gate's text checks
    read (text layer, or OCR text for a scan)."""
    from src.validation import account_blocks
    from src.validation import pdf_row_match as prm
    if not pdf_path:
        return _not_applicable("no PDF")
    if not rows:
        return _not_applicable("no rows")
    if computed is None:
        return _not_applicable("no charges - credits computed")
    outcome = prm.check_pdf_full_match(None, rows, pdf_path=pdf_path)
    result = {"applicable": outcome.get("applicable", True), "passed": False, "reason": outcome.get("reason") or "",
              "full_match": {k: outcome.get(k) for k in ("text_source", "pages", "rows", "rows_verified",
                                                          "pdf_transaction_lines", "problem_counts", "offending_rows",
                                                          "columns", "unlabelled_columns", "ocr_rereads")
                             if outcome.get(k) is not None}}
    if not outcome.get("applicable", True):
        return result
    if not outcome.get("passed"):
        if outcome.get("pdf_transaction_lines") == 0 and "not verified" not in result["reason"]:
            result["reason"] = "not verified: no printed transaction line could be read from the PDF"
        return result
    printed_rows = outcome.get("computed")
    if printed_rows is None or abs(round(printed_rows - computed, 2)) >= _CENT:
        result["reason"] = f"the matched lines' printed amounts add up to {printed_rows}, the rows' charges - credits to {computed:,.2f}"
        return result
    try:
        pages = prm.read_pdf_lines(pdf_path)   # cached: the same read check_pdf_full_match just used
    except prm.NotVerified as e:
        result["reason"] = f"not verified: {e}"
        return result
    blocks, _, _ = account_blocks.find_blocks(pages)
    labelled = [b for b in blocks if b["total"] is not None]
    if len(labelled) >= 2:
        result["reason"] = (f"the PDF prints {len(labelled)} account blocks with their own Total Amount Due "
                            "(" + ", ".join(f"p{b['first_page']} {b['total']:,.2f}" for b in labelled) + ") -- account-blocks territory")
        return result
    amounts = total_like_amounts(pages, text, pdf_path)
    differing = [a for a in amounts if abs(round(a["amount"] - computed, 2)) >= _CENT]
    result["safety"] = {"total_like_amounts": amounts, "computed": round(computed, 2),
                        "result": "none printed" if not amounts else
                        ("every printed total-like amount equals the rows" if not differing else "a printed amount differs")}
    if differing:
        a = differing[0]
        result["reason"] = (f"the PDF prints {a['label']} {a['amount']:,.2f}"
                            f"{'' if a['page'] is None else ' on page ' + str(a['page'])}, not the rows' charges - credits "
                            f"{computed:,.2f}" + (f" ({len(differing)} differing amounts)" if len(differing) > 1 else ""))
        return result
    result.update(passed=True, reason="", computed=round(computed, 2))
    return result
