-- 027_add_cleared_disposition.sql
--
-- "Clear exception" on the review page (2026-11-04): a person clears an
-- exception that needs no further action, with a note. It is recorded like
-- every other resolution, as disposition_status 'CLEARED'; "Undo" reopens it
-- with a 'PENDING' row, the same way undoing a manual match does.
--
-- SQLite cannot change a CHECK constraint in place, so the table is rebuilt
-- with the same columns and its rows copied across. (Azure SQL: the constraint
-- is replaced in src/lakehouse/azure_sql_migrations.py, CHECK_CONSTRAINTS.)
-- Numbered 027: 026 is the user activity log (feature/user-activity-log).

CREATE TABLE exception_dispositions_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exception_id TEXT NOT NULL,
    statement_id TEXT NOT NULL,
    vendor_name TEXT NOT NULL,
    invoice_number TEXT NOT NULL,
    reason_code TEXT,
    disposition_status TEXT NOT NULL CHECK(disposition_status IN
        ('ACCEPTED', 'DISPUTED', 'DUPLICATE', 'WRITE_OFF', 'PENDING', 'CLEARED')),
    disposition_notes TEXT,
    disposed_by TEXT,
    disposed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO exception_dispositions_new (id, exception_id, statement_id, vendor_name, invoice_number,
    reason_code, disposition_status, disposition_notes, disposed_by, disposed_at, created_at)
SELECT id, exception_id, statement_id, vendor_name, invoice_number,
    reason_code, disposition_status, disposition_notes, disposed_by, disposed_at, created_at
FROM exception_dispositions;

DROP TABLE exception_dispositions;

ALTER TABLE exception_dispositions_new RENAME TO exception_dispositions;

CREATE INDEX IF NOT EXISTS idx_exception_dispositions_lookup
    ON exception_dispositions(vendor_name, invoice_number, reason_code);
