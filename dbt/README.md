# dbt project: Bronze -> Silver normalization

Replaces `normalize_to_silver()` (`notebooks/01_document_intake.py:590-712`) for
vendor-statement data. Reads per-vendor raw tables in the Fabric Lakehouse
(Bronze), writes standardized `silver.statement` (header) / `silver.statement_line`
(line items) in the Fabric Warehouse. ERP/NetSuite data is unaffected --
stays on its current `bronze_internal_erp_raw` -> `silver_reconciliation_standard`
path. Everything here is **additive** to the existing SQLite/Azure SQL
Bronze/Silver pipeline, never a replacement -- both write paths run from
the same call site in `notebooks/01_document_intake.py`.

## Status (2026-08-26): wired into the real pipeline, verified end-to-end

Ran the actual pipeline (`scripts/run_full_pipeline.py`) against a real PDF
(`sample_data/KSI HEW 0726.pdf`) -- real Claude Sonnet extraction (46
invoices), both the existing SQLite Bronze/Silver write AND the new Fabric
write/dbt build completed successfully, landing all 46 rows correctly in
`silver.statement_line` in the Fabric Warehouse.

**Key design point discovered along the way:** extraction (both the AI
engine's `VISION_PROMPT` and the deterministic python-library adapter's
`_FIELD_MAP`) already normalizes every vendor into one generic shape
(`invoice_number`, `amount`, `outstanding_amount`, `ro_number`, `po_number`,
`description`, `shop`, ...) before it reaches Bronze -- confirmed by the
real KSI run above (`['Posting Date', 'Document No.', 'PO No.',
'Description', 'Sell-to Customer#', 'Due Date', 'Remaining Amount']` all
mapped into that generic shape). So Bronze does **not** preserve each
vendor's original raw column layout (an earlier version of this doc/models
assumed it did, built from hand-transcribed test data that bypassed
extraction) -- "different table per vendor" is a partitioning choice, not a
schema difference, since every vendor's Bronze table ends up with the same
columns. That means the Silver mapping is also genuinely vendor-generic now
-- see `models/silver/statement_line.sql`'s single templated model instead
of one file per vendor.

### What's wired

- **`src/lakehouse/fabric_bronze.py`** -- `write_bronze_fabric()`, called
  from `notebooks/01_document_intake.py` right after the existing
  `write_to_bronze()` call, same inputs. Generic for any `vendor_id` --
  writes `bronze.bronze_<vendor_id>_raw`, forcing concrete dtypes on
  numeric/date/string columns (works around the all-null-column ambiguous-type
  issue below) and calling the Fabric metadata-refresh REST API after every
  write. Best-effort: never raises, silently no-ops if `FABRIC_CLIENT_ID`/etc
  aren't set in `.env` (the common case for local dev/tests).
- **`src/lakehouse/fabric_dbt_runner.py`** -- `run_dbt_silver_build(statement_id)`,
  called from `scripts/run_full_pipeline.py` right after Phase 1 (Document
  Intake) completes. Runs `dbt run --vars '{"statement_id": "..."}'` as a
  subprocess, scoped to just that statement. Best-effort, same as above --
  a skip/failure here never stops the pipeline (Phase 2 Matching still runs
  against the existing Silver/Gold tables regardless).
- **`config/vendor_aliases.json`** -- added canonical `vendor_id` entries
  for `DCD_AUTOMOTIVE_HOLDINGS`, `BALD_HILL_DODGE_CHRYSLER_JEEP_KIA`,
  `BERLIN_CITY_AUTO_GROUP` (KSI's `KSI_TRADING_CORP` already existed). This
  affects the *existing* pipeline's vendor identification too, not just the
  new Fabric path -- without it, `vendor_id` for those 3 vendors would be
  an unpredictable transform of whatever `vendor_name` Claude happens to
  extract.
- **`dbt_project.yml`'s `known_vendor_ids` var** -- the only place a new
  vendor needs registering for the Silver build (in addition to
  `models/bronze/sources.yml`'s source table list). No new SQL file per
  vendor.

### Known gaps

1. **dbt isn't available wherever the app actually runs in production.**
   `dbt-core`/`dbt-fabric` are deliberately isolated from `requirements.txt`
   (own dependency set, avoids version collisions -- see
   `requirements-dbt.txt`'s docstring), installed only into this repo's
   local `venv/`. The `Dockerfile` installs only `requirements.txt` and
   `.dockerignore` excludes `venv/` entirely -- so in the deployed
   container, `run_dbt_silver_build()` will find no `dbt` executable and
   silently no-op (`DBT_EXECUTABLE_PATH` env var can point it elsewhere if
   dbt is installed some other way in that environment). Not fixed here --
   deploying dbt into the container (a second embedded venv, most likely,
   to preserve the isolation) is a real infra decision I didn't want to
   make unilaterally by editing the Dockerfile without asking first.
2. **Cache-hit path doesn't trigger a new Fabric Silver build.** On a
   cache hit, `run_intake()` re-normalizes Silver under a *new*
   `statement_id` pointing at the *old* Bronze rows (see
   `normalize_to_silver(cached_statement_id, statement_id, ...)`) -- the
   new dbt models don't yet support that bronze-id-vs-silver-id split, so a
   cache-hit re-run's new `statement_id` won't get a Fabric Silver build.
   `write_bronze_fabric()` itself is also simply not called on a cache hit
   (mirrors the existing `write_to_bronze()` behavior -- Bronze isn't
   rewritten either).
3. `silver.statement` header fields not populated from the generic Bronze
   schema (no header-level metadata in a per-invoice-row extraction
   output): `statement_number`, `statement_date`, `period_start`,
   `period_end`, `total_amount_due`. Would need extraction to also emit
   statement-level metadata, not just per-invoice rows -- out of scope
   here.
4. No local-dev fallback for `get_fabric_connection()`'s `AzureCliCredential`
   path (`extraction_cache`/`document_intake_log`/`validation_document_review_queue`
   -- the *existing*, unrelated Recon-table cut-over) when `az` CLI isn't
   installed -- pre-existing gap, not introduced here, just newly hit while
   testing this. Also: a fresh local SQLite db needs
   `apply_pending_migrations()` run once before `run_full_pipeline.py`
   works at all locally -- not normally an issue since the web app runs
   migrations on startup, but standalone script runs (like the test that
   verified this wiring) hit it on a brand-new checkout.

Fixed along the way (all documented inline in the affected files):
- **`+schema: silver` in `dbt_project.yml` doubled with the profile's
  default schema** into `silver_silver`. Fix: don't set `+schema` when it
  already matches the profile default.
- **Fabric Warehouse doesn't support the `DATETIME` type**, only
  `DATETIME2(n)` -- `GETDATE()` needs `CAST(... AS DATETIME2(6))`, and the
  precision must be explicit (bare `DATETIME2` fails on `CREATE TABLE`).
- **A 100%-null column gets an ambiguous type** that the SQL analytics
  endpoint won't expose as a queryable column, even though it's present in
  the Delta schema. Fix: force a concrete dtype before writing, even for
  all-null columns (`fabric_bronze.py` does this for every known
  numeric/date/string column unconditionally, not just when it happens to
  be all-null in one particular statement).
- **SQL analytics endpoint metadata sync lag is real** (this workspace is
  on Fabric's legacy sync, not the new "within seconds" preview one --
  Warehouse settings -> New metadata sync). `EXEC sys.sp_dw_refresh_ext_table`
  isn't enabled on this workspace ("Refresh is not supported for this type
  of table"); the REST API
  `POST /v1/workspaces/{ws}/sqlEndpoints/{sqlEndpointId}/refreshMetadata`
  works and is what `fabric_bronze.py` calls after every write. **This lag
  caused a real production-shaped bug, not just a slow `dbt debug`**: a
  real UI-uploaded Berlin City statement landed correctly in Bronze (89
  rows) and got a `silver.statement` header row, but zero
  `silver.statement_line` rows -- `write_bronze_fabric()` fired the
  metadata refresh and returned immediately, so `run_dbt_silver_build()`
  (triggered right after, from `run_full_pipeline.py`) queried Bronze
  before the new rows had actually synced. Not an error -- dbt's MERGE
  just silently had zero source rows for that statement_id. Fixed:
  `write_bronze_fabric()` now polls the SQL endpoint
  (`_wait_for_row_visibility()`) until the expected row count is actually
  visible before returning, blocking the caller rather than racing it.
  Verified against a fresh real extraction (69 invoices) -- all 69 landed
  in `silver.statement_line` on the first automatic pass afterward.
- **dbt-fabric 1.11.1's `ActiveDirectoryServicePrincipal` auth is broken**
  against the installed `mssql-python` driver (`Authority Id` connection-string
  keyword rejected -- [microsoft/mssql-python#539](https://github.com/microsoft/mssql-python/issues/539)).
  Fixed by using `authentication: token_credential` +
  `credential_class: azure.identity.ClientSecretCredential` instead (see
  `profiles.yml.example`), which pre-fetches the AAD token itself and
  sidesteps the broken driver-native path entirely.
- **A schema-enabled Lakehouse's custom schemas created via T-SQL `CREATE
  SCHEMA` don't register with the Lakehouse's own table-discovery** --
  tables written into them aren't visible over T-SQL even though the schema
  "exists." The pre-existing `bronze` schema (created natively, already in
  use by an unrelated CCC ONE/NetSuite ingestion pipeline) works fine;
  don't try to create new schemas via SQL DDL for this project.

## Layout

```
dbt/
  requirements-dbt.txt      # dbt-core + dbt-fabric, isolated from requirements.txt
  profiles.yml.example      # template for dbt/profiles.yml -- not real creds
  vive_recon/
    dbt_project.yml         # known_vendor_ids var -- add a vendor here + its Bronze table, nothing else
    models/
      bronze/sources.yml    # one source table per vendor (bronze_<vendor_id>_raw)
      silver/
        statement.sql        # loops known_vendor_ids -- one header row per statement_id (GROUP BY + MIN(), not DISTINCT -- shop_name_raw can vary per row for a consolidated statement)
        statement_line.sql   # loops known_vendor_ids -- generic mapping, identical logic for every vendor
    macros/
    seeds/
    tests/

src/lakehouse/
  fabric_bronze.py           # write_bronze_fabric() -- generic Bronze write, called from notebooks/01_document_intake.py
  fabric_dbt_runner.py        # run_dbt_silver_build() -- triggers dbt, called from scripts/run_full_pipeline.py
```

## Setup

```
venv\Scripts\python.exe -m pip install -r dbt\requirements-dbt.txt
```

`dbt/profiles.yml` (gitignored, no literal secrets -- all `env_var()`) is
auto-created from `profiles.yml.example` on first use by
`fabric_dbt_runner.py`; to run dbt manually instead:

```
copy dbt\profiles.yml.example dbt\profiles.yml
```

Run dbt with `DBT_PROFILES_DIR` pointing at `dbt/` (one level up from
`dbt/vive_recon/`) and the `FABRIC_*` vars from `.env` in the environment
-- dbt doesn't load `.env` itself. From the repo root (git-bash):

```
set -a; source <(grep -E '^FABRIC_' .env); set +a
cd dbt/vive_recon
DBT_PROFILES_DIR=.. ../../venv/Scripts/dbt.exe debug
```
