"""Contract for the shared terminal wordmark in zeline.branding.

One identity must render correctly on Termux, Linux, macOS, and Windows — in
colour on a real TTY and as clean monochrome under NO_COLOR / a pipe / CI. These
tests pin the behaviour the skill's checklist requires: exact source lines, a
colour path and a plain path generated from the same lines, a compact ASCII
fallback for narrow terminals, and a Unicode fallback for legacy encodings.
"""
from __future__ import annotations

import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from zeline import branding  # noqa: E402


class BrandingTests(unittest.TestCase):
    def test_full_wordmark_is_six_lines_of_uniform_width_block_art(self):
        self.assertEqual(len(branding.WORDMARK_FULL), 6)
        widths = {len(line) for line in branding.WORDMARK_FULL}
        self.assertEqual(widths, {branding.FULL_WIDTH})
        # It is real block art, not a framed label.
        self.assertIn("\u2588", "".join(branding.WORDMARK_FULL))

    def test_compact_wordmark_is_pure_ascii(self):
        joined = "".join(branding.WORDMARK_COMPACT)
        self.assertTrue(all(ord(ch) < 128 for ch in joined), "compact art must be ASCII")
        widths = {len(line) for line in branding.WORDMARK_COMPACT}
        self.assertEqual(widths, {branding.COMPACT_WIDTH})

    def test_plain_render_has_no_ansi_and_carries_the_subtitle(self):
        out = branding.banner("1.2.3", color=False, unicode_ok=True, width=80)
        self.assertNotIn("\x1b[", out)
        self.assertIn("AGENTIC AI BY ZEROLINEAR \u2022 v1.2.3", out)
        self.assertIn("\u2588", out)  # full block art on a wide unicode terminal

    def test_color_render_emits_ansi_from_the_same_lines(self):
        out = branding.banner("1.2.3", color=True, unicode_ok=True, width=80)
        self.assertIn("\x1b[", out)
        # Strip ANSI and the plain content must be identical to plain mode.
        import re

        stripped = re.sub(r"\x1b\[[0-9;]*m", "", out)
        self.assertEqual(stripped, branding.banner("1.2.3", color=False, unicode_ok=True, width=80))

    def test_narrow_terminal_falls_back_to_the_compact_wordmark(self):
        wide = branding.banner("1.2.3", color=False, unicode_ok=True, width=80)
        narrow = branding.banner("1.2.3", color=False, unicode_ok=True, width=30)
        self.assertIn("\u2588", wide)
        self.assertNotIn("\u2588", narrow)  # too narrow for block art
        self.assertIn(branding.WORDMARK_COMPACT[0].strip()[:4], narrow)

    def test_legacy_encoding_falls_back_to_ascii_wordmark_and_bullet(self):
        out = branding.banner("1.2.3", color=False, unicode_ok=False, width=80)
        self.assertNotIn("\u2588", out)
        self.assertNotIn("\u2022", out)  # bullet degrades to '-'
        self.assertIn("AGENTIC AI BY ZEROLINEAR - v1.2.3", out)

    def test_color_disabled_under_no_color_env(self):
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False):
            self.assertFalse(branding.color_enabled(io.StringIO()))

    def test_gradient_is_blue_leaning_and_darkens_monotonically(self):
        """The wordmark must go light-blue -> dark-blue, never bounce, never cyan.

        Regression for the reported "muda→tua→muda→tua" bounce: every row must be
        darker than the one above (monotonic luminance) and blue-dominant (the
        256-colour cube's blue channel strictly greater than green, so no teal).
        """
        codes = [int(sgr.split(";")[-1]) for sgr in branding._GRADIENT]
        self.assertEqual(len(codes), len(branding.WORDMARK_FULL))

        def rgb(n: int) -> tuple[int, int, int]:
            n -= 16
            r, g, b = n // 36, (n % 36) // 6, n % 6
            scale = lambda v: 0 if v == 0 else 55 + 40 * v
            return scale(r), scale(g), scale(b)

        def lum(n: int) -> float:
            r, g, b = rgb(n)
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        lums = [lum(c) for c in codes]
        self.assertEqual(lums, sorted(lums, reverse=True), "gradient must darken monotonically")
        # Row 1 is white (the "Putih" top); every row below it must be
        # blue-leaning (blue > green) so the fade never drifts into cyan/teal.
        head_r, head_g, head_b = rgb(codes[0])
        self.assertGreaterEqual(min(head_r, head_g, head_b), 200, "top row should be white")
        for c in codes[1:]:
            r, g, b = rgb(c)
            self.assertGreater(b, g, f"colour {c} is not blue-leaning (b={b} g={g})")

    def test_prompt_glyph_and_rule_degrade_on_legacy_encoding(self):
        self.assertEqual(branding.prompt_glyph(unicode_ok=True), "\u276f")
        self.assertEqual(branding.prompt_glyph(unicode_ok=False), ">")
        self.assertIn("\u2500", branding.rule(width=20, unicode_ok=True))
        self.assertNotIn("\u2500", branding.rule(width=20, unicode_ok=False))
        self.assertIn("-", branding.rule(width=20, unicode_ok=False))

    def test_emoji_prefix_present_when_capable_and_stripped_on_legacy(self):
        # Capable terminal → '🛰️ ' prefix with a trailing space before the label.
        self.assertEqual(branding.emoji("\U0001f6f0\ufe0f", unicode_ok=True), "\U0001f6f0\ufe0f ")
        # Legacy console cannot encode the astral emoji → empty prefix, never a
        # mojibake box. The label alone still reads cleanly.
        self.assertEqual(branding.emoji("\U0001f6f0\ufe0f", unicode_ok=False), "")

    def test_color_forced_on_with_force_color(self):
        with mock.patch.dict(os.environ, {"FORCE_COLOR": "1"}, clear=False):
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("NO_COLOR", None)
                self.assertTrue(branding.color_enabled(io.StringIO()))

    def test_supports_unicode_true_for_utf8_stream_false_for_cp1252(self):
        utf8_stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        legacy_stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        self.assertTrue(branding.supports_unicode(utf8_stream))
        self.assertFalse(branding.supports_unicode(legacy_stream))


if __name__ == "__main__":
    unittest.main()
