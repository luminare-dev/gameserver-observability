"""Tests for scripts/check_pr_title.py."""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_pr_title as pt  # noqa: E402


class TitleTest(unittest.TestCase):
    def test_good_titles(self):
        for title in ("feat: add a restore drill", "fix(backup): retry the upload after a timeout",
                      "feat(config)!: rename the port variable", "chore(main): release 0.1.0",
                      "ci(deps): bump the actions group with 2 updates", "security: rotate the example key",
                      "docs: explain the ADR format", "revert: undo the cache change"):
            with self.subTest(title=title):
                self.assertEqual(pt.problems(title), [])

    def test_bad_format(self):
        for title in ("update stuff", "Feat: add x", "feat:add x", "feat(): add x", "feature: add x",
                      'Revert "feat: add x"'):
            with self.subTest(title=title):
                self.assertTrue(pt.problems(title))

    def test_style(self):
        self.assertTrue(pt.problems("fix: Correct the retry delay"))
        self.assertTrue(pt.problems("fix: correct the retry delay."))
        self.assertEqual(pt.problems("fix: ADR numbering starts at 0001"), [])
        self.assertTrue(pt.problems("feat: " + "x" * 100))

    def test_dependabot_may_capitalise(self):
        """Dependabot writes 'Bump ...'; only that bot is exempt from the lower-case rule."""
        title = "ci(deps): Bump the actions group with 4 updates"
        self.assertEqual(pt.problems(title, "dependabot[bot]"), [])
        self.assertTrue(pt.problems(title, "someone"))
        self.assertTrue(pt.problems(title))
        self.assertTrue(pt.problems("Bump the actions group", "dependabot[bot]"))
        self.assertTrue(any(p.startswith("wording") for p in pt.problems("ci(deps): Bump the pro version", "dependabot[bot]")))

    def test_offer_wording_is_rejected(self):
        """Release notes are built from the titles, so they must be offer-free too."""
        for title in ("feat: add pro version toggle", "docs: add donation link", "feat: coming soon page",
                      "docs: link the tebex package"):
            with self.subTest(title=title):
                self.assertTrue(any(p.startswith("wording") for p in pt.problems(title)))

    def test_cli(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(pt.main(["fix: correct the retry delay"]), 0)
            self.assertEqual(pt.main(["bad title"]), 1)


if __name__ == "__main__":
    unittest.main()
