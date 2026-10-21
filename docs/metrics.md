# Metrics reference

Every series this pack collects, where it comes from and how far it is verified. All of them are
collected from outside the server process: Prometheus scrapes `/perf/` on the game port directly
and asks json_exporter and blackbox_exporter for the rest
([`prometheus/scrape/fxserver.yml`](../prometheus/scrape/fxserver.yml)). Counts only: no series
and no label holds a player's name, identifier, address or anything else tied to one player
([Not collected](#not-collected)). How many series this makes per server:
[cardinality budget](cardinality.md). The rules in `rules/` add
[recorded series](#recorded-series-rulesfxserverrecordingyml) and also read a few
[series of other exporters](#series-the-rules-read-from-other-exporters), and the dashboard reads
[a few more](#series-the-dashboard-reads-from-other-exporters).

## How far each metric is verified

The **Verified** column says what was checked for the source field on the game server:

- **source**: the endpoint, the field, its type and its access rule were read in the FXServer
  source code of build 35245 (commit [`6efb47d`](https://github.com/citizenfx/fivem/tree/6efb47dff473c0e2a12fb50b08d74c0eb24a50d5/code/components/citizen-server-impl/src),
  the Recommended build this project pins), on 2026-10-21.
- **exporter**: the metric is made by the exporter or by Prometheus itself, not by the game
  server.
- **live**: the field was read from the real endpoint through the exporter with this pack's
  module (only possible for the public version list, not for a game server).
- **unverified**: an assumption; the row says which one.

No row has been checked against a running FXServer yet. That needs a server with a license key;
until then this is listed under Limitations in the README, and the [probe log](probe-log.md)
holds the commands for that check and its empty result tables. The source files behind the rows
were compared with those of build 37692 (commit
[`ccd9221`](https://github.com/citizenfx/fivem/tree/ccd92212b96d4633897450940a57dc61dc2bc5b2/code/components/citizen-server-impl/src)),
the Latest build on 2026-10-22: the endpoint handlers, the tick-time histograms and the version
string's build script are unchanged, and so is the code around `onesync_enabled` (README,
Results).

The exported side is checked for every row except the optional tunnel probe:
`scripts/smoke_exporters.py` (the CI job `exporters`) runs Prometheus 3.15.0, json_exporter 0.8.0
and blackbox_exporter 0.29.0 with these configs against the fake server
(`demo/fake-fxserver/fake_fxserver.py`) and a synthetic version list, which answer with the shapes
listed here, and checks the metric names, labels and values that arrive in Prometheus, and the
recorded series of the rules.

Every series also has the labels `job` (the scrape job) and `instance` (for `/perf/` the
`host:port`, for the exporter jobs the probed URL or address). `server` is the label you set per
game server in the scrape config. Because `instance` can hold a host address or hostname, shared
views group by `server` and leave `instance` out
([ADR 0013](adr/0013-probed-target-in-the-instance-label.md)).

## Job `fxserver_perf`: `/perf/` on the game port

| Metric | Type | Labels | Source endpoint and field | Verified |
|---|---|---|---|---|
| `fxserver_tick_time_seconds_bucket` | counter (histogram bucket) | `server`, `thread`, `le` | `GET /perf/`: `tickTime_bucket{name="…",le="…"}` | source |
| `fxserver_tick_time_seconds_sum` | counter (seconds) | `server`, `thread` | `GET /perf/`: `tickTime_sum{name="…"}` | source |
| `fxserver_tick_time_seconds_count` | counter (ticks) | `server`, `thread` | `GET /perf/`: `tickTime_count{name="…"}` | source |

- **What it measures:** the time each server thread spends on one tick, measured in whole
  milliseconds and recorded in seconds
  ([`GameServer.cpp`](https://github.com/citizenfx/fivem/blob/6efb47dff473c0e2a12fb50b08d74c0eb24a50d5/code/components/citizen-server-impl/src/GameServer.cpp)).
  `thread` is `svMain` (server frame with the resources' work, a timer every 50 ms),
  `svNetwork` (network packets, every 10 ms) or `svSync` (OneSync state, every 8 ms). A tick that
  takes longer than its interval delays the next one, so the tick rate drops under load.
- **Buckets:** 0.001, 0.002, 0.004, 0.006, 0.008, 0.010, 0.015, 0.020, 0.030, 0.050, 0.070, 0.100,
  0.150 and 0.250 seconds, plus `+Inf`: 15 bucket series per thread.
- **Renaming:** the scrape job keeps only `tickTime_bucket`, `tickTime_sum` and `tickTime_count`
  (anything else a server version serves on `/perf/` is dropped), renames them to
  `fxserver_tick_time_seconds_*`, copies the `name` label to `thread` and drops `name`
  ([ADR 0010](adr/0010-rename-tick-time-to-fxserver-tick-time-seconds.md)).
- **Access:** when `sv_prometheusBasicAuthUser` or `sv_prometheusBasicAuthPassword` is set, a
  request without exactly these Basic credentials gets `401` with the body `Unauthorized.`; when
  both are empty, `/perf/` is open to anyone, limited to 2 requests per second (burst 5) per
  address
  ([`PerfHttpHandler.cpp`](https://github.com/citizenfx/fivem/blob/6efb47dff473c0e2a12fb50b08d74c0eb24a50d5/code/components/citizen-server-impl/src/PerfHttpHandler.cpp)).
  The probe `http_401_expected` below fails in that case.
- **Format:** the server answers with `Content-Type: text/plain`; Prometheus 3.15.0 reads that
  as the classic text format without a fallback setting (checked in the `exporters` run).

## Job `fxserver_json`: `info.json` and `dynamic.json` through json_exporter

Modules in [`json_exporter/config.yml`](../json_exporter/config.yml). The extra label `module`
is the json_exporter module that made the series.

| Metric | Type | Labels | Source endpoint and field | Verified |
|---|---|---|---|---|
| `fxserver_clients` | gauge | `server`, `module` | `GET /dynamic.json`: `clients`, the number of connected clients | source |
| `fxserver_max_clients` | gauge | `server`, `module` | `GET /dynamic.json`: `sv_maxclients`, the player slots, sent as a string such as `"32"` that json_exporter reads as a number | source |
| `fxserver_info` | gauge, always 1 | `server`, `module`, `version`, `build` | `GET /info.json`: `server`, `FXServer-` and the build description | source; `build`: unverified |
| `fxserver_onesync_enabled` | gauge, 0 or 1 | `server`, `module` | `GET /info.json`: `vars.onesync_enabled`, `"true"` or `"false"` | source |

- **Fields:** `dynamic.json` holds `hostname`, `gametype`, `mapname`, `clients`, `iv` and
  `sv_maxclients`; `info.json` holds `server`, `enhancedHostSupport`, `resources`, `vars`,
  `requestSteamTicket`, `enforceSteamAuth`, `version` and, with a server icon, `icon`
  ([`InfoHttpHandler.cpp`](https://github.com/citizenfx/fivem/blob/6efb47dff473c0e2a12fb50b08d74c0eb24a50d5/code/components/citizen-server-impl/src/InfoHttpHandler.cpp)).
  Only the four fields in the table are read.
- **`version` and `build`:** `version` is the raw `server` string, `FXServer-` followed by the
  build description. The Linux build script writes the description as
  `<branch> <CI build number> linux` for master and release builds, and as
  `<branch> SERVER v1.0.0.<date> linux` only for feature branches
  ([`build_server_proot_alpine.sh`](https://github.com/citizenfx/fivem/blob/6efb47dff473c0e2a12fb50b08d74c0eb24a50d5/code/tools/ci/build_server_proot_alpine.sh)).
  The server library in the build 35245 download (`libcitizen-server-impl.so`) holds the text
  `FXServer-master v1.0.0.35245 linux`; it has not yet been seen on a running server. The fake
  server serves that shape. The scrape job copies the digits after `v<a>.<b>.<c>.` into
  `build`, with or without `SERVER` before them (a unit test checks both); if the real string
  has another shape, `build` is missing and `version` still has the whole string. The label
  changes only when the server is upgraded.
- **OneSync:** the server sets `onesync_enabled` to true at start when `onesync` is `on` or
  `legacy` ([`ServerGameState.cpp`](https://github.com/citizenfx/fivem/blob/6efb47dff473c0e2a12fb50b08d74c0eb24a50d5/code/components/citizen-server-impl/src/state/ServerGameState.cpp)).
  When the variable is missing, the module returns no series instead of an error.
- **Errors:** json_exporter answers `503` when the server's status code is not 2xx (for example
  `403 Nope.`, see [Request paranoia](#request-paranoia-and-rate-limits)); then `up` is 0 for
  that target.

## Job `fxserver_blackbox`: probes of the game port

Modules in [`blackbox/blackbox.yml`](../blackbox/blackbox.yml); each probe target has the labels
`server` and `module`.

| Module | Target | Succeeds when | Verified |
|---|---|---|---|
| `tcp_connect` | `host:30120` | the game port accepts a TCP connection | exporter |
| `http_fxserver_info` | `http://host:30120/info.json` | `GET` answers `200` with a body that contains `"resources"` | exporter; field: source |
| `http_401_expected` | `http://host:30120/perf/` | `GET` without credentials is refused with `401` | exporter; behaviour: source |

The probes produce these series (blackbox_exporter 0.29.0, as seen in the `exporters` run):

| Metric | Type | Labels | Modules |
|---|---|---|---|
| `probe_success` | gauge, 0 or 1 | `server`, `module` | all |
| `probe_duration_seconds` | gauge | `server`, `module` | all |
| `probe_dns_lookup_time_seconds` | gauge | `server`, `module` | all |
| `probe_ip_protocol` | gauge (4 or 6) | `server`, `module` | all |
| `probe_ip_addr_hash` | gauge (hash of the address, to spot changes) | `server`, `module` | all |
| `probe_timeout_seconds` | gauge | `server`, `module` | all |
| `probe_failed_due_to_regex` | gauge, 0 or 1 | `server`, `module` | all |
| `probe_failed_due_to_bytes` | gauge, 0 or 1 | `server`, `module` | `tcp_connect` |
| `probe_http_status_code` | gauge | `server`, `module` | HTTP modules |
| `probe_http_duration_seconds` | gauge | `server`, `module`, `phase` | HTTP modules |
| `probe_http_content_length` | gauge | `server`, `module` | HTTP modules |
| `probe_http_uncompressed_body_length` | gauge | `server`, `module` | HTTP modules |
| `probe_http_redirects` | gauge | `server`, `module` | HTTP modules |
| `probe_http_ssl` | gauge, 0 or 1 | `server`, `module` | HTTP modules |
| `probe_http_version` | gauge | `server`, `module` | HTTP modules |

UDP on the game port has no generic probe; the TCP connect and the two HTTP probes go to the same
port.

## Job `fxserver_tunnel` (optional): the admin hostname

[`prometheus/scrape/tunnel.yml`](../prometheus/scrape/tunnel.yml) probes a hostname that an
access-protected tunnel publishes, for example the txAdmin web interface, with the module
`http_access_protected`: a `GET` without a login must answer `302`, `303` or `403` over HTTPS.
The series are the HTTP ones above, plus the TLS series blackbox_exporter adds for HTTPS targets
(certificate expiry, TLS version). Verified: unverified, because no tunnel exists here; the job
is not part of the `exporters` run. The dashboard reads one of the TLS series:

| Metric | Type | Labels | Source endpoint and field | Verified |
|---|---|---|---|---|
| `probe_ssl_earliest_cert_expiry` | gauge (Unix time) | `server`, `module` | the expiry of the certificate in the hostname's chain that expires first | exporter (blackbox_exporter 0.29.0 against a local HTTPS stand-in with a test certificate, 2026-10-21) |

## Job `fxserver_versions` (optional): the Recommended build

[`prometheus/scrape/versions.yml`](../prometheus/scrape/versions.yml) asks json_exporter, with the
module `fxserver_versions`, for the platform's public list of Linux server builds,
`https://changelogs-live.fivem.net/api/changelog/versions/linux/server`, every 4 minutes. The list
is the same for every game server, so the job runs once per Prometheus and its series have no
`server` label. The request goes from json_exporter on the Prometheus host to the platform and
carries nothing about your servers.

| Metric | Type | Labels | Source endpoint and field | Verified |
|---|---|---|---|---|
| `fxserver_recommended_build` | gauge | `module` | `GET` version list: `recommended`, the build number of the current Recommended build, sent as a string such as `"35245"` that json_exporter reads as a number | live (35245 on 2026-10-21) |

- **Fields:** the list also holds the Latest build, the download URL of each channel, and in
  `support_policy` the date each build's support ends. Only `recommended` is read.
- **Used by:** the alert `FXServerBuildBehindRecommended`
  ([`rules/build.alerts.yml`](../rules/build.alerts.yml)), which compares it with the build each
  game server runs.

## Series Prometheus adds per target

| Metric | Type | Labels |
|---|---|---|
| `up` | gauge, 0 or 1 | `server`, `module` (exporter jobs) |
| `scrape_duration_seconds` | gauge | same |
| `scrape_samples_scraped` | gauge | same |
| `scrape_samples_post_metric_relabeling` | gauge | same |
| `scrape_series_added` | gauge | same |

Each job sets a `sample_limit`, so a target that suddenly serves more series fails its scrape
(`up` 0) instead of filling the database ([cardinality budget](cardinality.md)).

## Recorded series (`rules/fxserver.recording.yml`)

The recording rules turn the tick-time histogram into one series per server and thread, every
30 seconds. Their names follow the Prometheus convention `level:metric:operations`: the level
lists the labels the series keep ([ADR 0014](adr/0014-tick-time-over-one-minute-windows.md)).

| Series | Labels | Meaning |
|---|---|---|
| `server_thread:fxserver_tick_time_seconds:p95_1m` | `server`, `thread` | 95th percentile of the tick time over the last minute, in seconds |
| `server_thread:fxserver_tick_time_seconds:p99_1m` | `server`, `thread` | 99th percentile of the tick time over the last minute, in seconds |
| `server_thread:fxserver_tick_time_seconds:mean1m` | `server`, `thread` | mean tick time over the last minute, in seconds |
| `server_thread:fxserver_tick_time_seconds_count:rate1m` | `server`, `thread` | ticks per second over the last minute (`svMain` about 20 while its ticks are short) |

- **Windows:** one minute, so a short spike stays visible and `FXServerTickTimeHigh`'s five
  minutes are five minutes of slow ticks. A one-minute rate needs at least two `/perf/` scrapes
  per minute; the pack scrapes every 15 seconds.
- **Percentiles:** interpolated within the bucket the rank falls into. The highest bucket bound
  below `+Inf` is 0.25 s, so a percentile among slower ticks reads 0.25.
- **Checked:** `tests/rules/recording.test.yml` computes each series from hand-made histograms,
  and the `exporters` run checks that each one exists per thread on the fake server's data.

Alerts that are pending or firing also appear as series; the dashboard reads `ALERTS` for its
alert count, its alert table and its annotations:

| Series | Labels | Meaning |
|---|---|---|
| `ALERTS` | `alertname`, `alertstate` (`pending` or `firing`), `server`, `severity` and, for some alerts, `thread`, `job` or `mountpoint` | 1 for every alert that is pending or firing |
| `ALERTS_FOR_STATE` | the same, without `alertstate` | the Unix time the alert became active; Prometheus uses it to keep the `for` wait across a restart |

## Series the rules read from other exporters

This pack ships no jobs for these exporters. Scrape them with jobs of your own and give every
target the `server` label of its game server
([configuration](configuration.md#host-and-database-jobs)); the alerts group by that label.

| Metric | Exporter | Labels the rules use | Rule |
|---|---|---|---|
| `node_filesystem_avail_bytes`, `node_filesystem_size_bytes`, `node_filesystem_readonly` | node_exporter, filesystem collector (on by default) | `server`, `mountpoint`, `fstype` | `HostDiskAlmostFull` |
| `fxserver_artifact_installed_timestamp_seconds` | node_exporter, textfile collector: `fxserver_artifact.prom`, written by the `fxserver` role of the `luminare.gameserver` collection when `fxserver_textfile_dir` is set | `server` | `FXServerArtifactOld` |
| `fxserver_artifact_build` | the same file | `server` | `FXServerBuildBehindRecommended` |
| `mysql_up` | mysqld_exporter | `server` | `MariaDBDown` |
| `mysql_global_status_slow_queries` | mysqld_exporter, global status collector (on by default) | `server` | `MariaDBSlowQueries` |

The two textfile metrics have no labels of their own: `fxserver_artifact_build` is the build
number the `current` link points to, `fxserver_artifact_installed_timestamp_seconds` the Unix time
that link was last replaced. Any other tool can write the same file for the alerts to work.

## Series the dashboard reads from other exporters

The dashboard ([`grafana/dashboards/`](../grafana/dashboards/)) reads the series above and these,
from the same jobs of your own plus one for the tunnel connector, each target with the `server`
label of its game server ([configuration](configuration.md#host-and-database-jobs)). Without a
job, its panels show no data; nothing else depends on them. `scripts/lint_dashboards.py` fails
when a dashboard query reads a metric that is not in a table of this page.

| Metric | Exporter | Labels the dashboard uses | Panel |
|---|---|---|---|
| `node_cpu_seconds_total` | node_exporter, cpu collector (on by default) | `server`, `mode` (`idle`, `steal`) | CPU |
| `node_memory_MemAvailable_bytes`, `node_memory_MemTotal_bytes` | node_exporter, meminfo collector (on by default) | `server` | Memory |
| `node_network_receive_bytes_total`, `node_network_transmit_bytes_total` | node_exporter, netdev collector (on by default) | `server`, `device` (all but `lo`) | Network |
| `mysql_global_status_queries` | mysqld_exporter, global status collector (on by default) | `server` | Queries per second |
| `mysql_global_status_threads_connected`, `mysql_global_variables_max_connections` | mysqld_exporter, global status and global variables collectors (on by default) | `server` | Connections |
| `mysql_global_status_innodb_buffer_pool_reads`, `mysql_global_status_innodb_buffer_pool_read_requests` | mysqld_exporter, global status collector | `server` | Buffer pool hit ratio |
| `cloudflared_tunnel_ha_connections` | cloudflared, metrics endpoint (`--metrics 127.0.0.1:2000`) | `server` | Tunnel connections |
| `cloudflared_tunnel_total_requests`, `cloudflared_tunnel_request_errors` | the same | `server` | Tunnel requests |

The names and types were read from node_exporter 1.12.1, mysqld_exporter 0.20.0 (with MariaDB
11.8.9) and cloudflared 2026.10.2 on 2026-10-21, in the dashboard check described in the README's
Results. cloudflared counts an edge connection in `cloudflared_tunnel_ha_connections` also while
it retries it (seen with an unreachable edge), so the dashboard shows it next to the admin
hostname probe. Prometheus 3 adds an information notice ("metric might not be a counter") to
`rate()` over counters whose names do not end in `_total`, such as mysqld_exporter's global status
counters and cloudflared's request counters; Grafana shows it as an icon on the panel, and the
values are right.

## Request paranoia and rate limits

From the source of build 35245:

- `sv_requestParanoia` 1 refuses `info.json`, `dynamic.json` and `players.json` requests that
  carry a `Via` header (sent by proxies); 2 also refuses requests with
  `Upgrade-Insecure-Requests` (sent by browsers). A refused request gets `403 Nope.` and the
  server blocks the sending address. json_exporter and blackbox_exporter send neither header, so
  direct scrapes keep working at every level; a proxy between them and the server would be
  refused from level 1.
- `info.json` and `players.json` are limited to 4 requests per second (burst 10) per address;
  this pack requests `info.json` twice per 30 seconds. `dynamic.json` has no limit.
  Unauthenticated `/perf/` requests are limited as described above; authenticated ones are not.

## Not collected

- **`players.json`, in any form.** The player count comes from `dynamic.json` `clients`. Without
  the players token (`sv_playersToken`) the server serves an anonymous entry per client there,
  with it names and identifiers; the pack needs neither, so no target, module or rule names that
  endpoint, and `scripts/check_pack.py` fails if one does
  ([ADR 0009](adr/0009-counts-only-from-the-status-endpoints.md)).
- **Any label tied to a player:** names, identifiers (license, Steam, Discord and so on), IP
  addresses, endpoints, pings or player IDs. `scripts/check_pack.py` rejects such label names in
  the scrape config, the relabel rules and the exporter modules, and the `exporters` run checks
  the labels that arrive in Prometheus.
- **Everything else in `info.json` and `dynamic.json`:** project name and description, host
  name, tags, locale, other variables, the resource list (one series per resource would break
  the [cardinality budget](cardinality.md)), the icon and the version hash.
- **txAdmin's own status endpoint:** its fields have not been checked yet, so there is no module
  for it ([probe log](probe-log.md#txadmin-hoststatus)).
- **The exporters' own `/metrics`:** not scraped by these jobs; add a job of your own if you want
  the exporters' process metrics.
