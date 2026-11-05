"""Maps the customer location of statements already in document_intake_log
onto VIVE shops (src/validation/location_lookup.py), so the Shop and Location
filters and cards (web/shop_display.py) show one entry per shop for old
statements too.

For every row stored before the mapping existed (billing_location_source NULL,
or one of the old values printed / lookup_table / shop_name_fallback), it runs
the same resolver the intake uses on the row's stored shop_or_entity and
billing_location, and sets billing_location (the shop's NetSuite name),
billing_location_source, billing_location_extracted (the old billing_location),
shop_phone, shop_city and shop_state. Old rows keep no street or phone, so
they map by name, alias and city only; a row that does not map keeps its raw
text and is marked "unmapped".

Which database it changes is the one the app reads: Azure SQL when
AZURE_SQL_SERVER is set in .env, else the local SQLite file. It says which
before doing anything.

Dry run by default: prints what would change and writes nothing to the
database. --apply writes, after saving every row's old values to the backup CSV
(--backup PATH, default backfill_shop_locations_backup.csv). --undo PATH puts
those old values back and clears the new columns for those rows. Re-running
--apply only touches rows that still have an old source.

--redo maps again the rows already marked unmapped, conflict or ambiguous
(from the extracted text kept in billing_location_extracted), after the shop
list, the aliases or the matching rules have changed. It updates only the rows
that now map to a shop; the others are left as they are. A backup made by any
mode can be undone with --undo (a backup from before --redo existed has fewer
columns and clears the extracted text and shop details, as it always did).

Run:  python scripts/backfill_shop_locations.py                      (dry run)
      python scripts/backfill_shop_locations.py --apply
      python scripts/backfill_shop_locations.py --redo [--apply]
      python scripts/backfill_shop_locations.py --undo backfill_shop_locations_backup.csv
"""
import contextlib
import csv
import json
import logging
import os
import sys
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from src.lakehouse.connection import execute_query, execute_sql  # noqa: E402
from src.validation.location_lookup import apply_location, MAPPED_SOURCES  # noqa: E402

# billing_location_source values written before the shop mapping existed.
OLD_SOURCES = ("printed", "lookup_table", "shop_name_fallback")
# Results that left a row without a shop; --redo tries them again.
REDO_SOURCES = ("unmapped", "conflict", "ambiguous")
DEFAULT_BACKUP = "backfill_shop_locations_backup.csv"
NEW_COLUMNS = ("billing_location", "billing_location_source", "billing_location_extracted",
               "shop_phone", "shop_city", "shop_state")
BACKUP_COLUMNS = ("id", "statement_id") + NEW_COLUMNS
_SELECT = ("SELECT id, statement_id, shop_or_entity, billing_location, billing_location_source, "
           "billing_location_extracted, shop_phone, shop_city, shop_state FROM document_intake_log")


def old_rows() -> list:
    placeholders = ", ".join("?" for _ in OLD_SOURCES)
    return execute_query(
        f"{_SELECT} WHERE billing_location_source IS NULL OR billing_location_source IN ({placeholders})",
        list(OLD_SOURCES))


def redo_rows() -> list:
    placeholders = ", ".join("?" for _ in REDO_SOURCES)
    return execute_query(f"{_SELECT} WHERE billing_location_source IN ({placeholders})", list(REDO_SOURCES))


def _shop_names(row: dict) -> list:
    try:
        names = json.loads(row["shop_or_entity"]) if row.get("shop_or_entity") else []
    except (TypeError, ValueError):
        names = []
    return names if isinstance(names, list) else []


def plan_update(row: dict) -> dict:
    """The new column values for one old row."""
    # A row already mapped once keeps its extracted text there; an old row has
    # only billing_location.
    meta = apply_location({"shop_or_entity": _shop_names(row),
                           "billing_location": row.get("billing_location_extracted") or row.get("billing_location")})
    return {column: meta.get(column) for column in NEW_COLUMNS}


def plan_updates(rows: list, only_mapped: bool = False) -> list:
    """One update per row; with `only_mapped`, only for rows that now map to a shop."""
    plan = [{"id": row["id"], "statement_id": row["statement_id"], "old": row, "new": plan_update(row)} for row in rows]
    return [item for item in plan if item["new"]["billing_location_source"] in MAPPED_SOURCES] if only_mapped else plan


def write_backup(path: str, rows: list) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(BACKUP_COLUMNS)
        for row in rows:
            writer.writerow([row.get(column) if row.get(column) is not None else "" for column in BACKUP_COLUMNS])


def apply_updates(plan: list) -> None:
    assignments = ", ".join(f"{column} = ?" for column in NEW_COLUMNS)
    for item in plan:
        execute_sql(f"UPDATE document_intake_log SET {assignments} WHERE id = ?",
                    [item["new"][column] for column in NEW_COLUMNS] + [item["id"]])


def undo_from_backup(path: str) -> int:
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        # A backup from before --redo has only these two columns: the rest were empty.
        values = [row.get(column) or None for column in NEW_COLUMNS]
        execute_sql(f"UPDATE document_intake_log SET {', '.join(f'{c} = ?' for c in NEW_COLUMNS)} WHERE id = ?",
                    values + [int(row["id"])])
    return len(rows)


def print_report(plan: list, label: str = "old rows") -> None:
    by_source = Counter(item["new"]["billing_location_source"] for item in plan)
    mapped = sum(n for source, n in by_source.items() if source in MAPPED_SOURCES)
    print(f"\n{len(plan)} {label}: {mapped} would map to a shop, {len(plan) - mapped} would keep their raw text")
    for source, n in by_source.most_common():
        print(f"  {source}: {n}")
    unmapped = Counter((item["old"].get("shop_or_entity"), item["old"].get("billing_location"))
                       for item in plan if item["new"]["billing_location_source"] not in MAPPED_SOURCES)
    if unmapped:
        print("\nMost common rows that would stay unmapped (shop_or_entity | billing_location):")
        for (shop, location), n in unmapped.most_common(15):
            print(f"  {n:4d}  {shop} | {location}")
    shown = Counter((item["old"].get("billing_location"), item["new"]["billing_location"])
                    for item in plan if item["new"]["billing_location_source"] in MAPPED_SOURCES)
    print("\nMost common mappings (old billing_location -> shop):")
    for (old, new), n in shown.most_common(10):
        print(f"  {n:4d}  {old!r} -> {new!r}")


def backend() -> str:
    return "Azure SQL (AZURE_SQL_SERVER)" if os.environ.get("AZURE_SQL_SERVER") else "local SQLite file"


@contextlib.contextmanager
def resolver_quiet():
    """The resolver logs a warning for every unmapped row; thousands of lines
    would bury the report. Restores the previous level on exit."""
    previous = logging.root.manager.disable
    logging.disable(logging.WARNING)
    try:
        yield
    finally:
        logging.disable(previous)


def main():
    args = sys.argv[1:]
    backup = args[args.index("--backup") + 1] if "--backup" in args else DEFAULT_BACKUP
    print(f"Database: {backend()}")
    if "--undo" in args:
        count = undo_from_backup(args[args.index("--undo") + 1])
        print(f"Restored {count} rows from {args[args.index('--undo') + 1]}")
        return
    redo = "--redo" in args
    with resolver_quiet():
        plan = plan_updates(redo_rows(), only_mapped=True) if redo else plan_updates(old_rows())
    print_report(plan, "rows that were unmapped, in conflict or ambiguous and now map" if redo else "old rows")
    if "--apply" not in args:
        print("\nDry run -- nothing changed. Re-run with --apply to write (the old values are saved to "
              f"{backup} first).")
        return
    write_backup(backup, [item["old"] for item in plan])
    apply_updates(plan)
    print(f"\nUpdated {len(plan)} rows. Old values saved to {backup}; undo with --undo {backup}")
    print("Azure SQL only: copy to Fabric with  python scripts/sync_locations_to_fabric.py --apply")


if __name__ == "__main__":
    main()
