"""Tests for scripts/set_byline.py: both byline modes render, and the switch is lossless."""

from __future__ import annotations

import io
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import set_byline as sb  # noqa: E402

# Patterns rather than literal text, so the tests keep passing once a repository created from the
# template has filled its placeholders or switched to the personal byline.
STUDIO_RE = re.compile(r"^\*a \[Luminare Development\]\(https://luminare\.tech/open-source/[^)]+/\) open-source project\*$",
                       re.MULTILINE)
PERSONAL_RE = re.compile(r"^\*by [^*\n]+ · \[project page\]\(https://luminare\.tech/open-source/[^)]+/\)\*$", re.MULTILINE)
IS_TEMPLATE = "template-only:begin" in (ROOT / "README.md").read_text(encoding="utf-8")


STUDIO_NOTICE = 'demo\n\nThe names "Luminare Development" and "Luminare", the Luminare logo and mark,\nare not licensed.\n'
NEUTRAL_NOTICE = "demo\n\nThe name and logo of this project are not licensed.\n"


def studio_readme() -> str:
    return sb.set_mode((ROOT / "README.md").read_text(encoding="utf-8"), "studio")


def temp_dir() -> Path:
    """A temporary folder that is removed when the tests of this module are done."""
    tmp = Path(tempfile.mkdtemp(prefix="byline-test-"))
    unittest.addModuleCleanup(shutil.rmtree, tmp, ignore_errors=True)
    return tmp


def copy_template() -> Path:
    """A studio-mode copy of the files set_byline reads, so the tests never touch the repository
    and do not depend on the mode this repository is in."""
    tmp = temp_dir()
    (tmp / "README.md").write_text(studio_readme(), encoding="utf-8")
    (tmp / "NOTICE").write_text(STUDIO_NOTICE, encoding="utf-8")
    (tmp / "docs" / "brand").mkdir(parents=True)
    (tmp / "docs" / "brand" / "KIT_VERSION").write_text("untagged+test\nvariant: studio\n", encoding="utf-8")
    return tmp


def quiet(fn, *args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = fn(*args)
    return code, buf.getvalue()


class TemplateReadmeTest(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "README.md").read_text(encoding="utf-8")

    @unittest.skipUnless(IS_TEMPLATE, "only the template itself must stay in studio mode")
    def test_default_mode_is_studio(self):
        self.assertEqual(sb.current_mode(self.text), "studio")

    def test_two_places_per_variant(self):
        """Under the header and in the licence section."""
        blocks = sb.parse_blocks(self.text)
        self.assertEqual(sorted(b.group("kind") for b in blocks), ["personal", "personal", "studio", "studio"])

    def test_studio_mode_renders(self):
        visible = sb.visible_text(sb.set_mode(self.text, "studio"))
        self.assertEqual(len(STUDIO_RE.findall(visible)), 2)
        self.assertEqual(PERSONAL_RE.findall(visible), [])
        self.assertIn("<picture>", visible)
        self.assertIn("docs/brand/readme-header-dark.svg", visible)

    def test_personal_mode_renders(self):
        personal = sb.set_mode(self.text, "personal")
        self.assertEqual(sb.current_mode(personal), "personal")
        visible = sb.visible_text(personal)
        self.assertEqual(len(PERSONAL_RE.findall(visible)), 2)
        self.assertNotIn("Luminare Development", visible)
        self.assertIn("<picture>", visible)

    def test_round_trip_is_lossless(self):
        mode = sb.current_mode(self.text)
        other = "personal" if mode == "studio" else "studio"
        self.assertEqual(sb.set_mode(sb.set_mode(self.text, other), mode), self.text)

    def test_comments_stay_balanced_in_both_modes(self):
        for mode in sb.MODES:
            text = sb.set_mode(self.text, mode)
            prose = re.sub(r"^```.*?^```", "", text, flags=re.MULTILINE | re.DOTALL)  # Mermaid arrows are "-->"
            self.assertEqual(prose.count("<!--"), prose.count("-->"), mode)
            text = prose
            stripped = sb.visible_text(text)
            self.assertNotIn("<!--", stripped, mode)
            self.assertNotIn("-->", stripped, mode)

    def test_only_byline_lines_change(self):
        personal = sb.set_mode(sb.set_mode(self.text, "studio"), "personal")
        changed = [(a, b) for a, b in zip(self.text.splitlines(), personal.splitlines()) if a != b]
        self.assertEqual(len(self.text.splitlines()), len(personal.splitlines()))
        for a, b in changed:
            self.assertTrue(re.search(r"byline:(studio|personal)", a + b), (a, b))


class MalformedReadmeTest(unittest.TestCase):
    def test_no_blocks(self):
        with self.assertRaises(sb.ReadmeError):
            sb.current_mode("# Title\n")

    def test_missing_variant(self):
        text = "<!-- byline:studio -->\n*x*\n<!-- /byline:studio -->\n"
        with self.assertRaises(sb.ReadmeError):
            sb.current_mode(text)

    def test_half_active_block(self):
        text = ("<!-- byline:studio -->\n*x*\n/byline:studio -->\n"
                "<!-- byline:personal\n*y*\n/byline:personal -->\n")
        with self.assertRaises(sb.ReadmeError):
            sb.current_mode(text)

    def test_both_active(self):
        text = ("<!-- byline:studio -->\n*x*\n<!-- /byline:studio -->\n"
                "<!-- byline:personal -->\n*y*\n<!-- /byline:personal -->\n")
        with self.assertRaises(sb.ReadmeError):
            sb.current_mode(text)

    def test_comment_inside_block(self):
        text = ("<!-- byline:studio -->\n*x* <!-- note -->\n<!-- /byline:studio -->\n"
                "<!-- byline:personal\n*y*\n/byline:personal -->\n")
        with self.assertRaises(sb.ReadmeError):
            sb.current_mode(text)


class CliTest(unittest.TestCase):
    def test_switch_and_verify(self):
        tmp = copy_template()
        code, out = quiet(sb.main, ["status", "--root", str(tmp)])
        self.assertEqual((code, out.strip()), (0, "studio"))
        code, out = quiet(sb.main, ["verify", "--root", str(tmp)])
        self.assertEqual(code, 0, out)

        code, out = quiet(sb.main, ["personal", "--root", str(tmp), "--slug", "demo"])
        self.assertEqual(code, 0)
        self.assertIn("studio -> personal", out)
        self.assertIn("brand-repos/out/demo/neutral/", out)  # tells which brand files to swap
        self.assertIn("NOTICE", out)
        self.assertEqual(sb.current_mode((tmp / "README.md").read_text(encoding="utf-8")), "personal")

        code, out = quiet(sb.main, ["verify", "--root", str(tmp)])
        self.assertEqual(code, 1)  # docs/brand and NOTICE are still the studio variant
        self.assertIn("docs/brand/ holds the studio variant", out)

        code, out = quiet(sb.main, ["studio", "--root", str(tmp)])
        self.assertEqual(code, 0)
        self.assertEqual((tmp / "README.md").read_text(encoding="utf-8"), studio_readme())

    def test_verify_passes_after_a_complete_swap(self):
        tmp = copy_template()
        quiet(sb.main, ["personal", "--root", str(tmp)])
        kv = tmp / "docs" / "brand" / "KIT_VERSION"
        kv.write_text(kv.read_text(encoding="utf-8").replace("variant: studio", "variant: neutral"), encoding="utf-8")
        (tmp / "NOTICE").write_text(NEUTRAL_NOTICE, encoding="utf-8")
        code, out = quiet(sb.main, ["verify", "--root", str(tmp), "--expect", "personal"])
        self.assertEqual(code, 0, out)

    def test_expect(self):
        tmp = copy_template()
        code, _ = quiet(sb.main, ["status", "--root", str(tmp), "--expect", "personal"])
        self.assertEqual(code, 1)

    def test_verify_expect_prints_the_steps_for_the_expected_mode(self):
        tmp = copy_template()
        code, out = quiet(sb.main, ["verify", "--root", str(tmp), "--slug", "demo", "--expect", "personal"])
        self.assertEqual(code, 1)
        self.assertIn("README byline is studio, expected personal", out)
        self.assertIn("run: python3 scripts/set_byline.py personal", out)
        self.assertIn("Brand files for 'personal'", out)
        self.assertIn("brand-repos/out/demo/neutral/", out)
        self.assertNotIn("/studio/", out)

    def test_malformed_exit_code(self):
        tmp = temp_dir()
        (tmp / "README.md").write_text("# no markers\n", encoding="utf-8")
        err = io.StringIO()
        old, sys.stderr = sys.stderr, err
        try:
            self.assertEqual(sb.main(["status", "--root", str(tmp)]), 2)
        finally:
            sys.stderr = old


if __name__ == "__main__":
    unittest.main()
