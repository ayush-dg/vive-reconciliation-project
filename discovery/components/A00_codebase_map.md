## A00 — Codebase Map
Produced by: BCE Stage 2 Session A0 (CC)
Date: 2026-09-02

Complete directory traversal of `src/`, `scripts/`, `migrations/`, `ui_tests/`, and
repo-root config files. Excludes `node_modules/`, `.git/`, `.next/`, `build/`, `dist/`.
Every file's purpose was read from its actual content, not inferred from its filename.

### ui_tests/
- global-setup.ts — Playwright global setup: applies local SQLite migrations, seeds two fixed test users (TEST_USERNAME/TEST_USERNAME_2) and the NetSuite/CCC fixture tables once before any spec runs, so test order/parallelism can't matter.
- sign-in.spec.ts — Verifies valid credentials for either of two distinct named users navigate to /home (OD5 multi-user), and invalid credentials show an inline error and stay on /login.
- home.spec.ts — Exercises the Home dashboard: uploads a fixture statement via the API, checks summary stats/table rendering, and the Extract/Reconcile action buttons' state transitions.
- upload.spec.ts — Verifies the Upload screen's dropzone/file-picker flow, no-Vendor-field invariant (D-L), duplicate-upload toast messaging, and auto-triggered extraction after a successful upload.
- extract-trigger.spec.ts — Covers Task 2.4's Extract trigger end-to-end via the UI: D-I separation from upload and the G5 concurrent-trigger 409 lock behavior, using real pdfplumber-parseable PDF fixtures.
- exceptions.spec.ts — Exercises the vendor-grouped Exceptions landing screen (search/filter, per-vendor drill-down) against seeded NetSuite fixture data producing real exceptions.
- exception-detail.spec.ts — Covers the per-vendor two-pane Exception detail view: filter tabs, CCC corroboration panel, NetSuite record toggle, and the resolve/flag/skip note workflow.
- document-detail.spec.ts — Covers the Document Detail screen: status badge, extraction-method summary strip, extracted-lines table, and Extract/Reconcile buttons reachable from a document's own page.
- global-elements.spec.ts — Verifies the shared Authentication Shell/sidebar (active nav items, username, logout), the disabled Admin group, and the global error/loading/toast boundaries via the dev-test-* pages.
- loading-error-consistency.spec.ts — Confirms Home, Exceptions, and Exception Detail all reuse the same global loading.tsx/error.tsx/InlineLoadError pattern rather than each screen inventing its own (Task 6.4).
- .gitkeep — Empty placeholder so the (initially empty) ui_tests/ directory is tracked by git; no content.

### scripts/
- extract_adas.py — pdfplumber-based deterministic parser for Adas Calibration Experts statements; sums "OPEN AMOUNT" (not the original invoice AMOUNT) per line, ported from a reference implementation, invoked as `<script> <pdf_path>` returning one JSON object.
- extract_astech.py — pdfplumber-based deterministic parser for asTech/Repairify statements, using pdfplumber's native table detection (ported for cost/reliability, not correctness — Claude already extracts this vendor correctly).
- extract_empire.py — pdfplumber-based deterministic parser for Empire Auto Parts statements; word-position column-bucketing plus a doc-number/description merge fixup to correct the generic path's ~81% accuracy.
- extract_fred_beans.py — pdfplumber-based deterministic parser for Fred Beans Parts statements; separates the layout's four money columns (charges/credits/amount_due/remit_amount_due) by right-edge position so only the true per-row transaction amount is summed, fixing a ~4.7x inflation bug in the generic Claude path.
- extract_keystone.py — pdfplumber-based deterministic parser for Keystone Automotive Industries statements; reconstructs the already-netted "Balance Due" column via measured column boundaries, fixing a 0%-accuracy failure in the generic path.
- extract_lia.py — pdfplumber-based deterministic parser for Lia Auto Group statements; the original Task 8.1 known-vendor extractor, using word-position/right-edge column reconstruction for a single signed "balance" amount per row.
- extract_precision.py — pdfplumber-based deterministic parser for Precision Diagnostics statements; reconstructs multi-line transactions (wrapped VIN/RO fragments across several physical lines) via column boundaries.
- extract_quirk.py — pdfplumber-based deterministic parser for Quirk Auto Group statements; filters a page watermark, classifies words by x-position, and detects department subtotal rows.
- extract_wilberts.py — pdfplumber-based deterministic parser for Wilbert's Inc. statements; merges DT# continuation rows and sums the "Balance" column (not "Amount") to correctly capture credit-memo rows.
- pdfplumber_extract.py — Generic deterministic text-layer extractor: dumps every page's raw text as one JSON `{text, page_count}` object; used both as the known-vendor path stand-in and as vendorIdentification.ts's cheap pre-extraction "peek" to guess a vendor slug/signature match.
- pdfplumber_ocr_fallback.py — Session 8.3's last-resort fallback tier: deterministic pdfplumber table extraction plus a per-page Tesseract/pdf2image OCR fallback for scanned pages, invoked only after a genuine Claude extraction failure; OCR degrades gracefully (not a hard failure) when the OCR binaries aren't installed.
- make_test_pdf.py — Test-fixture helper (PyMuPDF/`fitz`) that writes a single-page, genuinely pdfplumber-parseable PDF containing given text; used by testPdfFixture.mjs to build realistic PDF fixtures for tests.
- migrate.mjs — CLI entry point (`npm run migrate`) that applies pending local SQLite migrations via src/lib/migrate.ts; Fabric migrations are applied separately via sqlcmd, not through this script.
- seed_users.mjs — Idempotent dev-user bootstrap (`npm run seed:users`) that creates a first app_user row (SEED_USER_USERNAME/PASSWORD env vars or documented defaults) so Sign In is testable; SQLite-only, refuses to run against Fabric mode.
- cccRepairOrderFixture.mjs — Test-only fixture creating/seeding the `bronze_ccc_repair_order` placeholder table (CCC's real production table name is unconfirmed) used to exercise aiResidualMatching.ts's corroboration-found code path in tests.
- netsuiteVendorBillFixture.mjs — Test-only fixture creating/seeding a same-shape local stand-in for `bronze.netsuite_vendorbill`, used to exercise deterministicMatching.ts's SQL logic without live Fabric connectivity.
- testPdfFixture.mjs — Shared test helper that shells out to make_test_pdf.py to build a real parseable PDF from plain text, plus helpers (`marketLine`/`makeStatementText`) that generate this project's synthetic `VENDOR:/INVOICE:/AMOUNT:` marker-format statement text.
- e2e_extraction_service_round_trip.mjs — Session 3 integration check: registerDocument -> triggerExtraction -> Silver -> status badge -> extraction-method summary, through the real public entry points (not calling the pipeline function directly).
- e2e_matching_service_round_trip.mjs — Session 5 integration check: registerDocument -> triggerExtraction -> triggerMatchingForDocument -> Match/Exception, composing the extraction and matching pipelines together for the first time.
- run_extraction_service_smoke_test.sh — Session 3's literal EXECUTION_PLAN.md verification command: typecheck plus every Task 3.x test script plus the extraction e2e round trip, run in sequence.
- run_matching_service_smoke_test.sh — Session 5's literal EXECUTION_PLAN.md verification command: typecheck plus every Task 5.x test script plus the matching e2e round trip, run in sequence.
- test_ai_residual_matching.mjs — Task 5.3 test cases for AI-assisted residual matching, asserting it only ever proposes (`status: 'proposed'`, `requiresReview: true`) and never auto-approves a match (G3).
- test_ai_residual_matching.sh — Thin bash wrapper invoking test_ai_residual_matching.mjs via tsx.
- test_bounded_retry.mjs — Task 3.3 test cases confirming at most 2 total extraction attempts (S7) via the real runExtractionPipeline.
- test_bounded_retry.sh — Thin bash wrapper invoking test_bounded_retry.mjs via tsx.
- test_deterministic_matching.mjs — Task 5.2 test cases for SQL-based deterministic matching against the local NetSuite fixture (amount tolerance, reference-capture columns per S8 amended).
- test_deterministic_matching.sh — Thin bash wrapper invoking test_deterministic_matching.mjs via tsx.
- test_document_registration.mjs — Task 2.2 test cases for document registration and content-hash dedup (G4), exercising the real POST/GET /api/documents route handlers directly as constructed Request objects.
- test_document_registration.sh — Thin bash wrapper invoking test_document_registration.mjs via tsx.
- test_document_status.mjs — Task 2.3 test cases for computeDocumentStatus's badge logic, synthesizing extraction_attempt rows directly since no extraction service existed yet at that task's point in the build.
- test_document_status_computation.sh — Thin bash wrapper invoking test_document_status.mjs via tsx.
- test_exception_schema_wiring.mjs — Task 5.4 test cases for the exception category enum and schema wiring (S5 + S8 amended).
- test_exception_schema_wiring.sh — Thin bash wrapper invoking test_exception_schema_wiring.mjs via tsx.
- test_extraction_attempt_recording.mjs — Task 3.1 test cases for vendor identification, extraction routing, and attempt recording.
- test_extraction_attempt_recording.sh — Thin bash wrapper invoking test_extraction_attempt_recording.mjs via tsx.
- test_extraction_method_summary.mjs — Task 3.5 test cases for per-document extraction-method summary counts by provider_used.
- test_extraction_method_summary.sh — Thin bash wrapper invoking test_extraction_method_summary.mjs via tsx.
- test_foundation_schema.mjs — Task 1.2 test cases for the foundation schema, run against local SQLite (no live Fabric endpoint available in this environment).
- test_matching_invocation.mjs — Task 5.1 test cases for manual/scheduled matching invocation and the G5 document lock.
- test_matching_invocation.sh — Thin bash wrapper invoking test_matching_invocation.mjs via tsx.
- test_prompt_injection_defense.mjs — Task 3.4 test cases (G3, GLOBAL) confirming adversarial instruction-like text embedded in a document is treated strictly as extracted data, never as a command.
- test_prompt_injection_defense.sh — Thin bash wrapper invoking test_prompt_injection_defense.mjs via tsx.
- test_silver_normalization.mjs — Task 3.6 test cases for extracted-to-silver.statement_line normalization.
- test_silver_normalization.sh — Thin bash wrapper invoking test_silver_normalization.mjs via tsx.
- test_toast_store.mjs — Unit test for src/lib/toastStore.ts's framework-agnostic add/dismiss/auto-expire/subscribe logic, no browser dependency.
- test_validation_gate.mjs — Task 3.2 test cases for the arithmetic and structural validation gate (G2, amended).
- test_validation_gate.sh — Thin bash wrapper invoking test_validation_gate.mjs via tsx.
- verify_db_fallback.mjs — Reproducible check (`npm run test:db-fallback`) confirming a missing FABRIC_SQL_ENDPOINT env var falls back to local SQLite without crashing.
- verify_known_vendor_extractors.mjs — Task 9.7 (renumbered from 9.8) committed regression check running every registered known-vendor extractor through the real registerDocument -> triggerExtraction entry point against local sample PDFs (skips per-vendor if samples aren't present on the machine).

### migrations/
- 001_foundation_schema.sql — Canonical Fabric T-SQL migration creating the `extracted` schema plus the `silver`/`recon` tables this build owns (vendor_registry, document, statement_line, match, exception, etc.), applied via sqlcmd against live Fabric.
- 001_foundation_schema.sqlite.sql — Local SQLite equivalent of 001, using flattened schema-prefixed table names (e.g. `extracted_document`) instead of `schema.table` syntax so foreign keys stay enforced within SQLite's single-database model; applied automatically by src/lib/migrate.ts.
- 002_auth_users.sql — Fabric T-SQL creating `recon.app_user` (username/password_hash/display_name) — a plan gap filled for Task 1.3's Sign In screen, since no task explicitly specified a user store.
- 002_auth_users.sqlite.sql — Local SQLite equivalent of 002, creating `recon_app_user`.
- 003_normalization_version.sql — Fabric T-SQL adding `normalization_version` to `silver.statement_line` (S6: every row tagged with the normalization logic version that produced it).
- 003_normalization_version.sqlite.sql — Local SQLite equivalent of 003.
- 004_matching_lock.sql — Fabric T-SQL creating `recon.document_lock` (Task 5.1's G5 matching-invocation ownership lock, distinct from and released after each use, unlike the extraction lock).
- 004_matching_lock.sqlite.sql — Local SQLite equivalent of 004, creating `recon_document_lock`.
- 005_reference_capture_schema.sql — Fabric T-SQL replacing `recon.match`'s original `snapshot_version` column with three real reference-capture columns (reference_run_id/extracted_at/source_system, S8 amended) and adding the same plus `evidence` to `recon.exception`.
- 005_reference_capture_schema.sqlite.sql — Local SQLite equivalent of 005; drops and recreates `recon_match` (SQLite's ADD COLUMN can't add NOT NULL columns without a default) and ADD COLUMNs the nullable additions to `recon_exception`.
- 006_exception_reason_codes.sql — Fabric T-SQL adding `reason_codes` to `recon.exception` so each matching stage's structured reason codes (previously computed then discarded) are actually persisted.
- 006_exception_reason_codes.sqlite.sql — Local SQLite equivalent of 006.
- 007_document_original_filename.sql — Fabric T-SQL adding nullable `original_filename` to `extracted.document` so the Upload screen can show the actually-uploaded file name, not just the (often-null) extracted vendor.
- 007_document_original_filename.sqlite.sql — Local SQLite equivalent of 007.
- 008_exception_status.sql — Fabric T-SQL adding a `status`/`note`/`resolved_at` resolution workflow to `recon.exception` (Mark resolved/Flag for vendor/Skip) — an engineer-directed deviation from ARCHITECTURE.md D-C's "flat, ownerless list" design.
- 008_exception_status.sqlite.sql — Local SQLite equivalent of 008.
- 009_silver_line_dedup_flag.sql — Fabric T-SQL adding `is_duplicate_line` to `silver.statement_line` (Task 8.5) — a same-vendor/invoice-ref/amount repeat is flagged but never gated out of matching.
- 009_silver_line_dedup_flag.sqlite.sql — Local SQLite equivalent of 009.

### src/lib/
- aiProvider.ts — Claude Sonnet extraction entry point (extractViaClaude): routes to Azure AI Foundry, then direct Anthropic API, then a deterministic marker-text mock, depending on configured credentials and the EXTRACTION_LIVE_TESTS opt-in; owns the extraction system prompt and its own prompt-injection-defense framing (G3).
- aiResidualMatching.ts — Task 5.3's AI-assisted residual matching (runResidualMatch): for a line that didn't match deterministically, looks up CCC repair-order corroboration and proposes a next-step suggestion via Claude or a mock — always `status: 'proposed'`, never auto-approves a match.
- auth.ts — Password hashing (scrypt) and findUserByUsername lookup for Sign In (Task 1.3); Node-runtime only, not imported by the Edge-runtime proxy.ts.
- currentUser.ts — getCurrentSession(): Server Component/Action helper that reads and verifies the session cookie via session.ts, for use in server components/actions (not proxy.ts, which reads cookies directly).
- db.ts — Environment-driven DB connection: getDbMode()/getSqliteDb()/getFabricPool() switch between local SQLite (better-sqlite3) and Fabric (mssql) based on whether FABRIC_SQL_ENDPOINT is set; also pingDb()/closeDb().
- deterministicMatching.ts — Task 5.2's SQL-based deterministic matching (matchStatementLine/writeMatch): matches a statement line's normalized invoice ref against NetSuite's `tranid` (live Fabric Lakehouse via fabricLakehouse.ts, or a local SQLite fixture), vendor-scoped to avoid cross-vendor tranid collisions, with amount-tolerance comparison and credit-sign flipping.
- documentDetail.ts — getDocumentDetail(): assembles the Document Detail screen's data — header info, extraction-method summary, per-line statement rows with attempt-level confidence/provider, and reconciliation progress counts.
- documentStatus.ts — computeDocumentStatus(): derives a document's display status badge (Processing/Extracted/Reconciling/Retrying/Failed/Reconciled) from extraction_attempt history, an active matching lock, and match/exception completeness across all lines.
- documents.ts — Document registration (registerDocument, G4 content-hash dedup), listing (listDocuments/listDocumentsWithStatusBadge), and the internal-to-API document shape mapping (toApiDocument/ApiDocument).
- exceptionDetail.ts — getExceptionDetail()/updateExceptionResolution(): reads one exception's full detail (statement line, CCC corroboration, amount-mismatch drill-down, raw NetSuite record) from stored evidence, and is the sole write path for the resolve/flag/skip workflow.
- exceptionWriter.ts — writeException(): the single write path for `recon.exception`, validating the fixed category enum (amount_mismatch/not_posted) before insert.
- exceptionsList.ts — listVendorsWithExceptions()/listExceptionsForVendor(): the vendor-grouped Exceptions screen's data layer (2026-09-01 redesign, ported from Figma mockups), replacing the original flat all-vendor paginated list.
- extractAdas.ts — TS wrapper spawning scripts/extract_adas.py as a subprocess, converting its JSON output into this project's ExtractionOutcome/ExtractedStatement shape for Adas Calibration Experts (ADAS_SIGNATURES/ADAS_VENDOR_SLUG).
- extractAstech.ts — TS wrapper spawning scripts/extract_astech.py as a subprocess for asTech/Repairify (ASTECH_SIGNATURES/ASTECH_VENDOR_SLUG).
- extractEmpire.ts — TS wrapper spawning scripts/extract_empire.py as a subprocess for Empire Auto Parts (EMPIRE_SIGNATURES/EMPIRE_VENDOR_SLUG).
- extractFredBeans.ts — TS wrapper spawning scripts/extract_fred_beans.py as a subprocess for Fred Beans Parts (FRED_BEANS_SIGNATURES/FRED_BEANS_VENDOR_SLUG).
- extractKeystone.ts — TS wrapper spawning scripts/extract_keystone.py as a subprocess for Keystone Automotive Industries (KEYSTONE_SIGNATURES/KEYSTONE_VENDOR_SLUG).
- extractLiaAutoGroup.ts — TS wrapper spawning scripts/extract_lia.py as a subprocess for Lia Auto Group (LIA_AUTO_GROUP_SIGNATURES/LIA_AUTO_GROUP_VENDOR_SLUG) — the original Task 8.1 known-vendor extractor.
- extractPrecision.ts — TS wrapper spawning scripts/extract_precision.py as a subprocess for Precision Diagnostics (PRECISION_SIGNATURES/PRECISION_VENDOR_SLUG).
- extractQuirk.ts — TS wrapper spawning scripts/extract_quirk.py as a subprocess for Quirk Auto Group (QUIRK_SIGNATURES/QUIRK_VENDOR_SLUG).
- extractWilberts.ts — TS wrapper spawning scripts/extract_wilberts.py as a subprocess for Wilbert's Inc. (WILBERTS_SIGNATURES/WILBERTS_VENDOR_SLUG).
- extraction.ts — triggerExtraction(): the Extract action's entry point (Task 2.4), atomically flipping document.status to 'processing' (G5 ownership guard) before synchronously invoking extractionPipeline.ts.
- extractionMethodSummary.ts — getExtractionMethodSummary(): per-document counts of extraction_attempt rows grouped by provider_used, for the Document Detail screen.
- extractionPipeline.ts — runExtractionPipeline(): the extraction orchestrator tying together vendor identification/routing (vendorIdentification.ts), the validation gate, bounded retry (max 2 attempts, S7), routing a genuine Claude failure to the OCR/pdfplumber fallback tier, and Silver normalization on success.
- fabricLakehouse.ts — Live, read-only access (via `tedious`, not `mssql`) to the Fabric Lakehouse's `bronze.netsuite_vendorbill`/`bronze.netsuite_vendorcredit` tables, vendor-name-scoped and amount-closest-tie-broken to avoid the confirmed cross-vendor tranid collision bug; separate from db.ts's app-state DB switch.
- homeSummary.ts — getHomeSummaryStats(): computes Home dashboard's four summary stats (documents processed, open exceptions, reconciled/not-reconciled counts) reusing documents.ts's status-badge computation.
- knownVendorExtractors.ts — KNOWN_VENDOR_EXTRACTORS table-driven registry of all 9 per-vendor deterministic extractors keyed by printed-text signature; findKnownVendorExtractor() is the single lookup vendorIdentification.ts calls.
- legalEntities.ts — LEGAL_ENTITIES: a placeholder, non-canonical list of 3 legal entity options for Upload's (now-fixed-default) legal entity assignment — flagged as an unresolved real architectural gap, not sourced from VIVE's real structure.
- matchingInvocation.ts — Manual (triggerMatchingForDocument) and scheduled-batch (runScheduledMatchingBatch) matching entry points, both acquiring/releasing recon.document_lock (G5) around matchingPipeline.ts's runMatchingForDocument.
- matchingPipeline.ts — runMatchingForDocument(): per-document matching orchestrator running deterministic matching then (on a miss) the AI residual pass per line, buffering all writes in memory and committing every recon.match/recon.exception row for the document atomically in one transaction.
- migrate.ts — runMigrations(): applies pending migrations/*.sqlite.sql files in order against local SQLite via a `_migrations` bookkeeping table; throws with the sqlcmd commands needed for Fabric mode instead of attempting to run T-SQL migrations itself.
- pdfplumberExtractor.ts — extractViaPdfplumber(): TS wrapper spawning scripts/pdfplumber_extract.py, parsing the returned text against this project's own synthetic marker-format regex — the Task 3.1 "known-vendor deterministic" stand-in used before real per-vendor layouts existed.
- pdfplumberOcrFallback.ts — extractViaPdfplumberOcrFallback(): TS wrapper spawning scripts/pdfplumber_ocr_fallback.py, Task 8.3's actual OCR/pdfplumber last-resort fallback tier invoked only after a genuine Claude failure.
- schema.ts — Table-name resolution helpers (qualifiedTableName/vendorStmtTableName) reconciling Fabric's schema-qualified names vs. SQLite's flattened names, plus assertValidVendorSlug()'s trust-boundary guard against SQL-injecting a vendor slug into DDL text.
- session.ts — Edge-runtime-safe (Web Crypto) session cookie signing/verification (signSessionToken/verifySessionToken/isSessionExpired) shared between login, server actions, and the Edge-runtime proxy.ts middleware; 30-minute idle timeout.
- silverNormalization.ts — normalizeToSilver(): writes one silver.statement_line row per extracted line (normalized_invoice_ref, normalization_version tagging per S6), also flagging (but not gating) duplicate lines per Task 8.5.
- storage.ts — Environment-driven local file storage (saveDocumentFile/readDocumentFile/documentFileExists) storing uploaded PDFs by content hash under UPLOADS_DIR; local-filesystem-only fallback pending a real blob store.
- toastStore.ts — Framework-agnostic toast notification store (createToastStore: add/dismiss/auto-expire/subscribe), independently unit-testable without React; ToastProvider.tsx is its thin React subscriber.
- validationGate.ts — validateExtraction(): Task 3.2's structural (invoice_ref/RO presence, numeric amounts, parseable dates, identifiable vendor) and arithmetic (sum-of-lines vs. stated total, 1-cent tolerance) validation gate; confidence is explicitly excluded from gating (G2).
- vendorDisplay.ts — humanizeVendorSlug(): pure, zero-import display helper turning a vendor_slug into a human-readable label; deliberately isolated so client components avoid bundling db.ts's Node-only DB drivers.
- vendorIdentification.ts — identifyAndExtract(): Task 3.1's core routing — peeks the PDF text to guess a vendor, checks the known-vendor extractor registry first, then a registered deterministic vendor, then Claude (or the forced OCR fallback), creating provisional vendors and running S2 version-chaining as needed.
- vendorSchema.ts — ensureVendorStmtTable(): idempotently creates a per-vendor `stmt_<vendor_slug>` raw append-only table (+ no-update trigger) at runtime, in both Fabric T-SQL and SQLite dialects.

### src/app/(app)/
- layout.tsx — Authenticated shell layout (Sidebar + ToastProvider) wrapping every route in this group; defensively redirects to /login if no session (proxy.ts is the primary enforcement point).
- loading.tsx — App-level loading state (simple spinner, no skeletons) shown during initial load/route transitions within this route group.
- error.tsx — Global error boundary (inline "Something went wrong" message + Retry button) catching render-time errors thrown within this route group.

### src/app/(app)/dev-test-error/
- page.tsx — Test-only page that unconditionally throws, existing solely so ui_tests/global-elements.spec.ts can deterministically exercise error.tsx; not linked from real navigation.

### src/app/(app)/dev-test-loading/
- page.tsx — Test-only page with an artificial 1s delay so ui_tests/global-elements.spec.ts can observe the Suspense loading.tsx boundary actually mounting; not linked from real navigation.

### src/app/(app)/dev-test-toast/
- page.tsx — Test-only page with buttons that trigger a success/error toast via ToastProvider's useToast(), exercising the toast system end-to-end for ui_tests/global-elements.spec.ts; not linked from real navigation.

### src/app/(app)/documents/[id]/
- DocumentDetailView.tsx — Client component rendering the Document Detail screen: status badge, Extract/Reconcile action buttons (with 409-lock handling), extraction-method summary strip, and the extracted-lines table with per-line confidence/provider labels.
- page.tsx — Server component fetching one document's detail via getDocumentDetail() and rendering DocumentDetailView; throws (routing to the global error boundary) if the document isn't found.

### src/app/(app)/exceptions/
- page.tsx — Server component for the Exceptions landing route, fetching listVendorsWithExceptions() and rendering ExceptionsVendorListView.
- ExceptionsVendorListView.tsx — Client component: searchable table of vendors with open exceptions (missing/mismatch counts, resolve progress bar), each row linking to that vendor's detail page.

### src/app/(app)/exceptions/[vendorSlug]/
- page.tsx — Server component fetching one vendor's exception rows via listExceptionsForVendor() and rendering ExceptionVendorDetailView; throws if the vendor has no exceptions.
- ExceptionVendorDetailView.tsx — Client component implementing the two-pane master-detail Exception workspace: filterable list, exception detail panel (CCC corroboration, amount-mismatch diff, expandable raw NetSuite record fields), note field, and resolve/flag/skip actions with prev/next paging.

### src/app/(app)/home/
- page.tsx — Server component for the Home dashboard route, fetching listDocumentsWithStatusBadge() and getHomeSummaryStats() and rendering HomeView.
- HomeView.tsx — Client component rendering Home's summary stat cards and the recent-uploads table, with per-document Extract/Reconcile actions and Home's own softened status-label mapping (homeDisplayStatus).

### src/app/(app)/upload/
- page.tsx — Server component for the Upload route, fetching listDocumentsWithStatusBadge() and rendering UploadForm.
- UploadForm.tsx — Client component implementing the drag-and-drop/file-picker upload flow, auto-chaining extraction after a successful upload, and the uploaded-statements table with per-document status/Extract action.

### src/app/api/documents/
- route.ts — GET: lists all registered documents with status badges. POST: registers a new upload (Task 2.2) after MIME/extension/size/legal-entity validation; never triggers matching (S1).

### src/app/api/documents/[id]/
- detail/route.ts — GET: Document Detail screen's refresh endpoint, returning getDocumentDetail() or 404.
- extract/route.ts — POST: triggers extraction for one document via triggerExtraction(); 404 if not found, 409 if already processing (G5).
- match/route.ts — POST: triggers matching for one document via triggerMatchingForDocument(); 404 if not found, 409 if already processing (G5).

### src/app/api/exceptions/
- route.ts — GET: Exceptions landing screen's data endpoint, returning listVendorsWithExceptions().

### src/app/api/exceptions/[id]/
- route.ts — GET: one exception's full detail. PATCH: applies the Mark resolved/Flag for vendor/Skip workflow plus optional note via updateExceptionResolution().

### src/app/api/exceptions/vendor/[vendorSlug]/
- route.ts — GET: one vendor's full exception list for the two-pane detail view's left panel, via listExceptionsForVendor().

### src/app/api/health/
- route.ts — GET: minimal health endpoint exercising the env-driven DB connection (pingDb()), returning DB mode/ok or a 503 on failure.

### src/app/api/home-summary/
- route.ts — GET: Home screen's summary stats refresh endpoint, returning getHomeSummaryStats().

### src/app/api/matching/run-batch/
- route.ts — POST: scheduled-batch matching entry point (runScheduledMatchingBatch()) for an external scheduler to call; no live cron/timer infra invokes it in this build.

### src/app/login/
- page.tsx — Sign-in page rendering the Vive logo and LoginForm.
- LoginForm.tsx — Client component: username/password form using useActionState/loginAction, plus a disabled "Coming soon" SSO button.
- actions.ts — Server actions loginAction() (verifies credentials, signs and sets the session cookie, redirects to /home with an identical error for bad-username vs. bad-password) and logoutAction() (clears the cookie, redirects to /login).

### src/app/
- layout.tsx — Root HTML layout: loads the three self-hosted Google fonts (Barlow Semi Condensed/Inter/IBM Plex Mono) via next/font, renders IconSprite, and sets page metadata.
- page.tsx — Root route; unconditionally redirects to /login.
- globals.css — Design tokens (colors, radii, shadows, font-family vars) and shared component classes adapted from the engineer-supplied Figma HTML mockups, trimmed to this build's six actual screens.

### src/components/
- IconSprite.tsx — Renders the shared SVG `<symbol>` icon defs (home/upload/alert/file/users/settings/check-circle/key/folder) once near the root; other components reference icons via `<use href="#i-name">`.
- InlineLoadError.tsx — Shared inline "Something went wrong" + Retry component for client-side data-refetch failures (search/pagination/post-action refresh), reusing error.tsx's exact markup/classes/testids so both read as one pattern.
- Sidebar.tsx — Authenticated shell's primary navigation (Home/Upload/Exceptions active links, disabled Admin group) plus the user block with a logout form.
- ToastProvider.tsx — Client component subscribing to toastStore.ts and rendering the bottom-right toast stack; also exports the useToast() hook (showSuccess/showError) used throughout the app.

### src/
- proxy.ts — Edge-runtime middleware enforcing the 30-minute idle-timeout Authentication Shell: redirects to /login on a missing/expired session cookie, otherwise refreshes (slides) the session cookie on every matched request; matcher excludes /login, /api/health, and static assets.

### Root config files
- package.json — Project manifest: Next.js 16/React 19/TypeScript app depending on @anthropic-ai/sdk, @anthropic-ai/foundry-sdk, better-sqlite3, and mssql; npm scripts for dev/build, typecheck, Playwright UI tests, migrations, seeding, and each dedicated verification script.
- playwright.config.ts — Playwright test config: testDir ui_tests/, global setup, single Chromium project, and a webServer block that launches `npm run dev` with FABRIC_SQL_ENDPOINT/FABRIC_LAKEHOUSE_SQL_ENDPOINT/EXTRACTION_LIVE_TESTS force-blanked so automated tests always exercise the local SQLite/deterministic-mock paths, never live Fabric/Claude.
- tsconfig.json — TypeScript compiler config (ES2017 target, strict mode, bundler module resolution, `@/*` path alias to `src/*`); excludes ui_tests/ from the main program (Playwright specs typecheck separately).
- next.config.mjs — Next.js config: reactStrictMode on, `agentRules: false` (disables Next 16's auto-generated /AGENTS.md and /CLAUDE.md, which collide with this project's own root-stub convention), and devIndicators disabled.
- .env.example — Documents the env vars this app reads: FABRIC_SQL_ENDPOINT (DB mode switch), SQLITE_DB_PATH, SESSION_SECRET, SESSION_IDLE_TIMEOUT_MS (test-only override), and SEED_USER_USERNAME/PASSWORD for the dev-user bootstrap script.
- .gitignore — Standard Node/Next/Python ignore patterns (node_modules, .next, __pycache__, .env, local SQLite db files, Playwright artifacts) plus a deliberate exclusion of Next 16's auto-generated root /AGENTS.md and /CLAUDE.md, which collide with this project's own PBVI root-stub convention.
