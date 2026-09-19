"""Vendor-specific line selection/dedup for statements whose raw extraction
contains duplicate or reprint rows that don't represent separate real
transactions -- Fred Beans and Downeast Toyota, confirmed live against
real NetSuite data (2026-09-18).

This is matching logic, NOT a Silver transformation -- deliberately kept
out of the dbt Silver models (see dbt/vive_recon/models/silver_silver/).
Fred Beans/Downeast need zero field-level Silver work (no invoice
normalization rule for either); what they need is deciding which raw
Silver lines correspond to which real NetSuite transaction before shape-
based matching runs, which is a matching-time concern, not a Silver-build
concern. Config-driven via silver.vendor_line_selection_rule -- no
vendor-name branches here; a vendor with no row in that table passes
through select_lines() completely unchanged.

Two confirmed quirks handled, both from real recon queries traced against
live NetSuite data:

1. Classification isn't reliable from which mapped column (charge_amount/
   payment_amount) a value landed in -- confirmed as a known Fred Beans
   extraction bug: the same invoice+amount can land in raw_charges on one
   statement row and raw_credits on another (e.g. 91488007X1's $15.34
   appeared in Credits on one date, Charges on two others -- one real
   transaction, not three). The CM- prefix on the invoice number is the
   only reliable signal (credit_indicator column) -- used for BOTH
   Fred Beans and Downeast. Never stripped: NetSuite's own tranid retains
   it verbatim (confirmed live: 'CM9327256' posts as tranid 'CM9327256').

2. Fred Beans reprints every open invoice monthly under a fallback
   transaction_code ('99 57') -- not new charges, the same open invoice
   shown again. If a '60 35' (original posting) row exists for an
   invoice, it wins outright and every '99 57' row for that invoice is
   ignored. Otherwise, the earliest date on which fallback rows exist is
   taken, and SUM(DISTINCT amount) within that single date collapses
   exact duplicate-extraction rows without merging genuinely separate
   aging dates together (confirmed live on real data: a duplicate-
   extracted row summed correctly via DISTINCT, while a same-invoice
   amount recurring across three different dates stayed as three separate
   line-items rather than incorrectly summing to one).

Downeast Toyota has no transaction codes at all (confirmed 2026-09-17),
so its primary_code/fallback_code are both null in the seed -- every
non-credit row goes straight to the earliest-date-bucket + SUM(DISTINCT)
step, which is exactly Fred Beans' fallback path with no priority check
in front of it. Same underlying algorithm, different parameters -- not a
second rule_type.
"""
import logging

from src.lakehouse.fabric_sql import get_warehouse_connection

logger = logging.getLogger(__name__)


def _load_line_selection_rules() -> dict:
    """Returns {vendor_id: {"charge": rule_row_or_None, "credit": rule_row_or_None}}
    from silver.vendor_line_selection_rule. Read-only, best-effort: returns
    {} (== every vendor passes through unchanged) if the table can't be
    read."""
    try:
        conn = get_warehouse_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT vendor_id, applies_to, rule_type, primary_code, fallback_code, "
            "credit_indicator FROM silver.vendor_line_selection_rule WHERE is_active = 1"
        )
        cols = [c[0] for c in cur.description]
        rules = {}
        for row in cur.fetchall():
            rule = dict(zip(cols, row))
            rules.setdefault(rule["vendor_id"], {})[rule["applies_to"]] = rule
        return rules
    except Exception:
        logger.exception("Reading vendor_line_selection_rule failed -- treating every vendor as passthrough (non-fatal)")
        return {}


def _is_credit(line: dict, credit_indicator) -> bool:
    """True if this line's invoice number starts with the vendor's
    credit_indicator prefix (case-insensitive). Falls back to whichever
    of charge_amount/payment_amount is populated if no credit_indicator
    is configured for this vendor (a vendor without this quirk doesn't
    need prefix-based reclassification at all)."""
    invoice_number = line.get("original_invoice_number") or ""
    if credit_indicator:
        return invoice_number.upper().startswith(credit_indicator.upper())
    return line.get("charge_amount") is None and line.get("payment_amount") is not None


def _line_amount(line: dict):
    """Whichever of charge_amount/payment_amount/amount_remaining is
    populated -- matches the confirmed live query's
    COALESCE(raw_charges, raw_credits, raw_amount) approach, since which
    mapped column got the value is exactly the unreliable signal this
    module exists to route around."""
    for key in ("charge_amount", "payment_amount", "amount_remaining"):
        if line.get(key) is not None:
            return line[key]
    return None


def _exclude_restated_subtotal(distinct_amounts: set) -> list:
    """Fred Beans' page-break extraction quirk: when a fallback-code
    invoice spans a page break, the carried-forward cumulative total gets
    extracted as its own row alongside the real component rows -- e.g.
    9377528 across a page 6/7 break produced 285.13, 465.32, and 750.45,
    where 750.45 is exactly 285.13 + 465.32, not a third real charge
    (confirmed live: NetSuite's tranid 9377528 ties out to 750.45, the sum
    of the two real components, not 1500.90). If one distinct amount
    equals the sum of the others, it's that restated total -- drop it and
    sum only the remaining real components. No such relationship present
    (the common case) -- return every amount unchanged."""
    for amount in distinct_amounts:
        others = [a for a in distinct_amounts if a != amount]
        if others and amount == sum(others):
            return others
    return list(distinct_amounts)


def _select_charge_lines(lines: list, rule: dict) -> list:
    """Implements transaction_code_priority: a primary_code row (if
    configured and present) wins outright for its invoice; otherwise the
    earliest date among (fallback_code-matching, or all, if fallback_code
    isn't set either) rows for that invoice is taken, with
    SUM(DISTINCT amount) collapsing exact duplicate rows within that one
    date."""
    primary_code = (rule.get("primary_code") or "").strip() or None
    fallback_code = (rule.get("fallback_code") or "").strip() or None

    by_invoice = {}
    for line in lines:
        by_invoice.setdefault(line.get("original_invoice_number"), []).append(line)

    selected = []
    for invoice_number, invoice_lines in by_invoice.items():
        primary_rows = [
            l for l in invoice_lines
            if primary_code and (l.get("transaction_code") or "").strip() == primary_code
        ]
        if primary_rows:
            earliest = min(primary_rows, key=lambda l: l.get("line_date") or l.get("due_date"))
            row = dict(earliest)
            row["is_fallback"] = False
            row["component_row_count"] = 1
            selected.append(row)
            continue

        candidate_rows = [
            l for l in invoice_lines
            if not fallback_code or (l.get("transaction_code") or "").strip() == fallback_code
        ]
        if not candidate_rows:
            continue

        by_date = {}
        for l in candidate_rows:
            by_date.setdefault(l.get("line_date"), []).append(l)
        earliest_date = min(by_date.keys())
        date_rows = by_date[earliest_date]

        distinct_amounts = {a for a in (_line_amount(l) for l in date_rows) if a is not None}
        real_amounts = _exclude_restated_subtotal(distinct_amounts)
        summed = sum(real_amounts) if real_amounts else None

        row = dict(date_rows[0])
        row["charge_amount"] = summed
        row["payment_amount"] = None
        row["is_fallback"] = True
        row["component_row_count"] = len(real_amounts)
        selected.append(row)

    return selected


def _select_credit_lines(lines: list) -> list:
    """Implements dedup_by_earliest_date: same (invoice_number, amount)
    recurring on multiple dates -> keep only the earliest-dated row."""
    by_key = {}
    for line in lines:
        key = (line.get("original_invoice_number"), _line_amount(line))
        existing = by_key.get(key)
        line_date = line.get("line_date")
        if existing is None or (line_date and line_date < existing.get("line_date")):
            by_key[key] = line
    return list(by_key.values())


def _select_lines_keep_earliest(lines: list) -> list:
    """Implements keep_earliest: groups by invoice_number ALONE (not also
    amount, unlike _select_credit_lines()) and keeps only the
    earliest-dated row for that invoice, discarding every other row
    outright -- no summing. Confirmed live 2026-09-18 for Quirk/NYE/
    Hoselton's charge sides: these vendors reprint the same still-open
    invoice on every statement cycle until it's paid off, and the
    reprints are later copies of the SAME charge, not separate real
    transactions or components to add together (the distinction that
    makes Fred Beans' fallback-code duplicates need summing instead --
    see _select_charge_lines())."""
    by_invoice = {}
    for line in lines:
        inv = line.get("original_invoice_number")
        existing = by_invoice.get(inv)
        line_date = line.get("line_date")
        if existing is None or (line_date and existing.get("line_date") and line_date < existing["line_date"]):
            by_invoice[inv] = line
    return list(by_invoice.values())


def select_lines(vendor_id: str, lines: list, rules: dict = None) -> list:
    """The public entry point. Given a vendor_id and its raw Silver lines
    for one statement (each a dict with at least original_invoice_number,
    line_date, transaction_code, charge_amount, payment_amount), returns
    the selected/deduped lines ready for shape-based NetSuite matching.

    A vendor with no row in vendor_line_selection_rule passes through
    completely unchanged -- this is the default for every vendor except
    Fred Beans and Downeast Toyota today. `rules` can be passed in
    (already-loaded, e.g. once per matching run across many statements)
    to avoid re-querying the config table per statement; omit it to load
    fresh."""
    if rules is None:
        rules = _load_line_selection_rules()

    vendor_rules = rules.get(vendor_id)
    if not vendor_rules:
        return lines

    charge_rule = vendor_rules.get("charge")
    credit_rule = vendor_rules.get("credit")
    credit_indicator = (
        (charge_rule or {}).get("credit_indicator")
        or (credit_rule or {}).get("credit_indicator")
    )

    charge_side = [l for l in lines if not _is_credit(l, credit_indicator)]
    credit_side = [l for l in lines if _is_credit(l, credit_indicator)]

    result = []
    if charge_rule and charge_rule.get("rule_type") == "keep_earliest":
        result.extend(_select_lines_keep_earliest(charge_side))
    elif charge_rule:
        result.extend(_select_charge_lines(charge_side, charge_rule))
    else:
        result.extend(charge_side)

    if credit_rule:
        result.extend(_select_credit_lines(credit_side))
    else:
        result.extend(credit_side)

    if credit_indicator:
        # The stored line_type (sign-based, see silver_silver_build's
        # _derive_line_type()) is exactly the unreliable signal this
        # module exists to route around -- confirmed live that a
        # CM-prefixed Fred Beans row can carry transaction_code '60 35'
        # (looks like a charge) while genuinely being a credit memo. Once
        # credit_indicator has determined the real classification, fix
        # line_type to match rather than leaving the stale value in place.
        for line in result:
            line["line_type"] = "CREDIT" if _is_credit(line, credit_indicator) else "CHARGE"

    return result
