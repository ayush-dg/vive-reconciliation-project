"""Matches one statement's Fabric Silver rows (silver.statement_line)
against live NetSuite vendor bills (bronze.netsuite_vendorbill, an
existing, separately-maintained ingestion pipeline already in the same
Lakehouse) and writes results to silver.recon_matched_invoices/
recon_exceptions/recon_summary in the Fabric Warehouse (schema created by
scripts/create_fabric_recon_schema.py) -- NOT the gold_* tables in the
existing Azure SQL/SQLite backend (this data belongs on the Recon layer
per docs/ARCHITECTURE.md, not Gold; moved here from a local-SQLite-backed
migrations/013_add_recon_tables.sql per the user 2026-08-26, accepting
the latency of live Fabric queries over local SQLite for the Exceptions
page in exchange for the data genuinely living in Fabric).

Four matching rules (A/B/C generalized from a validated Bald Hill query,
same logic, applied to silver.statement_line's generic columns instead of
that vendor's raw column names; D added to generalize the
prefix-stripped/aging-statement vendors -- Hoselton, NYE, Quirk -- into
this same engine instead of a separate one, once their extractors emit a
clean invoice_number the same way every other vendor's already does):
  A. exactly one CHARGE line for an invoice_number, no CREDIT/PAYMENT lines
     -- checked against bronze.netsuite_vendorbill (a normal invoice)
  B. exactly one CREDIT or PAYMENT line, no CHARGE lines -- checked
     against bronze.netsuite_vendorcredit (a credit memo), not
     netsuite_vendorbill. PAYMENT-typed here specifically means "has an
     invoice_number" -- a PAYMENT line with no invoice_number (e.g. Berlin
     City's "Last payment of X received" memo, no document reference) is
     never grouped into a shape at all (see _build_invoice_shapes()), so
     it can't reach this rule; only PAYMENT lines that DO reference a real
     document -- which turned out, checking real Bald Hill data, to
     genuinely BE credit memos, not payment notices, hence the same
     table as CREDIT-type lines.
  C. exactly one CHARGE + one CREDIT line, their amounts are equal in
     magnitude, and that amount == NetSuite bill total -- checked against
     netsuite_vendorbill (a charge fully offset by its own reversal, both
     tying to the same original bill)
  D. anything else with at least one CHARGE or CREDIT line -- take the
     EARLIEST-dated CHARGE line, full stop, ignoring every other line on
     that invoice_number (further credit-memo reversals, payment
     applications, or a charge amount re-echoed on a later statement
     cycle); if there's no CHARGE line at all, take the earliest-dated
     CREDIT line instead. Checked against netsuite_vendorbill /
     netsuite_vendorcredit respectively. Deliberately NOT count-based (an
     earlier design counted charge lines and required exactly one; a
     charge amount can be legitimately re-echoed as a second CHARGE-typed
     line on a later cycle, which a count-based rule gets fooled by, so
     "earliest wins" is the rule that actually holds up). A shape with
     only PAYMENT lines (no CHARGE, no CREDIT) stays ineligible here --
     not enough validated real-world evidence yet for what that shape
     means; flagged rather than guessed.

Credit-side NetSuite lookups use substring matching (_match_credit()), not
an exact tranid match: a statement credit's real NetSuite tranid can take
inconsistent forms relative to the statement's own invoice_number (e.g.
CMA435584, CMA435584-1, CM-9435584X1 all logically the same credit) --
an exact-match assumption silently misses real matches. Bills still use
an exact tranid match (_fetch_netsuite_transactions()) since that pattern
hasn't been observed there.

Explicitly NOT implemented yet: the original query's "variants_on_statement"
guard (skipping invoice_numbers that have multiple revisions on the
statement) -- the generic extraction schema has no field capturing "this
line is a revision of that other invoice", so this can't be computed today.
Decided with the user 2026-08-26 to ship without it and revisit only if it
causes real false-positive matches in practice. Rule D's "earliest wins"
behavior is this project's replacement for that guard on the vendors that
actually needed it.

Best-effort in the sense every other module here is: never raises into the
caller (scripts/run_full_pipeline.py calls this right after the dbt Silver
build) -- a failure here shouldn't block the rest of the pipeline. Returns
a summary dict either way.

Connection reuse: one Warehouse connection and one Lakehouse connection for
the whole run, not one per statement/query/write -- each Fabric connection
does a real AAD token fetch + TLS handshake (seconds, not milliseconds).
The first version of this module called execute_sql() (a fresh connection
every call) once per row; on a 41-line statement that's 45+ connections and
took over 2 minutes. Passing shared cursors through instead brings a real
run down to a handful of round trips.
"""
import logging
import os
import re
import uuid
from datetime import datetime, timezone

from src.lakehouse.fabric_sql import get_lakehouse_connection, get_warehouse_connection
from src.matching.netsuite_vendor_resolver import resolve_entity_ids
from src.matching.vendor_line_selection import select_lines, _load_line_selection_rules
from src.shop_owners import get_shop_owner

logger = logging.getLogger(__name__)

EXACT_AMOUNT_EPSILON = 0.005


def _fabric_configured() -> bool:
    return bool(
        os.getenv("FABRIC_TENANT_ID")
        and os.getenv("FABRIC_CLIENT_ID")
        and os.getenv("FABRIC_CLIENT_SECRET")
        and os.getenv("FABRIC_SQL_ENDPOINT")
        and os.getenv("FABRIC_WAREHOUSE_NAME")
        and os.getenv("FABRIC_LAKEHOUSE_NAME")
    )


def _fetch_statement(cur, statement_id: str):
    # silver.statement has no statement_period column -- extraction only
    # produces per-invoice-row data, not statement-level metadata like
    # period (see dbt/README.md's known gaps). recon_summary.statement_period
    # is left null for rows from this pipeline until that's addressed.
    cur.execute(
        "SELECT statement_id, vendor_id, vendor_name_raw, shop_name_raw, "
        "source_bronze_table FROM silver.statement WHERE statement_id = ?",
        [statement_id],
    )
    row = cur.fetchone()
    if not row:
        return None
    cols = [c[0] for c in cur.description]
    return dict(zip(cols, row))


def _fetch_lines(cur, statement_id: str) -> list:
    cur.execute(
        "SELECT statement_line_id, invoice_number, document_number, invoice_number_ref, "
        "transaction_code, line_type, charge_amount, payment_amount, po_number, ro_number, line_date "
        "FROM silver.statement_line WHERE statement_id = ?",
        [statement_id],
    )
    cols = [c[0] for c in cur.description]
    lines = [dict(zip(cols, row)) for row in cur.fetchall()]

    # select_lines() (Fred Beans/Downeast Toyota reprint/fallback-code
    # dedup, see its own docstring) expects an "original_invoice_number"
    # key -- silver.statement_line only has "invoice_number", which is
    # already the raw/unnormalized value for both these vendors (neither
    # has a row in vendor_normalization_rule), so aliasing it in both
    # directions is safe: nothing here strips or reconstructs it. A
    # vendor with no row in vendor_line_selection_rule passes through
    # select_lines() completely unchanged. NOTE: this is a DIFFERENT
    # field from "document_number" fetched above -- for a vendor WITH a
    # normalization rule (Nucar/Quirk/NYE/Hoselton), invoice_number here
    # is already stripped/reconstructed, so "original_invoice_number"
    # is not actually the raw value for them (harmless today: select_lines()
    # only reads it for these two vendors, where it happens to be correct).
    # "document_number" is always the true pre-normalization raw value for
    # every vendor -- used to populate recon_matched_invoices/
    # recon_exceptions' original_invoice_number column (added 2026-09-21
    # so the UI can show both the raw statement value and the normalized
    # one it was matched against, instead of only the latter).
    for line in lines:
        line["original_invoice_number"] = line["invoice_number"]
    return lines


def _drop_payment_closing_lines(lines: list) -> list:
    """Universal, vendor-agnostic pre-filter (runs for every vendor,
    before any vendor_line_selection_rule dedup): drops a PAYMENT-typed
    line whose invoice_number ALSO has a CHARGE line on this same
    statement. Confirmed live 2026-09-21 on Bowser's STMT-700EB5D9
    (no vendor_line_selection_rule row at all -- Bowser isn't configured
    for dedup): invoices like 73964 have a CHARGE line (2052.30, dated
    06-29) and a PAYMENT line (2052.30, dated 07-29, same invoice_number)
    -- the PAYMENT line is the statement's own display of that charge
    being paid down, not a second NetSuite transaction, but with no dedup
    rule configured it was checked on its own against netsuite_vendorcredit
    for tranid '73964', found nothing, and got written up as a spurious
    'Not Found' exception right alongside the CHARGE line's correct match.
    Same underlying shape as Nucar's transaction_code=5 rows and
    Downeast's payment reprints -- this generalizes it as the default for
    every vendor, not a per-vendor config row, since nothing about it is
    vendor-specific: a payment posting for an invoice that's ALSO charged
    on the same statement is never a distinct NetSuite record anywhere.
    Deliberately keyed on "same invoice_number as a CHARGE line," not "is
    PAYMENT-typed" alone -- confirmed against Bowser's OTHER statement
    (STMT-266FED49) that this must NOT be a blanket PAYMENT exclusion:
    its PAYMENT lines are CM-prefixed (e.g. CM75914) with no bare '75914'
    CHARGE line anywhere on that statement -- genuine distinct credits,
    same convention as Fred Beans, and must still be checked."""
    charge_invoice_numbers = {
        l["invoice_number"] for l in lines if l.get("line_type") == "CHARGE"
    }
    return [
        l for l in lines
        if not (l.get("line_type") == "PAYMENT" and l.get("invoice_number") in charge_invoice_numbers)
    ]


def _apply_line_selection(vendor_id: str, lines: list, rules: dict) -> list:
    """select_lines() needs vendor_id (to look up its dedup rule) which
    _fetch_lines() doesn't have -- kept as a separate step, called right
    after _fetch_lines(), rather than threading vendor_id through it.
    `rules` is the already-loaded vendor_line_selection_rule table (see
    run_fabric_matching(), which also uses it to decide whether this
    vendor needs shape-based matching at all) -- passed in rather than
    reloaded here."""
    lines = select_lines(vendor_id, lines, rules)
    for line in lines:
        line["invoice_number"] = line["original_invoice_number"]
    return lines


def _fetch_netsuite_candidates(cur, entity_ids: list, table: str) -> dict:
    """Returns {tranid: [total, total, ...]} -- EVERY non-voided total for
    each tranid among these entities, not collapsed into a single value.
    A tranid with more than one differing non-voided total used to be
    treated as unresolved ambiguity and excluded outright -- confirmed
    live 2026-09-18 that this was too conservative for at least Fred
    Beans: many CM-prefixed credits have multiple legitimate non-voided
    NetSuite rows sharing a tranid, and one of them frequently ties out
    exactly with the statement amount. _best_candidate() below checks for
    that exact tie-out first; only when NONE of the candidates tie out
    does it fall back to the single closest one, surfaced as a reviewable
    near-miss (Amount Mismatch) rather than a blanket "unresolved.\""""
    if not entity_ids:
        return {}
    placeholders = ",".join("?" * len(entity_ids))
    cur.execute(
        f"SELECT tranid, total FROM bronze.{table} "
        f"WHERE entity IN ({placeholders}) AND voided = 'F' AND tranid IS NOT NULL",
        entity_ids,
    )
    # Keyed lowercase -- confirmed live 2026-09-18 that NetSuite's own
    # tranid casing is inconsistent even within one vendor (NYE: a
    # stripped TOW invoice ties out to an uppercase tranid, e.g.
    # "433845T", while a stripped CHW/GCW invoice ties out to a lowercase
    # one, e.g. "253431c") -- there is no single stored-case transform
    # that resolves both; comparing case-insensitively at match time does,
    # without needing a per-prefix normalization rule. The lookup side
    # (shape["invoice_number"].lower()) is lowercased to match.
    by_tranid = {}
    for tranid, total in cur.fetchall():
        try:
            total_f = float(total)
        except (TypeError, ValueError):
            continue
        by_tranid.setdefault(tranid.lower(), []).append(total_f)
    return by_tranid


def _best_candidate(candidates: list, target_amount) -> tuple:
    """Returns (chosen_total, is_exact_match). An exact tie-out (within
    EXACT_AMOUNT_EPSILON) against ANY candidate wins outright, regardless
    of how many other non-tying candidates share the same tranid.
    Otherwise the single closest-by-amount candidate is returned as a
    near-miss for human review, not a match. Returns (None, False) if
    there are no candidates at all for this tranid."""
    if not candidates:
        return None, False
    if target_amount is None:
        return candidates[0], False
    for total in candidates:
        if abs(total - target_amount) <= EXACT_AMOUNT_EPSILON:
            return total, True
    closest = min(candidates, key=lambda t: abs(t - target_amount))
    return closest, False


def _line_target(line: dict) -> tuple:
    """Per-line equivalent of _shape_target(), used for vendors that don't
    have a vendor_line_selection_rule row (i.e. every vendor except Fred
    Beans/Downeast Toyota -- see run_fabric_matching()). Where
    _shape_target() decides a NetSuite table for a whole GROUP of lines
    sharing an invoice_number and refuses to guess when a charge+credit
    pair doesn't net to exactly zero, this checks each line entirely on
    its own -- confirmed live 2026-09-18 that grouping was actively wrong
    for at least NYE: a $168.59 charge + an unrelated $39.02 credit on the
    same invoice_number (not a reversal of each other -- NetSuite has no
    record of the $39.02 at all) made the whole shape "ineligible" and
    permanently unmatchable, even though the charge line alone ties out
    to NetSuite exactly. Per the user 2026-09-18: keep this simpler
    per-line approach as the default for every vendor; the shape-based
    A/B/C rules (and their net-to-zero requirement) stay reserved for
    Fred Beans/Downeast, whose select_lines() dedup already collapses
    reprint/fallback-code duplicates into single deliberate lines before
    shape-building ever needs to reconcile a pair against each other."""
    line_type = line.get("line_type")
    if line_type == "CHARGE":
        return line.get("charge_amount"), "netsuite_vendorbill"
    if line_type == "CREDIT":
        # Falls back to payment_amount -- confirmed live 2026-09-21 for
        # Fred Beans: select_lines() reclassifies a CM-prefixed line as
        # CREDIT based on its invoice_number prefix regardless of which
        # mapped column the value landed in (the vendor's own "credits"
        # column maps to payment_amount, not charge_amount -- see
        # vendor_field_mapping.csv), so charge_amount is often None on a
        # line that IS a real credit. Looking at charge_amount alone
        # silently produced a None statement_amount, which _best_candidate()
        # then treated as an automatic non-exact match against whatever
        # candidate happened to be first -- a false "Amount Mismatch" on
        # 23 of Fred Beans' real exceptions, not a genuine discrepancy.
        amt = line.get("charge_amount")
        if amt is None:
            amt = line.get("payment_amount")
        return (abs(amt) if amt is not None else None), "netsuite_vendorcredit"
    if line_type == "PAYMENT":
        return line.get("payment_amount"), "netsuite_vendorcredit"
    return None, None


def _fetch_netsuite_credit_candidates(cur, entity_ids: list) -> list:
    """Returns [(tranid_lower, total), ...] -- every non-voided
    netsuite_vendorcredit row for these entities, as a flat list (not the
    dict-keyed-by-exact-tranid shape _fetch_netsuite_candidates() returns)
    since _match_credit() needs to scan every tranid for substring
    containment, not do an exact-key lookup. tranid is lowercased for a
    case-insensitive substring check -- same rationale as
    _fetch_netsuite_candidates()'s lowercasing (confirmed live elsewhere
    that NetSuite's own tranid casing is inconsistent)."""
    if not entity_ids:
        return []
    placeholders = ",".join("?" * len(entity_ids))
    cur.execute(
        f"SELECT tranid, total FROM bronze.netsuite_vendorcredit "
        f"WHERE entity IN ({placeholders}) AND voided = 'F' AND tranid IS NOT NULL",
        entity_ids,
    )
    candidates = []
    for tranid, total in cur.fetchall():
        try:
            total_f = float(total)
        except (TypeError, ValueError):
            continue
        candidates.append((tranid.lower(), total_f))
    return candidates


def _match_credit(invoice_number: str, statement_amount, credit_candidates: list) -> tuple:
    """Searches credit_candidates for tranids CONTAINING invoice_number as
    a substring (see _fetch_netsuite_credit_candidates() for why this
    isn't an exact match -- Keystone specifically, confirmed live
    2026-09-22: the SAME vendor reconstructs its credit tranid differently
    per statement/location -- Z1451096 -> CMZ1451096 (no dash), TS247490
    -> CM-TS247490 (dash), ME288615 -> ME288615 (no CM at all) -- with no
    way to know in advance which convention a given location uses.
    invoice_number is expected pre-lowercased by the caller, matching
    credit_candidates' tranids. Returns (netsuite_total_or_None,
    candidate_count).

    candidate_count > 1 with netsuite_total is None means a genuine
    ambiguity for the caller to flag ("Possible Duplicate"), not something
    to silently resolve -- 2+ real NetSuite records can share a base
    tranid (e.g. a credit memo split across multiple apply-against-bill
    records, or an unrelated base/suffix pair), and guessing which one is
    right risks a false match on a coincidental tranid collision under an
    unrelated entity. If exactly one of several candidates ties out to
    the statement amount, that candidate is returned (an unambiguous
    answer even though other candidates exist); otherwise None is
    returned so the caller reports "Possible Duplicate" rather than an
    amount mismatch it can't actually attribute to one record."""
    if not invoice_number or statement_amount is None:
        return None, 0
    matches = [total for tranid, total in credit_candidates if invoice_number in tranid]
    if not matches:
        return None, 0
    if len(matches) == 1:
        return matches[0], 1
    exact = [t for t in matches if _amounts_tie_out(statement_amount, t)]
    if len(exact) == 1:
        return exact[0], len(matches)
    return None, len(matches)


def _build_invoice_shapes(lines: list) -> dict:
    """Groups statement lines by invoice_number. charge_amount usually
    carries the sign (positive for CHARGE lines, negative for CREDIT lines
    -- see dbt/vive_recon/models/silver/statement_line.sql), so credit
    magnitude is normally abs(charge_amount) on a CREDIT-typed line --
    but falls back to payment_amount when charge_amount is None
    (confirmed live 2026-09-21: select_lines() can reclassify a line as
    CREDIT based on its invoice_number prefix -- e.g. Fred Beans' CM-
    prefix -- independent of which mapped column the vendor's own
    "credits" field landed in; Fred Beans' maps to payment_amount, not
    charge_amount). A PAYMENT line with no invoice_number (e.g. a
    payment-received memo with no document reference) is dropped here
    (`if not inv: continue`) -- only PAYMENT lines that DO reference a
    real invoice_number reach a shape, which in every real case checked
    so far means "credit memo", not "payment notice" -- see the module
    docstring's Rule B."""
    shapes = {}
    for line in lines:
        inv = line["invoice_number"]
        if not inv:
            continue
        shape = shapes.setdefault(inv, {
            "invoice_number": inv, "lines": [], "charge_line_count": 0,
            "credit_line_count": 0, "payment_line_count": 0,
            "charge_amt": None, "credit_amt": None, "payment_amt": None,
            "ro_number": None, "line_date": None, "document_number": None,
        })
        shape["lines"].append(line)
        shape["ro_number"] = shape["ro_number"] or line.get("ro_number")
        shape["line_date"] = shape["line_date"] or line.get("line_date")
        shape["document_number"] = shape["document_number"] or line.get("document_number")
        if line["line_type"] == "CHARGE":
            shape["charge_line_count"] += 1
            shape["charge_amt"] = line["charge_amount"]
        elif line["line_type"] == "CREDIT":
            shape["credit_line_count"] += 1
            # Falls back to payment_amount -- see _line_target()'s comment
            # for the exact live-confirmed case (Fred Beans CM-prefixed
            # credits whose value lives in payment_amount, not
            # charge_amount, after select_lines() reclassifies them).
            credit_amt = line["charge_amount"] if line["charge_amount"] is not None else line["payment_amount"]
            shape["credit_amt"] = abs(credit_amt) if credit_amt is not None else None
        elif line["line_type"] == "PAYMENT":
            shape["payment_line_count"] += 1
            shape["payment_amt"] = line["payment_amount"]
    return shapes


_ORDINAL_REF_RE = re.compile(r"\*(\d+)$")


def _apply_ordinal_suffix(invoice_number: str, invoice_number_ref) -> str:
    """Nucar's 'Lees' layout (Reynolds and Reynolds template) can show
    MULTIPLE separate real credit memos against the same base invoice on
    one statement -- e.g. CVW6283886 had two genuinely distinct $75
    credits, whose REFERENCE column values were 'CMCVW6283886' and
    'CMCVW6283886*1'. Both reconstruct to the identical invoice_number
    (CM6283886) under the vendor_normalization_rule CM{invoice} template,
    which only ever looks at the base document_number -- confirmed live
    2026-09-21 that NetSuite itself posts these as two SEPARATE tranids,
    'CM6283886' and 'CM6283886-1' (bronze.netsuite_vendorcredit), not one
    tranid with two applications. Without this, both statement lines would
    be checked against the SAME 'cm6283886' candidate list -- happened to
    still tie out on STMT-F4C7C745 only because both real credits were
    coincidentally $75 each; a statement where the ordinal credits differ
    in amount would silently mismatch. A '*N' suffix on invoice_number_ref
    (the raw REFERENCE column) is the statement's own way of marking "the
    Nth additional credit for this invoice" -- appending '-N' to the
    already-normalized invoice_number reproduces NetSuite's own tranid
    exactly. No-op (returns invoice_number unchanged) when invoice_number_ref
    doesn't end in '*<digits>' -- every other vendor's invoice_number_ref
    values are unaffected."""
    match = _ORDINAL_REF_RE.search(invoice_number_ref or "")
    if not match:
        return invoice_number
    return f"{invoice_number}-{match.group(1)}"


def _amounts_tie_out(a: float, b: float) -> bool:
    return a is not None and b is not None and abs(a - b) <= EXACT_AMOUNT_EPSILON


def _earliest_of_type(lines: list, line_type: str):
    """Returns the earliest-dated line of the given type from a shape's
    lines, or None if there isn't one. A line with no line_date sorts
    last rather than raising -- a missing date shouldn't crash matching,
    just lose priority to lines that do have one."""
    typed = [line for line in lines if line["line_type"] == line_type]
    if not typed:
        return None
    return min(typed, key=lambda line: (line["line_date"] is None, line["line_date"]))


def _shape_target(shape: dict) -> tuple:
    """Returns (statement_amount, netsuite_table_or_None) for one invoice
    shape, applying rules A/B/C/D -- decides WHICH NetSuite table (bill vs
    credit memo) this shape should be checked against, before any lookup
    happens. netsuite_table is None for a shape with no CHARGE or CREDIT
    line at all (e.g. payment-only activity) -- statement_amount is still
    returned where available so an exception row isn't left with no
    amount at all."""
    line_count = len(shape["lines"])
    c, r, p = shape["charge_line_count"], shape["credit_line_count"], shape["payment_line_count"]

    if line_count == 1 and c == 1 and r == 0 and p == 0:
        return shape["charge_amt"], "netsuite_vendorbill"
    if line_count == 1 and c == 0 and r == 1 and p == 0:
        return shape["credit_amt"], "netsuite_vendorcredit"
    if line_count == 1 and c == 0 and r == 0 and p == 1:
        return shape["payment_amt"], "netsuite_vendorcredit"
    if line_count == 2 and c == 1 and r == 1 and p == 0:
        stmt_amount = shape["charge_amt"]
        if _amounts_tie_out(shape["charge_amt"], shape["credit_amt"]):
            return stmt_amount, "netsuite_vendorbill"
        # Doesn't tie out -- not the "charge fully offset by its own
        # reversal" pattern Rule C was written for (e.g. a charge later
        # reduced by an unrelated-magnitude credit that was never meant to
        # net to zero). Falls through to Rule D instead of returning
        # ineligible -- Rule D resolves it correctly (earliest charge
        # line, checked against netsuite_vendorbill).

    # Rule D -- see module docstring. Earliest CHARGE line wins outright;
    # only falls back to earliest CREDIT line when there's no charge at
    # all on this invoice_number.
    earliest_charge = _earliest_of_type(shape["lines"], "CHARGE")
    if earliest_charge is not None:
        return earliest_charge["charge_amount"], "netsuite_vendorbill"
    earliest_credit = _earliest_of_type(shape["lines"], "CREDIT")
    if earliest_credit is not None:
        # Same payment_amount fallback as shape["credit_amt"] above --
        # Downeast's "credits" column maps to payment_amount, not
        # charge_amount (confirmed 2026-09-21: TEST-PREPROD-3E3DBFC6 was
        # returning null statement_amount for CM-prefixed invoices that
        # land here via Rule D, because this branch only ever read
        # charge_amount).
        charge_amount = earliest_credit["charge_amount"]
        if charge_amount is None:
            charge_amount = earliest_credit["payment_amount"]
        credit_amt = abs(charge_amount) if charge_amount is not None else None
        return credit_amt, "netsuite_vendorcredit"

    return (shape["charge_amt"] or shape["credit_amt"] or shape["payment_amt"]), None


def run_fabric_matching(statement_id: str) -> dict:
    """Best-effort: never raises. Returns a summary dict; check
    result.get("error") for a description of what went wrong, if anything."""
    if not _fabric_configured():
        logger.debug("Fabric not configured -- skipping Fabric NetSuite matching")
        return {"skipped": True, "reason": "fabric_not_configured"}

    wh_conn = None
    try:
        wh_conn = get_warehouse_connection()
        wh_cur = wh_conn.cursor()

        header = _fetch_statement(wh_cur, statement_id)
        if not header:
            return {"skipped": True, "reason": "no_silver_statement"}

        vendor_id = header["vendor_id"]
        vendor_name = header["vendor_name_raw"]
        shop = header["shop_name_raw"]
        shop_owner = get_shop_owner(vendor_id)
        now = datetime.now(timezone.utc).isoformat()

        # Idempotent: a re-run of the same statement_id (e.g. after fixing
        # a matching rule) replaces its prior results rather than
        # duplicating them -- same DELETE-then-INSERT pattern
        # write_to_bronze() already uses for the existing pipeline.
        wh_cur.execute("DELETE FROM silver.recon_matched_invoices WHERE statement_id = ?", [statement_id])
        wh_cur.execute("DELETE FROM silver.recon_exceptions WHERE statement_id = ?", [statement_id])
        wh_cur.execute("DELETE FROM silver.recon_summary WHERE statement_id = ?", [statement_id])

        lines = _fetch_lines(wh_cur, statement_id)
        lines = _drop_payment_closing_lines(lines)

        # select_lines() dedup applies to any vendor with a
        # vendor_line_selection_rule row -- today that's Fred Beans/
        # Downeast (transaction_code_priority: reprints get summed by
        # fallback code) and Quirk/NYE/Hoselton (keep_earliest: reprints
        # get discarded, only the first-dated charge line survives; added
        # 2026-09-18, confirmed live against real NetSuite data).
        #
        # Shape-based A/B/C matching (grouping every line sharing an
        # invoice_number, requiring a charge+credit pair to net to exactly
        # zero before even attempting a NetSuite lookup) is a SEPARATE,
        # narrower decision from "needs dedup" -- it stays reserved for
        # transaction_code_priority vendors specifically (Fred Beans/
        # Downeast), whose CM-prefixed credits can legitimately be a full
        # reversal of a charge. Quirk/NYE/Hoselton (keep_earliest) use the
        # simpler per-line direct query (_line_target()) instead --
        # confirmed live 2026-09-18 that shape-grouping was actively wrong
        # for a vendor without that reversal pattern (see _line_target()'s
        # docstring for the NYE case that motivated this).
        selection_rules = _load_line_selection_rules()
        vendor_rules = selection_rules.get(vendor_id)
        if vendor_rules:
            lines = _apply_line_selection(vendor_id, lines, selection_rules)
        vendor_uses_shapes = bool(vendor_rules) and (vendor_rules.get("charge") or {}).get("rule_type") == "transaction_code_priority"

        entity_ids = resolve_entity_ids(vendor_id, vendor_name)

        matched_count = 0
        exception_count = 0
        statement_total = 0.0
        erp_total = 0.0

        if not entity_ids:
            if vendor_uses_shapes:
                items = list(_build_invoice_shapes(lines).values())
            else:
                items = [l for l in lines if l.get("invoice_number")]
            for item in items:
                if vendor_uses_shapes:
                    stmt_amount = item["charge_amt"] if item["charge_line_count"] else item["credit_amt"]
                else:
                    stmt_amount, _ = _line_target(item)
                _write_exception(
                    wh_cur, statement_id, vendor_id, shop, shop_owner, item["invoice_number"],
                    item["ro_number"], stmt_amount, None, "Vendor Not Resolved in NetSuite", now,
                    original_invoice_number=item.get("document_number"),
                )
                exception_count += 1
                statement_total += stmt_amount or 0.0
        else:
            lh_conn = get_lakehouse_connection()
            lh_cur = lh_conn.cursor()
            bills = _fetch_netsuite_candidates(lh_cur, entity_ids, "netsuite_vendorbill")
            credits = _fetch_netsuite_candidates(lh_cur, entity_ids, "netsuite_vendorcredit")
            netsuite_by_table = {"netsuite_vendorbill": bills, "netsuite_vendorcredit": credits}

            # Keystone-only, confirmed live 2026-09-22: the same vendor
            # reconstructs its credit tranid differently per statement/
            # location with no way to predict which convention a given
            # one uses (Z1451096 -> CMZ1451096, TS247490 -> CM-TS247490,
            # ME288615 -> ME288615 verbatim, and there are more Keystone
            # locations than these three known ones). Rather than
            # enumerating every location's convention as a config row,
            # fuzzy substring matching (_match_credit()) finds the right
            # tranid without needing to know the convention in advance --
            # every one of the three known cases is a substring of its
            # own correct tranid already. Scoped to this vendor only:
            # every other vendor's credit matching is already validated
            # with exact/case-insensitive matching this session, and nothing
            # else has shown Keystone's "many unpredictable conventions"
            # problem.
            keystone_credit_candidates = None
            if vendor_id == "KEYSTONE_AUTOMOTIVE_INDUSTRIES":
                keystone_credit_candidates = _fetch_netsuite_credit_candidates(lh_cur, entity_ids)

            if vendor_uses_shapes:
                items = [(shape, _shape_target(shape)) for shape in _build_invoice_shapes(lines).values()]
            else:
                items = [
                    (l, _line_target(l)) for l in lines if l.get("invoice_number")
                ]

            for item, (stmt_amount, table) in items:
                inv = item["invoice_number"]
                ro = item["ro_number"]
                orig_inv = item.get("document_number")
                statement_total += stmt_amount or 0.0

                if table == "netsuite_vendorcredit":
                    inv = _apply_ordinal_suffix(inv, item.get("invoice_number_ref"))

                if table == "netsuite_vendorcredit" and keystone_credit_candidates is not None:
                    netsuite_total, candidate_count = _match_credit(
                        inv.lower(), stmt_amount, keystone_credit_candidates
                    )
                    if netsuite_total is None:
                        reason = "Possible Duplicate in NetSuite" if candidate_count > 1 else "Not Found in NetSuite"
                        _write_exception(
                            wh_cur, statement_id, vendor_id, shop, shop_owner, inv,
                            ro, stmt_amount, None, reason, now,
                            original_invoice_number=orig_inv,
                        )
                        exception_count += 1
                    elif _amounts_tie_out(stmt_amount, netsuite_total):
                        _write_match(
                            wh_cur, statement_id, vendor_id, shop, inv,
                            ro, stmt_amount, netsuite_total, now,
                            original_invoice_number=orig_inv,
                        )
                        matched_count += 1
                        erp_total += netsuite_total
                    else:
                        _write_exception(
                            wh_cur, statement_id, vendor_id, shop, shop_owner, inv,
                            ro, stmt_amount, netsuite_total, "Amount Mismatch", now,
                            original_invoice_number=orig_inv,
                        )
                        exception_count += 1
                        erp_total += netsuite_total
                    continue

                candidates = netsuite_by_table.get(table, {}).get(inv.lower(), []) if table else []
                netsuite_total, is_exact = _best_candidate(candidates, stmt_amount)

                if netsuite_total is None and table == "netsuite_vendorcredit":
                    # RH Long-confirmed 2026-09-22: its own standalone-credit
                    # tranid convention isn't consistent even across its own
                    # accounts -- Hudson posts 'CM<invoice>' (CM491604 exact),
                    # Holyoke posts the raw invoice with no prefix at all
                    # (488643 exact). Rather than guess which convention a
                    # given account uses ahead of time (see
                    # vendor_line_selection.py's
                    # _reclassify_payment_rows_by_po_reference()), try the raw
                    # tranid first (above) and only retry with a 'CM' prefix
                    # here if that missed -- exact-string-keyed either way, so
                    # this can't produce a false match for any other vendor.
                    cm_candidates = netsuite_by_table.get(table, {}).get(f"cm{inv.lower()}", [])
                    cm_total, cm_is_exact = _best_candidate(cm_candidates, stmt_amount)
                    if cm_total is not None:
                        netsuite_total, is_exact = cm_total, cm_is_exact

                if netsuite_total is None:
                    _write_exception(
                        wh_cur, statement_id, vendor_id, shop, shop_owner, inv,
                        ro, stmt_amount, None, "Not Found in NetSuite", now,
                        original_invoice_number=orig_inv,
                    )
                    exception_count += 1
                elif is_exact:
                    _write_match(
                        wh_cur, statement_id, vendor_id, shop, inv,
                        ro, stmt_amount, netsuite_total, now,
                        original_invoice_number=orig_inv,
                    )
                    matched_count += 1
                    erp_total += netsuite_total
                else:
                    # No candidate for this tranid tied out exactly --
                    # netsuite_total here is the single CLOSEST candidate
                    # (see _best_candidate()), surfaced so the UI can show
                    # what the nearest real NetSuite record actually was,
                    # not just "not found."
                    _write_exception(
                        wh_cur, statement_id, vendor_id, shop, shop_owner, inv,
                        ro, stmt_amount, netsuite_total, "Amount Mismatch", now,
                        original_invoice_number=orig_inv,
                    )
                    exception_count += 1
                    erp_total += netsuite_total

        total_count = matched_count + exception_count
        match_pct = round(100.0 * matched_count / total_count, 1) if total_count else 0.0
        overall_status = (
            "RECONCILED" if exception_count == 0
            else "MINOR_EXCEPTIONS" if exception_count <= 3
            else "EXCEPTIONS_PRESENT"
        )
        _write_summary(
            wh_cur, statement_id, vendor_id, vendor_name, shop, header.get("statement_period"),
            statement_total, erp_total, total_count, matched_count, exception_count,
            match_pct, overall_status, now,
        )

        wh_conn.commit()

        return {
            "matched": matched_count, "exceptions": exception_count,
            "vendor_resolved": entity_ids is not None,
        }

    except Exception:
        logger.exception("Fabric NetSuite matching failed for statement_id=%s (non-fatal)", statement_id)
        if wh_conn is not None:
            try:
                wh_conn.rollback()
            except Exception:
                pass
        return {"error": "matching_failed"}


def fetch_netsuite_record_for_invoice(vendor_id: str, vendor_name: str, invoice_number: str) -> dict:
    """Looks up the full NetSuite record for one invoice, for display on
    the Exceptions review page's "Amount Mismatch" detail (see
    web/routers/exceptions.py) -- a display-only lookup, not part of the
    matching run itself. Checks bronze.netsuite_vendorbill first
    (tranid = invoice_number, scoped to this vendor's resolved
    entity_ids -- same resolution _fetch_netsuite_candidates() uses
    during matching); if nothing there, falls back to
    bronze.netsuite_vendorcredit. Returns the row as a plain dict (every
    raw column, unmodified -- no code-to-label translation, since this
    app has no authoritative mapping for NetSuite's internal status/
    location/posting-period lookup lists) plus a "_source_table" key
    saying which table it came from. Returns None if genuinely not found
    in either table, Fabric isn't configured, or the vendor's entity_ids
    couldn't be resolved. Best-effort, same as the rest of this module:
    never raises -- a display-only lookup failing should never break the
    review page itself."""
    if not _fabric_configured() or not invoice_number:
        return None
    try:
        entity_ids = resolve_entity_ids(vendor_id, vendor_name)
        if not entity_ids:
            return None

        conn = get_lakehouse_connection()
        try:
            cur = conn.cursor()
            placeholders = ",".join("?" * len(entity_ids))
            for table in ("netsuite_vendorbill", "netsuite_vendorcredit"):
                cur.execute(
                    f"SELECT * FROM bronze.{table} WHERE tranid = ? AND entity IN ({placeholders})",
                    [invoice_number] + entity_ids,
                )
                row = cur.fetchone()
                if row:
                    cols = [c[0] for c in cur.description]
                    record = dict(zip(cols, row))
                    record["_source_table"] = table
                    return record
            return None
        finally:
            conn.close()
    except Exception:
        logger.exception(
            "NetSuite record lookup failed for vendor_id=%s invoice_number=%s",
            vendor_id, invoice_number,
        )
        return None


def _write_match(cur, statement_id, vendor_id, shop, invoice_number, ro_number,
                  stmt_amount, erp_amount, now, original_invoice_number=None):
    cur.execute(
        """
        INSERT INTO silver.recon_matched_invoices (
            match_id, vendor_id, shop, invoice_number, original_invoice_number, ro_number,
            statement_amount, erp_amount, match_level, match_status,
            statement_id, match_timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [str(uuid.uuid4()), vendor_id, shop, invoice_number, original_invoice_number, ro_number,
         stmt_amount, erp_amount, 1, "MATCHED", statement_id, now],
    )


def _write_exception(cur, statement_id, vendor_id, shop, shop_owner, invoice_number,
                      ro_number, stmt_amount, erp_amount, reason, now, original_invoice_number=None):
    cur.execute(
        """
        INSERT INTO silver.recon_exceptions (
            exception_id, vendor_id, shop, invoice_number, original_invoice_number, ro_number,
            statement_amount, erp_amount, match_status, exception_reason,
            exception_status, statement_id, date_raised, shop_owner
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [str(uuid.uuid4()), vendor_id, shop, invoice_number, original_invoice_number, ro_number,
         stmt_amount, erp_amount, "EXCEPTION", reason, "OPEN", statement_id, now, shop_owner],
    )


def _write_summary(cur, statement_id, vendor_id, vendor_name, shop, statement_period,
                    statement_total, erp_total, total_count, matched_count,
                    exception_count, match_pct, overall_status, now):
    # is_latest_version = 1 always -- there's no version-tracking equivalent
    # for this pipeline yet (see dbt/README.md's known gaps: silver.statement
    # has no version_number/previous_statement_id either). Every recon_summary
    # row from this pipeline is therefore "the latest" by construction, but
    # the UI's queries (web/queries.py) explicitly filter on
    # is_latest_version = 1 (matching the old gold_reconciliation_summary
    # convention) -- leaving this NULL would make the row invisible there.
    cur.execute(
        """
        INSERT INTO silver.recon_summary (
            summary_id, vendor_id, vendor_name, shop, statement_period, statement_id,
            statement_total, erp_total, difference, total_invoice_count, matched_count,
            exception_count, match_percentage, overall_status, reconciliation_timestamp,
            version_number, is_latest_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [str(uuid.uuid4()), vendor_id, vendor_name, shop, statement_period, statement_id,
         statement_total, erp_total, statement_total - erp_total, total_count, matched_count,
         exception_count, match_pct, overall_status, now, 1, 1],
    )
