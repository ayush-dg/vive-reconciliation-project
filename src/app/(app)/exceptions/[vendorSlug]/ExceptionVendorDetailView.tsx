'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import InlineLoadError from '@/components/InlineLoadError';
import { humanizeVendorSlug } from '@/lib/vendorDisplay';
import type { VendorExceptionRow } from '@/lib/exceptionsList';
import type { ExceptionDetailData, ExceptionStatus } from '@/lib/exceptionDetail';

const CATEGORY_LABELS: Record<string, string> = {
  amount_mismatch: 'Amount mismatch',
  not_posted: 'Missing in ERP',
};

// Fields worth surfacing before the full raw dump, in priority order — kept short and
// generic (not the mockup's fictional field list) since which custom fields a live
// NetSuite row actually carries varies per vendor; only fields present on THIS row make
// it into the highlighted grid, everything else (including these, again) shows in the
// "show all N fields" raw list below.
const HIGHLIGHT_FIELD_ORDER = ['tranid', 'total', 'trandate', 'duedate', 'status', 'entity', 'location', 'memo'];

type FilterTab = 'all' | 'missing' | 'mismatch';

function whyText(detail: ExceptionDetailData): string {
  if (detail.category === 'amount_mismatch' && detail.amountMismatch) {
    const diff = (detail.amountMismatch.statementAmount - detail.amountMismatch.netsuiteAmount).toFixed(2);
    return `Invoice #${detail.statementLine.invoiceRef ?? '—'} was matched by invoice number, but the statement amount does not match the amount recorded in NetSuite (difference: ${diff}). Review the source documents to confirm which figure is correct.`;
  }
  return `No matching bill or credit memo was found in NetSuite for invoice #${detail.statementLine.invoiceRef ?? '—'}. It may not have been posted yet, or may be recorded under a different invoice number.`;
}

export default function ExceptionVendorDetailView({
  vendorSlug,
  initialRows,
  initialSelectedId,
}: {
  vendorSlug: string;
  initialRows: VendorExceptionRow[];
  initialSelectedId: string | null;
}) {
  const [rows, setRows] = useState(initialRows);
  const [filter, setFilter] = useState<FilterTab>('all');
  const [selectedId, setSelectedId] = useState<string | null>(
    initialSelectedId && initialRows.some((r) => r.exceptionId === initialSelectedId)
      ? initialSelectedId
      : (initialRows[0]?.exceptionId ?? null)
  );
  const [detail, setDetail] = useState<ExceptionDetailData | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [listLoadError, setListLoadError] = useState(false);
  const [noteDraft, setNoteDraft] = useState('');
  const [actionPending, setActionPending] = useState(false);
  const [netsuiteOpen, setNetsuiteOpen] = useState(false);
  const [rawOpen, setRawOpen] = useState(false);

  const filteredRows = useMemo(() => {
    if (filter === 'missing') return rows.filter((r) => r.category === 'not_posted');
    if (filter === 'mismatch') return rows.filter((r) => r.category === 'amount_mismatch');
    return rows;
  }, [rows, filter]);

  // Switching tabs can leave the current selection outside the new filtered set — fall
  // back to that tab's first row rather than showing a detail panel for a row the list
  // no longer displays.
  useEffect(() => {
    if (selectedId && filteredRows.some((r) => r.exceptionId === selectedId)) return;
    setSelectedId(filteredRows[0]?.exceptionId ?? null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  async function loadDetail(id: string) {
    setDetailLoading(true);
    setNetsuiteOpen(false);
    setRawOpen(false);
    try {
      const res = await fetch(`/api/exceptions/${id}`);
      if (res.ok) {
        const data = (await res.json()) as ExceptionDetailData;
        setDetail(data);
        setNoteDraft(data.note ?? '');
      }
    } finally {
      setDetailLoading(false);
    }
  }

  useEffect(() => {
    if (selectedId) void loadDetail(selectedId);
    else setDetail(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  async function refreshRows() {
    try {
      const res = await fetch(`/api/exceptions/vendor/${encodeURIComponent(vendorSlug)}`);
      if (!res.ok) {
        setListLoadError(true);
        return;
      }
      const data = (await res.json()) as { rows: VendorExceptionRow[] };
      setRows(data.rows);
      setListLoadError(false);
    } catch {
      setListLoadError(true);
    }
  }

  async function applyAction(status: ExceptionStatus) {
    if (!selectedId) return;
    setActionPending(true);
    try {
      const res = await fetch(`/api/exceptions/${selectedId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, note: noteDraft }),
      });
      if (res.ok) {
        const data = (await res.json()) as ExceptionDetailData;
        setDetail(data);
        await refreshRows();
      }
    } finally {
      setActionPending(false);
    }
  }

  const total = rows.length;
  const resolvedCount = rows.filter((r) => r.status !== 'open').length;
  const resolvePct = total > 0 ? Math.round((resolvedCount / total) * 100) : 0;

  const selectedIndex = filteredRows.findIndex((r) => r.exceptionId === selectedId);
  const canPrev = selectedIndex > 0;
  const canNext = selectedIndex >= 0 && selectedIndex < filteredRows.length - 1;

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">
          <div className="eyebrow">
            <Link href="/exceptions" data-testid="back-to-exceptions">
              Exceptions
            </Link>{' '}
            / {humanizeVendorSlug(vendorSlug)}
          </div>
          <h1>{humanizeVendorSlug(vendorSlug)}</h1>
        </div>
      </div>

      <div className="content">
        {listLoadError && <InlineLoadError onRetry={refreshRows} />}

        <div className="detail-layout">
          <div className="detail-list">
            <div className="detail-list-head">
              <h3 data-testid="exceptions-vendor-count">{total} exceptions</h3>
              <div className="filter-tabs">
                <button
                  type="button"
                  className={`filter-tab${filter === 'all' ? ' active' : ''}`}
                  onClick={() => setFilter('all')}
                  data-testid="exceptions-filter-all"
                >
                  All
                </button>
                <button
                  type="button"
                  className={`filter-tab${filter === 'missing' ? ' active' : ''}`}
                  onClick={() => setFilter('missing')}
                  data-testid="exceptions-filter-missing"
                >
                  Missing
                </button>
                <button
                  type="button"
                  className={`filter-tab${filter === 'mismatch' ? ' active' : ''}`}
                  onClick={() => setFilter('mismatch')}
                  data-testid="exceptions-filter-mismatch"
                >
                  Mismatch
                </button>
              </div>
              <div className="resolve-track">
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${resolvePct}%` }} />
                </div>
                <span className="resolve-pct">{resolvePct}%</span>
              </div>
              <div className="resolve-count" data-testid="exceptions-resolve-count">
                {resolvedCount} / {total} resolved
              </div>
            </div>
            <div className="list-scroll">
              {filteredRows.map((row) => (
                <button
                  key={row.exceptionId}
                  type="button"
                  className={`exception-row${row.exceptionId === selectedId ? ' active' : ''}${row.status !== 'open' ? ' resolved' : ''}`}
                  onClick={() => setSelectedId(row.exceptionId)}
                  data-testid={`exception-row-${row.exceptionId}`}
                >
                  <div>
                    <div className="einv">Invoice #{row.invoiceRef ?? '—'}</div>
                    <div className="edate">{new Date(row.createdAt).toLocaleDateString('en-US')}</div>
                    <span className={`badge badge-${row.category === 'amount_mismatch' ? 'warning' : 'danger'}`}>
                      {CATEGORY_LABELS[row.category] ?? row.category}
                    </span>
                  </div>
                  <div className="exception-row-amt">{row.amount.toFixed(2)}</div>
                </button>
              ))}
              {filteredRows.length === 0 && (
                <div style={{ padding: 20, color: 'var(--text-faint)', fontSize: 13.5 }}>No exceptions in this filter.</div>
              )}
            </div>
          </div>

          <div className="detail-view-panel">
            {detailLoading && <div className="app-loading" data-testid="exception-detail-loading"><div className="spinner" />Loading…</div>}
            {!detailLoading && detail && (
              <>
                <div className="detail-view-head">
                  <h2 data-testid="exception-detail-title">
                    Invoice #{detail.statementLine.invoiceRef ?? '—'} — {humanizeVendorSlug(vendorSlug)}
                  </h2>
                  <span
                    className={`badge badge-${detail.category === 'amount_mismatch' ? 'warning' : 'danger'}`}
                    data-testid="exception-detail-category"
                  >
                    {CATEGORY_LABELS[detail.category] ?? detail.category}
                  </span>
                </div>

                <div className="field-grid">
                  <div className="field-box">
                    <div className="fb-label">Invoice number</div>
                    <div className="fb-value">{detail.statementLine.invoiceRef ?? '—'}</div>
                  </div>
                  <div className="field-box">
                    <div className="fb-label">Vendor</div>
                    <div className="fb-value muted">{humanizeVendorSlug(vendorSlug)}</div>
                  </div>
                  <div className="field-box">
                    <div className="fb-label">Statement period</div>
                    <div className="fb-value muted">{detail.statementLine.statementPeriod ?? '—'}</div>
                  </div>
                  <div className="field-box">
                    <div className="fb-label">Statement amount</div>
                    <div className="fb-value" data-testid="exception-detail-statement-amount">
                      {detail.statementLine.amount.toFixed(2)}
                    </div>
                  </div>
                  {detail.amountMismatch && (
                    <>
                      <div className="field-box">
                        <div className="fb-label">ERP amount</div>
                        <div className="fb-value" data-testid="exception-detail-erp-amount">
                          {detail.amountMismatch.netsuiteAmount.toFixed(2)}
                        </div>
                      </div>
                      <div className="field-box">
                        <div className="fb-label">Difference</div>
                        <div className="fb-value danger" data-testid="exception-detail-difference">
                          {(detail.amountMismatch.statementAmount - detail.amountMismatch.netsuiteAmount).toFixed(2)}
                        </div>
                      </div>
                    </>
                  )}
                </div>

                <div className="why-box" data-testid="exception-detail-why">
                  <span className="why-label">Why this is an exception</span>
                  {whyText(detail)}
                </div>

                <div className="field-box" style={{ marginBottom: 22 }} data-testid="ccc-evidence-panel">
                  <div className="fb-label">Related — CCC corroborating evidence</div>
                  {detail.cccCorroboration ? (
                    <div className="fb-value mono" data-testid="ccc-evidence-content" style={{ fontSize: 13, fontWeight: 500 }}>
                      RO {detail.cccCorroboration.roNumber} — {detail.cccCorroboration.amount.toFixed(2)}
                    </div>
                  ) : (
                    <div className="fb-value muted" data-testid="ccc-evidence-empty" style={{ fontSize: 13 }}>
                      No CCC confirmation available
                    </div>
                  )}
                </div>

                {detail.netsuiteRecord && (
                  <>
                    <button
                      type="button"
                      className={`db-toggle-row${netsuiteOpen ? ' open' : ''}`}
                      onClick={() => setNetsuiteOpen((v) => !v)}
                      data-testid="netsuite-record-toggle"
                    >
                      <div className="dtr-left">NetSuite record</div>
                      <span className="chev">{netsuiteOpen ? '▾' : '▸'}</span>
                    </button>
                    {netsuiteOpen && (
                      <div className="db-panel" data-testid="netsuite-record-panel">
                        <div className="db-field-grid">
                          {HIGHLIGHT_FIELD_ORDER.filter((key) => key in (detail.netsuiteRecord as object)).map((key, i) => (
                            <div className={`db-field${i === 0 ? ' highlight' : ''}`} key={key}>
                              <div className="dfb-label">{key}</div>
                              <div className="dfb-value">{String(detail.netsuiteRecord![key])}</div>
                            </div>
                          ))}
                        </div>

                        <button
                          type="button"
                          className={`db-showall-link${rawOpen ? ' open' : ''}`}
                          onClick={() => setRawOpen((v) => !v)}
                          data-testid="netsuite-raw-toggle"
                        >
                          <span>▸</span>
                          <span>
                            {rawOpen ? 'Hide' : 'Show'} all {Object.keys(detail.netsuiteRecord).length} fields
                          </span>
                        </button>
                        {rawOpen && (
                          <div className="db-raw-list" data-testid="netsuite-raw-list">
                            <div className="db-raw-grid">
                              {Object.entries(detail.netsuiteRecord)
                                .sort(([a], [b]) => a.localeCompare(b))
                                .map(([key, value]) => (
                                  <div className="db-raw-row" key={key}>
                                    <span className="draw-key">{key}</span>
                                    <span className="draw-val">{value === null || value === undefined ? '—' : String(value)}</span>
                                  </div>
                                ))}
                            </div>
                            <div className="db-raw-count">
                              {Object.keys(detail.netsuiteRecord).length} of {Object.keys(detail.netsuiteRecord).length} fields from the
                              NetSuite record
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}

                <div className="note-field">
                  <label htmlFor="exception-note">
                    Add a note <span style={{ color: 'var(--text-faint)', fontWeight: 500 }}>(optional)</span>
                  </label>
                  <textarea
                    id="exception-note"
                    value={noteDraft}
                    onChange={(e) => setNoteDraft(e.target.value)}
                    placeholder="e.g. 'Shop confirmed they'll post this by Friday' or 'Vendor confirmed it's a duplicate'"
                    data-testid="exception-note-input"
                  />
                </div>

                <div className="detail-actions">
                  <div className="action-cluster">
                    <button
                      type="button"
                      className="btn btn-primary"
                      disabled={actionPending}
                      onClick={() => applyAction('resolved')}
                      data-testid="exception-action-resolve"
                    >
                      Mark resolved
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      disabled={actionPending}
                      onClick={() => applyAction('flagged')}
                      data-testid="exception-action-flag"
                    >
                      Flag for vendor
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      disabled={actionPending}
                      onClick={() => applyAction('skipped')}
                      data-testid="exception-action-skip"
                    >
                      Skip
                    </button>
                  </div>
                  <div className="pager-cluster">
                    <button
                      type="button"
                      className="pager-btn"
                      disabled={!canPrev}
                      onClick={() => setSelectedId(filteredRows[selectedIndex - 1].exceptionId)}
                      data-testid="exception-pager-prev"
                    >
                      ←
                    </button>
                    <button
                      type="button"
                      className="pager-btn"
                      disabled={!canNext}
                      onClick={() => setSelectedId(filteredRows[selectedIndex + 1].exceptionId)}
                      data-testid="exception-pager-next"
                    >
                      →
                    </button>
                  </div>
                </div>
              </>
            )}
            {!detailLoading && !detail && filteredRows.length === 0 && (
              <div style={{ color: 'var(--text-faint)', padding: 20 }}>No exception selected.</div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
