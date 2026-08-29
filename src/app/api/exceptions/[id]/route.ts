import { NextResponse } from 'next/server';
import { getExceptionDetail } from '@/lib/exceptionDetail';

// GET: Exception Detail screen's data endpoint (Task 6.3).
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const detail = getExceptionDetail(id);
  if (!detail) {
    return NextResponse.json({ error: 'Exception not found.' }, { status: 404 });
  }
  return NextResponse.json(detail);
}
