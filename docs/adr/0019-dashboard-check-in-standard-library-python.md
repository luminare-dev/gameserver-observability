# 0019. Dashboard check in standard-library Python

- **Status:** accepted
- **Date:** 2026-10-21

## Context

The dashboards must keep rules that no Grafana tool knows: titles without platform or vendor
marks (the name check of `scripts/forbidden_words.py`), no hard-coded data source uid, only
metrics that `docs/metrics.md` describes, and no label that could identify a player or that
holds a host address (`instance`, ADR 0013). The check has to run in `ci / lint-test`, in the
`promtool` job, which installs nothing from PyPI, and on a contributor's machine. Grafana's own
dashboard linter is a Go program with rules about Grafana conventions; PromQL parsers for Python
are packages to pin, and some need compiled extensions.

## Considered options

1. A Python script that needs only the standard library: it reads each query with a small
   tokenizer (metric names, label names, aggregations), and hands every query to
   `promtool check rules` for the full parse.
2. Grafana's dashboard linter plus a script for the rules it does not know.
3. A Python PromQL parser package, pinned in `requirements-test.txt`.

## Decision

Chosen option 1, because it runs wherever Python 3.10 runs and the full PromQL parse comes from
the promtool this repository already pins (ADR 0006). `scripts/lint_dashboards.py` reuses the
privacy patterns of `scripts/check_pack.py` and the name rules of `scripts/forbidden_words.py`,
so all three checks agree. It also requires every selector to sit inside an aggregation that
keeps only the labels it names (`sum`, `max`, `count` and the like, with `by (...)` or no
clause), so that a panel shows only the labels its query chose. Option 2 adds a toolchain and
still needs the script. Option 3 adds a dependency for what promtool already does.

## Consequences

- Good: one command checks the dashboards and their shareable copies and writes the copies
  (`--fix`); the unit tests break each rule once and expect the check to report it.
- Bad: about 800 lines to maintain. The tokenizer is not a PromQL parser: it reads only what the
  rules need, and a query it cannot read fails the check instead of passing it. Without promtool
  on the PATH the full parse is skipped, except in the `promtool` job, which requires it.
