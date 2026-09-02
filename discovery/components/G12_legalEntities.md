**Module:** legalEntities.ts
**ID:** M-042
**Layer:** infra
**Primary Responsibility:** Exports a static, explicitly-placeholder list of legal-entity options for the Upload screen's dropdown — no canonical source of VIVE's real legal-entity structure exists yet.

**Inputs:** None — a static module-level constant, no parameters, no env vars, no I/O.

**Outputs:** None (no side effects) beyond the exported value itself.

**Public Interface:**
- `LEGAL_ENTITIES: readonly [{ id: 'vive-holdings'; name: 'Vive Collision Holdings, LLC' }, { id: 'vive-mid-atlantic'; name: 'Vive Collision — Mid-Atlantic Region' }, { id: 'vive-northeast'; name: 'Vive Collision — Northeast Region' }]` (declared `as const`)

**Error Behaviour:** Not applicable — no functions, cannot throw at call time. Only failure mode is the import itself failing (module load error), which is not expected under normal operation.

**Known Fragility:**
- **[NOTABLE]** The file's own header comment explicitly states these values are **not** sourced from VIVE's real legal-entity structure — UI_SURFACE.md flags this field's provenance as "a genuinely open gap," and Task 2.1 was scoped to flag it for revisiting, not resolve it. Any document's stored `legal_entity_id` is only as meaningful as this placeholder list; if a real source of truth is established elsewhere later, this hardcoded array becomes silently stale with nothing forcing reconciliation against historically stored values.
- **[NOTABLE — broader consumer set than the reference data-flow note captures]** Confirmed via direct source grep: `LEGAL_ENTITIES` is imported directly by **two** consumers, not just the one captured in the Internal Call Table's data-reference note (M-044 / `src/app/api/documents/route.ts`). `src/app/(app)/upload/UploadForm.tsx` (M-070 per the module map) also imports it directly — at line 5, to compute `const DEFAULT_LEGAL_ENTITY_ID = LEGAL_ENTITIES[0].id`, and again to render a stored `legal_entity_id` back to a human-readable name via `.find()`. Because the *default* selected entity is derived from array **order** (`LEGAL_ENTITIES[0]`), simply reordering this array silently changes the Upload form's default legal entity — a real behavior change with no test/assertion observed guarding it.
- No `id`-uniqueness or non-empty-array invariant is enforced anywhere in or around this module — a duplicate `id` would silently break `.find()`-based lookups in both consumers, and an empty array would throw at import time on `LEGAL_ENTITIES[0].id` inside UploadForm.tsx.

**Change Impact:** Direct data-consumers: M-044 (`api/documents/route.ts`, per the Internal Call Table's data-reference note) and, per direct source confirmation, `UploadForm.tsx`/M-070 (not listed in the given data-reference note — a discrepancy worth flagging to Stage 1). Any structural change (renaming `id`/`name`, reordering entries, adding/removing an entity) affects both the Upload form's dropdown/default selection and the display of `legal_entity_id` on already-uploaded documents.

**Callers:** None (no function to call — this is a static data export, not a callable module)
**Calls:** None
**Integration Points Used:** None

**Data-consumers (read `LEGAL_ENTITIES` directly, not a function call):** M-044 (per Internal Call Table); UploadForm.tsx/M-070 (confirmed via source grep — not present in the supplied data-reference note, flagged as [NOTABLE] gap relative to Stage 1 material)
