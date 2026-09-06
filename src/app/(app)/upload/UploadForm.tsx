'use client';

import { useRef, useState } from 'react';
import Link from 'next/link';
import { useToast } from '@/components/ToastProvider';
import { toastStore } from '@/lib/toastStore';
import { LEGAL_ENTITIES } from '@/lib/legalEntities';
import { runBatchUploadSequenced } from '@/lib/batchUploadSequencing';
import type { BatchRegisterResult } from '@/lib/batchUploadSequencing';
import type { ApiDocument } from '@/lib/documents';

// Fixed locale + explicit options — bare toLocaleString() depends on the
// runtime's default locale, which can (and did, in testing) differ between
// the Node server render and the browser client render, causing a React
// hydration mismatch ("8/27/2026, 2:16:10 PM" vs "27/8/2026, 2:16:10 pm").
// ENH-001 Task 1.4 (scope extended to this screen too — same duplicated function as
// HomeView.tsx's, same field, left inconsistent otherwise): fixed IST display
// (Asia/Kolkata), not user/locale-configurable. Underlying stored upload_timestamp value
// is unchanged; display-formatting only.
//
// upload_timestamp is SQLite's own `datetime('now')` — UTC, but stored as a naive
// "YYYY-MM-DD HH:MM:SS" string with no timezone marker. new Date() on that exact format
// parses it as the RUNTIME'S LOCAL system time, not UTC — silently wrong on any server
// whose local timezone isn't UTC (found during this task; the space is replaced with 'T'
// and 'Z' appended so it's unambiguously parsed as UTC before the IST conversion below).
function formatUploadTimestamp(isoLike: string): string {
  const utcIsoLike = isoLike.includes('T') ? isoLike : `${isoLike.replace(' ', 'T')}Z`;
  return new Date(utcIsoLike).toLocaleString('en-US', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  });
}

// Legal Entity is no longer user-selected (engineer-directed simplification, 2026-08-30)
// — no real legal-entity structure was ever specified (UI_SURFACE.md flagged this field's
// provenance as an open architectural gap), so every upload is now assigned this single
// fixed default. S4 (legal_entity_id must not be null) is still satisfied — more strongly
// than before, in fact, since there is no longer a code path that can omit it.
const DEFAULT_LEGAL_ENTITY_ID = LEGAL_ENTITIES[0].id;

// ENH-001 Task 2.2 — no defined maximum was set anywhere upstream (brief's own
// Known Constraints flagged this as an open decision); 15 chosen as a reasonable v1
// cap. A batch exceeding this is rejected outright, not silently truncated to 15.
const MAX_BATCH_SIZE = 15;

// ENH-001 Task 2.3 — a stable per-file identity assigned at selection time, since a
// queued/registering file has no document_id yet (that only exists once registration
// succeeds) — batch progress rows need something to key on before that point.
type BatchFile = { id: string; file: File };

type BatchRowState = 'queued' | 'registering' | 'extracting' | 'done' | 'failed';

type BatchRow = {
  id: string;
  fileName: string;
  state: BatchRowState;
  documentId: string | null;
};

export default function UploadForm({ initialDocuments }: { initialDocuments: ApiDocument[] }) {
  const [documents, setDocuments] = useState(initialDocuments);
  const [files, setFiles] = useState<BatchFile[]>([]);
  const [batchRows, setBatchRows] = useState<BatchRow[]>([]);
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [extractingIds, setExtractingIds] = useState<Set<string>>(new Set());
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { showSuccess, showError } = useToast();
  // ENH-001 Task 2.4 — a single running "X/N uploaded" toast for a real (>1 file)
  // batch, replacing N individual per-file success toasts. A ref, not state: it only
  // ever drives imperative toastStore calls, never a render, and N must be the batch's
  // actual starting size — read once here, not re-derived later once `files` is
  // cleared to [] in handleSubmit's finally block. null means "not a tracked batch"
  // (N=1 stays on the existing per-file toast — Task 2.2 already treats a lone file as
  // fire-and-forget, not a batch in this sense).
  const batchToastRef = useRef<{ toastId: string | null; successCount: number; total: number } | null>(null);

  function bumpBatchToast() {
    const state = batchToastRef.current;
    if (!state) return;
    state.successCount += 1;
    if (state.toastId) toastStore.dismiss(state.toastId);
    // Challenge agent Finding 1: the default 5s auto-dismiss is shorter than a real
    // file's full register+extract cycle can take (live Claude, not this suite's
    // mock) — an un-suppressed running counter would flicker off mid-batch and only
    // reappear on the next success, defeating the point of one persistent running
    // toast. Suppressed here (autoDismissMs: 0); handleSubmit's finally block
    // promotes the final count to a normal auto-dismissing toast once the batch
    // actually settles.
    state.toastId = toastStore.add('success', `${state.successCount}/${state.total} uploaded`, 0);
  }

  async function refreshDocuments() {
    const res = await fetch('/api/documents');
    if (res.ok) {
      const data = (await res.json()) as { documents: ApiDocument[] };
      setDocuments(data.documents);
    }
  }

  // G5: the endpoint itself does the atomic ownership acquisition; this
  // handler just reflects the outcome (success -> refresh so the button
  // disappears once status flips; 409 -> already in progress). Server-side,
  // registration (documents.ts) and extraction (extraction.ts) remain two
  // distinct calls with G5's lock still enforced between them — D-I's actual
  // separation is unchanged. What changed (2026-08-31, engineer-directed):
  // the CLIENT now chains them automatically right after a successful
  // upload (see handleSubmit's autoTriggered call below) instead of waiting
  // for a second, separate click — `silent` suppresses the "Extraction
  // started" toast for that case, since "Statement uploaded" already covers
  // it; a real failure still surfaces normally either way.
  async function handleExtract(documentId: string, options?: { silent?: boolean }) {
    setExtractingIds((prev) => new Set(prev).add(documentId));
    try {
      const res = await fetch(`/api/documents/${documentId}/extract`, { method: 'POST' });
      if (res.status === 409) {
        showError('Extraction already in progress for this document.');
        await refreshDocuments();
        return;
      }
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as { error?: string };
        showError(data.error ?? 'Failed to start extraction.');
        return;
      }
      if (!options?.silent) showSuccess('Extraction started.');
      await refreshDocuments();
    } catch {
      showError('Failed to start extraction — check your connection and try again.');
    } finally {
      setExtractingIds((prev) => {
        const next = new Set(prev);
        next.delete(documentId);
        return next;
      });
    }
  }

  // ENH-001 Task 2.2 — accepts the full selection (drag-drop FileList or the file
  // input's FileList), rejecting the WHOLE batch if it exceeds MAX_BATCH_SIZE rather
  // than silently truncating to the first 15.
  function pickFiles(fileList: FileList | null) {
    const selected = Array.from(fileList ?? []);
    if (selected.length > MAX_BATCH_SIZE) {
      setFiles([]);
      setFileError(`Select up to ${MAX_BATCH_SIZE} files at a time — ${selected.length} were selected.`);
      return;
    }
    // ENH-001 Task 2.3 — a stable id per file, assigned now rather than derived from
    // File identity/index, so batch progress rows have something reliable to key on.
    setFiles(selected.map((file) => ({ id: crypto.randomUUID(), file })));
    setFileError(null);
  }

  function updateBatchRow(id: string, patch: Partial<BatchRow>) {
    setBatchRows((prev) => prev.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  }

  function updateBatchRowByDocumentId(documentId: string, patch: Partial<BatchRow>) {
    setBatchRows((prev) => prev.map((row) => (row.documentId === documentId ? { ...row, ...patch } : row)));
  }

  // ENH-001 Task 2.2 — registers one file: toasts, refreshes the list, reports the
  // outcome to runBatchUploadSequenced's pure sequencing loop. Registration failure
  // is reported here (toast) and reported as ok:false, not thrown — the batch loop
  // continues to the next file regardless, it never aborts on one file's failure.
  // ENH-001 Task 2.3 — also drives this file's own batch-progress row: queued (set
  // when the row list was first seeded) -> registering -> failed, or -> extracting
  // (done immediately for a duplicate, since no extraction will run for it).
  async function registerFile({ id, file }: BatchFile): Promise<BatchRegisterResult> {
    updateBatchRow(id, { state: 'registering' });
    try {
      const body = new FormData();
      body.set('file', file);
      body.set('legalEntityId', DEFAULT_LEGAL_ENTITY_ID);
      const res = await fetch('/api/documents', { method: 'POST', body });
      const data = (await res.json()) as {
        document?: ApiDocument;
        duplicate?: boolean;
        legalEntityMismatch?: boolean;
        error?: string;
      };

      if (!res.ok) {
        showError(data.error ?? `Upload failed for ${file.name}.`);
        updateBatchRow(id, { state: 'failed' });
        return { ok: false, duplicate: false, documentId: null };
      }

      if (data.duplicate && data.legalEntityMismatch) {
        // A mismatch is still an error worth its own toast even inside a tracked
        // batch — Task 2.4's counter only ever counts and displays successes.
        showError(
          'This exact statement was already uploaded under a different legal entity — the entity you selected was not applied.'
        );
      } else if (batchToastRef.current) {
        bumpBatchToast();
      } else {
        showSuccess(
          data.duplicate
            ? 'This exact statement was already uploaded — no duplicate created.'
            : 'Statement uploaded successfully — extraction starting…'
        );
      }

      // Refresh immediately so the new row appears right away — extraction
      // (below) can take real, multi-second time with live Claude, and
      // waiting for it before the first refresh made a fresh upload look
      // like nothing had happened (engineer-directed fix, 2026-08-31).
      await refreshDocuments();

      const documentId = data.document?.document_id ?? null;
      // A duplicate hit (existing document, possibly already extracted/extracting) is
      // left alone — not re-triggered; the refresh above already covers it. This is
      // also what correctly handles Design Gate Finding 2 (the same file selected
      // twice within one batch) — the second occurrence hits this exact duplicate
      // path via registerDocument()'s existing race-tolerant catch, with no
      // batch-specific handling needed. No extraction runs for a duplicate, so its
      // row goes straight to 'done', not 'extracting'.
      updateBatchRow(id, { state: data.duplicate ? 'done' : 'extracting', documentId });
      return { ok: true, duplicate: !!data.duplicate, documentId };
    } catch {
      showError(`Upload failed for ${file.name} — check your connection and try again.`);
      updateBatchRow(id, { state: 'failed' });
      return { ok: false, duplicate: false, documentId: null };
    }
  }

  // ENH-001 Task 2.3 — wraps handleExtract to resolve the row's terminal state.
  // handleExtract itself never throws (its own try/catch swallows everything) and
  // its HTTP response alone can't distinguish "genuinely extracted" from "ran to
  // completion but ended in a Failed badge" (both return 200) — so the document's
  // actual resulting badge is re-checked directly after extraction settles.
  async function extractAndTrack(documentId: string) {
    await handleExtract(documentId, { silent: true });
    try {
      const res = await fetch('/api/documents');
      if (!res.ok) {
        // Challenge agent Finding 1: leaving the row at 'extracting' here would
        // permanently block batchInProgress from ever clearing (it requires every
        // row in a >1-row batch to reach a terminal state) — hiding every
        // click-through in the whole table until the next batch overwrites
        // batchRows. A transient failure on this follow-up GET must still resolve
        // the row to a terminal state, even if we can't confirm which one.
        updateBatchRowByDocumentId(documentId, { state: 'failed' });
        return;
      }
      const data = (await res.json()) as { documents: ApiDocument[] };
      const doc = data.documents.find((d) => d.document_id === documentId);
      if (!doc) {
        // Same Finding 1 principle: a document that vanished from the list
        // (shouldn't happen, but must still resolve to a terminal state) —
        // inconclusive, treated as failed rather than left stuck.
        updateBatchRowByDocumentId(documentId, { state: 'failed' });
        return;
      }
      const badge = doc.status_badge.badge;
      // Challenge agent Finding 2: handleExtract's 409 branch ("already in
      // progress" — some other trigger, e.g. a manual Extract click on this same
      // row, holds the G5 lock) returns early without this document's own
      // extraction having actually run; its badge can legitimately still be
      // 'Processing'/'Retrying' at this point. Only resolve to a terminal state
      // once the badge itself indicates one — otherwise leave the row as
      // 'extracting' rather than falsely marking it 'done'.
      if (badge === 'Failed') {
        updateBatchRowByDocumentId(documentId, { state: 'failed' });
      } else if (badge !== 'Processing' && badge !== 'Retrying') {
        updateBatchRowByDocumentId(documentId, { state: 'done' });
      }
    } catch {
      updateBatchRowByDocumentId(documentId, { state: 'failed' });
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    if (files.length === 0) {
      setFileError('Select a PDF statement.');
      return;
    }

    setSubmitting(true);
    // ENH-001 Task 2.4 — N fixed at the batch's actual starting size; null (not a
    // tracked batch) for a lone file, so its existing per-file toast is unaffected.
    batchToastRef.current = files.length > 1 ? { toastId: null, successCount: 0, total: files.length } : null;
    // ENH-001 Task 2.3 — seed every row as 'queued' before the batch starts, so a
    // file later in the queue visibly shows 'queued' while an earlier one is still
    // 'extracting', not all rows jumping to a final state at once.
    //
    // Challenge agent Finding 4 (accepted, not fixed): this unconditionally replaces
    // the whole array. Starting a new batch while a prior single-file batch's
    // fire-and-forget extraction (still pending) means that older row's progress
    // entry is silently dropped, and its later terminal-state update becomes a
    // no-op against the new array. batchRows is an ephemeral, live progress display
    // only — the "Uploaded statements" table (backed by `documents`) remains the
    // source of truth for the file's actual final state regardless; only the
    // transient progress list forgets it. Not fixed: preventing this would mean
    // either merging old rows into new batches (confusing UX — mixing two unrelated
    // uploads' progress) or blocking a new upload while any extraction is still
    // pending (defeats the whole point of fire-and-forget for single files).
    setBatchRows(files.map(({ id, file }) => ({ id, fileName: file.name, state: 'queued', documentId: null })));
    try {
      // ENH-001 Task 2.2 — the actual sequencing policy (single-file fire-and-forget
      // vs. multi-file strictly sequential) lives in runBatchUploadSequenced, a pure
      // function independent of React state so it's directly unit-testable
      // (scripts/test_batch_upload_sequencing.sh) without a browser. submitting
      // stays true for a multi-file batch's whole duration — the deliberate,
      // accepted tradeoff of real sequencing, distinct from the batch-of-1 case.
      await runBatchUploadSequenced(files, registerFile, extractAndTrack);
    } finally {
      // Challenge agent Finding 1 (cont'd): promote the batch's running-counter toast
      // (auto-dismiss suppressed while in progress, see bumpBatchToast) to a normal,
      // auto-dismissing one now that the batch has actually finished. An all-failure
      // batch never set a toastId at all — per the CC prompt, no toast shows at all
      // for that case — so there's nothing to promote.
      if (batchToastRef.current?.toastId) {
        const { toastId, successCount, total } = batchToastRef.current;
        toastStore.dismiss(toastId);
        toastStore.add('success', `${successCount}/${total} uploaded`);
      }
      batchToastRef.current = null;
      setSubmitting(false);
      setFiles([]);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  // ENH-001 Task 2.3, Design Gate Finding 3: while a multi-file batch is actively
  // running, navigating away via ANY click-through (not just one belonging to this
  // batch) would abandon the rest of it — there's no backend job queue, the
  // sequential loop is entirely client-side and unmounts with the page. Single-file
  // uploads are excluded: that click-through was never gated before this task, and a
  // 1-file "batch" was never at risk of leaving anything behind.
  const batchInProgress = batchRows.length > 1 && batchRows.some((row) => row.state !== 'done' && row.state !== 'failed');

  return (
    <div className="upload-grid">
      <div>
        <div
          className={`dropzone${dragActive ? ' drag-active' : ''}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragActive(false);
            pickFiles(e.dataTransfer.files);
          }}
        >
          <div className="dropzone-icon">
            <svg className="icon" style={{ width: 24, height: 24 }}>
              <use href="#i-folder" />
            </svg>
          </div>
          <h3>Drop vendor PDF(s) here</h3>
          <p>PDF files only · up to 50 MB each · up to {MAX_BATCH_SIZE} at a time · text or scanned</p>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf"
            multiple
            style={{ display: 'none' }}
            id="statement-file"
            onChange={(e) => pickFiles(e.target.files)}
          />
          <button type="button" className="btn btn-secondary" onClick={() => fileInputRef.current?.click()}>
            Browse files
          </button>
          {files.length > 0 && (
            <div data-testid="selected-files-list" style={{ marginTop: 18, textAlign: 'left' }}>
              {files.map(({ id, file }) => (
                <div className="file-row" key={id}>
                  <div className="file-icon">
                    <svg className="icon">
                      <use href="#i-file" />
                    </svg>
                  </div>
                  <div className="file-row-main">
                    <div className="file-row-top">
                      <span className="fname">{file.name}</span>
                      <span className="fsize">{(file.size / (1024 * 1024)).toFixed(1)} MB</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
          {fileError && (
            <p className="dropzone-error" role="alert" data-testid="upload-validation-error">
              {fileError}
            </p>
          )}
        </div>

        <form className="form-card" onSubmit={handleSubmit} data-testid="upload-form">
          <div className="form-actions">
            <button type="submit" className="btn btn-primary" style={{ width: 'auto', flex: 1 }} disabled={submitting} data-testid="upload-submit">
              {submitting ? 'Uploading…' : 'Upload statement'}
            </button>
          </div>
        </form>

        {/* ENH-001 Task 2.3 — per-file batch progress, driven live by the sequential
            loop above. Distinct from the historical "Uploaded statements" table below:
            a queued/registering row has no document_id yet, so it can't be represented
            there at all. */}
        {batchRows.length > 0 && (
          <div className="panel" style={{ marginTop: 20 }} data-testid="batch-progress-list">
            <div className="panel-head">
              <h2>Batch progress</h2>
            </div>
            {batchRows.map((row) => (
              <div className="file-row" key={row.id} data-testid={`batch-row-${row.id}`}>
                <div className="file-row-main">
                  <div className="file-row-top">
                    <span className="fname">{row.fileName}</span>
                    <span className={`badge status-badge ${row.state}`} data-testid={`batch-row-state-${row.id}`}>
                      {row.state}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel-head">
          <div>
            <h2>Uploaded statements</h2>
            <div className="sub">Showing the file you uploaded — vendor is identified automatically during extraction</div>
          </div>
        </div>
        <table data-testid="uploaded-documents-table">
          <thead>
            <tr>
              <th>File Name</th>
              <th>Legal Entity</th>
              <th>Uploaded</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {documents.length === 0 && (
              <tr key="empty">
                <td colSpan={4} style={{ color: 'var(--text-faint)', textAlign: 'center' }}>
                  No statements uploaded yet.
                </td>
              </tr>
            )}
            {documents.map((doc) => (
              <tr key={doc.document_id} data-testid={`document-row-${doc.document_id}`}>
                <td data-testid={`document-filename-${doc.document_id}`}>{doc.original_filename ?? '—'}</td>
                <td>{LEGAL_ENTITIES.find((e) => e.id === doc.legal_entity_id)?.name ?? doc.legal_entity_id}</td>
                <td className="mono">{formatUploadTimestamp(doc.upload_timestamp)}</td>
                <td>
                  {doc.status === 'registered' ? (
                    <button
                      type="button"
                      className="btn btn-secondary"
                      disabled={extractingIds.has(doc.document_id)}
                      onClick={() => handleExtract(doc.document_id)}
                      data-testid={`extract-button-${doc.document_id}`}
                    >
                      {extractingIds.has(doc.document_id) ? 'Starting…' : 'Extract'}
                    </button>
                  ) : (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      {/* Task 2.3's computed display badge — never the raw internal
                          status column (see documents.ts's ApiDocument doc comment
                          for why conflating the two was a real defect). */}
                      <span
                        className={`badge status-badge ${doc.status_badge.badge.toLowerCase()}`}
                        data-testid={`status-badge-${doc.document_id}`}
                      >
                        {doc.status_badge.label}
                      </span>
                      {/* ENH-001 Task 1.3: click-through once extraction has actually
                          completed. 'Extracted'/'Reconciling'/'Reconciled' are only
                          reachable after a successful extraction (computeDocumentStatus).
                          'Processing'/'Retrying' mean extraction isn't done yet — no link.
                          'Failed' is ambiguous by badge alone (documents.ts's own doc
                          comment: it covers both a genuine extraction failure with
                          nothing to view, and a reconciliation exception where extraction
                          DID succeed and lines exist) — open_exception_count > 0
                          disambiguates it, same field Home's own display mapping uses
                          for the identical distinction. */}
                      {!batchInProgress &&
                        (doc.status_badge.badge === 'Extracted' ||
                          doc.status_badge.badge === 'Reconciling' ||
                          doc.status_badge.badge === 'Reconciled' ||
                          (doc.status_badge.badge === 'Failed' && doc.open_exception_count > 0)) && (
                        <Link
                          href={`/documents/${doc.document_id}`}
                          data-testid={`view-extracted-lines-${doc.document_id}`}
                        >
                          View extracted lines
                        </Link>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
