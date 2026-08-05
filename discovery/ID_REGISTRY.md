# ID Registry — VIVE Reconciliation

Single sequential log of every ID assigned across this fresh Path A extraction (2026-08-05 onward). Guarantees no ID collisions across separate extraction sessions. This is a fresh baseline registry — it does not carry forward numbering from the archived registry (`discovery/_archive_2026-07/ID_REGISTRY.md`); see `discovery/TOPOLOGY.md`'s header note on why this pass re-numbers rather than refreshes in place.

`SYSTEM_GRAPH.json` has not yet been produced in this pass — the `Graph` column below points at the artifact that currently defines each ID (`A02_module_call_map.md` for modules, `TOPOLOGY.md` for integration points) until a fresh graph synthesis step runs.

| ID | Type | Name | Graph | Assigned |
|---|---|---|---|---|
| M-001 | Module | FastAPI entry point | A02_module_call_map.md | Session A |
| M-002 | Module | Shared web dependencies | A02_module_call_map.md | Session A |
| M-003 | Module | Web query layer | A02_module_call_map.md | Session A |
| M-004 | Module | Uvicorn launcher | A02_module_call_map.md | Session A |
| M-005 | Module | Background worker pool | A02_module_call_map.md | Session A |
| M-006 | Module | Auth router | A02_module_call_map.md | Session A |
| M-007 | Module | Dashboard router | A02_module_call_map.md | Session A |
| M-008 | Module | Exceptions router | A02_module_call_map.md | Session A |
| M-009 | Module | Jobs router | A02_module_call_map.md | Session A |
| M-010 | Module | Reports router | A02_module_call_map.md | Session A |
| M-011 | Module | Review queue router | A02_module_call_map.md | Session A |
| M-012 | Module | Upload router | A02_module_call_map.md | Session A |
| M-013 | Module | Users router | A02_module_call_map.md | Session A |
| M-014 | Module | Batches router | A02_module_call_map.md | Session A |
| M-015 | Module | Intake trigger router (Event Grid webhook) | A02_module_call_map.md | Session A |
| M-016 | Module | Lakehouse schema setup entry point | A02_module_call_map.md | Session A |
| M-017 | Module | Document intake pipeline | A02_module_call_map.md | Session A |
| M-018 | Module | Mock ERP generation entry point | A02_module_call_map.md | Session A |
| M-019 | Module | Matching engine entry point | A02_module_call_map.md | Session A |
| M-020 | Module | Report generation entry point | A02_module_call_map.md | Session A |
| M-021 | Module | Full pipeline orchestrator | A02_module_call_map.md | Session A |
| M-022 | Module | AI client contract | A02_module_call_map.md | Session A |
| M-023 | Module | AI client factory | A02_module_call_map.md | Session A |
| M-024 | Module | Document understanding engine | A02_module_call_map.md | Session A |
| M-025 | Module | Claude Sonnet 4.6 client (active primary) | A02_module_call_map.md | Session A |
| M-026 | Module | Claude Haiku 4.5 client | A02_module_call_map.md | Session A |
| M-027 | Module | Azure OpenAI client (dormant) | A02_module_call_map.md | Session A |
| M-028 | Module | Azure Document Intelligence client (dormant) | A02_module_call_map.md | Session A |
| M-029 | Module | Gemini client (dormant) | A02_module_call_map.md | Session A |
| M-030 | Module | Mistral client (dormant) | A02_module_call_map.md | Session A |
| M-031 | Module | pdfplumber fallback extraction | A02_module_call_map.md | Session A |
| M-032 | Module | OCR extractor (Tesseract) | A02_module_call_map.md | Session A |
| M-033 | Module | Exception explanation service | A02_module_call_map.md | Session A |
| M-034 | Module | Matching engine | A02_module_call_map.md | Session A |
| M-035 | Module | Mock ERP generator | A02_module_call_map.md | Session A |
| M-036 | Module | Invoice number normalization | A02_module_call_map.md | Session A |
| M-037 | Module | Lakehouse connection (storage backend abstraction) | A02_module_call_map.md | Session A |
| M-038 | Module | SQLite migration runner | A02_module_call_map.md | Session A |
| M-039 | Module | Azure SQL schema creator | A02_module_call_map.md | Session A |
| M-040 | Module | AI audit logger | A02_module_call_map.md | Session A |
| M-041 | Module | AI-call concurrency limiter | A02_module_call_map.md | Session A |
| M-042 | Module | Shop owner routing lookup | A02_module_call_map.md | Session A |
| M-043 | Module | Blob Storage client | A02_module_call_map.md | Session A |
| M-044 | Module | Provider chain smoke test | A02_module_call_map.md | Session A |
| M-045 | Module | Fabric Warehouse connection smoke test | A02_module_call_map.md | Session A |
| M-046 | Module | Review queue cleanup script | A02_module_call_map.md | Session A |
| M-047 | Module | Azure SQL detection probe | A02_module_call_map.md | Session A |
| M-048 | Module | Worker simulation (basic) | A02_module_call_map.md | Session A |
| M-049 | Module | Worker simulation (exact path replication) | A02_module_call_map.md | Session A |
| M-050 | Module | Level 2 matching real-pipeline integration test | A02_module_call_map.md | Session A |
| IP-001 | IntegrationPoint | Claude Sonnet 4.6 (Azure AI Foundry) | TOPOLOGY.md | Session A |
| IP-002 | IntegrationPoint | Claude Haiku 4.5 (Azure AI Foundry) | TOPOLOGY.md | Session A |
| IP-003 | IntegrationPoint | Azure OpenAI (gpt-5-mini/nano/5.1) | TOPOLOGY.md | Session A |
| IP-004 | IntegrationPoint | Azure Document Intelligence | TOPOLOGY.md | Session A |
| IP-005 | IntegrationPoint | Google Gemini 2.5 Flash | TOPOLOGY.md | Session A |
| IP-006 | IntegrationPoint | Mistral Medium | TOPOLOGY.md | Session A |
| IP-007 | IntegrationPoint | Tesseract OCR + Poppler (local) | TOPOLOGY.md | Session A |
| IP-008 | IntegrationPoint | Azure SQL / SQLite (lakehouse database) | TOPOLOGY.md | Session A |
| IP-009 | IntegrationPoint | Azure Blob Storage (vendor-statements container) | TOPOLOGY.md | Session A |
| IP-010 | IntegrationPoint | Azure Event Grid (auto-intake webhook) | TOPOLOGY.md | Session A |
| IP-011 | IntegrationPoint | Microsoft Fabric Warehouse (get_fabric_connection) | TOPOLOGY.md | Session A |

**Totals:** 50 modules (M-001–M-050), 11 integration points (IP-001–IP-011).
