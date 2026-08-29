import { NextResponse } from 'next/server';
import { getHomeSummaryStats } from '@/lib/homeSummary';

// GET: Home screen's summary stats refresh endpoint (Task 6.1).
export async function GET() {
  return NextResponse.json(getHomeSummaryStats());
}
