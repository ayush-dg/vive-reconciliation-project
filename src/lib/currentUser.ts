import { cookies } from 'next/headers';
import { SESSION_COOKIE_NAME, verifySessionToken, type SessionPayload } from './session';

// Server Component / Server Action helper — not used from src/proxy.ts (Edge
// middleware uses request.cookies directly, not next/headers's cookies()).
// Routes under src/app/(app)/ are guarded by proxy.ts, so a null result here
// would indicate the guard was bypassed — callers still handle it defensively.
export async function getCurrentSession(): Promise<SessionPayload | null> {
  const store = await cookies();
  return verifySessionToken(store.get(SESSION_COOKIE_NAME)?.value);
}
