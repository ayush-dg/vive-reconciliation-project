# INVARIANT_CATALOGUE.md — VIVE Reconciliation
Produced by: BCE Stage 2 Session D (CC) — Path A (Custodian-Led), fresh extraction
Date: 2026-08-05

No Stage 1 draft or IC-CANDIDATE entries exist (Path A has no Stage 1) — every entry below is fresh, cross-referenced this session against `docs/INVARIANTS.md` (INV-01–06 + CQ-001), `RULES.md` (13 rules, read in full this session), `docs/Claude.md` Section 5 (Rules 1–5), and every module contract from Sessions B/C/G. This is a **fresh baseline**, not a carry-forward of the archived `INVARIANT_CATALOGUE.md`.

---

## IC-01 — Confidence-gated human review

**Scope:** GLOBAL
**Source:** Both (`docs/INVARIANTS.md` INV-01; code-observed)
**Currently enforced:** YES
**Enforcement point:** `notebooks/01_document_intake.py:validate_invoice()` (`confidence_threshold`, default 0.60, from `config/validation/extraction_rules.json`)
**Owning module:** M-017
**Enforcing modules:** M-017
**Rationale:** Any row whose extraction confidence falls below the configured threshold must be routed to human review, never silently pass into Bronze/Silver as fully trusted. This is the single control that lets the rest of the pipeline treat Bronze/Silver data as reviewed-or-trustworthy.

---

## IC-02 — Matching engine is 100% deterministic, zero AI involvement

**Scope:** GLOBAL
**Source:** Both (`docs/INVARIANTS.md` INV-02; `RULES.md` RULE-03; code-observed)
**Currently enforced:** YES
**Enforcement point:** `src/matching/engine.py` — whole file (`classify_match()`, `amounts_match()`, `run_matching()`); confirmed no import of any `src/ai/*` module anywhere in this file.
**Owning module:** M-034
**Enforcing modules:** M-034
**Rationale:** Financial reconciliation decisions must be reproducible and auditable on demand — a permanent design position, not a current limitation. `match_confidence` scoring is also deterministic (rule-based on match type), not model-derived.

---

## IC-03 — No totals/summary row may be ingested as an invoice line

**Scope:** GLOBAL
**Source:** Both (`docs/INVARIANTS.md` INV-03; code-observed)
**Currently enforced:** YES (active primary + fallback only — see Divergence below)
**Enforcement point:** `src/ai/claude_sonnet_client.py:_is_totals_row()` (active primary); `src/ai/pdfplumber_fallback.py:_extract_invoice_row()` (deterministic fallback, keyword check on `invoice_number`)
**Owning module:** M-025
**Enforcing modules:** M-025, M-031
**Rationale:** A grand-total/subtotal/balance-forward row is not a real invoice line; ingesting one as such corrupts totals and produces a false discrepancy.
**Divergence note:** Confirmed this session — the two dormant clients M-029 (Gemini) and M-030 (Mistral) have no equivalent totals-row filter at all (only M-025 and M-031 do). This matches the archived `RISK_REGISTER.md`'s prior finding (tracked as IC-20 in the archived catalogue, R-002) — not a new gap, but re-confirmed still true against current source, not carried forward on trust.

---

## IC-04 — `invoice_number` and `outstanding_amount` must never be null in Silver

**Scope:** GLOBAL
**Source:** Both (`docs/INVARIANTS.md` INV-04; code-observed)
**Currently enforced:** YES — application-layer only, not database-enforced
**Enforcement point:** `notebooks/01_document_intake.py:get_skip_reason()` (broad skip for rows missing both fields entirely) + `validate_invoice()` (required-fields check)
**Owning module:** M-017
**Enforcing modules:** M-017
**Rationale:** These two fields are the minimum a Silver row needs to be usable by the matching engine at all.
**Divergence note:** Confirmed this session (Session F01) that `silver_reconciliation_standard`'s schema itself has **no NOT NULL constraint** on either column — the guarantee is entirely a code-layer gate before a row ever reaches Silver, not a database-level backstop. A future direct write to this table bypassing `notebooks/01_document_intake.py` (e.g. a data-fix script) would not be blocked by the schema itself.

---

## IC-05 — Job claiming is atomic and scoped per `pdf_filename`

**Scope:** GLOBAL
**Source:** Both (`docs/INVARIANTS.md` INV-05, amended 2026-07-24; `docs/Claude.md` Section 5 Rule 5; code-observed)
**Currently enforced:** YES
**Enforcement point:** `web/queries.py:claim_next_pending_job()` — single `UPDATE ... WHERE id = (SELECT MIN...) AND status = 'PENDING'` statement (never a two-step SELECT-then-UPDATE)
**Owning module:** M-003
**Enforcing modules:** M-003, M-005 (the only caller)
**Rationale:** Two facets of one mechanism, catalogued together since both govern the same function: (1) at most one job per distinct `pdf_filename` may be PROCESSING at a time — narrowed from an original system-wide lock specifically to enable the worker pool, since the real failure mode being prevented is two jobs for the *same* PDF racing the same `extraction_cache` write, not concurrent processing generally; (2) the claim itself must be one atomic statement — a separate SELECT then UPDATE leaves a race window where two worker threads read the same eligible row before either writes, both claiming it.

---

## IC-06 — AI-call concurrency cap

**Scope:** TASK-SCOPED — tasks touching `src/ai/` (extraction clients, concurrency limiter) or `web/worker.py`
**Source:** Both (`docs/INVARIANTS.md` INV-06; code-observed)
**Currently enforced:** YES, with one known accepted limitation
**Enforcement point:** `src/ai/concurrency_limiter.py:ai_call_slot()` — cross-process file-lock semaphore, wraps only the real network call in `src/ai/claude_sonnet_client.py`
**Owning module:** M-041
**Enforcing modules:** M-025 (the only caller)
**Rationale:** Each job runs in its own subprocess, so an in-process semaphore can't coordinate across jobs claimed by different worker threads — needed once the worker pool could run more than one job concurrently, to stay within Azure Foundry's rate limit.
**Scope resolution:** This invariant was flagged earlier in this engagement as ambiguously classified between GLOBAL and TASK-SCOPED (`docs/Claude.md` §2's own cross-reference footnote hedges rather than resolving it). Applying the actual test here: no task touching, say, the users router (M-013) or the batches router (M-014) has any plausible interaction with AI-call concurrency — only tasks touching the extraction/worker layer do. **Resolved as TASK-SCOPED** — narrower in footprint and different in category (Structural/resource-governance, not Domain/financial-integrity) than IC-01–05, which genuinely do apply everywhere data moves through the pipeline.
**Known limitation:** A killed (not normally-exited) process never releases its slot — capacity is permanently reduced by one until the stale lock file is manually removed from `lakehouse/ai_call_slots/`.

---

## CQ-001 — Single-purpose functions, max two levels of nesting

**Scope:** GLOBAL
**Source:** Docs-declared (`docs/INVARIANTS.md`, `docs/Claude.md` Section 2 — mandatory in every Claude.md regardless of authoring mode)
**Currently enforced:** NOT DETERMINABLE FROM SOURCE — this is a code-review-time discipline, not a runtime or static-analysis-enforced constraint; no linter configuration enforcing complexity/nesting limits was found in this codebase.
**Enforcement point:** NOT DETERMINABLE FROM SOURCE (human code review only)
**Owning module:** none (a cross-cutting coding standard, not owned by any one module)
**Enforcing modules:** none code-enforced
**Rationale:** Each function/method/handler must have a single stateable purpose; conditional nesting beyond two levels is a structural violation. Never negotiable per the methodology, but its enforcement mechanism today is entirely a human discipline, not a gate.

---

## IC-08 — No invoice-number suffix/prefix stripping or truncation

**Scope:** GLOBAL
**Source:** Docs-declared (`RULES.md` RULE-01) — **not currently present in `docs/INVARIANTS.md`**
**Currently enforced:** YES
**Enforcement point:** `src/normalization.py:normalize_invoice_number()` — whitespace-trim only, no other transformation
**Owning module:** M-036
**Enforcing modules:** M-036
**Rationale:** Suffix stripping was tried before and reverted — it hid real discrepancies between how the vendor and the ERP number the same invoice. A real formatting difference is a genuine exception to surface, not something to paper over.
**Finding — promotion candidate:** This is a genuine, historically-reverted-when-violated invariant, and Session B/C/G's own cross-cutting findings independently flagged M-036 as "the codebase's clearest example of correct-because-it-does-less" and the single highest-risk-of-well-intentioned-regression module. It is currently documented only in `RULES.md` prose, not in the formal `docs/INVARIANTS.md`/`Claude.md` §2 contract that a build session actually reads as authoritative. **Recommend promoting this to a formal GLOBAL invariant in `docs/INVARIANTS.md`** — as things stand, a future enhancement could "improve" `normalize_invoice_number()` without ever consulting `RULES.md` at all.

---

## IC-09 — Extraction cache hit requires `row_count > 0` from a prior successful run

**Scope:** GLOBAL
**Source:** Docs-declared (`RULES.md` RULE-02)
**Currently enforced:** YES
**Enforcement point:** `notebooks/01_document_intake.py:check_cache()` — `WHERE document_hash = ? AND row_count > 0`
**Owning module:** M-017
**Enforcing modules:** M-017
**Rationale:** A failed extraction (all providers errored, zero rows written) must never be treated as "already processed" — that would silently and permanently skip re-extraction of a document that was never actually parsed.

---

## IC-10 — Mock ERP generator is CLI-only, never web-facing

**Scope:** TASK-SCOPED — any task touching `src/mock_erp/`, dashboard wiring, or new web routers
**Source:** Docs-declared (`RULES.md` RULE-05)
**Currently enforced:** YES, by absence
**Enforcement point:** Confirmed this session — no router among M-006–M-015 imports `src.mock_erp` at all.
**Owning module:** M-035
**Enforcing modules:** none (enforced by the absence of a caller, not an active guard)
**Rationale:** The mock ERP generator and its suggestion workflow are a developer/QA tool for verifying the matching engine catches deliberately-planted errors — not something any of the real dashboard's end users should ever see or touch, even once a dashboard exists (it already does).

---

## IC-11 — No per-vendor onboarding or column-mapping configuration

**Scope:** TASK-SCOPED — any task touching extraction/column-mapping logic
**Source:** Docs-declared (`RULES.md` RULE-07)
**Currently enforced:** YES
**Enforcement point:** `src/ai/claude_sonnet_client.py:_map_columns()` (active primary); `src/ai/pdfplumber_fallback.py:_map_columns()` (fallback); each dormant client (M-027–M-030) also implements its own independent keyword-based mapping.
**Owning module:** M-025
**Enforcing modules:** M-025, M-028, M-029, M-030, M-031
**Rationale:** Any vendor statement PDF, any layout, must work without a human configuring column mappings for that vendor first — a deliberate design goal, not a temporary gap.

---

## IC-12 — OCR-derived rows are always scored below the validation confidence threshold

**Scope:** GLOBAL
**Source:** Docs-declared (`RULES.md` RULE-10)
**Currently enforced:** YES
**Enforcement point:** `src/ai/pdfplumber_fallback.py:extract_with_pdfplumber()` — `row_confidence = 0.50 if page_num in ocr_pages_used else 0.65`, checked downstream by IC-01's enforcement point
**Owning module:** M-031
**Enforcing modules:** M-031
**Rationale:** OCR-derived rows infer column boundaries from whitespace in flat text, not real geometry — inherently less reliable. `0.50` is deliberately below IC-01's `0.60` threshold specifically so every OCR-extracted invoice always fails validation and routes to human review — this must never be "fixed" by raising the constant once OCR accuracy looks good on a given sample, since the invariant is about the review gate always catching this class of row, not about today's actual OCR accuracy.

---

## IC-13 — No "fuzzy prefix" matching level

**Scope:** GLOBAL
**Source:** Docs-declared (`RULES.md` RULE-11); code-observed (confirmed via `MATCH_LEVEL_TO_TYPE = {1: "INVOICE", 2: "RO"}`, no level 3)
**Currently enforced:** YES
**Enforcement point:** `src/matching/engine.py:classify_match()` — the `NOTE` comment directly above the Level 2 branch documents the removal explicitly
**Owning module:** M-034
**Enforcing modules:** M-034
**Rationale:** An earlier truncated-prefix-plus-amount heuristic silently cross-matched unrelated invoices whenever their prefix and amount coincidentally lined up, hiding genuinely missing invoices behind a false match — removed on purpose, must not be reintroduced.

---

## IC-14 — Schema changes are new numbered migration files only

**Scope:** GLOBAL
**Source:** Docs-declared (`RULES.md` RULE-12)
**Currently enforced:** YES
**Enforcement point:** `src/lakehouse/migrations.py:apply_pending_migrations()` (discovery + application + `schema_version` bookkeeping); `migrations/` directory itself
**Owning module:** M-038
**Enforcing modules:** M-038, M-016 (the only caller), M-039 (mirrors the same end state for Azure SQL, not itself a numbered migration runner)
**Rationale:** A tracked, numbered migration history is what makes "what schema state is this database in" an answerable question rather than a guess — the discipline breaks down the moment more than one environment or person needs to apply the same sequence of changes reliably.

---

## IC-15 — `src/lakehouse/connection.py` is the only file that knows the storage backend

**Scope:** GLOBAL
**Source:** Docs-declared (`RULES.md` RULE-06, RULE-13); code-observed
**Currently enforced:** PARTIAL
**Enforcement point:** `src/lakehouse/connection.py` — `get_connection()`/`execute_sql()`/`execute_query()` (Azure SQL/SQLite path, fully backend-agnostic for callers)
**Owning module:** M-037
**Enforcing modules:** M-037; PARTIALLY by M-003, M-017 (see divergence below)
**Rationale:** Callers write backend-agnostic SQL; `connection.py` absorbs every dialect difference so calling code never branches on which backend is active.
**[STAGE-2-DIVERGENCE — 2026-08-05]:** `RULES.md` RULE-13 states this invariant with no caveat, and was not updated when the Fabric Warehouse cut-over landed. As of this session, callers of `execute_sql_fabric()`/`execute_query_fabric()` (M-003, M-017) **must know, table by table, which of the three Fabric-cut-over tables (`extraction_cache`, `document_intake_log`, `validation_document_review_queue`) is on Fabric versus which remaining tables are still on Azure SQL** — a real, if narrow, break from pure backend-agnosticism, since the Fabric functions have no dialect translation and no drop-retry, unlike their Azure SQL counterparts. Resolution required before Stage 3: either `RULES.md` RULE-13 is updated to describe the Fabric path as a documented, scoped exception, or the abstraction is deepened so callers no longer need table-level backend awareness.

---

## IC-16 — Dashboard/UI reads must always live-query `gold_exceptions`, never trust `gold_reconciliation_summary`'s cached counts

**Scope:** GLOBAL
**Source:** Docs-declared (`docs/Claude.md` Section 5, Rule 3)
**Currently enforced:** YES
**Enforcement point:** `web/queries.py:_with_live_exception_counts()`, `_live_open_exception_count()`, `get_vendor_summaries()` — every UI-facing read recomputes the open-exception count directly from `gold_exceptions` rather than trusting `gold_reconciliation_summary.exception_count`
**Owning module:** M-003
**Enforcing modules:** M-003; consumed by M-007, M-008, M-010, M-014
**Rationale:** `gold_reconciliation_summary`'s cached `exception_count`/`overall_status` go stale the moment an exception is resolved or a new one is raised outside a full re-match — confirmed this session that `_recompute_summary_counts()` (added `3cc3c37`) now also fixes the underlying table itself, but this Rule 3 invariant is what protected every UI-facing read even before that fix existed, and remains the correct belt-and-suspenders posture regardless.

---

## IC-17 — Every pipeline subprocess loads `.env` via an explicit absolute path

**Scope:** GLOBAL
**Source:** Docs-declared (`docs/Claude.md` Section 5, Rule 4)
**Currently enforced:** YES
**Enforcement point:** `load_dotenv(os.path.join(PROJECT_ROOT, ".env"))` — confirmed present in M-001, M-017, M-018, M-019, M-020, M-021 (every pipeline entry point and the web app itself)
**Owning module:** none single (a repeated pattern across entry points, not owned by one module)
**Enforcing modules:** M-001, M-017, M-018, M-019, M-020, M-021
**Rationale:** A bare `load_dotenv()` discovers the file via cwd/call-stack heuristics, which depend on how the process was invoked — this matters concretely because `scripts/run_full_pipeline.py` is invoked as a subprocess from a different working-directory context than a developer running a notebook directly. A silent fallback here means the subprocess never sees `AZURE_SQL_SERVER` and quietly writes to local SQLite while the web app reads/writes Azure SQL/Fabric — two processes disagreeing about which backend is "the real one," with no error, just missing data on one side.

---

## IC-18 — Exception router's fixed-suffix POST routes must be declared before its generic `:path` action route

**Scope:** TASK-SCOPED — any task touching `web/routers/exceptions.py`
**Source:** Code-observed only — new this session, no prior doc reference
**Currently enforced:** YES
**Enforcement point:** `web/routers/exceptions.py` — `/exceptions/{vendor_name}/bulk-approve` and `/exceptions/{vendor_name}/escalate` are declared textually before `POST /exceptions/{vendor_name:path}`
**Owning module:** M-008
**Enforcing modules:** M-008
**Rationale:** Starlette's `:path` converter matches greedily (regex `.*`); if the generic route were declared first, it would swallow both fixed suffixes into `vendor_name` and the two specific routes would never be reached. The file's own inline comment documents this explicitly — a future engineer adding a new action route below the generic one would silently break it with no test currently guarding this ordering (not verified whether a route-order test exists — worth a Session E gap note).

---

## IC-19 — No two concurrent writers may compute the same next `id` for a Fabric-cut-over table

**Scope:** TASK-SCOPED — any task touching `extraction_cache`, `document_intake_log`, or `validation_document_review_queue` writes, or `src/lakehouse/connection.py`'s Fabric path
**Source:** Code-observed only — new this session
**Currently enforced:** **NO**
**Enforcement point:** None exists. Every write site (`notebooks/01_document_intake.py`'s `update_cache()`/`write_to_review_queue()`/`write_intake_log()`) independently computes `MAX(id) + 1` in Python with no lock, transaction-level serialization, or retry-on-conflict.
**Owning module:** M-037 (the connection layer that should, in principle, own this guarantee)
**Enforcing modules:** none
**Rationale:** These three tables lost their `IDENTITY` property when cut over to Fabric Warehouse (confirmed: Fabric's IDENTITY only supports BIGINT with large non-sequential distributed values, incompatible with the already-migrated rows' small sequential ids without recreating the table). This invariant *should* hold for the same reason every other surrogate-key table in this schema has one enforced (silent id collisions corrupt data), but currently does not — this is a live, currently-accepted-by-omission gap, catalogued explicitly here specifically so it feeds directly into Session E's `RISK_REGISTER.md` as a real, not hypothetical, risk.

---

Session D is complete. `INVARIANT_CATALOGUE.md` must be committed before Session E begins.
