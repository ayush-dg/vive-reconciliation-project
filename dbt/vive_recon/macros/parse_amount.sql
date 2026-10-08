{#
    parse_amount (added 2026-10-08): a statement amount string -> decimal(18, 2).

    The plain try_cast(replace(x, ',', '')) this replaces returned NULL for
    three formats real statements print, silently dropping the amount:
      - a trailing minus for negatives:   '100.00-'   -> -100.00
        (Keystone / LKQ-branded ledgers via extract_keystone, Lia, Fred Beans' amount_due)
      - a dollar sign:                    '$1,279.50' -> 1279.50   (LKQ-branded copies)
      - parentheses for negatives:        '($259.50)' -> -259.50   (LKQ-branded copies)
    Everything the old expression already parsed parses the same way, and
    blanks / non-numbers still come back NULL. Confirmed 2026-10-08: in mapped
    charge / payment columns no stored value used these formats, so existing
    vendors' matching is unchanged; only previously-NULL amounts now parse.
#}
{% macro parse_amount(col) -%}
    try_cast(
        case
            when ltrim(rtrim({{ col }})) like '(%)'
                then '-' + replace(replace(substring(ltrim(rtrim({{ col }})), 2, len(ltrim(rtrim({{ col }}))) - 2), ',', ''), '$', '')
            when ltrim(rtrim({{ col }})) like '%[0-9]-'
                then '-' + replace(replace(left(ltrim(rtrim({{ col }})), len(ltrim(rtrim({{ col }}))) - 1), ',', ''), '$', '')
            else replace(replace(nullif(ltrim(rtrim({{ col }})), ''), ',', ''), '$', '')
        end as decimal(18, 2))
{%- endmacro %}
