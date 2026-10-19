"""Pipeline entry point for the NetSuite write-back.

Called by scripts/run_full_pipeline.py right after matching succeeds.
Best-effort, same contract as run_fabric_matching(): it NEVER raises, and a
failure here never fails the job -- the caller prints the returned summary.

Off unless NETSUITE_WRITEBACK_ENABLED=true, so nothing writes to NetSuite
until it is switched on per environment. The client itself only accepts a
sandbox account id.
"""
import logging
import os

from src.netsuite.client import NetSuiteClient, NetSuiteConfigError
from src.netsuite.log_store import now_iso, save_failed_run, save_run
from src.netsuite.writeback import (
    CAT_HELD_BY_OTHER, CAT_PERIOD_LOCKED, apply_plans, build_plans, failure_counts, skip_counts,
    write_apply_log, write_error_log,
)

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return os.getenv("NETSUITE_WRITEBACK_ENABLED", "").strip().lower() == "true"


def run_netsuite_writeback(statement_id: str) -> dict:
    """Returns {"skipped": True, "reason": ...}, {"error": ...}, or
    {"written": n, "failed": n, "period_locked": n, "held_by_other": n,
    "not_written": {reason: count}, "log": path}. "failed" excludes locked-period
    failures and bills another statement saved first, which are counted on their
    own: neither is a fault of the run. An {"error": ...} result carries the path
    of its error log under "log"."""
    if not _enabled():
        return {"skipped": True, "reason": "NETSUITE_WRITEBACK_ENABLED is not true"}
    started_at = now_iso()
    try:
        ns = NetSuiteClient()
        _, plans = build_plans(statement_id, ns)
        results = apply_plans(ns, plans)
        log_path = write_apply_log(ns, statement_id, results, plans)
    except NetSuiteConfigError as exc:
        return {"skipped": True, "reason": str(exc)}
    except Exception as exc:  # best-effort: never fail the job
        logger.exception("NetSuite write-back failed for %s", statement_id)
        error_log = write_error_log(statement_id, exc)
        save_failed_run(statement_id, exc, started_at=started_at, log_path=error_log)
        return {"error": f"{type(exc).__name__}: {exc}", "log": error_log}
    save_run(statement_id, results, plans, started_at=started_at, sandbox=ns.domain_id, log_path=log_path)
    failures = failure_counts(results)
    locked = failures.pop(CAT_PERIOD_LOCKED, 0)
    held = failures.pop(CAT_HELD_BY_OTHER, 0)
    return {
        "written": sum(1 for r in results if r.ok),
        "failed": sum(failures.values()),
        "period_locked": locked,
        "held_by_other": held,
        "not_written": skip_counts(plans),
        "log": log_path,
    }
