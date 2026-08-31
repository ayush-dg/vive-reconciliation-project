import { listExceptions } from '@/lib/exceptionsList';
import ExceptionsView from './ExceptionsView';

// Exceptions list (Task 6.2, route /exceptions, List type per UI_SURFACE.md).
// ?search= (e.g. Home's "Show exceptions" link for a specific vendor, 2026-08-31)
// pre-filters the initial server-rendered list, same query listExceptions() already
// supports for the client-side search box.
export default async function ExceptionsPage({ searchParams }: { searchParams: Promise<{ search?: string }> }) {
  const { search } = await searchParams;
  const initial = listExceptions({ search });
  return <ExceptionsView initial={initial} initialSearch={search ?? ''} />;
}
