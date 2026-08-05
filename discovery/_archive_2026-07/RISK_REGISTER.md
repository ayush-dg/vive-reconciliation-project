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

**Partially mitigated — fixed for the active provider (Claude Sonnet) on 2026-07-24; Gemini and Mistral remain affected but are currently dormant.** `src/ai/claude_sonnet_client.py`'s `EXTRACTION_PROMPT` now asks the model for a genuine per-row `"confidence"` field with explicit calibration guidance; `_row_to_invoice()` reads it via a new `_parse_confidence()` helper instead of assigning the hardcoded `ROW_CONFIDENCE = 0.75` constant. A missing or unparseable/out-of-range confidence value falls back to `FALLBACK_LINE_CONFIDENCE = 0.40` — below the `0.60` threshold — so an untrustworthy signal still routes to human review rather than silently passing. Verified against 3 real sample PDFs post-fix: `ASTCollex0526.pdf` came back uniformly `0.99` across 202 rows (a clean digital PDF — manually cross-checked 8 rows against the source, zero ambiguity found, so this is plausibly honest rather than a lazy default, though a uniform result alone couldn't rule that out); `KSI_Noakers_053126.pdf` came back with two distinct values, `0.93` and `0.95`, across 69 rows; and — the decisive evidence — `Very_Dirty_Scanned_Reconciliation.pdf`, a genuinely degraded document, came back at `0.35-0.60` across 132 rows (6 distinct values). The sharp drop on the hard document, contrasted with the two clean ones, confirms the model is genuinely discriminating by real difficulty rather than landing on a new fixed habitual default. Full details in `discovery/components/C10_claude_sonnet_client.md`'s Known Fragility section. **`GeminiClient` (M-025) and `MistralClient` (M-026) were deliberately left untouched this pass** — same bug, confirmed still present, but both remain dormant (not in the active `provider_chain`). Severity held at Critical, not downgraded, since two of the four originally-affected providers are still actively broken, and the mitigation for the third (`DocumentIntelligenceClient`, M-024) was never in scope (a structurally different, no-model-signal case per IC-15's scoping note).

---

## R-002 — No totals/summary-row exclusion in the three actively-registered LLM extraction clients

**Severity:** High

**Description:** `pdfplumber_fallback.py` (M-028) explicitly filters out rows whose invoice number contains `"total"`/`"balance"`/`"subtotal"` before they're written as invoice lines — and `document_intelligence_client.py` (M-024) inherits this protection by importing the same helper directly. **`ClaudeSonnetClient` (M-023), `GeminiClient` (M-025), and `MistralClient` (M-026) have no equivalent filter at either the prompt or code level**, confirmed by direct grep and inspection of each file's row-processing loop (`_row_to_invoice`/`_rows_to_invoices`, which convert every row unconditionally).

**Threatened invariant:** IC-20 (added at Stage 3, 2026-07-24, engineer sign-off — see `discovery/ANNOTATION_CHECKLIST.md` P2-S3-001). Originally recorded here with no formal invariant; now formalized.

**Affected modules:** M-023, M-025, M-026

**Live confirmation:** Not yet observed to have actually occurred in either database (no confirmed instance of a totals row being ingested as a fake invoice was found in this session's data checks) — this is a **real, unmitigated exposure**, not a confirmed incident. Severity is set on the exposure, not on an observed failure, per instruction not to soften based on absence of a caught incident.

**Mitigation (current):** None for the three affected clients. A vendor statement whose totals/summary row contains a plausible-looking invoice-number-shaped value and a dollar amount would be silently extracted and would proceed through validation exactly like a real invoice (since it would likely have both required fields populated).

**Recommended action:** Port `pdfplumber_fallback.py`'s keyword-based totals-row filter (or an equivalent) into `_row_to_invoice()`/`_rows_to_invoices()` for all three affected clients, or add an explicit prompt instruction (as `VISION_PROMPT` already has) requiring the model to separate a grand total from invoice lines.

**Partially mitigated — fixed for the active provider (Claude Sonnet) on 2026-07-24; Gemini and Mistral remain affected but are currently dormant.** `src/ai/claude_sonnet_client.py` now ports the exact recommended action above for M-023 only: a new `_is_totals_row()` check (same `"total"`/`"balance"`/`"subtotal"` keywords as `pdfplumber_fallback.py:_extract_invoice_row()`) drops any row whose final `invoice_number` matches, before it's ingested as an invoice line — `_row_to_invoice()` returns `None` for such a row and `_rows_to_invoices()` filters it out. `EXTRACTION_PROMPT` was also updated with an explicit instruction not to report a grand-total/subtotal/balance-forward row as an invoice line, mirroring `VISION_PROMPT`'s original approach. Full test suite (`tests/test_claude_sonnet_client.py`, 37 tests) passes unchanged. **`GeminiClient` (M-025) and `MistralClient` (M-026) were deliberately left untouched this pass** — same bug, confirmed still present, both dormant (not in the active `provider_chain`). Severity held at High, not downgraded, since two of the three originally-affected clients remain unfixed.

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

**Update (2026-07-25) — blast radius narrowed by the worker-pool change referenced above, gap itself unchanged.** The parallel-workers enhancement this entry anticipated has now landed, and it included the exact `claim_next_pending_job()` scoping change this risk's own "Threatened invariant" (IC-19) references — see `discovery/INVARIANT_CATALOGUE.md`'s rewritten IC-19. A job stuck in PROCESSING now only blocks new claims for *that same `pdf_filename`*, not the entire queue — other filenames remain claimable by the pool's other threads. This is a real, engineer-approved improvement to this risk's severity (no longer a single point of stall for the whole system), but it does not close the underlying gap: no stale-job requeue logic was added, so a stuck job for one filename still blocks all future resubmissions of that filename indefinitely. Severity held at Medium — the specific incident this entry describes (one filename's queue wedged forever) is still fully reachable, just no longer system-wide.

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

**Second location carrying the same value (confirmed 2026-07-24, verification pass):** `migrations/004_add_users_table.sql`'s own header comment also states the literal credential, explaining why the fallback is kept ("kept deliberately until database-backed users are confirmed working"). This means removing the fallback from `auth.py` alone would not purge the literal value from the repository/git history — the migration file would need the same treatment (redact or remove the literal from the comment, keep the rationale).

**Threatened invariant:** No formal IC-N currently covers authentication enforcement directly — a candidate for a future invariant, recorded here first as the concrete risk it represents.

**Affected modules:** M-001 (`web/routers/auth.py`); also `migrations/004_add_users_table.sql` (not a registered M-NNN module — a schema/migration file — but a second source location carrying the identical literal credential value in its header comment)

**Mitigation (current):** None. The fallback is live in the authentication path as of this session; it is not gated behind an environment flag or disabled in any deployment-specific config that was found during this extraction.

**Recommended action:** Remove the hardcoded fallback entirely, or at minimum gate it behind an explicit `DEBUG`/`DEV_MODE` environment check that defaults to off, so it cannot be reached in a production deployment even if the `users` table is empty or misconfigured. When doing so, also update `migrations/004_add_users_table.sql`'s header comment to drop the literal value (the rationale for keeping the fallback can stay; the credential itself doesn't need to remain in the comment).

**Engineer decision (2026-07-24):** Signed off as a new formal risk entry (Stage 3, P2-S3-002). Severity confirmed High — "production auth bypass path, even if intended as temporary."

---

## R-008 — Hardcoded session secret in `web/app.py`

**Severity:** High

**Description:** `web/app.py` (M-009) reads `WEB_SESSION_SECRET` from the environment via `os.getenv("WEB_SESSION_SECRET", "<hardcoded literal>")` — the mechanism itself does attempt an environment-variable override before falling back to a hardcoded literal default. **The gap is that nothing actually sets `WEB_SESSION_SECRET` today**: confirmed absent from both `.env` and `.env.example` (not even documented there as a variable to configure), so the hardcoded fallback is what's genuinely in effect in every environment that runs this code unmodified, right now — functionally equivalent to a hardcoded secret in practice, even though the code isn't structurally incapable of reading one. Nothing warns or fails loudly when the variable is missing, so this is easy to overlook. If this value is known or leaked (e.g. via source access, a public repo, or a shared build image), anyone can forge a valid session cookie for any user, including admin accounts — this is the same class of risk as R-007, but at the session-integrity layer rather than the login-credential layer.

**Correction (2026-07-24, verification pass):** An earlier version of this entry stated the code "sets `WEB_SESSION_SECRET` to a hardcoded literal value... rather than reading it from an environment variable" — that overstated the gap. The code does read the environment variable first; the real problem is that the variable is never configured or documented, not that the override path doesn't exist. Corrected here to match the actual code, per direct re-verification of `web/app.py`.

**Threatened invariant:** No formal IC-N currently covers session-secret management directly — a candidate for a future invariant, recorded here first as the concrete risk it represents.

**Affected modules:** M-009 (`web/app.py`)

**Mitigation (current):** None found. The environment-variable override path exists in the code but is unused — `WEB_SESSION_SECRET` is unset in `.env` and undocumented in `.env.example`, so the hardcoded literal is what's actually in effect, identical across every environment that runs this code unmodified.

**Recommended action:** Actually set `WEB_SESSION_SECRET` to a unique, generated value per deployment (the read path already supports this — it just needs to be configured), document it in `.env.example`, and make the hardcoded default loudly rejected (e.g. refuse to start, or log a prominent warning) in anything resembling a production config, rather than silently falling back.

**Engineer decision (2026-07-24):** Signed off as a new formal risk entry (Stage 3, P2-S3-002). Severity confirmed High — "if compromised, forges any user's session; same class of risk as R-007."

---

## R-009 — Event Grid auto-intake webhook had no authentication at all; now fixed in code, not yet deployed

**Severity:** Fixed in code (2026-07-25) — was Critical/High while open. Not closed: deployment is still pending, tracked below as an action item, not treated as a resolved risk.

**Description:** `web/routers/intake_trigger.py` (M-046, added 2026-07-24 as part of the Event Grid auto-intake enhancement) had no authentication mechanism whatsoever — no signature check, no shared secret, no Azure AD token. The one thing that looked like a check (`_validation_response()`, echoing back Event Grid's `validationCode`) is a delivery-handshake formality, not authentication: it proves the caller can read a value out of its own request and echo it back, which any caller — not just genuine Event Grid — can do. A second, independent finding in the same review: `src/storage/blob_client.py` (M-039) `download_pdf()` derived the *container* to download from directly out of the caller-supplied blob URL rather than pinning it to the configured dropzone container — so even setting auth aside, a crafted request could point the download at a different container than `incoming-statements` if the dropzone connection string had read access there.

**Exposure while open:** Anyone who found the `/api/intake-trigger` URL could POST arbitrary JSON. Garbage payloads (fabricated blob URLs) failed harmlessly at the download step and never reached Claude Sonnet, but every request still cost a full unauthenticated Azure SDK auth handshake per event, with no size or rate limit — an unconditional compute/DoS surface. If an attacker could reference a real, existing, distinct-content PDF blob the dropzone connection string could read, each such submission would trigger one real subprocess run and one real Claude Sonnet extraction call — a genuine AI-cost-inflation vector, bounded only by `VIVE_MAX_CONCURRENT_AI_CALLS` (see R-010/IC-21), not by any request-level throttle. See the 2026-07-25 conversation record for the full threat-model writeup; not reproduced verbatim here.

**Threatened invariant:** No formal IC-N covered inbound webhook authentication before this session — a gap of the same shape as R-007/R-008 (a real, externally-reachable bypass with no formal invariant tracking it), now closed at the mechanism level by IC-19/IC-21's neighboring infrastructure but not itself promoted to a numbered invariant, since it's a standard auth control rather than a system-specific behavioral guarantee.

**Affected modules:** M-046 (`web/routers/intake_trigger.py`), M-039 (`src/storage/blob_client.py`)

**Fix (code-complete, 2026-07-25):**
1. **Container pinned** — `BlobStorageClient.download_pdf()` no longer trusts the URL's container segment. It parses the URL, refuses outright if the parsed container doesn't equal `self.container_name`, and even on a match passes `self.container_name` (not the parsed string) to the actual download call — a future refactor bug in the comparison can't reopen the hole.
2. **Real authentication added** — `_is_authorized()` checks a shared secret (`VIVE_EVENTGRID_WEBHOOK_SECRET`) against an `x-vive-webhook-secret` header via `hmac.compare_digest` (constant-time), enforced before anything else in the handler runs, including the validation handshake. Fails closed: if the secret isn't configured at all, every request is rejected (401) — there is no "unconfigured means open" fallback.
3. **Request cap added** — `MAX_EVENTS_PER_REQUEST = 100`, checked after auth but before any blob processing; closes the unconditional-DoS angle independent of the auth fix.

Verified: `tests/test_blob_client.py` and `tests/test_intake_trigger.py` both pass (30 tests total, 8 new — container-mismatch rejection, auth-missing/wrong/unconfigured-fails-closed, validation-event-still-requires-auth, over-cap/at-cap). Full project test suite run clean apart from one pre-existing, unrelated Windows tempfile-locking failure in `tests/test_ai_clients.py`.

**Why this isn't closed yet — deployment action item, not a resolved risk:** the fix requires `VIVE_EVENTGRID_WEBHOOK_SECRET` to be generated and configured as a static (secret) delivery header on the actual Azure Event Grid subscription — an infrastructure step, not a code step. **That configuration has not happened.** It is blocked on Azure permissions, pending Ashrith. Until it's done, the webhook will fail-closed (401) against any real Event Grid delivery, which is the correct, safe default — but it also means the auto-intake enhancement (ENH-001) cannot actually go live yet. Do not mark this risk CLOSED until (a) the secret is generated, (b) it's configured on the Event Grid subscription's delivery-attribute settings, and (c) a real end-to-end delivery has been confirmed to succeed.

**Recommended action / follow-up:** Track "generate `VIVE_EVENTGRID_WEBHOOK_SECRET` and configure it on the Event Grid subscription" as an open action item against ENH-001, owned pending Ashrith's Azure permissions being resolved — not as an accepted/deferred risk in the R-001/R-004 sense, since the code-side fix is already done and waiting purely on an infra step.

---

## R-010 — AI-call concurrency limiter permanently loses a slot if a process holding one is killed

**Severity:** Medium

**Description:** `src/ai/concurrency_limiter.py` (M-047, added 2026-07-24) caps concurrent Claude Sonnet calls across the worker pool via lock files in `lakehouse/ai_call_slots/` (one per slot, exclusively created via `os.O_CREAT | os.O_EXCL`, released in a `finally` block). If the process holding a slot is killed outright — not a normal Python exception, which the `finally` still handles — rather than exiting normally (e.g. an OS-level kill, an out-of-memory kill, a hard container restart), that slot's lock file is never removed. Capacity is then permanently reduced by one, with no automatic detection or recovery — only a manual deletion of the stale file restores it.

**Threatened invariant:** IC-21 (this module's own cap) — this is that invariant's one documented failure mode, not a violation of it; the cap itself still holds (concurrency never exceeds the configured limit), it just silently shrinks over time under this specific failure condition.

**Affected modules:** M-047 (`src/ai/concurrency_limiter.py`)

**Mitigation (current):** None automated. The module's own docstring explicitly names this as a known, accepted limitation rather than something engineered around — the same posture this register already took with R-004's stale-job gap (a real, understood tradeoff, not an oversight). Each lock file's content is just the holding process's PID, written but never checked for liveness by any other code path.

**Recommended action:** If this becomes a real operational problem (repeated capacity loss observed, not just a theoretical possibility), the lowest-effort fix is a liveness check — since each lock file already stores the holding PID, a slot-acquisition attempt that finds an existing lock file could check whether that PID is still alive and reclaim the slot if not, rather than requiring a human to notice and manually delete the file. Not recommended to build ahead of an observed incident, consistent with this project's general posture on speculative hardening (see IC-9).

---

## R-011 — `friendly_dt()` (`web/deps.py`) hardcodes IST for all displayed timestamps

**Severity:** High — real, confirmed, user-facing; not theoretical.

**Description:** Every timestamp rendered through the `friendly_dt` Jinja2 filter converts it to a hardcoded `IST = timezone(timedelta(hours=5, minutes=30))` before display, regardless of where the AP team viewing the page actually is. Storage itself is correct — every timestamp is written as UTC (`datetime.now(timezone.utc).isoformat()`, per `queries.py`) — only the display layer is wrong.

**How this was surfaced:** During the 2026-07-27 Stage 3 reconciliation, via direct source read (`web/deps.py:118-137`) and a template call-site trace — not from a user-reported incident. This is `discovery/MODULE_CONTRACTS.md`'s cross-cutting finding #8 ("`web/deps.py`'s (M-010) `friendly_dt()` hardcodes India Standard Time for all displayed timestamps — confirmed by source, not yet confirmed against the actual AP team's location; flag for engineer confirmation at Session D/E, not assumed to be a defect"), now formally resolved into this risk entry rather than left dangling.

**Threatened invariant:** None formal — no IC-N currently covers display-timezone correctness.

**Affected modules:** M-010 (`web/deps.py`)

**Mitigation (current):** None.

**Recommended action:** Make the display timezone configurable via an env var (e.g. `VIVE_DISPLAY_TIMEZONE`, default US Eastern given VIVE Collision's Northeast US location) rather than hardcoding a replacement timezone.

**Status:** Open — not fixed. This entry is a paperwork/tracking step only; no code change made.

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
| R-007 | Hardcoded fallback admin credential in auth.py (also in migrations/004 comment) | High | — (candidate for future invariant) | M-001, migrations/004_add_users_table.sql |
| R-008 | Hardcoded session secret in web/app.py | High | — (candidate for future invariant) | M-009 |
| R-009 | Event Grid webhook had no auth + container not pinned — fixed in code 2026-07-25, deployment (secret config on Event Grid subscription) still pending | Fixed in code / deployment pending | — (candidate for future invariant) | M-046, M-039 |
| R-010 | AI-call concurrency limiter permanently loses a slot if a process holding one is killed | Medium | IC-21 | M-047 |
| R-011 | friendly_dt() (web/deps.py) hardcodes IST for all displayed timestamps | High | — (no formal invariant) | M-010 |

Session E Part 2 (RISK_REGISTER.md) complete, plus Stage 3 additions (R-007, R-008) per engineer sign-off, 2026-07-24, plus the 2026-07-25 scoped refresh additions (R-009, R-010, and the R-004 blast-radius update note) covering the worker pool, Event Grid auto-intake, and AI-call concurrency limiter built since, plus the 2026-07-27 Stage 3 reconciliation addition (R-011, resolving MODULE_CONTRACTS.md cross-cutting finding #8). All P1/P2 Stage 3 items are now closed — see `discovery/ANNOTATION_CHECKLIST.md`; the 2026-07-27 Stage 3 second pass (see ANNOTATION_CHECKLIST.md) resolved P1-S3-006/007/008 and added R-011, which remains OPEN pending a code fix.
