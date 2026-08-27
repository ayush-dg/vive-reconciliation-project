import { test, expect } from '@playwright/test';
import { TEST_USERNAME, TEST_PASSWORD, TEST_USERNAME_2, TEST_PASSWORD_2, TEST_SESSION_SECRET } from './global-setup';
import { SESSION_COOKIE_NAME, signSessionToken } from '../src/lib/session';

test.describe('Sign In', () => {
  test('valid credentials navigate to /home', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Username/Email').fill(TEST_USERNAME);
    await page.getByLabel('Password').fill(TEST_PASSWORD);
    await page.getByTestId('sign-in-submit').click();
    await page.waitForURL('/home');
    await expect(page.getByTestId('home-placeholder')).toBeVisible();
  });

  test('a second, distinct named user account can also sign in independently (OD5)', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Username/Email').fill(TEST_USERNAME_2);
    await page.getByLabel('Password').fill(TEST_PASSWORD_2);
    await page.getByTestId('sign-in-submit').click();
    await page.waitForURL('/home');
    await expect(page.getByTestId('home-placeholder')).toBeVisible();
  });

  test('invalid credentials show inline error, remain on /login', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Username/Email').fill(TEST_USERNAME);
    await page.getByLabel('Password').fill('wrong-password');
    await page.getByTestId('sign-in-submit').click();
    await expect(page.getByTestId('sign-in-error')).toBeVisible();
    await expect(page.getByTestId('sign-in-error')).toHaveText('Invalid username or password.');
    expect(new URL(page.url()).pathname).toBe('/login');
  });

  test('SSO button is present but disabled', async ({ page }) => {
    await page.goto('/login');
    const sso = page.getByTestId('sso-button');
    await expect(sso).toBeVisible();
    await expect(sso).toBeDisabled();
  });

  test('session idle beyond the timeout redirects to /login on next action', async ({ page, context }) => {
    // Deliberately old lastSeenAt (well past the 30-minute default) — the same
    // signing scheme src/lib/session.ts uses, sharing SESSION_SECRET with the
    // running dev server via playwright.config.ts's webServer.env.
    process.env.SESSION_SECRET = TEST_SESSION_SECRET;
    const staleToken = await signSessionToken({
      userId: 'irrelevant-for-this-test',
      username: 'irrelevant-for-this-test',
      lastSeenAt: Date.now() - 31 * 60 * 1000,
    });

    await context.addCookies([
      {
        name: SESSION_COOKIE_NAME,
        value: staleToken,
        url: 'http://localhost:3000',
        httpOnly: true,
        sameSite: 'Lax',
      },
    ]);

    await page.goto('/home');
    await page.waitForURL('/login');
  });
});
