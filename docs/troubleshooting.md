# Troubleshooting

## `The virtual environment was not created successfully because ensurepip is not available`

**Cause:** `scripts/test.sh` creates a virtual environment, and Debian and Ubuntu ship the `venv`
module's pip bootstrap in a separate package.

**Fix:** install it (the package name follows the Python version, for example `python3.12-venv`)
and run the script again. The failed run left an environment without pip behind; the script
notices that and creates the environment again (`… has no working pip; creating it again`).

```bash
sudo apt-get install python3-venv
bash scripts/test.sh
```

## `error: … exists but does not belong to …; remove it or set TEST_VENV`

**Cause:** the folder for the test environment (`$TEST_VENV`, see
[configuration](configuration.md)) already exists and belongs to another user. `scripts/test.sh`
refuses to run a Python that someone else could have put there.

**Fix:** check what the folder is, then delete it, or point `TEST_VENV` to a folder of your own,
for example `TEST_VENV="$HOME/.cache/gso-test-venv" bash scripts/test.sh`.

## `ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE`

**Cause:** pip downloaded a file whose sha256 is not listed in `requirements-test.txt`. That
happens when a proxy or mirror serves different files, or when the file was edited by hand.

**Fix:** install from PyPI directly. If `requirements-test.in` changed, compile the file again as
shown on the [toolchain page](toolchain.md) instead of editing hashes by hand.

## `sha256sum: WARNING: 1 computed checksum did NOT match`

**Cause:** the downloaded promtool tarball is not the file the pin expects: the download broke, or
the version and the sha256 were changed separately.

**Fix:** download again; when bumping promtool, take the version and the sha256 from the same
release's `sha256sums.txt` and change both in `ci.yml` and [toolchain.md](toolchain.md).

## `promtool: command not found`

**Cause:** `scripts/check_promtool.sh` expects promtool on the `PATH`.

**Fix:** install it as shown on the [toolchain page](toolchain.md) and add its folder to the
`PATH`, for example `PATH="$PWD:$PATH" bash scripts/check_promtool.sh`.

## `server returned HTTP status 401 Unauthorized` on the `fxserver_perf` target

**Cause:** the server refused the credentials. It compares the whole `Authorization` header, so
the user in `basic_auth.username` and the content of the password file must equal
`sv_prometheusBasicAuthUser` and `sv_prometheusBasicAuthPassword` exactly. Prometheus strips
leading and trailing whitespace, including the newline, from the password file and keeps the
spaces inside the password, so a server password that starts or ends with a space never matches.

**Fix:** compare the values (choose a password without leading or trailing spaces), then check
that Prometheus can read the file (its user needs read access to
`/etc/prometheus/secrets/fxserver_perf`) and that the server was restarted after the variables
changed. With the `luminare.gameserver` collection, the server's values are
`fxserver_perf_user` and `fxserver_perf_password`, or the `user` and `password` of the `txadmin`
role's `txadmin_prometheus_basic_auth` when that toggle is enabled
([installation](install.md#with-the-luminaregameserver-collection)).

## `sample limit exceeded` on a target

**Cause:** the target served more series than the job's `sample_limit`, so Prometheus dropped the
whole scrape. With the shipped configs this happens only when a server version or an exporter
version serves many more series than measured in the [cardinality budget](cardinality.md).

**Fix:** look at what the target serves (for an exporter job, open its `/probe` URL with the same
`module` and `target`), then raise the limit in the scrape job if the new series are expected.

## `Failed to fetch JSON response` in the json_exporter log, target answers `503`

**Cause:** json_exporter could not get a 2xx answer from `dynamic.json` or `info.json`: the server
is down, the address is wrong, or the server refused the request. A `403` with the body `Nope.`
comes from `sv_requestParanoia` when a proxy between json_exporter and the server adds a `Via`
header (level 1 or higher); a `429` means that address sent `info.json` more requests than the
server allows (4 per second, burst 10).

**Fix:** scrape the server directly (no proxy), or lower `sv_requestParanoia`; keep the JSON jobs
at 30 seconds or more.

## `probe_success{module="http_401_expected"}` is 0

**Cause:** `/perf/` answered without credentials, because neither `sv_prometheusBasicAuthUser`
nor `sv_prometheusBasicAuthPassword` is set on the server.

**Fix:** set both ([configuration](configuration.md#game-server)) and restart the server; see
the [runbook](runbook.md#alert-fxserverperfendpointexposed).

## Prometheus → Status → Rules shows no group `fxserver-alerts`

**Cause:** the rule files are not loaded: `rule_files` is missing from `prometheus.yml`, its path
does not match where the files are, or Prometheus was not reloaded. A file that does not parse
stops the reload, and Prometheus logs the error and keeps the old rules.

**Fix:** check the path (`rule_files: [/etc/prometheus/rules/*.yml]` with the files installed as
in [Installation](install.md#install)), run `promtool check config /etc/prometheus/prometheus.yml`
(it also checks the rule files it names) and reload Prometheus.

## An alert names no game server (`server` is empty)

**Cause:** the alert reads a series without the `server` label: the node_exporter or
mysqld_exporter job, or a target of the pack's jobs, has no `server` label.

**Fix:** add the label to every target of those jobs, with the name of the game server it belongs
to ([configuration](configuration.md#host-and-database-jobs)).

## `fxserver_recommended_build` is empty

**Cause:** the job `fxserver_versions` is not loaded (`prometheus/scrape/versions.yml` is not in
`scrape_config_files`), or json_exporter cannot fetch the version list: no outbound HTTPS from the
Prometheus host, no DNS, a proxy in between, or missing CA certificates. json_exporter then logs
`Failed to fetch JSON response` and the target answers `503`.

**Fix:** check `up{job="fxserver_versions"}`, then ask json_exporter directly on the Prometheus
host:

```bash
curl -fsS 'http://127.0.0.1:7979/probe?module=fxserver_versions&target=https://changelogs-live.fivem.net/api/changelog/versions/linux/server'
```

It must print `fxserver_recommended_build` with a build number. Allow outbound HTTPS for
json_exporter, or, behind a proxy, set `proxy_url` in the module's `http_client_config`.

## `check_pack: … [parse] line N: …`

**Cause:** `scripts/check_pack.py` reads only the YAML the configs need. Values such as `yes`,
`no`, `on` or `off`, numbers with a leading zero, dates, block scalars (`|`, `>`), anchors, values
that continue on the next line, and `:` inside an unquoted value in `[...]` are refused instead of
guessed.

**Fix:** quote the value or write it on one line, and use `true`/`false` for booleans, as the
other configs do.

## `smoke_exporters: port(s) in use on 127.0.0.1`

**Cause:** the end-to-end run needs the ports of the shipped configs: 30120 (fake server), 7979
(json_exporter) and 9115 (blackbox_exporter).

**Fix:** stop what uses them, or run the script in a container without published ports, for
example `docker run --rm --network none -v "$PWD":/repo:ro -v "$PWD/bin":/opt/bin:ro python:3.13-slim
python3 -I /repo/scripts/smoke_exporters.py --bin-dir /opt/bin`.

## Demo stack: `Bind for 127.0.0.1:3000 failed: port is already allocated`

**Cause:** `docker compose -f demo/docker-compose.yml up` publishes Grafana, Prometheus and the
simulated server on 127.0.0.1:3000, 9090 and 30120 of the Docker host, and another program or
container already uses one of them (the message names the port).

**Fix:** remove the half-started stack with `docker compose -f demo/docker-compose.yml down -v`,
then choose free host ports with `GSO_DEMO_GRAFANA_PORT`, `GSO_DEMO_PROMETHEUS_PORT` and
`GSO_DEMO_GAME_PORT` ([demo stack](demo.md#start-and-stop)). `scripts/smoke_demo.py` picks free
ports itself.

## Demo stack: Grafana and the simulated server stopped answering

**Cause:** the services share the network namespace of the Prometheus container. When only that
container was recreated (for example with `docker compose up -d --force-recreate prometheus`),
the others are left without a network.

**Fix:** run `docker compose -f demo/docker-compose.yml up -d`; it recreates them in the new
namespace ([ADR 0020](adr/0020-demo-stack-in-one-network-namespace.md)).

## `smoke_demo: the Compose project … already has N container(s)`

**Cause:** an earlier run of `scripts/smoke_demo.py` was stopped before it could remove its stack,
or a stack of yours uses the same project name. The script never removes containers it did not
create.

**Fix:** if they are left from an earlier run, remove them with
`docker compose -p gameserver-observability-demo-smoke -f demo/docker-compose.yml down -v`;
otherwise pass another `--project-name`.

## A dashboard panel shows "No data"

**Cause:** the panel's series are not in the selected data source: the Data source selector points
to another Prometheus, the job for that row is not scraped (node_exporter for Host, mysqld_exporter
for MariaDB, cloudflared for the tunnel, the optional `fxserver_tunnel` job for the admin hostname),
or its targets have no `server` label, so the Game server filter does not match them. The Game
server selector is empty when the job `fxserver_perf` has no target with a `server` label.

**Fix:** choose the data source that has the pack's series, and give every target of those jobs
the `server` label of its game server ([configuration](configuration.md#host-and-database-jobs)).
Panels of exporters you do not run stay empty; that is expected.

## `lint_dashboards: … [shareable] missing or not the copy of …`

**Cause:** a dashboard in `grafana/dashboards/` changed, and its copy in
`grafana/dashboards/shareable/` was not written again.

**Fix:** run `python3 scripts/lint_dashboards.py --fix`, then the check again, and commit both
files. A finding `[parse] … not in the repository's format` has the same fix.

## `FXServerArtifactOld` never fires and Build age shows "No data"

**Cause:** the two build alerts and the Build age panel read `fxserver_artifact_build` and
`fxserver_artifact_installed_timestamp_seconds`, which node_exporter's textfile collector reads
from `fxserver_artifact.prom` on the game server. The file is missing (the `fxserver` role of the
`luminare.gameserver` collection writes it only with `fxserver_textfile_dir` set), node_exporter
reads another folder, or its job has no `server` label. Without the series the alerts stay silent
instead of failing.

**Fix:** on the game server, check that the file exists in the folder passed to node_exporter's
`--collector.textfile.directory`; then query `fxserver_artifact_build` in Prometheus, which must
return one series per game server with its `server` label
([configuration](configuration.md#host-and-database-jobs)).

## Alerts fire in Prometheus, but nobody gets a notification

**Cause:** the pack evaluates alerts but sends none: Prometheus needs an `alerting` block that
names your Alertmanager, and the Alertmanager a route for the alerts' labels
([ADR 0023](adr/0023-no-alertmanager-in-0-1.md)).

**Fix:** add both as shown in [configuration](configuration.md#send-the-alerts-to-alertmanager).
`curl -fsS http://127.0.0.1:9090/api/v1/alertmanagers` lists the Alertmanagers Prometheus sends
to, and `amtool config routes test --config.file=alertmanager.yml severity=critical server=game-01`
prints the receiver an alert would reach.

## Quickstart: `curl: (7) Failed to connect to 127.0.0.1 port 30120`

**Cause:** the demo stack is not running, for example because `docker compose up` stopped at a
port that was already taken, or it was started with another game port (`GSO_DEMO_GAME_PORT`).

**Fix:** `docker compose -f demo/docker-compose.yml ps` shows what runs; start it again on free
ports ([demo stack](demo.md#start-and-stop)) and send the request to the game port you chose.

## Still stuck?

Search the [issues](https://github.com/luminare-dev/gameserver-observability/issues), then ask in
the repository's [Discussions](https://github.com/luminare-dev/gameserver-observability/discussions).
Never post secrets, keys, IP addresses, hostnames or player data; redact logs before you paste
them.
