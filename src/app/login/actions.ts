'use server';

import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { findUserByUsername, verifyPassword } from '@/lib/auth';
import { SESSION_COOKIE_NAME, sessionCookieOptions, signSessionToken } from '@/lib/session';

export type LoginState = { error: string | null };

export async function loginAction(_prevState: LoginState, formData: FormData): Promise<LoginState> {
  const username = String(formData.get('username') ?? '').trim();
  const password = String(formData.get('password') ?? '');

  if (!username || !password) {
    return { error: 'Enter your username and password.' };
  }

  const user = await findUserByUsername(username);
  if (!user || !verifyPassword(password, user.passwordHash)) {
    // Deliberately identical message for "no such user" and "wrong password" —
    // do not disclose which one failed.
    return { error: 'Invalid username or password.' };
  }

  const token = await signSessionToken({ userId: user.userId, username: user.username, lastSeenAt: Date.now() });
  const store = await cookies();
  store.set(SESSION_COOKIE_NAME, token, sessionCookieOptions());

  redirect('/home');
}

export async function logoutAction(): Promise<void> {
  const store = await cookies();
  store.delete(SESSION_COOKIE_NAME);
  redirect('/login');
}
