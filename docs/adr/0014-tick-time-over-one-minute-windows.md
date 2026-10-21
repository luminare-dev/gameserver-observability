# 0014. Tick time over one-minute windows

- **Status:** accepted
- **Date:** 2026-10-21

## Context

The alert asked for is "svMain p95 above 50 ms for 5 minutes". The histogram
`fxserver_tick_time_seconds` has a series per server and thread and is scraped every 15 seconds.
Dashboards and the alert need the percentiles per thread, so recording rules compute them once.
Two choices: the rate window of the recorded percentiles, and the names of the recorded series.
50 ms is the timer interval of `svMain` and a bucket bound of the histogram, so a percentile at the
threshold is exact.

## Considered options

1. One-minute windows (`[1m]`), names `server_thread:fxserver_tick_time_seconds:p95_1m` and so on.
2. Five-minute windows (`[5m]`), as most examples use, with the same alert.
3. Names without the level prefix, for example `fxserver:tick_time_seconds:p95_5m`.

## Decision

Chosen option 1. With a one-minute window, `for: 5m` means that every minute of those five had
more than 5 % slow ticks, which is what the alert says; with a five-minute window, one very bad
minute can keep the five-minute percentile above 50 ms for the whole window and fire the alert.
One minute holds four scrapes at the pack's interval, so `rate` still has samples when one scrape
fails. The names follow the Prometheus convention
`level:metric:operations`: the level `server_thread` lists exactly the labels the series keep, so
a reader knows what to group by, and the metric part keeps the unit.

## Consequences

- Good: a three-minute spike shows in the recorded p95 and does not fire the alert; a test
  (`tests/rules/tick.test.yml`) checks both. Each recorded series is tested against values worked
  out by hand (`tests/rules/recording.test.yml`), and the `exporters` run checks them on the fake
  server's histogram.
- Bad: a scrape interval above 30 seconds leaves fewer than two samples per window, and the
  recorded series go missing. The configuration page says to keep `/perf/` at 15 seconds; a
  slower setup needs its own copy of the rules with longer windows.
