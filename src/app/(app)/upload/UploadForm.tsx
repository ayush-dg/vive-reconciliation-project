'use client';

import { useRef, useState } from 'react';
import { useToast } from '@/components/ToastProvider';
import { LEGAL_ENTITIES } from '@/lib/legalEntities';
import type { ApiDocument } from '@/lib/documents';

// Fixed locale + explicit options — bare toLocaleString() depends on the
// runtime's default locale, which can (and did, in testing) differ between
// the Node server render and the browser client render, causing a React
// hydration mismatch ("8/27/2026, 2:16:10 PM" vs "27/8/2026, 2:16:10 pm").
function formatUploadTimestamp(isoLike: string): string {
  return new Date(isoLike).toLocaleString('en-US', {
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

export default function UploadForm({ initialDocuments }: { initialDocuments: ApiDocument[] }) {
  const [documents, setDocuments] = useState(initialDocuments);
  const [file, setFile] = useState<File | null>(null);
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

  // D-I: this is the only place extraction is triggered — never automatic on
  // upload. G5: the endpoint itself does the atomic ownership acquisition;
  // this handler just reflects the outcome (success -> refresh so the button
  // disappears once status flips; 409 -> already in progress).
  async function handleExtract(documentId: string) {
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
      showSuccess('Extraction started.');
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

  function pickFile(f: File | null) {
    setFile(f);
    setFileError(null);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    if (!file) {
      setFileError('Select a PDF statement.');
      return;
    }

    setSubmitting(true);
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
        showError(data.error ?? 'Upload failed.');
        return;
      }

      if (data.duplicate && data.legalEntityMismatch) {
        showError(
          'This exact statement was already uploaded under a different legal entity — the entity you selected was not applied.'
        );
      } else {
        showSuccess(
          data.duplicate
            ? 'This exact statement was already uploaded — no duplicate created.'
            : 'Statement uploaded successfully.'
        );
      }
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      await refreshDocuments();
    } catch {
      showError('Upload failed — check your connection and try again.');
    } finally {
      setSubmitting(false);
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
            pickFile(e.dataTransfer.files[0] ?? null);
          }}
        >
          <div className="dropzone-icon">
            <svg className="icon" style={{ width: 24, height: 24 }}>
              <use href="#i-folder" />
            </svg>
          </div>
          <h3>Drop vendor PDF here</h3>
          <p>PDF files only · up to 50 MB · text or scanned</p>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf"
            style={{ display: 'none' }}
            id="statement-file"
            onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
          />
          <button type="button" className="btn btn-secondary" onClick={() => fileInputRef.current?.click()}>
            Browse files
          </button>
          {file && (
            <div className="file-row" style={{ marginTop: 18, textAlign: 'left' }}>
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
            <div className="sub">Vendor is identified automatically during extraction</div>
          </div>
        </div>
        <table data-testid="uploaded-documents-table">
          <thead>
            <tr>
              <th>Vendor</th>
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
                <td>
                  {doc.vendor_id ? (
                    <span className="doc-list-vendor">{doc.vendor_id}</span>
                  ) : (
                    <span className="doc-list-vendor identifying" data-testid="vendor-identifying">
                      Identifying…
                    </span>
                  )}
                </td>
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
                    // Task 2.3's computed display badge — never the raw internal
                    // status column (see documents.ts's ApiDocument doc comment
                    // for why conflating the two was a real defect).
                    <span
                      className={`badge status-badge ${doc.status_badge.badge.toLowerCase()}`}
                      data-testid={`status-badge-${doc.document_id}`}
                    >
                      {doc.status_badge.label}
                    </span>
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
