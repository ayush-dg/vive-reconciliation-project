## B03 — exceptions router
ID: M-003
Layer: serving
Source file: web/routers/exceptions.py
Rewritten: 2026-07-25 scoped BCE refresh (bulk-approve + escalate endpoints and aging/routing fields added 2026-07-24, Steps 8 and 10)

**Module** — exceptions router
**ID** — M-003
**Layer** — serving
**Primary Responsibility** — Exceptions-by-vendor overview and per-vendor review/resolution flow, now also bulk-approval of high-confidence exceptions and single-exception escalation.

**Inputs**
- `GET /exceptions` — no inputs.
- `GET /exceptions/{vendor_name:path}` — path param `vendor_name` (URL-decoded), query params `filter: str = "all"`, `selected: str = None`.
- `POST /exceptions/{vendor_name}/bulk-approve` (**new**) — path param `vendor_name`, optional query/body param `threshold: float = BULK_APPROVE_THRESHOLD` (0.99).
- `POST /exceptions/{vendor_name}/escalate` (**new**) — path param `vendor_name`, form fields `exception_id`, `filter` (optional, default `"all"`).
- `POST /exceptions/{vendor_name:path}` — path param `vendor_name`, form fields `exception_id`, `statement_id`, `invoice_number`, `reason_code`, `action`, `note` (optional), `filter` (optional, default `"all"`) — all required except `note`/`filter`. Unchanged from before.

**Outputs**
- Renders `exceptions_vendors.html` (vendor cards with open-exception counts, **now also each vendor's oldest-exception aging summary via `queries.get_exception_aging_summary()`**) or `exceptions_review.html` (per-vendor exception list + detail panel, **now also `high_confidence_count`/`bulk_approve_threshold` context for the bulk-approve button, and each exception row carries `days_open`/`days_since_escalated` via `queries._with_aging_fields()`**).
- `POST /exceptions/{vendor}/bulk-approve` (**new**) — approves every OPEN exception for that vendor at or above `threshold` in one pass via `queries.bulk_approve_exceptions()`; returns `{"approved": <count>}` as JSON, not a redirect (this is an AJAX-style action from the review page, unlike the other two POST routes).
- `POST /exceptions/{vendor}/escalate` (**new**) — marks one exception `ESCALATED` via `queries.escalate_exception()`; redirects back to the same vendor/filter (303), same pattern as the existing resolve action.
- `POST /exceptions/{vendor_name:path}` writes one row to `exception_dispositions` and updates `gold_exceptions.exception_status = 'RESOLVED'` (via `queries.resolve_exception()`), then redirects back to the same vendor's review page. Unchanged.

**Public Interface**
- `exceptions_vendors(request, user) -> TemplateResponse` — `GET /exceptions`
- `exceptions_review(vendor_name, request, user, filter="all", selected=None) -> TemplateResponse` — `GET /exceptions/{vendor_name:path}`
- **`exceptions_bulk_approve(vendor_name, request, user, threshold=BULK_APPROVE_THRESHOLD) -> dict` (new)** — `POST /exceptions/{vendor_name}/bulk-approve`
- **`exceptions_escalate(vendor_name, request, user, exception_id, filter="all") -> RedirectResponse` (new)** — `POST /exceptions/{vendor_name}/escalate`
- `exceptions_action(vendor_name, request, user, exception_id, statement_id, invoice_number, reason_code, action, note="", filter="all") -> RedirectResponse` — `POST /exceptions/{vendor_name:path}`

**Error Behaviour** — A vendor with no `gold_reconciliation_summary` row falls back to `queries.get_exceptions_only_vendor()`; if that also returns nothing, renders `exceptions_review.html` with `not_found=True` and HTTP 404 rather than raising. No explicit try/except around `queries.resolve_exception()`, `queries.bulk_approve_exceptions()` (**new**), or `queries.escalate_exception()` (**new**) in their respective handlers — a DB error in any of them propagates as an unhandled 500, losing the action silently from the user's perspective (same known gap as the original resolve action, now shared by two more write paths).

**Known Fragility**
- **`REASON_BADGE` (module-level dict) hardcodes exactly 4 `exception_reason` labels** — unchanged from before; still matches all values actually observed/reachable, still no enforced consistency with `src/matching/engine.py`/`action_review_item()`.
- **The vendor-lookup fallback chain's filename-derived title-casing fragility** — unchanged from before.
- **New: route registration order for the two new POST routes is load-bearing, not incidental.** `/exceptions/{vendor_name}/bulk-approve` and `/exceptions/{vendor_name}/escalate` are both registered *before* the catch-all `/exceptions/{vendor_name:path}` POST route — confirmed necessary by the code's own comment: Starlette's `:path` converter matches greedily (regex `.*`), so if the catch-all route were checked first it would swallow `/bulk-approve` or `/escalate` into `vendor_name` itself and neither new route would ever be reached. A plain (non-`:path`) converter is safe for the two new routes specifically because every link to them is built from `quote(vendor_name, safe="")`, which never leaves a literal `/` in the URL segment — if a future caller ever constructed one of these URLs without that encoding, a vendor name containing a `/` could break the route match. Any future reordering of these three POST routes must preserve this sequence.
- **New: `exceptions_bulk_approve()` returns raw JSON, not a redirect, unlike every other write action in this router** (`escalate` and the original `resolve` action both redirect). This is a deliberate difference (an AJAX-style call from the review page's bulk-approve button, per its own docstring), not an inconsistency to fix — but worth noting for anyone extending this router expecting a uniform redirect-after-write pattern.
- **New: `BULK_APPROVE_THRESHOLD = 0.99` is deliberately set above every score `src/matching/engine.py`'s `EXCEPTION_MATCH_CONFIDENCE` table can currently produce (`0.90` max, Invoice Missing)** — confirmed intentional by the module's own comment ("today's highest-scoring exception type tops out at 0.90, so at 0.99 nothing currently qualifies — that's intentional, not a bug"). The bulk-approve button is therefore expected to be inert for any real exception at the shipped default; this is a deliberately conservative ship-disabled posture, not a defect. See C17's Known Fragility for the same note from the scoring-table side.

**Change Impact** — Any change to `gold_exceptions`'s schema or to `exception_dispositions`'s required columns must be mirrored in `resolve_exception()` (M-011) and this router's form fields together — unchanged. New: any change to `EXCEPTION_MATCH_CONFIDENCE`'s scoring scale (M-036) directly changes whether `BULK_APPROVE_THRESHOLD` remains unreachable or starts actually gating real exceptions — a scale change there should prompt re-checking this router's threshold choice, not just the scoring table itself.

**Callers** — none (top-level HTTP entry point)
**Calls** — M-010 (`render`, `require_login`, `sidebar_context`), M-011 (`get_vendor_summaries`, `get_vendor_latest_statement`, `get_exceptions_only_vendor`, `get_open_exceptions`, `get_open_exceptions_for_source_file`, `get_exception_counts`, `get_exception_counts_for_source_file`, `resolve_exception`, **`get_exception_aging_summary` (new), `get_high_confidence_exception_count` (new), `bulk_approve_exceptions` (new), `escalate_exception` (new)**)
**Integration Points Used** — none directly
