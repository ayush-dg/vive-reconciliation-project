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
     * static assets (favicon.ico, anything under public/ served by
     * extension — e.g. /vive-logo.png). The original pattern only excluded
     * favicon.ico by name, not asset paths in general — public/vive-logo.png
     * was getting redirected to /login like any other unauthenticated route,
     * which is what actually broke next/image's optimizer (it received a
     * redirect response, not image bytes, and reported "not a valid image").
     */
    '/((?!login|api/health|_next/static|_next/image|.*\\.(?:ico|png|jpg|jpeg|gif|webp|svg|css|js|map)$).*)',
  ],
};
