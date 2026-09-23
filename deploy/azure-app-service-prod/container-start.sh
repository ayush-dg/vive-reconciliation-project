#!/bin/sh
# Startup script for the Azure App Service prod deployment
# (deploy/azure-app-service-prod/). Same reasoning as the dev/demo
# variant's container-start.sh: App Service's Linux custom-container
# "Startup Command" field does naive whitespace tokenization with no
# quote-awareness, so a compound `cmd1 && cmd2` string can't be passed
# through it directly. Invoking this script as a single token
# (`sh /app/deploy/azure-app-service-prod/container-start.sh` in
# terraform's app_command_line) sidesteps that.

# AZURE_SQL_SERVER is always set here (this config always provisions Azure
# SQL). If FABRIC_SQLDB_ENDPOINT is empty (Fabric not yet wired in), the 3
# Fabric-cutover tables (extraction_cache, document_intake_log,
# validation_document_review_queue) fall back to local SQLite inside the
# container -- see get_fabric_connection() in
# src/lakehouse/connection.py -- which needs its own schema created, or
# every query against those 3 tables fails with "no such table". Forcing
# AZURE_SQL_SERVER empty for just this one invocation routes
# 00_setup_lakehouse_schema.py at that local SQLite file specifically,
# without letting its SQLite-only migrations/*.sql DDL anywhere near the
# real Azure SQL database.
if [ -z "$FABRIC_SQLDB_ENDPOINT" ]; then
    AZURE_SQL_SERVER= python notebooks/00_setup_lakehouse_schema.py
fi

# src/lakehouse/azure_sql_migrations.py is the dedicated Azure SQL schema
# creator -- safe to re-run, every CREATE TABLE/INDEX/COLUMN is
# individually guarded against sys.tables/sys.indexes/sys.columns.
python -m src.lakehouse.azure_sql_migrations

# exec so uvicorn replaces this shell as PID 1 instead of running as a
# child of it -- correct signal handling for restarts/stop.
exec python -m uvicorn web.app:app --host 0.0.0.0 --port 8000
