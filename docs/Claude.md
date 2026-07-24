---
version: v1.0
METHODOLOGY_VERSION: v5.0 (pbvi_core.md) — approximated onboarding, pbvi_brownfield.md unavailable
source: PBVI-009 brownfield onboarding (approximated — see notice below)
frozen: true
---

# Claude.md — v1.0 · FROZEN · 2026-07-24

> **PBVI-009 Brownfield Onboarding — Approximation Notice**
> Produced without `pbvi_brownfield.md` (not available at generation time). This is a
> best-effort approximation of the PBVI-009 brownfield Claude.md generation step, built
> from `pbvi_core.md`'s Claude.md Schema section and its v4.6 changelog description of
> the onboarding procedure. Inputs used: `docs/ARCHITECTURE.md` v1.0 and
> `docs/INVARIANTS.md` v1.0 (both also produced as onboarding approximations this same
> session). No `discovery/ONBOARDING_LOG.md` attestation record exists for this
> generation. **Engineer review of all five sections below is required before this is
> treated as a genuinely frozen execution contract** — "frozen: true" above reflects the
> PBVI convention that Claude.md is never partially applied, not a claim that engineer
> sign-off has occurred.

## Changelog
| Version | Date | Author | Change |
|---|---|---|---|
| v1.0 | 2026-07-24 | CD (approximated onboarding) | Brownfield — Initial, derived from docs/ARCHITECTURE.md v1.0 + docs/INVARIANTS.md v1.0 |
| v1.1 | 2026-07-24 | Ayush Kumar Sinha (engineer decision, direct instruction) | INV-05 amended — narrowed from "at most one job PROCESSING system-wide" to "at most one job per distinct pdf_filename PROCESSING at a time," to enable web/worker.py's parallel worker pool. See docs/INVARIANTS.md's amended INV-05 entry for the full rationale. |

---

## Section 1 — System Intent

VIVE Reconciliation extracts line-item data from vendor PDF statements, compares it
deterministically against VIVE Collision's ERP records (currently simulated via a mock
generator pending live NetSuite access), and surfaces discrepancies for a human AP team
to review. It does not itself approve, reject, or execute any payment. Success looks
like: every vendor statement's invoices are either matched with high confidence or
correctly routed to human review — never silently misclassified either way.

---

## Section 2 — Hard Invariants

**INV-01:** Any row whose extraction confidence falls below the configured threshold
(`0.60`) must be routed to human review — never silently pass into Bronze/Silver as if
it were a fully-trusted extraction.
This is never negotiable.

**INV-02:** The matching engine makes every match/exception decision through
deterministic rules only — no AI model is ever consulted inside the matching step, for
any reason.
This is never negotiable.

**INV-03:** No totals/summary row (grand total, subtotal, balance-forward) may ever be
ingested and validated as if it were a real invoice line.
This is never negotiable.

**INV-04:** `invoice_number` and `outstanding_amount` must never be null in any row
written to the Silver layer.
This is never negotiable.

**INV-05 (amended 2026-07-24):** At most one job per distinct `pdf_filename` may be in
`PROCESSING` status at any time — two jobs for the SAME PDF must never be claimed and
processed concurrently (they'd race the same `extraction_cache` row). Different
filenames MAY process concurrently, up to `web/worker.py`'s `WORKER_POOL_SIZE`. This
narrows the original INV-05 ("at most one job PROCESSING system-wide, full stop"),
which was superseded by direct engineer instruction specifically to enable the parallel
worker pool — see docs/INVARIANTS.md's amended INV-05 entry for the rationale.
This is never negotiable.

**CQ-001:** Each function, method, or handler must have a single stateable purpose.
Conditional nesting exceeding two levels is a structural violation — refactor before
proceeding.
This is never negotiable.

---

## Section 3 — Scope Boundary

**This is the onboarding baseline Claude.md — no build session is active and no
enhancement is currently scoped.** It establishes the system-wide boundary that future
enhancement Claude.md amendments (via `pbvi_sprint.md`'s amendment prompt) will narrow
per-enhancement. It does not itself authorize any file modification.

**In scope for future enhancement work** (module references per
`discovery/SYSTEM_GRAPH.json`, M-001 through M-044):
- `src/ai/` — extraction provider clients (M-020 through M-032)
- `src/lakehouse/` — connection, migrations (M-033 through M-035)
- `src/matching/` — matching engine (M-036)
- `src/mock_erp/`, `src/normalization.py`, `src/storage/` (M-037 through M-039)
- `web/` — FastAPI app, routers, worker, queries (M-001 through M-013)
- `notebooks/`, `scripts/` — pipeline entry points and orchestration (M-014 through M-019)
- `migrations/` — new numbered migration files only, never hand-edited DDL
- `config/` — provider chain, validation rules, matching tolerances

**Out of scope — do not build without an explicit new enhancement decision:**
- Live NetSuite integration (`src/mock_erp/generator.py` remains the placeholder until
  API access is granted — a separate future project)
- Per-vendor onboarding/configuration for column mapping
- Any AI involvement inside `src/matching/engine.py`
- Full role-based permission tiers (Admin/Reviewer split) — flat access model is
  intentional at current team scale
- Document-level aggregate confidence gate / AI "looks odd" advisory flag — deferred
  behind a specific trigger condition, not built ahead of evidence
- Wiring the mock ERP generator's suggestion workflow into the dashboard — must remain
  CLI-only

**Always out of scope:** `sample_data/`, `backup/`, `venv/`, `discovery/` (BCE artifacts —
updated only via the sprint BCE refresh procedure, never by a build session directly),
`BCE/` (methodology skill files).

---

## Section 4 — Fixed Stack

**Language/runtime:** Python (containerized via Docker)

**Web framework:** FastAPI >=0.110.0, uvicorn >=0.27.0, Jinja2 >=3.1.0 (server-rendered,
no client-side SPA), python-multipart >=0.0.9, itsdangerous >=2.1.0, bcrypt >=4.1.0

**Database:** SQLite (local/dev/test, no driver needed) or Azure SQL (production) via
pyodbc >=5.0.0 — selected automatically by whether `AZURE_SQL_SERVER` is set
(`src/lakehouse/connection.py`)

**AI extraction providers:**
- anthropic >=0.40.0 — Claude Sonnet 4.6 (active primary extraction, via Azure AI
  Foundry) and Claude Haiku 4.5 (exception explanations only, hardcoded independent of
  `provider_chain`)
- openai >=2.40.0 — Azure OpenAI gpt-5-mini/nano/5.1 (registered, dormant)
- google-genai >=2.10.0 — Gemini 2.5 Flash (registered, dormant)
- Mistral Medium — direct API, no SDK dependency pinned here (registered, dormant)
- Azure Document Intelligence — prebuilt-layout (registered, dormant, a prior primary)

**Deterministic fallback:** pdfplumber >=0.11.0, pytesseract ==0.3.13, pdf2image
==1.17.0, pypdf >=6.0.0

**Storage:** azure-storage-blob >=12.19.0 (Blob Storage archival, wired end-to-end)

**Testing:** pytest ==9.1.1

**Environment variables (see `.env.example` for the full set):**
`AZURE_CLAUDE_API_KEY`, `AZURE_CLAUDE_ENDPOINT`, `AZURE_CLAUDE_SONNET_DEPLOYMENT`,
`AZURE_CLAUDE_DEPLOYMENT` (Haiku), `AZURE_SQL_SERVER`, `AZURE_SQL_USERNAME`,
`AZURE_SQL_PASSWORD`, `AZURE_BLOB_CONNECTION_STRING`, `GEMINI_API_KEY`,
`MISTRAL_API_KEY`, `AZURE_DOC_INTEL_KEY`, `AZURE_DOC_INTEL_ENDPOINT`,
`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `WEB_SESSION_SECRET` (**currently
unset in this deployment — see `discovery/RISK_REGISTER.md` R-008; do not treat its
hardcoded fallback as acceptable for any new production-facing work**).

Anything not listed here, the AI selects.

---

## Section 5 — Rules

**Rule 1:** All file references use full paths from repo root — never bare filenames.

**Rule 2:** All files inside any enhancement package carry their ENH-NNN prefix — no
exceptions.

**Rule 3:** Any file not in the mandatory set for its directory and not registered in
`PROJECT_MANIFEST.md` must not be read by CC as authoritative input. CC flags
unregistered files and reports them to the engineer before proceeding.
