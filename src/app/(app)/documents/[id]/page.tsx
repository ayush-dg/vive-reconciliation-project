import { getDocumentDetail } from '@/lib/documentDetail';
import DocumentDetailView from './DocumentDetailView';

// Document Detail screen (Task 6.5, route /documents/:id, Detail type per UI_SURFACE.md).
// Resolves Home's prior "View statement" gap (Task 6.1). Document-not-found throws, so
// the global error boundary (error.tsx, "per global default") renders the same inline
// message + Retry pattern this build uses everywhere, rather than a separate 404 page.
export default async function DocumentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const detail = getDocumentDetail(id);
  if (!detail) {
    throw new Error(`Document not found: ${id}`);
  }

  return <DocumentDetailView detail={detail} />;
}
