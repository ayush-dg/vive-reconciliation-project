'use client';

import { useState } from 'react';
import Link from 'next/link';
import InlineLoadError from '@/components/InlineLoadError';
import type { VendorExceptionSummary } from '@/lib/exceptionsList';
import { humanizeVendorSlug } from '@/lib/vendorDisplay';

export default function ExceptionsVendorListView({ initial }: { initial: VendorExceptionSummary[] }) {
  const [vendors, setVendors] = useState(initial);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      const res = await fetch('/api/exceptions');
      if (!res.ok) {
        setLoadError(true);
        return;
      }
      const data = (await res.json()) as { vendors: VendorExceptionSummary[] };
      setVendors(data.vendors);
      setLoadError(false);
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }

  const filtered = search.trim()
    ? vendors.filter((v) => v.vendorSlug.toLowerCase().includes(search.trim().toLowerCase()))
    : vendors;

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
          <div className="list-toolbar">
            <input
              type="search"
              placeholder="Search vendor…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              data-testid="exceptions-vendor-search-input"
            />
            <button type="button" className="btn btn-secondary" disabled={loading} onClick={refresh} data-testid="exceptions-vendor-refresh">
              {loading ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>

          {loadError && <InlineLoadError onRetry={refresh} />}

          <table data-testid="exceptions-vendor-table">
            <thead>
              <tr>
                <th>Vendor</th>
                <th>Missing in ERP</th>
                <th>Amount mismatch</th>
                <th>Resolved</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 && (
                <tr key="empty">
                  <td colSpan={4} style={{ color: 'var(--text-faint)', textAlign: 'center' }} data-testid="exceptions-vendor-empty-state">
                    {search ? 'No matching vendors' : 'No exceptions — all statements reconciled cleanly'}
                  </td>
                </tr>
              )}
              {filtered.map((v) => {
                const pct = v.total > 0 ? Math.round((v.resolvedCount / v.total) * 100) : 0;
                return (
                  <tr key={v.vendorSlug} data-testid={`exceptions-vendor-row-${v.vendorSlug}`}>
                    <td>
                      <Link href={`/exceptions/${encodeURIComponent(v.vendorSlug)}`} data-testid={`exceptions-vendor-link-${v.vendorSlug}`}>
                        {humanizeVendorSlug(v.vendorSlug)}
                      </Link>
                    </td>
                    <td className="mono">{v.missingCount}</td>
                    <td className="mono">{v.mismatchCount}</td>
                    <td>
                      <div className="vlr-progress">
                        <div className="progress-track">
                          <div className="progress-fill" style={{ width: `${pct}%` }} />
                        </div>
                        <span className="mono" style={{ fontSize: 12 }}>
                          {v.resolvedCount}/{v.total}
                        </span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
