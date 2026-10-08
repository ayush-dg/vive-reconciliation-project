"""
rerun_in_place.py -- re-run ONE stored statement in place with a deterministic
extractor (no AI), keeping its statement_id. See src/rerun/in_place.py.

  Dry run (default -- reads only, writes nothing, prints from -> to per table
  and a fingerprint):
    python scripts/rerun_in_place.py --statement-id STMT-XXXXXXXX
  Apply (re-reads the state, refuses unless it still has the dry run's
  fingerprint; writes the backup to every --backup-dir FIRST and reads it
  back, then writes):
    python scripts/rerun_in_place.py --statement-id STMT-XXXXXXXX --apply --confirm <fingerprint>
  Resume a half-applied statement (Azure SQL written, raw row left in staging,
  Silver/matching not run) -- checks it against the backup's plan first:
    python scripts/rerun_in_place.py --resume <backup.json>                       (dry run)
    python scripts/rerun_in_place.py --resume <backup.json> --apply --confirm <fingerprint>
  Undo (dry run unless --apply):
    python scripts/rerun_in_place.py --undo scratchpad/rerun_backups/rerun_backup_<id>_<stamp>.json [--apply]

--pdf uses a local copy of the PDF instead of downloading the archived one;
either way its SHA-256 must equal the statement's document_hash.
"""

import argparse
import json
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from src.rerun import in_place  # noqa: E402

DEFAULT_BACKUP_DIR = os.path.join(PROJECT_ROOT, "scratchpad", "rerun_backups")


def main(argv=None, io=None, intake=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--statement-id")
    parser.add_argument("--pdf", help="local copy of the statement's PDF (default: download the archived one)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", help="the fingerprint printed by the dry run")
    parser.add_argument("--backup-dir", action="append", help="repeatable; default scratchpad/rerun_backups")
    parser.add_argument("--undo", help="a backup file written by --apply")
    parser.add_argument("--resume", help="a backup file of a half-applied statement: finish its Silver + matching")
    args = parser.parse_args(argv)
    io = io or in_place.LiveIO()

    if args.resume:
        if args.apply and not args.confirm:
            parser.error("--resume --apply needs --confirm <fingerprint> from the resume dry run")
        doc = json.load(open(args.resume, encoding="utf-8"))
        try:
            out = in_place.resume(io, doc, apply_changes=args.apply, expected_fingerprint=args.confirm)
        except in_place.RefusedError as e:
            print("REFUSED:", e)
            return 2
        print(json.dumps(out, indent=1, default=str))
        if not args.apply:
            print(f"\nRESUME DRY RUN -- nothing written. To apply: --resume {args.resume} --apply --confirm {out['fingerprint']}")
        return 0
    if args.undo:
        doc = json.load(open(args.undo, encoding="utf-8"))
        print(json.dumps(in_place.undo(io, doc, apply_changes=args.apply), indent=1, default=str))
        return 0
    if not args.statement_id:
        parser.error("--statement-id is required (one statement at a time)")
    if args.apply and not args.confirm:
        parser.error("--apply needs --confirm <fingerprint> from the dry run")

    intake = intake or in_place.load_intake()
    state = in_place.load_state(io, args.statement_id)
    # Jobs in flight only refuse --apply; a dry run reports them as a warning.
    problems = in_place.refusals(state, dry_run=not args.apply)
    if problems:
        print("REFUSED:", "; ".join(problems))
        return 2
    for warning in in_place.warnings(state):
        print("WARNING:", warning)
    pdf = args.pdf or io.download_pdf(state["intake"][0]["blob_storage_path"], tempfile.mkdtemp(prefix="rerun_"))
    try:
        new = in_place.reextract(io, intake, state, pdf)
    except in_place.RefusedError as e:
        print("REFUSED:", e)
        return 2
    decision = in_place.silver_matching_decision(io, state, new)
    the_plan = in_place.plan(state, new, decision)
    print(json.dumps(the_plan, indent=1, default=str))
    if not args.apply:
        print(f"\nDRY RUN -- nothing written. To apply: --apply --confirm {the_plan['fingerprint']}")
        return 0
    if args.confirm != the_plan["fingerprint"]:
        print(f"REFUSED: --confirm {args.confirm} doesn't match this state's fingerprint {the_plan['fingerprint']}")
        return 2
    paths = in_place.backup(state, args.backup_dir or [DEFAULT_BACKUP_DIR], the_plan)
    print("backup written and read back:", *paths, sep="\n  ")
    try:
        result = in_place.apply(io, intake, state, new, decision, expected_fingerprint=args.confirm, backup_paths=paths)
    except in_place.RefusedError as e:
        print("REFUSED:", e)
        return 2
    print(json.dumps(result, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
