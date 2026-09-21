-- Migrated 2026-09-18 to source from the dict-dump bronze
-- (bronze.raw_statement + unnested_statement_lines/_fields)
-- instead of the per-vendor bronze.bronze_<vendor_id>_raw tables. This is
-- the exact same pivot/normalization logic validated live against real
-- NetSuite data for all 13 vendors during the silver_silver test phase
-- (see git history for models/silver_silver/silver_silver_statement_line.sql,
-- now removed -- this file replaces it in place) -- vendor_field_mapping,
-- vendor_normalization_rule (incl. the mapping_priority coalesce and
-- prefix_pattern columns) and their macros are unchanged.
--
-- Column parity vs. the prior bronze-driven version: same column set,
-- same names/types (charge_amount/payment_amount/amount_remaining/
-- extraction_confidence stay float, not decimal, matching the existing
-- production column types exactly) -- nothing downstream
-- (src/matching/fabric_matching.py) needed to change. `invoice_number`
-- holds the STRIPPED/normalized value (apply_vendor_normalization()),
-- not the raw extracted one -- this is what actually ties out to
-- NetSuite tranids, and is a straight drop-in for what the old model's
-- `invoice_number` column already was (the value matching read).
-- vendor_id / silver_extra_attributes / the raw (pre-normalization)
-- invoice number are deliberately NOT added as new columns here -- the
-- old schema didn't have them either, and this migration is a source
-- swap, not a schema redesign. transaction_code IS added (2026-09-18,
-- right after the initial migration) -- src/matching/vendor_line_selection.py's
-- select_lines() needs it to dedup Fred Beans/Downeast Toyota's
-- reprint/fallback-code rows, and there is no other column it could be
-- read from.
{{ config(unique_key='statement_line_id') }}

{% set target_statement_id = var('statement_id', none) %}

with header_ranked as (

    select
        statement_id, vendor_id,
        row_number() over (partition by statement_id order by ingestion_timestamp desc) as rn
    from {{ source('bronze', 'raw_statement') }}
    {% if target_statement_id is not none %}
    where statement_id = '{{ target_statement_id }}'
    {% endif %}

),

header as (

    select statement_id, vendor_id
    from header_ranked
    where rn = 1

),

mapped_fields as (

    select
        f.statement_id,
        f.line_number,
        h.vendor_id,
        f.raw_field_name,
        f.raw_field_value,
        m.canonical_field_name,
        coalesce(m.mapping_priority, 1) as mapping_priority
    from {{ source('bronze', 'unnested_statement_fields') }} f
    inner join header h on h.statement_id = f.statement_id
    left join {{ ref('vendor_field_mapping') }} m
        on m.vendor_id = h.vendor_id
        and m.raw_field_name = f.raw_field_name

),

ranked_fields as (

    -- A vendor can map more than one raw field to the same canonical
    -- field (e.g. Keystone: charge amount normally lives in
    -- period_activity, but on a zero-activity carryover line the real
    -- amount is in balance_forward instead) -- field_rank picks the
    -- lowest-priority NON-BLANK candidate per line, i.e. a real
    -- coalesce(), not the plain max(raw_field_value) a second mapped row
    -- would otherwise silently become.
    select
        *,
        row_number() over (
            partition by statement_id, line_number, canonical_field_name
            order by
                case when raw_field_value is null or raw_field_value = '' then 1 else 0 end,
                mapping_priority
        ) as field_rank
    from mapped_fields
    where canonical_field_name is not null and canonical_field_name <> ''

),

pivoted as (

    select
        statement_id,
        line_number,
        vendor_id,
        max(case when canonical_field_name = 'original_invoice_number' and field_rank = 1 then raw_field_value end) as original_invoice_number,
        max(case when canonical_field_name = 'invoice_number_ref'      and field_rank = 1 then raw_field_value end) as invoice_number_ref,
        max(case when canonical_field_name = 'work_order_number'       and field_rank = 1 then raw_field_value end) as work_order_number,
        max(case when canonical_field_name = 'ro_number'                and field_rank = 1 then raw_field_value end) as ro_number,
        max(case when canonical_field_name = 'po_number'                and field_rank = 1 then raw_field_value end) as po_number,
        max(case when canonical_field_name = 'transaction_code'         and field_rank = 1 then raw_field_value end) as transaction_code,
        max(case when canonical_field_name = 'line_date'                and field_rank = 1 then raw_field_value end) as line_date_raw,
        max(case when canonical_field_name = 'due_date'                 and field_rank = 1 then raw_field_value end) as due_date_raw,
        max(case when canonical_field_name = 'charge_amount'            and field_rank = 1 then raw_field_value end) as charge_amount_raw,
        max(case when canonical_field_name = 'payment_amount'           and field_rank = 1 then raw_field_value end) as payment_amount_raw,
        max(case when canonical_field_name = 'amount_remaining'         and field_rank = 1 then raw_field_value end) as amount_remaining_raw,
        max(case when canonical_field_name = 'description_raw'          and field_rank = 1 then raw_field_value end) as description_raw,
        max(case when canonical_field_name = 'age_in_days'              and field_rank = 1 then raw_field_value end) as age_in_days_raw
    from ranked_fields
    group by statement_id, line_number, vendor_id

),

with_line_type as (

    -- Best-effort CHARGE/CREDIT/PAYMENT classification -- sign-based,
    -- same known limitation the prior bronze-driven model had.
    select
        p.*,
        try_cast(replace(p.charge_amount_raw, ',', '') as decimal(18, 2)) as charge_amount,
        try_cast(replace(p.payment_amount_raw, ',', '') as decimal(18, 2)) as payment_amount,
        case
            when try_cast(replace(coalesce(p.charge_amount_raw, p.payment_amount_raw), ',', '') as decimal(18, 2)) < 0 then 'CREDIT'
            when p.charge_amount_raw is not null then 'CHARGE'
            when p.payment_amount_raw is not null then 'PAYMENT'
            else null
        end as line_type
    from pivoted p

),

norm_rule_candidates as (

    -- A line can match both a prefix-specific normalization row and the
    -- vendor's blank-prefix fallback row -- rank by specificity and keep
    -- only the best match per line.
    select
        w.statement_id,
        w.line_number,
        vnr.rule_type,
        vnr.pattern,
        vnr.reconstruct_template,
        row_number() over (
            partition by w.statement_id, w.line_number
            order by case when vnr.prefix_pattern is not null and vnr.prefix_pattern <> '' then 0 else 1 end
        ) as rn
    from with_line_type w
    {{ vendor_normalization_rule_join('w.vendor_id', 'w.line_type', 'w.original_invoice_number') }}

),

vnr as (

    select statement_id, line_number, rule_type, pattern, reconstruct_template
    from norm_rule_candidates
    where rn = 1

),

lines as (

    select statement_id, line_number, extraction_confidence, shop_name
    from {{ source('bronze', 'unnested_statement_lines') }}

)

select
    w.statement_id + '-' + cast(w.line_number as varchar(10)) as statement_line_id,
    w.statement_id,
    w.line_number,
    w.line_type,
    try_cast(w.line_date_raw as date)                    as line_date,
    {{ apply_vendor_normalization('w.original_invoice_number', 'w.line_type') }} as invoice_number,
    w.invoice_number_ref,
    w.original_invoice_number                            as document_number,
    w.work_order_number,
    w.ro_number,
    case when w.ro_number is not null then 'extraction' else null end as ro_number_source,
    w.po_number,
    case when w.po_number is not null then 'extraction' else null end as po_number_source,
    cast(null as varchar(20))                            as vin,
    w.transaction_code,
    w.description_raw,
    cast(w.charge_amount as float)                       as charge_amount,
    cast(w.payment_amount as float)                       as payment_amount,
    cast(null as decimal(18, 2))                         as core_charge_amount,
    cast(null as decimal(18, 2))                         as line_net_amount,
    cast(null as decimal(18, 2))                         as running_balance,
    cast(try_cast(replace(w.amount_remaining_raw, ',', '') as decimal(18, 2)) as float) as amount_remaining,
    try_cast(w.due_date_raw as date)                     as due_date,
    try_cast(w.age_in_days_raw as int)                   as age_in_days,
    cast(null as varchar(50))                            as vendor_group_code,
    l.shop_name                                          as vendor_group_label,
    cast(l.extraction_confidence as float)                as extraction_confidence,
    cast(0 as bit)                                       as is_matched,
    cast(null as varchar(50))                            as source_bronze_row_id,
    cast(getdate() as datetime2(6))                      as ingested_at,
    cast(null as bigint)                                 as version_number
from with_line_type w
left join lines l on l.statement_id = w.statement_id and l.line_number = w.line_number
left join vnr on vnr.statement_id = w.statement_id and vnr.line_number = w.line_number
