"""
user_locations.py

Which VIVE shops each user works (2026-11-09), so Home, Statement Processing
and Exceptions can open on that user's own workload.

- Admins set a user's shops on the Users page; users cannot change their own.
- A user with shops gets a "My locations / All locations" switch on those
  three pages. "My locations" is the default at every login; picking "All
  locations" lasts until logout (kept in the login session, SCOPE_SESSION_KEY),
  the same choice on every page.
- A user with no shops sees everything, as before, and gets no switch.
- "My locations" shows only statements of the user's shops (2026-11-09). A
  statement whose location was never mapped to a shop (unmapped, ambiguous,
  conflict, a failed extraction) is in "All locations" only.

Shops are stored by their name in config/vive_shops.json
(src/validation/shop_list.py), the same name a mapped statement carries as
its shop, so a user's shop and a statement's shop compare directly.

Storage: the user_locations table (migrations/028_add_user_locations.sql;
src/lakehouse/azure_sql_migrations.py for Azure SQL). The app has no
startup migration step, so ensure_table() also creates it on first use.
"""

import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.lakehouse.connection import _using_azure_sql
from src.validation.shop_list import names as shop_names
from web import queries

logger = logging.getLogger(__name__)

SCOPE_SESSION_KEY = "location_scope"
SCOPE_MINE = "mine"
SCOPE_ALL = "all"

_SQLITE_DDL = (
    "CREATE TABLE IF NOT EXISTS user_locations ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " email TEXT NOT NULL,"
    " shop TEXT NOT NULL,"
    " created_at TEXT NOT NULL,"
    " created_by TEXT,"
    " UNIQUE (email, shop))"
)
_AZURE_DDL = (
    "IF OBJECT_ID('user_locations', 'U') IS NULL "
    "CREATE TABLE user_locations ("
    " id INT IDENTITY(1,1) PRIMARY KEY,"
    " email NVARCHAR(255) NOT NULL,"
    " shop NVARCHAR(255) NOT NULL,"
    " created_at NVARCHAR(40) NOT NULL,"
    " created_by NVARCHAR(255),"
    " CONSTRAINT uq_user_locations UNIQUE (email, shop))"
)

_TABLE_READY = {"done": False}
_TABLE_LOCK = threading.Lock()


def ensure_table() -> None:
    """Creates user_locations if it is not there yet (once per process)."""
    if _TABLE_READY["done"]:
        return
    with _TABLE_LOCK:
        if _TABLE_READY["done"]:
            return
        queries.execute_sql(_AZURE_DDL if _using_azure_sql() else _SQLITE_DDL)
        _TABLE_READY["done"] = True


def _key(name) -> str:
    """Case/punctuation-insensitive form of a shop name ("Ben's" == "Ben’s")."""
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def known_shops() -> list:
    """Every shop an admin can pick, sorted by name."""
    return sorted(shop_names(), key=lambda n: n.lower())


def canonical_shops(picked) -> list:
    """The picked names as config/vive_shops.json spells them; unknown names
    and duplicates are dropped, list order follows known_shops()."""
    wanted = {_key(p) for p in (picked or []) if _key(p)}
    return [name for name in known_shops() if _key(name) in wanted]


def get_user_shops(email) -> list:
    """The user's shops, sorted; [] for no shops or any database problem
    (the pages then show everything, as before this feature)."""
    email = (email or "").strip().lower()
    if not email:
        return []
    try:
        ensure_table()
        rows = queries.execute_query("SELECT shop FROM user_locations WHERE email = ?", [email])
    except Exception as error:
        logger.warning("user_locations read failed for %s: %s", email, error)
        return []
    return sorted({r["shop"] for r in rows}, key=lambda n: n.lower())


def all_user_shops() -> dict:
    """{email: [shops]} for every user with shops (the Users page)."""
    try:
        ensure_table()
        rows = queries.execute_query("SELECT email, shop FROM user_locations")
    except Exception as error:
        logger.warning("user_locations read failed: %s", error)
        return {}
    shops = {}
    for r in rows:
        shops.setdefault(r["email"], []).append(r["shop"])
    return {email: sorted(names, key=lambda n: n.lower()) for email, names in shops.items()}


def set_user_shops(email, picked, set_by) -> list:
    """Replaces the user's shops with `picked` (unknown names dropped).
    Returns what was saved. [] clears them: the user then sees everything."""
    email = (email or "").strip().lower()
    shops = canonical_shops(picked)
    ensure_table()
    queries.execute_sql("DELETE FROM user_locations WHERE email = ?", [email])
    now = datetime.now(timezone.utc).isoformat()
    for shop in shops:
        queries.execute_sql(
            "INSERT INTO user_locations (email, shop, created_at, created_by) VALUES (?, ?, ?, ?)",
            [email, shop, now, set_by],
        )
    return shops


def delete_user_shops(email) -> None:
    try:
        ensure_table()
        queries.execute_sql("DELETE FROM user_locations WHERE email = ?", [(email or "").strip().lower()])
    except Exception as error:
        logger.warning("user_locations delete failed for %s: %s", email, error)


@dataclass
class LocationScope:
    """What one page request shows. shops is the user's shops; mine is True
    when the page is narrowed to them (False: "All locations", or a user
    with no shops)."""
    shops: list = field(default_factory=list)
    mine: bool = False
    hidden: int = 0
    unassigned: int = 0
    # This page's path and query, where the switch returns to.
    here: str = "/"

    @property
    def has_shops(self) -> bool:
        return bool(self.shops)

    def apply(self, rows: list) -> list:
        """The rows this scope shows (each row a card/run with "shop" and
        "shop_canonical"): everything in "All", else only the statements of
        the user's shops -- one with no mapped shop is left out. Also counts
        what it hid, and how many of those had no mapped shop."""
        if not self.mine:
            return rows
        wanted = {_key(s) for s in self.shops}
        kept, hidden, unassigned = [], 0, 0
        for row in rows:
            if row.get("shop_canonical") and row.get("shop") and _key(row["shop"]) in wanted:
                kept.append(row)
            else:
                hidden += 1
                if not row.get("shop_canonical") or not row.get("shop"):
                    unassigned += 1
        self.hidden, self.unassigned = hidden, unassigned
        return kept


def location_scope(request, user) -> LocationScope:
    """The scope for this request: the user's shops, narrowed unless they
    chose "All locations" since logging in."""
    shops = get_user_shops(user)
    if not shops:
        return LocationScope()
    session = getattr(request, "session", None) if request is not None else None
    choice = session.get(SCOPE_SESSION_KEY) if isinstance(session, dict) else None
    here = "/"
    if request is not None:
        url = getattr(request, "url", None)
        path, query = getattr(url, "path", None), getattr(url, "query", None)
        if isinstance(path, str):
            here = safe_next(path + (f"?{query}" if isinstance(query, str) and query else ""))
    return LocationScope(shops=shops, mine=choice != SCOPE_ALL, here=here)


def safe_next(path: Optional[str], default: str = "/") -> str:
    """A same-site path to go back to after switching ("/exceptions?x=1");
    anything else (another host, "//evil", blank) becomes `default`."""
    path = (path or "").strip()
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        return default
    return path
