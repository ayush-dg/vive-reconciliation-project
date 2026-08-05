## G10 — Review Queue Cleanup Script
ID: M-046
Layer: infra
Source file: `check_queue.py`

**Module** — Review Queue Cleanup Script
**ID** — M-046
**Layer** — infra
**Primary Responsibility** — Ad hoc dev utility: deletes stale `validation_document_review_queue` rows for one hardcoded test filename (`Very_Dirty_Scanned_Reconciliation.pdf`) and prints the remaining row count.

**Inputs** — None (filename is a hardcoded literal in the script).

**Outputs** — A real DELETE against `validation_document_review_queue`, executed via the Fabric path.

**Public Interface** — None exported; script-only, root-level ad hoc tool, not part of any package.

**Error Behaviour** — None — a direct, unguarded `execute_sql_fabric()` call; any failure propagates as an uncaught exception.

**Known Fragility** — Hardcodes a specific test filename directly in the script body — not parameterized, not safe to run unmodified against a different cleanup target. A developer copying this pattern for a different filename must edit the source, not pass an argument — an easy way to accidentally delete the wrong rows if the literal isn't updated carefully.

**Change Impact** — None beyond the specific rows it targets — a one-off cleanup tool, not invoked by any other module or automated process.

**Callers** — none (developer-invoked)
**Calls** — M-037 (`execute_sql_fabric`, `execute_query_fabric`)
**Integration Points Used** — IP-011 (Fabric Warehouse, via M-037)
