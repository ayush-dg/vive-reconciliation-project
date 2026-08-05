# ID Registry — VIVE Reconciliation

Single sequential log of every ID assigned across SYSTEM_GRAPH.json and DOMAIN_MODEL.json. Guarantees no ID collisions across separate extraction sessions.

| ID | Type | Name | Graph | Assigned |
|---|---|---|---|---|
| M-001 | Module | auth router | SYSTEM_GRAPH.json | Session A |
| M-002 | Module | dashboard router | SYSTEM_GRAPH.json | Session A |
| M-003 | Module | exceptions router | SYSTEM_GRAPH.json | Session A |
| M-004 | Module | jobs router | SYSTEM_GRAPH.json | Session A |
| M-005 | Module | reports router | SYSTEM_GRAPH.json | Session A |
| M-006 | Module | review_queue router | SYSTEM_GRAPH.json | Session A |
| M-007 | Module | upload router | SYSTEM_GRAPH.json | Session A |
| M-008 | Module | users router | SYSTEM_GRAPH.json | Session A |
| M-009 | Module | web app entry | SYSTEM_GRAPH.json | Session A |
| M-010 | Module | web shared deps | SYSTEM_GRAPH.json | Session A |
| M-011 | Module | web query layer | SYSTEM_GRAPH.json | Session A |
| M-012 | Module | web launcher | SYSTEM_GRAPH.json | Session A |
| M-013 | Module | background job worker | SYSTEM_GRAPH.json | Session A |
| M-014 | Module | document intake pipeline | SYSTEM_GRAPH.json | Session A |
| M-015 | Module | mock ERP CLI entry | SYSTEM_GRAPH.json | Session A |
| M-016 | Module | matching CLI entry | SYSTEM_GRAPH.json | Session A |
| M-017 | Module | report CLI entry | SYSTEM_GRAPH.json | Session A |
| M-018 | Module | full pipeline orchestrator | SYSTEM_GRAPH.json | Session A |
| M-019 | Module | lakehouse schema setup | SYSTEM_GRAPH.json | Session A |
| M-020 | Module | document understanding engine | SYSTEM_GRAPH.json | Session A |
| M-021 | Module | Azure OpenAI client | SYSTEM_GRAPH.json | Session A |
| M-022 | Module | Claude (Haiku 4.5) client | SYSTEM_GRAPH.json | Session A |
| M-023 | Module | Claude Sonnet 4.6 client | SYSTEM_GRAPH.json | Session A |
| M-024 | Module | Azure Document Intelligence client | SYSTEM_GRAPH.json | Session A |
| M-025 | Module | Gemini client | SYSTEM_GRAPH.json | Session A |
| M-026 | Module | Mistral client | SYSTEM_GRAPH.json | Session A |
| M-027 | Module | OCR extractor | SYSTEM_GRAPH.json | Session A |
| M-028 | Module | pdfplumber fallback | SYSTEM_GRAPH.json | Session A |
| M-029 | Module | explanation service | SYSTEM_GRAPH.json | Session A |
| M-030 | Module | AI client contract | SYSTEM_GRAPH.json | Session A |
| M-031 | Module | AI client factory | SYSTEM_GRAPH.json | Session A |
| M-032 | Module | AI audit logger | SYSTEM_GRAPH.json | Session A |
| M-033 | Module | lakehouse connection | SYSTEM_GRAPH.json | Session A |
| M-034 | Module | SQLite migration runner | SYSTEM_GRAPH.json | Session A |
| M-035 | Module | Azure SQL schema creator | SYSTEM_GRAPH.json | Session A |
| M-036 | Module | matching engine | SYSTEM_GRAPH.json | Session A |
| M-037 | Module | mock ERP generator | SYSTEM_GRAPH.json | Session A |
| M-038 | Module | invoice normalization | SYSTEM_GRAPH.json | Session A |
| M-039 | Module | Blob Storage client | SYSTEM_GRAPH.json | Session A |
| M-040 | Module | provider-chain smoke test | SYSTEM_GRAPH.json | Session A |
| M-041 | Module | review-queue cleanup script | SYSTEM_GRAPH.json | Session A |
| M-042 | Module | Azure-SQL-detection probe | SYSTEM_GRAPH.json | Session A |
| M-043 | Module | worker simulation (basic) | SYSTEM_GRAPH.json | Session A |
| M-044 | Module | worker simulation (path-exact) | SYSTEM_GRAPH.json | Session A |
| M-045 | Module | batches router | SYSTEM_GRAPH.json | Scoped BCE refresh, 2026-07-25 |
| M-046 | Module | intake_trigger router (Event Grid webhook) | SYSTEM_GRAPH.json | Scoped BCE refresh, 2026-07-25 |
| M-047 | Module | AI-call concurrency limiter | SYSTEM_GRAPH.json | Scoped BCE refresh, 2026-07-25 |
| M-048 | Module | shop owner routing lookup | SYSTEM_GRAPH.json | Scoped BCE refresh, 2026-07-25 |
| IP-001 | IntegrationPoint | Claude Sonnet 4.6 (Anthropic, Azure AI Foundry) — active primary | SYSTEM_GRAPH.json | Session A |
| IP-002 | IntegrationPoint | Claude Haiku 4.5 (Anthropic, Azure AI Foundry) — explanation service | SYSTEM_GRAPH.json | Session A |
| IP-003 | IntegrationPoint | Azure OpenAI (gpt-5-mini/nano/5.1) — registered, inactive | SYSTEM_GRAPH.json | Session A |
| IP-004 | IntegrationPoint | Azure Document Intelligence (prebuilt-layout) — registered, inactive | SYSTEM_GRAPH.json | Session A |
| IP-005 | IntegrationPoint | Google Gemini 2.5 Flash — registered, inactive | SYSTEM_GRAPH.json | Session A |
| IP-006 | IntegrationPoint | Mistral Medium — registered, inactive | SYSTEM_GRAPH.json | Session A |
| IP-007 | IntegrationPoint | Tesseract OCR + Poppler (local binaries) | SYSTEM_GRAPH.json | Session A |
| IP-008 | IntegrationPoint | Lakehouse database (SQLite / Azure SQL) | SYSTEM_GRAPH.json | Session A |
| IP-009 | IntegrationPoint | Azure Blob Storage (vendor-statements container) | SYSTEM_GRAPH.json | Session A |
| IP-010 | IntegrationPoint | Azure Event Grid webhook (auto-intake dropzone, viverecondropzone/incoming-statements) | SYSTEM_GRAPH.json | Scoped BCE refresh, 2026-07-25 |
| E-001 | Entity | Invoice | DOMAIN_MODEL.json | Session F03 |
| A-001 | Attribute | record_id | DOMAIN_MODEL.json | Session F03 |
| A-002 | Attribute | record_source | DOMAIN_MODEL.json | Session F03 |
| A-003 | Attribute | document_type | DOMAIN_MODEL.json | Session F03 |
| A-004 | Attribute | statement_id | DOMAIN_MODEL.json | Session F03 |
| A-005 | Attribute | statement_date | DOMAIN_MODEL.json | Session F03 |
| A-006 | Attribute | vendor_id | DOMAIN_MODEL.json | Session F03 |
| A-007 | Attribute | vendor_name | DOMAIN_MODEL.json | Session F03 |
| A-008 | Attribute | shop | DOMAIN_MODEL.json | Session F03 |
| A-009 | Attribute | invoice_number | DOMAIN_MODEL.json | Session F03 |
| A-010 | Attribute | invoice_number_normalized | DOMAIN_MODEL.json | Session F03 |
| A-011 | Attribute | invoice_date | DOMAIN_MODEL.json | Session F03 |
| A-012 | Attribute | ro_number | DOMAIN_MODEL.json | Session F03 |
| A-013 | Attribute | po_number | DOMAIN_MODEL.json | Session F03 |
| A-014 | Attribute | work_order_number | DOMAIN_MODEL.json | Session F03 |
| A-015 | Attribute | amount | DOMAIN_MODEL.json | Session F03 |
| A-016 | Attribute | credit | DOMAIN_MODEL.json | Session F03 |
| A-017 | Attribute | outstanding_amount | DOMAIN_MODEL.json | Session F03 |
| A-018 | Attribute | due_date | DOMAIN_MODEL.json | Session F03 |
| A-019 | Attribute | posting_date | DOMAIN_MODEL.json | Session F03 |
| A-020 | Attribute | status | DOMAIN_MODEL.json | Session F03 |
| A-021 | Attribute | description | DOMAIN_MODEL.json | Session F03 |
| A-022 | Attribute | currency | DOMAIN_MODEL.json | Session F03 |
| A-023 | Attribute | statement_period | DOMAIN_MODEL.json | Session F03 |
| A-024 | Attribute | source_file | DOMAIN_MODEL.json | Session F03 |
| A-025 | Attribute | ingestion_timestamp | DOMAIN_MODEL.json | Session F03 |
| SV-001 | StatusVocabulary | record_source | DOMAIN_MODEL.json | Session F03 |
| SVV-001 | StatusValue | VENDOR_STATEMENT (record_source) | DOMAIN_MODEL.json | Session F03 |
| SVV-002 | StatusValue | INTERNAL_ERP | DOMAIN_MODEL.json | Session F03 |
| SV-002 | StatusVocabulary | document_type | DOMAIN_MODEL.json | Session F03 |
| SVV-003 | StatusValue | VENDOR_STATEMENT (document_type) | DOMAIN_MODEL.json | Session F03 |
| SVV-004 | StatusValue | MOCK_ERP_EXTRACT | DOMAIN_MODEL.json | Session F03 |
| SV-003 | StatusVocabulary | ERP posting status | DOMAIN_MODEL.json | Session F03 |
| SVV-005 | StatusValue | POSTED | DOMAIN_MODEL.json | Session F03 |
| SVV-006 | StatusValue | PENDING | DOMAIN_MODEL.json | Session F03 |
