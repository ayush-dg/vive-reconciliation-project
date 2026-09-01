import { listExceptionsForVendor } from '@/lib/exceptionsList';
import ExceptionVendorDetailView from './ExceptionVendorDetailView';

// Per-vendor two-pane Exception detail (route /exceptions/:vendorSlug, Exceptions screen
// redesign, 2026-09-01) — replaces the original flat list + separate /exceptions/:id
// detail page with the mockup's master-detail architecture. ?exception=<id> optionally
// preselects a specific row (Home's "Show exceptions ->" link, updated to point here).
// No exceptions for this vendor (bad slug, or everything predates this vendor ever having
// one) throws, same "let the global error boundary handle it" pattern the old detail page
// used.
export default async function ExceptionVendorDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ vendorSlug: string }>;
  searchParams: Promise<{ exception?: string }>;
}) {
  const { vendorSlug } = await params;
  const { exception } = await searchParams;
  const rows = listExceptionsForVendor(vendorSlug);
  if (rows.length === 0) {
    throw new Error(`No exceptions found for vendor: ${vendorSlug}`);
  }
  return <ExceptionVendorDetailView vendorSlug={vendorSlug} initialRows={rows} initialSelectedId={exception ?? null} />;
}
