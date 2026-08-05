# MODULE_CONTRACTS.md — VIVE Reconciliation
Produced by: BCE Stage 2 Sessions B, C, G (CC) — Path A (Custodian-Live), fresh extraction
Date: 2026-08-05

No Stage 1 skeletons exist (Path A has no Stage 1) — every entry below is fresh, produced directly from a full read of the module's source file this session, not from docstrings or the archived record. Full per-module detail lives in `discovery/components/`; this file indexes all 50 and rolls up cross-cutting findings that recur across multiple contracts. This is a **fresh baseline** superseding the archived `MODULE_CONTRACTS.md` (`discovery/_archive_2026-07/`) — module numbering was not preserved (see `TOPOLOGY.md`'s header note).

**Methodology note (carried forward, re-confirmed):** No UI-layer (U) modules exist in this system — server-rendered FastAPI/Jinja2, no SPA/component architecture to justify the PBVI-011 route/page/layout/component/store split.

---

## Index

### Serving layer (15 modules)

| ID | Module | Component file |
|---|---|---|
| M-001 | FastAPI entry point | [B01_fastapi_entry_point.md](components/B01_fastapi_entry_point.md) |
| M-002 | Shared web dependencies | [B02_shared_web_dependencies.md](components/B02_shared_web_dependencies.md) |
| M-003 | Web query layer | [B03_web_query_layer.md](components/B03_web_query_layer.md) |
| M-004 | Uvicorn launcher | [B04_uvicorn_launcher.md](components/B04_uvicorn_launcher.md) |
| M-005 | Background worker pool | [B05_background_worker_pool.md](components/B05_background_worker_pool.md) |
| M-006 | Auth router | [B06_auth_router.md](components/B06_auth_router.md) |
| M-007 | Dashboard router | [B07_dashboard_router.md](components/B07_dashboard_router.md) |
| M-008 | Exceptions router | [B08_exceptions_router.md](components/B08_exceptions_router.md) |
| M-009 | Jobs router | [B09_jobs_router.md](components/B09_jobs_router.md) |
| M-010 | Reports router | [B10_reports_router.md](components/B10_reports_router.md) |
| M-011 | Review queue router | [B11_review_queue_router.md](components/B11_review_queue_router.md) |
| M-012 | Upload router | [B12_upload_router.md](components/B12_upload_router.md) |
| M-013 | Users router | [B13_users_router.md](components/B13_users_router.md) |
| M-014 | Batches router | [B14_batches_router.md](components/B14_batches_router.md) |
| M-015 | Intake trigger router (Event Grid webhook) | [B15_intake_trigger_router.md](components/B15_intake_trigger_router.md) |

### Pipeline layer (21 modules)

| ID | Module | Component file |
|---|---|---|
| M-016 | Lakehouse schema setup entry point | [C01_lakehouse_schema_setup.md](components/C01_lakehouse_schema_setup.md) |
| M-017 | Document intake pipeline | [C02_document_intake_pipeline.md](components/C02_document_intake_pipeline.md) |
| M-018 | Mock ERP generation entry point | [C03_mock_erp_entry_point.md](components/C03_mock_erp_entry_point.md) |
| M-019 | Matching engine entry point | [C04_matching_entry_point.md](components/C04_matching_entry_point.md) |
| M-020 | Report generation entry point | [C05_report_entry_point.md](components/C05_report_entry_point.md) |
| M-021 | Full pipeline orchestrator | [C06_full_pipeline_orchestrator.md](components/C06_full_pipeline_orchestrator.md) |
| M-022 | AI client contract | [C07_ai_client_contract.md](components/C07_ai_client_contract.md) |
| M-023 | AI client factory | [C08_ai_client_factory.md](components/C08_ai_client_factory.md) |
| M-024 | Document understanding engine | [C09_document_understanding_engine.md](components/C09_document_understanding_engine.md) |
| M-025 | Claude Sonnet 4.6 client (active primary) | [C10_claude_sonnet_client.md](components/C10_claude_sonnet_client.md) |
| M-026 | Claude Haiku 4.5 client | [C11_claude_haiku_client.md](components/C11_claude_haiku_client.md) |
| M-027 | Azure OpenAI client (dormant) | [C12_azure_openai_client.md](components/C12_azure_openai_client.md) |
| M-028 | Azure Document Intelligence client (dormant) | [C13_document_intelligence_client.md](components/C13_document_intelligence_client.md) |
| M-029 | Gemini client (dormant) | [C14_gemini_client.md](components/C14_gemini_client.md) |
| M-030 | Mistral client (dormant) | [C15_mistral_client.md](components/C15_mistral_client.md) |
| M-031 | pdfplumber fallback extraction | [C16_pdfplumber_fallback.md](components/C16_pdfplumber_fallback.md) |
| M-032 | OCR extractor (Tesseract) | [C17_ocr_extractor.md](components/C17_ocr_extractor.md) |
| M-033 | Exception explanation service | [C18_explanation_service.md](components/C18_explanation_service.md) |
| M-034 | Matching engine | [C19_matching_engine.md](components/C19_matching_engine.md) |
| M-035 | Mock ERP generator | [C20_mock_erp_generator.md](components/C20_mock_erp_generator.md) |
| M-036 | Invoice number normalization | [C21_invoice_normalization.md](components/C21_invoice_normalization.md) |

### Infra layer (14 modules)

| ID | Module | Component file |
|---|---|---|
| M-037 | Lakehouse connection (storage backend abstraction) | [G01_lakehouse_connection.md](components/G01_lakehouse_connection.md) |
| M-038 | SQLite migration runner | [G02_sqlite_migration_runner.md](components/G02_sqlite_migration_runner.md) |
| M-039 | Azure SQL schema creator | [G03_azure_sql_schema_creator.md](components/G03_azure_sql_schema_creator.md) |
| M-040 | AI audit logger | [G04_ai_audit_logger.md](components/G04_ai_audit_logger.md) |
| M-041 | AI-call concurrency limiter | [G05_ai_concurrency_limiter.md](components/G05_ai_concurrency_limiter.md) |
| M-042 | Shop owner routing lookup | [G06_shop_owner_lookup.md](components/G06_shop_owner_lookup.md) |
| M-043 | Blob Storage client | [G07_blob_storage_client.md](components/G07_blob_storage_client.md) |
| M-044 | Provider chain smoke test | [G08_provider_chain_smoke_test.md](components/G08_provider_chain_smoke_test.md) |
| M-045 | Fabric Warehouse connection smoke test | [G09_fabric_connection_smoke_test.md](components/G09_fabric_connection_smoke_test.md) |
| M-046 | Review queue cleanup script | [G10_review_queue_cleanup_script.md](components/G10_review_queue_cleanup_script.md) |
| M-047 | Azure SQL detection probe | [G11_azure_sql_detection_probe.md](components/G11_azure_sql_detection_probe.md) |
| M-048 | Worker simulation (basic) | [G12_worker_simulation_basic.md](components/G12_worker_simulation_basic.md) |
| M-049 | Worker simulation (exact path replication) | [G13_worker_simulation_path_exact.md](components/G13_worker_simulation_path_exact.md) |
| M-050 | Level 2 matching real-pipeline integration test | [G14_level2_matching_integration_test.md](components/G14_level2_matching_integration_test.md) |

---

## Cross-Cutting Findings

Findings that recur across, or connect, multiple module contracts — recorded once here rather than duplicated in each affected file.

**1. The Fabric cut-over's concurrency-unsafe `id` assignment spans three tables and two modules.** `extraction_cache`, `document_intake_log`, and `validation_document_review_queue` all lost their `IDENTITY` property on the Fabric side; M-037's `execute_sql_fabric()`/`execute_query_fabric()` provide no compensating lock, so every write site in M-003 and M-017 independently computes `MAX(id) + 1` in Python. This is the single most consequential finding from Sessions B/C/G — a real, currently-live risk, not a hypothetical one, worth a RISK_REGISTER entry before Session E.

**2. `VISION_PROMPT` (M-024) is unreachable dead code for the active provider.** M-025 (Claude Sonnet, active primary) ignores the passed `prompt` argument entirely and sends its own internal `EXTRACTION_PROMPT`. The careful column-mapping and confidence-calibration instructions in `VISION_PROMPT` currently affect nothing in production — confirmed independently in this session, consistent with the archived record's STAGE-2-DIVERGENCE #1.

**3. Seven independently-scoped `*_status`/`*_confidence` naming collisions, spanning M-003/M-034/M-042 and the Gold/platform tables they write.** Already captured in `discovery/F02_vocabulary_extraction.md`'s Naming Pattern Flags — repeated here because Sessions B/C/G's per-module fragility notes (M-034 especially) independently arrived at the same finding from the code side, not just the schema side.

**4. The hardcoded fallback admin credential (M-006) remains live, with no tracked removal trigger.** Confirmed present and unchanged this session — same finding as the archived `RISK_REGISTER.md` R-007, now re-verified against current source rather than carried forward on trust.

**5. `friendly_dt()`'s IST hardcoding (M-002) is the same unfixed gap flagged throughout this session's earlier discussion (R-011)** — confirmed still present in `web/deps.py`, affecting every timestamp rendered anywhere in the app.

**6. Two distinct "looks like a bug, isn't" traps worth flagging together, since both could waste a future engineer's time chasing a non-issue:** M-008's bulk-approve threshold (0.99, structurally unreachable by any exception type scoring ≤0.90 today) and M-025's confidence-constant naming (`ROW_CONFIDENCE` feeds document-level confidence only, not per-row — genuine per-row confidence comes from `_parse_confidence()`).

**7. Route-registration-order dependencies exist in exactly one place (M-008)** — the greedy `:path` converter issue between `/bulk-approve`/`/escalate` and the generic action route. Not found to recur elsewhere in the 15 serving-layer modules checked this session.

**8. RULE-01's restraint (M-036, invoice number normalization) is the codebase's clearest example of "correct because it does less."** Flagged explicitly in its own contract as the highest-risk-of-well-intentioned-regression module — worth Session D (Invariant Catalogue) formalizing this as a named invariant, not just a code comment, given how easy it would be for a future engineer to "improve" it back into the bug it was reverted from.

---

Sessions B, C, and G are complete (no U-layer modules exist). `MODULE_CONTRACTS.md` must be committed before Session D (Invariant Catalogue) begins.
