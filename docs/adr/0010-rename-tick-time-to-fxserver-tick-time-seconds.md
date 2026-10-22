# 0010. Rename tickTime to fxserver_tick_time_seconds

- **Status:** accepted
- **Date:** 2026-10-21

## Context

`/perf/` serves one histogram, `tickTime`, with a label `name` that holds the server thread
(`svMain`, `svNetwork`, `svSync`); its unit is seconds. In a Prometheus that also monitors other
software, `tickTime` says neither where it comes from nor its unit, and `name` is the label
name that `scripts/check_pack.py` rejects because elsewhere it would hold a player's name. A
server version may also add metrics to `/perf/` that nobody has reviewed.

## Considered options

1. Keep only the histogram and rename it in `metric_relabel_configs`:
   `fxserver_tick_time_seconds_bucket`, `_sum` and `_count`, with the label `thread`.
2. Keep the server's names (`tickTime_*` with `name`).
3. Record renamed copies with recording rules and keep the originals.

## Decision

Chosen option 1, because the names then follow the Prometheus naming conventions (a prefix for
the source, the unit in the name), `thread` says what the label holds, and the rename happens
once, at the scrape, so rules and dashboards use only the new names. The job first keeps only
`tickTime_bucket`, `tickTime_sum` and `tickTime_count`, then renames them, copies `name` to
`thread` and drops `name`. `scripts/check_pack.py` fails when a job that scrapes `/perf/` lacks
the keep rule, the copy or the drop, or copies after the drop, and `scripts/smoke_exporters.py`
checks in CI that exactly the renamed series arrive, with no `name` label and nothing else from
`/perf/`. Option 3 would store every series twice, and option 2 leaves the generic names in
shared dashboards.

## Consequences

- Good: rules and dashboards read clearly, and other metrics on `/perf/` never enter the
  database unreviewed.
- Bad: queries written for the server's own names (for example from other projects) must be
  translated: `tickTime_bucket{name="svMain"}` is `fxserver_tick_time_seconds_bucket{thread="svMain"}`.
