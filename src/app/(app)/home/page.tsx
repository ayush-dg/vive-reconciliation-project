import { listDocumentsWithStatusBadge } from '@/lib/documents';
import { getHomeSummaryStats } from '@/lib/homeSummary';
import HomeView from './HomeView';

// Home screen (Task 6.1, route /home, Dashboard type per UI_SURFACE.md). Consumes Task
// 2.3's status computation, Task 2.4's Extract action, and Task 5.1's manual matching
// invocation for the new Reconcile action. Replaces Task 1.3's placeholder.
export default function HomePage() {
  const documents = listDocumentsWithStatusBadge();
  const stats = getHomeSummaryStats();

  return <HomeView initialDocuments={documents} stats={stats} />;
}
