## B14 — Batches Router
ID: M-014
Layer: serving
Source file: `web/routers/batches.py`

**Module** — Batches Router
**ID** — M-014
**Layer** — serving
**Primary Responsibility** — Batch summary list (Event Grid-delivered batches, newest first, plus manually-uploaded jobs grouped by date) and per-batch detail view.

**Inputs** — `batch_id` path param on the detail route.

**Outputs** — Renders `batches.html`/`batch_detail.html`.

**Public Interface** — `GET /batches`, `GET /batches/{batch_id}` — no functions called by other modules.

**Error Behaviour** — Detail route redirects to `/batches` (303) if `get_batch_detail()` finds no matching batch.

**Known Fragility** — `get_all_batches()` (M-003) issues one query per distinct `statement_id` across every batch to compute invoice/exception totals — cost scales with total historical job count, no pagination on this page.

**Change Impact** — Isolated to the batches pages; depends entirely on M-003's batch aggregation logic being correct.

**Callers** — M-001 (router registration)
**Calls** — M-002 (`render`, `require_login`, `sidebar_context`), M-003 (`get_all_batches`, `get_manual_uploads`, `get_batch_detail`)
**Integration Points Used** — none
