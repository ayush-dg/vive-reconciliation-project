-- Migrated 2026-09-18 to source from the dict-dump bronze
-- (bronze.raw_statement) instead of the per-vendor
-- bronze.bronze_<vendor_id>_raw tables -- see this migration's plan for
-- why: those per-vendor typed tables required a hand-maintained mapping
-- CSV row per raw field per vendor with no visibility into what
-- extraction actually produced, whereas bronze.raw_statement
-- captures every extracted field verbatim and vendor_field_mapping.csv
-- (silver.vendor_field_mapping) does the pivot generically. Same output
-- schema/column set as the prior bronze-driven model -- nothing
-- downstream (src/matching/fabric_matching.py) needed to change.
--
-- Column parity notes vs. the prior bronze-driven version:
--   shop_id, statement_number, statement_date, period_start, period_end,
--   total_amount_due, source_document_id, run_id stay NULL, same as
--   before (never populated either way -- no header-level source for
--   them yet).
--   currency has no equivalent field in the dict dump (the old model
--   read bronze's raw_currency) -- defaulted to 'USD' instead of NULL,
--   matching the old model's own COALESCE(raw_currency, 'USD') fallback,
--   which was actually what most rows resolved to anyway.
{{ config(unique_key='statement_id') }}

{% set target_statement_id = var('statement_id', none) %}

with header_ranked as (

    -- raw_statement is append-only and can legitimately accumulate more
    -- than one row per statement_id (re-runs, manual rebuilds) --
    -- row_number() picks the latest by ingestion_timestamp, same "latest
    -- wins" semantics used throughout this pipeline (see
    -- src/lakehouse/bronze_raw.py:read_raw_statement()).
    select
        statement_id,
        vendor_id,
        vendor_display_name,
        ingestion_timestamp,
        row_number() over (partition by statement_id order by ingestion_timestamp desc) as rn
    from {{ source('bronze', 'raw_statement') }}
    {% if target_statement_id is not none %}
    where statement_id = '{{ target_statement_id }}'
    {% endif %}

),

header as (

    select statement_id, vendor_id, vendor_display_name
    from header_ranked
    where rn = 1

),

shop_names as (

    select statement_id, min(shop_name) as shop_name_raw
    from {{ source('bronze', 'unnested_statement_lines') }}
    group by statement_id

)

select
    h.statement_id,
    h.vendor_id,
    h.vendor_display_name                as vendor_name_raw,
    cast(null as varchar(50))            as shop_id,
    s.shop_name_raw,
    cast(null as varchar(50))            as statement_number,
    cast(null as date)                   as statement_date,
    cast(null as date)                   as period_start,
    cast(null as date)                   as period_end,
    cast(null as decimal(18, 2))         as total_amount_due,
    'USD'                                 as currency,
    cast(null as varchar(100))           as source_document_id,
    'bronze.raw_statement'      as source_bronze_table,
    cast(null as decimal(5, 2))          as extraction_confidence,
    cast(getdate() as datetime2(6))      as ingested_at,
    'pipeline'                            as ingested_by,
    cast(1 as bit)                       as is_current,
    cast(null as varchar(50))            as run_id,
    'PENDING'                             as validation_status,
    cast(0 as bit)                       as arithmetic_gate_passed
from header h
left join shop_names s on s.statement_id = h.statement_id
