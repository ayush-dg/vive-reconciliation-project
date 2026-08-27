import { test, expect } from '@playwright/test';
import { TEST_USERNAME, TEST_SESSION_SECRET } from './global-setup';
import { SESSION_COOKIE_NAME, signSessionToken } from '../src/lib/session';

async function signInViaCookie(context: import('@playwright/test').BrowserContext) {
  process.env.SESSION_SECRET = TEST_SESSION_SECRET;
  const token = await signSessionToken({ userId: 'test-user-id', username: TEST_USERNAME, lastSeenAt: Date.now() });
  await context.addCookies([
    { name: SESSION_COOKIE_NAME, value: token, url: 'http://localhost:3000', httpOnly: true, sameSite: 'Lax' },
  ]);
}

test.describe('Global Elements', () => {
  test('sidebar renders active nav items, the signed-in username, and logout is clickable', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    await page.goto('/home');

    await expect(page.getByTestId('nav-home')).toBeVisible();
    await expect(page.getByTestId('nav-upload')).toBeVisible();
    await expect(page.getByTestId('nav-exceptions')).toBeVisible();
    await expect(page.getByTestId('sidebar-username')).toHaveText(TEST_USERNAME);
    await expect(page.getByTestId('logout-button')).toBeEnabled();
  });

  test('disabled Admin item does nothing on click', async ({ page, context }) => {
    await signInViaCookie(context);
    await page.goto('/home');

    const adminItem = page.getByTestId('nav-admin-settings');
    await expect(adminItem).toBeVisible();
    await expect(adminItem).toBeDisabled();
    // A disabled <button> cannot navigate or dispatch a click at all —
    // confirm the URL is unchanged after attempting one.
    await adminItem.click({ force: true }).catch(() => {});
    expect(new URL(page.url()).pathname).toBe('/home');
  });

  test('logout navigates to /login and actually invalidates the session', async ({ page, context }) => {
    await signInViaCookie(context);
    await page.goto('/home');
    await page.getByTestId('logout-button').click();
    await page.waitForURL('/login');

    // Not just a redirect after the click — confirm the session is actually
    // gone server-side: a fresh direct navigation to /home must also bounce
    // back to /login, not momentarily render authenticated content.
    await page.goto('/home');
    await page.waitForURL('/login');
  });

  test('unauthenticated access to an (app)-group route redirects to /login', async ({ page }) => {
    // Deliberately no signInViaCookie() — confirms proxy.ts's guard actually
    // covers this route, not just the routes other tests happen to sign into.
    await page.goto('/dev-test-error');
    await page.waitForURL('/login');
  });

  test('simulated error shows inline message with a Retry button', async ({ page, context }) => {
    await signInViaCookie(context);
    await page.goto('/dev-test-error');

    await expect(page.getByTestId('error-boundary')).toBeVisible();
    await expect(page.getByTestId('error-retry')).toBeVisible();
    // Inline, not a full-page redirect — still on the same route.
    expect(new URL(page.url()).pathname).toBe('/dev-test-error');
  });

  test('app-level loading spinner renders during a slow route transition', async ({ page, context }) => {
    await signInViaCookie(context);
    await page.goto('/home');
    await page.getByTestId('nav-home').click(); // no-op nav, just to have a starting point
    await page.goto('/dev-test-loading', { waitUntil: 'commit' });

    await expect(page.getByTestId('app-loading-spinner')).toBeVisible();
    await expect(page.getByTestId('dev-test-loading-content')).toBeVisible({ timeout: 5000 });
  });

  test('toast notifications appear bottom-right and are dismissible', async ({ page, context }) => {
    await signInViaCookie(context);
    await page.goto('/dev-test-toast');

    await page.getByTestId('trigger-success-toast').click();
    const toast = page.getByTestId('toast-success');
    await expect(toast).toBeVisible();
    await expect(toast).toContainText('Simulated success toast');

    const container = page.getByTestId('toast-container');
    const box = await container.boundingBox();
    const viewport = page.viewportSize();
    expect(box).not.toBeNull();
    expect(viewport).not.toBeNull();
    if (box && viewport) {
      // "bottom-right" per UI_SURFACE.md — box sits in the lower-right quadrant.
      expect(box.x + box.width).toBeGreaterThan(viewport.width * 0.5);
      expect(box.y + box.height).toBeGreaterThan(viewport.height * 0.5);
    }

    await toast.getByRole('button', { name: 'Dismiss' }).click();
    await expect(toast).not.toBeVisible();
  });

  test('error toast renders with the error variant', async ({ page, context }) => {
    await signInViaCookie(context);
    await page.goto('/dev-test-toast');
    await page.getByTestId('trigger-error-toast').click();
    await expect(page.getByTestId('toast-error')).toContainText('Simulated error toast');
  });
});
