# Configuration

The pack is configuration: the scrape jobs in `prometheus/scrape/`, the json_exporter modules in
`json_exporter/config.yml`, the blackbox_exporter modules in `blackbox/blackbox.yml`, the
recording and alerting rules in `rules/` and the dashboard in `grafana/`. Change the values below
for your servers, then run `python3 scripts/check_pack.py`, `bash scripts/check_promtool.sh` and
`python3 scripts/lint_dashboards.py` (with promtool on the `PATH`) before you load them.
[Metrics reference](metrics.md) describes what each job collects.

The pack check accepts only loopback and documentation addresses (`192.0.2.0/24`,
`198.51.100.0/24`, `203.0.113.0/24`, `2001:db8::/32`), so that no real address gets into this
repository. A copy with the addresses of your servers, such as your clone with the targets filled
in or a folder with the same `prometheus/`, `json_exporter/` and `blackbox/` layout (`--root`),
reports each of them as an `[addresses]` finding: check such a copy with
`python3 scripts/check_pack.py --allow-any-address`, which skips only that check.

## Game server

`/perf/` must be protected, otherwise anyone who reaches the game port can read it. Put the two
variables into the server's `secrets.cfg` (or wherever its secrets live, never into git):

```cfg
set sv_prometheusBasicAuthUser "prometheus"
set sv_prometheusBasicAuthPassword "CHANGE_ME_PERF_PASSWORD"
```

With the `luminare.gameserver` collection, set `fxserver_perf_user` and `fxserver_perf_password`
(or the `txadmin` role's `txadmin_prometheus_basic_auth`) instead, and its `fxserver` role writes
the two lines ([installation](install.md#with-the-luminaregameserver-collection)).

The server compares the whole `Authorization` header with these values. With neither set,
`/perf/` is open by the server's source code (not yet tried on a running server), and the probe
`http_401_expected` reports it (`probe_success` 0). The JSON
endpoints need no setting; a proxy between Prometheus and the server is refused from
`sv_requestParanoia 1` on ([metrics reference](metrics.md#request-paranoia-and-rate-limits)).

## Scrape jobs (`prometheus/scrape/fxserver.yml`)

| Setting | Default | Description |
|---|---|---|
| `server` label | `game-01` | Your name for the game server, the same in every job. Rules and dashboards group by it; use a short name, not a host name or address. |
| `fxserver_perf` target | `127.0.0.1:30120` | Host and game port of the server. |
| `basic_auth.username` | `prometheus` | Equal to `sv_prometheusBasicAuthUser`. |
| `basic_auth.password_file` | `/etc/prometheus/secrets/fxserver_perf` | File with the value of `sv_prometheusBasicAuthPassword` and nothing else. Prometheus strips leading and trailing whitespace (spaces, tabs, the newline) from it and keeps spaces inside the password, so do not use a password that starts or ends with a space. Readable by Prometheus only (for example mode 0640, group of the Prometheus user). |
| `fxserver_json` targets | `http://127.0.0.1:30120/dynamic.json` (module `fxserver_dynamic`), `http://127.0.0.1:30120/info.json` (module `fxserver_info`) | The URLs json_exporter fetches; the `module` label selects the json_exporter module. |
| `fxserver_blackbox` targets | `127.0.0.1:30120` (`tcp_connect`), `http://127.0.0.1:30120/info.json` (`http_fxserver_info`), `http://127.0.0.1:30120/perf/` (`http_401_expected`) | What blackbox_exporter probes; the `module` label selects the probe module. |
| `replacement` of `__address__` | `127.0.0.1:7979` (json_exporter), `127.0.0.1:9115` (blackbox_exporter) | Where the exporters listen, as seen from Prometheus. |
| `scrape_interval` | `15s` for `/perf/`, `30s` for the exporter jobs | `info.json` is rate-limited by the server (4 requests per second per address), so keep the JSON jobs at 30 seconds or more. |
| `sample_limit` | `100`, `20`, `60` | Upper bound of series per target ([cardinality budget](cardinality.md)). |

Never change the relabel rules of `fxserver_perf` without the pack check: they keep only the
tick-time histogram, rename it and drop the server's `name` label
([ADR 0010](adr/0010-rename-tick-time-to-fxserver-tick-time-seconds.md)).

### More than one game server

Add one target group per server and job, each with its own `server` label:

```yaml
    static_configs:
      - targets: ["192.0.2.10:30120"]
        labels:
          server: game-01
      - targets: ["192.0.2.11:30120"]
        labels:
          server: game-02
```

Basic auth is set per job, so every server scraped by `fxserver_perf` needs the same `/perf/`
user and password. The credentials travel unencrypted with plain HTTP: scrape a game server on
another host only over a private network or a tunnel, never over the internet.

### The admin hostname probe (`prometheus/scrape/tunnel.yml`)

Optional. Set the target to the HTTPS address of your access-protected admin hostname (for
example `https://demo-tx.example.com/`) and keep the `server` label of the game server. The probe
succeeds when a request without a login is redirected (`302`, `303`) or refused (`403`).

### The version list (`prometheus/scrape/versions.yml`)

Optional, once per Prometheus. It needs no change: the target is the platform's public version
list, which json_exporter fetches over HTTPS every 4 minutes, so the Prometheus host needs
outbound HTTPS. A shorter interval brings no benefit; a longer one lets the series go stale
between scrapes. Without this job, `FXServerBuildBehindRecommended` never fires; the other alerts
do not need it.

### Host and database jobs

Some alerts read node_exporter and mysqld_exporter ([metrics reference](metrics.md#series-the-rules-read-from-other-exporters)),
and the dashboard also reads the metrics of the tunnel connector, cloudflared
([metrics reference](metrics.md#series-the-dashboard-reads-from-other-exporters)). This pack ships
no jobs for them, because most setups scrape these exporters already. Give each of their targets
the `server` label of the game server it belongs to, so that the alerts and the dashboard name
it:

```yaml
scrape_configs:
  - job_name: node
    static_configs:
      - targets: ["127.0.0.1:9100"]
        labels:
          server: game-01
  - job_name: mysqld
    static_configs:
      - targets: ["127.0.0.1:9104"]
        labels:
          server: game-01
  - job_name: cloudflared
    static_configs:
      - targets: ["127.0.0.1:2000"]
        labels:
          server: game-01
```

cloudflared serves its metrics only with `--metrics <address>` (for example
`--metrics 127.0.0.1:2000` in its service's command line); keep that address on loopback or a
private network.

For the two build alerts, node_exporter reads the textfile collector folder that the `fxserver`
role of the `luminare.gameserver` collection writes to (`fxserver_textfile_dir`), for example
`--collector.textfile.directory=/var/lib/node_exporter/textfile_collector`. Without these jobs
the host, build and database alerts stay silent and the dashboard's host, MariaDB and tunnel
panels show no data; without the `server` label the alerts fire without naming a game server, the
alerts of two hosts merge into one, and the dashboard's `server` filter does not reach these
panels.

## Dashboard (`grafana/`)

| File | Content |
|---|---|
| `grafana/dashboards/game-server-overview.json` | The dashboard "Game server overview" (uid `gso-game-server-overview`), for provisioning. |
| `grafana/dashboards/shareable/game-server-overview.json` | The same dashboard without variables (uid `gso-game-server-overview-shared`), for importing; written by `python3 scripts/lint_dashboards.py --fix` ([ADR 0018](adr/0018-dashboard-with-a-shareable-copy.md)). |
| `grafana/provisioning/dashboards/gameserver-observability.yml` | Loads the dashboards from `/var/lib/grafana/dashboards/gameserver-observability` into the Grafana folder "Game server". |
| `grafana/provisioning/datasources/gameserver-observability.yml` | Optional: a Prometheus data source "Game server metrics" (uid `gso-prometheus`), for a Grafana that has none for the pack's metrics. |

The dashboard has six rows: Overview (status, players, slots in use, `svMain` p95, build, build
age, restarts, alerts), Tick time (heatmap of the `svMain` histogram, p95 and p99, ticks per
second, mean), Players, Host, MariaDB, and Probes and tunnel. It has no row for the game server's
resources (scripts and assets), because the pack does not collect the resource list
([metrics reference](metrics.md#not-collected)); the host row shows the machine's CPU, memory, disk
and network.

Its variables:

| Variable | Default | Description |
|---|---|---|
| `datasource` (Data source) | Grafana's default Prometheus data source | Any Prometheus data source with the pack's series. The file stores no data source, so every viewer gets their own default. |
| `server` (Game server) | All | The values of the `server` label of `up{job="fxserver_perf"}`; one or several. Every panel filters on it. |

Settings in the provisioning files:

| Setting | Default | Description |
|---|---|---|
| `options.path` (dashboards) | `/var/lib/grafana/dashboards/gameserver-observability` | The folder Grafana reads the dashboard files from. Copy only `grafana/dashboards/*.json` there: Grafana also reads subfolders, and would then provision the shareable copy as a second dashboard. |
| `folder`, `folderUid` (dashboards) | `Game server`, `gso-game-server` | The Grafana folder of the dashboard. |
| `allowUiUpdates`, `disableDeletion` (dashboards) | `false`, `true` | The files are the source: changes made in Grafana cannot be saved over them, and a dashboard is not deleted from Grafana when its file goes missing. |
| `updateIntervalSeconds` (dashboards) | `60` | How often Grafana reads the folder for changed files. |
| `url` (data source) | `http://prometheus:9090` | Your Prometheus, as Grafana reaches it. |
| `timeInterval` (data source) | `30s` | The scrape interval Grafana assumes for this data source. `$__rate_interval` is at least four times this value, so the rate panels use windows of 2 minutes or more, which hold two samples even of jobs scraped once a minute. |

The file does not mark the data source as the default, so it never takes over from a default
you have; Grafana makes it the default only when it is the first data source.

To change the dashboard, edit `grafana/dashboards/game-server-overview.json` (for example by
pasting the JSON model of a changed copy from Grafana, with `"id": null`, the same `uid` and the
data source variable kept), then write the shareable copy and check both:

```bash
python3 scripts/lint_dashboards.py --fix
python3 scripts/lint_dashboards.py --require-promtool
```

The check fails on platform or vendor marks in titles, a stored data source uid or variable
selection, a metric that is not in the [metrics reference](metrics.md), a label that could identify
a player, the `instance` label, an address or a link outside this repository, and a shareable
copy that does not match ([ADR 0019](adr/0019-dashboard-check-in-standard-library-python.md)).

## json_exporter modules (`json_exporter/config.yml`)

| Module | Fetches | Metrics |
|---|---|---|
| `fxserver_dynamic` | `dynamic.json` | `fxserver_clients`, `fxserver_max_clients` |
| `fxserver_info` | `info.json` | `fxserver_info` (labels `version`, and `build` from the scrape job), `fxserver_onesync_enabled` |
| `fxserver_versions` | the platform's version list (job `fxserver_versions`) | `fxserver_recommended_build` |

The modules do not follow redirects. json_exporter ignores keys it does not know, so a typo
would silently drop a metric; `scripts/check_pack.py` reports unknown keys. Start json_exporter
with `--config.file=/etc/json_exporter/config.yml --web.listen-address=127.0.0.1:7979`.

## blackbox_exporter modules (`blackbox/blackbox.yml`)

| Module | Prober | Succeeds when |
|---|---|---|
| `tcp_connect` | TCP | the port accepts a connection within 5 s |
| `http_fxserver_info` | HTTP | `GET` answers `200` with `"resources"` in the body within 5 s |
| `http_401_expected` | HTTP | `GET` without credentials answers `401` within 5 s |
| `http_access_protected` | HTTP | `GET` over HTTPS answers `302`, `303` or `403` within 10 s |

Start blackbox_exporter with `--config.file=/etc/blackbox_exporter/blackbox.yml
--web.listen-address=127.0.0.1:9115`. Both exporters fetch any URL that Prometheus (or anyone
else who reaches them) asks for, so they listen on loopback or a private address only.

## Rules (`rules/`)

Load all rule files with `rule_files: [/etc/prometheus/rules/*.yml]`, or leave out the files whose
data you do not collect. Every alert has the labels `server` and `severity` and the annotations
`summary`, `description` and `runbook_url` (a section of the [runbook](runbook.md))
([ADR 0015](adr/0015-alerts-per-game-server.md)).

| File | Rules | Needs |
|---|---|---|
| `fxserver.recording.yml` | the [recorded tick-time series](metrics.md#recorded-series-rulesfxserverrecordingyml) | job `fxserver_perf` |
| `fxserver.alerts.yml` | the game server alerts | the jobs in `prometheus/scrape/fxserver.yml` (and `tunnel.yml` for the admin hostname alerts), the recorded series |
| `build.alerts.yml` | the build alerts | node_exporter with the build textfile, and the job `fxserver_versions` for `FXServerBuildBehindRecommended` |
| `host.alerts.yml` | the disk alert | node_exporter |
| `mariadb.alerts.yml` | the database alerts | mysqld_exporter |

The thresholds:

| Alert | File | Fires when | For | Severity |
|---|---|---|---|---|
| `FXServerDown` | `fxserver.alerts.yml` | the probe `tcp_connect` or `http_fxserver_info` fails | 2 min | critical |
| `FXServerTargetDown` | `fxserver.alerts.yml` | a target of `fxserver_perf`, `fxserver_json`, `fxserver_blackbox` or `fxserver_tunnel` cannot be scraped while the probes do not report the server as down | 10 min | warning |
| `FXServerTickTimeHigh` | `fxserver.alerts.yml` | the `svMain` tick time's 95th percentile over a minute is above 50 ms | 5 min | warning |
| `FXServerNoPlayersAfterRestart` | `fxserver.alerts.yml` | 0 players for 30 minutes after a restart 30 to 60 minutes ago, with players in the 30 minutes before ([ADR 0016](adr/0016-restarts-from-tick-counter-resets.md)) | none | warning |
| `FXServerPerfEndpointExposed` | `fxserver.alerts.yml` | `/perf/` answers a request without credentials with `2xx` | 5 min | warning |
| `FXServerAdminHostnameUnprotected` | `fxserver.alerts.yml` | the admin hostname answers a request without a login with `2xx` | 5 min | critical |
| `FXServerAdminHostnameProbeFailing` | `fxserver.alerts.yml` | the admin hostname probe fails for another reason | 10 min | warning |
| `FXServerArtifactOld` | `build.alerts.yml` | the active build was switched on more than 56 days (8 weeks) ago | 1 h | warning |
| `FXServerBuildBehindRecommended` | `build.alerts.yml` | the active build is older than every Recommended build of the last 14 days ([ADR 0017](adr/0017-build-age-and-the-recommended-build.md)) | 1 h | warning |
| `HostDiskAlmostFull` | `host.alerts.yml` | a writable filesystem is more than 85 % full (less than 15 % available) | 10 min | warning |
| `MariaDBDown` | `mariadb.alerts.yml` | `mysql_up` is 0 | 2 min | critical |
| `MariaDBSlowQueries` | `mariadb.alerts.yml` | more than 1 slow query a minute, averaged over 5 minutes | 10 min | warning |

To change a threshold, edit the number in the alert's `expr` (or its `for`) in your copy, and in
this repository change the expected alerts in `tests/rules/` and the alert's runbook section with
it; `bash scripts/check_promtool.sh` must pass. The rule groups are evaluated every 30 seconds
(`fxserver-tick-time`, `fxserver-alerts`) or every minute (the others), whatever
`evaluation_interval` the Prometheus config sets.

## Send the alerts to Alertmanager

The pack ships no Alertmanager configuration: Prometheus evaluates the rules and shows pending and
firing alerts (Status → Alerts, the `ALERTS` series, the dashboard), and sending them to people is
the job of your Alertmanager ([ADR 0023](adr/0023-no-alertmanager-in-0-1.md)). Point Prometheus at
it in `/etc/prometheus/prometheus.yml`:

```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets: ["127.0.0.1:9093"]
```

Then route on the alerts' labels in your Alertmanager configuration. Every alert has the labels
`alertname`, `server` (the game server) and `severity` (`critical` or `warning`), and the
annotations `summary`, `description` and `runbook_url`, which most receivers can put into the
message. This route sends critical alerts to one receiver and everything else to another, grouped
by alert and game server:

```yaml
route:
  receiver: default
  group_by: [alertname, server]
  routes:
    - matchers: ['severity="critical"']
      receiver: on-call
receivers:
  - name: default
  - name: on-call
```

The two receivers are empty here, so they deliver nothing; add your mail, chat or webhook
settings to them in your own configuration, and keep their passwords, tokens and webhook URLs out
of git. On 2026-10-22, `amtool check-config` (amtool 0.34.1) accepted this file,
`amtool config routes test --config.file=alertmanager.yml severity=critical` printed `on-call`,
and the `alerting` block above passed `promtool check config` together with the pack's rule
files.

## Fake game server (`demo/fake-fxserver/fake_fxserver.py`)

For tests and demos only; every value it serves is synthetic. Each option can also be set with
the environment variable in the second column.

| Option | Variable | Default | Description |
|---|---|---|---|
| `--bind` | `FAKE_BIND` | `127.0.0.1` | Address to listen on. |
| `--port` | `FAKE_PORT` | `30120` | Port for all endpoints. |
| `--build` | `FAKE_BUILD` | `35245` | Build number in the version string. |
| `--clients`, `--max-clients` | `FAKE_CLIENTS`, `FAKE_MAX_CLIENTS` | `3`, `32` | Connected clients and slots. |
| `--main-tick-ms` | `FAKE_MAIN_TICK_MS` | `4` | The load knob: mean `svMain` tick time in milliseconds. 70 or more is a spike; above 50 the thread also ticks less often. |
| `--request-paranoia` | `FAKE_REQUEST_PARANOIA` | `0` | Like `sv_requestParanoia`, levels 0 to 3. |
| `--seed` | `FAKE_SEED` | `-1` (random) | Seed for repeatable tick times. |
| `--perf-user` | `FAKE_PERF_USER` | empty | User for `/perf/`. |
| `--perf-password-file` | `FAKE_PERF_PASSWORD_FILE` | empty | File with the `/perf/` password; without it `FAKE_PERF_PASSWORD` is used. With neither user nor password, `/perf/` is open, as on the real server. |
| `--no-control` | | control on | Turns off `/fake/state` and `/fake/control`. |
| `--quiet` | | log on | Does not log requests. |

At run time, `POST /fake/control` with a JSON object changes the load and the clients, for example
a two-minute spike:

```bash
curl -fsS -X POST -d '{"main_tick_ms": 90, "for_seconds": 120}' http://127.0.0.1:30120/fake/control
```

The fields are `main_tick_ms`, `for_seconds` (with `main_tick_ms`: return to the previous value
afterwards), `clients` and `restart` (`true` resets the histograms). `GET /fake/state` shows the
settings and how often each path was requested.

## Repository checks

| Option | Type | Default | Description |
|---|---|---|---|
| `TEST_VENV` (environment, `scripts/test.sh`) | path | in CI `$RUNNER_TEMP/gameserver-observability-test-venv`, elsewhere `${XDG_CACHE_HOME:-~/.cache}/gameserver-observability/test-venv` | Where the test script keeps its virtual environment. It is reused if it exists and belongs to the current user (otherwise the script stops with an error), and created again if it has no working pip; the requirements are installed again on every run. |
| `test-command` (input in `ci.yml` and `release.yml`) | string | `bash scripts/test.sh` | The test command for `ci / lint-test` and for the release build on the tag. Both files must use the same value (a unit test checks it). |
| `archive-name` (input in `release.yml`) | string | `gameserver-observability` | Name of the release asset `<name>-X.Y.Z.tar.gz`. |
| `PROMTOOL_VERSION`, `PROMTOOL_SHA256` (`env:` of the `promtool` job in `ci.yml`) | string | `3.15.0`, the sha256 of its linux-amd64 tarball | The promtool download. Change both together and update [toolchain.md](toolchain.md); a unit test compares them. |
| `PROMETHEUS_*`, `JSON_EXPORTER_*` and `BLACKBOX_EXPORTER_*`, each `_VERSION` and `_SHA256` (`env:` of the `exporters` job in `ci.yml`) | string | `3.15.0`, `0.8.0`, `0.29.0` and the sha256 of each linux-amd64 tarball | The downloads for `scripts/smoke_exporters.py`. Prometheus must equal the promtool pin; a unit test compares all of them with [toolchain.md](toolchain.md). |
| `GITLEAKS_VERSION`, `GITLEAKS_SHA256` (variables in `scripts/test.sh`) | string | `8.30.1`, the sha256 of its linux-x64 tarball | The gitleaks download that `scripts/test.sh` makes in CI (`CI=true`), so the secret-rule tests run there. Keep them equal to the defaults in `reusable-gitleaks.yml` and to [toolchain.md](toolchain.md); a unit test compares them. |
| `--allow-any-address` (`scripts/check_pack.py`) | flag | off | Accept any IP address instead of only loopback and the documentation ranges, for a copy of the configs with the addresses of your servers. CI never sets it. |
| `--require-promtool` (`scripts/check_pack.py`) | flag | off | Fail when promtool is not on the `PATH`, instead of skipping `promtool check config`. The `promtool` job sets it. |
| `--require-promtool` (`scripts/lint_dashboards.py`) | flag | off | Fail when promtool is not on the `PATH`, instead of skipping the parse of every panel query with `promtool check rules`. The `promtool` job sets it. |
| `--fix` (`scripts/lint_dashboards.py`) | flag | off | Write the dashboards in the repository's JSON format and their shareable copies, then check them. |
| `--bin-dir`, `--timeout` (`scripts/smoke_exporters.py`) | path, seconds | the `PATH`, `120` | Where the three binaries are, and how long to wait for each step: the first scrapes, the first evaluation of the rules, and each alert to go pending. |

## Secrets

Secrets never go into this repository, an issue or a log. Pass them through files outside the
repository, environment variables or a secret store. CI scans every commit with gitleaks; a
leaked secret is rotated first and removed from history second.

- The `/perf/` password goes into the password file on the Prometheus host and into the server's
  `secrets.cfg`; the scrape config only names the file. `scripts/check_pack.py` fails on any
  inline `password`, token or credentials setting, on inline `secrets` in an `http_headers` map,
  and on an inline value for a header named like a credential (`Authorization`, a cookie, token,
  key, secret or password header) in the header maps of the Prometheus jobs, json_exporter and
  blackbox_exporter modules.
- The repository's CI needs no secret: it uses only the workflow's own `GITHUB_TOKEN`, and the
  end-to-end run creates a random password for each run.
- Never commit a server license key (`sv_licenseKey`, `cfxk_…`), a txAdmin token or a password.
  Where an example needs a license key, write `CHANGE_ME_LICENSE_KEY`, and never start a
  placeholder with `cfxk_`. Any `cfxk_` value with 20 or more key characters after the prefix
  fails the secret scan, wherever it stands in a line; the only exception is a placeholder made of
  `x` and `_` characters. Shorter values such as `cfxk_REPLACE_ME` are not reported, but they still
  look like keys, so do not use them either
  ([ADR 0008](adr/0008-extra-secret-rule-for-any-cfxk-token.md)).
