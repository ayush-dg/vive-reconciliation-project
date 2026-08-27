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

Three matching rules (generalized from a validated Bald Hill query, same
logic, applied to silver.statement_line's generic columns instead of that
vendor's raw column names):
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

Explicitly NOT implemented yet: the original query's "variants_on_statement"
guard (skipping invoice_numbers that have multiple revisions on the
statement) -- the generic extraction schema has no field capturing "this
line is a revision of that other invoice", so this can't be computed today.
Decided with the user 2026-08-26 to ship without it and revisit only if it
causes real false-positive matches in practice.

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
    unresolved rather than guessing which one to use)."""
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


def _shape_target(shape: dict) -> tuple:
    """Returns (statement_amount, netsuite_table_or_None) for one invoice
    shape, applying rules A/B/C -- decides WHICH NetSuite table (bill vs
    credit memo) this shape should be checked against, before any lookup
    happens. netsuite_table is None for an ineligible shape (multiple
    charge lines for one invoice number, a charge+credit pair that
    doesn't even internally net to zero, etc.) -- statement_amount is
    still returned where available so an exception row isn't left with no
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
        return stmt_amount, None

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
            credits = _fetch_netsuite_transactions(lh_cur, entity_ids, "netsuite_vendorcredit")
            netsuite_by_table = {"netsuite_vendorbill": bills, "netsuite_vendorcredit": credits}

            shapes = _build_invoice_shapes(lines)
            for shape in shapes.values():
                stmt_amount, table = _shape_target(shape)
                statement_total += stmt_amount or 0.0
                netsuite_total = netsuite_by_table.get(table, {}).get(shape["invoice_number"]) if table else None

                if netsuite_total is None:
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
