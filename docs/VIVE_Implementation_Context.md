# VIVE Reconciliation — Implementation Context & Progress Tracker

*This document is the complete context for implementing the planned VIVE Reconciliation improvements. Read this fully before writing any code. Treat every decision below as final and settled — these were arrived at deliberately, through direct architecture comparison against a sister project (Scrutin), not guesses.*

---

## 0. How to Use This Document

- This is a **living tracker**. As each item is implemented and verified working, update its status in the tables below from `Not Started` → `In Progress` → `Done`, and add a one-line note (date, PR link, anything relevant).
- Implement in the phase order given in Section 4 — do not skip ahead to later-phase items unless explicitly asked.
- If something here seems ambiguous or you're about to make an assumption that changes architecture, ask before proceeding rather than guessing.
- Act as a senior data engineer would: prioritize correctness, idempotency, and not breaking what already works over speed. VIVE's existing pipeline (extraction, caching, matching) is already solid — the goal is to add reliability and multi-user support around it, not rewrite it.

---

## 1. What VIVE Reconciliation Is

A Python-based tool built for VIVE Collision (multi-shop auto body repair company, ~79 shops, Northeast US). Vendor suppliers (parts distributors, sublet shops, towing companies) send monthly PDF statements. VIVE extracts the data from each PDF, compares it against VIVE's ERP records, and surfaces discrepancies for the AP team to review — replacing what used to be an hours-long manual cross-check per vendor.

## 2. What Exists Today (Do Not Break These)

- **Four-stage pipeline**: document intake/extraction → mock ERP generation → deterministic matching → report generation, run via numbered scripts (`notebooks/01_...` through `04_...`)
- **⚠️ Mock ERP data is a temporary placeholder, not the permanent design.** VIVE does not currently have access to VIVE Collision's real NetSuite ERP. `02_generate_mock_erp.py` clones the extracted vendor statement data and deliberately injects known errors (missing invoices, wrong amounts, duplicates) via `scenario_config.json`, purely so the matching engine has something to reconcile against for testing. **The real production comparison is always meant to be PDF vs. actual NetSuite data** — mock data only exists because NetSuite API access isn't available yet. This was anticipated in the original design: both the mock ERP side and the vendor statement side already share the same normalized Silver schema, distinguished only by a `record_source` field (`VENDOR_STATEMENT` vs `INTERNAL_ERP`). When NetSuite access becomes available, the intended change is narrow: replace what feeds into Silver on the ERP side with a real NetSuite API adapter — extraction, matching, and reporting should not need to change. **Building the live NetSuite integration itself is not currently scoped or planned** — it depends on VIVE Collision granting API access, and is a separate future project, not part of the phases below. Do not attempt to build a NetSuite integration as part of this work unless explicitly asked — the current task is implementing the Phase 1-4 items with the existing mock-data setup left exactly as-is.
- **The mock-data workflow stays CLI-only and separate from the dashboard.** `01_document_intake.py` automatically picks a few real invoice numbers/amounts from the just-extracted data and prints a ready-to-paste JSON suggestion for `scenario_config.json` (this is plain deterministic Python — sorting by amount — not an AI/LLM call, despite feeling "suggested"). A developer then manually copies this into `scenario_config.json` before running the mock ERP step. **This entire suggestion-and-configure workflow must NOT be exposed in the Streamlit dashboard.** It is a developer/QA tool for validating that the matching engine correctly catches deliberately-planted errors — not something any of the 5-10 real dashboard users should ever see or interact with. Keeping this strictly CLI-only, fully separate from the dashboard's real reconciliation flow, is what preserves a clean swap-in point for the future NetSuite adapter — the dashboard should only ever know "there is ERP data in Silver to match against," never how it got there.
- **Extraction caching**: SHA-256 hash of every PDF checked against `extraction_cache` before re-running expensive AI extraction — cache hit requires `row_count > 0` from a prior *successful* run (deliberate, don't relax this check)
- **Matching engine**: 2-level deterministic hierarchy (Level 1: exact invoice number match; Level 2: RO number + amount match), configurable tolerances in `config/matching/matching_rules.json`, **zero AI involvement by design** — this is a hard invariant, not a limitation
- **Invoice number handling**: stored exactly as extracted, whitespace-trimmed only — no suffix stripping (previously removed on purpose; it was hiding real discrepancies)
- **Partial-JSON salvage**: brace-counting logic recovers usable data from a truncated AI response — kept as a backup strategy, not the first thing tried (see Section 3)
- **Bronze/Silver/Gold layering** in SQLite (`lakehouse/reconciliation.db`) — Bronze (raw AI output) → Silver (typed/normalized, shared schema for both vendor and ERP sides) → Gold (`gold_matched_invoices`, `gold_exceptions`, `gold_reconciliation_summary`)
- **Existing logging tables**: `ai_audit_log` (every AI call, with `ai_provider`, `model`, `success`, `attempt_count`, `error_message` columns) and `document_intake_log` (one row per PDF, with `extraction_method`, `extraction_model`, `extraction_confidence_overall` columns) — **both already exist in the schema**, no new tables needed for basic provenance tracking
- **30 passing tests** across 4 pytest files (AI clients, document understanding engine, matching engine, explanation service)

## 3. Final AI Extraction Decision

- **Claude (Haiku 4.5) is the extraction engine.** Not Sonnet, not Opus — extraction is a straightforward task (reading numbers/text off a PDF), and Haiku is the appropriate, cost-effective tier for it.
- **pdfplumber + Tesseract OCR is the last-resort fallback** if Claude is unavailable — free, no AI, no per-call cost. This is a real fallback, not theoretical: pdfplumber alone cannot read scanned PDFs, which is why OCR must run first for scanned documents before pdfplumber can parse them.
- **Final chain: Claude → pdfplumber+OCR.** No other AI providers in the chain.
- **Truncation handling**: if Claude's response is truncated (hit a token limit), detect this explicitly and fall back to pdfplumber+OCR immediately — the existing brace-counting salvage logic is kept only as a secondary recovery attempt, not the first thing tried.
- **Claude is also used for the optional `--explain` narrative step** (unchanged from before) — writing a plain-English cause/suggested-action per exception. This never changes a match decision, only adds narrative.
- **pdfplumber's "confidence" is fake/manual, not a real self-assessment** — the code assigns 0.65 if it found table-like rows, 0.20 if not. Since the validation gate threshold is 0.60, a 0.65 "pass" is really just "found something table-shaped," not a genuine quality signal. Be aware of this when touching validation logic — a messy but table-shaped extraction could slide through as "valid" when it shouldn't.
- **Which extraction method processed a given document is already loggable** via the existing `document_intake_log.extraction_method` and `ai_audit_log.ai_provider` columns — when implementing the new chain, make sure the code writing to these columns uses clean values (`"claude"`, `"pdfplumber_ocr"`) and not leftover provider-specific strings from the old chain.

## 4. Implementation Phases (Priority Order)

Work through phases in order. Each item below maps to a row in the Priority Table from the Improvement Plan PDF.

### Phase 1 — Foundation
| Item | What it does | Status |
|---|---|---|
| Docker | Whole pipeline runs in a container — one command reproduces the exact same environment on any machine | Done |
| Rules doc | A file (e.g. `RULES.md`) cataloguing every deliberate "don't undo this" decision already made (no suffix stripping, cache hit requires `row_count > 0`, matching stays 100% deterministic, etc.), with an ID per rule referenced in code comments at the enforcement point | Done |
| Migration tooling | A `schema_version` table plus numbered, versioned SQL migration scripts — every future schema change tracked, no more manual undocumented edits | Not Started |

### Phase 2 — Reliability & Multi-User Foundation
| Item | What it does | Status |
|---|---|---|
| Disposition model | New `exception_dispositions` table: `(exception_id, vendor_name, invoice_number, reason_code, resolution, resolved_by, resolved_at, statement_hash, note)`. Before generating a report, look up whether this exact exception (vendor + invoice + reason) was already resolved on a prior run; suppress or annotate instead of re-flagging fresh | Not Started |
| Audit log (human actions) | Bundled into the same `exception_dispositions` table — `resolved_by` + `resolved_at` double as the human-action audit trail. No separate table needed | Not Started |
| Object storage (Blob) | Every PDF saved to Azure Blob Storage at path `{vendor_slug}/{yyyy}/{mm}/{document_hash}.pdf`, reusing the same SHA-256 hash already computed for extraction caching — this prevents ever storing the same file twice. Metadata stored alongside: `original_filename`, `uploaded_by`, `uploaded_at`, `vendor_name`. Add a new `blob_storage_path` column to `document_intake_log` linking each processed statement to its stored file | Not Started |
| Reviewer dashboard (Streamlit) | A **complete** interface, not read-only: upload a PDF directly in the browser, which triggers the existing pipeline functions directly (same code the CLI calls — no duplicate logic, no separate REST API layer). Also shows run history, exception list with disposition status, and a form to record a new disposition. The CLI continues to work as an alternative entry point | Not Started |

### Phase 3 — Multi-User Infrastructure (Confirmed Requirement: 5-10 users, mixed frequent/occasional use)
| Item | What it does | Status |
|---|---|---|
| Real shared database | Azure SQL Database (Basic tier, ~$5/month) replacing SQLite — SQLite's single-writer limitation is a real, not theoretical, problem once multiple people use the system regularly | Not Started |
| Job queue + background worker | New table: `(job_id, document_hash, uploaded_by, status[QUEUED/PROCESSING/DONE/FAILED], created_at, started_at, completed_at, attempts, worker_id, error_message)`. A separate, always-running Python worker script polls for `QUEUED` jobs, claims one atomically (row-level locking so two workers never grab the same job), runs the pipeline, updates status. **Stale-job recovery**: any job stuck in `PROCESSING` past a timeout (e.g. 10 minutes) gets automatically re-queued, so a crashed worker doesn't leave a job stuck forever. Reuses the existing document-hash check for idempotency — the same file is never processed twice even if queued twice | Not Started |
| Per-user logins | Each of the 5-10 users gets their own login on the dashboard — needed so `resolved_by` on the disposition table means something real. **No separate permission tiers** (no Admin vs. Reviewer distinction) — everyone using the dashboard does the same job today, so this is intentionally a single flat access level, not a gap | Not Started |
| Shared hosting | Azure App Service (Basic tier, ~$13/month) — the dashboard needs to run somewhere all 5-10 users can reach at any time, not on one person's laptop | Not Started |

### Phase 4 — Smaller Reliability Polish
| Item | What it does | Status |
|---|---|---|
| Dependency-skip check | If a row is missing a required field (e.g. amount), tag it explicitly as `NOT_CHECKED` rather than guessing, crashing, or letting it silently fail a comparison — visibly distinct in the report from a row that was genuinely checked and didn't match | Not Started |
| Retry/truncation fix | Covered above in Section 3 — Claude truncation detected explicitly, falls back to pdfplumber+OCR immediately, salvage kept only as backup | Not Started |
| Config cleanup | Move the two remaining hardcoded values (extraction confidence threshold, currently 0.60; any provider-specific text trim limits) out of source code and into config, consolidated alongside the existing `matching_rules.json` | Not Started |

### Phase 5 — Deferred (Only If a Real Trigger Occurs — Do Not Build Preemptively)
| Item | Trigger condition |
|---|---|
| Document-level confidence gate | Only build if a real observed case shows a bad partial extraction (low confidence on one row) is letting a wrong MATCHED result slip through elsewhere in the same document. Today, only the specific low-confidence row is held back; the rest of the document proceeds normally — this is believed sufficient until proven otherwise |
| AI "looks odd" advisory flag | Only revisit after the Disposition model (Phase 2) is stable, and only if there's real evidence pure deterministic matching is missing genuine miscoding/mismatched-category issues. Also has an unresolved data gap: there's currently no vendor-type/category field to compare a line item's description against, which would need to be added first |

## 5. Explicitly Not Suitable — Do Not Build These

| Item | Why not |
|---|---|
| Full role-based permissions (Admin vs. Reviewer tiers) | Everyone using the dashboard does the same job today — per-user logins (who did what) are sufficient without needing separate permission levels |
| Full multi-role web app matching Scrutin's stack (React + FastAPI + full auth system) | Streamlit already covers the need at VIVE's scale; building Scrutin's heavier stack would be solving a problem VIVE doesn't have |
| Heavy formal process documentation (requirements briefs, phase-gate sign-offs, etc.) | Appropriate for Scrutin's multi-stakeholder, externally-facing, legally-sensitive context; pure overhead for VIVE's internal, single-team tool |

## 6. Scrutin Backend Coverage — What VIVE Needs vs. Doesn't

*This table was produced by directly comparing Scrutin's actual backend folder structure against VIVE's current and planned architecture. Use it to sanity-check that nothing is being over-built or under-built relative to what VIVE actually needs.*

| Scrutin backend piece | VIVE's status | Notes |
|---|---|---|
| 1. API layer | **Not needed** | Streamlit runs server-side and calls VIVE's Python functions directly — no HTTP layer needed between UI and logic |
| 2. Auth & authorization | **Partially covered** | Per-user logins planned (Phase 3), but deliberately only one permission level — no Reviewer/Admin split, since everyone does the same job |
| 3. Extraction pipeline orchestration | **Covered** | `document_understanding_engine.py` already does this — call AI, check confidence, route to review if needed. One real gap: confidence is checked per-row, not per-document (see Phase 5, Confidence gate) |
| 4. Validation logic | **Covered, deliberately simpler** | VIVE's matching stays 100% deterministic by design — no AI judgment calls like Scrutin's semantic modules. This is correct design for a reconciliation tool, not a shortcoming |
| 5. Job queue + background worker | **Not built yet — the one genuine gap** | Planned for Phase 3. This is the most important piece to actually build before multi-user use is real, not just planned on paper |
| 6. Database access | **Covered, migrating to Azure SQL** | Simpler than Scrutin's SQLAlchemy ORM — VIVE uses direct SQL — but functionally equivalent |
| 7. File storage handling | **Covered — planned Phase 2** | Azure Blob Storage retention does the same job as Scrutin's S3/MinIO |
| 8. Disposition/outcome logic | **Covered, simpler** | VIVE's version is "was this resolved before, yes/no" rather than Scrutin's full Accept/Reject-per-finding plus 4-state outcome derivation. Appropriate for VIVE's simpler matching problem — do not over-build this into Scrutin's full complexity |
| 9. Reference data management | **Correctly not needed** | Exists in Scrutin because firms need onboarded rate tables/rosters. VIVE deliberately has no per-vendor onboarding — nothing to manage here, and this should stay that way |
| 10. Report generation | **Covered** | Already exists (`04_generate_report.py`), continues unchanged |

**Bottom line: 7 of 10 pieces are handled** (several correctly simpler than Scrutin's version, which is by design, not a gap). **2 are deliberately not applicable** to VIVE's problem. **1 is a genuine, currently-unbuilt gap: the job queue + worker.**

## 7. Cost Summary (For Reference — Already Approved)

| Item | Estimated cost |
|---|---|
| Azure SQL Database (Basic tier) | ~$5/month |
| Azure App Service (Basic tier) | ~$13/month |
| Azure Blob Storage | A few cents/month at VIVE's volume |
| **Total new recurring cost** | **~$18-20/month combined** |

## 8. Things a Senior Data Engineer Should Also Insist On (Additions Beyond What's in the Plan PDFs)

These weren't explicitly itemized in the Priority Table but are standard production practice and should be applied while implementing the above, not treated as optional extras:

- **Idempotent processing everywhere**, not just at the queue level — reprocessing the same `document_hash` should never create duplicate Bronze/Silver/Gold rows. Partially true already via the extraction cache; verify it holds end-to-end once the job queue is added.
- **Index the hash/lookup columns** — `document_hash` in both the new job queue table and `document_intake_log`, and the `(vendor_name, invoice_number, reason_code)` combination on `exception_dispositions` — without these, lookups get slower as tables grow.
- **Structured logging in the worker process**, not print statements — the worker runs unattended; when something fails at 2am, whoever checks logs later needs structured, searchable output (timestamp, job_id, error type), not free-text prints.
- **Secrets management**: as this moves to Azure App Service, move API keys and DB credentials out of local `.env` files and into Azure Key Vault (or App Service's built-in application settings, encrypted) — don't let production secrets live in a file that could end up in version control.
- **Confirm encryption at rest is enabled** on the Blob Storage container — Azure enables this by default, but confirm explicitly rather than assuming.
- **Private, non-public Blob container** — vendor PDFs should never be reachable via a public URL; confirm container access level is set to private.
- **Basic alerting on repeated job failures** — if the same document fails processing multiple times in a row, someone should be notified rather than the job silently sitting in a failed state indefinitely.
- **A rollback plan for the Docker image** — tag images with versions, not just `latest`, so a bad deploy can be rolled back quickly.
- **Backup verification for Azure SQL** — confirm automated backups are actually enabled and (ideally) that a restore has been test-run at least once, not just assumed to work.

## 9. What NOT to Do (Explicit Guardrails)

- Do not introduce any AI judgment calls into the matching engine — matching must remain 100% deterministic, always.
- Do not re-add invoice number suffix stripping or normalization — this was deliberately removed because it was hiding real discrepancies.
- Do not relax the cache-hit condition (`row_count > 0`) — a failed run must never be treated as a valid cache hit.
- Do not build per-vendor onboarding/configuration — VIVE's universal column-mapping approach is deliberate and should stay that way.
- Do not build the Phase 5 items preemptively — they are gated behind specific trigger conditions, not a fixed timeline.
- Do not add Gemini, Groq, or any other AI provider back into the extraction chain — Claude + pdfplumber/OCR is the final decision.
- Do not build full Admin/Reviewer role separation — a flat permission model is correct for VIVE's current team structure.
- Do not modify, replace, or attempt to automate away the mock ERP generator, and do not build a live NetSuite integration — this is explicitly out of scope for the current phases (see Section 2). The mock data setup stays exactly as it is until NetSuite API access is available and a separate project is scoped for it.
- Do not expose the mock ERP generator's suggestion workflow (`scenario_config.json`, the auto-suggested exception targets) in the Streamlit dashboard — it is a CLI-only developer/QA tool and must stay fully separate from the real dashboard used by the 5-10 end users.

---

## Progress Log

*Add an entry here every time an item's status changes.*

**Note:** `ANTHROPIC_API_KEY` in `.env` is still empty pending company billing
setup — live pipeline testing with real Claude extraction is parked until
that's resolved.

| Date | Item | Status change | Notes |
|---|---|---|---|
| 2026-07-13 | Docker | Not Started → Done | Dockerfile + docker-compose.yml + DOCKER.md added on branch phase-1-foundation. Verified: image builds clean, 30/30 tests pass in container, full 4-stage pipeline runs end-to-end on a real sample PDF. Added pytest to requirements.txt (was missing, untracked). Note: config/ is baked into the image, not volume-mounted — edits there require rebuild or docker exec. |
| 2026-07-13 | Gemini/Groq removal | N/A → Done | Deleted gemini_client.py, groq_client.py, config/ai/gemini.json, config/ai/groq.json. Added src/ai/claude_client.py (retry/truncation logic ported from gemini_client.py). Rewrote client_factory.py and document_understanding_engine.py — Claude Vision primary (generate_with_file), pdfplumber+OCR fallback. Updated requirements.txt, .env/.env.example, active_provider.json, config/ai/claude.json. Tests: TestGeminiClient/TestGroqClient replaced with TestClaudeClient; fallback tests now assert routing to pdfplumber. 30 → 28 tests, all passing. |
| 2026-07-13 | OCR fallback fix | N/A → Done | Fixed pre-existing gap: pdfplumber_fallback.py's extract_with_pdfplumber() never actually consumed OCR output (OCR text previously only fed Groq, now removed). Added per-page scanned-page detection, new ocr_extractor.ocr_page() helper, OCR-text-to-pseudo-table conversion feeding the existing column-mapping pipeline. OCR-derived rows tagged line_confidence=0.50 (below the 0.60 validation threshold) so OCR-extracted invoices always route to human review, never auto-pass. |
| 2026-07-13 | Rules doc | Not Started → Done | RULES.md created with 11 numbered rules covering invoice handling, cache semantics, matching determinism, Claude-only extraction chain, mock ERP CLI-only boundary, NetSuite placeholder, universal column mapping, flat permission model, deferred Phase 5 items, OCR confidence tagging, and no fuzzy-prefix matching. Reference comments added at each enforcement point in code. |
| 2026-07-13 | Matching Level 3 → Level 2 rename | N/A → Done | Fixed standing inconsistency: matching_rules.json declared a 3-level hierarchy but classify_match() only ever implemented 2 real branches. Removed the never-built phantom "Level 2" (Invoice + Amount) config entry, merged its key into Level 1, renumbered RO+Amount from Level 3 to Level 2 throughout code/tests/config/docs. |
| 2026-07-13 | Lakehouse database reset | N/A → Done | Backed up lakehouse/reconciliation.db to backup/ (gitignored) before deleting, due to Gemini→Claude provider change making prior cached/extracted data stale. Re-ran 00_setup_lakehouse_schema.py for a fresh, empty schema (10 tables, 0 rows each, individually verified). |
| | | | |
