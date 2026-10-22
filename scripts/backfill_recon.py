"""
scripts/backfill_recon.py

Fills the recon table (one row per statement line, src/lakehouse/recon_table.py)
for statements reconciled before it existed, WITHOUT re-matching them:

  1. run_fabric_matching(dry_run=True, keep_run_time=True) decides every line
     exactly as a real run would and returns the recon rows it would write --
     nothing is written to Fabric;
  2. those results must equal the statement's STORED matches and exceptions
     (same invoice, reason and amount) -- otherwise the statement was matched
     with older rules and is skipped, never guessed;
  3. each exception row is linked to the stored exception (its real id), and
     decisions already made are applied (Accepted / Rejected, who, when);
  4. the rows are inserted with recon_table.replace_auto_rows() -- only for
     statements that have no auto rows yet; manual matches are kept.

Read-only unless --apply. Every run writes a CSV report; --undo REPORT deletes
the auto rows of the statements that report backfilled.

    python scripts/backfill_recon.py --env .env.dev --since 2026-10-13 [--apply]
    python scripts/backfill_recon.py --env .env.dev --statement STMT-... [--apply]
    python scripts/backfill_recon.py --env .env.dev --undo backfill_recon_report.csv
"""

import argparse
import csv
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPORT_COLUMNS = ["statement_id", "vendor_id", "action", "detail", "rows", "matched", "exceptions",
                  "resolved", "set_aside"]


def _amount(value):
    return None if value is None else round(abs(float(value)), 2)


def _exception_key(invoice, reason, amount):
    return (str(invoice or "").lower(), reason, _amount(amount))


FALLBACK_RULE = "backfill: paired with the stored result"
FALLBACK_NOTE = "not checked against NetSuite on its own (backfilled from the stored results)"


def _same_invoice(line_inv, result_inv, exact_only=False) -> bool:
    """The same number, or (unless exact_only) the matcher's '-N' ordinal
    form of it (web/statement_processing.py pairs lines the same way)."""
    if not line_inv or not result_inv:
        return False
    a, b = str(line_inv).lower(), str(result_inv).lower()
    return a == b or (not exact_only and b.startswith(a + "-"))


def paired_rows(fm, recon_table, statement_id, stored_matches, stored_exceptions):
    """The fallback (--fallback) for a statement whose stored results matching
    no longer reproduces (NetSuite changed since): every Silver line paired
    with its stored match/exception by invoice and amount -- exactly as
    Statement Processing shows it -- so recon agrees with the Exceptions page.
    A line no stored result pairs with shares its invoice's result when it has
    one, else is set aside with FALLBACK_NOTE. No NetSuite record ids (the
    stored results don't have them)."""
    cur = fm.get_warehouse_connection().cursor()
    header = fm._fetch_statement(cur, statement_id)
    lines = fm._fetch_lines(cur, statement_id)
    run_time = fm._previous_run_time(cur, statement_id)
    results = [("match", m) for m in stored_matches] + [("exception", e) for e in stored_exceptions]
    used, own = set(), {}
    # Exact invoice number first; the '-N' ordinal form only for lines still
    # unpaired -- else '563967E' takes '563967E-1''s result (Quirk, 2026-10-22).
    for exact_only in (True, False):
        for line in lines:
            amount = recon_table.line_amount(line)
            if amount is None or line["statement_line_id"] in own:
                continue
            for rid, (kind, result) in enumerate(results):
                stmt = result.get("statement_amount")
                if (rid not in used and stmt is not None and abs(abs(float(stmt)) - abs(amount)) < 0.005
                        and _same_invoice(line.get("invoice_number"), result.get("invoice_number"), exact_only)):
                    used.add(rid)
                    own[line["statement_line_id"]] = (kind, result)
                    break
    by_invoice = {}
    for kind, result in results:
        by_invoice.setdefault(str(result.get("invoice_number") or "").lower(), (kind, result))

    per_line = {}
    for line in lines:
        pair = own.get(line["statement_line_id"]) or by_invoice.get(str(line.get("invoice_number") or "").lower())
        if not pair:
            line["_recon_note"] = FALLBACK_NOTE
            continue
        kind, result = pair
        erp = result.get("erp_amount")
        per_line[line["statement_line_id"]] = {
            "invoice_number": result.get("invoice_number"),
            "status": (recon_table.STATUS_MATCHED if kind == "match"
                       else recon_table.status_for_reason(result.get("exception_reason"))),
            "statement_amount": result.get("statement_amount"),
            "exception_id": result.get("exception_id") if kind == "exception" else None,
            "exception_reason": result.get("exception_reason") if kind == "exception" else None,
            "netsuite": {"amount": erp} if erp is not None else None,
            "match_rule": FALLBACK_RULE,
        }
    statement = {"statement_id": statement_id, "vendor_id": (header or {}).get("vendor_id"),
                 "vendor_name": (header or {}).get("vendor_name_raw"), "statement_period": None}
    return recon_table.build_auto_rows(statement, lines, per_line, run_time)


def plan_statement(fm, recon_table, queries, statement_id, fallback=False):
    """(rows_to_insert, report_row) for one statement. rows_to_insert is None
    when the statement is skipped -- the report row says why. fallback=True
    pairs a statement whose stored results differ (paired_rows()) instead of
    skipping it."""
    report = {"statement_id": statement_id, "vendor_id": "", "action": "skipped", "detail": "",
              "rows": 0, "matched": 0, "exceptions": 0, "resolved": 0, "set_aside": 0}

    existing = recon_table.rows_for_statement(statement_id)
    if any(r.get("source") == recon_table.SOURCE_AUTO for r in existing):
        report["detail"] = "already has recon rows"
        return None, report

    dry = fm.run_fabric_matching(statement_id, dry_run=True, keep_run_time=True)
    if "recon_rows" not in dry:
        report["detail"] = f"matching could not run: {dry.get('reason') or dry.get('error')}"
        return None, report
    report["vendor_id"] = dry["vendor_id"]

    stored_matches = queries.recon_query(
        "SELECT invoice_number, statement_amount, erp_amount FROM silver.recon_matched_invoices "
        "WHERE statement_id = ?",
        [statement_id])
    stored_exceptions = queries.recon_query(
        "SELECT exception_id, invoice_number, exception_reason, statement_amount, erp_amount, exception_status "
        "FROM silver.recon_exceptions WHERE statement_id = ?", [statement_id])

    # 2. The stored results must be what matching gives today.
    written = dry["would_write"]
    dry_matches = Counter((str(r[3] or "").lower(), _amount(r[6])) for r in written["silver.recon_matched_invoices"])
    old_matches = Counter((str(r["invoice_number"] or "").lower(), _amount(r["statement_amount"])) for r in stored_matches)
    dry_exc = Counter(_exception_key(r[3], r[9], r[6]) for r in written["silver.recon_exceptions"])
    old_exc = Counter(_exception_key(r["invoice_number"], r["exception_reason"], r["statement_amount"])
                      for r in stored_exceptions)
    if dry_matches != old_matches or dry_exc != old_exc:
        detail = (f"stored results differ from matching today (matches {sum(old_matches.values())} vs "
                  f"{sum(dry_matches.values())}, exceptions {sum(old_exc.values())} vs {sum(dry_exc.values())})")
        if not fallback:
            report["detail"] = detail + " -- re-match, or --fallback"
            return None, report
        rows = paired_rows(fm, recon_table, statement_id, stored_matches, stored_exceptions)
        id_map = {e["exception_id"]: e for e in stored_exceptions}
        report["detail"] = "fallback (paired with stored results): " + detail
    else:
        # 3. Link each dry-run exception id to the stored exception.
        stored_by_key = defaultdict(list)
        for e in stored_exceptions:
            stored_by_key[_exception_key(e["invoice_number"], e["exception_reason"], e["statement_amount"])].append(e)
        id_map = {}
        for r in written["silver.recon_exceptions"]:
            id_map[r[0]] = stored_by_key[_exception_key(r[3], r[9], r[6])].pop(0)
        rows = dry["recon_rows"]

    decisions = {}
    for d in queries.execute_query(
            "SELECT exception_id, disposition_status, disposed_by, disposed_at, disposition_notes "
            "FROM exception_dispositions WHERE statement_id = ? ORDER BY disposed_at, id", [statement_id]):
        decisions[d["exception_id"]] = d  # latest wins

    for row in rows:
        stored = id_map.get(row.get("exception_id"))
        if not stored:
            continue
        row["exception_id"] = stored["exception_id"]
        decision = decisions.get(stored["exception_id"])
        status = recon_table.STATUS_BY_DISPOSITION.get((decision or {}).get("disposition_status"))
        if status and stored.get("exception_status") != "OPEN":
            row.update(status=status, matched_by=decision.get("disposed_by"),
                       matched_at=decision.get("disposed_at"), note=decision.get("disposition_notes"))
            report["resolved"] += 1

    counts = Counter(r["status"] for r in rows)
    report.update(action="backfill", rows=len(rows), matched=counts.get(recon_table.STATUS_MATCHED, 0),
                  exceptions=sum(1 for r in rows if r.get("exception_id")),
                  set_aside=sum(1 for r in rows if r["status"] == recon_table.STATUS_NOT_RECONCILED and r.get("note")))
    return rows, report


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--env", required=True)
    parser.add_argument("--since", help="statements reconciled on/after this date (YYYY-MM-DD)")
    parser.add_argument("--statement", action="append")
    parser.add_argument("--apply", action="store_true", help="insert the rows (default: report only)")
    parser.add_argument("--fallback", action="store_true",
                        help="pair lines with the stored results when matching no longer reproduces them")
    parser.add_argument("--report", default="backfill_recon_report.csv")
    parser.add_argument("--undo", metavar="REPORT", help="delete the auto rows this report backfilled")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(args.env, override=True)
    os.environ.pop("AZURE_BLOB_DROPZONE_CONNECTION_STRING", None)
    from src.lakehouse import recon_table
    from src.lakehouse.connection import execute_sql
    from src.matching import fabric_matching as fm
    from web import queries
    from scripts.dry_run_matching import _cache_reads

    if args.undo:
        done = [r["statement_id"] for r in csv.DictReader(open(args.undo, encoding="utf-8"))
                if r["action"] == "backfilled"]
        for sid in done:
            execute_sql("DELETE FROM recon WHERE statement_id = ? AND source = ?", [sid, recon_table.SOURCE_AUTO])
        print(f"removed the backfilled rows of {len(done)} statements")
        return

    wh = _cache_reads(fm)
    statement_ids = args.statement
    if not statement_ids:
        if not args.since:
            parser.error("--since or --statement is required")
        cur = wh.cursor()
        cur.execute("SELECT DISTINCT statement_id FROM silver.recon_summary WHERE reconciliation_timestamp >= ?",
                    [args.since])
        statement_ids = sorted(r[0] for r in cur.fetchall())

    reports = []
    for n, sid in enumerate(statement_ids, 1):
        try:
            rows, report = plan_statement(fm, recon_table, queries, sid, fallback=args.fallback)
            if rows is not None and args.apply:
                recon_table.replace_auto_rows(sid, rows)
                report["action"] = "backfilled"
        except Exception as exc:
            rows, report = None, {"statement_id": sid, "action": "error", "detail": f"{type(exc).__name__}: {exc}"}
        reports.append(report)
        print(f"[{n}/{len(statement_ids)}] {sid} {report.get('vendor_id', '')}: {report['action']} "
              f"{report.get('detail') or ''} rows={report.get('rows', 0)} matched={report.get('matched', 0)} "
              f"exceptions={report.get('exceptions', 0)} resolved={report.get('resolved', 0)} "
              f"set_aside={report.get('set_aside', 0)}", flush=True)

    with open(args.report, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REPORT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(reports)
    print("\nSUMMARY", dict(Counter(r["action"] for r in reports)), "| report:", args.report)
    if not args.apply:
        print("REPORT ONLY -- nothing written. Add --apply to insert.")


if __name__ == "__main__":
    main()
