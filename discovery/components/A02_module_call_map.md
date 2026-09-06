## Module Roster — VIVE Statement Reconciliation
Generated: 2026-09-02 by BCE Stage 2 Session A (CC)
Note: these IDs are permanent. Do not reassign at later sessions.

| ID | Module Name | Source File | Layer |
|---|---|---|---|
| M-001 | auth.ts | src/lib/auth.ts | infra |
| M-002 | currentUser.ts | src/lib/currentUser.ts | infra |
| M-003 | db.ts | src/lib/db.ts | infra |
| M-004 | session.ts | src/lib/session.ts | infra |
| M-005 | storage.ts | src/lib/storage.ts | infra |
| M-006 | schema.ts | src/lib/schema.ts | infra |
| M-007 | migrate.ts | src/lib/migrate.ts | infra |
| M-008 | fabricLakehouse.ts | src/lib/fabricLakehouse.ts | infra |
| M-009 | toastStore.ts | src/lib/toastStore.ts | infra |
| M-010 | vendorDisplay.ts | src/lib/vendorDisplay.ts | infra |
| M-011 | documents.ts | src/lib/documents.ts | serving |
| M-012 | documentStatus.ts | src/lib/documentStatus.ts | serving |
| M-013 | documentDetail.ts | src/lib/documentDetail.ts | serving |
| M-014 | homeSummary.ts | src/lib/homeSummary.ts | serving |
| M-015 | extraction.ts | src/lib/extraction.ts | serving |
| M-016 | extractionMethodSummary.ts | src/lib/extractionMethodSummary.ts | serving |
| M-017 | matchingInvocation.ts | src/lib/matchingInvocation.ts | serving |
| M-018 | exceptionDetail.ts | src/lib/exceptionDetail.ts | serving |
| M-019 | exceptionsList.ts | src/lib/exceptionsList.ts | serving |
| M-020 | exceptionWriter.ts | src/lib/exceptionWriter.ts | serving |
| M-021 | vendorIdentification.ts | src/lib/vendorIdentification.ts | pipeline |
| M-022 | extractionPipeline.ts | src/lib/extractionPipeline.ts | pipeline |
| M-023 | validationGate.ts | src/lib/validationGate.ts | pipeline |
| M-024 | silverNormalization.ts | src/lib/silverNormalization.ts | pipeline |
| M-025 | matchingPipeline.ts | src/lib/matchingPipeline.ts | pipeline |
| M-026 | deterministicMatching.ts | src/lib/deterministicMatching.ts | pipeline |
| M-027 | aiResidualMatching.ts | src/lib/aiResidualMatching.ts | pipeline |
| M-028 | aiProvider.ts | src/lib/aiProvider.ts | pipeline |
| M-029 | pdfplumberExtractor.ts | src/lib/pdfplumberExtractor.ts | pipeline |
| M-030 | pdfplumberOcrFallback.ts | src/lib/pdfplumberOcrFallback.ts | pipeline |
| M-031 | knownVendorExtractors.ts | src/lib/knownVendorExtractors.ts | pipeline |
| M-032 | extractAdas.ts | src/lib/extractAdas.ts | pipeline |
| M-033 | extractAstech.ts | src/lib/extractAstech.ts | pipeline |
| M-034 | extractEmpire.ts | src/lib/extractEmpire.ts | pipeline |
| M-035 | extractFredBeans.ts | src/lib/extractFredBeans.ts | pipeline |
| M-036 | extractKeystone.ts | src/lib/extractKeystone.ts | pipeline |
| M-037 | extractLiaAutoGroup.ts | src/lib/extractLiaAutoGroup.ts | pipeline |
| M-038 | extractPrecision.ts | src/lib/extractPrecision.ts | pipeline |
| M-039 | extractQuirk.ts | src/lib/extractQuirk.ts | pipeline |
| M-040 | extractWilberts.ts | src/lib/extractWilberts.ts | pipeline |
| M-041 | vendorSchema.ts | src/lib/vendorSchema.ts | infra |
| M-042 | legalEntities.ts | src/lib/legalEntities.ts | infra |
| M-043 | proxy.ts | src/proxy.ts | route |
| M-044 | api/documents/route.ts | src/app/api/documents/route.ts | route |
| M-045 | api/documents/[id]/detail/route.ts | src/app/api/documents/[id]/detail/route.ts | route |
| M-046 | api/documents/[id]/extract/route.ts | src/app/api/documents/[id]/extract/route.ts | route |
| M-047 | api/documents/[id]/match/route.ts | src/app/api/documents/[id]/match/route.ts | route |
| M-048 | api/exceptions/route.ts | src/app/api/exceptions/route.ts | route |
| M-049 | api/exceptions/[id]/route.ts | src/app/api/exceptions/[id]/route.ts | route |
| M-050 | api/exceptions/vendor/[vendorSlug]/route.ts | src/app/api/exceptions/vendor/[vendorSlug]/route.ts | route |
| M-051 | api/health/route.ts | src/app/api/health/route.ts | route |
| M-052 | api/home-summary/route.ts | src/app/api/home-summary/route.ts | route |
| M-053 | api/matching/run-batch/route.ts | src/app/api/matching/run-batch/route.ts | route |
| M-054 | login/actions.ts | src/app/login/actions.ts | route |
| M-060 | layout.tsx (root) | src/app/layout.tsx | layout |
| M-061 | page.tsx (root) | src/app/page.tsx | page |
| M-062 | login/page.tsx | src/app/login/page.tsx | page |
| M-063 | LoginForm.tsx | src/app/login/LoginForm.tsx | component |
| M-064 | (app)/layout.tsx | src/app/(app)/layout.tsx | layout |
| M-065 | (app)/loading.tsx | src/app/(app)/loading.tsx | layout |
| M-066 | (app)/error.tsx | src/app/(app)/error.tsx | layout |
| M-067 | home/page.tsx | src/app/(app)/home/page.tsx | page |
| M-068 | HomeView.tsx | src/app/(app)/home/HomeView.tsx | component |
| M-069 | upload/page.tsx | src/app/(app)/upload/page.tsx | page |
| M-070 | UploadForm.tsx | src/app/(app)/upload/UploadForm.tsx | component |
| M-071 | exceptions/page.tsx | src/app/(app)/exceptions/page.tsx | page |
| M-072 | ExceptionsVendorListView.tsx | src/app/(app)/exceptions/ExceptionsVendorListView.tsx | component |
| M-073 | exceptions/[vendorSlug]/page.tsx | src/app/(app)/exceptions/[vendorSlug]/page.tsx | page |
| M-074 | ExceptionVendorDetailView.tsx | src/app/(app)/exceptions/[vendorSlug]/ExceptionVendorDetailView.tsx | component |
| M-075 | documents/[id]/page.tsx | src/app/(app)/documents/[id]/page.tsx | page |
| M-076 | DocumentDetailView.tsx | src/app/(app)/documents/[id]/DocumentDetailView.tsx | component |
| M-077 | dev-test-error/page.tsx | src/app/(app)/dev-test-error/page.tsx | page |
| M-078 | dev-test-loading/page.tsx | src/app/(app)/dev-test-loading/page.tsx | page |
| M-079 | dev-test-toast/page.tsx | src/app/(app)/dev-test-toast/page.tsx | page |
| M-080 | IconSprite.tsx | src/components/IconSprite.tsx | component |
| M-081 | InlineLoadError.tsx | src/components/InlineLoadError.tsx | component |
| M-082 | Sidebar.tsx | src/components/Sidebar.tsx | component |
| M-083 | ToastProvider.tsx | src/components/ToastProvider.tsx | store |
| M-084 | batchUploadSequencing.ts | src/lib/batchUploadSequencing.ts | module (pure function) |

**M-084 added 2026-09-06 (SPRINT-001 BCE refresh, ENH-001 Task 2.2).** Exports
`runBatchUploadSequenced(files, registerFile, extractDocument)` — a caller-injected pure
function, no direct module dependencies of its own (registration/extraction are passed in
by M-070, not imported). Policy: a single-file batch fires extraction without awaiting
(fire-and-forget, matching pre-ENH-001 behavior byte-for-byte); a 2+-file batch awaits
each file's full register+extract cycle before the next file's registration begins —
"no two extractions in flight simultaneously." Extracted as a standalone module
specifically so this sequencing guarantee could be directly unit-tested
(`scripts/test_batch_upload_sequencing.sh`, 12/12) rather than only inferable from
Playwright network waterfalls.
| M-070 --[CALLS]--> M-084 | src/app/(app)/upload/UploadForm.tsx (handleSubmit) | Sync (in-process, awaited per its own policy above) |

This roster is the canonical ID-to-module mapping for all subsequent sessions. Sessions B,
C, D, and E must reference modules by M-NNN in all relationship fields — never by prose
name.

**IDs 055–059 skipped deliberately** (reserved gap between the backend and UI ranges from
the two parallel tracing passes this session used — not an error, no modules omitted;
confirmed both passes' file globs matched their target directories exactly, with zero
unlisted files found in either pass).

---

## 1. Internal Call Table

| Edge | Call Site (file:line) | Sync/Async |
|---|---|---|
| M-001 --[CALLS]--> M-003 | src/lib/auth.ts:35 | Sync |
| M-001 --[CALLS]--> M-003 | src/lib/auth.ts:37 | Sync |
| M-001 --[CALLS]--> M-003 | src/lib/auth.ts:54 | Async |
| M-002 --[CALLS]--> M-004 | src/lib/currentUser.ts:10 | Async |
| M-007 --[CALLS]--> M-003 | src/lib/migrate.ts:34 | Sync |
| M-007 --[CALLS]--> M-003 | src/lib/migrate.ts:45 | Sync |
| M-011 --[CALLS]--> M-003 | src/lib/documents.ts:33,65,105,131,184,192,238 | Sync |
| M-011 --[CALLS]--> M-005 | src/lib/documents.ts:103 | Sync |
| M-011 --[CALLS]--> M-012 | src/lib/documents.ts:230 | Sync |
| M-012 --[CALLS]--> M-003 | src/lib/documentStatus.ts:53,60 | Sync |
| M-013 --[CALLS]--> M-003 | src/lib/documentDetail.ts:16,30,67 | Sync |
| M-013 --[CALLS]--> M-011 | src/lib/documentDetail.ts:102,109 | Sync |
| M-013 --[CALLS]--> M-012 | src/lib/documentDetail.ts:105 | Sync |
| M-013 --[CALLS]--> M-016 | src/lib/documentDetail.ts:113 | Sync |
| M-014 --[CALLS]--> M-003 | src/lib/homeSummary.ts:12,26 | Sync |
| M-014 --[CALLS]--> M-011 | src/lib/homeSummary.ts:27 | Sync |
| M-015 --[CALLS]--> M-003 | src/lib/extraction.ts:14,25 | Sync |
| M-015 --[CALLS]--> M-022 | src/lib/extraction.ts:49 | Async |
| M-016 --[CALLS]--> M-003 | src/lib/extractionMethodSummary.ts:9,18 | Sync |
| M-017 --[CALLS]--> M-003 | src/lib/matchingInvocation.ts:23,49,61,72,97 | Sync |
| M-017 --[CALLS]--> M-025 | src/lib/matchingInvocation.ts:84,127 | Async |
| M-018 --[CALLS]--> M-003 | src/lib/exceptionDetail.ts:13,48,154 | Sync |
| M-019 --[CALLS]--> M-003 | src/lib/exceptionsList.ts:21,42,78 | Sync |
| M-020 --[CALLS]--> M-003 | src/lib/exceptionWriter.ts:21,47 | Sync |
| M-021 --[CALLS]--> M-003 | src/lib/vendorIdentification.ts:29,68,85,122,137,198 | Sync |
| M-021 --[CALLS]--> M-029 | src/lib/vendorIdentification.ts:55,223 | Async |
| M-021 --[CALLS]--> M-006 | src/lib/vendorIdentification.ts:84 | Sync |
| M-021 --[CALLS]--> M-041 | src/lib/vendorIdentification.ts:117 | Async |
| M-021 --[CALLS]--> M-031 | src/lib/vendorIdentification.ts:215 | Sync |
| M-021 --[CALLS]--> {M-032..M-040} | src/lib/vendorIdentification.ts:220 (dynamic dispatch — one of 9 possible targets via M-031's registry, exact target not statically determinable) | Async (uncertain/dynamic) |
| M-021 --[CALLS]--> M-030 | src/lib/vendorIdentification.ts:226 | Async |
| M-021 --[CALLS]--> M-028 | src/lib/vendorIdentification.ts:230 | Async |
| M-022 --[CALLS]--> M-003 | src/lib/extractionPipeline.ts:26,32,46,58 | Sync |
| M-022 --[CALLS]--> M-005 | src/lib/extractionPipeline.ts:97 | Sync |
| M-022 --[CALLS]--> M-021 | src/lib/extractionPipeline.ts:98 | Async |
| M-022 --[CALLS]--> M-023 | src/lib/extractionPipeline.ts:106 | Sync |
| M-022 --[CALLS]--> M-024 | src/lib/extractionPipeline.ts:147 | Sync |
| M-024 --[CALLS]--> M-003 | src/lib/silverNormalization.ts:21,40,66 | Sync |
| M-025 --[CALLS]--> M-003 | src/lib/matchingPipeline.ts:32,40,94 | Sync |
| M-025 --[CALLS]--> M-026 | src/lib/matchingPipeline.ts:69,97 | Async/Sync |
| M-025 --[CALLS]--> M-027 | src/lib/matchingPipeline.ts:79 | Async |
| M-025 --[CALLS]--> M-020 | src/lib/matchingPipeline.ts:98 | Sync |
| M-026 --[CALLS]--> M-003 | src/lib/deterministicMatching.ts:41,99,132,221 | Sync |
| M-026 --[CALLS]--> M-008 | src/lib/deterministicMatching.ts:84,86,94,126,127 | Sync/Async |
| M-027 --[CALLS]--> M-003 | src/lib/aiResidualMatching.ts:36 | Sync |
| M-027 --[CALLS]--> M-028 | src/lib/aiResidualMatching.ts:132 | Sync |
| M-041 --[CALLS]--> M-006 | src/lib/vendorSchema.ts:16,37 | Sync |
| M-041 --[CALLS]--> M-003 | src/lib/vendorSchema.ts:56,58,62 | Sync/Async |
| M-043 --[CALLS]--> M-004 | src/proxy.ts:15,17,24,30 | Async/Sync |
| M-044 --[CALLS]--> M-011 | src/app/api/documents/route.ts:12,44,49 | Sync |
| M-044 --[CALLS]--> M-012 | src/app/api/documents/route.ts:46 | Sync |
| M-045 --[CALLS]--> M-013 | src/app/api/documents/[id]/detail/route.ts:9 | Sync |
| M-046 --[CALLS]--> M-015 | src/app/api/documents/[id]/extract/route.ts:10 | Async |
| M-047 --[CALLS]--> M-017 | src/app/api/documents/[id]/match/route.ts:10 | Async |
| M-048 --[CALLS]--> M-019 | src/app/api/exceptions/route.ts:8 | Sync |
| M-049 --[CALLS]--> M-018 | src/app/api/exceptions/[id]/route.ts:9,30,35 | Sync |
| M-050 --[CALLS]--> M-019 | src/app/api/exceptions/vendor/[vendorSlug]/route.ts:9 | Sync |
| M-051 --[CALLS]--> M-003 | src/app/api/health/route.ts:9 | Async |
| M-052 --[CALLS]--> M-014 | src/app/api/home-summary/route.ts:6 | Sync |
| M-053 --[CALLS]--> M-017 | src/app/api/matching/run-batch/route.ts:10 | Async |
| M-054 --[CALLS]--> M-001 | src/app/login/actions.ts:18,19 | Async/Sync |
| M-054 --[CALLS]--> M-004 | src/app/login/actions.ts:25,27 | Async/Sync |
| M-063 --[CALLS]--> M-054 | src/app/login/LoginForm.tsx:19 (`useActionState(loginAction, ...)`) | Async |
| M-064 --[CALLS]--> M-002 | src/app/(app)/layout.tsx:11 | Async |
| M-067 --[CALLS]--> M-011 | src/app/(app)/home/page.tsx:9 | Sync |
| M-067 --[CALLS]--> M-014 | src/app/(app)/home/page.tsx:10 | Sync |
| M-068 --[CALLS]--> M-083 | src/app/(app)/home/HomeView.tsx:60,88,94,97,100,117,123,126,129 | Sync |
| M-068 --[CALLS]--> M-044 | src/app/(app)/home/HomeView.tsx:69 (fetch /api/documents) | Async |
| M-068 --[CALLS]--> M-052 | src/app/(app)/home/HomeView.tsx:69 (fetch /api/home-summary) | Async |
| M-068 --[CALLS]--> M-046 | src/app/(app)/home/HomeView.tsx:86 (fetch POST) | Async |
| M-068 --[CALLS]--> M-047 | src/app/(app)/home/HomeView.tsx:115 (fetch POST) | Async |
| M-069 --[CALLS]--> M-011 | src/app/(app)/upload/page.tsx:9 | Sync |
| M-070 --[CALLS]--> M-083 | src/app/(app)/upload/UploadForm.tsx:39,65,71,74,77,115,120,124,145 | Sync |
| M-070 --[CALLS]--> M-044 | src/app/(app)/upload/UploadForm.tsx:42,106 (fetch GET + POST upload) | Async |
| M-070 --[CALLS]--> M-046 | src/app/(app)/upload/UploadForm.tsx:63 (fetch POST) | Async |
| M-071 --[CALLS]--> M-019 | src/app/(app)/exceptions/page.tsx:9 | Sync |
| M-072 --[CALLS]--> M-048 | src/app/(app)/exceptions/ExceptionsVendorListView.tsx:18 (fetch) | Async |
| M-072 --[CALLS]--> M-010 | src/app/(app)/exceptions/ExceptionsVendorListView.tsx:86 | Sync |
| M-073 --[CALLS]--> M-019 | src/app/(app)/exceptions/[vendorSlug]/page.tsx:20 | Sync |
| M-074 --[CALLS]--> M-049 | src/app/(app)/exceptions/[vendorSlug]/ExceptionVendorDetailView.tsx:76,112 (fetch GET+PATCH) | Async |
| M-074 --[CALLS]--> M-050 | src/app/(app)/exceptions/[vendorSlug]/ExceptionVendorDetailView.tsx:95 (fetch) | Async |
| M-074 --[CALLS]--> M-010 | src/app/(app)/exceptions/[vendorSlug]/ExceptionVendorDetailView.tsx:143,145,223,240 | Sync |
| M-075 --[CALLS]--> M-013 | src/app/(app)/documents/[id]/page.tsx:10 | Sync |
| M-076 --[CALLS]--> M-083 | src/app/(app)/documents/[id]/DocumentDetailView.tsx:31,58,64,67,70,82,88,91,94 | Sync |
| M-076 --[CALLS]--> M-045 | src/app/(app)/documents/[id]/DocumentDetailView.tsx:39 (fetch) | Async |
| M-076 --[CALLS]--> M-046 | src/app/(app)/documents/[id]/DocumentDetailView.tsx:56 (fetch POST) | Async |
| M-076 --[CALLS]--> M-047 | src/app/(app)/documents/[id]/DocumentDetailView.tsx:80 (fetch POST) | Async |
| M-079 --[CALLS]--> M-083 | src/app/(app)/dev-test-toast/page.tsx:13,17,19 | Sync |
| M-082 --[CALLS]--> M-054 | src/components/Sidebar.tsx:66 (`<form action={logoutAction}>`) | Async |
| M-083 --[CALLS]--> M-009 | src/components/ToastProvider.tsx:9,11,20,30 | Sync |

*(Repeated edges to the same callee within one file are collapsed to one row citing all
line numbers, per the "identical repeated calls" allowance — each still represents a
distinct real call site, not a single occurrence.)*

**Data-reference dependencies (not CALLS edges — value/constant reads, listed for
completeness, not counted as invocations):** M-012 reads `LOCK_STALE_AFTER_MINUTES` from
M-017; M-027 reads `CLAUDE_MODEL_ID` from M-028; M-044 reads `LEGAL_ENTITIES` from M-042;
M-031 imports/registers (wiring, not invocation) M-032–M-040's `extractVia*` functions.

**Renders (UI component composition, informational only):** M-060→M-080; M-062→M-063;
M-064→M-082,M-083; M-067→M-068; M-068→M-081; M-069→M-070; M-071→M-072; M-072→M-081;
M-073→M-074; M-074→M-081; M-075→M-076; M-076→M-081.

---

## 2. Startup Sequence

| Step | Module (M-NNN) | Action | Failure Mode |
|---|---|---|---|
| 1 | — | `next dev`/`next start` boots the Next.js server; no explicit application-level startup/init routine runs at this point | NOT DETERMINABLE FROM SOURCE (framework-internal) |
| 2 | M-003 | First call to `getDbMode()`/`getSqliteDb()`/`getFabricPool()` (triggered by the first incoming request that needs the DB) lazily initializes module-level singletons (`sqliteInstance`, `fabricPoolPromise`) | NON-FATAL if the DB is unreachable at that point — the triggering request fails, but the process does not crash; no retry/backoff observed in this pass |
| 3 | M-007 | **Not part of runtime startup.** Migrations are NOT automatically applied when the app boots — `migrate.ts` is confirmed unreachable from the request-serving call graph (Session A's own finding); must be run manually beforehand via `npm run migrate` (SQLite) or `sqlcmd` (Fabric, per `docs/EXECUTION_PLAN.md` Task 1.2's documented command) | STARTUP-FATAL by omission — if migrations were never applied, the first DB query against a missing table fails; this is an operational prerequisite, not a code safeguard |
| 4 | M-043 | `proxy.ts` runs as Edge middleware on every matched request thereafter (not a one-time startup step) — session cookie verification/refresh | NON-FATAL — unauthenticated/expired requests redirect to `/login`, no crash |

**Note:** This application has no persistent background process, daemon, or message-queue
consumer to "start" in the traditional sense — it is a stateless, request-driven Next.js
app. The table above reflects that honestly rather than inventing a richer startup sequence
than exists.

---

## 3. Async Boundaries

**Finding: this codebase has no internal producer/consumer async boundaries** (no message
queue, no background worker, no event bus). Every operation this pass traced — extraction
(M-015→M-022), matching (M-017→M-025), the scheduled-batch endpoint (M-053→M-017) — runs
synchronously within its triggering HTTP request via `await`, blocking the response until
the pipeline completes. This matches `docs/Claude.md` §4's own description: "n8n... triggers
the monthly Run Creation API call and sends completion notifications only; does not
orchestrate extraction or matching."

| Producer | Consumer | Mechanism | Failure behaviour |
|---|---|---|---|
| n8n (external, scheduled) | M-053 (`api/matching/run-batch/route.ts`) | External HTTP POST trigger, not traced by this pass (outside the codebase) | NOT DETERMINABLE FROM SOURCE — this app's side (M-053→M-017, synchronous) has no queue/retry; n8n's own retry/failure behavior is not this codebase's concern |

No other producer/consumer pairs exist in this codebase's own internal call graph — flagged
explicitly rather than fabricating boundaries that aren't there.

---

## 4. A01/A03 Reconciliation

See `discovery/TOPOLOGY.md` — Part 2 of Session A updates that file directly with
`[STAGE-2-UPDATE — 2026-09-02]` tags per corrected field, plus IP-NNN assignment in A03.
No `STAGE-2-DIVERGENCE` was found — every Stage 1 A01/A03 claim was either confirmed as
stated or given more precision (e.g. the Fabric Lakehouse read path uses a separate `tedious`
client, distinct from `mssql` used for `recon`), not contradicted.
