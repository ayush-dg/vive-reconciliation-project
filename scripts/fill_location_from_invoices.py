"""Gives the statements that name/alias/street/city could not place a shop from
their matched NetSuite bills (src/validation/invoice_location.py).

For every statement in document_intake_log whose billing_location_source is
ambiguous, conflict or unmapped, it looks at the NetSuite location of the bills
and credits the statement is matched to (the recon table). When they all sit at
one location that is a VIVE shop, the statement gets that shop and the source
"invoice_match"; billing_location_extracted keeps what extraction returned. A
statement with no matched bill, or bills at several locations, is left alone.
New statements get this automatically after matching; this is for the ones
already there.

Which database it changes is the one the app reads: Azure SQL when
AZURE_SQL_SERVER is set in .env, else the local SQLite file. It says which
before doing anything.

Dry run by default: prints what would change and writes nothing. --apply
writes, after saving every changed row's old values to the backup CSV
(--backup PATH, default fill_location_from_invoices_backup.csv). --undo PATH
puts those old values back. Re-running --apply only touches rows that are
still ambiguous, conflict or unmapped.

Run:  python scripts/fill_location_from_invoices.py                      (dry run)
      python scripts/fill_location_from_invoices.py --apply
      python scripts/fill_location_from_invoices.py --undo fill_location_from_invoices_backup.csv
"""
import csv
import os
import sys
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from src.lakehouse.connection import execute_query  # noqa: E402
from src.validation.invoice_location import (  # noqa: E402
    FALLBACK_SOURCES, LOCATION_VALUE_COLUMNS, bill_locations, invoice_values, shop_for, write_values)

DEFAULT_BACKUP = "fill_location_from_invoices_backup.csv"
BACKUP_COLUMNS = ("id", "statement_id") + LOCATION_VALUE_COLUMNS


def fallback_rows() -> list:
    placeholders = ", ".join("?" for _ in FALLBACK_SOURCES)
    return execute_query(
        "SELECT id, statement_id, billing_location, billing_location_source, billing_location_extracted, "
        "shop_phone, shop_city, shop_state, shop_or_entity FROM document_intake_log "
        f"WHERE billing_location_source IN ({placeholders}) AND statement_id IS NOT NULL",
        list(FALLBACK_SOURCES))


def plan_updates(rows: list, locations: dict) -> tuple:
    """([{"id", "statement_id", "old", "new"}], Counter of why the rest stay)."""
    plan, left = [], Counter()
    for row in rows:
        codes = locations.get(row["statement_id"], set())
        if not codes:
            left["no matched bill"] += 1
        elif len(codes) > 1:
            left["bills at several locations"] += 1
        else:
            shop = shop_for(codes)
            if shop is None:
                left["bill location is not a VIVE shop"] += 1
            else:
                plan.append({"id": row["id"], "statement_id": row["statement_id"], "old": row,
                             "new": invoice_values(shop, row)})
    return plan, left


def write_backup(path: str, plan: list) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(BACKUP_COLUMNS)
        for item in plan:
            old = item["old"]
            writer.writerow([old.get(c) if old.get(c) is not None else "" for c in BACKUP_COLUMNS])


def undo_from_backup(path: str) -> int:
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        write_values(int(row["id"]), {c: row[c] or None for c in LOCATION_VALUE_COLUMNS})
    return len(rows)


def print_report(rows: list, plan: list, left: Counter) -> None:
    print(f"\n{len(rows)} statements with no shop (ambiguous / conflict / unmapped): "
          f"{len(plan)} would take their matched bills' shop, {len(rows) - len(plan)} stay as they are")
    for reason, n in left.most_common():
        print(f"  stays: {reason}: {n}")
    print("\nBy the source they have now:")
    for source, n in Counter(item["old"]["billing_location_source"] for item in plan).most_common():
        print(f"  {source}: {n}")
    shown = Counter((item["old"].get("billing_location"), item["new"]["billing_location"]) for item in plan)
    print("\nMost common changes (old billing_location -> shop):")
    for (old, new), n in shown.most_common(15):
        print(f"  {n:4d}  {old!r} -> {new!r}")


def backend() -> str:
    return "Azure SQL (AZURE_SQL_SERVER)" if os.environ.get("AZURE_SQL_SERVER") else "local SQLite file"


def main():
    args = sys.argv[1:]
    backup = args[args.index("--backup") + 1] if "--backup" in args else DEFAULT_BACKUP
    print(f"Database: {backend()}")
    if "--undo" in args:
        path = args[args.index("--undo") + 1]
        print(f"Restored {undo_from_backup(path)} rows from {path}")
        return
    rows = fallback_rows()
    plan, left = plan_updates(rows, bill_locations())
    print_report(rows, plan, left)
    if "--apply" not in args:
        print(f"\nDry run -- nothing changed. Re-run with --apply to write (the old values are saved to {backup} first).")
        return
    write_backup(backup, plan)
    for item in plan:
        write_values(item["id"], item["new"])
    print(f"\nUpdated {len(plan)} rows. Old values saved to {backup}; undo with --undo {backup}")


if __name__ == "__main__":
    main()
