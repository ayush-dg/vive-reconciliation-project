## B11 — Review Queue Router
ID: M-011
Layer: serving
Source file: `web/routers/review_queue.py`

**Module** — Review Queue Router
**ID** — M-011
**Layer** — serving
**Primary Responsibility** — Vendor (by source_file) overview and per-file review of `validation_document_review_queue` rows; approving or flagging an item.

**Inputs** — `vendor_name` (actually a `source_file` value, URL-encoded) path param; `review_id`/`action` form fields.

**Outputs** — Renders `review_queue_vendors.html`/`review_queue_review.html`; writes via M-003's `action_review_item()`.

**Public Interface** — `GET /review-queue`, `GET /review-queue/{vendor_name:path}`, `POST /review-queue/{vendor_name:path}/action` — no functions called by other modules.

**Error Behaviour** — None explicit; relies on default FastAPI error handling.

**Known Fragility** — `vendor_name` in this router's routes is actually a `source_file` value, not a real vendor name — these rows have no AI-detected `vendor_id`/`vendor_name` at all (confirmed in the module docstring). A future engineer conflating this router's `vendor_name` with M-008's real vendor names would misread the URL structure.

**Change Impact** — `action_review_item()` (M-003) can raise a new `gold_exceptions` row on "flag," which then surfaces in M-008's exception views — a change here has a downstream effect on the exceptions page, not just this one.

**Callers** — M-001 (router registration)
**Calls** — M-002 (`render`, `require_login`, `sidebar_context`), M-003 (`get_review_queue_vendors`, `get_review_queue_for_vendor`, `action_review_item`)
**Integration Points Used** — none
