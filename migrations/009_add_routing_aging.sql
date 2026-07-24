-- 009_add_routing_aging.sql
-- Adds exception routing (shop_owner -- see config/shop_owners.json,
-- looked up by vendor_id whenever a new exception is written) and
-- escalation tracking (escalation_status/escalated_at/escalated_by --
-- see web/queries.py's escalate_exception()) to gold_exceptions.
--
-- days_open is deliberately NOT added here. The Azure SQL side implements
-- it as a true computed column (DATEDIFF(day, date_raised, GETUTCDATE())
-- -- see src/lakehouse/azure_sql_migrations.py's COMPUTED_COLUMNS), but
-- SQLite's GENERATED ALWAYS AS columns must be deterministic and cannot
-- reference the current time (datetime('now')/julianday('now') are
-- explicitly disallowed in a SQLite generated-column expression, so this
-- would fail at ALTER TABLE time). The app computes "days open" from
-- date_raised in Python instead (see web/queries.py's _days_since()), so
-- neither backend's application code actually depends on a stored
-- days_open column.

ALTER TABLE gold_exceptions ADD COLUMN shop_owner TEXT;
ALTER TABLE gold_exceptions ADD COLUMN escalation_status TEXT DEFAULT 'NONE';
ALTER TABLE gold_exceptions ADD COLUMN escalated_at TEXT;
ALTER TABLE gold_exceptions ADD COLUMN escalated_by TEXT;
