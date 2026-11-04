"""Re-extract with Claude Opus when a statement fails validation (2026-11-04).

The first extraction (Claude Sonnet 4.6, or a deterministic reader) is
validated as always. When that fails, the PDF is read again by Claude Opus
5.5 (config/ai/claude_opus_extraction.json) and validated again -- at most
OPUS_ATTEMPTS times. The first passing read is kept. If every read fails,
the statement fails validation as before, with the LAST read that returned
rows (an Opus read that returns nothing never replaces an earlier read).

Why: extraction is not deterministic. On 2026-11-04 the same Nashua Kia PDF
passed in dev and failed in prod a minute apart, because one run put the
payment rows' amounts under BALANCE instead of PAYMENTS & CREDITS.

Retried: any validation status other than "matches" (a pass) and
"not_a_statement" (no line-item table -- not a failure), and no status at
all (validation never ran). Every read is
recorded in validation["detail"]["extraction_attempts"] ([{"attempt",
"model", "status", "difference"}]) so the statement page can say which
model read it and after how many tries.

Switched on by EXTRACTION_OPUS_RETRY_ENABLED=true (off when unset). An Opus
read is not started once the job has run OPUS_START_DEADLINE_SECONDS, so the
retries cannot push a job past the worker's 1800 s cap
(web/worker.py PIPELINE_TIMEOUT_SECONDS); the statement then fails as today.
"""
import os
import time
from typing import Callable, Optional

OPUS_PROVIDER = "claude_opus"
OPUS_ATTEMPTS = 2
OPUS_START_DEADLINE_SECONDS = 1000
NOT_RETRIED = ("matches", "not_a_statement")


def enabled() -> bool:
    return os.environ.get("EXTRACTION_OPUS_RETRY_ENABLED", "").strip().lower() == "true"


def _record(attempt: int, schema_result: dict) -> dict:
    validation = schema_result.get("validation") or {}
    return {"attempt": attempt, "model": schema_result.get("_model_used") or schema_result.get("_provider_used"),
            "status": validation.get("status"), "difference": validation.get("difference")}


def _attach(schema_result: dict, attempts: list) -> dict:
    validation = schema_result.setdefault("validation", {})
    validation["detail"] = {**(validation.get("detail") or {}), "extraction_attempts": attempts}
    return schema_result


def retry_on_validation_failure(schema_result: dict, extract: Callable[[], Optional[dict]],
                                validate: Callable[[dict], dict], started: float = None,
                                clock: Callable[[], float] = time.monotonic) -> dict:
    """Returns the schema_result to keep.

    extract():  one Opus read -> schema dict, or None when it read nothing.
    validate(s): runs the validation gate on s (sets s["validation"]).
    started:    clock() when the job's extraction began (for the deadline)."""
    status = (schema_result.get("validation") or {}).get("status")
    if not enabled() or not status or status in NOT_RETRIED:
        return schema_result
    attempts = [_record(1, schema_result)]
    kept = schema_result
    for n in range(1, OPUS_ATTEMPTS + 1):
        if started is not None and clock() - started > OPUS_START_DEADLINE_SECONDS:
            print(f"  [Opus retry] Not starting Opus try {n}: the job has run "
                  f"{clock() - started:.0f}s (limit {OPUS_START_DEADLINE_SECONDS}s)")
            attempts.append({"attempt": n + 1, "model": None, "status": "skipped_time_limit", "difference": None})
            break
        print(f"\n  [Opus retry] Validation {status} -- re-extracting with Claude Opus (try {n} of {OPUS_ATTEMPTS})")
        candidate = extract()
        if candidate is None:
            attempts.append({"attempt": n + 1, "model": OPUS_PROVIDER, "status": "no_rows", "difference": None})
            continue
        validate(candidate)
        attempts.append(_record(n + 1, candidate))
        kept = candidate
        status = (candidate.get("validation") or {}).get("status")
        if status == "matches":
            print(f"  [Opus retry] Opus try {n} passed validation")
            break
    else:
        print(f"  [Opus retry] All {OPUS_ATTEMPTS} Opus tries failed validation -- the statement fails validation")
    return _attach(kept, attempts)
