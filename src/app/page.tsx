import { redirect } from 'next/navigation';

// Unauthenticated root -> Sign In, per UI_SURFACE.md's Authentication Shell
// ("post-logout redirect: Sign-in screen"). Now safe to wire up — /login exists
// as of Task 1.3 (it did not yet when this route was scaffolded in Task 1.1).
export default function RootPage() {
  redirect('/login');
}
