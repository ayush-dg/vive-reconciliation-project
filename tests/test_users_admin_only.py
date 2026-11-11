"""
tests/test_users_admin_only.py

Only admins add or remove users (2026-11-04). Admins are the ADMIN_EMAILS
app setting plus the fallback admin login (ADMIN_LOGIN_EMAIL). Everyone else
sees the list read-only, and the server refuses their add/remove posts.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from web.deps import is_admin, require_login
from web.routers import users

USERS = [
    {"name": "Ann Admin", "email": "ann@vive.com", "created_at": None, "is_active": 1},
    {"name": "Bob User", "email": "bob@vive.com", "created_at": None, "is_active": 1},
]
SETTINGS = {"ADMIN_EMAILS": " Ann@Vive.com , carl@vive.com", "ADMIN_LOGIN_EMAIL": "setup@vive.com"}


class IsAdminTests(unittest.TestCase):
    def test_admins_are_the_setting_plus_the_fallback_login(self):
        with mock.patch.dict(os.environ, SETTINGS):
            self.assertTrue(is_admin("ann@vive.com"))
            self.assertTrue(is_admin(" CARL@vive.com "))
            self.assertTrue(is_admin("setup@vive.com"))
            self.assertFalse(is_admin("bob@vive.com"))
            self.assertFalse(is_admin(None))

    def test_no_settings_means_no_admins(self):
        with mock.patch.dict(os.environ, {"ADMIN_EMAILS": "", "ADMIN_LOGIN_EMAIL": ""}):
            self.assertFalse(is_admin("ann@vive.com"))


class UsersPageTests(unittest.TestCase):
    def setUp(self):
        patches = [
            mock.patch.dict(os.environ, SETTINGS),
            mock.patch("web.deps._sidebar_counts", return_value={}),
            mock.patch("web.queries.list_users", return_value=USERS),
            mock.patch("web.queries.get_user_by_email", return_value=None),
            # Locations (web/user_locations.py) are tested in test_user_locations.py.
            mock.patch("web.user_locations.all_user_shops", return_value={}),
            mock.patch("web.user_locations.delete_user_shops"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.create = mock.patch("web.queries.create_user").start()
        self.delete = mock.patch("web.queries.delete_user_by_email").start()
        self.addCleanup(mock.patch.stopall)

    def _client(self, me):
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-secret")
        app.include_router(users.router)
        app.dependency_overrides[require_login] = lambda: me
        return TestClient(app)

    def test_admin_sees_the_controls_and_can_add_and_remove(self):
        client = self._client("ann@vive.com")
        page = client.get("/users").text
        self.assertIn('action="/users/add"', page)
        self.assertIn('action="/users/remove"', page)

        added = client.post("/users/add", data={"name": "Dee", "email": "dee@vive.com", "password": "pw123456"},
                            follow_redirects=False)
        # The page comes back with the one-time "Download credentials" button.
        self.assertEqual(added.status_code, 200)
        self.assertIn('action="/users/credentials.xlsx"', added.text)
        self.create.assert_called_once()
        removed = client.post("/users/remove", data={"email": "bob@vive.com"}, follow_redirects=False)
        self.assertEqual(removed.status_code, 303)
        self.delete.assert_called_once_with("bob@vive.com")

    def test_non_admin_sees_a_read_only_list(self):
        page = self._client("bob@vive.com").get("/users")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Ann Admin", page.text)
        self.assertNotIn('action="/users/add"', page.text)
        self.assertNotIn('action="/users/remove"', page.text)
        self.assertIn("Only admins can add or remove users.", page.text)

    def test_non_admin_add_and_remove_are_refused(self):
        client = self._client("bob@vive.com")
        added = client.post("/users/add", data={"name": "Eve", "email": "eve@vive.com", "password": "pw123456"})
        removed = client.post("/users/remove", data={"email": "ann@vive.com"})
        self.assertEqual((added.status_code, removed.status_code), (403, 403))
        self.create.assert_not_called()
        self.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
