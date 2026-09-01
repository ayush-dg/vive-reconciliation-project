import { NextResponse } from 'next/server';
import { listVendorsWithExceptions } from '@/lib/exceptionsList';

// GET: Exceptions landing screen's data + refresh endpoint — one row per vendor with at
// least one exception (Exceptions screen redesign, 2026-09-01). Per-vendor exception
// lists live at GET /api/exceptions/vendor/[vendorSlug] instead.
export async function GET() {
  return NextResponse.json({ vendors: listVendorsWithExceptions() });
}
