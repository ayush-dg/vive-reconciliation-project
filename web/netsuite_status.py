"""
netsuite_status.py

The small "NetSuite write-back" status shown in the top-right of a statement's
exception review page (no counts in the label -- a number beside one exception
reads as if it were about that exception; the statement-wide breakdown is in the
hover text; the label is "NetSuite write-back", with a tick when it went through): green when the write-back went through, amber when
part of it was blocked, red when something failed, grey when nothing was
written. Pure functions over one netsuite_writeback_run row (see
src/netsuite/log_store.py), so the rules are testable without a database.

A statement with no run at all gets no status (None): the write-back was off
for it, or it predates the log tables, and "not written" would be wrong.
"""

import json

# Badge classes already defined by the app's stylesheet.
SUCCESS, WARNING, DANGER, NEUTRAL = "badge-success", "badge-warning", "badge-danger", "badge-neutral"

# Text colours matching those badges, for places that show the status as a plain line (the vendor cards).
COLOR = {SUCCESS: "var(--success)", WARNING: "var(--warning)", DANGER: "var(--danger)", NEUTRAL: "var(--text-muted)"}

NAME = "NetSuite write-back"

# Must equal src.netsuite.writeback.CAT_NOT_ATTEMPTED (a test checks); repeated
# here so this module stays free of the write-back's heavy imports.
NOT_ATTEMPTED = "not attempted (run stopped early)"


def _counts(run) -> dict:
    try:
        return json.loads(run.get("not_written_counts") or "{}")
    except (TypeError, ValueError):
        return {}


def _tooltip(run, not_written: dict) -> str:
    parts = []
    for key, text in (("written", "{} written"), ("period_locked", "{} period locked"),
                      ("held_by_other", "{} saved first by another statement"), ("failed", "{} failed")):
        if run.get(key):
            parts.append(text.format(run[key]))
    if not_written:
        parts.append("not written: " + ", ".join(f"{n} {reason}" for reason, n in not_written.items()))
    return "Whole statement: " + ("; ".join(parts) or "nothing to write")


def _verdict(run) -> tuple:
    """(css, label, short) for a completed run. `short` is for tight spots
    such as the vendor-card badge."""
    written, failed = run.get("written") or 0, run.get("failed") or 0
    blocked = ((run.get("period_locked") or 0) + (run.get("held_by_other") or 0)
               + (_counts(run).get(NOT_ATTEMPTED) or 0))
    if failed:
        return DANGER, f"{NAME} · failed", "Write-back · failed"
    if written and blocked:
        return WARNING, f"{NAME} · partial", "Write-back · partial"
    if blocked:
        return WARNING, f"{NAME} · not written", "Write-back · not written"
    if written:
        return SUCCESS, NAME, NAME      # the tick beside it says it went through
    return NEUTRAL, f"{NAME} · nothing to write", "Nothing to write"


def writeback_pill(run):
    """The status to show for a statement's latest write-back run, or None
    when there is no run. {"css", "label", "tooltip", "finished_at", "ok"}."""
    if not run:
        return None
    if run.get("outcome") == "failed":
        detail = (run.get("error_message") or "").strip().splitlines()
        return {"css": DANGER, "color": COLOR[DANGER], "label": f"{NAME} · failed", "short": "Write-back · failed",
                "ok": False,
                "tooltip": detail[0][:160] if detail else "the write-back could not run",
                "finished_at": run.get("finished_at")}
    if run.get("outcome") == "reverted":
        # The statement's NetSuite records were cleared after the write-back, so
        # an earlier "written" must not keep showing.
        reverted = _counts(run).get("reverted", 0)
        return {"css": NEUTRAL, "color": COLOR[NEUTRAL], "label": f"{NAME} · reverted",
                "short": "Write-back · reverted", "ok": False,
                "tooltip": f"Whole statement: undone in NetSuite ({reverted} record{'' if reverted == 1 else 's'} cleared)",
                "finished_at": run.get("finished_at")}
    css, label, short = _verdict(run)
    return {"css": css, "color": COLOR[css], "label": label, "short": short, "ok": css == SUCCESS,
            "tooltip": _tooltip(run, _counts(run)), "finished_at": run.get("finished_at")}
