"""Copies statements' location from Azure SQL into Fabric (bronze.raw_statement,
then silver.statement), in bulk, for statements whose location was changed in
Azure SQL only: the old rows scripts/backfill_shop_locations.py mapped, the
ones that took the shop of their matched bills before the pipeline did this
itself (scripts/fill_location_from_invoices.py), or any the live copy missed.

It reads every statement's location from Azure SQL and every silver.statement
row once, and lists the statements where they differ. --apply then merges them
into bronze (one Delta MERGE for all of them, retried on a concurrent-write conflict) and updates silver, bronze
first, so silver never holds a location bronze lacks. A statement is changed
only if silver differs from Azure SQL, so re-running is safe and continues where
a stopped or failed run left off. A statement not yet in silver is left alone
(its build reads bronze). Dry run by default: lists, changes nothing.

Which Fabric it changes is the one the FABRIC_ settings in .env name; it says
so first. The Azure SQL side is whatever AZURE_SQL_SERVER names (else the local
SQLite file).

Run:  python scripts/sync_locations_to_fabric.py            (dry run)
      python scripts/sync_locations_to_fabric.py --apply
      python scripts/sync_locations_to_fabric.py --only invoice_match [--apply]
"""
import os
import sys
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from src.lakehouse import fabric_location  # noqa: E402
from src.lakehouse.connection import execute_query  # noqa: E402


def statements_with_source(source: str) -> list:
    rows = execute_query("SELECT DISTINCT statement_id FROM document_intake_log "
                         "WHERE statement_id IS NOT NULL AND billing_location_source = ?", [source])
    return [row["statement_id"] for row in rows]


def print_report(plan: dict) -> None:
    print(f"{len(plan)} statements differ in silver.statement")
    shops = Counter(values["billing_location"] for values in plan.values())
    for shop, n in shops.most_common(10):
        print(f"  {n:5d}  -> {shop!r}")
    if len(shops) > 10:
        print(f"  ... and {len(shops) - 10} more locations")


def main():
    args = sys.argv[1:]
    print(f"Fabric workspace: {os.environ.get('FABRIC_WORKSPACE_ID') or '(not set)'}")
    if not os.environ.get("FABRIC_WORKSPACE_ID"):
        sys.exit("FABRIC_ settings are not set in .env.")
    only = statements_with_source(args[args.index("--only") + 1]) if "--only" in args else None
    plan = fabric_location.plan_sync(only)
    print_report(plan)
    if "--apply" not in args:
        print("\nDry run -- nothing changed. Re-run with --apply to copy them to Fabric (bronze, then silver).")
        return
    result = fabric_location.sync_many(plan)
    print(f"\nDone: bronze {result['bronze']}, silver {result['silver']}.")


if __name__ == "__main__":
    main()
