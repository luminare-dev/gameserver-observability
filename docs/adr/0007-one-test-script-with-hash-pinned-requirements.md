# 0007. One test script with hash-pinned requirements

- **Status:** accepted
- **Date:** 2026-10-21

## Context

The template runs the repository's test command in two places: in `ci / lint-test`, where a
virtual environment with `requirements-dev.txt` is already on the `PATH`, and in the release build
on the tag, which runs on the bare runner Python without any installed packages. The pack's tests
parse YAML, so they need PyYAML in both places, installed the same hash-pinned way as every other
Python tool. The system Python of `ubuntu-24.04` refuses `pip install` outside a virtual
environment (PEP 668).

## Considered options

1. A script, `scripts/test.sh`, that creates its own virtual environment, installs
   `requirements-test.txt` with `--require-hashes --only-binary=:all:` and runs the tests; both
   workflows pass `bash scripts/test.sh` as `test-command`.
2. A long inline `test-command` string repeated in `ci.yml` and `release.yml`.
3. Tests limited to the Python standard library.

## Decision

Chosen option: "one script", because a pull request, the release tag and a contributor's machine
then run exactly the same command, and the workflows stay short. `requirements-test.txt` is
compiled from `requirements-test.in` with `pip-compile --generate-hashes` on Python 3.12 (the
runner's Python), so Dependabot can recompile it. `tests/test_pack_repo.py` checks that both
workflows pass the same command and that every requirement has a version and a hash. The script
sets `PACK_TESTS_STRICT=1`, so a missing package fails the run; a bare
`python3 -m unittest discover -s tests` without PyYAML skips the YAML tests instead of erroring.
In CI the script also installs the sha256-pinned gitleaks binary, so the secret-rule tests run
([ADR 0008](0008-extra-secret-rule-for-any-cfxk-token.md)). Outside CI the environment lives in
the user's cache folder, and one that belongs to another user is never reused. Further checks of
the pack belong in the same script.

## Consequences

- Good: no unpinned package is ever installed, and the release fails if the tests fail on the tag.
- Good: `bash scripts/test.sh` is the only command a contributor needs to remember.
- Bad: every run installs the requirements (in CI into a fresh environment; a few seconds, needs
  PyPI).
