/**
 * ENH-001 Task 2.2 — pure sequencing policy for a multi-PDF upload batch, decoupled
 * from React state so the "no two extraction calls ever in flight simultaneously"
 * acceptance criterion is directly unit-testable (scripts/test_batch_upload_sequencing.sh)
 * without a browser or live server. UploadForm.tsx supplies the real register/extract
 * implementations (closures over fetch, toasts, refreshDocuments); a test supplies
 * instrumented fakes with artificial delays to observe call ordering.
 *
 * Policy: a single-file batch fires extraction without awaiting it — matches
 * pre-enhancement single-file behavior byte-for-byte (regression case; the Upload
 * button must not stay blocked for however long extraction takes). A multi-file
 * batch awaits each file's full register+extract cycle before starting the next
 * file's registration — an explicit, tested requirement, not the default outcome of
 * a naive loop over N files.
 *
 * A file whose registration fails is skipped (not retried, not aborting the batch) —
 * the loop continues to the next file regardless. A file whose EXTRACTION throws is
 * treated the same way (challenge-agent Finding 1, 2026-09-04) — the batch's
 * "does not abort" guarantee must not silently depend on extractDocument() never
 * rejecting; today's real implementation (UploadForm.tsx's handleExtract) never
 * does, but this function's own contract shouldn't rely on that being true forever.
 */
export type BatchRegisterResult = {
  ok: boolean;
  duplicate: boolean;
  documentId: string | null;
};

export async function runBatchUploadSequenced<TFile>(
  files: TFile[],
  registerFile: (file: TFile) => Promise<BatchRegisterResult>,
  extractDocument: (documentId: string) => Promise<void>
): Promise<void> {
  const singleFile = files.length === 1;
  for (const file of files) {
    const result = await registerFile(file);
    if (!result.ok) {
      continue; // registration failed for this file — skip, continue the loop
    }
    if (result.duplicate) {
      continue; // existing document, possibly already extracted/extracting — left alone
    }
    if (!result.documentId) {
      // Challenge-agent Finding 2: an ok:true, non-duplicate result with no
      // documentId is anomalous (the real API always returns one for this case) —
      // nothing to extract, skip rather than silently falling through unaccounted.
      continue;
    }
    const documentId = result.documentId;
    const runExtraction = async () => {
      try {
        await extractDocument(documentId);
      } catch {
        // Symmetric to a registration failure: this file's extraction failing must
        // not abort the remaining batch.
      }
    };
    if (singleFile) {
      void runExtraction();
    } else {
      await runExtraction();
    }
  }
}
