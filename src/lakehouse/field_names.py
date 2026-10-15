"""How an extracted field name is compared with vendor_field_mapping.raw_field_name.

The same printed column reaches Bronze spelled several ways: a parser's own
names (reference_number), Claude's verbatim header (Reference Number), and
small differences in how a header was read (DOCUMENT / TRANSACTION vs
DOCUMENT/TRANSACTION). An exact comparison treated each spelling as a
different column, so a vendor's first Claude-read statement -- or one header
read with a different space -- reconciled nothing.

Names are compared case-insensitively with these separator/punctuation
characters removed. An exact match still wins: when a field has any exact
mapping rows, only those are used (see models/silver/statement_line.sql).

dbt/vive_recon/macros/normalize_field_name.sql applies the same rule in SQL;
tests/test_field_name_matching.py keeps the two in step.
"""

FIELD_NAME_STRIP_CHARS = (" ", "_", "/", "\\", "-", ".", ",", ":", "#", "$", "&", "(", ")", "'", "*")


def normalize_field_name(name) -> str:
    s = (name or "").lower()
    for ch in FIELD_NAME_STRIP_CHARS:
        s = s.replace(ch, "")
    return s
