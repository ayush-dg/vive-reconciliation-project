import { Connection, Request, TYPES, type ConnectionConfiguration } from 'tedious';
import { ClientSecretCredential } from '@azure/identity';

/**
 * Live, read-only access to the Fabric Lakehouse's `bronze.netsuite_vendorbill` table —
 * the externally-owned NetSuite reference data (ARCHITECTURE.md D-M). This is additive to
 * deterministicMatching.ts's existing local-SQLite-fixture path (see
 * isFabricLakehouseConfigured()), not a replacement for this app's own operational data
 * store: `recon`/`extracted`/`silver` remain in local SQLite (getDbMode() unaffected).
 *
 * Deliberately a SEPARATE endpoint variable (FABRIC_LAKEHOUSE_SQL_ENDPOINT) from
 * db.ts's FABRIC_SQL_ENDPOINT — the latter is getDbMode()'s all-or-nothing app-state
 * switch, which every src/lib module still hard-throws against (Fabric app-state was never
 * implemented). Reusing that same variable here would mean any local run wanting this live
 * reference lookup would also flip the entire app into a mode that immediately breaks
 * everything else. Both variables hold the same real hostname (confirmed by direct
 * connectivity test — same Fabric SQL endpoint serves both the Lakehouse and Warehouse
 * databases, distinguished only by `database` in the connection config); kept as two names
 * so the two concerns can be toggled independently.
 *
 * Uses tedious directly, not the `mssql` package's ConnectionPool — confirmed by direct
 * test that Fabric's SQL endpoint issues a mid-handshake reroute to a different backend
 * host (`*.pbidedicated.windows.net`) which `mssql`'s pool does not follow (fails with
 * "socket hang up"), while raw tedious follows it automatically. A new short-lived
 * Connection is opened per call rather than pooled — this lookup runs at most once per
 * statement line during a user-triggered Reconcile action, not at request-per-second
 * volume, so pooling complexity isn't justified; the AAD token is cached across calls
 * since acquiring one is the more expensive part.
 */

const REFERENCE_TABLE = 'bronze.netsuite_vendorbill';

export function isFabricLakehouseConfigured(): boolean {
  return Boolean(
    process.env.FABRIC_CLIENT_ID &&
      process.env.FABRIC_CLIENT_SECRET &&
      process.env.FABRIC_TENANT_ID &&
      process.env.FABRIC_LAKEHOUSE_SQL_ENDPOINT &&
      process.env.FABRIC_LAKEHOUSE_NAME
  );
}

let cachedToken: { token: string; expiresOnTimestamp: number } | null = null;

async function getAccessToken(): Promise<string> {
  // 60s safety margin so a token doesn't expire mid-connection.
  if (cachedToken && cachedToken.expiresOnTimestamp - 60_000 > Date.now()) {
    return cachedToken.token;
  }
  const credential = new ClientSecretCredential(
    process.env.FABRIC_TENANT_ID!,
    process.env.FABRIC_CLIENT_ID!,
    process.env.FABRIC_CLIENT_SECRET!
  );
  const token = await credential.getToken('https://database.windows.net/.default');
  if (!token) {
    throw new Error('fabricLakehouse.ts: failed to acquire an AAD access token for the Fabric SQL endpoint.');
  }
  cachedToken = token;
  return token.token;
}

type SqlParam = { name: string; type: typeof TYPES[keyof typeof TYPES]; value: unknown };

/** Opens a short-lived connection, runs one read-only query, closes the connection. */
function runQuery(sqlText: string, params: SqlParam[], accessToken: string): Promise<Record<string, unknown>[]> {
  return new Promise((resolve, reject) => {
    const config: ConnectionConfiguration = {
      server: process.env.FABRIC_LAKEHOUSE_SQL_ENDPOINT!,
      authentication: { type: 'azure-active-directory-access-token', options: { token: accessToken } },
      options: {
        port: 1433,
        database: process.env.FABRIC_LAKEHOUSE_NAME!,
        encrypt: true,
        trustServerCertificate: false,
        rowCollectionOnRequestCompletion: true,
      },
    };

    const connection = new Connection(config);
    connection.on('error', (err) => reject(err));
    connection.on('connect', (err) => {
      if (err) {
        reject(err);
        return;
      }
      const request = new Request(sqlText, (err, _rowCount, rows) => {
        connection.close();
        if (err) {
          reject(err);
          return;
        }
        resolve(
          (rows as { metadata: { colName: string }; value: unknown }[][]).map((row) =>
            Object.fromEntries(row.map((col) => [col.metadata.colName, col.value]))
          )
        );
      });
      for (const p of params) request.addParameter(p.name, p.type, p.value);
      connection.execSql(request);
    });
    connection.connect();
  });
}

export type NetsuiteVendorBillRow = {
  tranid: string;
  total: number;
  _run_id: string;
  _extracted_at: string;
  _source_system: string;
  // Every column the live row actually carries, JSON-safe (Dates coerced to ISO strings) —
  // captured so an exception's evidence can show the full NetSuite record (Exceptions
  // screen redesign, 2026-09-01) without a live re-query at view time. Not attempted
  // against bronze.netsuite_vendor (the JOIN'd table) — only the bill/credit row's own
  // columns are captured, matching what a "NetSuite record" means to the reviewer.
  rawFields: Record<string, unknown>;
};

/**
 * Real, confirmed bug (2026-08-31): NetSuite's `tranid` is not unique across vendors — a
 * bill number can and does repeat between completely unrelated companies (confirmed
 * directly: a real Bald Hill Dodge statement had 6 of 11 lines silently matched against
 * the WRONG vendor's bill — Taylor's, Faulkner Subaru, etc. — because the old query only
 * filtered by tranid). Fixed two ways, layered:
 * 1. Vendor-scoped first: join to bronze.netsuite_vendor and restrict to entities whose
 *    name starts with the statement's own vendor's first name-token (e.g. "fred" for
 *    "Fred Beans" — confirmed 2026-08-31 that Fred Beans' own 4+ shop entities never
 *    collide with each other on tranid, so this alone fully resolves a multi-entity vendor
 *    family without needing to know exactly which specific shop issued the statement).
 * 2. Amount-closest as the tie-break within whatever candidate set results, and as a full
 *    fallback (unscoped) when no vendor name is available or the scoped search finds
 *    nothing — never worse than the old behavior, and still correct even if vendor
 *    name-matching itself fails for some reason.
 */
async function findBillOrCreditRow(
  table: string,
  tranId: string,
  vendorNamePrefix: string | null,
  amount: number
): Promise<NetsuiteVendorBillRow | null> {
  const accessToken = await getAccessToken();

  if (vendorNamePrefix) {
    const scopedRows = await runQuery(
      `SELECT TOP 1 b.*
       FROM ${table} b
       JOIN bronze.netsuite_vendor v ON v.id = b.entity
       WHERE UPPER(LTRIM(RTRIM(b.tranid))) = @tranId
         AND LOWER(v.entityid) LIKE @vendorPrefix
       ORDER BY ABS(b.total - @amount) ASC, b._extracted_at DESC`,
      [
        { name: 'tranId', type: TYPES.NVarChar, value: tranId },
        { name: 'vendorPrefix', type: TYPES.NVarChar, value: `${vendorNamePrefix.toLowerCase()}%` },
        { name: 'amount', type: TYPES.Float, value: amount },
      ],
      accessToken
    );
    const scopedRow = scopedRows[0] as Record<string, unknown> | undefined;
    // Once a vendor is known, trust the scoped result either way — found, or genuinely
    // not posted for THIS vendor. Falling through to an unscoped search here would
    // reintroduce the exact cross-vendor collision bug this whole fix exists to close:
    // confirmed live (2026-08-31) — Bald Hill's own bill #178375 genuinely doesn't exist
    // in NetSuite, and an unscoped fallback matched Toyota & Volvo of Keene's unrelated
    // #178375 instead, silently reporting a wrong-vendor "mismatch" rather than a correct
    // NOT_POSTED. A false NOT_POSTED (human reviews it) is the safe failure direction here;
    // a false cross-vendor match (looks resolved, is actually wrong) is not.
    return scopedRow ? normalizeRow(scopedRow) : null;
  }

  // No vendor known at all (document's vendor was never resolved) — unscoped,
  // amount-closest is the best available signal.
  const rows = await runQuery(
    `SELECT TOP 1 *
     FROM ${table}
     WHERE UPPER(LTRIM(RTRIM(tranid))) = @tranId
     ORDER BY ABS(total - @amount) ASC, _extracted_at DESC`,
    [
      { name: 'tranId', type: TYPES.NVarChar, value: tranId },
      { name: 'amount', type: TYPES.Float, value: amount },
    ],
    accessToken
  );
  const row = rows[0] as Record<string, unknown> | undefined;
  if (!row) return null;
  return normalizeRow(row);
}

/** SELECT only — no write path exists in this module by design. */
export async function getReferenceRowByTranId(
  tranId: string,
  vendorNamePrefix: string | null,
  amount: number
): Promise<NetsuiteVendorBillRow | null> {
  return findBillOrCreditRow(REFERENCE_TABLE, tranId, vendorNamePrefix, amount);
}

const CREDIT_TABLE = 'bronze.netsuite_vendorcredit';

/** Same shape/columns as bronze.netsuite_vendorbill (confirmed 2026-08-31) — a statement
 * line that comes back NOT_POSTED against vendorbill may still be a genuine credit memo
 * recorded here instead (a real, live example: 4 credit-memo lines on a KSI statement
 * existed only in vendorcredit, not vendorbill). SELECT only, same as above. */
export async function getCreditRowByTranId(
  tranId: string,
  vendorNamePrefix: string | null,
  amount: number
): Promise<NetsuiteVendorBillRow | null> {
  return findBillOrCreditRow(CREDIT_TABLE, tranId, vendorNamePrefix, amount);
}

/** tedious returns this warehouse's `total` column as a string and `_extracted_at` as a
 * JS Date object (confirmed by direct query — neither is a documented type guarantee,
 * and both differ from the local SQLite fixture's plain TEXT/REAL columns). Normalized
 * here, at the source, so every caller gets refAmount as an actual number and
 * extractedAt as the same ISO string shape the SQLite fixture path already returns,
 * rather than depending on JS's silent string/number coercion or Date's default
 * (non-ISO) toString(). */
function normalizeRow(row: Record<string, unknown>): NetsuiteVendorBillRow {
  const rawFields: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(row)) {
    rawFields[key] = value instanceof Date ? value.toISOString() : value;
  }
  return {
    tranid: String(row.tranid),
    total: Number(row.total),
    _run_id: String(row._run_id),
    _extracted_at: row._extracted_at instanceof Date ? row._extracted_at.toISOString() : String(row._extracted_at),
    _source_system: String(row._source_system),
    rawFields,
  };
}

/** The reference table's own most-recently-extracted row overall — same "what state of
 * NetSuite data was checked" purpose as deterministicMatching.ts's local-fixture equivalent
 * (S8, amended), for the NOT_POSTED case where no row matched at all. */
export async function getLatestReferenceWatermark(): Promise<Pick<NetsuiteVendorBillRow, '_run_id' | '_extracted_at' | '_source_system'> | null> {
  const accessToken = await getAccessToken();
  const rows = await runQuery(
    `SELECT TOP 1 _run_id, _extracted_at, _source_system FROM ${REFERENCE_TABLE} ORDER BY _extracted_at DESC`,
    [],
    accessToken
  );
  const row = rows[0] as Record<string, unknown> | undefined;
  if (!row) return null;
  return {
    _run_id: String(row._run_id),
    _extracted_at: row._extracted_at instanceof Date ? row._extracted_at.toISOString() : String(row._extracted_at),
    _source_system: String(row._source_system),
  };
}
