// Pure, client-safe display helper — deliberately its own module with zero imports.
// exceptionsList.ts (which owns vendor_slug's actual data queries) pulls in db.ts, which
// pulls in better-sqlite3/mssql/tedious — fine for a server component/route, but any
// 'use client' component importing a value from that module bundles those Node-only
// packages into the browser bundle and fails to build ("Module not found: Can't resolve
// 'tls'"). Client components that just need a display label import this instead.

/** vendor_slug has no separate stored display name (extracted_vendor_registry only ever
 * carries the slug) — humanized here for display only ("fred_beans_parts_inc" -> "Fred
 * Beans Parts Inc"). */
export function humanizeVendorSlug(vendorSlug: string): string {
  return vendorSlug
    .split('_')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}
