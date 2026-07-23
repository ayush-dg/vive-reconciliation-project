# RISK_REGISTER.md — VIVE Reconciliation
Produced by: BCE Stage 2 Session E (CD) — Path A (Custodian-Led)
Date: 2026-07-24

Synthesized entirely from `discovery/INVARIANT_CATALOGUE.md`, `discovery/MODULE_CONTRACTS.md`, and `discovery/TOPOLOGY.md` — no new source reads performed. Severity reflects what was actually confirmed during this extraction, not softened for presentation. Six distinct entries per explicit engineer instruction — related-but-separate findings are kept apart rather than folded together.

---

## R-001 — Confidence-gated human review is functionally defeated for 4 of 6 registered extraction providers, including the active primary

**Severity:** Critical

**Description:** The system's core safety mechanism — any row with `line_confidence` below `0.60` must route to human review, never silently pass (RULE-10's design principle) — depends on genuine, model-elicited confidence existing in the first place. It does not for `ClaudeSonnetClient` (M-023, the **confirmed active primary**), `GeminiClient` (M-025), `MistralClient` (M-026), or `DocumentIntelligenceClient` (M-024, a confirmed prior primary) — all four hardcode a flat `ROW_CONFIDENCE = 0.75` constant, which always clears the threshold regardless of actual extraction quality. Only `AzureOpenAIClient` (M-021) and `ClaudeClient` (M-022) preserve a real signal, and neither is currently active for document extraction.

**Threatened invariant:** IC-15 (also touches IC-10, which remains accurate but was never intended to cover this)

**Affected modules:** M-023, M-024, M-025, M-026 (source of the gap); M-014 (the validation gate whose input is compromised)

**Live confirmation (this session, aggregate-only queries):** 100% of 1,510 local + 2,120 Azure SQL `gold_matched_invoices` rows (plus 4 `gold_exceptions` rows) traced to `claude_sonnet`-tagged Bronze data show `extraction_confidence` exactly `0.75` — zero variance across every recorded run. This is not a theoretical exposure; it has governed every statement this system has reconciled under its current active provider.

**Mitigation (current):** None at the extraction-provider level. `pdfplumber_fallback.py` (M-028) is the sole path with genuine, differentiated confidence, but it is only reached when a primary provider outright fails — not when it succeeds with a low-quality read.

**Recommended action:** Either (a) restore a real confidence-eliciting prompt/response contract for the active primary (would require `ClaudeSonnetClient` to request and honor a genuine per-row confidence field, similar to `VISION_PROMPT`'s approach), or (b) explicitly and consciously accept that this system currently has no meaningful per-row confidence signal for its live extraction path, and adjust operational expectations (e.g. increased manual spot-checking) accordingly. This is an engineer/business decision, not a code fix BCE can make unilaterally.

**Engineer decision (2026-07-24):** Accepted as-is for now — not fixing today. Will be prioritized against Sprint 1 planning rather than addressed ad hoc. Tracked here as Critical so it isn't lost or understated when that prioritization happens.

**Azure SQL instance provenance — confirmed (2026-07-24):** The Azure SQL instance checked during this investigation is **confirmed test/dev data, not production traffic**. Evidence: the `fake`/`fake-model` value in `document_intake_log.extraction_method` is a test-fixture artifact; only 2 users exist, both created within 10 minutes of each other; both stray `source_file` filenames (`REPRO_CACHE_TEST.pdf`, and a page-sliced duplicate of the Tekion sample) were traced directly to test artifacts, not unknown real vendors. This confirmation resolves the "engineer should confirm definitively" note originally attached to this finding in `discovery/components/A02_module_call_map.md` — the 2,124-row figure describes shared dev/test infrastructure, not live production exposure. Severity remains Critical regardless, since the underlying code defect is real and would affect production identically once real traffic runs through it.

---

## R-002 — No totals/summary-row exclusion in the three actively-registered LLM extraction clients

**Severity:** High

**Description:** `pdfplumber_fallback.py` (M-028) explicitly filters out rows whose invoice number contains `"total"`/`"balance"`/`"subtotal"` before they're written as invoice lines — and `document_intelligence_client.py` (M-024) inherits this protection by importing the same helper directly. **`ClaudeSonnetClient` (M-023), `GeminiClient` (M-025), and `MistralClient` (M-026) have no equivalent filter at either the prompt or code level**, confirmed by direct grep and inspection of each file's row-processing loop (`_row_to_invoice`/`_rows_to_invoices`, which convert every row unconditionally).

**Threatened invariant:** IC-20 (added at Stage 3, 2026-07-24, engineer sign-off — see `discovery/ANNOTATION_CHECKLIST.md` P2-S3-001). Originally recorded here with no formal invariant; now formalized.

**Affected modules:** M-023, M-025, M-026

**Live confirmation:** Not yet observed to have actually occurred in either database (no confirmed instance of a totals row being ingested as a fake invoice was found in this session's data checks) — this is a **real, unmitigated exposure**, not a confirmed incident. Severity is set on the exposure, not on an observed failure, per instruction not to soften based on absence of a caught incident.

**Mitigation (current):** None for the three affected clients. A vendor statement whose totals/summary row contains a plausible-looking invoice-number-shaped value and a dollar amount would be silently extracted and would proceed through validation exactly like a real invoice (since it would likely have both required fields populated).

**Recommended action:** Port `pdfplumber_fallback.py`'s keyword-based totals-row filter (or an equivalent) into `_row_to_invoice()`/`_rows_to_invoices()` for all three affected clients, or add an explicit prompt instruction (as `VISION_PROMPT` already has) requiring the model to separate a grand total from invoice lines.

---

## R-003 — Reprocessing the same document produces genuine row-level duplication in Gold tables

**Severity:** Medium

**Description:** Every intake run — cache hit or not — generates a fresh `statement_id` and writes a new, independent set of Silver/Gold rows; there is no deduplication at the Silver/Gold layer, only at the AI-extraction-cost layer (IC-2). Confirmed: the home dashboard's headline KPIs (`get_kpis()`) are protected against this because they join against `_LATEST_RUN_PER_VENDOR` before summing — but that protection is **incidental**, a side effect of "show current state" rather than a deliberate anti-duplication design. The Reports page (`get_all_runs()`) is confirmed unprotected and would show duplicate-looking entries for the same vendor/period.

**Threatened invariant:** IC-16

**Affected modules:** M-014 (source of the gap), M-011 (`get_kpis()` — incidental protection; `get_all_runs()` — unprotected)

**Severity rationale:** Downgraded from an initial P1-level concern after precise verification — the scenario that would justify Critical/High (visibly doubled vendor total exposure on the primary dashboard) does not occur today, thanks to the incidental protection above. What remains real: genuine duplicate rows in the raw Gold tables, a confusing (not numerically-inflated) Reports-page symptom, and no safety net for any future feature that aggregates across a vendor's full run history without replicating `get_kpis()`'s specific filtering pattern.

**Mitigation (current):** `_LATEST_RUN_PER_VENDOR`, incidentally, on the one view that matters most.

**Recommended action:** (1) Document explicitly, in code comments on `get_kpis()`/`get_recent_runs()`/`get_vendor_summaries()`, that the `_LATEST_RUN_PER_VENDOR` join is load-bearing for duplicate-upload safety, not just a "latest state" convenience — so a future refactor doesn't remove it without recognizing the connection. (2) Decide whether "each upload = an independent reconciliation run, by design" is the intended model, or whether true document-level dedup should be added at the Silver/Gold layer.

---

## R-004 — No liveness/watchdog on the background worker thread; no stale-job requeue logic

**Severity:** Medium

**Description:** `web/worker.py`'s (M-013) polling loop is resilient to *exceptions within* its own iterations (a broad `try/except Exception` around the loop body), but nothing external monitors whether the thread itself is still alive, and nothing requeues a job stuck in `PROCESSING` past any timeout. Since `claim_next_pending_job()` (M-011)'s atomic single-job guard blocks *any* new job from being claimed while one is `PROCESSING`, a worker that dies mid-job (or a job that hangs beyond the 30-minute subprocess timeout in an unexpected way) stalls the entire queue indefinitely — not just that one job.

**Threatened invariant:** IC-19 (the same guard that correctly prevents double-claiming is what makes this a single point of stall)

**Affected modules:** M-013, M-011

**Mitigation (current):** The 30-minute subprocess timeout (`_run_job()`) bounds *most* hang scenarios, and the worker's own exception handling prevents a single bad job from crashing the loop — but neither addresses the thread itself dying, or a job somehow left in `PROCESSING` by a process restart/crash outside the subprocess's own lifecycle.

**Recommended action:** Implement the stale-job requeue logic Implementation Context's Phase 3 spec already describes ("any job stuck in PROCESSING past a timeout... gets automatically re-queued") but which was never actually built — confirmed absent from every job-related function in `web/queries.py`.

**Engineer decision (2026-07-24):** Accepted as-is for now. Will be addressed as part of Sprint 1 enhancement #5 (parallel workers), since that work touches this exact code path anyway — not worth a standalone fix ahead of it.

---

## R-005 — The job pipeline depends on an untested, untyped string contract between the orchestrator's print output and the worker's regex parser

**Severity:** Medium

**Description:** `scripts/run_full_pipeline.py` (M-018) prints `"Statement ID: {statement_id}"` as its only mechanism for communicating the resulting statement_id back to its caller; `web/worker.py` (M-013) extracts this via `STATEMENT_ID_RE = re.compile(r"Statement ID:\s*(\S+)")` against the subprocess's combined stdout/stderr. No test asserts this contract holds. A future reformatting of that one print line — for readability, localization, or unrelated cleanup — would silently break the worker's ability to determine which statement a completed job produced, and the job would be marked FAILED even if the underlying pipeline run fully succeeded (confirmed: `if result.returncode != 0 or not match:` treats a missing regex match identically to a nonzero exit code).

**Threatened invariant:** IC-18

**Affected modules:** M-018 (producer), M-013 (consumer)

**Distinct from R-004:** this is a separate fragility from the stale-job-requeue gap — one is about a job that hangs, this is about a job that *succeeds* but gets misreported as failed due to an unrelated text change elsewhere in the codebase. Keeping them as separate entries per instruction, since they have different root causes, different triggers, and different fixes.

**Mitigation (current):** None — purely incidental that this hasn't broken yet.

**Recommended action:** Replace the string-based signal with a structured one — e.g. writing the statement_id to a small JSON file or a dedicated line the worker greps for with a version-stamped format, or (better) having `run_full_pipeline.py` return/exit with a machine-readable result rather than relying on log-scraping.

---

## R-006 — Azure SQL schema provisioning happens outside the tracked, numbered migration system, with no automated sync check

**Severity:** Medium

**Description:** `src/lakehouse/migrations.py` (M-034) is the tracked, numbered, transaction-safe source of truth for schema history — but it only ever runs against SQLite. Azure SQL schema is provisioned by `src/lakehouse/azure_sql_migrations.py` (M-035), a separate one-shot creator whose `TABLES`/`COLUMNS` dicts must be **manually** kept in sync with every new SQLite migration file. Nothing in the codebase checks that the two stay aligned.

**Threatened invariant:** IC-12

**Affected modules:** M-034, M-035

**Mitigation (current):** Confirmed currently in sync — migrations 004-006 (`users`, `jobs`, `claim_token`) are correctly mirrored in `azure_sql_migrations.py`'s `TABLES`/`COLUMNS` dicts as of this session (verified by direct comparison, not assumed).

**Recommended action:** Add an automated check (e.g. a test that diffs the SQLite schema derived from `migrations/*.sql` against `azure_sql_migrations.py`'s declared `TABLES`/`COLUMNS`) so a future migration added to one side without the other is caught before deployment, not discovered as a production incident.

---

## R-007 — Hardcoded fallback admin credential in `web/routers/auth.py`

**Severity:** High

**Description:** `web/routers/auth.py` (M-001) contains a hardcoded fallback admin credential, used when no matching row exists in the `users` table. Per the standing rule established this session, the literal value is not reproduced in this or any other `discovery/` artifact — see the source file directly for the exact value. This is a production auth-bypass path: anyone with knowledge of the fallback credential (or who obtains it by reading the source, a config diff, or a leaked build artifact) can authenticate as an admin, regardless of what's actually provisioned in the `users` table.

**Threatened invariant:** No formal IC-N currently covers authentication enforcement directly — a candidate for a future invariant, recorded here first as the concrete risk it represents.

**Affected modules:** M-001 (`web/routers/auth.py`)

**Mitigation (current):** None. The fallback is live in the authentication path as of this session; it is not gated behind an environment flag or disabled in any deployment-specific config that was found during this extraction.

**Recommended action:** Remove the hardcoded fallback entirely, or at minimum gate it behind an explicit `DEBUG`/`DEV_MODE` environment check that defaults to off, so it cannot be reached in a production deployment even if the `users` table is empty or misconfigured.

**Engineer decision (2026-07-24):** Signed off as a new formal risk entry (Stage 3, P2-S3-002). Severity confirmed High — "production auth bypass path, even if intended as temporary."

---

## R-008 — Hardcoded session secret in `web/app.py`

**Severity:** High

**Description:** `web/app.py` (M-009) sets `WEB_SESSION_SECRET` to a hardcoded literal value used to sign session cookies, rather than reading it from an environment variable or secret store. Per the standing rule established this session, the literal value is not reproduced in this or any other `discovery/` artifact — see the source file directly. If this value is known or leaked (e.g. via source access, a public repo, or a shared build image), anyone can forge a valid session cookie for any user, including admin accounts — this is the same class of risk as R-007, but at the session-integrity layer rather than the login-credential layer.

**Threatened invariant:** No formal IC-N currently covers session-secret management directly — a candidate for a future invariant, recorded here first as the concrete risk it represents.

**Affected modules:** M-009 (`web/app.py`)

**Mitigation (current):** None found. The value is a fixed literal in source, identical across every environment that runs this code unmodified.

**Recommended action:** Move `WEB_SESSION_SECRET` to an environment variable or secret store, generated uniquely per deployment, with no hardcoded default (or a default that only applies to local/dev and is loudly rejected in anything resembling a production config).

**Engineer decision (2026-07-24):** Signed off as a new formal risk entry (Stage 3, P2-S3-002). Severity confirmed High — "if compromised, forges any user's session; same class of risk as R-007."

---

## Summary Table

| Risk ID | Description | Severity | Threatened Invariant | Affected Modules |
|---|---|---|---|---|
| R-001 | Confidence gate defeated for 4/6 providers incl. active primary | Critical | IC-15 | M-023, M-024, M-025, M-026, M-014 |
| R-002 | Missing totals-row filter in 3 LLM clients | High | IC-20 | M-023, M-025, M-026 |
| R-003 | Duplicate-upload row-level duplication in Gold tables | Medium | IC-16 | M-014, M-011 |
| R-004 | No worker liveness/watchdog, no stale-job requeue | Medium | IC-19 | M-013, M-011 |
| R-005 | Fragile "Statement ID:" string contract | Medium | IC-18 | M-018, M-013 |
| R-006 | Azure SQL schema provisioning outside tracked migrations | Medium | IC-12 | M-034, M-035 |
| R-007 | Hardcoded fallback admin credential in auth.py | High | — (candidate for future invariant) | M-001 |
| R-008 | Hardcoded session secret in web/app.py | High | — (candidate for future invariant) | M-009 |

Session E Part 2 (RISK_REGISTER.md) complete, plus Stage 3 additions (R-007, R-008) per engineer sign-off, 2026-07-24. All P1/P2 Stage 3 items are now closed — see `discovery/ANNOTATION_CHECKLIST.md`.
