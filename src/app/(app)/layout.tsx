import { redirect } from 'next/navigation';
import Sidebar from '@/components/Sidebar';
import ToastProvider from '@/components/ToastProvider';
import { getCurrentSession } from '@/lib/currentUser';

// Authenticated shell (UI_SURFACE.md Global Elements): sidebar + toast host,
// present on every route under this group. proxy.ts already redirects
// unauthenticated requests to /login before they reach here; the redirect
// below is a defensive fallback, not the primary enforcement point.
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const session = await getCurrentSession();
  if (!session) {
    redirect('/login');
  }

  return (
    <div className="app-shell">
      <Sidebar username={session.username} />
      <main className="app-main">{children}</main>
      <ToastProvider />
    </div>
  );
}
