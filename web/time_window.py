"""
time_window.py

The Home page's time filter -- which statements (by
silver.recon_summary.statement_id) the KPI cards, the "N of M statements
reconciled" line and the runs table all cover. Pure date/grouping logic,
no database access, so it is testable on its own; web/queries.py's
get_home_dashboard() applies the resulting window, and
web/routers/validation.py reuses the "last" (Outlook) piece for its own
"Last run" filter.

Two different kinds of window:

- Calendar-bounded (today/date/month/month_current/all): a half-open
  [start_utc, end_utc) pair of NAIVE UTC datetimes, checked in SQL against
  silver.recon_summary.reconciliation_timestamp (RUN date, not statement
  period) -- DATETIME2 holding UTC wall-clock time with no offset
  (fabric_matching.py writes datetime.now(timezone.utc)), returned by
  pyodbc as a naive datetime. Calendar boundaries (day, month) are US
  Eastern -- the same zone web/deps.py's friendly_dt() displays -- and are
  converted to UTC here in Python, one boundary at a time, so DST is
  handled by ZoneInfo: Eastern midnight is 04:00Z under EDT and 05:00Z
  under EST, which makes the spring-forward day 23 hours long and the
  fall-back day 25. (Fabric does support AT TIME ZONE, but pyodbc cannot
  read the DATETIMEOFFSET it returns -- and bound boundaries keep the SQL
  portable to the SQLite test backend.) US clocks change at 02:00, so
  midnight is never ambiguous.
- "last" (redefined 2026-09-30): NOT calendar-bounded at all -- "the most
  recent Outlook mailbox sync" is a set of statement_ids (see
  outlook_last_sync()), checked by Python-side membership rather than a
  SQL predicate, since jobs (Azure SQL/SQLite) and silver.recon_summary
  (Fabric) are different database engines with no join available.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

# Same zone as web/deps.py's EASTERN (friendly_dt()). Defined here too so
# this module stays importable without the web layer's template setup.
EASTERN = ZoneInfo("America/New_York")

# "Last run" (redefined 2026-09-30) = the most recent Outlook mailbox
# sync: the newest job with source_blob_path set (see
# queries.get_outlook_synced_jobs() -- only web/routers/mailbox_sync.py's
# "Sync to Webapp" ever sets that column; manual uploads, the dropzone
# watcher and Event Grid never do), plus every such job chained back from
# it with no gap longer than this. One "Sync to Webapp" click queues all
# its jobs in a single synchronous loop (download-then-create_job per
# blob), so gaps inside one click are seconds, not hours; 10 minutes
# comfortably covers slow per-file downloads within one click while still
# separating two distinct clicks minutes apart.
OUTLOOK_SYNC_GAP = timedelta(minutes=10)

RANGES = ("last", "today", "month_current", "all", "date", "month")
DEFAULT_RANGE = "last"


@dataclass(frozen=True)
class TimeWindow:
    range: str
    # Naive UTC, half-open [start_utc, end_utc). Both None = no bound
    # ("all"); empty=True = matches nothing (an empty window: "last" with
    # no Outlook jobs at all).
    start_utc: Optional[datetime] = None
    end_utc: Optional[datetime] = None
    date: Optional[str] = None    # "YYYY-MM-DD" -- range "date" / "today"
    month: Optional[str] = None   # "YYYY-MM"    -- range "month" / "month_current"
    empty: bool = False
    # "last" only (redefined 2026-09-30 as "the most recent Outlook sync",
    # not a time-gap on reconciliation runs -- see outlook_last_sync()):
    # the statement_ids that sync's jobs produced (checked by Python-side
    # membership, not SQL -- see .sql()), that sync's own queued-job count
    # and its jobs counted by status (for the "572 statements (568
    # completed, 4 failed)" label -- see sync_status_counts()) and the
    # newest of its jobs' submitted_at (the label's timestamp).
    statement_ids: Optional[frozenset] = None
    sync_time_utc: Optional[datetime] = None
    sync_job_count: int = 0
    sync_completed: int = 0
    sync_failed: int = 0
    sync_processing: int = 0

    def sql(self, column: str = "reconciliation_timestamp"):
        """(" AND <predicate>", params) to append to a WHERE clause."""
        if self.empty:
            return " AND 1 = 0", []
        if self.statement_ids is not None:
            # Membership is checked in Python by the caller (see
            # queries.get_home_dashboard()) -- jobs (Azure SQL/SQLite) and
            # recon_summary (Fabric) are different engines with no single
            # join available, and reading the whole (modest) table and
            # filtering in Python avoids ever needing a bound IN-list
            # (and its 2100-parameter cap).
            return "", []
        if self.start_utc is None:
            return "", []
        return f" AND {column} >= ? AND {column} < ?", [self.start_utc, self.end_utc]


def to_naive_utc(value) -> Optional[datetime]:
    """A timestamp value as returned by either backend (naive UTC
    datetime from pyodbc, or an ISO string from SQLite) -> naive UTC."""
    if value is None or value == "":
        return None
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _eastern_midnight_as_utc(d: date) -> datetime:
    return datetime.combine(d, time.min, EASTERN).astimezone(timezone.utc).replace(tzinfo=None)


def day_bounds(d: date):
    return _eastern_midnight_as_utc(d), _eastern_midnight_as_utc(d + timedelta(days=1))


def month_bounds(year: int, month: int):
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return _eastern_midnight_as_utc(date(year, month, 1)), _eastern_midnight_as_utc(date(next_year, next_month, 1))


def parse_date(value) -> Optional[date]:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def parse_month(value):
    try:
        dt = datetime.strptime(str(value), "%Y-%m")
        return dt.year, dt.month
    except (TypeError, ValueError):
        return None


def to_eastern(naive_utc: datetime) -> datetime:
    return naive_utc.replace(tzinfo=timezone.utc).astimezone(EASTERN)


MAX_SYNC_OPTIONS = 30

# jobs.status values that mean a job is still in flight -- the only
# statuses web/queries.py ever writes are PENDING (create_job()),
# PROCESSING (claim_next_pending_job()), COMPLETED and FAILED
# (update_job_status() via web/worker.py).
IN_FLIGHT_STATUSES = frozenset({"PENDING", "PROCESSING"})


def sync_status_counts(chain) -> tuple:
    """(completed, failed, still_processing) for one sync's jobs, by
    jobs.status alone (2026-10-06). Until then "still processing" was
    every job without a silver.recon_summary row, so a finished sync
    with no job left in flight still read "481 of 572 statements (91
    still processing)" on dev for the Oct 1 sync: 87 cache hits (a
    byte-identical PDF already extracted, which completes without a
    recon_summary row of its own) plus 4 failed jobs. A cache hit counts
    as completed here; a FAILED job as failed, with or without a
    statement_id."""
    processing = sum(1 for j in chain if j.get("status") in IN_FLIGHT_STATUSES)
    failed = sum(1 for j in chain if j.get("status") == "FAILED")
    return len(chain) - processing - failed, failed, processing


def sync_count_text(completed: int, failed: int, processing: int) -> str:
    """"572 statements", or "572 statements (568 completed, 4 failed)"
    once anything failed or is still in flight -- zero counts left out,
    e.g. "3 statements (3 still processing)". Shared by the window label
    and the Past syncs dropdown so the two never disagree."""
    total = completed + failed + processing
    text = f"{total:,} statement{'s' if total != 1 else ''}"
    if not failed and not processing:
        return text
    parts = [f"{n:,} {word}" for n, word in ((completed, "completed"), (failed, "failed"),
                                             (processing, "still processing")) if n]
    return f"{text} ({', '.join(parts)})"


def outlook_all_syncs(jobs, gap: timedelta = OUTLOOK_SYNC_GAP) -> list:
    """jobs: dicts with "submitted_at" (any shape to_naive_utc accepts),
    "statement_id" (may be None -- extraction/matching hasn't produced
    one yet, or the job failed before it did) and "status" (see
    sync_status_counts()) -- see queries.get_outlook_synced_jobs(), already
    scoped to source_blob_path IS NOT NULL, so a manual upload, a
    dropzone-watcher job or an Event Grid job is never even in `jobs` to
    begin with; nothing here needs to re-check their origin.

    Returns EVERY Outlook sync (not just the newest -- see
    outlook_last_sync()), newest first: a list of chains, each chain a
    list of job dicts (newest job first within it). A gap of exactly
    `gap` still chains. A "Sync to Webapp" click that queued 0 PDFs
    creates zero job rows, so it's simply invisible here -- it never
    produces an empty chain. Added 2026-09-30 for the "Last run"
    dropdown (web/routers/dashboard.py, exceptions.py, validation.py) --
    see outlook_sync_options() and resolve_window()'s `sync_` param."""
    ordered = sorted(
        (dict(j, submitted_at=to_naive_utc(j["submitted_at"])) for j in jobs if j.get("submitted_at") is not None),
        key=lambda j: j["submitted_at"], reverse=True,
    )
    syncs = []
    chain = []
    for j in ordered:
        if chain and chain[-1]["submitted_at"] - j["submitted_at"] > gap:
            syncs.append(chain)
            chain = []
        chain.append(j)
    if chain:
        syncs.append(chain)
    return syncs


def outlook_last_sync(jobs, gap: timedelta = OUTLOOK_SYNC_GAP):
    """The single newest Outlook sync -- see outlook_all_syncs() for the
    full list (every sync, not just this one). Returns the winning chain
    (list of job dicts, newest first) or None if `jobs` is empty."""
    syncs = outlook_all_syncs(jobs, gap)
    return syncs[0] if syncs else None


def outlook_sync_options(jobs, cap: int = MAX_SYNC_OPTIONS, gap: timedelta = OUTLOOK_SYNC_GAP):
    """The "Last run" dropdown's options (Home, Exceptions, Validation) --
    every Outlook sync (outlook_all_syncs()), newest first, capped at
    `cap` so the <select> stays a reasonable size. A bookmarked ?sync=
    for a sync older than this cap still resolves correctly --
    resolve_window() always searches the FULL (uncapped) list, so
    truncating this display list never breaks a direct link to an older
    sync, only hides it from the dropdown itself.

    Returns (options, truncated): `options` is a newest-first list of
    {"value": <UTC ISO "Z" string of that sync's newest job -- the
    exact ?sync= a <select> submits, and what resolve_window() parses
    back via to_naive_utc()>, "label": <"Sep 29, 7:02 AM ET · 12
    statements", or "12 statements (11 completed, 1 failed)" when any
    of that sync's jobs failed or are still in flight -- same
    sync_count_text() wording as window_label()>}. `truncated` is True
    when more syncs exist than `cap` allowed through (the caller shows a
    trailing disabled "older syncs not shown" option)."""
    syncs = outlook_all_syncs(jobs, gap)
    truncated = len(syncs) > cap
    options = []
    for chain in syncs[:cap]:
        t = to_eastern(chain[0]["submitted_at"])
        options.append({
            "value": chain[0]["submitted_at"].isoformat() + "Z",
            "label": f"{_day(t)}, {_clock(t)} ET · {sync_count_text(*sync_status_counts(chain))}",
        })
    return options, truncated


def month_options(timestamps) -> list:
    """Distinct Eastern "YYYY-MM" months that have at least one run,
    newest first -- the Month dropdown never offers an empty month."""
    months = {to_eastern(t).strftime("%Y-%m") for t in (to_naive_utc(v) for v in timestamps) if t is not None}
    return sorted(months, reverse=True)


def resolve_window(range_: str = None, date_: str = None, month_: str = None, *,
                   timestamps=(), outlook_jobs=(), now: datetime = None, sync_: str = None) -> TimeWindow:
    """URL params -> TimeWindow. ?date= alone implies range=date and
    ?month= alone range=month. Anything unknown or malformed falls back to
    the default ("last"). `now` is injectable for tests only.

    `timestamps` (silver.recon_summary run timestamps, via
    queries.get_run_timestamps()) drives the Month dropdown's options
    only -- unrelated to "last" since 2026-09-30. `outlook_jobs` (via
    queries.get_outlook_synced_jobs()) is what "last" is built from now
    -- see outlook_all_syncs().

    `sync_` (added 2026-09-30, the "Last run" dropdown's ?sync=) picks
    one specific Outlook sync by its newest job's UTC ISO timestamp
    (outlook_sync_options()'s own "value") out of the FULL sync list --
    never just the capped/displayed one, so a bookmark to a sync older
    than the dropdown's cap still resolves. Unset, unparseable, or
    matching no known sync all fall back to the latest sync with no
    error -- same permissive posture as an unknown `range_`."""
    if not range_:
        range_ = "date" if date_ else "month" if month_ else DEFAULT_RANGE
    if range_ not in RANGES:
        range_ = DEFAULT_RANGE
    now_et = (now or datetime.now(timezone.utc)).astimezone(EASTERN)

    if range_ == "date":
        d = parse_date(date_)
        if d is None:
            return resolve_window(DEFAULT_RANGE, timestamps=timestamps, outlook_jobs=outlook_jobs, now=now, sync_=sync_)
        start, end = day_bounds(d)
        return TimeWindow("date", start, end, date=d.isoformat())

    if range_ == "month":
        ym = parse_month(month_)
        if ym is None:
            return resolve_window(DEFAULT_RANGE, timestamps=timestamps, outlook_jobs=outlook_jobs, now=now, sync_=sync_)
        start, end = month_bounds(*ym)
        return TimeWindow("month", start, end, month=f"{ym[0]:04d}-{ym[1]:02d}")

    if range_ == "today":
        start, end = day_bounds(now_et.date())
        return TimeWindow("today", start, end, date=now_et.date().isoformat())

    if range_ == "month_current":
        start, end = month_bounds(now_et.year, now_et.month)
        return TimeWindow("month_current", start, end, month=now_et.strftime("%Y-%m"))

    if range_ == "all":
        return TimeWindow("all")

    all_syncs = outlook_all_syncs(outlook_jobs)
    if not all_syncs:
        return TimeWindow("last", empty=True)
    chain = all_syncs[0]
    if sync_:
        try:
            target = to_naive_utc(sync_)
        except (ValueError, TypeError):
            target = None
        if target is not None:
            for candidate in all_syncs:
                if candidate[0]["submitted_at"] == target:
                    chain = candidate
                    break
    ids = frozenset(j["statement_id"] for j in chain if j.get("statement_id"))
    completed, failed, processing = sync_status_counts(chain)
    return TimeWindow("last", statement_ids=ids, sync_time_utc=chain[0]["submitted_at"], sync_job_count=len(chain),
                      sync_completed=completed, sync_failed=failed, sync_processing=processing)


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

def _clock(dt: datetime) -> str:
    return f"{dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def _day(dt, with_year=False) -> str:
    return f"{dt:%b} {dt.day}" + (f", {dt.year}" if with_year else "")


def _month_name(ym: str) -> str:
    y, m = parse_month(ym)
    return date(y, m, 1).strftime("%B %Y")


def window_title(window: TimeWindow) -> str:
    """The window itself, without a count -- e.g. "Last sync · Sep 29,
    7:02 AM ET", "Today · Sep 29", "September 2026". ("Last Outlook
    sync" until 2026-10-06; the top bar's "Outlook: <time>" badge is
    what names Outlook now.)"""
    if window.range == "all":
        return "All time"
    if window.range == "last":
        if window.empty:
            return "Last sync"
        t = to_eastern(window.sync_time_utc)
        return f"Last sync · {_day(t)}, {_clock(t)} ET"
    if window.range == "today":
        return f"Today · {_day(parse_date(window.date))}"
    if window.range == "date":
        return _day(parse_date(window.date), with_year=True)
    if window.range == "month_current":
        return f"This month · {_month_name(window.month)}"
    return _month_name(window.month)


def window_label(window: TimeWindow, statement_count: int) -> str:
    """window_title() plus the number of statements in it. For "last" the
    count is the sync's own jobs by status (sync_count_text()), and
    `statement_count` (the window's silver.recon_summary rows) is not
    used: a cache-hit job completes without a recon_summary row of its
    own, so comparing the two misreported finished jobs as "still
    processing" -- see sync_status_counts()."""
    if window.range == "last" and not window.empty:
        return (f"{window_title(window)} · "
                f"{sync_count_text(window.sync_completed, window.sync_failed, window.sync_processing)}")
    if statement_count:
        return f"{window_title(window)} · {statement_count:,} statement{'s' if statement_count != 1 else ''}"
    return f"{window_title(window)} · no runs{' yet' if window.range in ('today', 'month_current') else ''}"


def window_short(window: TimeWindow) -> str:
    """Lower-case phrase for the KPI cards' sub-labels."""
    if window.range == "date":
        return _day(parse_date(window.date), with_year=True)
    if window.range == "month":
        return _month_name(window.month)
    return {"last": "last run", "today": "today", "month_current": "this month", "all": "all time"}[window.range]


def empty_message(window: TimeWindow) -> str:
    """The runs panel's message when the window itself has no runs."""
    if window.range == "today":
        return "No reconciliation runs today yet."
    if window.range == "month_current":
        return "No reconciliation runs this month yet."
    if window.range == "date":
        return f"No reconciliation runs on {_day(parse_date(window.date), with_year=True)}."
    if window.range == "month":
        return f"No reconciliation runs in {_month_name(window.month)}."
    return "No reconciliation runs yet — upload a vendor statement to get started."
