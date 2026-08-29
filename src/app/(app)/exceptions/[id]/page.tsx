import { getExceptionDetail } from '@/lib/exceptionDetail';
import ExceptionDetailView from './ExceptionDetailView';

// Exception Detail (Task 6.3, route /exceptions/:id, Detail type per UI_SURFACE.md).
// Exception-not-found throws, so the global error boundary (error.tsx) renders the same
// inline message + Retry pattern this build uses everywhere.
export default async function ExceptionDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const detail = getExceptionDetail(id);
  if (!detail) {
    throw new Error(`Exception not found: ${id}`);
  }

  return <ExceptionDetailView detail={detail} />;
}
