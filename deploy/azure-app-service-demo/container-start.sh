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
# Migration step: the SQLite file starts genuinely empty on every fresh
# container -- get_connection() only creates the file, it never runs
# migrations/*.sql against it. notebooks/00_setup_lakehouse_schema.py is
# explicitly safe to re-run (already-applied migrations are skipped), so
# running it on every boot is a no-op after the first. The DB itself is
# ephemeral here (no Azure Files mount -- SQLite's WAL journal mode needs
# POSIX locking semantics that mount doesn't reliably provide, see
# README.md's "Where the database lives"), so this really does run fresh
# every restart/redeploy.
python notebooks/00_setup_lakehouse_schema.py

# exec so uvicorn replaces this shell as PID 1 instead of running as a
# child of it -- correct signal handling for restarts/stop.
exec python -m uvicorn web.app:app --host 0.0.0.0 --port 8000
