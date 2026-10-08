"""NetSuite custom field / record ids the write-back depends on.

Kept in one place so the preflight (scripts/netsuite_preflight.py) and the
write-back read the same list. Everything here was created by hand in the
sandbox -- a sandbox refresh wipes anything not deployed via SDF/bundle,
which is why the preflight re-checks these on every run instead of
trusting that they still exist.
"""

# Record types that carry the reconciliation body fields.
BODY_RECORD_TYPES = ("vendorbill", "vendorcredit")

# custbody_statement_link is the Hyperlink-type field holding the PDF link;
# custbody_statement_reference stays a human-readable statement id.
BODY_FIELDS = (
    "custbody_reconciled",
    "custbody_statement_reference",
    "custbody_statement_link",
    "custbody_reconciled_date",
    "custbody_reconciliation_exception",
)

STATEMENT_LINE_RECORD = "customrecord_statement_line"

STATEMENT_LINE_FIELDS = (
    "custrecord_sl_vendor",
    "custrecord_sl_statement_id",
    "custrecord_sl_invoice_number",
    "custrecord_sl_statement_amount",
    "custrecord_sl_status",
    "custrecord_sl_exception_type",
    "custrecord_sl_matched_bill",
    "custrecord_sl_shop",
    "custrecord_sl_statement_link",
    "custrecord_sl_location",
)
