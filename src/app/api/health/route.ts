import { NextResponse } from 'next/server';
import { pingDb } from '@/lib/db';

// Minimal health endpoint — makes Task 1.1's env-var-driven DB connection
// (FABRIC_SQL_ENDPOINT set -> Fabric; unset -> local SQLite fallback) a real,
// reachable request path instead of an unused library.
export async function GET() {
  try {
    const result = await pingDb();
    return NextResponse.json(result);
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: error instanceof Error ? error.message : String(error) },
      { status: 503 }
    );
  }
}
