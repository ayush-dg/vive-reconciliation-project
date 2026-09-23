"""
netsuite_status_codes.py

Decodes NetSuite's internal single-letter transaction status codes (e.g.
vendor bill status "A"/"B") into their actual business meaning, for
display on the Exceptions review page's "Amount Mismatch" NetSuite
record preview (web/routers/exceptions.py -> exceptions_review.html).

fetch_netsuite_record_for_invoice() (src/matching/fabric_matching.py)
returns each NetSuite row's status column completely raw, on the
explicit stated basis that "this app has no authoritative mapping for
NetSuite's internal status ... lookup lists" -- this module is that
mapping, sourced directly from NetSuite's own status code reference
(the same code means different things on different record types, so
lookups are always scoped by record type, never a bare letter).

Only record types this app actually looks up (see
_SOURCE_TABLE_TO_RECORD_TYPE) are wired to a source table; the rest of
NETSUITE_STATUS_LABELS is kept as-is (unused today) so a future record
type doesn't need this table re-typed from scratch.
"""

NETSUITE_STATUS_LABELS = {
    "VendBill": {"A": "Open", "B": "Paid In Full"},
    "VendPymt": {"V": "Voided", "Z": "Online Bill Pay Pending Accounting Approval"},
    "CashSale": {"A": "Unapproved Payment", "B": "Not Deposited", "C": "Deposited"},
    "Check": {"V": "Voided", "Z": "Online Bill Pay Pending Accounting Approval"},
    "Commissn": {
        "A": "Pending Payment", "O": "Overpaid", "P": "Pending Accounting Approval",
        "R": "Rejected by Accounting", "X": "Paid in Full",
    },
    "CustCred": {"A": "Open", "B": "Fully Applied"},
    "CustDep": {"A": "Not Deposited", "B": "Deposited", "C": "Fully Applied"},
    "CustRfnd": {"V": "Voided"},
    "ExpRept": {
        "A": "In Progress", "B": "Pending Supervisor Approval", "C": "Pending Accounting Approval",
        "D": "Rejected by Supervisor", "E": "Rejected by Accounting", "F": "Approved by Accounting",
        "G": "Approved (Overridden) by Accounting", "H": "Rejected (Overridden) by Accounting",
        "I": "Paid In Full",
    },
    "CustInvc": {"A": "Open", "B": "Paid In Full"},
    "ItemShip": {"A": "Picked", "B": "Packed", "C": "Shipped"},
    "Journal": {"A": "Pending Approval", "B": "Approved for Posting"},
    "Opprtnty": {"A": "In Progress", "B": "Issued Estimate", "C": "Closed – Won", "D": "Closed – Lost"},
    "Paycheck": {
        "A": "Undefined", "C": "Pending Tax Calculation", "D": "Pending Commitment",
        "F": "Committed", "P": "Preview", "R": "Reversed",
    },
    "CustPymt": {"A": "Unapproved Payment", "B": "Not Deposited", "C": "Deposited"},
    "LiabPymt": {"V": "Voided"},
    "PurchOrd": {
        "A": "Pending Supervisor Approval", "B": "Pending Receipt", "C": "Rejected by Supervisor",
        "D": "Partially Received", "E": "Pending Billing/Partially Received", "F": "Pending Bill",
        "G": "Fully Billed", "H": "Closed",
    },
    "Estimate": {"A": "Open", "B": "Processed", "C": "Closed", "V": "Voided", "X": "Expired"},
    "RtnAuth": {
        "A": "Pending Approval", "B": "Pending Receipt", "C": "Cancelled", "D": "Partially Received",
        "E": "Pending Refund/Partially Received", "F": "Pending Refund", "G": "Refunded", "H": "Closed",
    },
    "SalesOrd": {
        "A": "Pending Approval", "B": "Pending Fulfillment", "C": "Cancelled", "D": "Partially Fulfilled",
        "E": "Pending Billing/Partially Fulfilled", "F": "Pending Billing", "G": "Billed", "H": "Closed",
    },
    "TaxPymt": {"V": "Voided", "Z": "Online Bill Pay Pending Accounting Approval"},
    "CustChrg": {"A": "Open", "B": "Paid In Full"},
    "TaxLiab": {"V": "Voided"},
    "TegPybl": {"E": "Endorsed", "I": "Issued", "P": "Paid"},
    "TegRcvbl": {"C": "Collected", "D": "Discounted", "E": "Endorsed", "H": "Holding"},
    "TrnfrOrd": {
        "A": "Pending Approval", "B": "Pending Fulfillment", "C": "Rejected", "D": "Partially Fulfilled",
        "E": "Pending Receipt/Partially Fulfilled", "F": "Pending Receipt", "G": "Received", "H": "Closed",
    },
    "VendAuth": {
        "A": "Pending Approval", "B": "Pending Return", "C": "Cancelled", "D": "Partially Returned",
        "E": "Pending Credit/Partially Returned", "F": "Pending Credit", "G": "Credited", "H": "Closed",
    },
    "WorkOrd": {"B": "Pending Build", "C": "Cancelled", "D": "Partially Built", "G": "Built", "H": "Closed"},
}

# Maps the bronze table fetch_netsuite_record_for_invoice() actually reads
# from to its NetSuite record-type prefix above. netsuite_vendorcredit has
# no confirmed mapping (NetSuite's own status list has no distinct "Vendor
# Credit" record type entry) -- left unmapped so its status is shown raw
# rather than guessed.
_SOURCE_TABLE_TO_RECORD_TYPE = {
    "netsuite_vendorbill": "VendBill",
}


def decode_netsuite_status(source_table: str, status_code: str):
    """Returns the human-readable label for status_code on source_table's
    record type, or None if source_table/status_code is unmapped (caller
    falls back to showing the raw code)."""
    record_type = _SOURCE_TABLE_TO_RECORD_TYPE.get(source_table or "")
    if not record_type:
        return None
    return NETSUITE_STATUS_LABELS.get(record_type, {}).get(status_code)
