import { listExceptions } from '@/lib/exceptionsList';
import ExceptionsView from './ExceptionsView';

// Exceptions list (Task 6.2, route /exceptions, List type per UI_SURFACE.md).
export default function ExceptionsPage() {
  const initial = listExceptions();
  return <ExceptionsView initial={initial} />;
}
