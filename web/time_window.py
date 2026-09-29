"""
time_window.py

The Home page's time filter -- which reconciliation runs (by
silver.recon_summary.reconciliation_timestamp, i.e. RUN date, not
statement period) the KPI cards, the "N of M statements reconciled" line
and the runs table all cover. Pure date logic, no database access, so it
is testable on its own; web/queries.py's get_home_dashboard() applies the
resulting window as one SQL predicate.

reconciliation_timestamp is DATETIME2 holding UTC wall-clock time with no
offset (fabric_matching.py writes datetime.now(timezone.utc)), and pyodbc
returns it as a naive datetime. Every window here is therefore expressed
as a half-open [start_utc, end_utc) pair of NAIVE UTC datetimes, ready to
bind as parameters. Calendar boundaries (day, month) are US Eastern --
the same zone web/deps.py's friendly_dt() displays -- and are converted to
UTC here in Python, one boundary at a time, so DST is handled by ZoneInfo:
Eastern midnight is 04:00Z under EDT and 05:00Z under EST, which makes the
spring-forward day 23 hours long and the fall-back day 25. (Fabric does
support AT TIME ZONE, but pyodbc cannot read the DATETIMEOFFSET it
returns -- and bound boundaries keep the SQL portable to the SQLite test
backend.) US clocks change at 02:00, so midnight is never ambiguous.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

# Same zone as web/deps.py's EASTERN (friendly_dt()). Defined here too so
# this module stays importable without the web layer's template setup.
EASTERN = ZoneInfo("America/New_York")

# "Last run" = the latest run plus every run chained back from it with no
# gap longer than this. Chosen from live data (2026-09-29): gaps inside one
# batch are almost all under 30 minutes, with a few of 1-2h; 60 minutes
# split that morning's 47-run batch in two, while 2h and 4h agreed. 2h also
# keeps two Sep 25 batches 2h48m apart as separate sessions.
LAST_RUN_GAP = timedelta(hours=2)

RANGES = ("last", "today", "month_current", "all", "date", "month")
DEFAULT_RANGE = "last"

# One microsecond: DATETIME2(6)'s precision, so "ts < latest + 1us" is
# exactly "ts <= latest" while keeping every window half-open.
_ONE_TICK = timedelta(microseconds=1)


@dataclass(frozen=True)
class TimeWindow:
    range: str
    # Naive UTC, half-open [start_utc, end_utc). Both None = no bound
    # ("all"); empty=True = matches nothing ("last" with no runs at all).
    start_utc: Optional[datetime] = None
    end_utc: Optional[datetime] = None
    date: Optional[str] = None    # "YYYY-MM-DD" -- range "date" / "today"
    month: Optional[str] = None   # "YYYY-MM"    -- range "month" / "month_current"
    empty: bool = False

    def sql(self, column: str = "reconciliation_timestamp"):
        """(" AND <predicate>", params) to append to a WHERE clause."""
        if self.empty:
            return " AND 1 = 0", []
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


def last_run_bounds(timestamps, gap: timedelta = LAST_RUN_GAP):
    """(session_start, session_end) for the most recent session, or None
    when there are no runs. `timestamps` may be in any order; a gap of
    exactly `gap` still chains."""
    ordered = sorted((t for t in (to_naive_utc(v) for v in timestamps) if t is not None), reverse=True)
    if not ordered:
        return None
    start = ordered[0]
    for older in ordered[1:]:
        if start - older > gap:
            break
        start = older
    return start, ordered[0]


def month_options(timestamps) -> list:
    """Distinct Eastern "YYYY-MM" months that have at least one run,
    newest first -- the Month dropdown never offers an empty month."""
    months = {to_eastern(t).strftime("%Y-%m") for t in (to_naive_utc(v) for v in timestamps) if t is not None}
    return sorted(months, reverse=True)


def resolve_window(range_: str = None, date_: str = None, month_: str = None, *,
                   timestamps=(), now: datetime = None) -> TimeWindow:
    """URL params -> TimeWindow. ?date= alone implies range=date and
    ?month= alone range=month. Anything unknown or malformed falls back to
    the default ("last"). `now` is injectable for tests only."""
    if not range_:
        range_ = "date" if date_ else "month" if month_ else DEFAULT_RANGE
    if range_ not in RANGES:
        range_ = DEFAULT_RANGE
    now_et = (now or datetime.now(timezone.utc)).astimezone(EASTERN)

    if range_ == "date":
        d = parse_date(date_)
        if d is None:
            return resolve_window(DEFAULT_RANGE, timestamps=timestamps, now=now)
        start, end = day_bounds(d)
        return TimeWindow("date", start, end, date=d.isoformat())

    if range_ == "month":
        ym = parse_month(month_)
        if ym is None:
            return resolve_window(DEFAULT_RANGE, timestamps=timestamps, now=now)
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

    bounds = last_run_bounds(timestamps)
    if bounds is None:
        return TimeWindow("last", empty=True)
    return TimeWindow("last", bounds[0], bounds[1] + _ONE_TICK)


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
    """The window itself, without a count -- e.g. "Last run · Sep 29,
    3:36 AM – 8:08 AM ET", "Today · Sep 29", "September 2026"."""
    if window.range == "all":
        return "All time"
    if window.range == "last":
        if window.empty:
            return "Last run"
        start, end = to_eastern(window.start_utc), to_eastern(window.end_utc - _ONE_TICK)
        if start == end:
            return f"Last run · {_day(start)}, {_clock(start)} ET"
        if start.date() == end.date():
            return f"Last run · {_day(start)}, {_clock(start)} – {_clock(end)} ET"
        return f"Last run · {_day(start)}, {_clock(start)} – {_day(end)}, {_clock(end)} ET"
    if window.range == "today":
        return f"Today · {_day(parse_date(window.date))}"
    if window.range == "date":
        return _day(parse_date(window.date), with_year=True)
    if window.range == "month_current":
        return f"This month · {_month_name(window.month)}"
    return _month_name(window.month)


def window_label(window: TimeWindow, statement_count: int) -> str:
    """window_title() plus the number of statements (runs) in it."""
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
