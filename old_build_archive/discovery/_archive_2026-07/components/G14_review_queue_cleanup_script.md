## G14 — review-queue cleanup script
ID: M-041
Layer: infra
Source file: check_queue.py

**Module** — review-queue cleanup script
**ID** — M-041
**Layer** — infra
**Primary Responsibility** — Meets the BCE-009 module-worthiness bar (a real `DELETE`/`SELECT` against the live database via `connection.py`, not an assertion against a modeled module). Ad hoc dev utility: deletes stale `validation_document_review_queue` rows for one specific hardcoded test filename (`Very_Dirty_Scanned_Reconciliation.pdf`).

**Inputs** — None (no CLI args; the target filename is a hardcoded string literal in the script).

**Outputs** — Deletes matching rows from `validation_document_review_queue`; prints the deletion confirmation and remaining row count.

**Public Interface** — None (script-only, no functions defined).

**Error Behaviour** — None — a DB error would raise uncaught, printing a traceback.

**Known Fragility** — The target filename is hardcoded — this script is single-purpose and would need editing to target a different file. Not a reusable cleanup utility as written.

**Change Impact** — None — standalone script, not imported anywhere, no other module depends on it.

**Callers** — none (invoked directly, `python check_queue.py`)
**Calls** — M-033 (`execute_sql`, `execute_query`)
**Integration Points Used** — IP-008 (Lakehouse database)
