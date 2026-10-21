#!/usr/bin/env python3
"""Switch the README byline between the studio and the personal variant (BYLINE_MODE).

The README keeps both variants in marker-delimited blocks. The active block is plain Markdown
between two complete HTML comments; the inactive block sits inside one HTML comment, so GitHub
does not render it:

    <!-- byline:studio -->                       <!-- byline:personal
    *a ... open-source project*                  *by {{AUTHOR_NAME}} ...*
    <!-- /byline:studio -->                      /byline:personal -->

Commands:
    set_byline.py studio      activate the studio byline (default mode)
    set_byline.py personal    activate the personal byline (fallback)
    set_byline.py status      print the current mode
    set_byline.py verify      exit 1 unless README, docs/brand/KIT_VERSION and NOTICE agree

The brand files are not in the README: switching also means swapping docs/brand/ and NOTICE,
which come from the brand-repos generator. The script prints the exact steps.

Exit codes: 0 ok, 1 mismatch (verify, or --expect), 2 malformed README.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODES = ("studio", "personal")
BRAND_VARIANT = {"studio": "studio", "personal": "neutral"}  # README mode -> brand-repos variant
STUDIO_NAME = "Luminare Development"

BLOCK_RE = re.compile(
    r"^(?P<open><!-- byline:(?P<kind>studio|personal)(?P<open_close> -->)?)[ \t]*\n"
    r"(?P<body>.*?)\n"
    r"(?P<close>(?P<close_open><!-- )?/byline:(?P=kind) -->)[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
ANY_MARKER_RE = re.compile(r"byline:(studio|personal)")


class ReadmeError(Exception):
    pass


def parse_blocks(text: str) -> list[re.Match]:
    blocks = list(BLOCK_RE.finditer(text))
    if not blocks:
        raise ReadmeError("no byline blocks found (expected '<!-- byline:studio -->' ... '<!-- /byline:studio -->')")
    found_markers = len(ANY_MARKER_RE.findall(text))
    if found_markers != 2 * len(blocks):
        raise ReadmeError(f"{found_markers} byline markers but {len(blocks)} complete blocks; a marker is malformed")
    for b in blocks:
        active_open, active_close = b.group("open_close") is not None, b.group("close_open") is not None
        if active_open != active_close:
            raise ReadmeError(f"byline:{b.group('kind')} block is half active (line "
                              f"{text.count(chr(10), 0, b.start()) + 1}); fix the markers by hand")
        if "<!--" in b.group("body") or "-->" in b.group("body"):
            raise ReadmeError(f"byline:{b.group('kind')} block contains an HTML comment; it cannot be toggled")
    kinds = {b.group("kind") for b in blocks}
    if kinds != set(MODES):
        raise ReadmeError(f"both variants must be present, found only {sorted(kinds)}")
    return blocks


def current_mode(text: str) -> str:
    blocks = parse_blocks(text)
    active = {b.group("kind") for b in blocks if b.group("open_close") is not None}
    if len(active) != 1:
        raise ReadmeError(f"expected exactly one active variant, found {sorted(active) or 'none'}")
    return active.pop()


def render_block(kind: str, body: str, active: bool) -> str:
    if active:
        return f"<!-- byline:{kind} -->\n{body}\n<!-- /byline:{kind} -->"
    return f"<!-- byline:{kind}\n{body}\n/byline:{kind} -->"


def set_mode(text: str, mode: str) -> str:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    parse_blocks(text)
    return BLOCK_RE.sub(lambda b: render_block(b.group("kind"), b.group("body"), b.group("kind") == mode), text)


def visible_text(text: str) -> str:
    """The text GitHub renders: everything outside HTML comments."""
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def brand_variant(brand_dir: Path) -> str | None:
    kv = brand_dir / "KIT_VERSION"
    if not kv.is_file():
        return None
    m = re.search(r"^variant:\s*(\S+)", kv.read_text(encoding="utf-8"), re.MULTILINE)
    return m.group(1) if m else None


def notice_variant(notice: Path) -> str | None:
    if not notice.is_file():
        return None
    return "studio" if STUDIO_NAME in notice.read_text(encoding="utf-8") else "neutral"


def consistency_problems(root: Path, mode: str) -> list[str]:
    want = BRAND_VARIANT[mode]
    problems = []
    bv = brand_variant(root / "docs" / "brand")
    if bv is None:
        problems.append("docs/brand/KIT_VERSION is missing or has no 'variant:' line")
    elif bv != want:
        problems.append(f"docs/brand/ holds the {bv} variant, but the README byline is {mode} (needs {want})")
    nv = notice_variant(root / "NOTICE")
    if nv is None:
        problems.append("NOTICE is missing")
    elif nv != want:
        problems.append(f"NOTICE is the {nv} text, but the README byline is {mode} (needs {want})")
    return problems


def swap_instructions(mode: str, slug: str) -> str:
    v = BRAND_VARIANT[mode]
    return "\n".join([
        f"Brand files for '{mode}' (brand-repos variant '{v}'):",
        f"  1. In brand-repos/repos.yaml set 'variant: {v}' for slug '{slug}', then run build_repos.py.",
        f"  2. cp brand-repos/out/{slug}/{v}/* docs/brand/     (headers, social preview, KIT_VERSION)",
        f"  3. cp brand-repos/out/{slug}/NOTICE NOTICE         (fill {{{{AUTHOR_NAME}}}} and {{{{YEAR}}}} again)",
        "  4. Upload docs/brand/social-preview-1280x640.png under Settings -> General -> Social preview.",
        "  5. Run: python3 scripts/set_byline.py verify",
    ])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=MODES + ("status", "verify"))
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--readme", default="README.md", help="README path relative to --root")
    p.add_argument("--slug", help="repository slug for the printed instructions (default: folder name)")
    p.add_argument("--expect", choices=MODES, help="with 'status' or 'verify': exit 1 unless the README is in this mode")
    args = p.parse_args(argv)
    root = args.root.resolve()
    readme = root / args.readme
    slug = args.slug or root.name
    try:
        text = readme.read_text(encoding="utf-8")
        mode = current_mode(text)
    except (OSError, ReadmeError) as exc:
        print(f"error: {readme}: {exc}", file=sys.stderr)
        return 2

    if args.command == "status":
        print(mode)
        return 1 if args.expect and args.expect != mode else 0
    if args.command == "verify":
        problems = consistency_problems(root, mode)
        if args.expect and args.expect != mode:
            problems.insert(0, f"README byline is {mode}, expected {args.expect}")
        for prob in problems:
            print(f"error: {prob}")
        if problems:
            target = args.expect or mode
            if target != mode:
                print(f"run: python3 scripts/set_byline.py {target}")
            print(swap_instructions(target, slug))
            return 1
        print(f"ok: README byline, docs/brand/ and NOTICE all use the {mode} variant")
        return 0

    new_text = set_mode(text, args.command)
    if new_text != text:
        readme.write_text(new_text, encoding="utf-8")
        print(f"README byline switched: {mode} -> {args.command}")
    else:
        print(f"README byline already {args.command}")
    problems = consistency_problems(root, args.command)
    if problems:
        for prob in problems:
            print(f"todo: {prob}")
        print(swap_instructions(args.command, slug))
    return 0


if __name__ == "__main__":
    sys.exit(main())
