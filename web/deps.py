"""
deps.py

Shared FastAPI dependencies for the web app: templates (with formatting
filters registered), the login-required dependency, and the sidebar
context (open exceptions count, shown as the nav-dot on "Exceptions").
"""

import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import Request
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


class LoginRequired(Exception):
    """Raised by require_login when no session user is present; caught by
    an app-level exception handler that redirects to /login."""


def require_login(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise LoginRequired()
    return user


def sidebar_context(request: Request) -> dict:
    from web.queries import get_open_recon_exceptions_count, get_pending_review_count
    return {
        "open_exceptions_count": get_open_recon_exceptions_count(),
        "pending_review_count": get_pending_review_count(),
        "user_email": request.session.get("user"),
        "user_name": request.session.get("user_name") or request.session.get("user") or "",
    }


def render(request: Request, name: str, ctx: dict = None, status_code: int = 200):
    return templates.TemplateResponse(request, name, ctx or {}, status_code=status_code)


# ---------------------------------------------------------------------------
# Template filters
# ---------------------------------------------------------------------------

def money(value, decimals=2):
    if value is None:
        return "$0.00" if decimals else "$0"
    return f"${float(value):,.{decimals}f}"


def money_signed(value):
    if value is None:
        return "$0.00"
    v = float(value)
    sign = "−" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


def money_short(value):
    if value is None:
        return "$0"
    v = float(value)
    if abs(v) >= 1000:
        return f"${v / 1000:,.1f}K"
    return f"${v:,.0f}"


def period_label(period_str):
    if not period_str:
        return "—"
    try:
        dt = datetime.strptime(period_str, "%Y-%m")
        return dt.strftime("%b %Y")
    except ValueError:
        return period_str


def initials(name):
    if not name:
        return "??"
    words = [w for w in name.replace("/", " ").replace(",", " ").split() if w.isalpha()]
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    if words:
        return words[0][:2].upper()
    return name[:2].upper()


_US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV",
    "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN",
    "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC", "PR", "VI", "GU",
}


def smart_title(value):
    """Normalizes a vendor/shop/location string to proper title case --
    display-only, never touches stored data. Source text is printed
    however each vendor's own PDF happened to print it (some ALL CAPS,
    some all lowercase, rarely already proper case), which looks
    inconsistent side by side on a card grid.

    Plain str.title() mishandles apostrophes (OLIVER'S -> "Oliver'S", not
    "Oliver's") since it treats the character after an apostrophe as a
    new word boundary -- tracked here explicitly instead: capitalize the
    first letter after start-of-string or whitespace/hyphen/slash/
    parens/comma, but never after an apostrophe.

    A standalone 2-letter token matching a real US state code (e.g. the
    "RI" in "North Kingstown, RI") is kept fully uppercase rather than
    title-cased to "Ri" -- title-casing a state abbreviation reads as a
    mistake to anyone who recognizes postal codes, the opposite of the
    "look professional" goal this exists for."""
    if not value:
        return value
    result = []
    capitalize_next = True
    for ch in value:
        if ch.isalpha():
            result.append(ch.upper() if capitalize_next else ch.lower())
            capitalize_next = False
        else:
            result.append(ch)
            capitalize_next = ch != "'"
    titled = "".join(result)
    # Second pass, on the already-title-cased string: a standalone
    # 2-letter token (word boundary on both sides, so this never touches
    # a 2-letter substring inside a longer word) that's a real state code
    # gets uppercased back -- done as a separate pass rather than folded
    # into the loop above, since the loop processes one character at a
    # time with no lookahead to know a 2-letter word is coming.
    return re.sub(
        r"\b[A-Za-z]{2}\b",
        lambda m: m.group(0).upper() if m.group(0).upper() in _US_STATE_CODES else m.group(0),
        titled,
    )


def location_group_key(value):
    """Canonicalization key for grouping billing_location strings that
    refer to the same place but were extracted with different punctuation/
    spacing -- e.g. "Springfield, MA" vs "Springfield MA" vs "SPRINGFIELD,
    MA" (confirmed live 2026-09-22: the same location showing up as
    multiple separate entries in the Exceptions page's location filter,
    since billing_location has no alias/normalization system the way
    vendor_name does via config/vendor_aliases.json -- see
    web/routers/exceptions.py's grouping pass that uses this).

    Deliberately looser than smart_title() (which is display-only and
    preserves punctuation): uppercases, drops commas/periods entirely, and
    collapses whitespace, so "Springfield, MA" and "Springfield MA" land
    on the identical key while still being sorted/deduped consistently."""
    if not value:
        return value
    collapsed = re.sub(r"[,\.]", "", value).strip()
    collapsed = re.sub(r"\s+", " ", collapsed)
    return collapsed.upper()


_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y")


def friendly_date(value):
    """Best-effort reformat of an invoice date to '12 Dec 2025' — vendor
    statement dates arrive in whatever format the source PDF used, so this
    tries the formats seen in practice and falls back to the raw value."""
    if not value:
        return "—"
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%d %b %Y")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%d %b %Y")
    except ValueError:
        return text


IST = timezone(timedelta(hours=5, minutes=30))


def friendly_dt(iso_str):
    """All timestamps are stored as UTC (see queries.py/resolve_exception
    etc., which write datetime.now(timezone.utc).isoformat()) — this
    converts to IST for display, since that's the app's audience."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
    except ValueError:
        return str(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(IST)
    now = datetime.now(timezone.utc).astimezone(IST)
    hour12 = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    time_part = f"{hour12}:{dt.minute:02d} {ampm}"
    if dt.date() == now.date():
        return f"Today, {time_part}"
    return f"{dt.strftime('%b %d, %Y')}, {time_part}"


def friendly_error(raw):
    """A failed job's error_message can be a full stdout+traceback dump up
    to 4000 characters (see worker.py's _run_job()) -- showing the first
    ~200 chars of that (as the UI used to) just shows the pipeline's
    opening "FULL RECONCILIATION PIPELINE" banner, not the actual failure,
    since that banner is always printed first. The real explanation is
    always at the END of captured output, never the start: for an
    uncaught exception it's the traceback's final "ExceptionType: message"
    line; for worker.py's own short messages ("Pipeline exited with no
    output.", "Worker error: ...") it's simply the whole (already short,
    already clean) string. Truncated defensively in case a message has no
    newlines and is itself very long."""
    if not raw:
        return ""
    lines = [line for line in str(raw).strip().splitlines() if line.strip()]
    if not lines:
        return ""
    return lines[-1].strip()[:300]


def urlname(value):
    """Fully percent-encodes a value (including '/') for use as a single
    path segment — vendor names can contain slashes (e.g. "Tekion / Vinart")
    that must not be read as path separators."""
    return quote(str(value or ""), safe="")


templates.env.filters["money"] = money
templates.env.filters["money_signed"] = money_signed
templates.env.filters["money_short"] = money_short
templates.env.filters["period_label"] = period_label
templates.env.filters["initials"] = initials
templates.env.filters["friendly_dt"] = friendly_dt
templates.env.filters["friendly_date"] = friendly_date
templates.env.filters["friendly_error"] = friendly_error
templates.env.filters["urlname"] = urlname
templates.env.filters["smart_title"] = smart_title
