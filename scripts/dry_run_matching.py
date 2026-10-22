"""
scripts/dry_run_matching.py

Read-only comparison of NetSuite matching with and without the generic line
handling (MATCHING_GENERIC_LINES, src/matching/fabric_matching.py): runs
run_fabric_matching(dry_run=True) twice per statement and reports every
exception and match that would change. Writes nothing to Fabric, Azure SQL
or NetSuite.

    python scripts/dry_run_matching.py --env .env.prod [--statement STMT-...] [--out report.csv]

Without --statement it covers every statement in silver.recon_summary.
"""

import argparse
import csv
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _key_exception(row):
    # silver.recon_exceptions columns: id, vendor, shop, invoice, original, ro,
    # statement_amount, erp_amount, type, reason, status, statement, time, owner
    return (row[3], row[9], None if row[6] is None else round(float(row[6]), 2))


def _key_match(row):
    return (row[3], None if row[6] is None else round(float(row[6]), 2))


def _run(fm, statement_id, generic):
    os.environ["MATCHING_GENERIC_LINES"] = "true" if generic else "false"
    result = fm.run_fabric_matching(statement_id, dry_run=True)
    if "would_write" not in result:
        return None
    written = result["would_write"]
    return {
        "exceptions": Counter(_key_exception(r) for r in written["silver.recon_exceptions"]),
        "matches": Counter(_key_match(r) for r in written["silver.recon_matched_invoices"]),
        "vendor_id": result["vendor_id"],
        "set_aside": result["set_aside"],
    }


def _cache_reads(fm):
    """One Fabric connection each for the whole run, and NetSuite candidates
    fetched once per vendor -- read-only either way."""
    wh, lh, candidates = fm.get_warehouse_connection(), fm.get_lakehouse_connection(), {}

    class _Shared:
        def __init__(self, conn):
            self._conn = conn

        def cursor(self):
            return self._conn.cursor()

        def commit(self):
            raise RuntimeError("dry run must not commit")

        def rollback(self):
            self._conn.rollback()

        def close(self):
            pass

    original_fetch = fm._fetch_netsuite_candidates

    def cached_fetch(cur, entity_ids, table):
        key = (tuple(entity_ids or ()), table)
        if key not in candidates:
            candidates[key] = original_fetch(cur, entity_ids, table)
        return candidates[key]

    fm.get_warehouse_connection = lambda: _Shared(wh)
    fm.get_lakehouse_connection = lambda: _Shared(lh)
    fm._fetch_netsuite_candidates = cached_fetch
    return wh


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--env", default=".env.prod")
    parser.add_argument("--statement", action="append")
    parser.add_argument("--out", default="dry_run_matching.csv")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(args.env, override=True)
    os.environ.pop("AZURE_BLOB_DROPZONE_CONNECTION_STRING", None)
    from src.matching import fabric_matching as fm

    wh = _cache_reads(fm)
    statement_ids = args.statement
    if not statement_ids:
        cur = wh.cursor()
        cur.execute("SELECT DISTINCT statement_id FROM silver.recon_summary")
        statement_ids = sorted(r[0] for r in cur.fetchall())

    rows, totals = [], Counter()
    for n, sid in enumerate(statement_ids, 1):
        old, new = _run(fm, sid, False), _run(fm, sid, True)
        if old is None or new is None:
            print(f"[{n}/{len(statement_ids)}] {sid}: skipped (no Silver statement)")
            continue
        gone = old["exceptions"] - new["exceptions"]
        added = new["exceptions"] - old["exceptions"]
        new_matches = new["matches"] - old["matches"]
        lost_matches = old["matches"] - new["matches"]
        totals["statements"] += 1
        totals["old_exceptions"] += sum(old["exceptions"].values())
        totals["new_exceptions"] += sum(new["exceptions"].values())
        totals["old_matches"] += sum(old["matches"].values())
        totals["new_matches"] += sum(new["matches"].values())
        if gone or added or new_matches or lost_matches:
            totals["changed_statements"] += 1
        print(f"[{n}/{len(statement_ids)}] {sid} {new['vendor_id']}: exceptions "
              f"{sum(old['exceptions'].values())} -> {sum(new['exceptions'].values())}, matches "
              f"{sum(old['matches'].values())} -> {sum(new['matches'].values())}")
        notes = {(inv, amount): note for _, inv, note, amount in new["set_aside"]}
        matched_now = {(inv, amount) for inv, amount in new["matches"]}
        for (inv, reason, amount), count in gone.items():
            why = ("now matched in NetSuite" if (inv, amount) in matched_now
                   else notes.get((inv, amount), ""))
            rows.append([sid, new["vendor_id"], "exception removed", inv, reason, amount, count, why])
        for (inv, reason, amount), count in added.items():
            rows.append([sid, new["vendor_id"], "exception added", inv, reason, amount, count, ""])
        for (inv, amount), count in new_matches.items():
            rows.append([sid, new["vendor_id"], "new match", inv, "", amount, count, ""])
        for (inv, amount), count in lost_matches.items():
            rows.append([sid, new["vendor_id"], "match lost", inv, "", amount, count, ""])

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["statement_id", "vendor_id", "change", "invoice_number", "reason",
                         "statement_amount", "count", "why"])
        writer.writerows(rows)
    print("\nTOTALS", dict(totals))
    print("changes by kind", dict(Counter(r[2] for r in rows)))
    print(f"report: {args.out}")


if __name__ == "__main__":
    main()
