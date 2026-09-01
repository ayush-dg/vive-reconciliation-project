import { defineConfig, devices } from '@playwright/test';
import { TEST_SESSION_SECRET } from './ui_tests/global-setup';

export default defineConfig({
  testDir: './ui_tests',
  globalSetup: './ui_tests/global-setup.ts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      SESSION_SECRET: TEST_SESSION_SECRET,
      // Every module in src/lib (Sessions 1-5) still throws on Fabric mode —
      // "Fabric required starting Session N" — none of them has a real
      // implementation yet. .env now carries a real FABRIC_SQL_ENDPOINT
      // value (added outside this dev loop, presumably for a separate live-
      // Fabric effort); left as-is, Next's automatic .env loading would
      // route every DB call in this suite to Fabric mode and break the
      // entire app locally. Overridden to empty here only for the
      // Playwright-launched dev server, forcing the local SQLite fallback
      // every session's tests have always assumed — .env itself is untouched.
      FABRIC_SQL_ENDPOINT: '',
      // fabricLakehouse.ts's live-reference-lookup gate (isFabricLakehouseConfigured())
      // is a separate concern from the app-state switch above, but .env.local (local-dev
      // only, not committed) sets this for real so `npm run dev` can compare extracted
      // statements against the live Lakehouse. Blanked here so automated tests keep
      // exercising the local SQLite fixture path deterministically, not a live external
      // dependency.
      FABRIC_LAKEHOUSE_SQL_ENDPOINT: '',
      // aiProvider.ts's live-extraction opt-in (Azure Foundry or direct Anthropic) —
      // .env.local sets this for real so `npm run dev` exercises live Claude. Blanked
      // here so automated tests keep using the deterministic mock, not a live, billed,
      // network-dependent external call.
      EXTRACTION_LIVE_TESTS: '',
    },
  },
});
