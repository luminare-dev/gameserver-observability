"""Tests for the lint and scan configuration (.markdownlint-cli2.jsonc, .gitleaks.toml).

The checks that need markdownlint-cli2 or gitleaks run only where the tool is on the PATH (the
CI lint-test job has neither; the secrets job scans tests/fixtures/ with every commit).
"""

from __future__ import annotations

import json
import secrets
import shutil
import string
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"

# A release entry as release-please writes it: two blank lines after each version heading.
RELEASE_PLEASE_ENTRY = (
    "## [0.1.0](https://github.com/luminare-dev/demo/compare/v0.0.0...v0.1.0) (2026-10-07)\n\n\n"
    "### Features\n\n"
    "* **ci:** add the first check ([#1](https://github.com/luminare-dev/demo/issues/1)) "
    "([abc1234](https://github.com/luminare-dev/demo/commit/abc1234))\n\n\n"
    "### Bug Fixes\n\n"
    "* retry the upload ([#2](https://github.com/luminare-dev/demo/issues/2)) "
    "([def5678](https://github.com/luminare-dev/demo/commit/def5678))\n\n"
)


def temp_dir(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    unittest.addModuleCleanup(shutil.rmtree, tmp, ignore_errors=True)
    return tmp


def markdownlint_config() -> dict:
    text = (ROOT / ".markdownlint-cli2.jsonc").read_text(encoding="utf-8")
    return json.loads("\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//")))


class MarkdownlintTest(unittest.TestCase):
    def test_generated_changelog_is_not_linted(self):
        """release-please leaves two blank lines after each heading (MD012), so the generated
        CHANGELOG.md is excluded; otherwise every release pull request fails lint-test."""
        cfg = markdownlint_config()
        self.assertTrue("CHANGELOG.md" in cfg.get("ignores", []) or cfg["config"].get("MD012") is False, cfg)

    @unittest.skipUnless(shutil.which("markdownlint-cli2"), "markdownlint-cli2 is not on the PATH")
    def test_release_please_changelog_passes(self):
        tmp = temp_dir("mdl-test-")
        shutil.copy(ROOT / ".markdownlint-cli2.jsonc", tmp)
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [Origin]", changelog)
        (tmp / "CHANGELOG.md").write_text(changelog.replace("## [Origin]", RELEASE_PLEASE_ENTRY + "## [Origin]"),
                                          encoding="utf-8")
        (tmp / "README.md").write_text("# demo\n\nText.\n", encoding="utf-8")
        out = subprocess.run(["markdownlint-cli2", "**/*.md"], cwd=tmp, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)


@unittest.skipUnless(shutil.which("gitleaks"), "gitleaks is not on the PATH")
class GitleaksConfigTest(unittest.TestCase):
    def scan(self, folder: Path) -> list[str]:
        report = temp_dir("gl-report-") / "report.json"  # never written into the scanned folder
        subprocess.run(["gitleaks", "dir", "--no-banner", "--redact", "--exit-code", "0",
                        "--config", str(ROOT / ".gitleaks.toml"), "--report-format", "json",
                        "--report-path", str(report), str(folder)],
                       check=True, capture_output=True, text=True)
        return [f["RuleID"] for f in json.loads(report.read_text(encoding="utf-8") or "[]")]

    def test_documentation_placeholders_stay_clean(self):
        self.assertEqual(self.scan(FIXTURES), [])

    def test_real_looking_values_are_found(self):
        """Values built at run time, so no secret-shaped string is ever committed."""
        def rand(n: int) -> str:
            return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(n))

        key = f"cfxk_{rand(20)}_{rand(6)}"
        tmp = temp_dir("gl-test-")
        (tmp / "server.cfg").write_text(f'sv_licenseKey "{key}"\n', encoding="utf-8")
        (tmp / "txadmin.env").write_text(f"TXHOST_API_TOKEN={secrets.token_hex(16)}\n", encoding="utf-8")
        found = set(self.scan(tmp))
        self.assertTrue({"cfx-server-key", "txadmin-api-token"} <= found, found)


if __name__ == "__main__":
    unittest.main()
