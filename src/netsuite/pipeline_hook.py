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
from src.netsuite.writeback import apply_plans, build_plans, skip_counts, write_apply_log

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return os.getenv("NETSUITE_WRITEBACK_ENABLED", "").strip().lower() == "true"


def run_netsuite_writeback(statement_id: str) -> dict:
    """Returns {"skipped": True, "reason": ...}, {"error": ...}, or
    {"written": n, "failed": n, "not_written": {reason: count}, "log": path}."""
    if not _enabled():
        return {"skipped": True, "reason": "NETSUITE_WRITEBACK_ENABLED is not true"}
    try:
        ns = NetSuiteClient()
        _, plans = build_plans(statement_id, ns)
        results = apply_plans(ns, plans)
        log_path = write_apply_log(ns, statement_id, results, plans)
    except NetSuiteConfigError as exc:
        return {"skipped": True, "reason": str(exc)}
    except Exception as exc:  # best-effort: never fail the job
        logger.exception("NetSuite write-back failed for %s", statement_id)
        return {"error": f"{type(exc).__name__}: {exc}"}
    failed = sum(1 for r in results if not r.ok)
    return {
        "written": len(results) - failed,
        "failed": failed,
        "not_written": skip_counts(plans),
        "log": log_path,
    }
