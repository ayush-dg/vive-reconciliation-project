-- One header row per statement_id, derived via SELECT DISTINCT over the
-- header fields denormalized onto every Bronze row (vendor_id/vendor_name/
-- statement_period/source_file repeated per row -- see
-- src/lakehouse/fabric_bronze.py). Loops over var('known_vendor_ids') --
-- see statement_line.sql for why this is genuinely vendor-generic now.
--
-- Not populated (not in the generic Bronze schema / not derivable):
--   shop_id (needs a normalized shop lookup, not built yet)
--   statement_number, period_start, total_amount_due, due_date (no header-
--   level fields for these in the generic per-row Bronze schema -- would
--   need extraction to also emit statement-level metadata, not just
--   per-invoice rows; out of scope here)
--
-- shop_name_raw genuinely varies per row for a consolidated statement
-- (e.g. Nucar's multiple DBA sub-entities) -- GROUP BY + MIN() guarantees
-- exactly one header row per statement_id regardless (an arbitrary
-- representative value in that case, not a real "the" shop; per-line shop
-- detail lives in statement_line.vendor_group_label instead).
{{ config(unique_key='statement_id') }}

{% set target_statement_id = var('statement_id', none) %}

with unioned as (

    {% for vendor_id in var('known_vendor_ids') %}
    select
        statement_id,
        vendor_id,
        min(vendor_name)              as vendor_name_raw,
        cast(null as varchar(50))     as shop_id,
        min(raw_shop_name)            as shop_name_raw,
        cast(null as varchar(50))     as statement_number,
        cast(null as date)            as statement_date,
        cast(null as date)            as period_start,
        cast(null as date)            as period_end,
        cast(null as decimal(18, 2))  as total_amount_due,
        min(coalesce(raw_currency, 'USD')) as currency,
        cast(null as varchar(100))    as source_document_id,
        '{{ source("bronze", "bronze_" ~ vendor_id ~ "_raw") }}' as source_bronze_table,
        cast(null as decimal(5, 2))   as extraction_confidence,
        cast(getdate() as datetime2(6)) as ingested_at,
        'pipeline'                     as ingested_by,
        cast(1 as bit)                as is_current,
        cast(null as varchar(50))     as run_id,
        'PENDING'                     as validation_status,
        cast(0 as bit)                as arithmetic_gate_passed
    from {{ source('bronze', 'bronze_' ~ vendor_id ~ '_raw') }}
    group by statement_id, vendor_id
    {% if not loop.last %} union all {% endif %}
    {% endfor %}

)

select * from unioned
{% if target_statement_id is not none %}
where statement_id = '{{ target_statement_id }}'
{% endif %}
