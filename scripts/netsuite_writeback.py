"""Dry-run preview of the NetSuite sandbox write-back for one statement.

PHASE 1: this script only READS (the Warehouse, and the sandbox via
SuiteQL). It has no apply mode -- there is deliberately no flag that
writes. It prints what WOULD be PATCHed/POSTed, and counts per outcome.

Run:  python scripts/netsuite_writeback.py --statement-id STMT-910A0737
      python scripts/netsuite_writeback.py --statement-id STMT-910A0737 --json out.json
"""
import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from src.netsuite.client import NetSuiteClient, NetSuiteConfigError
from src.netsuite.writeback import (
    apply_plans, apply_revert, build_plans, build_revert_actions, find_revert_actions_for_statement,
    write_apply_log,
)

_ACTION_ORDER = (
    "PATCH_MATCHED", "PATCH_EXCEPTION", "CREATE_STATEMENT_LINE",
    "SKIP_UP_TO_DATE", "SKIP_RECONCILED_EARLIER", "SKIP_REVIEW",
)


def _fmt_amount(value) -> str:
    return "-" if value is None else f"{value:,.2f}"


def _print_header(ctx) -> None:
    print(f"Statement      : {ctx.statement_id}")
    print(f"Vendor         : {ctx.vendor_name} ({ctx.vendor_id}), {len(ctx.entity_ids)} NetSuite entities")
    print(f"Reference text : {ctx.reference}")
    print(f"PDF link       : {ctx.link or '(none) -- ' + ctx.link_note}")
    print(f"Reconciled date: {ctx.today}")
    print()


def _print_counts(plans) -> None:
    counts = Counter(p.action for p in plans)
    print("Summary (nothing has been written):")
    for action in _ACTION_ORDER:
        print(f"  {action:<26}{counts.get(action, 0):>4}")
    print(f"  {'TOTAL':<26}{len(plans):>4}\n")


def _print_table(plans) -> None:
    print(f"{'ACTION':<24}{'INVOICE':<16}{'STMT AMT':>11}{'NS AMT':>11}  {'NS REC':<22}NOTE")
    for action in _ACTION_ORDER:
        for p in (x for x in plans if x.action == action):
            record = f"{p.record_type}/{p.record_id}" if p.record_id else "-"
            print(f"{p.action:<24}{p.invoice_number:<16}{_fmt_amount(p.statement_amount):>11}"
                  f"{_fmt_amount(p.sandbox_amount):>11}  {record:<22}{p.note}")


def _print_field_samples(plans) -> None:
    print("\nField values per write type (first example of each):")
    for action in ("PATCH_MATCHED", "PATCH_EXCEPTION", "CREATE_STATEMENT_LINE"):
        sample = next((p for p in plans if p.action == action), None)
        if sample:
            print(f"  {action} ({sample.invoice_number}):")
            print("    " + json.dumps(sample.fields, default=str))


def _plans_as_json(ctx, plans) -> dict:
    return {
        "statement_id": ctx.statement_id, "reference": ctx.reference, "link": ctx.link,
        "plans": [{**p.__dict__, "statement_amount": str(p.statement_amount),
                   "sandbox_amount": str(p.sandbox_amount) if p.sandbox_amount is not None else None}
                  for p in plans],
    }


def _apply(ns, ctx, plans) -> int:
    print("\nAPPLYING (each write is read back and verified):")
    results = apply_plans(ns, plans)
    for r in results:
        record = r.new_record_id or r.plan.record_id or "-"
        print(f"  {'OK  ' if r.ok else 'FAIL'} {r.plan.action:<22}{r.plan.invoice_number:<14}"
              f"{r.plan.record_type or 'statement_line':<16}{record:<10}{r.detail}")
    failed = [r for r in results if not r.ok]
    print(f"\n{len(results) - len(failed)} written and verified, {len(failed)} failed.")
    print(f"Write log: {write_apply_log(ns, ctx.statement_id, results)}")
    return 1 if failed else 0


def _revert_from_log(ns, log_path: str, apply: bool) -> int:
    """Undo a previous apply run from its JSON log. Previews unless --apply."""
    with open(log_path, encoding="utf-8") as f:
        log = json.load(f)
    title = f"Revert of {log['statement_id']} (applied {log['applied_at']})"
    return _run_revert(ns, title, build_revert_actions(log), apply)


def _revert_statement(ns, statement_id: str, apply: bool) -> int:
    """Undo everything stamped with this statement id, found in NetSuite
    itself -- no log file needed. Previews unless --apply."""
    title = f"Revert of {statement_id} (found in NetSuite, no log)"
    return _run_revert(ns, title, find_revert_actions_for_statement(ns, statement_id), apply)


def _run_revert(ns, title: str, actions: list, apply: bool) -> int:
    print(f"{title}: {len(actions)} undo actions\n")
    for a in actions:
        what = "delete Statement Line" if a["op"] == "DELETE" else f"restore {json.dumps(a['body'], default=str)}"
        print(f"  {a['record_type']}/{a['record_id']}  {a['invoice_number']:<14}{what}")
    if not apply:
        print("\nPREVIEW ONLY -- add --apply to undo these changes in the sandbox.")
        return 0
    results = apply_revert(ns, actions)
    for a, ok, detail in results:
        print(f"  {'OK  ' if ok else 'FAIL'} {a['record_type']}/{a['record_id']}  {a['invoice_number']:<14}{detail}")
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)} reverted, {len(failed)} failed.")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview, or with --apply write, the NetSuite sandbox write-back.")
    parser.add_argument("--statement-id")
    parser.add_argument("--revert", dest="revert_log", help="Undo the writes recorded in this log file")
    parser.add_argument("--revert-statement", dest="revert_statement", metavar="STATEMENT_ID",
                        help="Undo everything written for this statement, found in NetSuite (no log needed)")
    parser.add_argument("--json", dest="json_path", help="Also write the full plan to this JSON file")
    parser.add_argument("--apply", action="store_true",
                        help="Actually write to the SANDBOX. Without this flag nothing is written.")
    args = parser.parse_args()

    try:
        ns = NetSuiteClient()
    except NetSuiteConfigError as exc:
        print(f"REFUSING TO RUN: {exc}")
        return 2

    mode = "APPLY -- WRITING TO SANDBOX" if args.apply else "DRY RUN -- read-only"
    print(f"NetSuite sandbox: {ns.domain_id}  ({mode})\n")
    if args.revert_log:
        return _revert_from_log(ns, args.revert_log, args.apply)
    if args.revert_statement:
        return _revert_statement(ns, args.revert_statement, args.apply)
    if not args.statement_id:
        parser.error("--statement-id is required unless --revert is given")
    ctx, plans = build_plans(args.statement_id, ns)
    _print_header(ctx)
    _print_counts(plans)
    _print_table(plans)
    _print_field_samples(plans)
    if args.apply:
        return _apply(ns, ctx, plans)
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump(_plans_as_json(ctx, plans), f, indent=2, default=str)
        print(f"\nFull plan written to {args.json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
