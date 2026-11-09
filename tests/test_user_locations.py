"""
tests/test_user_locations.py

"My locations" (2026-11-09, web/user_locations.py): admins set the VIVE shops
each user works; Home, Statement Processing and Exceptions then open on that
user's shops only, with a switch to "All locations" (which also has the
statements matched to no shop). A user with no shops sees everything.
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from src.lakehouse import connection
from web import queries
from web import user_locations as ul
from web.deps import require_login
from web.routers import users


def _row(shop, canonical=True, **extra):
    return {"shop": shop, "shop_canonical": canonical, **extra}


class _TempDb(unittest.TestCase):
    """A throwaway SQLite database behind web.queries (the table is created by
    ensure_table(), as on a database the migration has not reached)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="user_locations_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        db = os.path.join(self.dir, "test.db")
        sqlite3.connect(db).close()
        for patcher in (mock.patch.object(connection, "DB_PATH", db),
                        mock.patch.dict(os.environ, {"AZURE_SQL_SERVER": ""}),
                        mock.patch.dict(ul._TABLE_READY, {"done": False})):
            patcher.start()
            self.addCleanup(patcher.stop)


class StorageTests(_TempDb):
    def test_saves_reads_and_replaces_a_users_shops(self):
        saved = ul.set_user_shops(" Erin@Vivecollision.com ", ["Albany", "Don Joe", "Englishtown"], set_by="admin")
        self.assertEqual(saved, ["Albany", "Don Joe", "Englishtown"])
        self.assertEqual(ul.get_user_shops("erin@vivecollision.com"), ["Albany", "Don Joe", "Englishtown"])

        ul.set_user_shops("erin@vivecollision.com", ["Klapec"], set_by="admin")
        self.assertEqual(ul.get_user_shops("erin@vivecollision.com"), ["Klapec"])

    def test_names_are_spelled_as_the_shop_list_and_unknown_ones_dropped(self):
        saved = ul.set_user_shops("m@v.com", ["neet's", "Jake’s", "PRESTIGE - NH", "Nowhere", "Klapec", "klapec"],
                                  set_by="admin")
        self.assertEqual(saved, ["Jake's", "Klapec", "Neet's", "Prestige - NH"])

    def test_clearing_and_deleting_leave_no_shops(self):
        ul.set_user_shops("a@v.com", ["Vestal"], set_by="admin")
        ul.set_user_shops("b@v.com", ["Owego", "Keene"], set_by="admin")
        ul.set_user_shops("a@v.com", [], set_by="admin")
        self.assertEqual(ul.get_user_shops("a@v.com"), [])
        self.assertEqual(ul.all_user_shops(), {"b@v.com": ["Keene", "Owego"]})
        ul.delete_user_shops("B@v.com")
        self.assertEqual(ul.all_user_shops(), {})

    def test_a_database_problem_means_no_shops_not_a_broken_page(self):
        with mock.patch("web.queries.execute_query", side_effect=sqlite3.OperationalError("boom")):
            self.assertEqual(ul.get_user_shops("a@v.com"), [])
            self.assertEqual(ul.all_user_shops(), {})


class ScopeTests(unittest.TestCase):
    ROWS = [_row("Vestal", statement_id="1"), _row("Owego", statement_id="2"),
            _row("some raw text", canonical=False, statement_id="3"), _row(None, canonical=False, statement_id="4"),
            _row("Norwich", statement_id="5")]

    def test_mine_keeps_only_the_users_shops(self):
        scope = ul.LocationScope(shops=["Vestal", "Norwich"], mine=True)
        kept = scope.apply(list(self.ROWS))
        self.assertEqual([r["statement_id"] for r in kept], ["1", "5"])
        self.assertEqual((scope.hidden, scope.unassigned), (3, 2))

    def test_shop_names_compare_without_case_or_apostrophe_differences(self):
        scope = ul.LocationScope(shops=["Ben's"], mine=True)
        self.assertEqual(len(scope.apply([_row("BEN’S")])), 1)

    def test_all_and_no_shops_keep_everything(self):
        self.assertEqual(ul.LocationScope(shops=["Vestal"], mine=False).apply(list(self.ROWS)), self.ROWS)
        self.assertEqual(ul.LocationScope().apply(list(self.ROWS)), self.ROWS)

    def test_the_session_picks_all_otherwise_mine(self):
        request = mock.Mock(session={})
        with mock.patch.object(ul, "get_user_shops", return_value=["Vestal"]):
            self.assertTrue(ul.location_scope(request, "u@v.com").mine)
            request.session = {ul.SCOPE_SESSION_KEY: "all"}
            self.assertFalse(ul.location_scope(request, "u@v.com").mine)
        with mock.patch.object(ul, "get_user_shops", return_value=[]):
            scope = ul.location_scope(mock.Mock(session={}), "u@v.com")
            self.assertFalse(scope.mine)
            self.assertFalse(scope.has_shops)

    def test_the_scope_knows_the_page_to_return_to(self):
        request = mock.Mock(session={})
        request.url.path, request.url.query = "/exceptions", "range=all"
        with mock.patch.object(ul, "get_user_shops", return_value=["Vestal"]):
            self.assertEqual(ul.location_scope(request, "u@v.com").here, "/exceptions?range=all")

    def test_safe_next_only_goes_back_to_this_site(self):
        self.assertEqual(ul.safe_next("/exceptions?range=all"), "/exceptions?range=all")
        for bad in ("https://evil.example", "//evil.example", "/\\evil", "", None):
            self.assertEqual(ul.safe_next(bad), "/")


class HomeScopeTests(unittest.TestCase):
    """The Home cards, the N of M line and the table all follow the scope."""

    RUNS = [
        {"statement_id": "S1", "vendor_name": "A", "statement_period": None, "total_invoice_count": 10,
         "matched_count": 8, "exception_count": 2, "statement_total": 100, "overall_status": "x",
         "reconciliation_timestamp": "2026-11-01"},
        {"statement_id": "S2", "vendor_name": "B", "statement_period": None, "total_invoice_count": 5,
         "matched_count": 5, "exception_count": 0, "statement_total": 50, "overall_status": "x",
         "reconciliation_timestamp": "2026-11-02"},
        {"statement_id": "S3", "vendor_name": "C", "statement_period": None, "total_invoice_count": 4,
         "matched_count": 1, "exception_count": 3, "statement_total": 40, "overall_status": "x",
         "reconciliation_timestamp": "2026-11-03"},
    ]
    SHOPS = {"S1": ("Vestal", True), "S2": ("Owego", True), "S3": ("raw shop", False)}

    def _home(self, scope):
        def attach(rows, ids=None):
            for r in rows:
                r["shop"], r["shop_canonical"] = self.SHOPS[r["statement_id"]]
        with mock.patch.object(queries, "recon_query", return_value=[dict(r) for r in self.RUNS]), \
                mock.patch.object(queries, "_attach_intake_period_and_shop", side_effect=attach), \
                mock.patch.object(queries, "_attach_job_ids_and_display_names"):
            return queries.get_home_dashboard(window=None, scope=scope)

    def test_my_locations_counts_only_my_shops(self):
        data = self._home(ul.LocationScope(shops=["Vestal"], mine=True))
        self.assertEqual({r["statement_id"] for r in data["runs"]}, {"S1"})
        self.assertEqual(data["kpis"]["total_invoices"], 10)
        self.assertEqual(data["kpis"]["open_exceptions"], 2)
        self.assertEqual(data["statement_count"], 1)

    def test_all_locations_is_unchanged(self):
        data = self._home(ul.LocationScope(shops=["Vestal"], mine=False))
        self.assertEqual(data["statement_count"], 3)
        self.assertEqual(data["kpis"]["total_invoices"], 19)


class UsersPageTests(_TempDb):
    def setUp(self):
        super().setUp()
        for p in (mock.patch.dict(os.environ, {"ADMIN_EMAILS": "ann@vive.com", "ADMIN_LOGIN_EMAIL": ""}),
                  mock.patch("web.deps._sidebar_counts", return_value={}),
                  mock.patch("web.queries.list_users", return_value=[
                      {"id": 1, "name": "Ann", "email": "ann@vive.com", "created_at": None, "is_active": 1},
                      {"id": 2, "name": "Jenn", "email": "jenn@vivecollision.com", "created_at": None,
                       "is_active": 1}]),
                  mock.patch("web.queries.create_user"),
                  mock.patch("web.queries.delete_user_by_email")):
            p.start()
            self.addCleanup(p.stop)

    def _client(self, me):
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-secret")
        app.include_router(users.router)
        app.dependency_overrides[require_login] = lambda: me
        return TestClient(app)

    def test_admin_sets_locations_and_the_list_shows_them(self):
        client = self._client("ann@vive.com")
        with mock.patch("web.queries.get_user_by_email", return_value={"email": "jenn@vivecollision.com"}):
            page = client.post("/users/locations", data={"email": "jenn@vivecollision.com", "shops": ["Jasmin"]})
        self.assertEqual(page.status_code, 200)
        self.assertIn("now sees 1 location: Jasmin", page.text)
        self.assertEqual(ul.get_user_shops("jenn@vivecollision.com"), ["Jasmin"])
        self.assertIn('action="/users/locations"', client.get("/users").text)

    def test_adding_a_user_can_set_their_locations(self):
        client = self._client("ann@vive.com")
        with mock.patch("web.queries.get_user_by_email", return_value=None):
            r = client.post("/users/add", data={"name": "Erin", "email": "erin@vivecollision.com",
                                                "password": "pw123456", "shops": ["Albany", "Don Joe"]},
                            follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(ul.get_user_shops("erin@vivecollision.com"), ["Albany", "Don Joe"])

    def test_a_non_admin_cannot_change_locations(self):
        client = self._client("jenn@vivecollision.com")
        with mock.patch("web.queries.get_user_by_email", return_value={"email": "jenn@vivecollision.com"}):
            r = client.post("/users/locations", data={"email": "jenn@vivecollision.com", "shops": ["Vestal"]})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(ul.get_user_shops("jenn@vivecollision.com"), [])
        self.assertNotIn('action="/users/locations"', client.get("/users").text)

    def test_removing_a_user_removes_their_locations(self):
        ul.set_user_shops("jenn@vivecollision.com", ["Jasmin"], set_by="ann@vive.com")
        self._client("ann@vive.com").post("/users/remove", data={"email": "jenn@vivecollision.com"},
                                          follow_redirects=False)
        self.assertEqual(ul.get_user_shops("jenn@vivecollision.com"), [])

    def test_the_switch_remembers_the_choice_and_goes_back(self):
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-secret")
        app.include_router(users.router)
        app.dependency_overrides[require_login] = lambda: "jenn@vivecollision.com"

        @app.get("/seen")
        def seen(request: Request):
            return {"scope": request.session.get(ul.SCOPE_SESSION_KEY)}

        client = TestClient(app)
        r = client.get("/location-scope", params={"value": "all", "next": "/exceptions?range=all"},
                       follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(r.headers["location"], "/exceptions?range=all")
        self.assertEqual(client.get("/seen").json(), {"scope": "all"})
        r = client.get("/location-scope", params={"value": "mine", "next": "https://evil.example"},
                       follow_redirects=False)
        self.assertEqual(r.headers["location"], "/")
        self.assertEqual(client.get("/seen").json(), {"scope": "mine"})

    def test_logging_in_starts_on_my_locations(self):
        from web.routers import auth
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-secret")
        app.include_router(auth.router)
        app.include_router(users.router)
        app.dependency_overrides[require_login] = lambda: "jenn@vivecollision.com"

        @app.get("/seen")
        def seen(request: Request):
            return {"scope": request.session.get(ul.SCOPE_SESSION_KEY)}

        client = TestClient(app)
        client.get("/location-scope", params={"value": "all"}, follow_redirects=False)
        with mock.patch.object(auth, "_authenticate", return_value="Jenn"):
            client.post("/login", data={"email": "jenn@vivecollision.com", "password": "x"}, follow_redirects=False)
        self.assertEqual(client.get("/seen").json(), {"scope": None})



class ShopFilterOptionsTests(unittest.TestCase):
    """The location filter's options (web/templates/_location_scope.html)."""

    def _options(self, scope, shops):
        from web.deps import templates
        t = templates.env.from_string(
            '{% import "_location_scope.html" as loc %}{{ loc.shop_filter_options(s, shops) }}')
        import re
        return re.findall(r'<option value="([^"]*)"[^>]*>([^<]*)</option>', t.render(s=scope, shops=shops))

    def test_my_locations_lists_my_shops_then_the_switch_to_all(self):
        scope = ul.LocationScope(shops=["Collex", "Dallas"], mine=True)
        self.assertEqual(self._options(scope, ["Collex", "Dallas"]),
                         [("", "My locations (2)"), ("Collex", "Collex"), ("Dallas", "Dallas"),
                          ("__scope_all", "All locations")])

    def test_all_locations_offers_the_switch_back_then_every_shop(self):
        scope = ul.LocationScope(shops=["Collex"], mine=False)
        self.assertEqual(self._options(scope, ["Albany", "Collex"]),
                         [("__scope_mine", "My locations (1)"), ("", "All locations"),
                          ("Albany", "Albany"), ("Collex", "Collex")])

    def test_no_shops_is_the_plain_list(self):
        self.assertEqual(self._options(ul.LocationScope(), ["Albany"]), [("", "All locations"), ("Albany", "Albany")])


if __name__ == "__main__":
    unittest.main()
