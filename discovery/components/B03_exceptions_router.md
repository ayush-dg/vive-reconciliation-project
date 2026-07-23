## B03 — exceptions router
ID: M-003
Layer: serving
Source file: web/routers/exceptions.py

**Module** — exceptions router
**ID** — M-003
**Layer** — serving
**Primary Responsibility** — Exceptions-by-vendor overview and per-vendor review/resolution flow.

**Inputs**
- `GET /exceptions` — no inputs.
- `GET /exceptions/{vendor_name:path}` — path param `vendor_name` (URL-decoded), query params `filter: str = "all"`, `selected: str = None`.
- `POST /exceptions/{vendor_name:path}` — path param `vendor_name`, form fields `exception_id`, `statement_id`, `invoice_number`, `reason_code`, `action`, `note` (optional), `filter` (optional, default `"all"`) — all required except `note`/`filter`.

**Outputs**
- Renders `exceptions_vendors.html` (vendor cards with open-exception counts) or `exceptions_review.html` (per-vendor exception list + detail panel).
- `POST` writes one row to `exception_dispositions` and updates `gold_exceptions.exception_status = 'RESOLVED'` (via `queries.resolve_exception()`), then redirects back to the same vendor's review page (preserving the `filter` query param).

**Public Interface**
- `exceptions_vendors(request, user) -> TemplateResponse` — `GET /exceptions`
- `exceptions_review(vendor_name, request, user, filter="all", selected=None) -> TemplateResponse` — `GET /exceptions/{vendor_name:path}`
- `exceptions_action(vendor_name, request, user, exception_id, statement_id, invoice_number, reason_code, action, note="", filter="all") -> RedirectResponse` — `POST /exceptions/{vendor_name:path}`

**Error Behaviour** — A vendor with no `gold_reconciliation_summary` row falls back to `queries.get_exceptions_only_vendor()`; if that also returns nothing, renders `exceptions_review.html` with `not_found=True` and HTTP 404 rather than raising. No explicit try/except around `queries.resolve_exception()` in the POST handler — a DB error there propagates as an unhandled 500, losing the disposition silently from the user's perspective (no partial-write concern since `resolve_exception()`'s two statements aren't wrapped in an explicit transaction — see M-011 Known Fragility).

**Known Fragility**
- `REASON_BADGE` (module-level dict) hardcodes exactly 4 `exception_reason` labels (`Invoice Missing`, `Amount Mismatch`, `EXTRACTION_INCOMPLETE`, `DUPLICATE_RECORD`) — matches all values actually observed/reachable per F02, so currently complete, but any new `exception_reason` value introduced elsewhere (e.g. in `src/matching/engine.py` or `action_review_item()`) would render with no badge styling unless this dict is updated in lockstep — no code path enforces that consistency.
- The vendor-lookup fallback chain (`get_vendor_latest_statement` → `get_exceptions_only_vendor`) depends on `_vendor_name_from_source_file()`'s filename-derived title-casing matching exactly — a vendor name containing punctuation or unusual casing could fail to match its own orphaned exceptions.

**Change Impact** — Any change to `gold_exceptions`'s schema or to `exception_dispositions`'s required columns must be mirrored in `resolve_exception()` (M-011) and this router's form fields together.

**Callers** — none (top-level HTTP entry point)
**Calls** — M-010 (`render`, `require_login`, `sidebar_context`), M-011 (`get_vendor_summaries`, `get_vendor_latest_statement`, `get_exceptions_only_vendor`, `get_open_exceptions`, `get_open_exceptions_for_source_file`, `get_exception_counts`, `get_exception_counts_for_source_file`, `resolve_exception`)
**Integration Points Used** — none directly
