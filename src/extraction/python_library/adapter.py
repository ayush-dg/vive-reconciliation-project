"""
adapter.py

Bridges the copied Python-library PDF extractors (extract_all.py's vendor
dispatch, in this same folder) into the Universal Financial Document
Schema shape notebooks/01_document_intake.py expects from
src.ai.document_understanding_engine.DocumentUnderstandingEngine.understand().

Wired into production for text-embedded statements from the vendors
listed in _FIELD_MAP below -- see notebooks/01_document_intake.py's
_determine_extraction_route(), which routes any scanned PDF or any
vendor not in this map to DocumentUnderstandingEngine (Claude Sonnet).
src/ai/document_understanding_engine.py and
src/ai/claude_sonnet_client.py are untouched -- this class is a drop-in
substitute with the same understand(pdf_text, pdf_path, statement_id=None)
signature.

Each hand-written extract_*.py module in this folder uses its own
line-item column names and its own summary-field names, tuned independently
to that vendor's printed statement layout (see each module's own
docstring) -- there is no shared schema across them the way there would be
if one generic extractor produced all of them. _FIELD_MAP /
_VENDOR_DISPLAY_NAMES / _STATEMENT_DATE_KEY / _PRINTED_TOTAL_KEY below are
what translate each module's own field names into the roles understand()
needs. A module not present in _FIELD_MAP (extract_ksi -- OCR/scanned,
never wired to production) is intentionally left unmapped: detect_vendor()
would find it by signature, but understand() refuses to guess a mapping
for it and raises rather than silently routing it with wrong/blank field
values.

extract_keystone (wired 2026-08-23) is a balance-forward/period-activity
ledger rather than simple charge rows -- see its own _FIELD_MAP entry
below. Extraction and Bronze storage are fully wired (every row, every
field, reaches Bronze); charges/credits/outstanding_amount deliberately
stay None for every Keystone row pending a separate, still-open decision
on how its ledger fields relate to a chargeable amount for matching
purposes. That decision is out of scope here -- see the Keystone
investigation session and migrations/012_add_keystone_ledger_columns.sql.
"""

import os
import re
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import extract_all  # noqa: E402 (needs _THIS_DIR on sys.path first)

_MONTH = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06",
    "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}
_DATE_RE = re.compile(r"^(\d{2})([A-Z]{3})(\d{2})$")

# Display vendor_name per module -- matches each module's own
# VENDOR_SIGNATURE and (where one exists) config/vendor_aliases.json, the
# same way the original Fred-Beans-only code hardcoded "Fred Beans Parts".
_VENDOR_DISPLAY_NAMES = {
    "extract_statement": "Fred Beans Parts",
    "extract_astech": "asTech",
    "extract_empire": "Empire Auto Parts",
    "extract_wilberts": "Wilbert's Inc.",
    "extract_quirk": "Quirk Auto Group",
    "extract_nimey": "Matt Nimey GMC",
    "extract_lia": "Lia Auto Group",
    "extract_precision": "Precision Diagnostics",
    "extract_adas": "Adas Calibration Experts",
    "extract_keystone": "Keystone Automotive Industries",
}

# Which summary key holds the statement's own printed grand total, per
# module -- confirmed against each module's real output (see
# extraction_test_results.json from the 15-file batch test). Most modules
# agree on "total_printed", but extract_statement (Fred Beans) and
# extract_astech each use their own name instead.
_PRINTED_TOTAL_KEY = {
    "extract_statement": "balance_due",
    "extract_astech": "total_outstanding_invoices_printed",
    "extract_empire": "total_balance_printed",
    "extract_wilberts": "total_printed",
    "extract_quirk": "total_printed",
    "extract_nimey": "total_printed",
    "extract_lia": "total_printed",
    "extract_precision": "total_printed",
    "extract_adas": "total_printed",
    "extract_keystone": "total_printed",
}

# Which summary key holds the statement date, per module -- these
# genuinely differ in both key name and printed format (DDMonYY, MM/DD/YY,
# "DD MON YYYY", ...). _normalize_date() only understands DDMonYY and
# safely passes any other format through unchanged (see its own
# docstring), so a vendor not on that exact format just keeps its
# as-printed date string rather than a normalized one -- no crash, just
# non-uniform formatting until each format gets its own normalizer.
_STATEMENT_DATE_KEY = {
    "extract_statement": "statement_date",
    "extract_astech": "statement_as_of",
    "extract_empire": "activity_through",
    "extract_wilberts": "statement_date",
    "extract_quirk": "statement_date",
    "extract_nimey": "statement_period_end",
    "extract_lia": "closing_date",
    "extract_precision": "statement_date",
    "extract_adas": "statement_date",
    "extract_keystone": "statement_date",
}

# Per-module line-item field mapping. invoice_number is a tuple tried in
# order (first non-empty wins), matching the original Fred Beans
# invoice_number-or-remit_invoice_no fallback. charge_field/credit_field
# are separate columns, parsed independently. signed_field is for a
# vendor whose statement uses ONE signed column for both charges and
# credits (only extract_quirk today, e.g. "-125.00") -- positive becomes
# a charge, negative becomes a credit, the same charge/credit split Fred
# Beans already does with two separate columns. Mutually exclusive with
# charge_field/credit_field.
_FIELD_MAP = {
    "extract_statement": {
        "invoice_number": ("invoice_number", "remit_invoice_no"),
        "date_field": "date", "due_date_field": None,
        "charge_field": "charges", "credit_field": "credits",
        "amount_due_field": "amount_due", "transaction_code_field": "transaction_code",
    },
    "extract_astech": {
        "invoice_number": ("invoice_no",),
        "date_field": "invoice_date", "due_date_field": "due_date",
        "charge_field": "outstanding_amount", "credit_field": None,
    },
    "extract_empire": {
        "invoice_number": ("doc_no",),
        "date_field": "transaction_date", "due_date_field": "due_date",
        "charge_field": "amount", "credit_field": None,
    },
    "extract_wilberts": {
        "invoice_number": ("invoice_number",),
        "date_field": "date", "due_date_field": None,
        # "balance", not "amount" -- extract_wilberts.py's own docstring:
        # the printed total reconciles against sum(balance), not
        # sum(amount). They're identical for ordinary rows, but the one
        # lump-sum "Payment" row has a non-zero amount (the payment total)
        # and a zero balance (already absorbed by the credit rows it paid
        # down) -- summing amount there double-counts it.
        "charge_field": "balance", "credit_field": None,
    },
    "extract_quirk": {
        "invoice_number": ("invoice",),
        "date_field": "date", "due_date_field": None,
        "signed_field": "amount",
    },
    "extract_nimey": {
        "invoice_number": ("invoice_no",),
        "date_field": "invoice_date", "due_date_field": None,
        "charge_field": "purchases", "credit_field": "payments",
    },
    "extract_lia": {
        "invoice_number": ("document_transaction",),
        "date_field": "date", "due_date_field": None,
        "charge_field": "purchases", "credit_field": "payments_credits",
    },
    "extract_precision": {
        "invoice_number": ("invoice_no",),
        "date_field": "date", "due_date_field": None,
        "charge_field": "charge", "credit_field": "payment",
    },
    "extract_adas": {
        "invoice_number": ("invoice_no",),
        "date_field": "date", "due_date_field": "due_date",
        # "open_amount", not "amount" -- extract_adas.py's own docstring:
        # amount is the ORIGINAL invoice amount, open_amount is what's
        # still unpaid, and the printed TOTAL DUE reconciles against
        # sum(open_amount) (most older invoices are already paid off, so
        # their open_amount is 0.00 while amount still shows the original
        # charge).
        "charge_field": "open_amount", "credit_field": None,
    },
    "extract_keystone": {
        # Ledger-style statement (see extract_keystone.py's own docstring
        # and the Keystone investigation session): every row is EITHER a
        # new-charge row (period_activity populated) OR a settlement row
        # (balance_forward/credit_applied/payment_applied populated),
        # never both. No single field maps cleanly to the shared
        # charge_field/credit_field roles without first deciding how these
        # relate to a chargeable amount for matching purposes -- an
        # explicit, still-open decision, deliberately NOT made here.
        # charge_field/credit_field/amount_due_field are intentionally
        # left unset except amount_due_field below: charges/credits/
        # outstanding_amount stay None for every Keystone row (extraction/
        # Bronze-visibility wiring only -- see migrations/
        # 012_add_keystone_ledger_columns.sql). Every real field still
        # reaches Bronze in its own dedicated column: reference_date ->
        # raw_invoice_date, reference_number -> raw_invoice_number
        # (invoice_number below), purchase_order_number -> raw_po_number
        # (po_number_field below), balance_due -> raw_amount_due
        # (amount_due_field below -- balance_due is the one column always
        # populated on every row, purely display/storage, never read by
        # the matching engine), and the remaining four via
        # passthrough_fields.
        "invoice_number": ("reference_number",),
        "date_field": "reference_date", "due_date_field": None,
        "po_number_field": "purchase_order_number",
        "amount_due_field": "balance_due",
        "passthrough_fields": {
            "balance_forward": "balance_forward",
            "period_activity": "period_activity",
            "credit_applied": "credit_applied",
            "payment_applied": "payment_applied",
        },
    },
}


# Flat signature list for the fast, non-OCR routing gate in
# notebooks/01_document_intake.py (_determine_extraction_route()) -- sourced
# from _FIELD_MAP's own keys so the gate's routable set and this module's
# actual field-mapped set can never drift apart.
ROUTABLE_VENDOR_SIGNATURES = [
    sig
    for module_name in _FIELD_MAP
    for sig in getattr(extract_all, module_name).VENDOR_SIGNATURE
]


def _normalize_date(raw):
    """'23DEC25' -> '2025-12-23'. Returns the raw string unchanged if it
    doesn't match the expected DDMonYY shape -- never guesses."""
    if not raw:
        return None
    m = _DATE_RE.match(raw)
    if not m:
        return raw
    day, mon, yy = m.groups()
    month = _MONTH.get(mon)
    if not month:
        return raw
    return f"20{yy}-{month}-{day}"


def _parse_money(raw):
    """'14,681.56' -> 14681.56, '100.00-' -> -100.00, '$27.11' -> 27.11,
    '-$27.11' -> -27.11 (extract_nimey prints amounts with a leading '$',
    unlike every other module here), '' -> None."""
    if raw is None or str(raw).strip() == "":
        return None
    s = str(raw).strip().replace("$", "").replace(",", "").strip()
    negative = s.endswith("-")
    if negative:
        s = s[:-1].strip()
    try:
        value = float(s)
    except ValueError:
        return None
    return -value if negative else value


class PythonLibraryExtractionEngine:
    """Drop-in substitute for DocumentUnderstandingEngine -- same
    understand(pdf_text, pdf_path, statement_id=None) signature. Ignores
    pdf_text (kept for call-site compatibility, matching the AI engine's
    own convention) and runs the copied pdfplumber-based vendor extractors
    directly against pdf_path instead of calling any AI provider."""

    def understand(self, pdf_text: str, pdf_path: str, statement_id: str = None) -> dict:
        module = extract_all.detect_vendor(pdf_path)
        if module.__name__ not in _FIELD_MAP:
            # Signature-matched by extract_all.py but not yet given a
            # field mapping above (extract_ksi -- OCR/scanned, never
            # wired to production). Raise rather than silently emitting
            # invoices with every amount field blank --
            # notebooks/01_document_intake.py's
            # _determine_extraction_route() gate is what's supposed to keep
            # this class from ever being called for these, so reaching
            # here at all means that gate and this map have drifted out
            # of sync.
            raise extract_all.UnknownVendorError(
                f"{module.__name__} is detected by signature but has no "
                f"field mapping in adapter.py's _FIELD_MAP -- not safe to "
                f"route through PythonLibraryExtractionEngine yet."
            )
        field_map = _FIELD_MAP[module.__name__]
        kwargs = {"output_dir": "."} if module is extract_all.extract_ksi else {}
        result = module.extract(pdf_path, **kwargs)

        line_items = result["line_items"]
        invoices = []

        for row_num, item in enumerate(line_items, start=1):
            if "signed_field" in field_map:
                # One signed column serves as both charges and credits
                # (e.g. Quirk's "amount": "-125.00" for a credit memo) --
                # split it the same way Fred Beans' separate charges/
                # credits columns already are: positive is a charge,
                # negative becomes a credit.
                signed = _parse_money(item.get(field_map["signed_field"]))
                charges = signed if (signed is not None and signed > 0) else None
                credits = abs(signed) if (signed is not None and signed < 0) else None
            else:
                # charge_field is optional (unlike the original Fred-Beans-
                # only code, every other module here declares one) -- a
                # ledger-style module like extract_keystone may have no
                # single field that safely fills the shared charges role
                # at all, pending its own matching design (see that
                # module's _FIELD_MAP entry). Left unset, charges just
                # stays None, same as credit_field already behaves.
                charge_field = field_map.get("charge_field")
                charges = _parse_money(item.get(charge_field)) if charge_field else None
                credit_field = field_map.get("credit_field")
                credits = _parse_money(item.get(credit_field)) if credit_field else None
                # Normalize to a positive magnitude regardless of how the
                # source vendor's own raw text encodes negativity (e.g.
                # extract_nimey.py's "payments" keeps a leading "-$" sign,
                # extract_lia.py's "payments_credits" can carry a trailing
                # "-") -- "credit" means "the credit amount", matching
                # Fred Beans' own credits column convention (always
                # printed/stored positive).
                if credits is not None:
                    credits = abs(credits)

            amount_due_field = field_map.get("amount_due_field")
            amount_due = _parse_money(item.get(amount_due_field)) if amount_due_field else None

            # Ground-truth rule (confirmed by the engineer): Charges is the
            # only field that can ever populate the amount/outstanding_amount
            # matching role. A row with only Credits/Amount Due populated
            # (e.g. a credit memo, or a running-balance line) correctly
            # leaves this blank -- it still reaches Bronze/Silver like any
            # other row (INV-04 amended 2026-08-23, see docs/INVARIANTS.md;
            # a blank amount no longer diverts a row anywhere at extraction
            # time), it simply has no charge amount for matching to read.
            # Never fall back to credits/amount_due here -- that would
            # silently misrepresent a credit or a running balance as a
            # chargeable amount.
            outstanding = charges

            invoice_number = None
            for key in field_map["invoice_number"]:
                invoice_number = item.get(key)
                if invoice_number:
                    break

            due_date_field = field_map.get("due_date_field")
            transaction_code_field = field_map.get("transaction_code_field")
            po_number_field = field_map.get("po_number_field")

            invoice = {
                "invoice_number": invoice_number,
                "invoice_date": _normalize_date(item.get(field_map["date_field"])),
                "due_date": item.get(due_date_field) if due_date_field else None,
                "amount": outstanding,
                "outstanding_amount": outstanding,
                "ro_number": None,
                "po_number": item.get(po_number_field) if po_number_field else None,
                "work_order_number": None,
                "description": None,
                "credit": credits,
                "shop": None,
                "page_number": item.get("page"),
                "row_number": row_num,
                "line_confidence": 1.0,
                # New pass-through columns (migrations/010_add_python_extraction_columns.sql)
                # -- carried by write_to_bronze()/normalize_to_silver()/the
                # matching engine in addition to the fields above, never
                # instead of them.
                "charges": charges,
                "credits": credits,
                "amount_due": amount_due,
                "transaction_code": item.get(transaction_code_field) if transaction_code_field else None,
            }

            # Vendor-specific extra money fields with no shared role across
            # modules (e.g. extract_keystone's balance_forward/
            # period_activity/credit_applied/payment_applied -- see
            # migrations/012_add_keystone_ledger_columns.sql) -- each reaches
            # Bronze in its own dedicated raw_<key> column
            # (write_to_bronze()), untouched by charges/credits/
            # outstanding_amount above and never read by Silver or the
            # matching engine.
            for bronze_key, source_key in field_map.get("passthrough_fields", {}).items():
                invoice[bronze_key] = _parse_money(item.get(source_key))

            invoices.append(invoice)

        summary = result.get("summary", {})

        # This vendor's true printed name, matching this extractor's own
        # VENDOR_SIGNATURE -- 01_document_intake.py's resolve_vendor_id()
        # maps known vendor_names to a canonical vendor_id via
        # config/vendor_aliases.json (currently populated for Fred Beans
        # Parts and asTech only; resolve_vendor_id() returns None for any
        # other miss and callers fall back to a default vendor_id
        # transform, by design -- see that module's own docstring). A
        # vendor's real voucher-sourced ERP data (scripts/load_voucher_data.py)
        # must exist under "VOUCHER-<vendor_id>" for matching to find
        # anything to reconcile against; that's a separate prerequisite
        # from extraction working, unaffected by this change either way.
        vendor_name = _VENDOR_DISPLAY_NAMES.get(module.__name__, module.VENDOR_SIGNATURE[0])

        statement_date = _normalize_date(summary.get(_STATEMENT_DATE_KEY.get(module.__name__, "statement_date")))

        return {
            "document_metadata": {
                "document_type": "VENDOR_STATEMENT",
                "source_file": os.path.basename(pdf_path),
                "page_count": max((li.get("page") or 1) for li in line_items) if line_items else 1,
                "document_type_confidence": 1.0,
            },
            "vendor_metadata": {
                "vendor_name": vendor_name,
                "vendor_address": None,
                "shop_or_entity": [summary["customer_name"]] if summary.get("customer_name") else [],
                "vendor_confidence": 1.0,
            },
            "statement_metadata": {
                "statement_date": statement_date,
                "statement_period_start": None,
                "statement_period_end": statement_date,
                "currency": "USD",
                "statement_total_as_printed": _parse_money(
                    summary.get(_PRINTED_TOTAL_KEY.get(module.__name__, "total_printed"))
                ),
                "statement_confidence": 1.0,
            },
            "invoices": invoices,
            "extraction_confidence": {
                "overall": 1.0,
                "table_detection_confidence": 1.0,
                "column_mapping_confidence": 1.0,
            },
            "warnings": [],
            "_provider_used": "python_library_pdfplumber",
            "_model_used": module.__name__,
        }
