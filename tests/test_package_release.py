"""Tests for scripts/package_release.py (needs git)."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import package_release as pr  # noqa: E402


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def scratch_repo() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="pkg-test-"))
    unittest.addModuleCleanup(shutil.rmtree, tmp, ignore_errors=True)
    repo = tmp / "demo-project"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("not in the archive\n", encoding="utf-8")
    git(repo, "add", "README.md", "src/app.py")
    git(repo, "commit", "-q", "-m", "feat: first")
    git(repo, "tag", "v0.1.0")
    return repo


class PackageTest(unittest.TestCase):
    def test_archive_and_checksums(self):
        repo = scratch_repo()
        files = pr.build(repo, "v0.1.0", "demo-project", "0.1.0", repo / "dist")
        archive, sums = files
        self.assertEqual(archive.name, "demo-project-0.1.0.tar.gz")
        with tarfile.open(archive) as tar:
            names = sorted(tar.getnames())
        self.assertIn("demo-project-0.1.0/README.md", names)
        self.assertIn("demo-project-0.1.0/src/app.py", names)
        self.assertNotIn("demo-project-0.1.0/untracked.txt", names)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.assertEqual(sums.read_text(encoding="utf-8"), f"{digest}  demo-project-0.1.0.tar.gz\n")
        check = subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=repo / "dist", capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_reproducible(self):
        repo = scratch_repo()
        a = pr.build(repo, "v0.1.0", "demo-project", "0.1.0", repo / "dist-a")[0].read_bytes()
        b = pr.build(repo, "v0.1.0", "demo-project", "0.1.0", repo / "dist-b")[0].read_bytes()
        self.assertEqual(a, b)

    def test_version_from_ref(self):
        self.assertEqual(pr.version_from_ref("v1.2.3"), "1.2.3")
        self.assertEqual(pr.version_from_ref("refs/tags/v0.1.0"), "0.1.0")
        with self.assertRaises(SystemExit):
            pr.version_from_ref("main")

    def test_bad_name(self):
        repo = scratch_repo()
        with self.assertRaises(SystemExit):
            pr.build(repo, "v0.1.0", "Bad Name", "0.1.0", repo / "dist")


if __name__ == "__main__":
    unittest.main()
