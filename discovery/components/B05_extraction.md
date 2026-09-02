**Module:** extraction.ts
**ID:** M-015
**Layer:** serving
**Primary Responsibility:** The Extract trigger — atomically claims processing ownership of a document (G5 lock via a guarded status-column UPDATE) and then synchronously runs the extraction pipeline.

**Inputs:** `triggerExtraction(documentId: string): Promise<TriggerExtractionResult>` — string id, no other parameters.

**Outputs:** Side effect: `UPDATE extracted_document SET status = 'processing' WHERE document_id = ? AND status != 'processing'` — the atomic guarded UPDATE itself IS the ownership-acquisition mechanism (G5). Then invokes `runExtractionPipeline` (M-022), which performs its own further writes (not this module's responsibility, but triggered by it). Returns `TriggerExtractionResult`.

**Public Interface:**
- `export type TriggerExtractionResult = { ok: true; status: string } | { ok: false; reason: 'not_found' | 'already_processing' }`
- `export async function triggerExtraction(documentId: string): Promise<TriggerExtractionResult>`

**Error Behaviour:** No try/catch around `await runExtractionPipeline(documentId)` — if the pipeline throws, the exception propagates uncaught straight out of `triggerExtraction` to its caller (M-046). `assertSqliteMode()` also throws uncaught if not in SQLite mode. If document not found: returns `{ ok: false, reason: 'not_found' }` cleanly (no throw). If already processing (UPDATE `changes === 0`): returns `{ ok: false, reason: 'already_processing' }` cleanly.

**Known Fragility:** [NOTABLE] The document's status is flipped to `'processing'` via the atomic UPDATE *before* the pipeline runs, and there is no catch/rollback in this module if `runExtractionPipeline` throws — status would remain stuck at `'processing'` with no automatic reset here. Since the G5 guard is `WHERE status != 'processing'`, this would block any future retry trigger for that document indefinitely unless something else resets the status column. Whether `extractionPipeline.ts` (M-022) always internally catches its own errors and never lets one escape is NOT DETERMINABLE FROM SOURCE within this module alone — but this module itself provides no safety net if that assumption is ever violated.
- The G5 guard value (`'processing'`) is never reset back to a non-processing value anywhere visible in this module — the transition out of `'processing'` apparently happens elsewhere (not traced in this pass) or relies entirely on the pipeline's own completion path.
- Extraction is awaited synchronously inside the HTTP request handler chain — documented as a deliberate tradeoff (no queue infrastructure exists), but a slow/hanging extraction (e.g. OCR fallback) blocks the triggering HTTP request for its full duration; a latency fragility if extraction ever becomes materially slower.

**Change Impact:** M-046 is the sole caller — the Extract action on Upload (via M-070) and Document Detail (via M-076) both invoke it through that one route (fetch POST). A change to `TriggerExtractionResult`'s shape or reason codes breaks both UI call sites' error-branch handling.

**Callers:** M-046
**Calls:** M-003, M-022
**Integration Points Used:** None (routes through M-003)
