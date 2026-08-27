import { NextResponse, type NextRequest } from 'next/server';
import {
  SESSION_COOKIE_NAME,
  isSessionExpired,
  sessionCookieOptions,
  signSessionToken,
  verifySessionToken,
} from '@/lib/session';

// Authentication Shell (UI_SURFACE.md): applies to all authenticated screens.
// 30-minute idle timeout -> redirect to /login. Sliding window: every
// authenticated request refreshes lastSeenAt, matching "idle" (not "absolute").
export async function proxy(request: NextRequest) {
  const token = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  const payload = await verifySessionToken(token);

  if (!payload || isSessionExpired(payload)) {
    const loginUrl = new URL('/login', request.url);
    const response = NextResponse.redirect(loginUrl);
    response.cookies.delete(SESSION_COOKIE_NAME);
    return response;
  }

  const refreshed = await signSessionToken({
    userId: payload.userId,
    username: payload.username,
    lastSeenAt: Date.now(),
  });
  const response = NextResponse.next();
  response.cookies.set(SESSION_COOKIE_NAME, refreshed, sessionCookieOptions());
  return response;
}

export const config = {
  matcher: [
    /*
     * Match every route except: /login, /api/health, Next internals, and
     * common static-asset paths.
     */
    '/((?!login|api/health|_next/static|_next/image|favicon.ico).*)',
  ],
};
