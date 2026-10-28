"""
section_totals.py

Several account sections and no grand total (method "pdf_section_totals",
2026-10-26, Blaise Alexander STMT-B0E5C003 and Matthews Auto STMT-B0E5C004):
one scanned CDK statement printing two or four account statements one after
the other, each closing with its own NEW BALANCE / PAY THIS AMOUNT box, and
no total for the whole file. The extraction returns each section's name and
total (statement_metadata.section_totals) and the section of every row. Such
a statement is "total_not_found": on a scan the account-blocks check (text
layer only) does not apply, and the row-by-row PDF checks refuse it on the
OCR noise of a few rows. This runs only after the no-total rule, the
account-blocks check and full_match_no_total, so it can only add a pass.

It passes only if ALL of this holds:
  - two or more sections, each with a name and a total, names distinct;
  - every row (informational rows left out) belongs to exactly one of them,
    and every section has rows;
  - each section's rows, netted as the gate nets them (_row_net), equal that
    section's total to the cent, and the statement's charges - credits
    equals the sum of the section totals to the cent;
  - each section total is printed on the PDF as a labelled total, read from
    the PDF itself -- never taken from the extraction alone:
      (A) an amount on a total-labelled line of the PDF's text (its text
          layer, or OCR text for a scan), with printed_total's labels and
          rules (NEW BALANCE, PAY THIS AMOUNT, TOTAL DUE, BALANCE DUE,
          AMOUNT DUE, ...; never a prose line or a percentage);
      (B) the box under the label: a total-labelled line that prints no
          amount, and the next non-blank line is not labelled and prints
          exactly ONE non-zero amount ("OVER 90 DAYS  OVER 120 DAYS  NEW
          BALANCE  STATEMENT DATE" / "0.00  0.00  4623.41  25 SEP 2026");
      (C) full_match_no_total.total_like_amounts on the PDF's positioned
          lines (an amount on or directly under a positional total label, or
          in a bare BALANCE box), within the PDF checks' OCR budget;
    a total found in fewer places than the sections that print it refuses;
  - SAFETY: every amount found by (A), (B) or (C) is one of the section
    totals or their sum to the cent. Any other one -- a misread, an aging
    bucket read in place of the box, a total the extraction lacks --
    refuses, naming it.
Nothing is derived from the rows to fill a total: on a pass the result's
printed total is the SUM of the section totals (as pdf_account_blocks does;
the statement keeps no printed total of its own) and computed is charges -
credits. SECTION_TOTALS_CHECK_ENABLED=false switches it off (default on).
"""

import os
import re
from collections import Counter
from typing import Optional

METHOD = "pdf_section_totals"
ENV_FLAG = "SECTION_TOTALS_CHECK_ENABLED"
_CENT = 0.005


def enabled() -> bool:
    return os.getenv(ENV_FLAG, "true").strip().lower() != "false"


def _not_applicable(reason: str) -> dict:
    return {"applicable": False, "passed": False, "reason": reason}


def _name(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def text_totals(text: Optional[str]) -> list:
    """[{"line", "label", "amount", "read"}] read from the text by rules (A) and (B)."""
    from src.validation import printed_total as pt
    lines = (text or "").splitlines()
    found = []
    for k, line in enumerate(lines):
        if not pt._is_total_line(line) or pt._is_prose(line):
            continue
        same = pt._line_amounts(line, skip_percentages=True)
        if same:
            found += [{"line": k + 1, "label": line.strip()[:70], "amount": a, "read": "on the label's line"} for a in same]
            continue
        j = next((j for j in range(k + 1, len(lines)) if lines[j].strip()), None)
        if j is None or pt._is_total_line(lines[j]) or pt._is_prose(lines[j]):
            continue
        under = [v for v in pt._money_values(lines[j], skip_percentages=True) if v != 0]
        if len(under) == 1:
            found.append({"line": j + 1, "label": line.strip()[:70], "amount": under[0], "read": "the one amount on the line under the label"})
    return found


def check_section_totals(rows: list, section_totals, text: Optional[str], computed, pdf_path: Optional[str] = None) -> dict:
    """{"applicable", "passed", "reason", ...}; see the module docstring. rows: the statement's
    non-informational rows; section_totals: statement_metadata["section_totals"]; text: the text the gate's
    text checks read (text layer, or OCR text for a scan); computed: charges - credits."""
    from src.validation.arithmetic_gate import _row_net
    if not section_totals or len(section_totals) < 2:
        return _not_applicable("fewer than two account sections were extracted")
    if not rows:
        return _not_applicable("no rows")
    sections = {}
    for entry in section_totals:
        name, total = _name((entry or {}).get("section")), (entry or {}).get("subtotal")
        if not name or isinstance(total, bool) or not isinstance(total, (int, float)):
            return {"applicable": True, "passed": False, "reason": "an extracted section has no name or no total"}
        if name in sections:
            return {"applicable": True, "passed": False, "reason": f"section {name!r} is extracted twice"}
        sections[name] = round(float(total), 2)
    result = {"applicable": True, "passed": False, "reason": ""}
    members = {name: [] for name in sections}
    for position, inv in enumerate(rows, start=1):
        name = _name(inv.get("section"))
        if name not in members:
            result["reason"] = (f"row {position} ({inv.get('invoice_number')}) is in no extracted section" if not name
                                else f"row {position} is in section {name!r}, which has no total")
            return result
        members[name].append(inv)
    report = [{"section": name, "rows": len(members[name]), "rows_total": round(sum(_row_net(inv) for inv in members[name]), 2),
               "section_total": total} for name, total in sections.items()]
    result["sections"] = report
    for r in report:
        if not r["rows"]:
            result["reason"] = f"section {r['section']!r} has no rows"
            return result
        if abs(round(r["rows_total"] - r["section_total"], 2)) >= _CENT:
            result["reason"] = f"section {r['section']!r}: its rows total {r['rows_total']:,.2f}, its total {r['section_total']:,.2f}"
            return result
    grand = round(sum(sections.values()), 2)
    if computed is None or abs(round(computed - grand, 2)) >= _CENT:
        result["reason"] = f"charges - credits {computed} is not the sum of the section totals {grand:,.2f}"
        return result

    # Where the PDF itself prints each total.
    from src.validation import full_match_no_total as fm
    from src.validation import pdf_row_match as prm
    from_text = text_totals(text)
    positional = []
    if pdf_path:
        try:
            positional = [dict(f, read="positioned: " + f["read"])
                          for f in fm.total_like_amounts(prm.read_pdf_lines(pdf_path), None, pdf_path)]
        except prm.NotVerified as e:
            result["positional_read"] = f"not verified: {e}"
        except Exception as e:   # an unreadable PDF: the text alone has to show every total
            result["positional_read"] = f"PDF unreadable ({type(e).__name__})"
    found = [f for f in from_text + positional if abs(f["amount"]) >= _CENT]
    result["printed_totals_found"] = found
    allowed = list(sections.values()) + [grand]
    stray = [f for f in found if not any(abs(round(f["amount"] - v, 2)) < _CENT for v in allowed)]
    if stray:
        f = stray[0]
        where = f"line {f['line']}" if "line" in f else f"page {f.get('page')}"
        result["reason"] = (f"the PDF prints {f['amount']:,.2f} as a total ({where}: {f['label']!r}, {f['read']}), "
                            f"neither a section total nor their sum {grand:,.2f}"
                            + (f" ({len(stray)} such amounts)" if len(stray) > 1 else ""))
        return result
    needed = Counter(sections.values())
    for name, total in sections.items():
        places = max(sum(1 for f in from_text if abs(round(f["amount"] - total, 2)) < _CENT),
                     sum(1 for f in positional if abs(round(f["amount"] - total, 2)) < _CENT))
        if places < needed[total]:
            result["reason"] = f"section {name!r}: its total {total:,.2f} is not found as a labelled total on the PDF"
            return result
    result.update(passed=True, printed_total=grand, computed=round(computed, 2),
                  printed_total_is="the sum of the account sections' totals, each found as a labelled total on the PDF")
    return result
