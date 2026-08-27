import Link from 'next/link';
import { logoutAction } from '@/app/login/actions';

// UI_SURFACE.md Global Elements > Navigation: Home, Upload, Exceptions active;
// Admin group present but disabled/non-functional (single-role build, D-E — no
// admin surface exists). No specific Admin sub-items are named anywhere in the
// signed-off docs; "Settings" is a representative placeholder label, not a
// real screen this task builds.
export default function Sidebar({ username }: { username: string }) {
  return (
    <nav aria-label="Primary" data-testid="sidebar">
      <ul>
        <li>
          <Link href="/home" data-testid="nav-home">
            Home
          </Link>
        </li>
        <li>
          <Link href="/upload" data-testid="nav-upload">
            Upload
          </Link>
        </li>
        <li>
          <Link href="/exceptions" data-testid="nav-exceptions">
            Exceptions
          </Link>
        </li>
      </ul>

      <div data-testid="admin-group">
        <span>Admin</span>
        <ul>
          <li>
            <button type="button" disabled data-testid="nav-admin-settings">
              Settings
            </button>
          </li>
        </ul>
      </div>

      <div data-testid="sidebar-user-block">
        <span data-testid="sidebar-username">{username}</span>
        <form action={logoutAction}>
          <button type="submit" data-testid="logout-button">
            Logout
          </button>
        </form>
      </div>
    </nav>
  );
}
