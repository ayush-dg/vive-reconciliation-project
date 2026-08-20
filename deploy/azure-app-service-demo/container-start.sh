#!/bin/sh
# Startup script for the Azure App Service demo (deploy/azure-app-service-demo/).
#
# Exists because Azure App Service's Linux custom-container "Startup
# Command" field does naive whitespace tokenization with NO quote
# awareness -- there is no way to pass a compound `cmd1 && cmd2` string
# through that field directly (confirmed empirically: both single- and
# double-quoted attempts broke, since quotes are never stripped/respected
# -- see git history / conversation for the diagnostic). Baking the
# compound logic into a script and invoking it as a single-token command
# (`sh /app/deploy/azure-app-service-demo/container-start.sh` in
# terraform's app_command_line) sidesteps the tokenizer entirely: no
# spaces inside either token means nothing gets mis-split.
#
# Not copied into the main Dockerfile/CMD -- this is App-Service-only,
# same reasoning as the app_command_line override itself not touching the
# Dockerfile (local docker-compose dev is unaffected).
#
# Migration step: notebooks/00_setup_lakehouse_schema.py's apply_pending_migrations()
# runs the migrations/*.sql files as literal SQLite DDL (CREATE TABLE IF
# NOT EXISTS, AUTOINCREMENT) -- invalid T-SQL syntax, so it fails outright
# against a real Azure SQL Database, not just when a table already exists.
# src/lakehouse/azure_sql_migrations.py is the dedicated Azure SQL schema
# creator (see its own docstring / RULES.md RULE-13) -- safe to re-run,
# each CREATE TABLE/INDEX/COLUMN is individually guarded against
# sys.tables/sys.indexes/sys.columns. When AZURE_SQL_SERVER isn't set
# (SQLite fallback), the SQLite file starts genuinely empty on every fresh
# container -- get_connection() only creates the file, it never runs
# migrations/*.sql against it -- so 00_setup_lakehouse_schema.py's own
# migration runner is still what's needed there; it's also safe to re-run.
# The SQLite DB itself is ephemeral here (no Azure Files mount -- SQLite's
# WAL journal mode needs POSIX locking semantics that mount doesn't
# reliably provide, see README.md's "Where the database lives"), so that
# path really does run fresh every restart/redeploy.
# The 3 Fabric-cutover tables (extraction_cache, document_intake_log,
# validation_document_review_queue) fall back to local SQLite whenever
# Fabric itself isn't configured (FABRIC_SQLDB_ENDPOINT unset), regardless
# of whether AZURE_SQL_SERVER is set -- see get_fabric_connection()'s own
# docstring. That local SQLite file needs its own schema created too, or
# every query against those 3 tables fails with "no such table" the
# moment AZURE_SQL_SERVER is set without a real Fabric SQL database item
# also configured (this repo's actual state today). Forcing
# AZURE_SQL_SERVER empty for just this one invocation routes
# 00_setup_lakehouse_schema.py at the local SQLite file specifically,
# without letting its SQLite-only migrations/*.sql DDL anywhere near real
# Azure SQL -- that's what the block below is for instead.
if [ -n "$AZURE_SQL_SERVER" ] && [ -z "$FABRIC_SQLDB_ENDPOINT" ]; then
    AZURE_SQL_SERVER= python notebooks/00_setup_lakehouse_schema.py
fi

if [ -n "$AZURE_SQL_SERVER" ]; then
    python -m src.lakehouse.azure_sql_migrations
else
    python notebooks/00_setup_lakehouse_schema.py
fi

# One-time cleanup: stale job f7298ada-6bfb-49ca-9d63-f11676fbfb4c
# (Fred Beans Lee's.pdf, FAILED, manually terminated during troubleshooting
# on 2026-08-19 -- stuck in PROCESSING with no Bronze/Silver written after
# an earlier container restart orphaned it). scripts/remove_job.py is
# idempotent -- a no-op once this row is gone -- so this is safe to leave
# running on every container start rather than needing a follow-up deploy
# to remove it.
python scripts/remove_job.py --job-id f7298ada-6bfb-49ca-9d63-f11676fbfb4c || true

# exec so uvicorn replaces this shell as PID 1 instead of running as a
# child of it -- correct signal handling for restarts/stop.
exec python -m uvicorn web.app:app --host 0.0.0.0 --port 8000
