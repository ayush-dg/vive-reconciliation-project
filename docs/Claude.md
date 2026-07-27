---
version: v2.0
METHODOLOGY_VERSION: v5.0 (pbvi_core.md)
frozen: true
---

# Claude.md — v2.0 · FROZEN · 2026-07-27

## Changelog
| Version | Date | Author | Change |
|---|---|---|---|
| v1.0 | 2026-07-24 | CD | Brownfield initial |
| v1.1 | 2026-07-24 | Ayush Kumar Sinha | INV-05 amended — narrowed to per-filename to enable parallel worker pool |
| v2.0 | 2026-07-27 | Ayush Kumar Sinha | Full update — new routes, tables, worker pool, batch intake, review queue, match confidence, routing/aging, bulk approve all reflected |

---

## Section 1 — System Intent

VIVE Reconciliation extracts line-item data from vendor PDF statements, compares it deterministically against VIVE Collision's ERP records (currently simulated via a mock generator pending live NetSuite access), and surfaces discrepancies for a human AP team to review. It does not itself approve, reject, or execute any payment. Success looks like: every vendor statement's invoices are either matched with high confidence or correctly routed to human review — never silently misclassified either way.

---

## Section 2 — Hard Invariants

**INV-01:** Any row whose extraction confidence falls below `0.60` must be routed to human review — never silently pass into Bronze/Silver.
This is never negotiable.

**INV-02:** The matching engine makes every match/exception decision through deterministic rules only — no AI model is ever consulted inside the matching step, for any reason. `match_confidence` scoring is also deterministic (rule-based, not AI).
This is never negotiable.

**INV-03:** No totals/summary row (grand total, subtotal, balance-forward) may ever be ingested and validated as if it were a real invoice line.
This is never negotiable.

**INV-04:** `invoice_number` and `outstanding_amount` must never be null in any row written to the Silver layer.
This is never negotiable.

**INV-05 (amended 2026-07-24):** At most one job per distinct `pdf_filename` may be in `PROCESSING` status at any time. Different filenames MAY process concurrently up to `WORKER_POOL_SIZE` (default 3). The original system-wide statement was superseded by direct engineer instruction to enable the parallel worker pool.
This is never negotiable.

**CQ-001:** Each function, method, or handler must have a single stateable purpose. Conditional nesting exceeding two levels is a structural violation.
This is never negotiable.

**Cross-reference (not a sixth GLOBAL invariant — see `pbvi_core.md`'s five-invariant ceiling on this section):** `VIVE_MAX_CONCURRENT_AI_CALLS` caps concurrent Claude Sonnet calls system-wide — see `docs/INVARIANTS.md` INV-06 / `discovery/INVARIANT_CATALOGUE.md` IC-21.

---

## Section 3 — Scope Boundary

**In scope for build work:**
- `src/ai/` — extraction provider clients
- `src/lakehouse/` — connection, migrations
- `src/matching/` — matching engine
- `src/mock_erp/`, `src/normalization.py`, `src/storage/`
- `web/` — FastAPI app, all routers, worker, queries
- `notebooks/`, `scripts/` — pipeline entry points
- `migrations/` — new numbered migration files only, never hand-edited DDL
- `config/` — provider chain, validation rules, matching tolerances, shop_owners.json

**Out of scope — do not build without an explicit new enhancement decision:**
- Live NetSuite integration (`src/mock_erp/generator.py` stays until API access is granted)
- Per-vendor column mapping configuration
- Any AI involvement inside `src/matching/engine.py`
- Full role-based permission tiers (Admin/Reviewer split)
- Document-level aggregate confidence gate
- Wiring the mock ERP generator into the dashboard (must remain CLI-only)
- Email alerts (Step 9) — provider decision pending
- Fault isolation per file in a batch (Step 6) — not yet built

**Always out of scope:** `sample_data/`, `backup/`, `venv/`, `discovery/` (BCE artifacts).

---

## Section 4 — Fixed Stack

**Language/runtime:** Python 3.12, Docker

**Web framework:** FastAPI >=0.110.0, uvicorn >=0.27.0, Jinja2 >=3.1.0, python-multipart, itsdangerous, bcrypt

**Database:** SQLite (local/dev/test) or Azure SQL (production) via pyodbc — selected by `AZURE_SQL_SERVER` env var. Both backends supported by all migration runners including ALTER TABLE column additions.

**AI extraction:**
- anthropic — Claude Sonnet 4.6 (active primary, Azure AI Foundry) + Claude Haiku 4.5 (exception explanations only)
- openai — Azure OpenAI (registered, dormant)
- google-genai — Gemini 2.5 Flash (registered, dormant)
- Mistral — direct API (registered, dormant)
- Azure Document Intelligence (registered, dormant, prior primary)

**Deterministic fallback:** pdfplumber, pytesseract, pdf2image, pypdf

**Storage:** azure-storage-blob (archival to vivereconciliation + drop zone viverecondropzone)

**Security note:** the drop-zone webhook (`/api/intake-trigger`) was unauthenticated end-to-end until 2026-07-25 — now fixed in code (shared secret, pinned container, event-count cap); see `discovery/RISK_REGISTER.md` R-009.

**Worker:** 3-thread pool, configurable via `VIVE_WORKER_POOL_SIZE`. AI rate limit via `VIVE_MAX_CONCURRENT_AI_CALLS` (default 2).

**Testing:** pytest

**Key environment variables:** `AZURE_CLAUDE_API_KEY`, `AZURE_CLAUDE_ENDPOINT`, `AZURE_CLAUDE_SONNET_DEPLOYMENT`, `AZURE_CLAUDE_DEPLOYMENT`, `AZURE_SQL_SERVER`, `AZURE_SQL_DATABASE`, `AZURE_SQL_USERNAME`, `AZURE_SQL_PASSWORD`, `AZURE_BLOB_CONNECTION_STRING`, `AZURE_BLOB_DROPZONE_CONNECTION_STRING`, `VIVE_WORKER_POOL_SIZE`, `VIVE_MAX_CONCURRENT_AI_CALLS`, `WEB_SESSION_SECRET`

---

## Section 5 — Rules

**Rule 1:** All file references use full paths from repo root — never bare filenames.

**Rule 2:** All files inside any enhancement package carry their ENH-NNN prefix.

**Rule 3:** Dashboard KPI cards must live-query `gold_exceptions` for exception counts — never trust the `gold_reconciliation_summary` snapshot directly.

**Rule 4:** All pipeline subprocesses (run_full_pipeline.py and all notebooks) must call `load_dotenv(os.path.join(PROJECT_ROOT, ".env"))` with an explicit path — bare `load_dotenv()` silently fails to find `.env` when invoked as a subprocess from a different working directory, causing the process to fall back to SQLite instead of Azure SQL.

**Rule 5:** Job claiming must use the atomic `UPDATE ... WHERE NOT EXISTS` guard in `web/queries.py:claim_next_pending_job()` — never a two-step SELECT then UPDATE.
