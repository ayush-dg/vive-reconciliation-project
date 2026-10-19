"""
revalidate_intake.py -- recompute ONLY the seven document_intake_log
validation columns of the named statements with the current gate, from their
stored extraction rows and hash-checked local PDFs. See src/rerun/revalidate.py.

  Dry run (reads only; writes the plan file):
    python scripts/revalidate_intake.py --statement-id STMT-A --pdf STMT-A=<file> [...] --plan-out plan.json
  Apply the saved plan (re-reads the rows, refuses unless the fingerprint still
  matches; writes backup .json + undo .sql/.py to every --backup-dir FIRST and
  reads it back; then ONE transaction; then re-reads to verify):
    python scripts/revalidate_intake.py --plan plan.json --apply --confirm <fingerprint>
  Undo (dry run unless --apply):  python <backup dir>/revalidation_<stamp>_undo.py [--apply]
"""

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from src.rerun import in_place, revalidate  # noqa: E402

DEFAULT_BACKUP_DIR = os.path.join(PROJECT_ROOT, "scratchpad", "revalidation_backups")


def main(argv=None, io=None, intake=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--statement-id", action="append", default=[])
    parser.add_argument("--pdf", action="append", default=[], help="STATEMENT_ID=<local PDF> (repeatable)")
    parser.add_argument("--plan-out", help="dry run: where to write the plan file")
    parser.add_argument("--plan", help="apply: the plan file written by the dry run")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", help="the fingerprint printed by the dry run")
    parser.add_argument("--backup-dir", action="append", help="repeatable; default scratchpad/revalidation_backups")
    args = parser.parse_args(argv)
    io = io or in_place.LiveIO()

    if args.apply:
        if not args.plan or not args.confirm:
            parser.error("--apply needs --plan <file> and --confirm <fingerprint>")
        the_plan = json.load(open(args.plan, encoding="utf-8"))
        if the_plan.get("fingerprint") != args.confirm:
            print(f"REFUSED: --confirm doesn't match the plan's fingerprint {the_plan.get('fingerprint')}")
            return 2
        paths = revalidate.backup(the_plan, args.backup_dir or [DEFAULT_BACKUP_DIR])
        print("backup written and read back:", *paths, sep="\n  ")
        try:
            result = revalidate.apply(io, the_plan, args.confirm, paths)
        except revalidate.RefusedError as e:
            print("REFUSED:", e)
            return 2
        print(json.dumps(result, indent=1))
        return 0 if result["verified"] else 3

    if not args.statement_id or not args.plan_out:
        parser.error("a dry run needs --statement-id (repeatable) and --plan-out <file>")
    pdfs = dict(p.split("=", 1) for p in args.pdf)
    intake = intake or in_place.load_intake()
    try:
        the_plan = revalidate.plan(io, intake, args.statement_id, pdfs)
    except revalidate.RefusedError as e:
        print("REFUSED:", e)
        return 2
    with open(args.plan_out, "w", encoding="utf-8") as f:
        json.dump(the_plan, f, indent=1, default=str)
    for r in the_plan["rows"]:
        print(f"{r['statement_id']}: " + "; ".join(f"{c} {r['old'][c]!r} -> {r['new'][c]!r}"
                                                   for c in r["changed"] if c != "validation_detail"))
    for u in the_plan["unchanged"]:
        print(f"{u['statement_id']}: unchanged -- {u['reason']}")
    print(f"\nDRY RUN -- nothing written. Plan: {args.plan_out}. To apply: --plan {args.plan_out} --apply "
          f"--confirm {the_plan['fingerprint']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
