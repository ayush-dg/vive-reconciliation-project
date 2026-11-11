-- 029_add_statement_completion_log.sql
--
-- "Mark statement complete" (2026-11-11): every time a reviewer marks a
-- statement complete (action 'completed') or un-marks it ('reopened') on its
-- Exceptions review page, with who and when. A statement's current state is
-- its newest row (web/statement_completion.py).
-- (Azure SQL: src/lakehouse/azure_sql_migrations.py, TABLES["statement_completion_log"].)

CREATE TABLE IF NOT EXISTS statement_completion_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id TEXT NOT NULL,
    action TEXT NOT NULL,
    done_by TEXT NOT NULL,
    done_at TEXT NOT NULL,
    note TEXT
);
