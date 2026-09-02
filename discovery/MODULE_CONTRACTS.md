STAGE-1-DRAFT: DOCS-DERIVED — 2026-09-01 — Produced by BCE Adapter Pipeline Stage 1
STAGE-2-STATUS: COMPLETE — 2026-09-02, BCE Adapter Pipeline Stage 2 Sessions B (serving),
C (pipeline), G (infra), U (route + UI). All 10 Stage 1 skeletons replaced; 68 modules with
no Stage 1 entry added. Zero STAGE-2-DIVERGENCE tags — no Stage 1 skeleton was contradicted
by source, only completed. One Stage 1 skeleton (S1-08_home_ui, mapped below to M-014/M-068)
led indirectly to a real correction: source reading here is what caught that Phase 8's
recorded S7 FAIL was a stale-test false positive — see M-012's entry and
`verification/VERIFICATION_CHECKLIST.md`'s correction note.

# MODULE_CONTRACTS.md — VIVE Statement Reconciliation

**Full per-module contracts (9 fields: Inputs, Outputs, Public Interface, Error Behaviour,
Known Fragility, Change Impact, Callers, Calls, Integration Points Used) live in
`discovery/components/` — one file per module, read directly from source at Stage 2. This
file is the consolidated index, not a duplicate copy** (same pattern as `TOPOLOGY.md`'s A02
section — avoids drift between two copies of the same data). Module IDs (M-NNN) are
permanent, assigned in `discovery/components/A02_module_call_map.md`'s Module Roster.

---

## infra (12 modules — Session G)

| ID | Module | File | Primary Responsibility | Most notable finding |
|---|---|---|---|---|
| M-001 | auth.ts | `components/G01_auth.md` | Password hashing (scrypt) + user lookup, both DB backends | SQLite/Fabric row-mapping duplicated inline — a column rename in one dialect's migration but not the other diverges silently |
| M-002 | currentUser.ts | `components/G02_currentUser.md` | Resolves current session from request cookie | Relies entirely on `proxy.ts`'s route guard by convention — no enforcement of its own |
| M-003 | db.ts | `components/G03_db.md` | Central env-driven SQLite/Fabric connection layer, 20+ callers | **A failed Fabric `ConnectionPool.connect()` permanently caches the rejected promise in the module singleton** — no retry until `closeDb()` is called; a transient startup blip can permanently break Fabric access for the process lifetime |
| M-004 | session.ts | `components/G04_session.md` | Edge-safe HMAC session token sign/verify | A misconfigured `SESSION_SECRET` and a genuinely tampered/expired cookie both collapse to the same `null` result — no way to distinguish server misconfig from "not logged in" |
| M-005 | storage.ts | `components/G05_storage.md` | Local-disk, content-addressed PDF storage | No validation that `contentSha256` actually matches `bytes` — a caller can silently corrupt the content-addressing invariant |
| M-006 | schema.ts | `components/G06_schema.md` | Table-name resolution + vendor-slug DDL-injection guard | `qualifiedTableName` has zero validation; only the vendor-slug path is guarded, and that regex is the sole defense since neither driver supports parameterized identifiers |
| M-007 | migrate.ts | `components/G07_migrate.md` | SQLite migration runner (Fabric mode refuses, throws sqlcmd instructions) | Zero callers in the app's own request-serving call graph — confirmed unreachable at runtime, invoked only externally |
| M-008 | fabricLakehouse.ts | `components/G08_fabricLakehouse.md` | Read-only NetSuite bronze reference lookups via `tedious` | Vendor-scoped-then-amount-closest logic fixes a confirmed real cross-vendor tranid collision bug — reintroducing an unscoped fallback would reopen it |
| M-009 | toastStore.ts | `components/G09_toastStore.md` | Framework-agnostic toast pub/sub, app-wide singleton | No server/client isolation — if ever mutated server-side, state would leak across requests (Node modules are process-wide) |
| M-010 | vendorDisplay.ts | `components/G10_vendorDisplay.md` | Zero-import vendor-slug humanizer, kept out of the DB-driver bundle | The "zero imports" constraint is documentation-only — one import risks reintroducing a client-bundle build failure |
| M-041 | vendorSchema.ts | `components/G11_vendorSchema.md` | Per-vendor raw table + append-only trigger DDL generation | **The Fabric DDL has no `IF NOT EXISTS` guard** (unlike SQLite's) — calling it twice for the same vendor in Fabric mode would throw, contradicting its own "idempotent" doc comment; currently unreachable since Fabric app-state isn't implemented elsewhere |
| M-042 | legalEntities.ts | `components/G12_legalEntities.md` | Static placeholder legal-entity list | Imported by both M-044 (route) and M-070 (UploadForm) — since the default is `LEGAL_ENTITIES[0]`, reordering the array silently changes Upload's default entity |

## serving (10 modules — Session B)

| ID | Module | File | Primary Responsibility | Most notable finding |
|---|---|---|---|---|
| M-011 | documents.ts | `components/B01_documents.md` | Registration/dedup (G4), listing, lookup, API projection | UNIQUE-violation catch relies on string-matching the driver's error text; `listDocumentsWithStatusBadge` is an unbatched N+1 over `computeDocumentStatus` |
| M-012 | documentStatus.ts | `components/B02_documentStatus.md` | Six-value status badge computation | **Traced the "S7 status-badge bug" precisely and found it's not real** — the code correctly returns `'Extracted'` for the failed-then-succeeded retry case (added 2026-08-31 specifically to disambiguate from `'Processing'`); the FAIL was `test_bounded_retry.mjs:58` asserting a stale pre-2026-08-31 literal. `VERIFICATION_CHECKLIST.md` corrected 2026-09-02 |
| M-013 | documentDetail.ts | `components/B03_documentDetail.md` | Assembles Document Detail screen data | Three independent existence checks across M-011/M-012/M-016 instead of one shared guard |
| M-014 | homeSummary.ts | `components/B04_homeSummary.md` | Home dashboard's four summary stats | Mixes line-level (`reconciledCount`) and document-level (`notReconciledCount`) units in one return type — not directly comparable |
| M-015 | extraction.ts | `components/B05_extraction.md` | Extract trigger entry point, G5 lock | No rollback of the `'processing'` status column if the pipeline throws — a document could get permanently stuck |
| M-016 | extractionMethodSummary.ts | `components/B06_extractionMethodSummary.md` | Per-document provider-attempt counts | Duplicates M-012's existence-check pattern independently rather than sharing it |
| M-017 | matchingInvocation.ts | `components/B07_matchingInvocation.md` | Manual + scheduled matching entry points, G5 lock | `runScheduledMatchingBatch` has no per-document error isolation — one throwing document aborts the whole batch, and the `{processed, skipped}` result is never returned |
| M-018 | exceptionDetail.ts | `components/B08_exceptionDetail.md` | Exception read + sole resolution-write path | `note: null` is indistinguishable from omitting `note` — can't explicitly clear a note via this API |
| M-019 | exceptionsList.ts | `components/B09_exceptionsList.md` | Vendor-grouped exception lists | Vendors with NULL `vendor_slug` are silently invisible; per-vendor list is intentionally unpaginated with no safety limit |
| M-020 | exceptionWriter.ts | `components/B10_exceptionWriter.md` | Sole `recon_exception` write path | No idempotency guard — a caller retry could double-insert an exception for the same line |

## pipeline (20 modules — Session C)

| ID | Module | File | Primary Responsibility | Most notable finding |
|---|---|---|---|---|
| M-021 | vendorIdentification.ts | `components/C01_vendorIdentification.md` | Routes to known-vendor/deterministic/Claude/fallback extraction, runs version-chaining | Confirmed the historical "`ensureVendorStmtTable` never called" bug is correctly fixed — called unconditionally, even on the registry-exists branch |
| M-022 | extractionPipeline.ts | `components/C02_extractionPipeline.md` | Orchestrates identify→validate→retry(×2)→normalize | Never touches `document.status` itself — the (non-)bug traced to M-012 above, not here |
| M-023 | validationGate.ts | `components/C03_validationGate.md` | Pure arithmetic/structural gate | Explicitly guards against NaN-based false-passes |
| M-024 | silverNormalization.ts | `components/C04_silverNormalization.md` | Writes Silver lines, flags (never blocks) duplicates | Trusts the caller to have already gated on validation |
| M-025 | matchingPipeline.ts | `components/C05_matchingPipeline.md` | Per-document matching orchestrator, buffered single-transaction commit | Any mid-loop exception discards ALL buffered work for the document, not just the failing line — an all-or-nothing trade for correct concurrent-read visibility |
| M-026 | deterministicMatching.ts | `components/C06_deterministicMatching.md` | NetSuite tranid matching, credit-sign flip, vendor-scoped | Vendor-prefix scoping is a naive first-token heuristic, fragile for multi-word family names |
| M-027 | aiResidualMatching.ts | `components/C07_aiResidualMatching.md` | Proposal-only residual matching (never auto-approves) | Makes its own direct Anthropic API call independent of M-028, despite IP-001 being attributed to M-028 as module of record — worth reconciling in a future pass |
| M-028 | aiProvider.ts | `components/C08_aiProvider.md` | Claude extraction, Azure Foundry/direct/mock routing | Fixed a max_tokens truncation bug (4096→16000) with a stop_reason guard |
| M-029 | pdfplumberExtractor.ts | `components/C09_pdfplumberExtractor.md` | Deterministic pdfplumber subprocess wrapper | Uses synthetic test-fixture marker parsing, not real vendor layouts |
| M-030 | pdfplumberOcrFallback.ts | `components/C10_pdfplumberOcrFallback.md` | OCR-fallback subprocess wrapper | Same synthetic-fixture caveat as M-029 |
| M-031 | knownVendorExtractors.ts | `components/C11_knownVendorExtractors.md` | Table-driven registry of the 9 vendor extractors | Signature matching is a naive substring check with array-order as an implicit tiebreak |
| M-032 | extractAdas.ts | `components/C12_extractAdas.md` | Adas Calibration Experts parser | Sums Open Amount, not Amount |
| M-033 | extractAstech.ts | `components/C13_extractAstech.md` | asTech/Repairify parser | Sums Outstanding Amount via native table detection |
| M-034 | extractEmpire.ts | `components/C14_extractEmpire.md` | Empire Auto Parts parser | Single signed Amount column + doc-number/description un-merge fixup |
| M-035 | extractFredBeans.ts | `components/C15_extractFredBeans.md` | Fred Beans Parts parser | Splits 4 money columns by right-edge, charges-positive/credits-negative — fixes a documented ~4.7x historical inflation bug |
| M-036 | extractKeystone.ts | `components/C16_extractKeystone.md` | Keystone Automotive Industries parser | Sums the already-netted Balance Due column (0% Claude baseline) |
| M-037 | extractLiaAutoGroup.ts | `components/C17_extractLiaAutoGroup.md` | Lia Auto Group parser (original Task 8.1 extractor) | Sums Balance — the pattern template the other 8 followed |
| M-038 | extractPrecision.ts | `components/C18_extractPrecision.md` | Precision Diagnostics parser | Multi-line transaction reconstruction, sums Charge |
| M-039 | extractQuirk.ts | `components/C19_extractQuirk.md` | Quirk Auto Group parser | Drops watermark tokens, sums a single signed Amount column |
| M-040 | extractWilberts.ts | `components/C20_extractWilberts.md` | Wilbert's Inc. parser | Sums Balance (not Amount) with a DT# continuation-row merge |

## route (12 modules — Session U)

| ID | Module | File | Primary Responsibility | Most notable finding |
|---|---|---|---|---|
| M-043 | proxy.ts | `components/U01_proxy.md` | Edge middleware, 30-min idle-timeout auth shell | An unset `SESSION_SECRET` would throw unhandled inside Edge middleware on the refresh path — not caught |
| M-044 | api/documents/route.ts | `components/U02_documents_route.md` | GET list, POST register+dedup | A duplicate upload under a different legal entity returns 200 with `legalEntityMismatch:true`, not an error |
| M-045 | api/documents/[id]/detail/route.ts | `components/U03_documents_detail_route.md` | GET document detail | No try/catch — unhandled errors surface as a raw 500 |
| M-046 | api/documents/[id]/extract/route.ts | `components/U04_documents_extract_route.md` | POST extraction trigger, G5 lock | Lock is non-releasing on failure — a pipeline exception mid-run leaves the document permanently stuck in `'processing'`, no `finally`/unlock path |
| M-047 | api/documents/[id]/match/route.ts | `components/U05_documents_match_route.md` | POST matching trigger, G5 lock | Lock mechanism differs materially from M-046's — self-releasing, staleness-reclaimable (10-min TTL), always releases via `finally` |
| M-048 | api/exceptions/route.ts | `components/U06_exceptions_route.md` | GET vendor-summary list | Vendors with NULL `vendor_slug` silently excluded, no signal |
| M-049 | api/exceptions/[id]/route.ts | `components/U07_exceptions_id_route.md` | GET detail, PATCH resolution workflow | PATCH's catch block conflates "not found" with any other DB error — both surface as 404 |
| M-050 | api/exceptions/vendor/[vendorSlug]/route.ts | `components/U08_exceptions_vendor_route.md` | GET per-vendor exception list | Unknown vendor slug returns 200 `{rows:[]}`, not 404 |
| M-051 | api/health/route.ts | `components/U09_health_route.md` | GET DB ping | Only route excluded from M-043's auth matcher; only one with a deliberate try/catch producing 503 |
| M-052 | api/home-summary/route.ts | `components/U10_home_summary_route.md` | GET Home stats | Thin passthrough to M-014 |
| M-053 | api/matching/run-batch/route.ts | `components/U11_matching_run_batch_route.md` | POST scheduled-batch entry (IP-005/n8n's target) | **One throwing document aborts the entire batch with no partial-result reporting; also inherits M-043's session-cookie auth requirement** — unusual for a machine-to-machine trigger, since it isn't excluded from the auth matcher the way M-051 is |
| M-054 | login/actions.ts | `components/U12_login_actions.md` | Server Actions loginAction/logoutAction | Deliberately identical error message for bad-username vs. bad-password (anti-enumeration) |

## UI: layout / page / component / store (24 modules — Session U)

| ID | Module | File | Primary Responsibility | Most notable finding |
|---|---|---|---|---|
| M-060 | layout.tsx (root) | `components/U13_root_layout.md` | HTML shell, fonts, IconSprite mount point | Root of all icon `<use>` refs — must stay mounted before any icon usage |
| M-061 | page.tsx (root) | `components/U14_root_page.md` | Unconditional redirect to `/login` | No auth check of its own — relies entirely on downstream logic |
| M-062 | login/page.tsx | `components/U15_login_page.md` | Static shell around LoginForm | — |
| M-063 | LoginForm.tsx | `components/U16_LoginForm.md` | Username/password form via loginAction | SSO button and "Contact IT" link are permanent disabled stubs |
| M-064 | (app)/layout.tsx | `components/U17_app_layout.md` | Authenticated shell (Sidebar + ToastProvider) | Its own session check is explicitly a "defensive fallback" per its own comment — real enforcement lives in M-043 |
| M-065 | (app)/loading.tsx | `components/U18_app_loading.md` | App-level loading spinner | Only exercised in tests via M-078's artificial delay — no real fetch is slow enough to trigger it naturally |
| M-066 | (app)/error.tsx | `components/U19_app_error.md` | Global error boundary | **Discards the `error` object entirely — no logging** — and doubles as the "not found" UI for M-073/M-075's deliberate throws |
| M-067 | home/page.tsx | `components/U20_home_page.md` | Home route, fetches list + summary | — |
| M-068 | HomeView.tsx | `components/U21_HomeView.md` | Home dashboard rendering | Has its own `homeDisplayStatus()` relabeling layer over the raw badge; `canExtract`/`canReconcile` gating logic duplicated verbatim in M-070 and M-076 |
| M-069 | upload/page.tsx | `components/U22_upload_page.md` | Upload route | — |
| M-070 | UploadForm.tsx | `components/U23_UploadForm.md` | Upload flow, auto-chains extraction | Auto-chains a silent, un-awaited extraction call after upload; fixed `LEGAL_ENTITIES[0]` as default entity |
| M-071 | exceptions/page.tsx | `components/U24_exceptions_page.md` | Exceptions landing route | — |
| M-072 | ExceptionsVendorListView.tsx | `components/U25_ExceptionsVendorListView.md` | Vendor list, search/filter | Client-side-only search filtering, no pagination |
| M-073 | exceptions/[vendorSlug]/page.tsx | `components/U26_exceptions_vendorSlug_page.md` | Vendor detail route | — |
| M-074 | ExceptionVendorDetailView.tsx | `components/U27_ExceptionVendorDetailView.md` | Two-pane exception workspace | **`loadDetail` and `applyAction` (resolve/flag/skip) have zero failure feedback — no toast, no inline error — unlike every other mutating component in the app** |
| M-075 | documents/[id]/page.tsx | `components/U28_documents_id_page.md` | Document Detail route | Same not-found-throws-generic-error pattern as M-073 |
| M-076 | DocumentDetailView.tsx | `components/U29_DocumentDetailView.md` | Document Detail rendering | Hard-coded `PROVIDER_LABELS` map silently falls back to raw provider strings for unmapped values |
| M-077 | dev-test-error/page.tsx | `components/U30_dev_test_error.md` | Test-only error trigger | Navigation-unreachable, direct-URL-only |
| M-078 | dev-test-loading/page.tsx | `components/U31_dev_test_loading.md` | Test-only loading trigger | Navigation-unreachable, direct-URL-only |
| M-079 | dev-test-toast/page.tsx | `components/U32_dev_test_toast.md` | Test-only toast trigger | Navigation-unreachable, direct-URL-only |
| M-080 | IconSprite.tsx | `components/U33_IconSprite.md` | Shared SVG symbol defs | Must stay mounted at/near root or all icon `<use>` refs across the app silently render nothing |
| M-081 | InlineLoadError.tsx | `components/U34_InlineLoadError.md` | Shared inline error+retry | Deliberately duplicates M-066's exact markup/testid, manually kept in sync, no shared abstraction |
| M-082 | Sidebar.tsx | `components/U35_Sidebar.md` | Primary nav + logout | Admin/Settings button is a permanent, intentional dead stub (single-role build) |
| M-083 | ToastProvider.tsx | `components/U36_ToastProvider.md` | Toast rendering + useToast hook | No cap on simultaneous toasts — single shared stream across the whole app |

---

## Cross-cutting findings worth flagging together (not one module's alone)

- **Duplicated status-gating logic**: `canExtract`/`canReconcile` predicates are independently
  re-implemented in M-068, M-070, and M-076 rather than shared — a future status-value
  change risks updating two of the three and missing the third.
- **Inconsistent lock semantics between the two G5 implementations**: M-046 (extraction)
  uses a non-releasing raw status column with no unlock-on-failure path; M-047 (matching)
  uses a proper self-releasing, TTL-reclaimable lock table. Both satisfy G5's "no
  concurrent double-processing" requirement, but only one recovers cleanly from a mid-run
  crash.
- **Inconsistent failure-feedback pattern**: most mutating UI components (M-068, M-070,
  M-076) show a toast on failure; M-074 (Exception resolve/flag/skip) shows none at all.
