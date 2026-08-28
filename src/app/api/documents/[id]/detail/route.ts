import { NextResponse } from 'next/server';
import { getDocumentDetail } from '@/lib/documentDetail';

// GET: Document Detail screen's refresh endpoint (Task 6.5) — re-fetched after an
// Extract/Reconcile action so the status badge and extraction summary update without a
// full page reload.
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const detail = getDocumentDetail(id);
  if (!detail) {
    return NextResponse.json({ error: 'Document not found.' }, { status: 404 });
  }
  return NextResponse.json(detail);
}
