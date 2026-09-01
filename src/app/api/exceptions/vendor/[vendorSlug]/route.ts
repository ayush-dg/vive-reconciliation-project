import { NextResponse } from 'next/server';
import { listExceptionsForVendor } from '@/lib/exceptionsList';

// GET: one vendor's full exception list, for the two-pane detail view's left panel
// (Exceptions screen redesign, 2026-09-01) — refetched after a resolve/flag/skip action
// so the resolve-progress bar and filter-tab counts stay in sync.
export async function GET(_request: Request, { params }: { params: Promise<{ vendorSlug: string }> }) {
  const { vendorSlug } = await params;
  return NextResponse.json({ rows: listExceptionsForVendor(vendorSlug) });
}
