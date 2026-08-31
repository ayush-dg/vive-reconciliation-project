'use client';

import { useState } from 'react';
import Link from 'next/link';
import InlineLoadError from '@/components/InlineLoadError';
import type { ExceptionsListResult } from '@/lib/exceptionsList';

const CATEGORY_LABELS: Record<string, string> = {
  amount_mismatch: 'Amount Mismatch',
  not_posted: 'Not Posted',
};

function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category;
}

export default function ExceptionsView({
  initial,
  initialSearch = '',
}: {
  initial: ExceptionsListResult;
  // Set from the URL's own ?search= param (e.g. Home's "Show exceptions" link for a
  // specific vendor, 2026-08-31) — page.tsx already applied it server-side for the
  // initial render; seeded here too so the search box/state agree with what's shown.
  initialSearch?: string;
}) {
  const [result, setResult] = useState(initial);
  const [searchInput, setSearchInput] = useState(initialSearch);
  const [appliedSearch, setAppliedSearch] = useState(initialSearch);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [lastAttempt, setLastAttempt] = useState({ search: initialSearch, page: 1 });

  async function load(search: string, page: number) {
    setLastAttempt({ search, page });
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search) params.set('search', search);
      params.set('page', String(page));
      const res = await fetch(`/api/exceptions?${params.toString()}`);
      if (res.ok) {
        setResult((await res.json()) as ExceptionsListResult);
        setLoadError(false);
      } else {
        // Per-global-default inline error + Retry (UI_SURFACE.md's Error state) — a
        // failed refetch must not leave the table silently showing stale/wrong data with
        // no signal, which is what happened here before this fix.
        setLoadError(true);
      }
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }

  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault();
    setAppliedSearch(searchInput);
    void load(searchInput, 1);
  }

  const totalPages = Math.max(1, Math.ceil(result.total / result.pageSize));

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">
          <div className="eyebrow">Exceptions</div>
          <h1>Exceptions</h1>
        </div>
      </div>

      <div className="content">
        <div className="panel">
          <form className="list-toolbar" onSubmit={handleSearchSubmit} data-testid="exceptions-search-form">
            <input
              type="search"
              placeholder="Search vendor or invoice ref…"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              data-testid="exceptions-search-input"
            />
            <button type="submit" className="btn btn-secondary" disabled={loading} data-testid="exceptions-search-submit">
              Search
            </button>
          </form>

          {loadError && <InlineLoadError onRetry={() => load(lastAttempt.search, lastAttempt.page)} />}

          <table data-testid="exceptions-table">
            <thead>
              <tr>
                <th>Vendor</th>
                <th>Statement</th>
                <th>Invoice Ref</th>
                <th>Amount</th>
                <th>Exception Type</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {result.rows.length === 0 && (
                <tr key="empty">
                  <td colSpan={6} style={{ color: 'var(--text-faint)', textAlign: 'center' }} data-testid="exceptions-empty-state">
                    {appliedSearch ? 'No matching exceptions' : 'No exceptions — all statements reconciled cleanly'}
                  </td>
                </tr>
              )}
              {result.rows.map((row) => (
                <tr key={row.exceptionId} data-testid={`exception-row-${row.exceptionId}`}>
                  <td>{row.vendorSlug ?? '—'}</td>
                  <td className="mono">{row.statementPeriod ?? '—'}</td>
                  <td className="mono">{row.invoiceRef ?? '—'}</td>
                  <td className="mono">{row.amount.toFixed(2)}</td>
                  <td>
                    <span className={`badge badge-${row.category === 'amount_mismatch' ? 'warning' : 'danger'}`} data-testid={`exception-category-${row.exceptionId}`}>
                      {categoryLabel(row.category)}
                    </span>
                  </td>
                  <td className="mono">
                    <Link href={`/exceptions/${row.exceptionId}`} data-testid={`exception-detail-link-${row.exceptionId}`}>
                      {new Date(row.createdAt).toLocaleDateString('en-US')}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="pagination" data-testid="exceptions-pagination">
            <span className="mono" data-testid="exceptions-pagination-summary">
              Page {result.page} of {totalPages} ({result.total} total)
            </span>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={loading || result.page <= 1}
              onClick={() => load(appliedSearch, result.page - 1)}
              data-testid="exceptions-prev-page"
            >
              Previous
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={loading || result.page >= totalPages}
              onClick={() => load(appliedSearch, result.page + 1)}
              data-testid="exceptions-next-page"
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
