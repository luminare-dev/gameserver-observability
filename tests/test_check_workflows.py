"""Tests for scripts/check_workflows.py (SHA pins and workflow policy)."""

from __future__ import annotations

import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_workflows as cw  # noqa: E402

SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"


def workflow(body: str, top: str = "permissions: {}\n") -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="wf-test-"))
    unittest.addModuleCleanup(shutil.rmtree, tmp, ignore_errors=True)
    (tmp / ".github" / "workflows").mkdir(parents=True)
    (tmp / ".github" / "workflows" / "w.yml").write_text("name: w\non: push\n" + top + "jobs:\n" + body,
                                                         encoding="utf-8")
    return tmp


def errors(root: Path) -> list[str]:
    errs, _ = cw.check_file(root / ".github" / "workflows" / "w.yml", root)
    return errs


GOOD_CHECKOUT = f"""  a:
    runs-on: ubuntu-24.04
    steps:
      - name: Check out
        uses: actions/checkout@{SHA} # v7.0.1
        with:
          persist-credentials: false
"""


class PinTest(unittest.TestCase):
    def test_good(self):
        self.assertEqual(errors(workflow(GOOD_CHECKOUT)), [])

    def test_tag_is_rejected(self):
        body = GOOD_CHECKOUT.replace(f"@{SHA} # v7.0.1", "@v7")
        self.assertTrue(any("not pinned" in e for e in errors(workflow(body))))

    def test_short_sha_is_rejected(self):
        body = GOOD_CHECKOUT.replace(f"@{SHA}", f"@{SHA[:12]}")
        self.assertTrue(any("not pinned" in e for e in errors(workflow(body))))

    def test_version_comment_required(self):
        body = GOOD_CHECKOUT.replace(" # v7.0.1", "")
        self.assertTrue(any("version comment" in e for e in errors(workflow(body))))

    def test_branch_is_rejected(self):
        body = f"""  a:
    runs-on: ubuntu-24.04
    steps:
      - uses: someone/action@main
"""
        self.assertTrue(any("not pinned" in e for e in errors(workflow(body))))

    def test_remote_reusable_workflow_needs_sha(self):
        body = "  a:\n    uses: luminare-dev/oss-template/.github/workflows/reusable-ci.yml@v1\n"
        self.assertTrue(any("not pinned" in e for e in errors(workflow(body))))
        body = f"  a:\n    uses: luminare-dev/oss-template/.github/workflows/reusable-ci.yml@{SHA} # v0.1.0\n"
        self.assertEqual(errors(workflow(body)), [])

    def test_local_reference_is_allowed(self):
        self.assertEqual(errors(workflow("  a:\n    uses: ./.github/workflows/reusable-ci.yml\n")), [])

    def test_docker_needs_digest(self):
        body = "  a:\n    runs-on: ubuntu-24.04\n    steps:\n      - uses: docker://alpine:3\n"
        self.assertTrue(any("sha256" in e for e in errors(workflow(body))))
        digest = "a" * 64
        body = f"  a:\n    runs-on: ubuntu-24.04\n    steps:\n      - uses: docker://alpine@sha256:{digest}\n"
        self.assertEqual(errors(workflow(body)), [])

    def test_quoted_uses(self):
        body = GOOD_CHECKOUT.replace(f"uses: actions/checkout@{SHA} # v7.0.1",
                                     f"uses: 'actions/checkout@{SHA}' # v7.0.1")
        self.assertEqual(errors(workflow(body)), [])


class PolicyTest(unittest.TestCase):
    def test_checkout_without_persist_credentials_false(self):
        body = GOOD_CHECKOUT.replace("        with:\n          persist-credentials: false\n", "")
        self.assertTrue(any("persist-credentials" in e for e in errors(workflow(body))))

    def test_compact_step_form(self):
        body = f"""  a:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@{SHA} # v7.0.1
        with:
          fetch-depth: 0
          persist-credentials: false
      - run: echo ok
"""
        self.assertEqual(errors(workflow(body)), [])

    def test_persist_credentials_of_next_step_does_not_count(self):
        body = f"""  a:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@{SHA} # v7.0.1
      - uses: actions/checkout@{SHA} # v7.0.1
        with:
          persist-credentials: false
"""
        self.assertEqual(sum("persist-credentials" in e for e in errors(workflow(body))), 1)

    def test_pull_request_target_is_rejected(self):
        root = workflow(GOOD_CHECKOUT)
        wf = root / ".github" / "workflows" / "w.yml"
        wf.write_text(wf.read_text().replace("on: push", "on: pull_request_target"), encoding="utf-8")
        self.assertTrue(any("pull_request_target" in e for e in errors(root)))

    def test_top_level_permissions_required(self):
        self.assertTrue(any("permissions" in e for e in errors(workflow(GOOD_CHECKOUT, top=""))))
        self.assertTrue(any("permissions" in e for e in errors(workflow(GOOD_CHECKOUT, top="permissions: read-all\n"))))

    def test_secrets_inherit_is_rejected(self):
        body = "  a:\n    uses: ./.github/workflows/x.yml\n    secrets: inherit\n"
        self.assertTrue(any("inherit" in e for e in errors(workflow(body))))


class RepositoryTest(unittest.TestCase):
    def test_this_repository_passes(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cw.main([str(ROOT)])
        self.assertEqual(code, 0, buf.getvalue())

    def test_every_uses_line_in_this_repository_is_a_sha_or_local(self):
        for path in cw.workflow_files(ROOT):
            for line in path.read_text(encoding="utf-8").splitlines():
                m = cw.USES_RE.match(line)
                if m:
                    ref = m.group("ref")
                    with self.subTest(file=path.name, ref=ref):
                        self.assertTrue(ref.startswith("./") or cw.PINNED_RE.match(ref), ref)


if __name__ == "__main__":
    unittest.main()
