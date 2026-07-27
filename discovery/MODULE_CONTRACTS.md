# MODULE_CONTRACTS.md — VIVE Reconciliation
Produced by: BCE Stage 2 Sessions B, C, G (CC) — Path A (Custodian-Led)
Date: 2026-07-23; scoped refresh 2026-07-25

No Stage 1 skeletons exist (Path A has no Stage 1) — all 44 original entries were fresh, produced directly from source per the standing verification rule: every claim traces to the actual function body, not docstrings. Full per-module detail lives in `discovery/components/`; this file indexes all 48 (44 original + 4 added 2026-07-25) and rolls up the cross-cutting findings that recur across multiple contracts.

**2026-07-25 scoped refresh note:** 8 commits landed since the 2026-07-23/24 extraction (worker pool, Event Grid auto-intake + batch UI, match confidence scoring, bulk-approve/escalate, routing/aging). This pass added 4 new module contracts (M-045–M-048, marked below) and rewrote 9 existing contracts whose actual behavior changed (C01, G03, C17, B03, G12, G11, G01, B02, C02 — see each file's own updated content). The other 35 contracts were not re-verified this pass and are carried forward unchanged.

**Methodology note:** Sessions B/C/G/U were run as a single combined pass across serving, pipeline, and infra layers only — no UI-layer (U) modules exist in this system, per the engineer-confirmed methodology adaptation (server-rendered FastAPI/Jinja2, no SPA/component architecture to justify the PBVI-011 route/page/layout/component/store split — see TOPOLOGY.md).

---

## Index

### Serving layer (10 modules)

| ID | Module | Component file |
|---|---|---|
| M-001 | auth router | [B01_auth_router.md](components/B01_auth_router.md) |
| M-002 | dashboard router | [B02_dashboard_router.md](components/B02_dashboard_router.md) |
| M-003 | exceptions router | [B03_exceptions_router.md](components/B03_exceptions_router.md) |
| M-004 | jobs router | [B04_jobs_router.md](components/B04_jobs_router.md) |
| M-005 | reports router | [B05_reports_router.md](components/B05_reports_router.md) |
| M-006 | review_queue router | [B06_review_queue_router.md](components/B06_review_queue_router.md) |
| M-007 | upload router | [B07_upload_router.md](components/B07_upload_router.md) |
| M-008 | users router | [B08_users_router.md](components/B08_users_router.md) |
| M-045 | batches router *(added 2026-07-25)* | [B09_batches_router.md](components/B09_batches_router.md) |
| M-046 | intake_trigger router — Event Grid webhook *(added 2026-07-25)* | [B10_intake_trigger_router.md](components/B10_intake_trigger_router.md) |

### Pipeline layer (19 modules)

| ID | Module | Component file |
|---|---|---|
| M-013 | background job worker | [C01_background_job_worker.md](components/C01_background_job_worker.md) |
| M-014 | document intake pipeline | [C02_document_intake_pipeline.md](components/C02_document_intake_pipeline.md) |
| M-015 | mock ERP CLI entry | [C03_mock_erp_cli_entry.md](components/C03_mock_erp_cli_entry.md) |
| M-016 | matching CLI entry | [C04_matching_cli_entry.md](components/C04_matching_cli_entry.md) |
| M-017 | report CLI entry | [C05_report_cli_entry.md](components/C05_report_cli_entry.md) |
| M-018 | full pipeline orchestrator | [C06_full_pipeline_orchestrator.md](components/C06_full_pipeline_orchestrator.md) |
| M-020 | document understanding engine | [C07_document_understanding_engine.md](components/C07_document_understanding_engine.md) |
| M-021 | Azure OpenAI client | [C08_azure_openai_client.md](components/C08_azure_openai_client.md) |
| M-022 | Claude (Haiku 4.5) client | [C09_claude_haiku_client.md](components/C09_claude_haiku_client.md) |
| M-023 | Claude Sonnet 4.6 client | [C10_claude_sonnet_client.md](components/C10_claude_sonnet_client.md) |
| M-024 | Azure Document Intelligence client | [C11_azure_document_intelligence_client.md](components/C11_azure_document_intelligence_client.md) |
| M-025 | Gemini client | [C12_gemini_client.md](components/C12_gemini_client.md) |
| M-026 | Mistral client | [C13_mistral_client.md](components/C13_mistral_client.md) |
| M-027 | OCR extractor | [C14_ocr_extractor.md](components/C14_ocr_extractor.md) |
| M-028 | pdfplumber fallback | [C15_pdfplumber_fallback.md](components/C15_pdfplumber_fallback.md) |
| M-029 | explanation service | [C16_explanation_service.md](components/C16_explanation_service.md) |
| M-036 | matching engine | [C17_matching_engine.md](components/C17_matching_engine.md) |
| M-037 | mock ERP generator | [C18_mock_erp_generator.md](components/C18_mock_erp_generator.md) |
| M-038 | invoice normalization | [C19_invoice_normalization.md](components/C19_invoice_normalization.md) |

### Infra layer (19 modules)

| ID | Module | Component file |
|---|---|---|
| M-009 | web app entry | [G01_web_app_entry.md](components/G01_web_app_entry.md) |
| M-010 | web shared deps | [G02_web_shared_deps.md](components/G02_web_shared_deps.md) |
| M-011 | web query layer | [G03_web_query_layer.md](components/G03_web_query_layer.md) |
| M-012 | web launcher | [G04_web_launcher.md](components/G04_web_launcher.md) |
| M-019 | lakehouse schema setup | [G05_lakehouse_schema_setup.md](components/G05_lakehouse_schema_setup.md) |
| M-030 | AI client contract | [G06_ai_client_contract.md](components/G06_ai_client_contract.md) |
| M-031 | AI client factory | [G07_ai_client_factory.md](components/G07_ai_client_factory.md) |
| M-032 | AI audit logger | [G08_ai_audit_logger.md](components/G08_ai_audit_logger.md) |
| M-033 | lakehouse connection | [G09_lakehouse_connection.md](components/G09_lakehouse_connection.md) |
| M-034 | SQLite migration runner | [G10_sqlite_migration_runner.md](components/G10_sqlite_migration_runner.md) |
| M-035 | Azure SQL schema creator | [G11_azure_sql_schema_creator.md](components/G11_azure_sql_schema_creator.md) |
| M-039 | Blob Storage client | [G12_blob_storage_client.md](components/G12_blob_storage_client.md) |
| M-040 | provider-chain smoke test | [G13_provider_chain_smoke_test.md](components/G13_provider_chain_smoke_test.md) |
| M-041 | review-queue cleanup script | [G14_review_queue_cleanup_script.md](components/G14_review_queue_cleanup_script.md) |
| M-042 | Azure-SQL-detection probe | [G15_azure_sql_detection_probe.md](components/G15_azure_sql_detection_probe.md) |
| M-043 | worker simulation (basic) | [G16_worker_simulation_basic.md](components/G16_worker_simulation_basic.md) |
| M-044 | worker simulation (path-exact) | [G17_worker_simulation_path_exact.md](components/G17_worker_simulation_path_exact.md) |
| M-047 | AI-call concurrency limiter *(added 2026-07-25)* | [G18_ai_concurrency_limiter.md](components/G18_ai_concurrency_limiter.md) |
| M-048 | shop owner routing lookup *(added 2026-07-25)* | [G19_shop_owner_lookup.md](components/G19_shop_owner_lookup.md) |

---

## Cross-Cutting Findings (rolled up from individual contracts)

**1. Confidence fabrication is now traced to exact line numbers across all four affected clients.** M-023 (`claude_sonnet_client.py:521`), M-025 (`gemini_client.py:595`), M-026 (`mistral_client.py:356`), and M-024 (`document_intelligence_client.py:242`) all hardcode `ROW_CONFIDENCE = 0.75`. Only M-021 (Azure OpenAI) and M-022 (Claude Haiku) preserve genuine model-elicited confidence; M-028 (`pdfplumber_fallback.py`) is the only path with real, differentiated confidence (0.65/0.50). Already fully documented in `discovery/components/A02_module_call_map.md` and `discovery/DOMAIN_MODEL.json` — this module-contract pass confirms the exact code location in each file rather than adding new severity.

**2. `client_factory.py`'s (M-031) own inline comments are the clearest single piece of evidence for the AI-provider-chain divergence** — they name Gemini as "Active primary" directly above the branch that instantiates it, while `active_provider.json` (which this same file reads) names `claude_sonnet` as `provider_chain[0]`. This module contract makes explicit what TOPOLOGY.md's divergence note described more generally.

**3. A new, previously-unflagged fragility: `AIClient`'s abstract base (M-030) only formally requires `generate()`, not `generate_with_file()`.** All 6 concrete clients implement both, but the contract doesn't enforce it — a future 7th provider client implementing only `generate()` would pass the ABC check and fail at runtime with an `AttributeError` the first time `document_understanding_engine.py` calls `generate_with_file()`. Recommend an INVARIANT_CATALOGUE.md candidate at Session D.

**4. A second new finding: `run_intake()`'s "Statement ID: {statement_id}" print statement (M-014) is a load-bearing, untyped string contract with `web/worker.py`'s regex extraction (M-013).** Reformatting that one print line in `scripts/run_full_pipeline.py` (M-018) would silently break the worker's ability to record which statement a completed job produced — no test or type system would catch it. Recommend a RISK_REGISTER entry (fragile string-based inter-process contract).

**5. Level 2 matching (RO number + amount) has zero observed exercise across either database** (M-036) — real, tested, reachable code with no live evidence it has ever actually fired. Consistent with F02's vocabulary findings; not a defect, but worth confirming with the engineer whether it's still needed or defensive-only.

**6. Two independently-maintained schema sources must be kept in sync by hand** — `migrations/*.sql` (SQLite, source of truth for schema history) and `azure_sql_migrations.py`'s `TABLES`/`COLUMNS` dicts (M-035, the only path that provisions Azure SQL). Confirmed currently in sync as of this session (migrations 004-006 mirrored correctly), but nothing enforces this going forward — a missed update to M-035 would silently mean a new SQLite migration never reaches Azure SQL.

**7. `WEB_SESSION_SECRET` (M-009) defaults to a hardcoded, source-visible string if unset** — a second hardcoded-secret-adjacent finding alongside M-001's fallback login credential, both RISK_REGISTER candidates from the same root cause category (dev conveniences left enabled).

**8. `web/deps.py`'s (M-010) `friendly_dt()` hardcodes India Standard Time for all displayed timestamps** — confirmed by source, not yet confirmed against the actual AP team's location; flag for engineer confirmation at Session D/E, not assumed to be a defect.

**9. [2026-07-25] Match confidence scoring (M-036) is confirmed deterministic — IC-3/RULE-03 still holds.** `score_match_confidence()`/`score_exception_confidence()` (`src/matching/engine.py`) are pure lookup-table functions keyed on `match_level`/amount-exactness/`exception_reason` — no model call, no import of any AI client. Worth stating explicitly rather than assuming, since "confidence score" elsewhere in this codebase (M-023/M-025/M-026's fabricated `line_confidence`, see finding #1) is a loaded term in this project's history; this is a genuinely different, deterministic mechanism on a different table column.

**10. [2026-07-25] `web/queries.py` (M-011) has grown a second real dependency — on M-036 and M-048 — that its "Calls: M-033 only" line no longer reflects.** `action_review_item()` now calls `score_exception_confidence()` (M-036) and `get_shop_owner()` (M-048) directly. This is a genuine new coupling, not a doc-staleness artifact — M-011 was infra-only calling only the DB layer before this session's work; it now also depends on a pipeline module's scoring table and a second infra module's config-file lookup. Reflected in G03's rewritten Callers/Calls section.

**11. [2026-07-25] The Event Grid webhook (M-046) was unauthenticated end-to-end until this session — found during this pass's scoped security review, not by a prior BCE session.** Full writeup in `discovery/RISK_REGISTER.md` R-009 and `discovery/components/B10_intake_trigger_router.md`. Now fixed in code (shared secret, pinned container, event-count cap) but not yet deployed — the fix's value is contingent on `VIVE_EVENTGRID_WEBHOOK_SECRET` actually being generated and configured on the Azure Event Grid subscription, which is a separate infra step blocked on Azure permissions.

---

Sessions B, C, and G are complete. MODULE_CONTRACTS.md must be committed before Session D (Invariant Catalogue) begins.
