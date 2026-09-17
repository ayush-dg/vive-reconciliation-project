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
import uuid
from datetime import datetime, timezone

from src.lakehouse.fabric_sql import get_lakehouse_connection, get_warehouse_connection
from src.matching.netsuite_vendor_resolver import resolve_entity_ids
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
        "SELECT statement_line_id, invoice_number, line_type, charge_amount, "
        "payment_amount, ro_number, line_date FROM silver.statement_line WHERE statement_id = ?",
        [statement_id],
    )
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _fetch_netsuite_transactions(cur, entity_ids: list, table: str) -> dict:
    """Returns {tranid: total} from bronze.<table> (netsuite_vendorbill or
    netsuite_vendorcredit -- same shape, tranid/entity/total/voided).
    Excludes voided rows and any tranid with more than one differing
    non-voided total among these entities (ambiguous -- treated as
    unresolved rather than guessing which one to use). Used for BILLS
    only -- see _fetch_netsuite_credit_candidates() for why credits need a
    different lookup shape entirely, not just this same dict."""
    if not entity_ids:
        return {}
    placeholders = ",".join("?" * len(entity_ids))
    cur.execute(
        f"SELECT tranid, total FROM bronze.{table} "
        f"WHERE entity IN ({placeholders}) AND voided = 'F' AND tranid IS NOT NULL",
        entity_ids,
    )
    by_tranid = {}
    ambiguous = set()
    for tranid, total in cur.fetchall():
        try:
            total_f = float(total)
        except (TypeError, ValueError):
            continue
        if tranid in by_tranid and by_tranid[tranid] != total_f:
            ambiguous.add(tranid)
        by_tranid[tranid] = total_f
    for tranid in ambiguous:
        logger.warning("Multiple differing NetSuite %s totals for tranid=%s -- excluding from matching", table, tranid)
        del by_tranid[tranid]
    return by_tranid


def _fetch_netsuite_credit_candidates(cur, entity_ids: list) -> list:
    """Returns [(tranid, total)] from bronze.netsuite_vendorcredit for
    these entities, excluding voided rows and deduplicating identical
    (tranid, total) pairs. Deliberately a flat list consumed via substring
    search (_match_credit()), not an exact-match dict like
    _fetch_netsuite_transactions() -- a statement credit's real NetSuite
    tranid can take wildly inconsistent forms relative to the statement's
    own invoice_number (CMA435584, CMA435584-1, CM-9435584X1,
    cm3000r0004355846ac all logically the same credit) -- an exact-match
    assumption (e.g. tranid == 'CM' + invoice_number) silently misses real
    matches that don't survive contact with real data. Applies to every
    vendor's credit-typed shapes uniformly, not just the ones that
    surfaced this.

    The (tranid, total) dedup matters more here than it did for
    _fetch_netsuite_transactions()'s dict (which dedupes for free by
    construction): a NetSuite record synced into Bronze on more than one
    run (identical tranid+total, different _run_id) produces two
    IDENTICAL entries in this flat list, which _match_credit() then can't
    tell apart from two genuinely different candidates -- it would see 2
    matches, both tying out to the same amount, and report "Possible
    Duplicate" instead of a clean match. Deduping here (not just relying
    on the caller) keeps that distinction correct: a real duplicate (2+
    DIFFERENT totals under a related tranid) still surfaces as a genuine
    ambiguity; a same-value Bronze-sync artifact no longer masquerades as
    one."""
    if not entity_ids:
        return []
    placeholders = ",".join("?" * len(entity_ids))
    cur.execute(
        f"SELECT DISTINCT tranid, total FROM bronze.netsuite_vendorcredit "
        f"WHERE entity IN ({placeholders}) AND voided = 'F' AND tranid IS NOT NULL",
        entity_ids,
    )
    candidates = []
    for tranid, total in cur.fetchall():
        try:
            candidates.append((tranid, float(total)))
        except (TypeError, ValueError):
            continue
    return candidates


def _match_credit(invoice_number: str, statement_amount, credit_candidates: list) -> tuple:
    """Searches credit_candidates for tranids CONTAINING invoice_number as
    a substring (see _fetch_netsuite_credit_candidates() for why this
    isn't an exact match). Returns (netsuite_total_or_None,
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
    """Groups statement lines by invoice_number. charge_amount already
    carries the sign (positive for CHARGE lines, negative for CREDIT lines
    -- see dbt/vive_recon/models/silver/statement_line.sql), so credit
    magnitude is abs(charge_amount) on a CREDIT-typed line. A PAYMENT line
    with no invoice_number (e.g. a payment-received memo with no document
    reference) is dropped here (`if not inv: continue`) -- only PAYMENT
    lines that DO reference a real invoice_number reach a shape, which in
    every real case checked so far means "credit memo", not "payment
    notice" -- see the module docstring's Rule B."""
    shapes = {}
    for line in lines:
        inv = line["invoice_number"]
        if not inv:
            continue
        shape = shapes.setdefault(inv, {
            "invoice_number": inv, "lines": [], "charge_line_count": 0,
            "credit_line_count": 0, "payment_line_count": 0,
            "charge_amt": None, "credit_amt": None, "payment_amt": None,
            "ro_number": None, "line_date": None,
        })
        shape["lines"].append(line)
        shape["ro_number"] = shape["ro_number"] or line.get("ro_number")
        shape["line_date"] = shape["line_date"] or line.get("line_date")
        if line["line_type"] == "CHARGE":
            shape["charge_line_count"] += 1
            shape["charge_amt"] = line["charge_amount"]
        elif line["line_type"] == "CREDIT":
            shape["credit_line_count"] += 1
            shape["credit_amt"] = abs(line["charge_amount"]) if line["charge_amount"] is not None else None
        elif line["line_type"] == "PAYMENT":
            shape["payment_line_count"] += 1
            shape["payment_amt"] = line["payment_amount"]
    return shapes


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
        charge_amount = earliest_credit["charge_amount"]
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
        entity_ids = resolve_entity_ids(vendor_id, vendor_name)

        matched_count = 0
        exception_count = 0
        statement_total = 0.0
        erp_total = 0.0

        if not entity_ids:
            shapes = _build_invoice_shapes(lines)
            for shape in shapes.values():
                stmt_amount = shape["charge_amt"] if shape["charge_line_count"] else shape["credit_amt"]
                _write_exception(
                    wh_cur, statement_id, vendor_id, shop, shop_owner, shape["invoice_number"],
                    shape["ro_number"], stmt_amount, None, "Vendor Not Resolved in NetSuite", now,
                )
                exception_count += 1
                statement_total += stmt_amount or 0.0
        else:
            lh_conn = get_lakehouse_connection()
            lh_cur = lh_conn.cursor()
            bills = _fetch_netsuite_transactions(lh_cur, entity_ids, "netsuite_vendorbill")
            credit_candidates = _fetch_netsuite_credit_candidates(lh_cur, entity_ids)

            shapes = _build_invoice_shapes(lines)
            for shape in shapes.values():
                stmt_amount, table = _shape_target(shape)
                statement_total += stmt_amount or 0.0

                candidate_count = 0
                if table == "netsuite_vendorbill":
                    netsuite_total = bills.get(shape["invoice_number"])
                elif table == "netsuite_vendorcredit":
                    netsuite_total, candidate_count = _match_credit(
                        shape["invoice_number"], stmt_amount, credit_candidates
                    )
                else:
                    netsuite_total = None

                if candidate_count >= 2 and netsuite_total is None:
                    # 2+ NetSuite credit records share this invoice_number as
                    # a substring and none of them ties out cleanly -- a
                    # genuine ambiguity (see _match_credit()), not a plain
                    # not-found.
                    _write_exception(
                        wh_cur, statement_id, vendor_id, shop, shop_owner, shape["invoice_number"],
                        shape["ro_number"], stmt_amount, None, "Possible Duplicate in NetSuite", now,
                    )
                    exception_count += 1
                elif netsuite_total is None:
                    _write_exception(
                        wh_cur, statement_id, vendor_id, shop, shop_owner, shape["invoice_number"],
                        shape["ro_number"], stmt_amount, None, "Not Found in NetSuite", now,
                    )
                    exception_count += 1
                elif _amounts_tie_out(stmt_amount, netsuite_total):
                    _write_match(
                        wh_cur, statement_id, vendor_id, shop, shape["invoice_number"],
                        shape["ro_number"], stmt_amount, netsuite_total, now,
                    )
                    matched_count += 1
                    erp_total += netsuite_total
                else:
                    _write_exception(
                        wh_cur, statement_id, vendor_id, shop, shop_owner, shape["invoice_number"],
                        shape["ro_number"], stmt_amount, netsuite_total, "Amount Mismatch", now,
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
    entity_ids -- same resolution _fetch_netsuite_transactions() uses
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
                  stmt_amount, erp_amount, now):
    cur.execute(
        """
        INSERT INTO silver.recon_matched_invoices (
            match_id, vendor_id, shop, invoice_number, ro_number,
            statement_amount, erp_amount, match_level, match_status,
            statement_id, match_timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [str(uuid.uuid4()), vendor_id, shop, invoice_number, ro_number,
         stmt_amount, erp_amount, 1, "MATCHED", statement_id, now],
    )


def _write_exception(cur, statement_id, vendor_id, shop, shop_owner, invoice_number,
                      ro_number, stmt_amount, erp_amount, reason, now):
    cur.execute(
        """
        INSERT INTO silver.recon_exceptions (
            exception_id, vendor_id, shop, invoice_number, ro_number,
            statement_amount, erp_amount, match_status, exception_reason,
            exception_status, statement_id, date_raised, shop_owner
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [str(uuid.uuid4()), vendor_id, shop, invoice_number, ro_number,
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
