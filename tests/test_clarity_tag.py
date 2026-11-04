"""
tests/test_clarity_tag.py

Microsoft Clarity (2026-11-04): web/deps.py clarity_project_id() and
_clarity.html, included by base.html and login.html. The tag is on the page
only when CLARITY_PROJECT_ID is set. Nothing here talks to Clarity.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web.deps import clarity_project_id, templates

ON = {"CLARITY_PROJECT_ID": "z89ibclxzx"}
OFF = {"CLARITY_PROJECT_ID": ""}


def _render(**ctx):
    return templates.get_template("_clarity.html").render(**ctx)


class ProjectIdTests(unittest.TestCase):
    def test_unset_means_no_tag(self):
        with mock.patch.dict(os.environ, OFF):
            self.assertIsNone(clarity_project_id())
            self.assertNotIn("clarity", _render(user_email="a@vive.com", active_page="home"))

    def test_a_value_that_is_not_a_project_id_is_ignored(self):
        with mock.patch.dict(os.environ, {"CLARITY_PROJECT_ID": 'x");alert(1);("'}):
            self.assertIsNone(clarity_project_id())

    def test_set_puts_the_tag_on_the_page(self):
        with mock.patch.dict(os.environ, ON):
            html = _render(user_email="a@vive.com", user_name="Ann", active_page="exceptions")
        self.assertIn('"clarity", "script", "z89ibclxzx"', html)
        self.assertIn('clarity("identify", "a@vive.com", null, null, "Ann")', html)
        self.assertIn('clarity("set", "page", "exceptions")', html)


class PageTests(unittest.TestCase):
    def test_signed_out_pages_are_tagged_without_identify(self):
        with mock.patch.dict(os.environ, ON):
            html = _render(clarity_page="login")
        self.assertNotIn("identify", html)
        self.assertIn('clarity("set", "page", "login")', html)

    def test_base_and_login_include_it(self):
        for name in ("base.html", "login.html"):
            source = templates.env.loader.get_source(templates.env, name)[0]
            self.assertIn('{% include "_clarity.html" %}', source, name)


if __name__ == "__main__":
    unittest.main()
