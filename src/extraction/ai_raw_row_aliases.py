"""Renames an AI (Claude) extraction's raw row keys to the field names the
vendor's seed mapping knows, for vendors whose vendor_field_mapping rows
were written for their parser (added 2026-10-08).

Why: Claude names each column by its printed header, verbatim ("INVOICE
NUMBER", "Invoice #", "Outstanding Amount", ...), and splits an unlabeled
two-part code into UNLABELED_TRANSACTION_CODE / _2. vendor_field_mapping
matches raw_field_name exactly (case-sensitive), so a scanned statement --
no text layer, so the parser can't read it and Claude does -- mapped no
field at all: Bronze had every line, Silver got 0, and the run showed
0 / 0 / 0 (prod STMT-3C9D4BBB Fred Beans 71 lines, STMT-EC5E296A Astech
135 lines).

How: a key is left alone when it already is a mapped raw_field_name for
the vendor. Otherwise it is compared with the vendor's mapped names after
normalizing both -- lowercase, "#" and "number" read as "no", everything
but letters and digits dropped -- so "Invoice #" lines up with
"invoice_no", "INVOICE NUMBER" with "invoice_number", "Due Date" with
"due_date". _EXTRA_ALIASES covers the few headers that differ by more than
that. A key with no match keeps its own name (it just won't map, as
before), and parser rows -- which already use the mapped names -- come out
unchanged.

Fred Beans also gets its UNLABELED_TRANSACTION_CODE parts joined into
transaction_code ("66 35"): its vendor_line_selection_rule picks the
original posting ('60 35') over the reprint ('99 57') per invoice, so
without it reprints would be counted too.

Applied to `invoices` (in place) right before the Bronze writes in
notebooks/01_document_intake.py and src/rerun/in_place.py, so
bronze.raw_statement and the unnested tables hold the same names.
"""
import csv
import os
import re

_SEED = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     "dbt", "vive_recon", "seeds", "vendor_field_mapping.csv")

# vendor_id -> {normalized header: mapped raw_field_name}, for headers the
# generic normalization can't line up on its own.
_EXTRA_ALIASES = {
    "FRED_BEANS_PARTS": {
        "invoice": "invoice_number",
        "invno": "invoice_number",
        "transactiondate": "date",
        "invoicedate": "date",
        "charge": "charges",
        "credit": "credits",
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

_mapped_cache = None


def _norm(header) -> str:
    s = str(header).lower().replace("#", "no").replace("number", "no")
    return re.sub(r"[^a-z0-9]", "", s)


def _mapped_names() -> dict:
    """vendor_id -> set of raw_field_name values with a canonical field."""
    global _mapped_cache
    if _mapped_cache is None:
        mapped = {}
        try:
            with open(_SEED, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    if (r.get("canonical_field_name") or "").strip():
                        mapped.setdefault(r["vendor_id"], set()).add(r["raw_field_name"])
        except OSError:
            mapped = {}
        _mapped_cache = mapped
    return _mapped_cache


def _aliases_for(vendor_id: str) -> tuple:
    """(exact mapped names, {normalized name: mapped name})"""
    exact = _mapped_names().get(vendor_id, set())
    by_norm = {}
    for name in sorted(exact):
        by_norm.setdefault(_norm(name), name)
    for k, v in _EXTRA_ALIASES.get(vendor_id, {}).items():
        by_norm.setdefault(k, v)
    return exact, by_norm


def _normalize_row(row: dict, exact: set, by_norm: dict, join_into) -> dict:
    out = {}
    unlabeled = []
    renamed = []
    for key, value in row.items():
        if join_into and _UNLABELED_RE.match(str(key)):
            m = _UNLABELED_RE.match(str(key))
            unlabeled.append((int(m.group(1) or 1), key, value))
            continue
        if key in exact:
            out[key] = value
        else:
            renamed.append((key, value))
    for key, value in renamed:
        target = by_norm.get(_norm(key))
        if target and target not in out:
            out[target] = value
        else:
            # No match, or the mapped name is already taken on this row:
            # keep it under its own name so nothing is lost.
            out[key] = value
    if unlabeled:
        if join_into not in out:
            parts = [str(v).strip() for _, _, v in sorted(unlabeled, key=lambda p: p[0]) if v not in (None, "")]
            out[join_into] = " ".join(parts) if parts else None
        else:
            for _, key, value in unlabeled:
                out[key] = value
    return out


def normalize_raw_rows(invoices: list, vendor_id: str) -> int:
    """Rewrites each invoice's "_raw_row" so its keys use the vendor's
    mapped raw_field_names. Returns how many rows changed (0 for a vendor
    with no mapping, or rows that already use the mapped names)."""
    exact, by_norm = _aliases_for(vendor_id)
    if not by_norm:
        return 0
    join_into = _JOIN_UNLABELED.get(vendor_id)
    changed = 0
    for inv in invoices or []:
        row = inv.get("_raw_row") if isinstance(inv, dict) else None
        if not isinstance(row, dict):
            continue
        new_row = _normalize_row(row, exact, by_norm, join_into)
        if new_row != row:
            inv["_raw_row"] = new_row
            changed += 1
    return changed
