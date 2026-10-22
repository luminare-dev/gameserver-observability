# 0011. Pack check in standard-library Python

- **Status:** accepted
- **Date:** 2026-10-21

## Context

The pack's configs must parse and must keep the privacy rules (no `players.json`, no per-player
labels, passwords only from files) before a release ships them. promtool checks Prometheus
configs, and both exporters have `--config.check`, but json_exporter silently ignores unknown keys,
so a misspelt key drops a metric without an error, and none of the tools knows the privacy rules.
The check has to run in `ci / lint-test`, in the `promtool` job (which installs nothing from PyPI)
and on a contributor's machine.

## Considered options

1. A Python script that needs only the standard library, with its own reader for the YAML subset
   the configs use.
2. A Python script that uses PyYAML (pinned in `requirements-test.txt`).
3. Only the tools' own checks.

## Decision

Chosen option 1, because the check then runs anywhere Python 3.10 runs, before anything is
installed, which the `promtool` job needs. `scripts/check_pack.py` reads the subset of YAML the
configs use (block and one-line flow collections, plain and quoted scalars, comments) and refuses
everything else, such as anchors, block scalars, multi-line values or
YAML 1.1 values like `yes` or `0755`, instead of guessing. The unit tests compare its result with
PyYAML for every config file and for sample documents. On 2026-10-21 it was also run over 214
YAML files from this project's repositories and from installed Python packages: it read
52 of them exactly as PyYAML does, refused the other 162 and read none differently. The script
then checks the json_exporter schema, the privacy rules, addresses, module references and job
names, and runs `promtool check config --lint=all` when promtool is on the PATH; the `promtool`
job requires it (`--require-promtool`).

## Consequences

- Good: one command checks everything about the configs, with no dependency to pin or update.
- Bad: about 360 lines of reader code to maintain. They are covered by unit tests and limited to
  the subset; a config that needs more YAML than that fails the check and the reader has to be
  extended.
