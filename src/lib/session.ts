/**
 * Session-cookie signing/verification (Task 1.3). Deliberately Edge-runtime-safe
 * (Web Crypto `crypto.subtle`, `btoa`/`atob` — no `node:crypto`, no `Buffer`)
 * because src/middleware.ts runs on Next.js's Edge runtime and imports this
 * module directly; it is also used from Node-runtime server actions, where the
 * same Web Crypto globals are available (Node 20+).
 */

export const SESSION_COOKIE_NAME = 'vive_session';

// Shared cookie options for every site that sets the session cookie (login,
// proxy's per-request refresh) — `secure` only in production so local HTTP
// dev keeps working, matching the Azure App Service (HTTPS) deployment target.
export function sessionCookieOptions() {
  return {
    httpOnly: true,
    sameSite: 'lax' as const,
    path: '/',
    secure: process.env.NODE_ENV === 'production',
  };
}

// 30-minute idle timeout per UI_SURFACE.md's Sign In spec / resolved default.
// Overridable so ui_tests/sign-in.spec.ts can exercise expiry without a real
// 30-minute wait — never overridden outside test runs.
export function getIdleTimeoutMs(): number {
  const override = process.env.SESSION_IDLE_TIMEOUT_MS;
  return override ? Number(override) : 30 * 60 * 1000;
}

export type SessionPayload = {
  userId: string;
  lastSeenAt: number; // epoch ms
};

function toBase64Url(bytes: Uint8Array): string {
  let binary = '';
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fromBase64Url(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(value.length / 4) * 4, '=');
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function getSigningKey(): Promise<CryptoKey> {
  const secret = process.env.SESSION_SECRET;
  if (!secret) {
    throw new Error('SESSION_SECRET is not set — required to sign/verify session cookies.');
  }
  return crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign', 'verify']
  );
}

export async function signSessionToken(payload: SessionPayload): Promise<string> {
  const key = await getSigningKey();
  const payloadBytes = new TextEncoder().encode(JSON.stringify(payload));
  const payloadB64 = toBase64Url(payloadBytes);
  const signature = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(payloadB64));
  const sigB64 = toBase64Url(new Uint8Array(signature));
  return `${payloadB64}.${sigB64}`;
}

export async function verifySessionToken(token: string | undefined): Promise<SessionPayload | null> {
  if (!token) return null;
  const [payloadB64, sigB64] = token.split('.');
  if (!payloadB64 || !sigB64) return null;

  try {
    const key = await getSigningKey();
    const valid = await crypto.subtle.verify(
      'HMAC',
      key,
      fromBase64Url(sigB64),
      new TextEncoder().encode(payloadB64)
    );
    if (!valid) return null;

    const payload = JSON.parse(new TextDecoder().decode(fromBase64Url(payloadB64))) as SessionPayload;
    if (typeof payload.userId !== 'string' || typeof payload.lastSeenAt !== 'number') return null;
    return payload;
  } catch {
    return null;
  }
}

export function isSessionExpired(payload: SessionPayload, now = Date.now()): boolean {
  return now - payload.lastSeenAt > getIdleTimeoutMs();
}
