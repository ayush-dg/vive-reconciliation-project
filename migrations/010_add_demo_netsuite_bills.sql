-- 010_add_demo_netsuite_bills.sql
-- Demo table holding real NetSuite "Bill" rows (AsTech vendor) for the
-- live-ERP-matching demo. Loaded from sample_data/netsuite_exports/ via
-- scripts/load_netsuite_export.py, not by application code. Deliberately
-- separate from the Bronze/Silver/Gold lakehouse schema — this is a flat,
-- denormalized staging table for Pass 1 (exact invoice number) matching
-- only, per the ENH decision to matching against real NetSuite data for
-- this vendor while P3/live integration remain out of scope.

CREATE TABLE IF NOT EXISTS demo_netsuite_bills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT NOT NULL,
    amount REAL NOT NULL,
    bill_date TEXT,
    source_file TEXT,
    loaded_at TEXT NOT NULL
);
