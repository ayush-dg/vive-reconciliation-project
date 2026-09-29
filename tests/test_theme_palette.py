"""
tests/test_theme_palette.py

Guards the soft light theme (2026-09-29, replacing the earlier pure
monochrome pass): every colour in web/static/style.css -- outside the
commented-out dark-mode block, which is left as it was -- must belong to
one of:
  - a grey/slate neutral (R, G, B all within a few points of each other)
  - the one accent family: #1E3A5F (--navy-2/--accent/--exception),
    #EEF2F7 (--navy-tint), #16304F (--accent-hover)
  - the sidebar/login-hero's original navy palette (#040B14 and the
    handful of one-off blues/blue-greys listed below)
  - the single failure red, #B42318 (--danger, text only)
Templates must not hard-code a colour outside that same set either, and
the only font is Inter -- IBM Plex Mono must not be referenced or loaded
anywhere in the web app. Also catches URL-encoded hex colours inside data
URIs (%23RRGGBB, e.g. an inline SVG's stroke="%23..." after "#" gets
percent-encoded), not just literal "#RRGGBB"/"rgb(...)" -- the select
arrow background-image is exactly this shape.
"""

import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..", "web")
CSS_PATH = os.path.join(ROOT, "static", "style.css")
TEMPLATES = os.path.join(ROOT, "templates")

ACCENT = {(0x1E, 0x3A, 0x5F), (0xEE, 0xF2, 0xF7), (0x16, 0x30, 0x4F)}
FAILURE_RED = (0xB4, 0x23, 0x18)
# The sidebar and login hero deliberately kept their original navy palette
# (from before the 2026-09-29 restyle) rather than moving to the accent.
SIDEBAR_LOGIN = {
    (0x04, 0x0B, 0x14),  # --navy (sidebar bg / login hero bg / step-num text bg)
    (0xDC, 0xE5, 0xEE), (0xB8, 0xC8, 0xDA), (0x5E, 0x79, 0x94), (0xC4, 0xD2, 0xDF),
    (0x6F, 0xA8, 0xDC), (0x2A, 0x50, 0x7A), (0x8F, 0xA3, 0xB8),
    (0x9F, 0xB4, 0xC9), (0x8F, 0xBE, 0xEB), (0xB9, 0xC9, 0xD8),
}
ALLOWED = ACCENT | SIDEBAR_LOGIN | {FAILURE_RED}

HEX_RE = re.compile(r"#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b")
RGB_RE = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")
# %23RRGGBB / %23RGB -- a URL-encoded "#" hex colour, as appears inside a
# data: URI (e.g. an inline SVG background-image's stroke="..." attribute
# after browser/CSS percent-encoding of the literal "#").
URL_HEX_RE = re.compile(r"%23([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b")
# Neutral if every channel is within this many points of the mean. The
# palette's slates are deliberately cool (a slight blue/green lean, e.g.
# --text-strong #111827 has a max channel deviation of ~12.3, --success
# (the shared badge text colour) #374151 ~14.0) rather than pure greys, so
# the tolerance has to clear that bar -- 16 does, while still rejecting
# any genuinely saturated colour (e.g. the old orange nav dot #D98A3D
# deviates ~79, the accent #1E3A5F ~34).
NEUTRAL_TOLERANCE = 16


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
    for m in URL_HEX_RE.finditer(text):
        yield m.group(0), _hex_to_rgb(m.group(1))


def _is_neutral(rgb):
    mean = sum(rgb) / 3
    return all(abs(c - mean) <= NEUTRAL_TOLERANCE for c in rgb)


def _is_allowed(rgb):
    return _is_neutral(rgb) or rgb in ALLOWED


def _line_of(text, needle):
    return next((line.strip() for line in text.splitlines() if needle in line), "")


class TestThemePaletteStylesheet(unittest.TestCase):

    def test_every_colour_is_neutral_accent_sidebar_or_the_one_failure_red(self):
        css = _css_without_dark_block()
        offenders = [
            f"{raw} rgb{rgb}  <-  {_line_of(css, raw)[:120]}"
            for raw, rgb in _colours(css)
            if not _is_allowed(rgb)
        ]
        self.assertEqual(offenders, [], "colours outside the palette in style.css:\n" + "\n".join(offenders))

    def test_the_failure_red_is_only_the_danger_token(self):
        css = _css_without_dark_block()
        self.assertIn("--danger: #B42318;", css)

    def test_the_accent_is_defined_once_each(self):
        css = _css_without_dark_block()
        self.assertIn("--navy-2: #1E3A5F;", css)
        self.assertIn("--navy-tint: #EEF2F7;", css)
        self.assertIn("--accent-hover: #16304F;", css)

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

    def test_templates_hard_code_no_colour_outside_the_palette(self):
        offenders = []
        for name, html in self._template_files():
            for style in re.findall(r'style="([^"]*)"', html):
                for raw, rgb in _colours(style):
                    if not _is_allowed(rgb):
                        offenders.append(f"{name}: {raw} rgb{rgb}")
        self.assertEqual(offenders, [])

    def test_no_ibm_plex_mono_anywhere(self):
        hits = []
        for folder, _, files in os.walk(ROOT):
            for f in files:
                if f.endswith((".html", ".css", ".js", ".py")):
                    text = open(os.path.join(folder, f), encoding="utf-8", errors="ignore").read()
                    if re.search(r"IBM\+?\s*Plex", text):
                        hits.append(os.path.relpath(os.path.join(folder, f), ROOT))
        self.assertEqual(hits, [])

    def test_google_fonts_loads_inter_400_500_600_only(self):
        for name in ("base.html", "login.html"):
            html = open(os.path.join(TEMPLATES, name), encoding="utf-8").read()
            links = re.findall(r'href="(https://fonts\.googleapis\.com/css2[^"]*)"', html)
            with self.subTest(template=name):
                self.assertEqual(links, ["https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap"])


if __name__ == "__main__":
    unittest.main()
