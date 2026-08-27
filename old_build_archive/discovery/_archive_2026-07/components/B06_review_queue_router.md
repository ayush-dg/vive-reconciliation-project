## B06 — review_queue router
ID: M-006
Layer: serving
Source file: web/routers/review_queue.py

**Module** — review_queue router
**ID** — M-006
**Layer** — serving
**Primary Responsibility** — Separate review flow for `validation_document_review_queue` rows (extraction-incomplete/duplicate rows never written to `gold_exceptions` by intake itself).

**Inputs**
- `GET /review-queue` — no inputs.
- `GET /review-queue/{vendor_name:path}` — path param `vendor_name`, query param `selected: str = None`.
- `POST /review-queue/{vendor_name:path}/action` — path param `vendor_name`, form fields `review_id`, `action` (both required).

**Outputs** — Renders `review_queue_vendors.html`/`review_queue_review.html`. `POST .../action` calls `queries.action_review_item()`, which updates `validation_document_review_queue.review_status` to `APPROVED` or `FLAGGED`, and — only when flagging — additionally inserts a new `gold_exceptions` row (`exception_reason` = `DUPLICATE_RECORD` if the item's `rejection_category` was `DUPLICATE_RECORD`, else `EXTRACTION_INCOMPLETE`; see M-011's `action_review_item()`).

**Public Interface**
- `review_queue_vendors(request, user) -> TemplateResponse` — `GET /review-queue`
- `review_queue_review(vendor_name, request, user, selected=None) -> TemplateResponse` — `GET /review-queue/{vendor_name:path}`
- `review_queue_action(vendor_name, request, user, review_id, action) -> RedirectResponse` — `POST /review-queue/{vendor_name:path}/action`

**Error Behaviour** — No explicit try/except in this module; `queries.action_review_item()` returns silently (`if not item: return`) if the `review_id` doesn't exist, so a stale/invalid `review_id` in a submitted form produces no visible error and no redirect message — the user is redirected back to the vendor page with no feedback that nothing happened.

**Known Fragility**
- `CATEGORY_BADGE` (module-level dict) hardcodes only 2 of the 4 real `rejection_category` values observed possible in code (`MISSING_MANDATORY_FIELD`, `DUPLICATE_RECORD`) — `INVALID_FIELD_TYPE` and `LOW_CONFIDENCE` (both real branches in `notebooks/01_document_intake.py`'s `validate_invoice()`, confirmed in F02, though never yet observed in live data) have no badge styling if they ever occur.
- These rows have no AI-detected `vendor_id`/`vendor_name` (per the module's own docstring, confirmed by source), so `source_file` stands in as the grouping key — the same convention `web/routers/exceptions.py` uses for its "exceptions-only" vendor fallback, but the two groupings are not guaranteed to line up for the same underlying vendor if filenames vary.

**Change Impact** — Tightly coupled to `web/queries.py`'s `action_review_item()` exception-reason mapping logic — a new `rejection_category` value added to intake validation would need a corresponding badge entry here and a decision in `action_review_item()` about how to map it if ever flagged.

**Callers** — none (top-level HTTP entry point)
**Calls** — M-010 (`render`, `require_login`, `sidebar_context`), M-011 (`get_review_queue_vendors`, `get_review_queue_for_vendor`, `get_review_queue_item`, `action_review_item`)
**Integration Points Used** — none directly
