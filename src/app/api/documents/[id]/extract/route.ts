import { NextResponse } from 'next/server';
import { triggerExtraction } from '@/lib/extraction';

// D-I: separate, explicit act from upload — this route is never called from
// the registration path (Task 2.2). G5: triggerExtraction() does the atomic
// ownership acquisition; a second rapid trigger on the same document gets a
// 409, not a second extraction attempt.
export async function POST(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const result = await triggerExtraction(id);

  if (!result.ok) {
    if (result.reason === 'not_found') {
      return NextResponse.json({ error: 'Document not found.' }, { status: 404 });
    }
    return NextResponse.json({ error: 'Extraction already in progress for this document.' }, { status: 409 });
  }

  return NextResponse.json({ status: result.status });
}
