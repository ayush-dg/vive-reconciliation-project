'use client';

import { useRef, useState } from 'react';
import Link from 'next/link';
import { useToast } from '@/components/ToastProvider';
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

export default function UploadForm({ initialDocuments }: { initialDocuments: ApiDocument[] }) {
  const [documents, setDocuments] = useState(initialDocuments);
  const [files, setFiles] = useState<File[]>([]);
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [extractingIds, setExtractingIds] = useState<Set<string>>(new Set());
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { showSuccess, showError } = useToast();

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
    setFiles(selected);
    setFileError(null);
  }

  // ENH-001 Task 2.2 — registers one file: toasts, refreshes the list, reports the
  // outcome to runBatchUploadSequenced's pure sequencing loop. Registration failure
  // is reported here (toast) and reported as ok:false, not thrown — the batch loop
  // continues to the next file regardless, it never aborts on one file's failure.
  async function registerFile(file: File): Promise<BatchRegisterResult> {
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
        return { ok: false, duplicate: false, documentId: null };
      }

      if (data.duplicate && data.legalEntityMismatch) {
        showError(
          'This exact statement was already uploaded under a different legal entity — the entity you selected was not applied.'
        );
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

      // A duplicate hit (existing document, possibly already extracted/extracting) is
      // left alone — not re-triggered; the refresh above already covers it. This is
      // also what correctly handles Design Gate Finding 2 (the same file selected
      // twice within one batch) — the second occurrence hits this exact duplicate
      // path via registerDocument()'s existing race-tolerant catch, with no
      // batch-specific handling needed.
      return { ok: true, duplicate: !!data.duplicate, documentId: data.document?.document_id ?? null };
    } catch {
      showError(`Upload failed for ${file.name} — check your connection and try again.`);
      return { ok: false, duplicate: false, documentId: null };
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    if (files.length === 0) {
      setFileError('Select a PDF statement.');
      return;
    }

    setSubmitting(true);
    try {
      // ENH-001 Task 2.2 — the actual sequencing policy (single-file fire-and-forget
      // vs. multi-file strictly sequential) lives in runBatchUploadSequenced, a pure
      // function independent of React state so it's directly unit-testable
      // (scripts/test_batch_upload_sequencing.sh) without a browser. submitting
      // stays true for a multi-file batch's whole duration — the deliberate,
      // accepted tradeoff of real sequencing, distinct from the batch-of-1 case.
      await runBatchUploadSequenced(files, registerFile, (documentId) => handleExtract(documentId, { silent: true }));
    } finally {
      setSubmitting(false);
      setFiles([]);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

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
              {files.map((f, i) => (
                <div className="file-row" key={`${f.name}-${i}`}>
                  <div className="file-icon">
                    <svg className="icon">
                      <use href="#i-file" />
                    </svg>
                  </div>
                  <div className="file-row-main">
                    <div className="file-row-top">
                      <span className="fname">{f.name}</span>
                      <span className="fsize">{(f.size / (1024 * 1024)).toFixed(1)} MB</span>
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
                      {(doc.status_badge.badge === 'Extracted' ||
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
