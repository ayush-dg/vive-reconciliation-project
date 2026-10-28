"""
account_blocks.py

The gate's "pdf_account_blocks" check (2026-10-20, Lithia STMT-142DA134):
one TEXT-LAYER PDF that holds two or more complete account statements, each
printing its own "Total Amount Due" and its own transaction table, and no
single total for the whole file. Such a statement is "total_not_found", and
the no-total rule (pdf_rows_no_total) refuses it because the PDF does print
totals. It runs only after that rule, so it can only add a pass.

A block starts on a page that prints "Total Amount Due" or "Page 1 of N";
a page printing "Page k of N" (k > 1) continues the block of page k-1 and
must repeat the same Total Amount Due if it prints one. Any other page
(Lithia's terms pages) belongs to no block. It passes only if ALL hold:
  - every page has a text layer (a scan is not applicable), at most
    the PDF checks' page cap (pdf_row_match.max_pages()), and two or more blocks;
  - every block prints its Total Amount Due, read from the PDF's own words:
    the one amount printed directly under the label, or after it on the
    same line;
  - every extracted row matches exactly one printed transaction line and
    every printed transaction line exactly one row (reference + date +
    amount + sign, pdf_row_match._check_row); any ambiguity fails;
  - every matched line is printed on a page of a block, every block has
    rows, and each block's rows summed with their printed signs equal its
    own printed Total Amount Due to the cent;
  - the statement's charges - credits equals the sum of the blocks' printed
    totals to the cent. That sum is the result's printed total (recorded as
    such; the statement keeps no single printed total of its own).

A line printing only its block's Total Amount Due under an "Amount Due"
label within the three lines above it (the remittance stub) restates that
total and is not a transaction; it is recorded under "restated_totals".

Columns are read as pdf_row_match reads them, except that a header naming a
purchase/charge and "payment" is one signed amount column (the client's
is_signed_amount_header, "Purchase/Payments Amount"); that wider reading is
used by this check only, so every other PDF check reads PDFs as before.
"""

import re
import time

from src.validation import pdf_row_match as prm

METHOD = "pdf_account_blocks"
TOTAL_LABEL = ("total", "amount", "due")
STUB_LABEL = ("amount", "due")
_PAGE_MARKER_RE = re.compile(r"\bpage\s+(\d{1,3})\s+of\s+(\d{1,3})\b", re.IGNORECASE)
_STUB_LOOKBACK = 3


def _classify(phrase: str) -> str:
    from src.ai.claude_sonnet_client import is_signed_amount_header
    h = re.sub(r"\s+", " ", phrase.lower().strip().replace("_", " "))
    if is_signed_amount_header(h):
        return "signed"
    return prm.classify_header(phrase)


def _word(w) -> str:
    return w["text"].strip().rstrip(":.").lower()


def _label_runs(line, label):
    """[(x0, x1, index of the label's last word)] of each run of words spelling `label`."""
    words = line["words"]
    out = []
    for k in range(len(words) - len(label) + 1):
        if all(_word(words[k + j]) == label[j] for j in range(len(label))):
            out.append((words[k]["x0"], words[k + len(label) - 1]["x1"], k + len(label) - 1))
    return out


def _money_words(line):
    return [w for w in line["words"] if prm.parse_money(w["text"]) is not None]


def _under(word, x0, x1):
    return word["x1"] > x0 - 2 and word["x0"] < x1 + 2


def _total_amount_due(lines):
    """(value, where, problem) for one page. value None and problem None: the
    page prints no "Total Amount Due" label. The value is the one amount on
    the label's line after it, else the one amount directly under the label
    on the next line; two labels must agree."""
    found = []
    for i, line in enumerate(lines):
        for x0, x1, last in _label_runs(line, TOTAL_LABEL):
            after = [w for w in line["words"][last + 1:] if prm.parse_money(w["text"]) is not None]
            if after:
                if len(after) != 1:
                    return None, None, f"{len(after)} amounts after \"Total Amount Due\" on one line"
                found.append((prm.parse_money(after[0]["text"]), "after \"Total Amount Due\" on its line"))
                continue
            below = lines[i + 1] if i + 1 < len(lines) else None
            if below is None or below["top"] - line["bottom"] > 2.5 * line["height"]:
                return None, None, "no amount printed under \"Total Amount Due\""
            values = [w for w in _money_words(below) if _under(w, x0, x1)]
            if len(values) != 1:
                return None, None, (f"{len(values)} amounts printed under \"Total Amount Due\"" if values
                                    else "no amount printed under \"Total Amount Due\"")
            found.append((prm.parse_money(values[0]["text"]), f"printed under \"Total Amount Due\" ({values[0]['text']})"))
    if not found:
        return None, None, None
    if any(abs(v - found[0][0]) >= prm._CENT for v, _ in found):
        return None, None, "two different amounts under \"Total Amount Due\" on one page"
    return found[0][0], found[0][1], None


def _page_marker(lines):
    for line in lines:
        m = _PAGE_MARKER_RE.search(line["text"])
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def find_blocks(pages):
    """(blocks, page_block, problems). blocks: [{"first_page", "pages",
    "total", "total_read", "marker"}]; page_block: {page number: block
    index}; problems: why the block structure itself fails."""
    blocks, page_block, problems = [], {}, []
    open_block = None
    for page in pages:
        number = page["page"]
        value, where, problem = _total_amount_due(page["lines"])
        labelled = value is not None or problem is not None
        marker = _page_marker(page["lines"])
        if problem:
            problems.append(f"page {number}: {problem}")
        if marker and marker[0] > 1:
            if not (open_block and open_block["marker"] and open_block["marker"][1] == marker[1]
                    and open_block["marker"][0] == marker[0] - 1):
                problems.append(f"page {number} prints \"page {marker[0]} of {marker[1]}\" but continues no block")
                open_block = None
                continue
            if value is not None and open_block["total"] is not None and abs(value - open_block["total"]) >= prm._CENT:
                problems.append(f"page {number} prints Total Amount Due {value:,.2f}, its block "
                                f"{open_block['total']:,.2f}")
            open_block["pages"].append(number)
            open_block["marker"] = marker
            page_block[number] = len(blocks) - 1
            continue
        if labelled or (marker and marker[0] == 1):
            open_block = {"first_page": number, "pages": [number], "total": value, "total_read": where,
                          "marker": marker}
            blocks.append(open_block)
            page_block[number] = len(blocks) - 1
            if not labelled:
                problems.append(f"the account block starting on page {number} prints no Total Amount Due")
            continue
        open_block = None  # a page with neither belongs to no block and ends the open one
    for b in blocks:
        if b["marker"] and b["marker"][0] != b["marker"][1]:
            problems.append(f"the account block starting on page {b['first_page']} ends on "
                            f"\"page {b['marker'][0]} of {b['marker'][1]}\"")
    return blocks, page_block, problems


def _restated_total(line, table, block):
    """True when the line prints only its block's Total Amount Due, under an
    "Amount Due" label within the _STUB_LOOKBACK lines above it."""
    money = [m for m in line["money"] if abs(m["value"]) > prm._CENT]
    if len(money) != 1 or block["total"] is None or abs(money[0]["value"] - block["total"]) >= prm._CENT:
        return False
    word = money[0]["word"]
    k = table.index(line)
    for above in table[max(0, k - _STUB_LOOKBACK):k][::-1]:
        if above["page"] != line["page"] or above["money"]:
            continue
        if any(_under(word, x0, x1) for x0, x1, _ in _label_runs(above, STUB_LABEL)):
            return True
    return False


def _block_name(table, block):
    """The text of the block's section line (the block's total printed after
    a name, below the column header, not a transaction), else None."""
    for line in table:
        if (line["page"] != block["first_page"] or not line["in_region"] or line["is_transaction"]
                or line.get("restated_total") or line["dates"]):
            continue
        money = [m for m in line["money"] if abs(m["value"]) > prm._CENT]
        if len(money) == 1 and abs(money[0]["value"] - block["total"]) < prm._CENT:
            name = " ".join(w["text"] for w in line["words"] if w is not money[0]["word"]).strip()
            if re.search(r"[A-Za-z]", name) and not prm._is_label_line(name):
                return name
    return None


def _pages_label(pages):
    return str(pages[0]) if len(pages) == 1 else f"{pages[0]}-{pages[-1]}"


def _fail(result, reason, started):
    result.update(passed=False, reason=reason, seconds=round(time.monotonic() - started, 2))
    return result


def check_pdf_account_blocks(rows, pdf_path, computed):
    """{"applicable", "passed", "reason", ...}; see the module docstring.
    rows: the statement's non-informational rows; computed: its charges -
    credits (statement_total_computed)."""
    started = time.monotonic()
    if not pdf_path or not rows:
        return prm._not_applicable("no PDF" if not pdf_path else "no rows")
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            if len(pdf.pages) > prm.max_pages():
                return prm._not_applicable(f"{len(pdf.pages)} pages (cap {prm.max_pages()})")
            scans = [i + 1 for i, page in enumerate(pdf.pages)
                     if len(prm._text_layer_words(page)) < prm.MIN_TEXT_WORDS]
    except Exception as e:
        return prm._not_applicable(f"PDF unreadable ({type(e).__name__})")
    if scans:
        return prm._not_applicable(f"not a text-layer PDF (page {scans[0]} has no text layer)")
    try:
        pages = prm.read_pdf_lines(pdf_path)
    except prm.NotVerified as e:
        return prm._not_applicable(f"not verified: {e}")
    blocks, page_block, problems = find_blocks(pages)
    if len(blocks) < 2 or not any(b["total"] is not None for b in blocks):
        return prm._not_applicable(f"the PDF prints {len(blocks)} account block(s) with a Total Amount Due"
                                   if len(blocks) < 2 else "no account block prints a Total Amount Due")
    result = {"applicable": True, "passed": False, "computed": None, "text_source": "text_layer",
              "pages": len(pages), "rows": len(rows)}
    if problems:
        return _fail(result, "; ".join(problems), started)

    headed = {p["page"] for p in pages if prm._find_header(p["lines"], _classify)[1]}
    unheaded = [b["first_page"] for b in blocks if not headed & set(b["pages"])]
    if unheaded:
        return _fail(result, f"the account block starting on page {unheaded[0]} prints no transaction table header",
                     started)
    table = prm.build_table(pages, classify=_classify)
    restated = []
    for line in table:
        block = blocks[page_block[line["page"]]] if line["page"] in page_block else None
        if line["is_transaction"] and block is not None and _restated_total(line, table, block):
            line["is_transaction"] = False
            line["restated_total"] = True
            restated.append({"page": line["page"], "amount": block["total"], "text": line["text"][:80]})
    result["restated_totals"] = restated
    lines = [line for line in table if line["is_transaction"] and line["in_region"]]
    result["pdf_transaction_lines"] = len(lines)

    # One to one: each row against every printed transaction line.
    issues, matched_rows, line_rows = [], [], {}
    for position, inv in enumerate(rows, start=1):
        label = f"row {position} ({inv.get('invoice_number')} {inv.get('invoice_date')})"
        invoice_norm = prm.norm_invoice(inv.get("invoice_number"))
        want_date = prm.parse_date(inv.get("invoice_date"))
        candidates = [l for l in lines if (prm._invoice_on_line(invoice_norm, l) if invoice_norm
                                           else want_date is not None and want_date in l["dates"])]
        hits = [l for l in candidates if prm._check_row(inv, l) is None]
        if not hits:
            why = prm._check_row(inv, candidates[0]) if candidates else "no printed transaction line with its reference"
            issues.append(f"{label}: {why}")
            continue
        if len(hits) > 1:
            issues.append(f"{label}: matches {len(hits)} printed lines "
                          f"({', '.join('p%d' % l['page'] for l in hits)}) -- ambiguous")
            continue
        prm._check_row(inv, hits[0])  # leaves the matched printed amounts on the line
        matched_rows.append((inv, hits[0]))
        line_rows.setdefault(id(hits[0]), []).append(position)
    for line in lines:
        n = len(line_rows.get(id(line), []))
        if n == 0:
            issues.append(f"printed line not extracted (p{line['page']}): {line['text'][:80]}")
        elif n > 1:
            issues.append(f"printed line p{line['page']} matched by {n} rows: {line['text'][:60]}")
    result["rows_verified"] = len(matched_rows)
    if issues:
        result["problems"] = issues[:10]
        return _fail(result, f"{len(issues)} row/line problem(s): " + "; ".join(issues[:3]), started)

    # Every row in exactly one block; each block's rows equal its own printed total.
    per_block = [[] for _ in blocks]
    for inv, line in matched_rows:
        if line["page"] not in page_block:
            issues.append(f"{inv.get('invoice_number')} is printed on page {line['page']}, in no account block")
            continue
        per_block[page_block[line["page"]]].append((inv, line))
    recorded = []
    for b, members in zip(blocks, per_block):
        printed_sum = round(sum(prm._printed_net(line) for _, line in members), 2)
        rows_sum = round(sum(a for inv, _ in members for a, _k in prm._row_amounts(inv)), 2)
        entry = {"name": _block_name(table, b) or f"account on page {b['first_page']}",
                 "pages": _pages_label(b["pages"]), "printed_total_amount_due": b["total"],
                 "total_read_from": f"page {b['first_page']}, {b['total_read']}", "rows": len(members),
                 "rows_signed_sum": rows_sum}
        recorded.append(entry)
        if not members:
            issues.append(f"the account block on page {entry['pages']} has no extracted rows")
        elif abs(printed_sum - rows_sum) >= prm._CENT:
            issues.append(f"block {entry['name']}: printed lines sum to {printed_sum:,.2f}, rows to {rows_sum:,.2f}")
        elif abs(rows_sum - b["total"]) >= prm._CENT:
            issues.append(f"block {entry['name']} (pages {entry['pages']}): rows sum to {rows_sum:,.2f}, "
                          f"printed Total Amount Due {b['total']:,.2f}")
    result["blocks"] = recorded
    if issues:
        return _fail(result, "; ".join(issues), started)
    printed_total = round(sum(b["total"] for b in blocks), 2)
    result["printed_total"] = printed_total
    result["printed_total_is"] = "the sum of the account blocks' printed Total Amount Due"
    if computed is None or abs(round(computed - printed_total, 2)) >= prm._CENT:
        return _fail(result, f"charges - credits {computed} is not the blocks' printed total {printed_total:,.2f}",
                     started)
    result.update(passed=True, computed=printed_total, reason="", seconds=round(time.monotonic() - started, 2))
    return result
