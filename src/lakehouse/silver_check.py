"""Post-Silver sanity check (added 2026-10-08): did this statement's lines
actually come through the field mapping?

Why: a statement whose extracted field names match none of the vendor's
vendor_field_mapping rows (e.g. a scanned PDF read by Claude, whose
verbatim headers differ from the parser's names) built 0 Silver lines,
matched nothing, and showed 0 / 0 / 0 as "Reconciled" -- prod
STMT-3C9D4BBB (Fred Beans, 71 Bronze lines) and STMT-EC5E296A (Astech,
135). A mapping that misses only SOME fields is quieter still: lines
without an invoice number or amount just become exceptions.

scripts/run_full_pipeline.py calls check_silver_lines() after the Silver
build and before matching; a problem fails the job (web/worker.py, via
SILVER_CHECK_MARKER) instead of writing a misleading summary.

Thresholds, measured 2026-10-08 over all 656 dev statements with Silver
lines: only one (Faulkner STMT-88E6559F, 2 lines, no invoice number or
amount on either) would fail. Small statements are allowed a minority of
lines without an invoice number (payment / balance rows).

Best-effort: any error while checking returns None (no problem reported),
so the check itself can never fail a job.
"""
import logging

logger = logging.getLogger(__name__)

# Statements with at least this many Silver lines must have an invoice
# number and an amount on at least MIN_SHARE of them.
MIN_LINES_FOR_SHARE = 5
MIN_SHARE = 0.5

# Bronze fields that never map, listed separately from real unmapped ones.
_IGNORED_FIELDS = {"confidence", "page"}


def _unmapped_fields(statement_id: str, vendor_id: str) -> list:
    from src.extraction.ai_raw_row_aliases import _mapped_names
    from src.lakehouse.fabric_sql import get_lakehouse_connection
    cur = get_lakehouse_connection().cursor()
    cur.execute("SELECT DISTINCT raw_field_name FROM bronze.unnested_statement_fields WHERE statement_id = ?",
                [statement_id])
    mapped = _mapped_names().get(vendor_id, set())
    return sorted(r[0] for r in cur.fetchall() if r[0] not in mapped and r[0] not in _IGNORED_FIELDS)


def describe_problem(lines: int, with_invoice: int, with_amount: int, bronze_lines: int):
    """The problem text for these counts, or None when they look fine."""
    if lines == 0:
        if bronze_lines:
            return f"No lines read: {bronze_lines} lines were extracted but none matched {{vendor}}'s field mapping"
        return None
    if with_invoice == 0 or with_amount == 0 or (
            lines >= MIN_LINES_FOR_SHARE
            and (with_invoice < MIN_SHARE * lines or with_amount < MIN_SHARE * lines)):
        return (f"Field mapping incomplete: of {lines} lines, {with_invoice} have an invoice number "
                f"and {with_amount} an amount ({{vendor}})")
    return None


def check_silver_lines(statement_id: str):
    """Returns a one-line problem description, or None when the lines look
    fine (or the check couldn't run)."""
    try:
        from src.lakehouse.fabric_sql import get_lakehouse_connection, get_warehouse_connection
        w = get_warehouse_connection().cursor()
        w.execute("SELECT TOP 1 vendor_id FROM silver.statement WHERE statement_id = ?", [statement_id])
        row = w.fetchone()
        vendor_id = row[0] if row else None
        w.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN invoice_number IS NOT NULL AND invoice_number <> '' THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN charge_amount IS NOT NULL OR payment_amount IS NOT NULL "
            "OR amount_remaining IS NOT NULL THEN 1 ELSE 0 END) "
            "FROM silver.statement_line WHERE statement_id = ?",
            [statement_id],
        )
        lines, with_invoice, with_amount = (int(v or 0) for v in w.fetchone())
        bronze_lines = 0
        if lines == 0:
            lc = get_lakehouse_connection().cursor()
            lc.execute("SELECT COUNT(*) FROM bronze.unnested_statement_lines WHERE statement_id = ?", [statement_id])
            bronze_lines = int(lc.fetchone()[0] or 0)
        problem = describe_problem(lines, with_invoice, with_amount, bronze_lines)
        if not problem:
            return None
        problem = problem.replace("{vendor}", vendor_id or "the vendor")
        try:
            unmapped = _unmapped_fields(statement_id, vendor_id)
        except Exception:
            unmapped = []
        if unmapped:
            problem += ". Unmapped fields: " + ", ".join(repr(f) for f in unmapped[:12])
        return problem
    except Exception:
        logger.exception("Silver line check failed for %s (ignored)", statement_id)
        return None
