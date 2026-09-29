"""
tests/test_monochrome_theme.py

Guards the monochrome UI (2026-09-29): every colour in web/static/style.css
-- outside the commented-out dark-mode block, which is left as it was --
must be a grey (R = G = B), with exactly one allowed exception: the
failure red #B42318 (--danger, text only). Templates must not hard-code a
non-grey hex colour either. And the only font is Inter: IBM Plex Mono must
not be referenced or loaded anywhere in the web app.
"""

import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..", "web")
CSS_PATH = os.path.join(ROOT, "static", "style.css")
TEMPLATES = os.path.join(ROOT, "templates")
ALLOWED_RED = (0xB4, 0x23, 0x18)

HEX_RE = re.compile(r"#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b")
RGB_RE = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")


def _css_without_dark_block():
    css = open(CSS_PATH, encoding="utf-8").read()
    start = css.index("/* Dark mode")
    end = css.index("*/", css.index("@media (prefers-color-scheme: dark)")) + 2
    return css[:start] + css[end:]


def _hex_to_rgb(h):
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _colours(text):
    for m in HEX_RE.finditer(text):
        yield m.group(0), _hex_to_rgb(m.group(1))
    for m in RGB_RE.finditer(text):
        yield m.group(0), tuple(int(v) for v in m.groups())


def _line_of(text, needle):
    return next((line.strip() for line in text.splitlines() if needle in line), "")


class TestMonochromeStylesheet(unittest.TestCase):

    def test_every_colour_is_grey_except_the_one_failure_red(self):
        css = _css_without_dark_block()
        offenders = [
            f"{raw}  <-  {_line_of(css, raw)[:120]}"
            for raw, rgb in _colours(css)
            if len(set(rgb)) != 1 and rgb != ALLOWED_RED
        ]
        self.assertEqual(offenders, [], "non-grey colours in style.css:\n" + "\n".join(offenders))

    def test_the_failure_red_is_only_the_danger_token(self):
        css = _css_without_dark_block()
        reds = [raw for raw, rgb in _colours(css) if rgb == ALLOWED_RED]
        self.assertEqual(len(reds), 1, "the red should be defined once, as --danger")
        self.assertIn("--danger: #B42318;", css)

    def test_dark_mode_block_is_still_commented_out(self):
        css = open(CSS_PATH, encoding="utf-8").read()
        start = css.index("/* Dark mode")
        self.assertLess(start, css.index("@media (prefers-color-scheme: dark)"))
        self.assertNotIn("*/", css[start:css.index("@media (prefers-color-scheme: dark)")])

    def test_font_mono_is_inter(self):
        self.assertIn("--font-mono: 'Inter', sans-serif;", _css_without_dark_block())


class TestTemplatesAndFonts(unittest.TestCase):

    def _template_files(self):
        for name in sorted(os.listdir(TEMPLATES)):
            if name.endswith(".html"):
                path = os.path.join(TEMPLATES, name)
                yield name, open(path, encoding="utf-8").read()

    def test_templates_hard_code_no_non_grey_colour(self):
        offenders = []
        for name, html in self._template_files():
            for style in re.findall(r'style="([^"]*)"', html):
                for raw, rgb in _colours(style):
                    if len(set(rgb)) != 1:
                        offenders.append(f"{name}: {raw}")
        self.assertEqual(offenders, [])

    def test_no_ibm_plex_mono_anywhere(self):
        hits = []
        for folder, _, files in os.walk(ROOT):
            for f in files:
                if f.endswith((".html", ".css", ".js", ".py")):
                    text = open(os.path.join(folder, f), encoding="utf-8", errors="ignore").read()
                    if re.search(r"IBM\+?\s*Plex", text):
                        hits.append(os.path.relpath(os.path.join(folder, f), ROOT))
        # The disabled dark-mode block defines no fonts, so no exemption is needed.
        self.assertEqual(hits, [])

    def test_google_fonts_loads_inter_400_500_600_only(self):
        for name in ("base.html", "login.html"):
            html = open(os.path.join(TEMPLATES, name), encoding="utf-8").read()
            links = re.findall(r'href="(https://fonts\.googleapis\.com/css2[^"]*)"', html)
            with self.subTest(template=name):
                self.assertEqual(links, ["https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap"])


if __name__ == "__main__":
    unittest.main()
