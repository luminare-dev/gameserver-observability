#!/usr/bin/env python3
"""Policy check for GitHub Actions workflows (Python standard library only).

Fails (exit 1) when a workflow or action file under .github/:
  * uses a remote action or reusable workflow that is not pinned to a full 40-character commit
    SHA followed by a version comment ("uses: owner/repo@<sha> # v1.2.3");
  * uses a Docker image without a sha256 digest;
  * is triggered by pull_request_target;
  * has no top-level "permissions: {}" (every job then asks for what it needs);
  * passes "secrets: inherit" to a reusable workflow;
  * checks out code without "persist-credentials: false".
Local references ("uses: ./.github/workflows/x.yml") are allowed: they are pinned by the commit
that runs them.

Usage: python3 scripts/check_workflows.py [--list] [ROOT]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USES_RE = re.compile(r"^(?P<indent>\s*)(?:-\s+)?uses:\s*(?P<quote>['\"]?)(?P<ref>[^'\"\s#]+)(?P=quote)\s*(?:#\s*(?P<comment>.*))?$")
PINNED_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[^@\s]+)?@[0-9a-f]{40}$")
VERSION_COMMENT_RE = re.compile(r"^v?\d+(?:\.\d+){1,2}\b")
DOCKER_RE = re.compile(r"^docker://[^@\s]+@sha256:[0-9a-f]{64}$")


def workflow_files(root: Path) -> list[Path]:
    gh = root / ".github"
    files = sorted(list(gh.glob("workflows/*.yml")) + list(gh.glob("workflows/*.yaml")))
    files += sorted(p for p in gh.glob("actions/**/action.y*ml"))
    files += [p for p in (root / "action.yml", root / "action.yaml") if p.is_file()]
    return files


def check_file(path: Path, root: Path) -> tuple[list[str], list[tuple[str, str, str]]]:
    rel = path.relative_to(root).as_posix()
    errors: list[str] = []
    pins: list[tuple[str, str, str]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    is_workflow = "/workflows/" in f"/{rel}"
    for no, line in enumerate(lines, start=1):
        m = USES_RE.match(line)
        if m:
            ref, comment = m.group("ref"), (m.group("comment") or "").strip()
            if ref.startswith("./"):
                pins.append((rel, ref, "local"))
            elif ref.startswith("docker://"):
                if not DOCKER_RE.match(ref):
                    errors.append(f"{rel}:{no}: Docker image {ref!r} is not pinned by sha256 digest")
                pins.append((rel, ref, "docker"))
            elif not PINNED_RE.match(ref):
                errors.append(f"{rel}:{no}: {ref!r} is not pinned to a full 40-character commit SHA")
            elif not VERSION_COMMENT_RE.match(comment):
                errors.append(f"{rel}:{no}: {ref!r} needs a version comment such as '# v1.2.3'")
            else:
                pins.append((rel, ref, comment.split()[0]))
            if ref.split("@", 1)[0].lower() in ("actions/checkout",):
                if not _step_has(lines, no - 1, len(m.group("indent")), r"persist-credentials:\s*false\b"):
                    errors.append(f"{rel}:{no}: actions/checkout without 'persist-credentials: false'")
        if re.match(r"^\s*secrets:\s*inherit\b", line):
            errors.append(f"{rel}:{no}: 'secrets: inherit' passes every secret; pass only the ones needed")
        if re.search(r"\bpull_request_target\b", line.split("#", 1)[0]):
            errors.append(f"{rel}:{no}: pull_request_target is not allowed (use pull_request)")
    if is_workflow and not any(re.match(r"^permissions:\s*\{\s*\}\s*(#.*)?$", ln) for ln in lines):
        errors.append(f"{rel}: no top-level 'permissions: {{}}'")
    return errors, pins


def _step_has(lines: list[str], idx: int, uses_indent: int, pattern: str) -> bool:
    """Look through the rest of the step that starts at lines[idx] for a pattern."""
    first = lines[idx]
    step_indent = len(first) - len(first.lstrip(" "))
    for line in lines[idx + 1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= step_indent and (stripped.startswith("- ") or indent < uses_indent):
            break
        if re.search(pattern, line):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument("root", nargs="?", type=Path, default=ROOT)
    p.add_argument("--list", action="store_true", help="print every reference with its pin")
    args = p.parse_args(argv)
    root = args.root.resolve()
    files = workflow_files(root)
    if not files:
        print("error: no workflow files found")
        return 1
    all_errors: list[str] = []
    all_pins: list[tuple[str, str, str]] = []
    for path in files:
        errors, pins = check_file(path, root)
        all_errors += errors
        all_pins += pins
    if args.list:
        for rel, ref, version in all_pins:
            print(f"{rel}\t{ref}\t{version}")
    for e in all_errors:
        print(f"error: {e}")
    remote = sum(1 for _, _, v in all_pins if v not in ("local", "docker"))
    print(f"{len(all_errors)} error(s); {len(files)} file(s), {remote} SHA-pinned remote reference(s), "
          f"{sum(1 for _, _, v in all_pins if v == 'local')} local reference(s)")
    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main())
