# Cardinality budget

The budget is **at most 2,000 series per game server**, for everything that monitors it: this
pack's jobs plus the host and database exporters that run next to it. The pack's own jobs stay far
below that, and every job has a `sample_limit`, so a target that suddenly serves more series fails
its scrape (`up` 0) instead of filling the database. [Metrics reference](metrics.md) lists every
series.

## Measured: the pack's jobs

Measured on 2026-10-21 with `scripts/smoke_exporters.py`: Prometheus 3.15.0, json_exporter 0.8.0
and blackbox_exporter 0.29.0 with this repository's configs, scraping the fake server
(`scrape_samples_post_metric_relabeling` per target). The numbers do not depend on the server's
load or player count: the threads, the buckets and the probe phases are fixed.

| Job and target | Samples per scrape | Plus Prometheus' own series | `sample_limit` |
|---|---|---|---|
| `fxserver_perf` | 51 (3 threads × (15 buckets + sum + count)) | 5 | 100 |
| `fxserver_json`, module `fxserver_dynamic` | 2 | 5 | 20 |
| `fxserver_json`, module `fxserver_info` | 2 | 5 | 20 |
| `fxserver_blackbox`, module `tcp_connect` | 8 | 5 | 60 |
| `fxserver_blackbox`, module `http_fxserver_info` | 18 | 5 | 60 |
| `fxserver_blackbox`, module `http_401_expected` | 18 | 5 | 60 |
| **Total, 6 targets** | **99** | **30** | |

So one game server costs **129 series** with the default jobs. Prometheus' own series are `up`,
`scrape_duration_seconds`, `scrape_samples_scraped`, `scrape_samples_post_metric_relabeling` and
`scrape_series_added`, five per target. The optional `fxserver_tunnel` job adds one HTTPS probe
(the HTTP series plus a few TLS series, not measured here, at most 60 by its limit) and five
Prometheus series.

## The whole budget per server

| Part | Series | How it is kept there |
|---|---|---|
| This pack, default jobs | 129 measured; at most 350 by the sample limits (100 + 2 × 20 + 3 × 60, plus 30 from Prometheus) | `sample_limit` per job |
| This pack, tunnel probe | at most 65 | `sample_limit: 60` |
| Reserve: node_exporter on the game host | 900 | not part of this pack: set `sample_limit` on your job and filter collectors you do not use |
| Reserve: mysqld_exporter | 400 | the same |
| Reserve: tunnel connector metrics | 150 | the same |
| Reserve: textfile metrics (for example the installed build and its age) | 10 | the same |
| **Total** | **at most 1,875** | |

The reserves are planning values for the exporters that monitor the host and the database; this
repository does not ship their configs. With the measured 129 series for the default jobs instead
of their limit of 350, and without the tunnel probe, 411 of the 2,000 series stay free when the
reserves are used up (346 with the tunnel probe at its limit).

## What is left out, and why

- **One series per resource.** `info.json` lists every started resource; a server with a few
  hundred resources would add as many series. The pack collects no resource series.
- **One series per player.** Never collected, for privacy and for cardinality: a busy server
  would add series with every join. The player count is one series, `fxserver_clients`.
- **Other `/perf/` metrics.** The scrape job keeps only the tick-time histogram, so a server
  version that adds metrics to `/perf/` does not grow the budget.

## What changes the numbers

- **Each further game server** adds the same 129 series (its own targets and `server` label).
- **An upgrade** changes the `version` and `build` labels of `fxserver_info`: one new series,
  while the old one stops getting samples.
- **Another bucket layout** in a future server version changes the 51 `/perf/` series; the
  `sample_limit` of 100 holds up to 31 bucket series per thread (with `+Inf`).

## Check it on your Prometheus

```promql
# Samples per scrape for each target of the pack (compare with the table above)
scrape_samples_post_metric_relabeling{job=~"fxserver_.*"}

# Series per game server, all jobs that carry the server label
count({server="game-01"})

# New series per scrape: should be 0 in steady state; a steady stream means churn
sum by (job) (scrape_series_added{job=~"fxserver_.*"})
```

Prometheus' web interface also lists the metric names with the most series under
**Status → TSDB status**.
