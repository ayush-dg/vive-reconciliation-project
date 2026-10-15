{#
    normalize_field_name (added 2026-10-15): a field name -> lower case with
    separators / punctuation removed, so 'Reference Number', 'reference_number'
    and 'REFERENCE NUMBER' compare equal, as do 'DOCUMENT / TRANSACTION' and
    'DOCUMENT/TRANSACTION'. Used by statement_line.sql's mapping join, where an
    exact raw_field_name match still wins over a normalized one.
    Same characters as src/lakehouse/field_names.FIELD_NAME_STRIP_CHARS
    (tests/test_field_name_matching.py checks they agree).
#}
{% macro normalize_field_name(col) -%}
    {%- set strip_chars = [" ", "_", "/", "\\", "-", ".", ",", ":", "#", "$", "&", "(", ")", "''", "*"] -%}
    {%- set ns = namespace(expr="lower(" ~ col ~ ")") -%}
    {%- for ch in strip_chars -%}
        {%- set ns.expr = "replace(" ~ ns.expr ~ ", '" ~ ch ~ "', '')" -%}
    {%- endfor -%}
    {{ ns.expr }}
{%- endmacro %}
