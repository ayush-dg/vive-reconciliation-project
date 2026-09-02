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

## Not yet assigned

Entra ID/company SSO — no IP-NNN assigned; confirmed not integrated (disabled placeholder
only, per `UI_SURFACE.md` gap #1). Will be assigned only if/when it's actually built.
