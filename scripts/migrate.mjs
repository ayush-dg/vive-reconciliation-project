// CLI entry: applies pending local SQLite migrations. Run: npm run migrate
// (Fabric migrations are applied via sqlcmd directly, per Task 1.2's Verification
// Command — this script does not touch Fabric.)
import { runMigrations } from '../src/lib/migrate.ts';
import { closeDb } from '../src/lib/db.ts';

const { applied, skipped } = runMigrations();
console.log(`Applied: ${applied.length ? applied.join(', ') : '(none)'}`);
console.log(`Already applied (skipped): ${skipped.length ? skipped.join(', ') : '(none)'}`);
await closeDb();
