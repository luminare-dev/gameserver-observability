#!/usr/bin/env python3
"""Build the release source archive and its checksum file (Python standard library only).

Creates, from a git ref (normally the release tag):
  dist/<name>-<version>.tar.gz   `git archive` of the tracked files, with "<name>-<version>/" as
                                 the top folder (gzip -n via git, so the same commit gives the
                                 same bytes with the same git version)
  dist/SHA256SUMS                "<sha256>  <file>" lines, readable by `sha256sum -c`

The release workflow attests every file listed in SHA256SUMS (actions/attest) and uploads both.

Usage: python3 scripts/package_release.py --ref v0.1.0 [--name my-project] [--out dist]
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def version_from_ref(ref: str) -> str:
    m = re.fullmatch(r"v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)", ref.rsplit("/", 1)[-1])
    if not m:
        raise SystemExit(f"error: ref {ref!r} is not a vX.Y.Z tag; pass --version")
    return m.group(1)


def build(root: Path, ref: str, name: str, version: str, out: Path) -> list[Path]:
    if not NAME_RE.match(name):
        raise SystemExit(f"error: archive name {name!r} must be lower-case letters, digits, '.', '_' or '-'")
    out.mkdir(parents=True, exist_ok=True)
    archive = out / f"{name}-{version}.tar.gz"
    subprocess.run(["git", "-C", str(root), "archive", "--format=tar.gz", f"--prefix={name}-{version}/",
                    f"--output={archive}", ref], check=True)
    files = [archive]
    sums = out / "SHA256SUMS"
    sums.write_text("".join(f"{sha256_file(f)}  {f.name}\n" for f in files), encoding="utf-8")
    return files + [sums]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument("--ref", required=True, help="git ref to archive, normally the release tag (vX.Y.Z)")
    p.add_argument("--name", help="archive name (default: repository folder name)")
    p.add_argument("--version", help="version in the file name (default: from --ref)")
    p.add_argument("--out", type=Path, default=Path("dist"))
    p.add_argument("--root", type=Path, default=ROOT)
    args = p.parse_args(argv)
    root = args.root.resolve()
    name = (args.name or root.name).lower()
    version = args.version or version_from_ref(args.ref)
    out = args.out if args.out.is_absolute() else root / args.out
    for f in build(root, args.ref, name, version, out):
        print(f"{f.relative_to(root) if f.is_relative_to(root) else f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
