{#
    Generic invoice-number normalization, driven entirely by
    silver.vendor_normalization_rule -- no vendor-name branches here or in
    any caller. See Vendor_Normalization_Strategy.md for the design and
    dbt/vive_recon/seeds/vendor_normalization_rule.csv for the confirmed
    rules (Quirk/Nucar/Keystone verified live against real NetSuite data;
    NYE not yet verified -- see that CSV's notes column).

    Usage: the calling model must LEFT JOIN vendor_normalization_rule as
    `vnr` itself, via vendor_normalization_rule_join() below -- NOT `rule`:
    RULE is a reserved T-SQL keyword (the legacy CREATE RULE object),
    confirmed 2026-09-17 against the real Fabric Warehouse ("Incorrect
    syntax near the keyword 'rule'") when first tried as an alias.
    Joining in the calling model (rather than a correlated subquery here)
    lets this macro reference vnr.rule_type/pattern/reconstruct_template as
    a plain column reference -- a correlated subquery would risk the same
    "UnSupportedLogicalOperation" distributed-engine failure confirmed
    against the real Fabric Warehouse while building silver_silver (see
    src/lakehouse/silver_silver_build.py's docstring).

    Two stages, matching the CSV's columns, both validated against the
    real Fabric Warehouse 2026-09-17 (Quirk/Nucar/NYE/Keystone/ASTECH/
    Empire test cases, all matched expected output exactly):
      1. base normalize (vnr.rule_type): strip_first_n_chars (positional,
         vnr.pattern = N as a string), strip_trailing_char (vnr.pattern =
         the single character), lowercase, or no match at all -> passthrough
         (NOT an implicit default strip -- see the CSV's ASTECH/Bowser/RH
         Long absence, which must stay byte-for-byte unchanged).
      2. credit reconstruction (vnr.reconstruct_template): only applied
         when this is a credit line AND the matched rule has a non-null
         template -- wraps the base-normalized value into
         "...{invoice}..." (e.g. 'CM{invoice}', 'CM-{invoice}-1').

    Closed rule_type taxonomy, matching the strategy doc's own guidance
    (resist adding a 5th without a confirmed, real case) -- currently:
    strip_first_n_chars, strip_trailing_char, lowercase,
    strip_first_n_chars_lowercase (added 2026-09-18: NYE's GCW/CHW/TOW
    prefixes strip 3 positional chars same as FOW, but NetSuite's tranid
    keeps the trailing letter lowercase where FOW's happens not to need
    it -- confirmed live, e.g. GCW590306G -> 590306g, CHW253431C ->
    253431c, both exact ties against bronze.netsuite_vendorbill).
#}
{% macro apply_vendor_normalization(invoice_col, line_type_col) %}
    case
        when vnr.reconstruct_template is not null and {{ line_type_col }} = 'CREDIT'
            then replace(
                vnr.reconstruct_template,
                '{invoice}',
                (
                    case
                        when vnr.rule_type = 'strip_first_n_chars'
                            then substring({{ invoice_col }}, cast(vnr.pattern as int) + 1, 200)
                        when vnr.rule_type = 'strip_first_n_chars_lowercase'
                            then lower(substring({{ invoice_col }}, cast(vnr.pattern as int) + 1, 200))
                        when vnr.rule_type = 'strip_trailing_char'
                            then case
                                    when right({{ invoice_col }}, 1) = vnr.pattern
                                        then left({{ invoice_col }}, len({{ invoice_col }}) - 1)
                                    else {{ invoice_col }}
                                 end
                        when vnr.rule_type = 'lowercase'
                            then lower({{ invoice_col }})
                        else {{ invoice_col }}
                    end
                )
            )
        when vnr.rule_type = 'strip_first_n_chars'
            then substring({{ invoice_col }}, cast(vnr.pattern as int) + 1, 200)
        when vnr.rule_type = 'strip_first_n_chars_lowercase'
            then lower(substring({{ invoice_col }}, cast(vnr.pattern as int) + 1, 200))
        when vnr.rule_type = 'strip_trailing_char'
            then case
                    when right({{ invoice_col }}, 1) = vnr.pattern
                        then left({{ invoice_col }}, len({{ invoice_col }}) - 1)
                    else {{ invoice_col }}
                 end
        when vnr.rule_type = 'lowercase'
            then lower({{ invoice_col }})
        else {{ invoice_col }}
    end
{% endmacro %}


{#
    The join the calling model needs -- factored out here so every caller
    joins vendor_normalization_rule identically. `line_type_col` must
    already be uppercase CHARGE/CREDIT/PAYMENT (matching statement_line.sql's
    existing derivation); vnr.applies_to is lowercase in the CSV
    ('both'/'charge'/'credit'), hence the lower() compare below.

    prefix_pattern (added 2026-09-18) lets one vendor have multiple rows
    that only apply to invoices starting with a given prefix -- e.g. NYE
    needs CHW/GCW invoices lowercased after stripping but TOW/VWW kept
    uppercase (confirmed live: a single vendor-wide lowercase rule broke
    TOW/VWW while fixing CHW/GCW). A row with prefix_pattern blank is the
    vendor's fallback/default and matches every invoice; a row with a
    prefix_pattern only matches invoices starting with it. Because a line
    can match BOTH a specific-prefix row and the vendor's blank-prefix
    fallback, this join can return more than one candidate row per line --
    the caller must rank by specificity (prefix_pattern not null wins) and
    keep only the top one, e.g. via row_number() partitioned by the line's
    key. See silver_silver_statement_line.sql's norm_rule_ranked CTE.
#}
{% macro vendor_normalization_rule_join(vendor_id_col, line_type_col, invoice_col) %}
    left join {{ ref('vendor_normalization_rule') }} vnr
        on vnr.vendor_id = {{ vendor_id_col }}
        and vnr.is_active = 1
        and (vnr.applies_to = 'both' or lower(vnr.applies_to) = lower({{ line_type_col }}))
        and vnr.effective_start <= cast(getdate() as date)
        and (vnr.effective_end is null or vnr.effective_end >= cast(getdate() as date))
        and (
            vnr.prefix_pattern is null or vnr.prefix_pattern = ''
            or left({{ invoice_col }}, len(vnr.prefix_pattern)) = vnr.prefix_pattern
        )
{% endmacro %}
