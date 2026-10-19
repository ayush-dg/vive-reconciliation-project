# NetSuite write-back

After a statement is reconciled, its result is written back into NetSuite so AP
sees it on the bill itself. **Sandbox only**: the client refuses any account that
is not `<digits>-sb<digits>`. The write-back reads the matcher's saved results
(`silver.recon_matched_invoices`, `silver.recon_exceptions`), finds each invoice
in NetSuite, and updates its status. It never re-matches anything.

## What gets written

| Matcher result | Written to NetSuite |
|---|---|
| Matched | Bill/credit: *Statement Reconciled* on, reconciled date, statement reference; any old exception value cleared |
| Exception on an existing bill (amount mismatch, possible duplicate) | Bill/credit: reconciled off, *Reconciliation Exception* list value, statement reference. A duplicate flags every record with that invoice number |
| Not found in NetSuite | A **Statement Line** record: vendor, statement id, invoice number (stripped form), amount, status, exception type, shop, location, invoice date, *Reconciled* unchecked |
| Anything else (vendor not resolved, extraction incomplete) | Not written; listed in the log with a reason |

Rules that follow: a Statement Line takes its vendor and location from the statement's own matched bills (location is left blank if they disagree); a bill already
reconciled by an *earlier* statement is skipped; re-running a statement skips what is already done; the invoice number used is the matcher's normalised one, never the raw statement text.

## Where it runs

`scripts/run_full_pipeline.py` calls `src/netsuite/pipeline_hook.py` right after
matching succeeds. It is best-effort: it never fails a job. It is **off unless**
`NETSUITE_WRITEBACK_ENABLED=true`.

| File | Role |
|---|---|
| `src/netsuite/client.py` | OAuth1 (TBA) REST + SuiteQL client; sandbox-only guard |
| `src/netsuite/writeback.py` | planning, applying (with read-back), revert, file logs |
| `src/netsuite/log_store.py` | saves every run to the database |
| `src/netsuite/pipeline_hook.py` | the pipeline entry point |
| `src/netsuite/fields.py` | the custom fields the write-back depends on |
| `scripts/netsuite_preflight.py` | checks credentials and that every field exists |
| `scripts/netsuite_writeback.py` | preview (default), `--apply`, `--revert`, `--revert-statement` |
| `web/netsuite_status.py` | the status pill shown in the Exceptions pages |

## Configuration (`.env.example` lists them all)

| Variable | Meaning |
|---|---|
| `SANDBOX_ACCOUNT_ID`, `SANDBOX_CONSUMER_KEY`, `SANDBOX_CONSUMER_SECRET`, `SANDBOX_TOKEN_ID`, `SANDBOX_TOKEN_SECRET` | TBA credentials for the sandbox |
| `NETSUITE_WRITEBACK_ENABLED` | `true` turns the write-back on (default off) |
| `NETSUITE_WRITEBACK_PDF_LINK` | `true` also writes the statement PDF link (default off) |
| `SHAREPOINT_*` | the statement PDF is archived to SharePoint at intake; the link written is that file's SharePoint URL (see `.env.example`) |

## What must exist in NetSuite

Bill and credit body fields `custbody_reconciled`, `custbody_reconciled_date`,
`custbody_statement_reference`, `custbody_statement_link`, `custbody_reconciliation_exception`
(list: Amount differs / Wrong shop / Duplicate / No match found); the custom
record `customrecord_statement_line` with its `custrecord_sl_*` fields (see `src/netsuite/fields.py`).
The API role needs access to the Statement Line record type, and **Allow Non-G/L Changes**
for bills in closed periods. Run `python scripts/netsuite_preflight.py` to check all of it.

## Logging: nothing is silent

Every run is saved **twice**.

* **Database** (`netsuite_writeback_run` + `netsuite_writeback_record`; Azure SQL when deployed, SQLite locally;
  schema in `migrations/021_...sql` and `src/lakehouse/azure_sql_migrations.py`). One row per run
  (when, outcome, counts, source `pipeline`/`cli`) and one per invoice line: outcome and reason, the
  NetSuite record, the fields sent and the values they replaced. Outcomes: `written`, `period locked`,
  `reconciled by another statement`, `failed`, `not written` (with reason), `not attempted` (the run stopped
  early), and for undo runs `reverted`. A run that failed *as a whole* is saved with its error and traceback.
* **Files** in `logs/netsuite_writeback/`: `<statement>_<time>.json` (apply), `..._ERROR.json` (whole-run failure),
  `..._REVERT.json` (undo). These are inside the container when deployed and do not survive a restart; the database copy does.

Saving to the database is best-effort and never fails a job.

**In the app:** a small status next to the exception count on a statement's review page, and a badge on each
statement card: green with a tick when written, amber when partly blocked, red on a failure, grey for
*reverted* or *nothing to write*; none when the statement has no saved run. Hover for the statement-wide breakdown.

## Operating it

```
python scripts/netsuite_preflight.py                                  # credentials + fields
python scripts/netsuite_writeback.py --statement-id STMT-XXXX         # preview, writes nothing
python scripts/netsuite_writeback.py --statement-id STMT-XXXX --apply # write (re-runs skip what is done)
python scripts/netsuite_writeback.py --revert-statement STMT-XXXX     # preview an undo
python scripts/netsuite_writeback.py --revert-statement STMT-XXXX --apply
```
`--revert` takes a JSON apply log instead of a statement id. An undo clears the reconciled box, date, reference,
exception and link on every record stamped with that statement id and deletes its Statement Lines
(deleting needs *Allow Delete* on the record type). A statement is re-written only after an undo,
because bills it already stamped are skipped.

## Known limits

* If matching itself fails (or is skipped), no write-back is attempted and no run is recorded; the job's output line says why.
  A run is keyed by statement id (its `job_id` column is empty); join to `jobs.statement_id` to find the job.
* Sandbox only. Production needs its own credentials, the same fields/record/permissions, and a deliberate change to the guard in `client.py`.
* The sandbox lacks bills created in production after its last refresh, so matched lines can be skipped as "not in sandbox".
* Invoices whose matcher-saved number is not NetSuite's exact tranid (some vendors use alternate spellings) are skipped as not found in the sandbox.
* The stored link is the PDF's SharePoint URL, shown as the whole address in a Hyperlink field; searches and portlets cannot show
  just the file name (their formula columns show the HTML as text). A bill already reconciled by this statement but lacking the link
  gets a link-only write; those are counted separately and a failed one is "not written", not a failure of the run.
* Two statements covering the same bills processed at the same moment can collide ("Record has been changed"); the loser re-checks the bill and
  leaves it to the winner. The root cause (the same PDF uploaded twice) is not prevented.
