import Image from 'next/image';
import Link from 'next/link';
import { logoutAction } from '@/app/login/actions';

function initials(name: string): string {
  const parts = name.replace(/[._-]+/g, ' ').trim().split(/\s+/);
  return parts
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('');
}

// UI_SURFACE.md Global Elements > Navigation: Home, Upload, Exceptions active;
// Admin group present but disabled/non-functional (single-role build, D-E — no
// admin surface exists). No specific Admin sub-items are named anywhere in the
// signed-off docs; "Settings" is a representative placeholder label, not a
// real screen this task builds. Visual design per the engineer-supplied Figma
// mockups (sessions/S02_SESSION_LOG.md Decision Log).
export default function Sidebar({ username }: { username: string }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <Image src="/vive-logo.png" alt="" width={34} height={34} />
        <div className="sidebar-brand-text">
          Reconciliation
          <span>Vive Collision</span>
        </div>
      </div>

      <nav aria-label="Primary" data-testid="sidebar">
        <div className="nav-group-label">Workspace</div>
        <Link href="/home" className="nav-item" data-testid="nav-home">
          <svg className="icon">
            <use href="#i-home" />
          </svg>
          Home
        </Link>
        <Link href="/upload" className="nav-item" data-testid="nav-upload">
          <svg className="icon">
            <use href="#i-upload" />
          </svg>
          Upload
        </Link>
        <Link href="/exceptions" className="nav-item" data-testid="nav-exceptions">
          <svg className="icon">
            <use href="#i-alert" />
          </svg>
          Exceptions
        </Link>

        <div className="nav-group-label" data-testid="admin-group">
          Admin
        </div>
        <button type="button" className="nav-item" disabled data-testid="nav-admin-settings">
          <svg className="icon">
            <use href="#i-settings" />
          </svg>
          Settings
        </button>
      </nav>

      <div className="sidebar-spacer" />

      <div className="sidebar-footer">
        <div data-testid="sidebar-user-block">
          <form action={logoutAction}>
            <button type="submit" className="sidebar-user" data-testid="logout-button">
              <span className="avatar">{initials(username)}</span>
              <span>
                <span className="sidebar-user-name" data-testid="sidebar-username">
                  {username}
                </span>
                <span className="sidebar-user-role">Sign out</span>
              </span>
            </button>
          </form>
        </div>
      </div>
    </aside>
  );
}
