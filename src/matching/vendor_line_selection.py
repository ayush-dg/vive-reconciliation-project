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
    credit_indicator prefix (case-insensitive). credit_indicator only
    exists for vendors whose line_type is known unreliable (Fred Beans/
    Downeast -- see module docstring, quirk 1). Every other vendor's
    line_type is already correctly derived in Silver, so that's the
    fallback when no credit_indicator is configured -- confirmed live
    2026-09-21 that the previous fallback (charge_amount is None and
    payment_amount is not None) silently misclassified every CREDIT line
    for Quirk/NYE/Hoselton too (their credit lines carry a populated,
    negative charge_amount, not payment_amount) -- harmless for those
    three only because their raw credit/charge document numbers never
    collide, but a real bug for Nucar's Lees layout, whose CHARGE and
    CREDIT lines for the same invoice share the identical raw
    document_number (e.g. CVW6278158-1) -- the old heuristic would merge
    them into one keep_earliest group and silently drop one."""
    invoice_number = line.get("original_invoice_number") or ""
    if credit_indicator:
        return invoice_number.upper().startswith(credit_indicator.upper())
    return line.get("line_type") == "CREDIT"


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
    date.

    primary_code may hold more than one code, pipe-separated (e.g.
    '60 35|65 35|66 35') -- confirmed live 2026-09-23 that Fred Beans uses
    a DIFFERENT original-posting code per branch/customer number, not one
    fixed code: STMT-C1007C68 uses '65 35' where every other seen Fred
    Beans statement uses '60 35', and a third ('66 35') also appears
    elsewhere -- all functionally the same "original posting" row, single
    hardcoded '60 35' silently dropped the whole original charge for any
    statement using a different one (falling through to the fallback-only
    reprint row instead, e.g. invoice 9435152 matched against NetSuite's
    real bill total of $489.62 using only the reprint's $414.62, a false
    'Amount Mismatch'). Deliberately NOT "any code that isn't the fallback
    code" -- Fred Beans also has an unrelated '60 56' code used only for
    'NM<date><code>'/'VS<date>CA'-style statement-total control rows (a
    balance-forward marker, not a real invoice, always paired with an
    identical-amount '99 57' twin under the same pseudo-document-number)
    that would otherwise get swept in as a fake invoice and reported as a
    spurious 'Not Found' exception."""
    primary_codes = {
        c.strip() for c in (rule.get("primary_code") or "").split("|") if c.strip()
    }
    fallback_code = (rule.get("fallback_code") or "").strip() or None

    by_invoice = {}
    for line in lines:
        by_invoice.setdefault(line.get("original_invoice_number"), []).append(line)

    selected = []
    for invoice_number, invoice_lines in by_invoice.items():
        primary_rows = [
            l for l in invoice_lines
            if (l.get("transaction_code") or "").strip() in primary_codes
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


def _reclassify_payment_rows_by_po_reference(lines: list) -> list:
    """Implements reclassify_payment_by_po_reference (applies_to='both'):
    RH Long Motor Sales' statements (REFER# -> original_invoice_number,
    PO#/MEMO -> po_number, JR -> transaction_code). transaction_code is the
    reliable, account-independent signal here -- confirmed live 2026-09-22
    on two different RH accounts: JR=50 always marks a payment-batch
    application row (e.g. Hudson's document 220663, Holyoke's 220830, each
    recurring once per invoice it pays off that cycle, PO#/MEMO holding
    that invoice's own REFER#) and JR=85 always marks either a real charge
    or a standalone credit. What ISN'T reliable is which raw column (and
    therefore which sign-based line_type) a JR=50 or JR=85 row's amount
    lands in -- it's flipped between Hudson and Holyoke (a JR=50 row is
    PAYMENT-typed on Hudson's statement, CHARGE-typed on Holyoke's;
    likewise the JR=85 charges it pays off land the opposite way). A
    line_type-only check therefore worked for one account and silently
    broke on the other. Using transaction_code directly sidesteps that
    entirely.

    Two passes:

    1. Every JR=50 row is a payment-batch application row -- dropped
       outright (not a real NetSuite transaction), and its po_number is
       recorded as "referenced."
    2. Any JR=85 row whose own REFER# was referenced by a JR=50 row is
       therefore a real charge being paid down this cycle -- forced to
       CHARGE (undoing a wrong sign-based classification if its amount
       happened to land in PYMTS/CR), regardless of which column its
       amount landed in. A JR=85 row that's NOT referenced by any JR=50
       row keeps its natural sign-based classification: real open charges
       stay CHARGE, and the remainder (JR=85 rows whose amount landed in
       PYMTS/CR with no batch application pointing at them) are genuine
       standalone credits -- confirmed live: Hudson's 491604/489356 and
       Holyoke's 488177/488643/etc. are all JR=85 too, same code as real
       charges, which is exactly why JR alone can't tell a real charge
       from a standalone credit -- only the reference check can.
       Reclassified to CREDIT here (routes to netsuite_vendorcredit
       instead of netsuite_vendorbill). Does NOT guess a 'CM' prefix at
       this layer: RH's own credit-tranid convention is inconsistent even
       across its own accounts -- Hudson posts 'CM<invoice>' (CM491604 ->
       $52.87 exact), Holyoke posts the raw invoice with no prefix at all
       (488643 -> $50 exact, as-is). fabric_matching.py's credit lookup
       tries the raw invoice_number first and falls back to
       'CM'+invoice_number only if that misses -- see
       run_fabric_matching()'s credit branch.

    Does NOT attempt RH's separate invoice-to-invoice reallocation pattern
    (e.g. Holyoke's 486876/487374, which share a PO#/MEMO purely
    coincidentally with unrelated invoices too -- per-vendor rule #5:
    PO#/MEMO is not unique per invoice, so it can't be trusted as a
    reallocation signal the way it can for the batch-number case above,
    where the po_number is unambiguously another invoice's exact REFER#)."""
    referenced_by_batch = {
        l.get("po_number") for l in lines
        if (l.get("transaction_code") or "").strip() == "50"
    }

    result = []
    for line in lines:
        if (line.get("transaction_code") or "").strip() == "50":
            continue  # payment-batch application row -- not a real transaction
        inv = line.get("original_invoice_number")
        if inv in referenced_by_batch and line.get("line_type") != "CHARGE":
            line = dict(line)
            line["line_type"] = "CHARGE"
            if line.get("charge_amount") is None:
                line["charge_amount"] = line.get("payment_amount")
            result.append(line)
            continue
        if line.get("line_type") == "PAYMENT":
            line = dict(line)
            line["line_type"] = "CREDIT"
        result.append(line)
    return result


def _exclude_by_transaction_code(lines: list, rule: dict) -> list:
    """Implements exclude_by_transaction_code: drops every line whose
    transaction_code matches rule['primary_code'] outright -- not a dedup,
    these lines don't represent a distinct real transaction at all.
    Confirmed live 2026-09-21 for Nucar's 'Lees' layout (Reynolds and
    Reynolds template): each invoice has up to three raw rows -- the
    CHARGE, a genuine credit memo (transaction_code '4', reference column
    'CM<invoice>', a real bronze.netsuite_vendorcredit tranid), and a
    transaction_code '5' row (the statement's own legend: '5 PAYMENT') that
    exactly cancels the CHARGE and carries a shared batch reference
    ('751401' recurring across dozens of unrelated invoices on the same
    statement), not an invoice-specific one. Sign-based line_type
    classification (see dbt/vive_recon/models/silver/statement_line.sql)
    can't tell these two CREDIT-typed rows apart -- both reconstruct to the
    identical invoice_number (e.g. CM6281023-1), so without this exclusion
    the real credit memo's exact NetSuite match and the payment row's
    unrelated amount collide under the same key, and the payment row gets
    written up as a false 'Amount Mismatch' against the credit memo's
    total. The CHARGE itself already matches correctly against
    bronze.netsuite_vendorbill on its own (e.g. 6281023-1 -> $398.86) --
    the payment row isn't a second NetSuite transaction to find, it's the
    statement's own bookkeeping showing that charge got paid down."""
    exclude_code = (rule.get("primary_code") or "").strip()
    if not exclude_code:
        return lines
    return [l for l in lines if (l.get("transaction_code") or "").strip() != exclude_code]


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

    both_rule = vendor_rules.get("both")
    if both_rule and both_rule.get("rule_type") == "reclassify_payment_by_po_reference":
        lines = _reclassify_payment_rows_by_po_reference(lines)

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

    if credit_rule and credit_rule.get("rule_type") == "exclude_by_transaction_code":
        result.extend(_exclude_by_transaction_code(credit_side, credit_rule))
    elif credit_rule:
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
