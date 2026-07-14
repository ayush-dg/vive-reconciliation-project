# RULES — Deliberate Decisions, Do Not Undo

This catalogues decisions in this codebase that were made deliberately, often
after finding out the hard way why the obvious alternative doesn't work.
Each entry has an ID referenced in a code comment at its enforcement point
(`# See RULES.md RULE-XX`), so a future reader who's tempted to "simplify"
or "fix" something here can find the reasoning first.

This is a living document — add a new rule whenever a deliberate decision
gets made or rediscovered, the same way the Progress Log in
`docs/VIVE_Implementation_Context.md` tracks phase status.

---

### RULE-01 — No invoice number suffix stripping

**Rule:** Invoice numbers are stored exactly as extracted, whitespace-trimmed
only. No suffix/prefix normalization, no truncation.

**Why:** Suffix stripping was tried before and removed on purpose — it was
hiding real discrepancies between how the vendor and the ERP numbered the
same invoice. If the two sides genuinely format invoice numbers differently,
that's a real exception to surface, not something to paper over.

**Enforced at:** [`src/normalization.py`](src/normalization.py) —
`normalize_invoice_number()`.

---

### RULE-02 — Cache hit requires `row_count > 0` from a prior successful run

**Rule:** The extraction cache only counts as a hit if a previous run for
this exact `document_hash` completed with at least one row written.

**Why:** A failed extraction (e.g. all providers errored, zero invoices
written) must never be treated as "already processed" — that would silently
skip re-extraction of a document that was never actually parsed.

**Enforced at:** [`notebooks/01_document_intake.py`](notebooks/01_document_intake.py) —
`check_cache()` (`WHERE document_hash = ? AND row_count > 0`).

---

### RULE-03 — Matching engine is 100% deterministic, zero AI involvement

**Rule:** Match/exception decisions are pure Python/SQL. No AI call is ever
consulted to decide whether two invoices match.

**Why:** Financial reconciliation decisions must be reproducible and
auditable on demand — this is a hard invariant of the system, not a
current limitation waiting to be lifted.

**Enforced at:** [`src/matching/engine.py`](src/matching/engine.py) —
the whole file (`classify_match()`, `amounts_match()`, `run_matching()`);
see the module docstring: "AI never touches this."

---

### RULE-04 — Azure OpenAI gpt-5-mini + pdfplumber/OCR is the final extraction chain (supersedes original RULE-04)

**Rule:** No other AI providers in the extraction chain. Primary: Azure
OpenAI gpt-5-mini via the Responses API, PDF sent as a per-page inline
base64 `input_file` block (medium reasoning effort, 180s per-page timeout —
sending a whole multi-page statement in one call was found to time out
even at 600s; per-page calls complete reliably). Fallback: deterministic
pdfplumber, which handles scanned pages internally via per-page OCR.

**Why:** Originally Claude (Haiku 4.5) held this slot (see the superseded
text below). Vendor consolidation onto Azure OpenAI was a committed
decision independent of accuracy, so a real 3-model comparison
(gpt-5-mini, gpt-5-nano, gpt-5.1) was run against sample vendor statements
using the actual production `VISION_PROMPT` extraction schema. gpt-5-mini
passed the accuracy gate (exact invoice-count and line-level number/amount
matches on a smoke test); Claude was retired from the active chain as a
result. `src/ai/claude_client.py` and `config/ai/claude.json` are kept in
the repo (not deleted) pending a separate cleanup pass — see
`src/ai/azure_openai_client.py` for the current primary client.

**Superseded text (kept for history):** "No other AI providers in the
extraction chain. Primary: Claude Vision (PDF sent directly). Fallback:
deterministic pdfplumber, which handles scanned pages internally via
per-page OCR. Settled decision (`docs/VIVE_Implementation_Context.md`
Section 3). Gemini and Groq were removed in this session specifically to
enforce this — having three AI providers with an inconsistent fallback
order was itself a source of confusion (see the OCR-fix and
provider-removal work in the Progress Log)."

**Enforced at:** [`config/ai/active_provider.json`](config/ai/active_provider.json)
(`"provider_chain": ["azure_gpt5_mini", "pdfplumber"]`),
[`src/ai/client_factory.py`](src/ai/client_factory.py) — `get_ai_client()`,
[`config/ai/azure_gpt5_mini.json`](config/ai/azure_gpt5_mini.json).

---

### RULE-05 — Mock ERP generator and its suggestion workflow are CLI-only, forever

**Rule:** `src/mock_erp/generator.py` and the `scenario_config.json`
suggestion workflow (auto-suggested exception targets printed after intake)
are only ever invoked via `notebooks/02_generate_mock_erp.py` (and
`scripts/run_full_pipeline.py`). This must **never** be wired into a
dashboard or any web entry point — even after a dashboard exists.

**Why:** It's a developer/QA tool for verifying the matching engine
correctly catches deliberately-planted errors, not something any of the
real dashboard's 5-10 end users should ever see or touch.

**Enforced at:** [`src/mock_erp/generator.py`](src/mock_erp/generator.py) —
enforced by *absence*: there is no HTTP-facing wrapper around it, and none
should be added. Entry points: [`notebooks/02_generate_mock_erp.py`](notebooks/02_generate_mock_erp.py).

---

### RULE-06 — No live NetSuite integration; mock ERP is a deliberate placeholder

**Rule:** Internal ERP data is simulated by the mock ERP generator. Building
a real NetSuite integration is out of scope until VIVE Collision grants API
access — do not attempt it preemptively.

**Why:** NetSuite API access isn't available yet. The mock/real split is
deliberately isolated so the eventual swap is narrow: both sides already
share the same Silver schema, distinguished only by `record_source`.

**Enforced at:** [`src/lakehouse/connection.py`](src/lakehouse/connection.py) —
"the only file that knows the storage backend is SQLite locally"; the
`record_source` column (`VENDOR_STATEMENT` vs `INTERNAL_ERP`) in
`silver_reconciliation_standard`. Full rationale: `docs/VIVE_Implementation_Context.md` Section 2.

---

### RULE-07 — No per-vendor onboarding/configuration

**Rule:** Column mapping is universal — there is no per-vendor config file
or setup step before a new vendor's statement can be processed.

**Why:** Deliberate design goal: any vendor statement PDF, any layout,
works without a human configuring column mappings for that vendor first.

**Enforced at:** [`src/ai/document_understanding_engine.py`](src/ai/document_understanding_engine.py) —
`VISION_PROMPT`'s generic column-mapping instructions;
[`src/ai/pdfplumber_fallback.py`](src/ai/pdfplumber_fallback.py) — `_map_columns()`.

---

### RULE-08 — No full Admin/Reviewer role separation

**Rule:** Even once per-user logins exist (Phase 3), there is deliberately
only one flat permission level — no Admin vs. Reviewer tiers.

**Why:** Everyone using the dashboard does the same job today. Per-user
logins exist so `resolved_by` on a disposition means something real, not to
gate access by role.

**Enforced at:** Not yet built (Phase 3 — per-user logins is unbuilt as of
this writing). Enforced by design intent — check any future PR that
introduces role/permission checks against `docs/VIVE_Implementation_Context.md`
Sections 4 and 5 before merging it.

---

### RULE-09 — Confidence gate and "AI looks odd" flag are deferred, not built preemptively

**Rule:** A document-level confidence gate and an AI advisory "this looks
odd" flag are explicitly not being built now.

**Why:** Only build these if a real, observed case shows today's per-row
confidence handling actually lets something bad through. Building ahead of
a real trigger risks solving a problem that may never materialize, in a way
that's hard to validate without a real failure case to test against.

**Enforced at:** Not yet built. Trigger conditions are documented in
`docs/VIVE_Implementation_Context.md` Section 4, Phase 5 — check those
conditions before starting either of these.

---

### RULE-10 — OCR-derived invoice rows get confidence 0.50, deliberately below the 0.60 validation threshold

**Rule:** When `extract_with_pdfplumber()`'s fallback OCRs a scanned page and
converts the OCR text into a pseudo-table, every row extracted from that
page gets `line_confidence = 0.50` — as opposed to `0.65` for rows from
pdfplumber's real (geometry-based) table extraction.

**Why:** OCR-derived rows infer column boundaries from whitespace in flat
text, not real table geometry — inherently less reliable. `0.50` is
deliberately below the `0.60` confidence threshold in
`config/validation/extraction_rules.json`, so **every OCR-extracted invoice
always fails `validate_invoice()`'s confidence check and routes to the human
review queue — it can never silently auto-pass into Bronze/Silver.** This is
intended behavior, consistent with "never silently succeed" — not something
to "fix" by raising the confidence score once OCR accuracy is judged good
enough on the same PDFs.

**Enforced at:** [`src/ai/pdfplumber_fallback.py`](src/ai/pdfplumber_fallback.py) —
`extract_with_pdfplumber()` (`row_confidence = 0.50 if page_num in ocr_pages_used else 0.65`),
checked downstream by [`notebooks/01_document_intake.py`](notebooks/01_document_intake.py) —
`validate_invoice()` (`confidence_threshold`, from `config/validation/extraction_rules.json`).

**Context:** Added because the OCR fallback path previously existed but had
no consumer — Tesseract would run, but its output never reached the
deterministic table parser (see Progress Log). Fixing that gap meant OCR
output could newly reach Bronze/Silver, so the confidence tagging above was
added at the same time to keep the "never silently succeed" invariant intact
for this newly-functional path.

---

### RULE-11 — No "fuzzy prefix" matching level

**Rule:** The matching engine does not match invoices on a truncated
invoice-number prefix (e.g. first 6 characters) plus amount. Level 1
requires an exact invoice number match; anything short of that falls
through to Level 2 (RO + amount) or an exception.

**Why:** An earlier version matched on a truncated prefix plus amount,
intended to catch revision suffixes that survived normalization. In
practice, vendor invoice numbers commonly share a long common prefix
(e.g. `"SIN122..."`) and flat per-line-item fees repeat constantly, so
that heuristic cross-matched unrelated invoices whenever their prefix
*and* amount coincidentally lined up — silently hiding genuinely missing
invoices behind an unrelated match. Level 1 (exact `invoice_number`, via
`invoice_number_normalized`) already covers genuine suffix normalization
once a vendor-specific profile is configured; Level 2 (RO + amount) is
the correct fallback otherwise.

**Enforced at:** [`src/matching/engine.py`](src/matching/engine.py) —
`classify_match()`, the `NOTE` comment directly above the Level 2 (RO +
amount) branch.

---

### RULE-12 — Schema changes go through a new numbered migration file

**Rule:** Every lakehouse schema change is a new file under `migrations/`
(`NNN_description.sql`, zero-padded to 3 digits) — never a manual edit to
an existing migration file, never a direct `ALTER`/`CREATE` run by hand
against the database, and never a change to `notebooks/00_setup_lakehouse_schema.py`
itself (it only calls the migration runner now).

**Why:** Before this, all schema DDL lived directly in
`00_setup_lakehouse_schema.py`, with no record of what had changed when or
in what order. That's fine for a single always-fresh dev database, but
breaks down the moment more than one environment or more than one person
needs to apply the same sequence of changes reliably — the numbered,
tracked migration history is what makes "what schema state is this
database in" an answerable question instead of a guess.

**Enforced at:** [`src/lakehouse/migrations.py`](src/lakehouse/migrations.py) —
`apply_pending_migrations()` (discovery + application + `schema_version`
bookkeeping), [`migrations/`](migrations/) (the migration files themselves),
[`notebooks/00_setup_lakehouse_schema.py`](notebooks/00_setup_lakehouse_schema.py)
(the only thing that should call the runner — it should never contain DDL directly again).
