## B08 — Exceptions Router
ID: M-008
Layer: serving
Source file: `web/routers/exceptions.py`

**Module** — Exceptions Router
**ID** — M-008
**Layer** — serving
**Primary Responsibility** — Vendor exception list, per-vendor review flow, bulk-approve, escalate, and single-exception resolution (Accept/Dispute/Write-off).

**Inputs** — `vendor_name` path param (URL-encoded, `unquote()`d); `filter`/`selected` query params; form fields for action routes (`exception_id`, `statement_id`, `invoice_number`, `reason_code`, `action`, `note`).

**Outputs** — Renders `exceptions_vendors.html`/`exceptions_review.html`; writes via M-003's `resolve_exception`/`escalate_exception`/`bulk_approve_exceptions`.

**Public Interface**
- `GET /exceptions`, `GET /exceptions/{vendor_name:path}`, `POST /exceptions/{vendor_name}/bulk-approve`, `POST /exceptions/{vendor_name}/escalate`, `POST /exceptions/{vendor_name:path}` — no functions called by other modules.

**Error Behaviour** — A vendor with no statement and no exceptions-only match renders a 404-status page (not a raised HTTPException) with `not_found: True` in context.

**Known Fragility**
- **Route registration order is load-bearing, confirmed via inline comment:** `/bulk-approve` and `/escalate` (fixed-suffix POST routes) must be declared before the generic `/exceptions/{vendor_name:path}` POST handler — Starlette's `:path` converter matches greedily and would otherwise swallow both suffixes into `vendor_name`. A future engineer adding a new action route below the generic one would silently break it.
- `BULK_APPROVE_THRESHOLD = 0.99` is deliberately unreachable by any exception type today (highest exception confidence is 0.90) — the bulk-approve button is present in the UI but structurally never actionable until either the threshold changes or a new higher-confidence exception type is added. Not a bug, but a real "looks broken, isn't" trap for anyone testing it.
- `exceptions_action()` (the generic single-action route) passes the `action` form value straight through as `disposition_status` with no server-side enum check against `exception_dispositions`'s CHECK constraint (`ACCEPTED`/`DISPUTED`/`DUPLICATE`/`WRITE_OFF`/`PENDING`) — a template button value outside that set would fail at the database CHECK constraint, not at this router.

**Change Impact** — Any reordering of the four POST route declarations in this file directly risks the greedy-path-converter bug described above.

**Callers** — M-001 (router registration)
**Calls** — M-002 (`render`, `require_login`, `sidebar_context`), M-003 (`get_vendor_summaries`, `get_exception_aging_summary`, `get_vendor_latest_statement`, `get_exceptions_only_vendor`, `get_open_exceptions_for_source_file`, `get_exception_counts_for_source_file`, `get_open_exceptions`, `get_exception_counts`, `get_high_confidence_exception_count`, `bulk_approve_exceptions`, `escalate_exception`, `resolve_exception`)
**Integration Points Used** — none
