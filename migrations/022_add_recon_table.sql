-- 022_add_recon_table.sql
--
-- recon: one row per statement line with its reconciliation status
-- (src/lakehouse/recon_table.py). The matching run
-- (src/matching/fabric_matching.py) writes the "auto" rows -- replacing only
-- a statement's auto rows on a re-run -- and a person's "Accept as match"
-- writes "manual" rows (Exceptions review page). Accept / Reject on an
-- exception set its lines to Accepted / Rejected.
--
--   status        Matched | Matched manually | Amount mismatch |
--                 Not found in NetSuite | Possible duplicate |
--                 Vendor not resolved | Accepted | Rejected | Not reconciled
--   source        'auto' (matching run) | 'manual' (a person)
--   netsuite_*    the NetSuite bill/credit the line is linked to, if any
--   writeback_*   the NetSuite sandbox write for a manual match
--   netsuite_before  JSON of the NetSuite values before that write (undo)
--   is_active     0 once a manual match is undone (kept as history)

CREATE TABLE IF NOT EXISTS recon (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recon_id TEXT NOT NULL UNIQUE,
    statement_id TEXT NOT NULL,
    vendor_id TEXT,
    vendor_name TEXT,
    statement_period TEXT,
    line_number INTEGER,
    statement_line_id TEXT,
    invoice_number TEXT,
    original_invoice_number TEXT,
    line_date TEXT,
    line_amount REAL,
    status TEXT NOT NULL,
    exception_id TEXT,
    exception_reason TEXT,
    netsuite_record_type TEXT,
    netsuite_internal_id TEXT,
    netsuite_tranid TEXT,
    netsuite_transaction_number TEXT,
    netsuite_amount REAL,
    difference REAL,
    netsuite_entity_id TEXT,
    netsuite_location TEXT,
    source TEXT NOT NULL,
    match_rule TEXT,
    matched_by TEXT,
    matched_at TEXT,
    note TEXT,
    writeback_status TEXT,
    writeback_detail TEXT,
    netsuite_statement_line_id TEXT,
    netsuite_before TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    undone_by TEXT,
    undone_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_recon_statement ON recon(statement_id, is_active);
CREATE INDEX IF NOT EXISTS idx_recon_invoice ON recon(statement_id, invoice_number);
