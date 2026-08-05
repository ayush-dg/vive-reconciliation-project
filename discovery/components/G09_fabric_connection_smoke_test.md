## G09 — Fabric Warehouse Connection Smoke Test
ID: M-045
Layer: infra
Source file: `scripts/test_fabric_connection.py`

**Module** — Fabric Warehouse Connection Smoke Test
**ID** — M-045
**Layer** — infra
**Primary Responsibility** — Standalone, read-only smoke test proving `get_fabric_connection()` can actually reach the real Fabric Warehouse — the first evidence in this codebase of the Fabric cut-over being validated end-to-end, not just implemented.

**Inputs** — Requires `AZURE_SQL_SERVER` to be set (to route past the SQLite fallback) and an existing `az login` session.

**Outputs** — Stdout only: connection confirmation, `SELECT 1` result, and the full `INFORMATION_SCHEMA.TABLES` list actually present in the connected Fabric Warehouse.

**Public Interface** — None exported; script-only.

**Error Behaviour** — No error handling — any connection or query failure propagates as an uncaught exception and traceback; appropriate for a smoke test meant to fail loudly.

**Known Fragility** — Not part of the main test suite (confirmed by its own docstring) — has no CI/automated re-run signal; its "passing" state observed once is not continuously re-verified. Given it queries live `INFORMATION_SCHEMA.TABLES`, a real, actionable follow-up is to compare that output against the three tables this codebase's code assumes exist there (`extraction_cache`, `document_intake_log`, `validation_document_review_queue`) — not done as part of this script itself.

**Change Impact** — None — diagnostic-only.

**Callers** — none (developer-invoked)
**Calls** — M-037 (`get_fabric_connection`)
**Integration Points Used** — IP-011 (Fabric Warehouse)
