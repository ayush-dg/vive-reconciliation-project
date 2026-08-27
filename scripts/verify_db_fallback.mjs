// Reproducible check for Task 1.1's specified failure case:
// "missing FABRIC_SQL_ENDPOINT env var falls back to local SQLite without crashing."
// Run: npm run test:db-fallback
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import fs from 'node:fs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const testDbDir = path.join(__dirname, '..', '.data');
const testDbPath = path.join(testDbDir, 'verify_fallback.tmp.db');

delete process.env.FABRIC_SQL_ENDPOINT;
process.env.SQLITE_DB_PATH = path.relative(process.cwd(), testDbPath);

const dbModuleUrl = pathToFileURL(path.join(__dirname, '..', 'src', 'lib', 'db.ts')).href;
const { getDbMode, pingDb, closeDb } = await import(dbModuleUrl);

const mode = getDbMode();
if (mode !== 'sqlite') {
  console.error(`FAIL: expected mode 'sqlite' with FABRIC_SQL_ENDPOINT unset, got '${mode}'`);
  process.exit(1);
}

const result = await pingDb();
if (!result.ok || result.mode !== 'sqlite') {
  console.error(`FAIL: pingDb() did not report a healthy sqlite fallback: ${JSON.stringify(result)}`);
  process.exit(1);
}

await closeDb();
console.log('PASS: FABRIC_SQL_ENDPOINT unset -> sqlite fallback, no crash.', JSON.stringify(result));

// Clean up the temp db file this check creates.
for (const suffix of ['', '-wal', '-shm']) {
  fs.rmSync(testDbPath + suffix, { force: true });
}
