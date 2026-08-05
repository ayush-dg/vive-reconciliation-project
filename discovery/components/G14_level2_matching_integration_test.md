## G14 — Level 2 Matching Real-Pipeline Integration Test
ID: M-050
Layer: infra
Source file: `tests/test_level2_matching_integration.py`

**Module** — Level 2 Matching Real-Pipeline Integration Test
**ID** — M-050
**Layer** — infra
**Primary Responsibility** — End-to-end test proving Level 2 (RO+amount) matching fires correctly through the real `run_intake()` → `generate_mock_erp()` → `run_matching()` chain — only the AI network call is faked (via a monkeypatched `client_factory.get_ai_client`); every other function is the real production code, run against a real temporary SQLite database with the full migration history applied.

**Inputs** — A synthetic 2-invoice `FakeVisionClient` response (one Level-2-only candidate via a renumbered invoice number, one Level-1 control); a temp-file scenario config with `renumbered_invoices: {"STMT-100": "ERP-999"}`.

**Outputs** — Asserts against real `silver_reconciliation_standard`/`gold_matched_invoices` rows written by the real pipeline functions into a temporary SQLite DB (`tempfile.NamedTemporaryFile`, cleaned up via `addCleanup`).

**Public Interface** — `TestLevel2MatchingFiresThroughRealPipeline` (unittest `TestCase`), one test method: `test_level2_ro_and_amount_match_fires_when_invoice_numbers_differ`.

**Error Behaviour** — Standard `unittest` assertion failures; `setUp()`'s `mock.patch`/`mock.patch.dict` calls are registered via `addCleanup` so they unwind even if the test body raises partway through.

**Known Fragility**
- **This test exists specifically because Level 2 matching had never fired through any real pipeline run before this commit** (`d77f305`) — 0 of 1,940 historical `gold_matched_invoices` rows were ever Level 2, because the mock ERP generator (M-035) had no prior controlled-exception type that could vary `invoice_number` independently between sides. If `renumbered_invoices` were ever removed from M-035 without updating this test, it would break loudly (a clear signal), which is the intended safety net.
- Defensively forces `AZURE_SQL_SERVER=""` in the test environment regardless of the invoking shell's actual environment — a deliberate guard against this test accidentally running against real Azure SQL/Fabric if the developer's shell happens to have those variables set.
- Loads `notebooks/01_document_intake.py` via `importlib.util.spec_from_file_location()` (the same pattern M-021 uses) rather than a normal import — any change to that dynamic-loading pattern in M-021 should be mirrored here, or this test's method of reaching `run_intake()` could silently diverge from how it's actually invoked in production.

**Change Impact** — A regression here is a strong signal that either the matching engine's Level 2 path (M-034) or the mock ERP generator's `renumbered_invoices` handling (M-035) broke — this test is the only place in the codebase that exercises that interaction end-to-end.

**Callers** — none (test entry point, run via `pytest`/`unittest`)
**Calls** — M-017 (`run_intake`, via dynamic load), M-035 (`generate_mock_erp`, `normalize_erp_to_silver`), M-034 (`run_matching`), M-038 (`apply_pending_migrations`)
**Integration Points Used** — none directly (AI call is faked; database is a real temporary SQLite file, IP-008 in spirit but not a live connection to the system's actual configured backend)
