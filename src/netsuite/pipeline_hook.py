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
from src.netsuite.writeback import (
    CAT_LINK_ONLY_FAILED, CAT_PERIOD_LOCKED, PATCH_LINK_ONLY, apply_plans, build_plans, failure_counts,
    skip_counts, write_apply_log,
)

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return os.getenv("NETSUITE_WRITEBACK_ENABLED", "").strip().lower() == "true"


def run_netsuite_writeback(statement_id: str) -> dict:
    """Returns {"skipped": True, "reason": ...}, {"error": ...}, or
    {"written": n, "failed": n, "period_locked": n, "links_added": n, "link_only_failed": n,
    "link_mismatch": n, "not_written": {reason: count}, "log": path}. "failed" excludes
    locked-period failures, which are counted on their own: they are expected for older
    invoices and are not a fault of the run. "written" counts reconciliation results only;
    "links_added" counts link-only writes (a bill that already had this statement's result
    but no PDF link), "link_only_failed" the ones that failed for a reason other than a
    locked period, and "link_mismatch" result writes whose link came back different."""
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
    failures = failure_counts(results)
    locked = failures.pop(CAT_PERIOD_LOCKED, 0)
    link_only_failed = failures.pop(CAT_LINK_ONLY_FAILED, 0)
    return {
        "written": sum(1 for r in results if r.ok and r.plan.action != PATCH_LINK_ONLY),
        "failed": sum(failures.values()),
        "period_locked": locked,
        "links_added": sum(1 for r in results if r.ok and r.plan.action == PATCH_LINK_ONLY),
        "link_only_failed": link_only_failed,
        "link_mismatch": sum(1 for r in results if r.link_mismatch),
        "not_written": skip_counts(plans),
        "log": log_path,
    }
