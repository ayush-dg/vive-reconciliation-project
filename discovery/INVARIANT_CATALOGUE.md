# INVARIANT_CATALOGUE.md — VIVE Reconciliation
Produced by: BCE Stage 2 Session D (CC) — Path A (Custodian-Led)
Date: 2026-07-24

RULES.md's 13 numbered rules are the primary candidate source (this project's functional equivalent of `docs/INVARIANTS.md`, though not PBVI-governed). Every rule below was walked against its actual enforcement point in code this session — five were already confirmed in prior sessions (carried forward, not re-derived); the remaining eight were freshly verified. Six additional implicit invariants (IC-14–19), never documented in RULES.md at all, were surfaced by walking the data touchpoints directly.

---

## IC-1 — Invoice numbers are stored exactly as extracted, whitespace-trimmed only
**Scope:** GLOBAL
**Source:** Docs-declared (RULES.md RULE-01) + Code-observed
**Currently enforced:** YES
**Enforcement point:** `src/normalization.py:normalize_invoice_number()` — confirmed the entire function body is a null-check and `.strip()`, nothing else.
**Owning module:** M-038
**Enforcing modules:** M-038
**Rationale:** Divergent vendor/ERP invoice-number formatting is a real discrepancy to surface, not paper over — a previously-tried suffix-stripping normalization was hiding genuine mismatches and was deliberately removed.

---

## IC-2 — A cache hit requires `row_count > 0` from a prior successful run
**Scope:** GLOBAL
**Source:** Docs-declared (RULE-02) + Code-observed
**Currently enforced:** YES (re-confirmed this session)
**Enforcement point:** `notebooks/01_document_intake.py:check_cache()` — `WHERE document_hash = ? AND row_count > 0`.
**Owning module:** M-014
**Enforcing modules:** M-014
**Rationale:** A failed extraction (zero rows written) must never be treated as "already processed" — that would silently skip re-extraction of a document that was never actually parsed.
**Note:** This invariant governs AI-extraction-cost deduplication only. It does not guarantee Silver/Gold-level deduplication — see IC-16.

---

## IC-3 — The matching engine is 100% deterministic, zero AI involvement
**Scope:** GLOBAL
**Source:** Docs-declared (RULE-03) + Code-observed
**Currently enforced:** YES (confirmed prior session, carried forward)
**Enforcement point:** `src/matching/engine.py` — the entire file; confirmed no import of, or call into, any AI client anywhere in this module.
**Owning module:** M-036
**Enforcing modules:** M-036
**Rationale:** Financial reconciliation decisions must be reproducible and auditable on demand — a hard invariant, not a current limitation awaiting removal.

---

## IC-4 — Exactly one documented, deterministic extraction provider chain governs primary extraction
**Scope:** GLOBAL
**Source:** Docs-declared (RULE-04 — confirmed stale) + Code-observed (authoritative)
**Currently enforced:** YES in both code and documentation, as of 2026-07-24 (see resolution note below) — originally cataloged as PARTIAL: the *code* contract always held (`client_factory.get_ai_client()` always resolves to exactly one deterministic primary, `provider_chain[0]`); the *documentation* contract was broken in **nine** separate locations (RULES.md RULE-04; `docs/VIVE_Implementation_Context.md` Section 3; `src/ai/gemini_client.py`'s docstring; `src/ai/client_factory.py`'s own inline comments; `src/ai/ocr_extractor.py`'s docstring; `src/ai/document_understanding_engine.py`'s docstring; `notebooks/04_generate_report.py`'s docstring; `src/ai/mistral_client.py`'s docstring; `src/ai/claude_sonnet_client.py`'s own docstring), each naming a different provider than the one actually resolved.
**Enforcement point:** `config/ai/active_provider.json` (`provider_chain[0]` = `"claude_sonnet"`) + `src/ai/client_factory.py:get_ai_client()`.
**Owning module:** M-031
**Enforcing modules:** M-023 (actual current primary), M-031
**Rationale:** RULE-04's intent is a single, documented, understood extraction path. The mechanism itself is sound (never ambiguous which provider runs); what's broken is every human-readable description of which provider that is. **[RESOLVED — Stage 3, 2026-07-24, engineer sign-off (P1-S3-002), completed across three passes the same day]:** engineer confirmed Claude Sonnet 4.6 is intentionally the current primary. The initial documentation sweep corrected 6 of the 9 locations now known to be affected (RULES.md RULE-04, Implementation Context Section 3, `gemini_client.py`, `client_factory.py`'s comments, `ocr_extractor.py`, `04_generate_report.py`). A subsequent independent verification pass found `document_understanding_engine.py`'s own docstring still stale despite being named in this invariant's original divergence description, and separately discovered `mistral_client.py`'s docstring carried the same class of error (naming `azure_doc_intel` as primary) — both corrected. `claude_sonnet_client.py`'s own docstring was initially left deliberately uncorrected out of caution about blast radius on the active provider's own file during the original fix; it was corrected in a final pass once that caution no longer applied. All nine locations are now confirmed corrected. `Currently enforced` above now reads YES without qualification.

---

## IC-5 — The mock ERP generator and its suggestion workflow are CLI-only, never dashboard-facing
**Scope:** GLOBAL
**Source:** Docs-declared (RULE-05) + Code-observed
**Currently enforced:** YES (re-confirmed this session via direct grep)
**Enforcement point:** Enforced by absence — a repo-wide grep of `web/` for any reference to `mock_erp`/`generate_mock_erp`/`normalize_erp_to_silver` returns zero matches.
**Owning module:** M-037
**Enforcing modules:** none structurally (no code path exists that could violate this — the invariant holds because the temptation was simply never wired in, not because a runtime check blocks it)
**Rationale:** It's a developer/QA tool for verifying the matching engine correctly catches deliberately-planted errors — not something any of the real dashboard's 5-10 end users should see or touch.

---

## IC-6 — No live NetSuite integration exists; the mock ERP is a deliberate, isolated placeholder
**Scope:** GLOBAL
**Source:** Docs-declared (RULE-06) + Code-observed
**Currently enforced:** YES
**Enforcement point:** Enforced by absence — no NetSuite client, SDK import, or API call exists anywhere in the codebase (confirmed across every source file read across Sessions A0 through D). `silver_reconciliation_standard.record_source` (schema, `src/lakehouse/connection.py`'s backend isolation) is what keeps the eventual swap narrow.
**Owning module:** M-037
**Enforcing modules:** M-033 (`record_source` schema design), M-037
**Rationale:** NetSuite API access isn't available yet; the mock/real split is deliberately isolated so both sides already share the same Silver schema, distinguished only by `record_source`.

---

## IC-7 — Column mapping is universal; no per-vendor configuration exists before a new statement can be processed
**Scope:** GLOBAL
**Source:** Docs-declared (RULE-07 — enforcement citation confirmed stale) + Code-observed
**Currently enforced:** YES, but RULE-07's own citation is incomplete
**Enforcement point:** RULES.md cites `document_understanding_engine.py`'s `VISION_PROMPT` and `pdfplumber_fallback.py`'s `_map_columns()` — but `VISION_PROMPT` is confirmed unused by the active primary (M-023, per IC-4/Session B-C-G findings). The actual live enforcement point is `src/ai/claude_sonnet_client.py:_map_columns()`, which independently confirms the same design (generic keyword matching, no per-vendor config file, no vendor-specific lookup table anywhere).
**Owning module:** M-020
**Enforcing modules:** M-023 (actual live path), M-028 (deterministic fallback path), M-024/M-025/M-026 (dormant paths — each independently confirmed to also use generic keyword mapping, not vendor config)
**Rationale:** Any vendor statement PDF, any layout, must work without a human configuring column mappings for that vendor first. **[RESOLVED — Stage 3, 2026-07-24, engineer sign-off (P1-S3-004)]:** RULES.md RULE-07's enforcement-point citation updated to name `src/ai/claude_sonnet_client.py:_map_columns()` as the actual live enforcement point. `Currently enforced` above should now read YES without qualification.

---

## IC-8 — No role-based permission tiers exist; all authenticated users share one flat access level
**Scope:** GLOBAL
**Source:** Docs-declared (RULE-08 — build-status premise confirmed stale) + Code-observed
**Currently enforced:** YES, but RULE-08's own text is out of date about what's built
**Enforcement point:** `web/routers/users.py` and `web/deps.py:require_login()` — confirmed by absence of any role/permission check anywhere in either file, or anywhere in the request path.
**Owning module:** M-008
**Enforcing modules:** M-001, M-008
**Rationale:** RULE-08's text states "per-user logins is unbuilt as of this writing" — false as of this session (confirmed built: `users`/`jobs` tables, M-001 auth router, M-008 users management router, all fully functional). The underlying *design intent* it describes (flat permission model, no Admin/Reviewer split) is confirmed still accurate in the now-built code — any authenticated user, including a non-admin-added one, can add or remove any other user (self-removal excepted). **[RESOLVED — Stage 3, 2026-07-24, engineer sign-off (P1-S3-005)]:** RULES.md RULE-08's text updated to reflect that per-user logins are built, with the flat-permission design intent explicitly reconfirmed as still accurate. `Currently enforced` above should now read YES without qualification.

---

## IC-9 — A document-level confidence gate and an AI "looks odd" advisory flag are deliberately not built
**Scope:** GLOBAL
**Source:** Docs-declared (RULE-09) + Code-observed
**Currently enforced:** YES (still not built, confirmed by absence)
**Enforcement point:** N/A — enforced by absence. No document-level aggregate confidence check exists anywhere in the traced pipeline; validation is exclusively per-row (`notebooks/01_document_intake.py:validate_invoice()`).
**Owning module:** M-014
**Enforcing modules:** none (deferred feature, correctly not built)
**Rationale:** Only build these if a real, observed case shows today's per-row confidence handling actually lets something bad through — building ahead of a real trigger risks solving a problem that may never materialize.

---

## IC-10 — OCR-derived invoice rows always carry confidence below the validation threshold, routing them to human review
**Scope:** TASK-SCOPED — the deterministic pdfplumber/OCR fallback path only
**Source:** Docs-declared (RULE-10) + Code-observed
**Currently enforced:** YES for `pdfplumber_fallback.py` specifically — **not applicable** to the four LLM-based provider clients, which never reach this code path's logic at all under normal operation (they fabricate their own flat confidence before ever falling back here).
**Enforcement point:** `src/ai/pdfplumber_fallback.py:extract_with_pdfplumber()` — `row_confidence = 0.50 if page_num in ocr_pages_used else 0.65`; checked downstream by `notebooks/01_document_intake.py:validate_invoice()` (`confidence_threshold = 0.60`, from `config/validation/extraction_rules.json`).
**Owning module:** M-028
**Enforcing modules:** M-028, M-014
**Rationale:** OCR-derived rows infer column boundaries from whitespace in flat text, not real table geometry — inherently less reliable; deliberately kept below threshold so they can never silently auto-pass into Bronze/Silver.
**Scoping note (engineer-requested clarification, 2026-07-24):** RULE-10 is not contradicted or weakened by this session's fabricated-confidence findings (IC-15) — it was written specifically about, and remains fully accurate for, the deterministic fallback path. It was never the mechanism responsible for the four AI providers' own confidence reporting; that gap belongs to IC-15, a broader invariant RULE-10 was never intended to cover.

---

## IC-11 — No fuzzy-prefix matching level exists in the matching hierarchy
**Scope:** GLOBAL
**Source:** Docs-declared (RULE-11) + Code-observed
**Currently enforced:** YES (confirmed during Session B/C/G, carried forward)
**Enforcement point:** `src/matching/engine.py:classify_match()` — an explicit code comment directly above the Level 2 branch states the rationale; only two real match levels exist in the code (exact invoice+amount, RO+amount).
**Owning module:** M-036
**Enforcing modules:** M-036
**Rationale:** An earlier truncated-prefix-plus-amount heuristic cross-matched unrelated invoices whenever prefix and amount coincidentally aligned, silently hiding genuinely missing invoices behind an unrelated match.

---

## IC-12 — Schema changes go through a new numbered migration file, never a direct edit
**Scope:** GLOBAL, with a confirmed carve-out for the Azure SQL path
**Source:** Docs-declared (RULE-12) + Code-observed
**Currently enforced:** PARTIAL — fully enforced for SQLite; not enforced the same way for Azure SQL.
**Enforcement point:** `src/lakehouse/migrations.py:apply_pending_migrations()` (SQLite — confirmed `notebooks/00_setup_lakehouse_schema.py` contains no direct DDL, only calls the runner). `src/lakehouse/azure_sql_migrations.py:run_migrations()` (Azure SQL — a **second, independently-maintained schema-definition mechanism**, `TABLES`/`COLUMNS` dicts that must be manually kept in sync with the numbered SQLite migrations and are not themselves versioned/tracked the same way).
**Owning module:** M-034
**Enforcing modules:** M-034 (SQLite, full enforcement), M-035 (Azure SQL, manual/partial enforcement only)
**Rationale:** A numbered, tracked migration history is what makes "what schema state is this database in" an answerable question instead of a guess — currently only fully true for the SQLite side. Confirmed in sync as of this session (migrations 004-006 correctly mirrored in `azure_sql_migrations.py`), but nothing enforces that going forward.

---

## IC-13 — Azure SQL is the production backend; SQLite is reserved for local dev/tests
**Scope:** GLOBAL
**Source:** Docs-declared (RULE-13) + Code-observed
**Currently enforced:** YES
**Enforcement point:** `src/lakehouse/connection.py:_using_azure_sql()`, `get_connection()`, `execute_sql()`/`execute_query()`, `AZURE_UPSERT_KEYS`.
**Owning module:** M-033
**Enforcing modules:** M-033
**Rationale:** Phase 3 requirement to run against a real production database without breaking local development or the test suite, which never sets `AZURE_SQL_SERVER`. Confirmed actively load-bearing, not aspirational — `web/queries.py:get_recent_runs()` (M-011) independently documents having to work around this translator's exact-literal `LIMIT` requirement.

---

## New Implicit Invariants Surfaced This Session (not documented anywhere in RULES.md)

## IC-14 — `invoice_number` and `outstanding_amount` must never be null in Silver
**Scope:** GLOBAL
**Source:** Code-observed only
**Currently enforced:** YES
**Enforcement point:** `notebooks/01_document_intake.py:get_skip_reason()` (broad skip when neither an identifier nor an amount exists at all) + `validate_invoice()`'s `required_fields` gate (`config/validation/extraction_rules.json`).
**Owning module:** M-014
**Enforcing modules:** M-014
**Rationale:** The matching engine depends on both fields being present for every Silver row; `discovery/DOMAIN_MODEL.json`'s `null_semantic` annotations for A-009/A-017 trace directly to this two-layer enforcement.

---

## IC-15 — A row whose confidence falls below the configured threshold must be routed to human review, never silently pass
**Scope:** GLOBAL in mechanism, but only genuinely protective for a subset of providers
**Source:** Code-observed only — the general principle RULE-10 is one specific application of
**Currently enforced:** PARTIAL — mechanically enforced for every row (the check always runs), but **functionally defeated for the four providers that fabricate a flat `0.75` confidence** (M-023, M-024, M-025, M-026), which always clears the `0.60` threshold regardless of actual extraction quality. Only genuinely protective where the input signal is real: M-021, M-022 (model-elicited), and M-028 (geometry/OCR-differentiated).
**Enforcement point:** `notebooks/01_document_intake.py:validate_invoice()` — `confidence_threshold` check.
**Owning module:** M-014
**Enforcing modules:** M-014 (mechanism), M-021, M-022, M-028 (providers supplying a genuine input)
**Rationale:** This is this session's central finding, now formalized as an invariant: the code enforcing "low confidence never silently succeeds" is correct, but is starved of real signal for the majority of currently-registered extraction providers — including the active primary. See `discovery/components/A02_module_call_map.md` and `discovery/MODULE_CONTRACTS.md` for the full cross-provider audit. Priority RISK_REGISTER candidate at Session E.

---

## IC-16 — Reprocessing the same document should never create duplicate reconciliation data
**Scope:** GLOBAL
**Source:** Docs-declared (Implementation Context Section 8: "reprocessing the same document_hash should never create duplicate Bronze/Silver/Gold rows") + Code-observed
**Currently enforced:** PARTIAL — only the AI-extraction-cost layer is deduplicated (IC-2). Every call to `run_intake()` — cache hit or not — generates a fresh `statement_id` and writes a new set of Silver rows via `normalize_to_silver()`, copying the cached Bronze content forward under that new ID. No dedup exists at the Silver/Gold layer.
**Enforcement point:** `notebooks/01_document_intake.py:run_intake()`/`normalize_to_silver()` — confirmed no `document_hash`-level dedup beyond Bronze/AI-cost.
**Owning module:** M-014
**Enforcing modules:** none at the Silver/Gold layer
**Rationale:** Directly explains this session's earlier finding (local Silver row count 3,031 vs. Bronze row count 2,203 for VENDOR_STATEMENT rows) and the two orphaned test-seed statement_ids investigation. Implementation Context's stated goal is broader than what RULE-02 alone delivers. Needs an explicit engineer decision: is "each upload = a new independent reconciliation run" the intended design, or a gap to close?

**Blast radius, precisely confirmed (engineer-requested follow-up, 2026-07-24):**
- **The one number that matters most — the home dashboard's headline KPIs (`web/queries.py:get_kpis()`) — is NOT affected.** That query `INNER JOIN`s against `_LATEST_RUN_PER_VENDOR` before summing anything, so only the newer of two duplicate runs for the same vendor counts toward the displayed total exposure/invoice count. Same protection confirmed on `get_recent_runs()` and `get_vendor_summaries()` (exceptions page) — both show exactly one row per vendor, not two. This filtering is a side effect of "show current state," not a deliberate dedup design, but it is real and it is what prevents the specific doubled-total-exposure scenario this was flagged against.
- **`get_all_runs()` (Reports page) is confirmed unprotected** — its query (`SELECT ... FROM gold_reconciliation_summary ORDER BY reconciliation_timestamp DESC`) has no vendor-level filtering at all, verified by direct read. A duplicate upload appears as two separate, likely near-identical rows. Each row shows its own per-statement total rather than a summed aggregate, so this does not itself present one inflated number, but is a visible, confusing symptom.
- **Raw Gold-table data is genuinely duplicated** — `gold_matched_invoices`, `gold_exceptions`, `gold_reconciliation_summary` hold two complete, independent row sets under the two `statement_id`s. Confirmed by re-reading every remaining `SUM(`/`COUNT(*)` query in `web/queries.py`: all others are scoped to a single `statement_id`/`source_file`, none aggregate across a vendor's multiple runs, so this duplication has no other current blast radius beyond the Reports page and the raw tables themselves.
- **Severity assessment: P2, not P1.** The scenario motivating a P1 read (visibly doubled vendor exposure on the primary dashboard) does not occur today. What's real is a Reports-page display quirk and genuine row-level duplication that any future export/audit feature would need to independently guard against, since the protection that exists today is incidental to `get_kpis()`, not a system-wide invariant.

**Carry-forward note for RISK_REGISTER.md (engineer-requested, 2026-07-24):** the protection `get_kpis()` currently provides against duplicate-upload inflation is **incidental** — a side effect of the `_LATEST_RUN_PER_VENDOR` join existing to answer "what's this vendor's current state," not a deliberate anti-duplication safeguard anyone designed on purpose. Nothing documents this connection today; nothing would flag it if broken. Recommend RISK_REGISTER.md carry this forward as its own explicit note (not folded silently into IC-16's general description) so that any future change to `get_kpis()` — e.g. simplifying the query, changing how "latest" is determined, or removing the join for a performance reason — gets checked against this dependency first, rather than someone unknowingly removing the one thing currently preventing doubled-total-exposure display on the home dashboard.

---

## IC-17 — Every registered AI provider client must implement `generate_with_file()`, not just the ABC's formal `generate()`
**Scope:** GLOBAL
**Source:** Code-observed only
**Currently enforced:** NO at the contract level (confirmed: only `generate()` is `@abstractmethod` in `src/ai/base_client.py:AIClient`) — YES only by convention (confirmed via grep: all 6 current clients implement it).
**Enforcement point:** Gap lives in `src/ai/base_client.py:AIClient`; the unenforced dependency lives in `src/ai/document_understanding_engine.py`, which calls `generate_with_file()` unconditionally on whatever client it resolves.
**Owning module:** M-030
**Enforcing modules:** none (a 7th client implementing only `generate()` would pass the ABC check and fail at runtime with an `AttributeError`)
**Rationale:** Already flagged as an INVARIANT_CATALOGUE.md candidate in `discovery/MODULE_CONTRACTS.md`'s cross-cutting finding #3 — formalized here.

---

## IC-18 — The job pipeline depends on an exact, untyped string contract between the orchestrator's output and the worker's parser
**Scope:** TASK-SCOPED — web-uploaded job processing only
**Source:** Code-observed only
**Currently enforced:** NO formal enforcement (no test asserts this; a print-statement reword would silently break it)
**Enforcement point:** `scripts/run_full_pipeline.py` (producer: prints `"Statement ID: {statement_id}"`) / `web/worker.py:STATEMENT_ID_RE` (consumer: regex `r"Statement ID:\s*(\S+)"`).
**Owning module:** M-018
**Enforcing modules:** M-013
**Rationale:** Already flagged in `discovery/MODULE_CONTRACTS.md`'s cross-cutting finding #4 — formalized here as exactly the class of implicit, unenforced constraint Session D exists to surface.

---

## IC-19 — At most one job may be in `PROCESSING` status system-wide at any time
**Scope:** GLOBAL
**Source:** Code-observed only
**Currently enforced:** YES
**Enforcement point:** `web/queries.py:claim_next_pending_job()` — single atomic `UPDATE` with a `NOT EXISTS (SELECT 1 FROM jobs WHERE status = 'PROCESSING')` guard.
**Owning module:** M-011
**Enforcing modules:** M-011, M-013
**Rationale:** Prevents two worker processes (or a leftover dev server) from claiming the same job or racing concurrently-uploaded jobs against each other's cache/extraction writes.
**Related gap (cross-reference, not a violation):** this same guard is exactly what makes the already-documented missing stale-job-requeue logic a single point of stall for the *entire* queue — if one job never leaves `PROCESSING`, this invariant's own guard blocks every subsequent job indefinitely.

---

## IC-20 — No totals/summary row may be ingested as an invoice line
**Scope:** GLOBAL in intent, currently enforced only on 2 of 5 extraction paths
**Source:** Code-observed only — added at Stage 3 (2026-07-24), engineer-signed-off, per `discovery/ANNOTATION_CHECKLIST.md` P2-S3-001
**Currently enforced:** PARTIAL — `pdfplumber_fallback.py` (M-028) explicitly filters rows whose invoice number contains `"total"`/`"balance"`/`"subtotal"` before they're written as invoice lines; `document_intelligence_client.py` (M-024) inherits this protection by importing the same helper directly. `ClaudeSonnetClient` (M-023, active primary), `GeminiClient` (M-025), and `MistralClient` (M-026) have no equivalent filter at either the prompt or code level.
**Enforcement point:** `src/ai/pdfplumber_fallback.py:_extract_invoice_row()` (the only real enforcement); absent from `claude_sonnet_client.py`/`gemini_client.py`/`mistral_client.py`'s own `_row_to_invoice()`/`_rows_to_invoices()`.
**Owning module:** M-028
**Enforcing modules:** M-028, M-024 (via import)
**Rationale:** A vendor statement's grand-total or subtotal row typically carries a dollar amount and sometimes a number-like reference in the same position an invoice number would occupy — without this filter, such a row can be silently extracted and validated as if it were a real invoice, corrupting the statement total and the reconciliation itself. Formalizes the gap already tracked as `discovery/RISK_REGISTER.md` R-002 (High severity) and cross-referenced from IC-15's provider audit.

---

Sessions D and Stage 3 (Cross-Artifact Review) are both reflected in this artifact. `discovery/INVARIANT_CATALOGUE.md` must remain committed and current before Graph Construction (`discovery/SYSTEM_GRAPH.json`) runs.
