"""Renames an AI (Claude) extraction's raw row keys to the field names a
vendor's parser writes, for vendors whose vendor_field_mapping seed rows
only know the parser's names (added 2026-10-08).

Why: Claude names each column by its printed header, verbatim ("INVOICE
NUMBER", "CHARGES", ...), and splits an unlabeled two-part code into
UNLABELED_TRANSACTION_CODE / _2. vendor_field_mapping matches raw_field_name
exactly (case-sensitive), so a scanned Fred Beans statement -- no text
layer, so the parser can't read it and Claude does -- mapped no field at
all: Bronze had all 71 lines, Silver got 0, and the run showed 0 / 0 / 0
as "RECONCILED" (prod STMT-3C9D4BBB, dev STMT-28766577). The joined code
matters too: Fred Beans' vendor_line_selection_rule picks the original
posting ('60 35') over the reprint ('99 57') per invoice, so without it
reprints would be counted as well.

Header matching ignores case, spaces and punctuation ("Invoice #",
"INVOICE NO." and "invoice_number" are all the same key), so small
variations between AI runs still map. A header not listed here is kept
under its own name -- it just won't map, as before. Parser rows already use
the target names, so running this on them changes nothing.

Applied to `invoices` (in place) right before the Bronze writes in
notebooks/01_document_intake.py and src/rerun/in_place.py, so
bronze.raw_statement and the unnested tables hold the same names.
"""
import re

# vendor_id -> {normalized header: parser field name}
_ALIASES = {
    "FRED_BEANS_PARTS": {
        "invoicenumber": "invoice_number",
        "invoiceno": "invoice_number",
        "invoice": "invoice_number",
        "invnumber": "invoice_number",
        "invno": "invoice_number",
        "date": "date",
        "transactiondate": "date",
        "invoicedate": "date",
        "charges": "charges",
        "charge": "charges",
        "credits": "credits",
        "credit": "credits",
        "amountdue": "amount_due",
        "balancedue": "amount_due",
        "transactioncode": "transaction_code",
        "code": "transaction_code",
    },
}

# vendor_id -> field the UNLABELED_TRANSACTION_CODE[_n] parts are joined into
_JOIN_UNLABELED = {
    "FRED_BEANS_PARTS": "transaction_code",
}

_UNLABELED_RE = re.compile(r"^UNLABELED_TRANSACTION_CODE(?:_(\d+))?$", re.IGNORECASE)


def _norm(header) -> str:
    return re.sub(r"[^a-z0-9]", "", str(header).lower())


def _normalize_row(row: dict, aliases: dict, join_into) -> dict:
    out = {}
    unlabeled = []
    for key, value in row.items():
        m = _UNLABELED_RE.match(str(key)) if join_into else None
        if m:
            unlabeled.append((int(m.group(1) or 1), value))
            continue
        target = aliases.get(_norm(key), key)
        if target in out:
            # Two headers for the same field: keep the first, and the
            # second under its own name so nothing is lost.
            out[key] = value
        else:
            out[target] = value
    if unlabeled and join_into not in out:
        parts = [str(v).strip() for _, v in sorted(unlabeled, key=lambda p: p[0]) if v not in (None, "")]
        out[join_into] = " ".join(parts) if parts else None
    elif unlabeled:
        for n, v in unlabeled:
            out["UNLABELED_TRANSACTION_CODE" + ("" if n == 1 else f"_{n}")] = v
    return out


def normalize_raw_rows(invoices: list, vendor_id: str) -> int:
    """Rewrites each invoice's "_raw_row" for a vendor listed above.
    Returns how many rows changed (0 for any other vendor)."""
    aliases = _ALIASES.get(vendor_id)
    if not aliases:
        return 0
    join_into = _JOIN_UNLABELED.get(vendor_id)
    changed = 0
    for inv in invoices or []:
        row = inv.get("_raw_row") if isinstance(inv, dict) else None
        if not isinstance(row, dict):
            continue
        new_row = _normalize_row(row, aliases, join_into)
        if new_row != row:
            inv["_raw_row"] = new_row
            changed += 1
    return changed
