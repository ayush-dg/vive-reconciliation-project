**Module:** api/documents/[id]/match/route.ts
**ID:** M-047
**Layer:** route
**Primary Responsibility:** Manually triggers the matching pipeline for one document (the "Reconcile" action), acquiring a self-releasing per-document lock so a concurrent trigger on the same document is rejected with 409 rather than double-run.

**Inputs:** `POST(_request: Request, { params }: { params: Promise<{ id: string }> })` — path param `id` only; no body read, no query params.
**Outputs:**
- 200: `{ status: 'matched' }` — a fixed literal string, NOT derived from `triggerMatchingForDocument`'s return value (which is just `{ ok: true }` with no status field — this route hardcodes `'matched'` itself).
- 404: `{ error: 'Document not found.' }` when `result.reason === 'not_found'`.
- 409: `{ error: 'Matching already in progress for this document.' }` when `result.reason === 'already_processing'` — the lock acquisition (`acquireMatchingLock`) failed.
**Public Interface:**
`export async function POST(_request: Request, { params }: { params: Promise<{ id: string }> }): Promise<NextResponse>`
**Error Behaviour:** No try/catch in the route itself. `triggerMatchingForDocument` (M-017) throws via `assertSqliteMode()` if not in SQLite mode — unhandled -> 500. Unlike extraction (M-046), the matching lock in M-017 IS released on pipeline failure: `triggerMatchingForDocument` wraps `matchDocument(documentId)` in `try { ... } finally { releaseMatchingLock(documentId); }`, so if `runMatchingForDocument` (M-025) throws, the lock is released before the exception propagates up to this route (still unhandled here -> 500, but the document is NOT left stuck).
**Known Fragility:** [NOTABLE — confirmed G5 mechanism, and confirms it is NOT the same as extraction's] The 409 here is produced by `acquireMatchingLock` in M-017: an atomic `INSERT ... ON CONFLICT(document_id) DO UPDATE ... WHERE recon_document_lock.acquired_at < datetime('now', '-10 minutes')` against `recon_document_lock` — a genuinely different lock shape from M-046's non-releasing status-column lock. This lock self-releases on both success and failure (via `finally`), and additionally treats a lock older than `LOCK_STALE_AFTER_MINUTES` (10, exported from M-017) as abandoned/reclaimable — recovering from a hard process crash between acquire and release, which M-046's lock has no equivalent recovery for. A future engineer must not assume both routes' 409s mean the same thing operationally (one is permanent-until-manual-fix, the other self-heals after 10 minutes). The success body's `status: 'matched'` is hardcoded in the route, not sourced from the underlying result — if `triggerMatchingForDocument`'s result type ever gains a real status field, this route would need an explicit edit to surface it (silent staleness risk otherwise).
**Change Impact:** Called by the Home screen's per-document Reconcile action (M-068) and the Document Detail screen's Reconcile button (M-076) — both re-fetch document data afterward. Any change to the hardcoded `'matched'` literal or the 409 condition changes both UIs' post-reconcile state handling. Depends on M-017's lock semantics and `LOCK_STALE_AFTER_MINUTES`, which M-012 (documentStatus.ts) also reads directly (per A02's data-reference note) to determine display status — so a change to that constant has a blast radius beyond this route alone.
**Callers:** M-068 (HomeView.tsx, fetch POST), M-076 (DocumentDetailView.tsx, fetch POST)
**Calls:** M-017 (`src/app/api/documents/[id]/match/route.ts:10`)
**Integration Points Used:** None (routes through serving-layer modules)
