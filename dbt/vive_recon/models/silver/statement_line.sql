-- Loops over var('known_vendor_ids') (dbt_project.yml) instead of one
-- staging model per vendor -- extraction already normalizes every vendor
-- into the same generic Bronze schema (see models/bronze/sources.yml's
-- comment), so the mapping below is genuinely identical across vendors.
-- Onboarding a new vendor is: add its id to known_vendor_ids once its
-- bronze.bronze_<id>_raw table exists -- no new SQL file.
--
-- unique_key + merge (see dbt_project.yml) makes a re-run of the same
-- statement_id idempotent. The statement_id var scopes a run to just one
-- job's statement (passed as `--vars '{"statement_id": "..."}'` by the
-- pipeline) so a per-job run doesn't rescan every vendor's full Bronze
-- history; omit it (e.g. manual dev runs) to process everything.
{{ config(unique_key='statement_line_id') }}

{% set target_statement_id = var('statement_id', none) %}

with unioned as (

    {% for vendor_id in var('known_vendor_ids') %}
    select
        statement_id + '-' + cast(row_number as varchar(10))              as statement_line_id,
        statement_id,
        row_number                                                        as line_number,
        case
            when coalesce(raw_outstanding_amount, raw_amount) < 0 then 'CREDIT'
            when coalesce(raw_outstanding_amount, raw_amount) is null
                 and raw_credit is not null then 'PAYMENT'
            else 'CHARGE'
        end                                                                as line_type,
        raw_invoice_date                                                  as line_date,
        raw_invoice_number                                                as invoice_number,
        cast(null as varchar(50))                                         as invoice_number_ref,
        raw_invoice_number                                                as document_number,
        raw_work_order_number                                             as work_order_number,
        raw_ro_number                                                     as ro_number,
        case when raw_ro_number is not null then 'extraction' else null end as ro_number_source,
        raw_po_number                                                     as po_number,
        case when raw_po_number is not null then 'extraction' else null end as po_number_source,
        cast(null as varchar(20))                                         as vin,
        raw_description                                                   as description_raw,
        coalesce(raw_outstanding_amount, raw_amount)                      as charge_amount,
        raw_credit                                                        as payment_amount,
        cast(null as decimal(18, 2))                                      as core_charge_amount,
        cast(null as decimal(18, 2))                                      as line_net_amount,
        cast(null as decimal(18, 2))                                      as running_balance,
        coalesce(raw_outstanding_amount, raw_amount)                      as amount_remaining,
        raw_due_date                                                      as due_date,
        cast(null as int)                                                 as age_in_days,
        cast(null as varchar(50))                                         as vendor_group_code,
        raw_shop_name                                                     as vendor_group_label,
        extraction_confidence,
        cast(0 as bit)                                                    as is_matched,
        cast(null as varchar(50))                                         as source_bronze_row_id,
        cast(getdate() as datetime2(6))                                   as ingested_at,
        version_number
    from {{ source('bronze', 'bronze_' ~ vendor_id ~ '_raw') }}
    {% if not loop.last %} union all {% endif %}
    {% endfor %}

)

select * from unioned
{% if target_statement_id is not none %}
where statement_id = '{{ target_statement_id }}'
{% endif %}
