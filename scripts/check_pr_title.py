#!/usr/bin/env python3
"""Check a pull request title (Python standard library only).

Pull requests are squash-merged, so the title becomes the commit message on main, and
release-please builds the changelog and release notes from it. The title must therefore:
  * follow Conventional Commits with one of the allowed types (see TYPES);
  * pass the wording check from scripts/forbidden_words.py (offer-free release notes).

Usage: python3 scripts/check_pr_title.py "feat(backup): add a restore drill"
       PR_TITLE="..." PR_AUTHOR="login" python3 scripts/check_pr_title.py      (how CI calls it)
Exit codes: 0 ok, 1 rejected, 2 no title given.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forbidden_words import check_string  # noqa: E402

# The types of the organization's CONTRIBUTING guide (release-please-config.json maps them to
# Keep a Changelog sections).
TYPES = ("feat", "fix", "docs", "refactor", "perf", "test", "style", "build", "ci", "chore", "revert", "security")
TITLE_RE = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[a-z0-9][a-z0-9._/-]*)\))?(?P<bang>!)?: (?P<subject>\S.*)$")
MAX_LENGTH = 100
# Bots whose titles follow Conventional Commits but start the summary with a capital ("Bump ...").
# Only the lower-case rule is relaxed for them; format, types, length and wording still apply.
CAPITALISED_SUMMARY_OK = ("dependabot[bot]",)


def problems(title: str, author: str = "") -> list[str]:
    title = title.strip()
    out: list[str] = []
    m = TITLE_RE.match(title)
    if not m:
        out.append("not a Conventional Commit: expected '<type>(<optional scope>): <summary>', "
                   "for example 'fix(backup): retry the upload after a timeout'")
    else:
        if m.group("type") not in TYPES:
            out.append(f"type {m.group('type')!r} is not one of: {', '.join(TYPES)}")
        subject = m.group("subject")
        if subject.endswith("."):
            out.append("the summary must not end with a full stop")
        if (subject[:1].isupper() and not subject.split()[0].isupper()
                and author not in CAPITALISED_SUMMARY_OK):
            out.append("the summary must start with a lower-case letter (imperative mood: 'add', 'fix')")
    if len(title) > MAX_LENGTH:
        out.append(f"the title is {len(title)} characters long; keep it to {MAX_LENGTH}")
    out += [f"wording: {e.split(': ', 1)[-1]}" for e in check_string(title)]
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    title = argv[0] if argv else os.environ.get("PR_TITLE", "")
    if not title.strip():
        print("error: no pull request title given", file=sys.stderr)
        return 2
    found = problems(title, os.environ.get("PR_AUTHOR", ""))
    for prob in found:
        print(f"error: {prob}")
    if not found:
        print(f"ok: {title.strip()!r}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
