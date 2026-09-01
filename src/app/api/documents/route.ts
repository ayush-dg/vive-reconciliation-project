import { NextResponse } from 'next/server';
import { LEGAL_ENTITIES } from '@/lib/legalEntities';
import { registerDocument, toApiDocument, listDocumentsWithStatusBadge, getOpenExceptionCount } from '@/lib/documents';
import { computeDocumentStatus } from '@/lib/documentStatus';

const MAX_FILE_BYTES = 50 * 1024 * 1024; // 50 MB, per the Upload screen's stated limit

// GET: list registered documents (uploaded-document list + Task 2.3's status
// consumer). POST: register a new upload (Task 2.2). Never calls a matching
// service — S1.
export async function GET() {
  return NextResponse.json({ documents: listDocumentsWithStatusBadge() });
}

export async function POST(request: Request) {
  let formData: FormData;
  try {
    formData = await request.formData();
  } catch {
    return NextResponse.json({ error: 'Expected multipart/form-data.' }, { status: 400 });
  }

  const file = formData.get('file');
  const legalEntityId = String(formData.get('legalEntityId') ?? '');

  if (!(file instanceof File)) {
    return NextResponse.json({ error: 'Select a PDF statement.' }, { status: 400 });
  }
  // Require a positive PDF signal (MIME type OR .pdf extension) — the previous
  // `file.type && ...` form failed open (accepted anything) whenever the
  // client reported no MIME type at all, regardless of filename.
  const looksLikePdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
  if (!looksLikePdf) {
    return NextResponse.json({ error: 'PDF files only.' }, { status: 400 });
  }
  if (file.size > MAX_FILE_BYTES) {
    return NextResponse.json({ error: 'File exceeds the 50 MB limit.' }, { status: 400 });
  }
  if (!LEGAL_ENTITIES.some((e) => e.id === legalEntityId)) {
    return NextResponse.json({ error: 'Select a legal entity.' }, { status: 400 });
  }

  const bytes = Buffer.from(await file.arrayBuffer());
  const { document, duplicate, legalEntityMismatch } = registerDocument(bytes, legalEntityId, file.name);

  const { badge, label } = computeDocumentStatus(document.documentId);
  return NextResponse.json(
    {
      document: toApiDocument(document, { badge, label }, getOpenExceptionCount(document.documentId)),
      duplicate,
      legalEntityMismatch,
    },
    { status: duplicate ? 200 : 201 }
  );
}
