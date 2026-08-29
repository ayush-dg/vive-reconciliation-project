import { NextResponse } from 'next/server';
import { listExceptions } from '@/lib/exceptionsList';

// GET: Exceptions list screen's data + refresh endpoint (Task 6.2). Query params:
// ?search=<vendor or invoice ref substring>&page=<1-based>.
export async function GET(request: Request) {
  const url = new URL(request.url);
  const search = url.searchParams.get('search') ?? undefined;
  const pageParam = url.searchParams.get('page');
  const page = pageParam ? Number(pageParam) : 1;
  const validPage = Number.isInteger(page) && page > 0 ? page : 1;

  return NextResponse.json(listExceptions({ search, page: validPage }));
}
