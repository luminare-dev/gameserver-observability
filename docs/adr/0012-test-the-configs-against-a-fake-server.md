# 0012. Test the configs against a fake server

- **Status:** accepted
- **Date:** 2026-10-21

## Context

A scrape config can be valid and still deliver nothing useful: a relabel rule that never matches,
a json_exporter path that misses its field, or a module name with a typo all pass the config
checks. A real game server cannot run in CI: it needs a license key, it must not be downloaded or
redistributed by this project, and it would have real players.

## Considered options

1. A fake server in standard-library Python that answers `/info.json`, `/dynamic.json`,
   `/players.json` and `/perf/` like the real one, plus a CI job that runs the real Prometheus,
   json_exporter and blackbox_exporter binaries against it.
2. Recorded responses served as static files.
3. Config checks only.

## Decision

Chosen option 1. The fake (`demo/fake-fxserver/fake_fxserver.py`) follows what the server's
source code at build 35245 does: the fields and their types, the histogram buckets and thread
timers, the basic-auth rule of `/perf/` (open when no user and password are set, `401` otherwise),
`Content-Type: text/plain` and the request-paranoia refusals. Its data is synthetic; the tick
times move with a load knob (`main_tick_ms`, also as a temporary spike) and the counters grow in
real time, which static files (option 2) cannot do. The CI job `exporters` installs the three
binaries by version and sha256 and runs `scripts/smoke_exporters.py`, which starts everything on
127.0.0.1, waits for the scrapes and checks the result in Prometheus: names, labels, values,
probes, and that `players.json` was never requested. The fake's own behaviour is covered by
unit tests in `ci / lint-test`.

## Consequences

- Good: a change that breaks a metric, a label or a probe fails CI, not a live server.
- Bad: the fake shows what the source code says, not what a running server does; where the two
  could differ (the exact version string, rate limits) the [metrics reference](../metrics.md)
  says so, and the check against a running server is still open.
- Bad: three more downloads to keep current by hand ([toolchain](../toolchain.md)).
