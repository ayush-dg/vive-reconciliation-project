# ID_REGISTRY.md — VIVE Statement Reconciliation

All M-NNN and IP-NNN IDs assigned during BCE Stage 2 Session A (2026-09-02). These IDs are
**permanent for the life of this project** — never reassign them at later sessions.

## Module IDs (M-NNN)

Backend: M-001–M-054 (see `discovery/components/A02_module_call_map.md`'s Module Roster
for the full table — layers: infra, serving, pipeline, route).
UI: M-060–M-083 (layers: layout, page, component, store).

IDs 055–059 are a deliberate gap between the two parallel tracing passes used this
session — not an error, no modules omitted (both passes' file globs confirmed exhaustive
against their target directories).

## External Integration Point IDs (IP-NNN)

| ID | System | Called by |
|---|---|---|
| IP-001 | Claude (Anthropic) via Azure AI Foundry | M-028 |
| IP-002 | Microsoft Fabric SQL database (`recon`) | M-003 |
| IP-003 | Microsoft Fabric Lakehouse (`bronze`) | M-008 |
| IP-004 | Microsoft Fabric Warehouse (`silver`/`gold`) | M-003 (silver write path only) |
| IP-005 | n8n | N/A — n8n calls this app (M-053), not the reverse |

Full field detail for each lives in `discovery/TOPOLOGY.md`'s A03 section.

## Domain Model IDs (E-NNN / A-NNN / SV-NNN / SVV-NNN / REL-NNN)

Assigned during BCE Stage 2 Session F03 (2026-09-02, domain model synthesis). Separate
namespace from M-NNN/IP-NNN — no prefix overlaps. Full detail lives in
`discovery/DOMAIN_MODEL.json`.

| Prefix | Range | Count | Meaning |
|---|---|---|---|
| E-NNN | E-001–E-006 | 6 | Entities: Document, Vendor, StatementLine, Match, Exception, AppUser |
| A-NNN | A-001–A-038 | 38 | Attributes (columns of the 6 promoted entities) |
| SV-NNN | SV-001–SV-006 | 6 | Status vocabularies (enum/status field groupings) |
| SVV-NNN | SVV-001–SVV-019 | 19 | Individual status values across those 6 vocabularies |
| REL-NNN | REL-001–REL-006 | 6 | Relationships between entities |

**No MT-NNN (Metric) IDs** — `metricsLayer: false` in `DOMAIN_MODEL.json`; no metrics
layer exists in this build (Session 7/Gold reporting was removed, per prior planning).

**Entities NOT promoted** (recorded in `DOMAIN_MODEL.json`'s `entity_promotion_notes`,
not given E-NNN IDs): `extracted.extraction_attempt` (pipeline audit log, not a business
noun), the dynamic `extracted.stmt_<vendor_slug>` raw tables (pre-normalization staging),
`recon.document_lock` (concurrency infra), and all `bronze.*` external tables (not owned
by this build).

## Not yet assigned

Entra ID/company SSO — no IP-NNN assigned; confirmed not integrated (disabled placeholder
only, per `UI_SURFACE.md` gap #1). Will be assigned only if/when it's actually built.
