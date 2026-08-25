"""
Row-by-row comparison of extract_generic.py's output against the ground-
truth reference JSON (generate_reference.py's output, produced by each
vendor's existing verified extract_<vendor>.py module).

For each vendor, every reference line item is matched to a generic-script
line item by (invoice_number, date) key, consumed in document order (so
duplicate invoice numbers on different rows still pair up correctly in
sequence). For each matched pair, charge and credit are compared to the
cent. Unmatched reference rows are reported as MISSING; unmatched generic
rows left over are reported as EXTRA/SPURIOUS.
"""
import json
import os
import sys
from collections import defaultdict, deque

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.dirname(THIS_DIR)
SAMPLE_DIR = os.path.join(LIB_DIR, "sample_pdfs")
OUT_DIR = os.path.join(THIS_DIR, "output")

sys.path.insert(0, LIB_DIR)
from extract_generic import extract as generic_extract, clean_money  # noqa: E402

VENDORS = [
    ("Fred Beans Lee's", "Fred Beans Lee's.pdf",
     {"date": "date", "invoice": "invoice_number", "charge": "charges", "credit": "credits"}),
    ("Astech Owego", "Astech Owego.pdf",
     {"date": "invoice_date", "invoice": "invoice_no", "amount": "outstanding_amount"}),
    ("Empire Hewitt's", "Empire Hewitt's.PDF",
     {"date": "transaction_date", "invoice": "doc_no", "amount": "amount"}),
    ("Wilbert's Owego", "Wilbert's Owego.PDF",
     {"date": "date", "invoice": "invoice_number", "amount": "amount"}),
    ("Quirk Colemans", "Quirk Colemans.PDF",
     {"date": "date", "invoice": "invoice", "amount": "amount"}),
    ("Matt Nimey Sprague's", "Matt Nimey Sprague's.pdf",
     {"date": "invoice_date", "invoice": "invoice_no", "charge": "purchases", "credit": "payments"}),
    ("Lia Vestal", "Lia Vestal.pdf",
     {"date": "date", "invoice": "document_transaction", "charge": "purchases", "credit": "payments_credits"}),
    ("Keystone Neet's", "Keystone Neet's.pdf",
     {"date": "reference_date", "invoice": "reference_number", "amount": "balance_due"}),
    ("Precision Diagnostics Klapec", "Precision Diagnostics Klapec.pdf",
     {"date": "date", "invoice": "invoice_no", "charge": "charge", "credit": "payment"}),
    ("Adas Calibration Don Joe", "Adas Calibration Don Joe.pdf",
     {"date": "date", "invoice": "invoice_no", "amount": "open_amount"}),
]


def ref_tuple(item, cfg):
    date = (item.get(cfg["date"]) or "").strip()
    invoice = (item.get(cfg["invoice"]) or "").strip()
    if "amount" in cfg:
        val = clean_money(item.get(cfg["amount"]))
        charge = val if (val is not None and val >= 0) else None
        credit = -val if (val is not None and val < 0) else None
    else:
        charge = clean_money(item.get(cfg["charge"]))
        credit = clean_money(item.get(cfg["credit"]))
    return date, invoice, charge, credit


def gen_tuple(item):
    charge, credit = item.get("charge"), item.get("credit")
    if charge is None and credit is None:
        # Neither a CHARGE-role nor a CREDIT-role header was found on this
        # document (e.g. the only numeric column classified is BALANCE) -
        # fall back to splitting the single reconciling amount by sign, the
        # same convention used for the reference side's single-"amount"-
        # column vendors (see ref_tuple).
        bal = item.get("balance")
        if bal is not None:
            charge = bal if bal >= 0 else None
            credit = -bal if bal < 0 else None
    return (item.get("date") or "").strip(), (item.get("invoice_number") or "").strip(), charge, credit


def money_eq(a, b, tol=0.005):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def key_of(date, invoice):
    return (invoice.upper(), date.upper())


def compare_vendor(label, filename, cfg):
    ref_path = os.path.join(OUT_DIR, f"{label} - reference.json")
    ref_data = json.load(open(ref_path, encoding="utf-8"))
    ref_items = ref_data["line_items"]

    pdf_path = os.path.join(SAMPLE_DIR, filename)
    generic_result = generic_extract(pdf_path)
    gen_items = generic_result["line_items"]

    gen_by_key = defaultdict(deque)
    for i, gi in enumerate(gen_items):
        d, inv, _, _ = gen_tuple(gi)
        gen_by_key[key_of(d, inv)].append(i)

    used_gen_idx = set()
    matched, mismatched, missing = [], [], []

    for ref_idx, ritem in enumerate(ref_items):
        rd, rinv, rcharge, rcredit = ref_tuple(ritem, cfg)
        k = key_of(rd, rinv)
        q = gen_by_key.get(k)
        if q:
            gi_idx = q.popleft()
            used_gen_idx.add(gi_idx)
            gitem = gen_items[gi_idx]
            gd, ginv, gcharge, gcredit = gen_tuple(gitem)
            if money_eq(rcharge, gcharge) and money_eq(rcredit, gcredit):
                matched.append((ref_idx, ritem, gitem))
            else:
                mismatched.append((ref_idx, ritem, gitem, (rd, rinv, rcharge, rcredit), (gd, ginv, gcharge, gcredit)))
        else:
            missing.append((ref_idx, ritem, (rd, rinv, rcharge, rcredit)))

    extra = [(i, gen_items[i]) for i in range(len(gen_items)) if i not in used_gen_idx]

    return {
        "label": label,
        "reference_count": len(ref_items),
        "generic_count": len(gen_items),
        "tiers": generic_result["summary"]["tier_used_per_page"],
        "matched": matched,
        "mismatched": mismatched,
        "missing": missing,
        "extra": extra,
    }


def main():
    all_results = []
    for label, filename, cfg in VENDORS:
        res = compare_vendor(label, filename, cfg)
        all_results.append(res)

        exact_pct = 100.0 * len(res["matched"]) / res["reference_count"] if res["reference_count"] else 0.0
        print(f"\n{'=' * 90}\n{label}\n{'=' * 90}")
        print(f"  reference rows: {res['reference_count']}   generic rows: {res['generic_count']}")
        print(f"  tiers used: {res['tiers']}")
        print(f"  MATCHED (date+invoice+amount all correct): {len(res['matched'])} / {res['reference_count']} ({exact_pct:.1f}%)")
        print(f"  MISMATCHED (matched row, wrong amount):     {len(res['mismatched'])}")
        print(f"  MISSING (reference row not found in generic output): {len(res['missing'])}")
        print(f"  EXTRA (generic row not in reference / spurious):      {len(res['extra'])}")

        if res["mismatched"]:
            print("  -- sample amount mismatches --")
            for ref_idx, ritem, gitem, rtup, gtup in res["mismatched"][:5]:
                print(f"    ref row #{ref_idx}: ref(date,inv,charge,credit)={rtup}  generic={gtup}")

        if res["missing"]:
            print("  -- sample missing rows --")
            for ref_idx, ritem, rtup in res["missing"][:5]:
                print(f"    ref row #{ref_idx}: {rtup}  (raw ref item: {ritem})")

        if res["extra"]:
            print("  -- sample extra/spurious rows --")
            for i, gitem in res["extra"][:5]:
                print(f"    generic row #{i}: {gitem}")

    print(f"\n{'#' * 90}\nSUMMARY\n{'#' * 90}")
    for res in all_results:
        exact = len(res["matched"]) == res["reference_count"] and len(res["extra"]) == 0
        pct = 100.0 * len(res["matched"]) / res["reference_count"] if res["reference_count"] else 0.0
        verdict = "EXACT MATCH" if exact else ("FAIL" if pct < 20 else "PARTIAL MATCH")
        print(f"  {res['label']:32s} {verdict:14s} matched {len(res['matched'])}/{res['reference_count']} "
              f"({pct:.1f}%)  extra={len(res['extra'])}  mismatched_amount={len(res['mismatched'])}")


if __name__ == "__main__":
    main()
