import { NextResponse } from 'next/server';
import { triggerMatchingForDocument } from '@/lib/matchingInvocation';

// S1: matching is never implicitly triggered by upload/intake — this route is the only
// manual entry point, called by Task 6.1's per-document "Reconcile" button, never from
// documents.ts's registration path (Task 2.2). G5: triggerMatchingForDocument() does the
// atomic ownership acquisition; a concurrent trigger on the same document gets a 409.
export async function POST(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const result = await triggerMatchingForDocument(id);

  if (!result.ok) {
    if (result.reason === 'not_found') {
      return NextResponse.json({ error: 'Document not found.' }, { status: 404 });
    }
    return NextResponse.json({ error: 'Matching already in progress for this document.' }, { status: 409 });
  }

  return NextResponse.json({ status: 'matched' });
}
