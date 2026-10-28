"""
tests/test_auth_fallback.py

The fallback admin login (web/routers/auth.py, 2026-10-28) comes only from
the app settings -- ADMIN_LOGIN_EMAIL and ADMIN_LOGIN_PASSWORD -- and is off
when either is unset. Users-table logins are unaffected.
Offline: the users-table lookup is mocked.
"""

import os
import sys
import unittest
from unittest import mock

import bcrypt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web.routers import auth


def _login(email, password, env, user=None):
    with mock.patch.dict(os.environ, env, clear=False), \
            mock.patch.object(auth.queries, "get_user_by_email", return_value=user):
        for name in ("ADMIN_LOGIN_EMAIL", "ADMIN_LOGIN_PASSWORD"):
            if name not in env:
                os.environ.pop(name, None)
        return auth._authenticate(email, password)


class FallbackLoginTests(unittest.TestCase):
    SETTINGS = {"ADMIN_LOGIN_EMAIL": "Ops@Example.com", "ADMIN_LOGIN_PASSWORD": "correct horse"}

    def test_settings_login_works_case_insensitively_on_the_email(self):
        self.assertEqual(_login(" ops@example.com ", "correct horse", self.SETTINGS), "Admin")

    def test_wrong_password_or_email_fails(self):
        self.assertIsNone(_login("ops@example.com", "wrong", self.SETTINGS))
        self.assertIsNone(_login("other@example.com", "correct horse", self.SETTINGS))

    def test_no_fallback_without_both_settings(self):
        self.assertIsNone(_login("ops@example.com", "correct horse", {"ADMIN_LOGIN_EMAIL": "ops@example.com"}))
        self.assertIsNone(_login("ops@example.com", "correct horse", {"ADMIN_LOGIN_PASSWORD": "correct horse"}))
        self.assertIsNone(_login("ops@example.com", "correct horse", {}))

    def test_no_login_is_hardcoded(self):
        self.assertFalse(hasattr(auth, "FALLBACK_EMAIL"))
        self.assertFalse(hasattr(auth, "FALLBACK_PASSWORD"))

    def test_the_password_is_case_sensitive(self):
        self.assertIsNone(_login("ops@example.com", "Correct Horse", self.SETTINGS))

    def test_users_table_login_still_wins(self):
        user = {"name": "Vaishali", "is_active": 1,
                "password_hash": bcrypt.hashpw(b"pw", bcrypt.gensalt(rounds=4)).decode()}
        self.assertEqual(_login("v@example.com", "pw", {}, user=user), "Vaishali")


if __name__ == "__main__":
    unittest.main()
