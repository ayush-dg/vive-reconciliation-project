-- 002_exception_dispositions.sql
-- Phase 2: Disposition model + human audit log.
--
-- Records what the AP team decided about a given exception, so recurring
-- exceptions can be recognized across statement runs instead of being
-- re-flagged fresh every month. The lookup key is (vendor_name,
-- invoice_number, reason_code) rather than statement_id, since statement_id
-- changes every period even when the same underlying exception recurs.
-- exception_id/statement_id link back to the specific gold_exceptions row
-- that was disposed (by convention, not an enforced FOREIGN KEY -- see
-- migrations/001_initial_schema.sql, which follows the same pattern
-- throughout). disposed_by/disposed_at double as the human-action audit
-- trail per docs/VIVE_Implementation_Context.md Phase 2 -- no separate
-- audit table needed.

CREATE TABLE IF NOT EXISTS exception_dispositions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exception_id TEXT NOT NULL,
    statement_id TEXT NOT NULL,
    vendor_name TEXT NOT NULL,
    invoice_number TEXT NOT NULL,
    reason_code TEXT,
    disposition_status TEXT NOT NULL CHECK(disposition_status IN
        ('ACCEPTED', 'DISPUTED', 'DUPLICATE', 'WRITE_OFF', 'PENDING')),
    disposition_notes TEXT,
    disposed_by TEXT,
    disposed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Per docs/VIVE_Implementation_Context.md Section 8: index the
-- (vendor_name, invoice_number, reason_code) combination used to look up
-- whether an exception was already resolved on a prior run.
CREATE INDEX IF NOT EXISTS idx_exception_dispositions_lookup
    ON exception_dispositions(vendor_name, invoice_number, reason_code);
