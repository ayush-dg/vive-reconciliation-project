"""Adds the statement's customer-location columns to silver.statement in the
Fabric Warehouse.

The default Silver build (src/lakehouse/silver_build.py, SILVER_BUILD_MODE
unset) appends rows only into columns the Warehouse table already has -- a
model column missing from the table is dropped with a warning, never added --
so dbt's on_schema_change does not apply there and these have to be added by
hand, the same way original_invoice_number was added to the recon tables (see
scripts/create_fabric_recon_schema.py).

The columns (src/validation/shop_list.py LOCATION_COLUMNS) hold what
extraction returned for the customer location, the mapped VIVE shop name, and
that shop's phone / city / state. They are read from bronze.raw_statement, so
run scripts/create_fabric_lakehouse_schema.py FIRST (it adds the same columns
to the Lakehouse table) and let the SQL endpoint pick them up -- the dbt model
change that selects them fails the Silver build for every statement if
bronze.raw_statement does not have them yet.

Report only by default: lists which of the columns silver.statement has and
which it is missing. Nothing is changed. --apply adds the missing ones
(nullable; existing columns and rows untouched). Safe to re-run: a column that
exists is skipped.

Run:  python scripts/add_shop_columns_warehouse.py            (report only)
      python scripts/add_shop_columns_warehouse.py --apply    (add what is missing)
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from src.lakehouse.fabric_sql import get_warehouse_connection  # noqa: E402
from src.validation.shop_list import LOCATION_COLUMNS  # noqa: E402

SCHEMA, TABLE = "silver", "statement"
COLUMN_TYPES = {
    "billing_location_extracted": "VARCHAR(500)",
    "billing_location": "VARCHAR(500)",
    "shop_phone": "VARCHAR(50)",
    "shop_city": "VARCHAR(200)",
    "shop_state": "VARCHAR(50)",
}


def existing_columns(cur) -> set:
    cur.execute(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
        [SCHEMA, TABLE])
    return {row[0].lower() for row in cur.fetchall()}


def add_missing(conn, cur, existing: set) -> list:
    added = []
    for column in LOCATION_COLUMNS:
        if column not in existing:
            cur.execute(f"ALTER TABLE {SCHEMA}.{TABLE} ADD {column} {COLUMN_TYPES[column]}")
            added.append(column)
    conn.commit()
    return added


def main():
    conn = get_warehouse_connection()
    try:
        cur = conn.cursor()
        existing = existing_columns(cur)
        if not existing:
            sys.exit(f"{SCHEMA}.{TABLE} not found in the Warehouse.")
        print(f"{SCHEMA}.{TABLE}: {len(existing)} columns")
        print(f"  location columns present: {[c for c in LOCATION_COLUMNS if c in existing] or 'none'}")
        print(f"  location columns missing: {[c for c in LOCATION_COLUMNS if c not in existing] or 'none'}")
        if "--apply" not in sys.argv:
            print("\nReport only -- nothing changed. Re-run with --apply to add the missing columns.")
            return
        print(f"\nAdded: {add_missing(conn, cur, existing) or 'nothing (all present)'}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
