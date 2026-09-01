import { listVendorsWithExceptions } from '@/lib/exceptionsList';
import ExceptionsVendorListView from './ExceptionsVendorListView';

// Exceptions landing (route /exceptions) — one row per vendor with at least one
// exception (Exceptions screen redesign, 2026-09-01). Drills into
// /exceptions/[vendorSlug] for that vendor's own two-pane exception list + detail,
// replacing the original flat all-vendor list.
export default async function ExceptionsPage() {
  const vendors = listVendorsWithExceptions();
  return <ExceptionsVendorListView initial={vendors} />;
}
