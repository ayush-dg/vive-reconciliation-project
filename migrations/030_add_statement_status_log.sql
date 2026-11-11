-- 030_add_statement_status_log.sql
--
-- Follow-up status (2026-11-11): each time a reviewer sets a statement's
-- status on its Exceptions review page -- requested_copy ("Requested copy
-- from vendor"), sent_to_shop, waiting_to_post, or '' (cleared) -- with who
-- and when. The current status is the newest row (web/statement_completion.py).
-- Separate from statement_completion_log: a statement can have both.
-- (Azure SQL: src/lakehouse/azure_sql_migrations.py, TABLES["statement_status_log"].)

CREATE TABLE IF NOT EXISTS statement_status_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id TEXT NOT NULL,
    status TEXT NOT NULL,
    set_by TEXT NOT NULL,
    set_at TEXT NOT NULL
);
