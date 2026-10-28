"""
tests/test_filter_memory.py

List-page filters survive leaving the page (2026-10-27): static/filters.js is
loaded in <head> (before the pages' own scripts), and Home, Exceptions and
Statement Processing each start from it, save to it and offer "Reset
filters". The browser behaviour itself (sessionStorage, the address) can't
run here; these checks keep the wiring from being dropped.
"""

import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class FilterMemoryWiringTests(unittest.TestCase):
    def test_the_helper_loads_in_head_before_the_page_scripts(self):
        base = _read("web", "templates", "base.html")
        head = base.split("</head>")[0]
        self.assertIn("static_url('filters.js')", head)
        self.assertIn("{% block head_scripts %}", head)
        self.assertNotIn("filters.js", base.split("</head>")[1])

    def test_each_list_page_starts_from_saves_to_and_can_reset_its_filters(self):
        pages = {
            "home.html": (r'ViveFilters\.init\(\[\], true\)', False),
            "exceptions_vendors.html": (r'ViveFilters\.init\(\["vendor", "shop", "location"\], true\)', True),
            "validation.html": (r'ViveFilters\.init\(\["status", "vendor", "shop", "period", "sync", "day"\], false\)', True),
        }
        for page, (init, saves) in pages.items():
            with self.subTest(page=page):
                html = _read("web", "templates", page)
                self.assertRegex(html, init)
                self.assertIn("ViveFilters.reset()", html)
                if saves:
                    self.assertIn("ViveFilters.save(", html)

    def test_the_helper_never_overrides_a_choice_made_on_the_same_page(self):
        js = _read("web", "static", "filters.js")
        self.assertIn("cameFromThisPage()", js)
        self.assertTrue(re.search(r"!location\.search && saved && !cameFromThisPage\(\)", js))


if __name__ == "__main__":
    unittest.main()
