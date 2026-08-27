"""
deps.py

Shared FastAPI dependencies for the web app: templates (with formatting
filters registered), the login-required dependency, and the sidebar
context (open exceptions count, shown as the nav-dot on "Exceptions").
"""

import os
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
    from web.queries import get_open_exceptions_count, get_pending_review_count
    return {
        "open_exceptions_count": get_open_exceptions_count(),
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


# %m/%d/%y (2-digit year) must come before %m/%d/%Y — Python's %Y accepts a
# bare 2-digit string too (parsing it as year 26 AD, not 2026), so trying
# %m/%d/%Y first on a string like "04/01/26" would silently succeed wrong.
_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%y", "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y", "%d%b%y", "%B %d, %Y", "%b %d, %Y")


def parse_flexible_date(value):
    """Best-effort parse of a date in whatever format the source PDF used —
    returns a date object, or None if nothing matched. Shared by
    friendly_date (display) and queries.get_upload_batch_status (computing
    a statement's actual invoice date range)."""
    if not value:
        return None
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def friendly_date(value):
    """Best-effort reformat of an invoice date to '12 Dec 2025' — vendor
    statement dates arrive in whatever format the source PDF used, so this
    tries the formats seen in practice and falls back to the raw value."""
    if not value:
        return "—"
    parsed = parse_flexible_date(value)
    if parsed:
        return parsed.strftime("%d %b %Y")
    return str(value).strip()


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
templates.env.filters["urlname"] = urlname
