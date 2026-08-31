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
};

/** SELECT only — no write path exists in this module by design. */
export async function getReferenceRowByTranId(tranId: string): Promise<NetsuiteVendorBillRow | null> {
  const accessToken = await getAccessToken();
  const rows = await runQuery(
    `SELECT TOP 1 tranid, total, _run_id, _extracted_at, _source_system
     FROM ${REFERENCE_TABLE}
     WHERE UPPER(LTRIM(RTRIM(tranid))) = @tranId
     ORDER BY _extracted_at DESC`,
    [{ name: 'tranId', type: TYPES.NVarChar, value: tranId }],
    accessToken
  );
  const row = rows[0] as Record<string, unknown> | undefined;
  if (!row) return null;
  return normalizeRow(row);
}

const CREDIT_TABLE = 'bronze.netsuite_vendorcredit';

/** Same shape/columns as bronze.netsuite_vendorbill (confirmed 2026-08-31) — a statement
 * line that comes back NOT_POSTED against vendorbill may still be a genuine credit memo
 * recorded here instead (a real, live example: 4 credit-memo lines on a KSI statement
 * existed only in vendorcredit, not vendorbill). SELECT only, same as above. */
export async function getCreditRowByTranId(tranId: string): Promise<NetsuiteVendorBillRow | null> {
  const accessToken = await getAccessToken();
  const rows = await runQuery(
    `SELECT TOP 1 tranid, total, _run_id, _extracted_at, _source_system
     FROM ${CREDIT_TABLE}
     WHERE UPPER(LTRIM(RTRIM(tranid))) = @tranId
     ORDER BY _extracted_at DESC`,
    [{ name: 'tranId', type: TYPES.NVarChar, value: tranId }],
    accessToken
  );
  const row = rows[0] as Record<string, unknown> | undefined;
  if (!row) return null;
  return normalizeRow(row);
}

/** tedious returns this warehouse's `total` column as a string and `_extracted_at` as a
 * JS Date object (confirmed by direct query — neither is a documented type guarantee,
 * and both differ from the local SQLite fixture's plain TEXT/REAL columns). Normalized
 * here, at the source, so every caller gets refAmount as an actual number and
 * extractedAt as the same ISO string shape the SQLite fixture path already returns,
 * rather than depending on JS's silent string/number coercion or Date's default
 * (non-ISO) toString(). */
function normalizeRow(row: Record<string, unknown>): NetsuiteVendorBillRow {
  return {
    tranid: String(row.tranid),
    total: Number(row.total),
    _run_id: String(row._run_id),
    _extracted_at: row._extracted_at instanceof Date ? row._extracted_at.toISOString() : String(row._extracted_at),
    _source_system: String(row._source_system),
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
