import { NextResponse } from 'next/server';
import { getExceptionDetail, updateExceptionResolution } from '@/lib/exceptionDetail';
import type { ExceptionStatus } from '@/lib/exceptionDetail';

// GET: Exception Detail panel's data endpoint (Task 6.3, extended 2026-09-01 with
// status/note/netsuiteRecord for the two-pane redesign).
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const detail = getExceptionDetail(id);
  if (!detail) {
    return NextResponse.json({ error: 'Exception not found.' }, { status: 404 });
  }
  return NextResponse.json(detail);
}

const VALID_STATUSES: ExceptionStatus[] = ['open', 'resolved', 'flagged', 'skipped'];

// PATCH: Mark resolved / Flag for vendor / Skip + the optional note (Exceptions screen
// redesign, 2026-09-01) — engineer-directed deviation from ARCHITECTURE.md D-C, see
// exceptionsList.ts's doc comment.
export async function PATCH(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = (await request.json().catch(() => ({}))) as { status?: string; note?: string };

  if (!body.status || !VALID_STATUSES.includes(body.status as ExceptionStatus)) {
    return NextResponse.json({ error: `status must be one of ${VALID_STATUSES.join(', ')}.` }, { status: 400 });
  }

  try {
    updateExceptionResolution(id, { status: body.status as ExceptionStatus, note: body.note });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : 'Update failed.' }, { status: 404 });
  }

  const detail = getExceptionDetail(id);
  return NextResponse.json(detail);
}
