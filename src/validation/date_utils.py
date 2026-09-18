"""
date_utils.py

Shared date-normalization helper, path-agnostic like arithmetic_gate.py
(kept in its own module rather than folded into arithmetic_gate.py since
this is date logic, not arithmetic validation). The pdfplumber path
already normalizes its own statement_date to ISO YYYY-MM-DD before this
runs (see adapter.py's _normalize_date()), but the Foundry path's raw
statement_date is confirmed inconsistent across vendors ('2026-08-31',
'25AUG26', '07/31/2026', ...) with no normalization today -- this
function derives a canonical "YYYY-MM" statement month from whatever
raw string either path produced, so callers don't need to know which
path's format quirks they're looking at.
"""

from typing import Optional

from dateutil import parser as _dateutil_parser


def normalize_statement_month(raw_date: Optional[str]) -> Optional[str]:
    """Parses `raw_date` (any format either extraction path has produced)
    into a canonical "YYYY-MM" string. Returns None for empty or
    genuinely unparseable input -- never raises, never guesses."""
    if not raw_date:
        return None
    try:
        return _dateutil_parser.parse(raw_date, dayfirst=False).strftime("%Y-%m")
    except (ValueError, OverflowError, TypeError):
        return None
