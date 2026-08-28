import { NextResponse } from 'next/server';
import { runScheduledMatchingBatch } from '@/lib/matchingInvocation';

// Scheduled path (Task 5.1) — no live timer/cron infrastructure invokes this in this
// build (see sessions/S05_SESSION_LOG.md's Decision Log); exposed so an external
// scheduler can call it. Each document's own G5 lock still applies per document, so a
// concurrent manual Reconcile click on one of the documents this batch is processing is
// safely skipped here, not double-processed.
export async function POST() {
  const result = await runScheduledMatchingBatch();
  return NextResponse.json(result);
}
