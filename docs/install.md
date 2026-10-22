# Installation

Install the scrape jobs, the exporter modules and the rules on the host that runs Prometheus, and
the dashboard on the host that runs Grafana ([Dashboards](#dashboards)). The game server needs no
software from this pack, only the two `/perf/` credentials
([configuration](configuration.md#game-server)). There is no release yet, so the commands use the
`main` branch; once releases exist, check out a release tag instead and verify the download as
shown below.

The commands in [Install](#install), and those for Prometheus and the exporters in
[Uninstall](#uninstall), were run on 2026-10-21 as root in
a `python:3.13-slim` container, against the fake server: from a local copy instead of
`git clone`, without `sudo`, with the password written by `printf` instead of `sudoedit`, with the
exporters started by the commands of their `ExecStart=` lines and Prometheus 3.15.0 started
directly instead of as services, with `fxserver.yml`, the optional `versions.yml` and the rules
included. All seven targets were up (the version list job read 35245 from the real list), the
five rule groups were evaluated without an error, no alert was active, and the queries in
[Check that it works](#check-that-it-works) returned their series. On a second run, with an
exporter config already in each place, the first Install block left both files unchanged.
Run again on 2026-10-22 in the same image, the password block kept an existing password file and
its content.

## Requirements

| Requirement | Version | Notes |
|---|---|---|
| Prometheus | 3.15.0 tested | 3.x; `scrape_config_files` needs 2.43 or newer, the scrape jobs are checked with promtool 3.15.0 |
| json_exporter | 0.8.0 tested | the module format of 0.8.0 ([toolchain](toolchain.md) has the download and sha256) |
| blackbox_exporter | 0.29.0 tested | |
| Game server (FXServer) | build 35245 read in the source | not yet tried against a running server; see the README's Limitations |
| node_exporter, mysqld_exporter | not run here | optional, for the host, build and database alerts; scraped by jobs of your own ([configuration](configuration.md#host-and-database-jobs)) |
| Grafana | 13.2.4 tested | optional, for the [dashboard](#dashboards); dashboard schema 42, the latest of Grafana 13.2.4; other versions not tried |
| cloudflared | 2026.10.2 tested | optional, for the dashboard's tunnel panels; its metrics scraped by a job of your own |
| Network | | the Prometheus host reaches the game port (30120) over loopback, a private network or a tunnel; the exporters listen on 127.0.0.1; the optional version list job needs outbound HTTPS from json_exporter |
| Python | 3.10 or newer | only for the pack check, the fake server and the repository's tests |

## Install

`/etc/prometheus/scrape/fxserver.yml` is this pack's own file. The two exporter configs are
installed only where none exists yet: `test -e … ||` skips a file that is already there, so an
exporter that serves other modules keeps them. If json_exporter or blackbox_exporter already runs
on this host (a distribution package may keep its config in another place), copy this pack's
modules into that config under `modules:` instead, after checking that it has no modules of the
same names: `fxserver_dynamic`, `fxserver_info` and `fxserver_versions` from
`json_exporter/config.yml`, and
`tcp_connect`, `http_fxserver_info`, `http_401_expected` and `http_access_protected` from
`blackbox/blackbox.yml`.

```bash
git clone https://github.com/luminare-dev/gameserver-observability.git
cd gameserver-observability
sudo install -D -m 0644 prometheus/scrape/fxserver.yml /etc/prometheus/scrape/fxserver.yml
sudo install -D -m 0644 -t /etc/prometheus/rules rules/*.yml
test -e /etc/json_exporter/config.yml || sudo install -D -m 0644 json_exporter/config.yml /etc/json_exporter/config.yml
test -e /etc/blackbox_exporter/blackbox.yml || sudo install -D -m 0644 blackbox/blackbox.yml /etc/blackbox_exporter/blackbox.yml
```

`/etc/prometheus/rules/` then holds this pack's five rule files; if you keep rules of your own
there, check first that none has the same name. Leave out a rule file whose data you do not
collect, or keep it: rules without data stay silent ([configuration](configuration.md#rules-rules)).

Then change the targets and the `server` label in `/etc/prometheus/scrape/fxserver.yml`
([configuration](configuration.md#scrape-jobs-prometheusscrapefxserveryml)), and write the `/perf/`
password into a file only Prometheus can read (the group is the one Prometheus runs as, often
`prometheus`):

```bash
sudo install -d -m 0750 -g prometheus /etc/prometheus/secrets
test -e /etc/prometheus/secrets/fxserver_perf || sudo install -m 0640 -g prometheus /dev/null /etc/prometheus/secrets/fxserver_perf
sudoedit /etc/prometheus/secrets/fxserver_perf   # the password only, one line
```

Include the jobs and the rules in `/etc/prometheus/prometheus.yml`:

```yaml
scrape_config_files:
  - /etc/prometheus/scrape/fxserver.yml
rule_files:
  - /etc/prometheus/rules/*.yml
```

The host, build and database alerts read node_exporter and mysqld_exporter: give their jobs the
`server` label of the game server ([configuration](configuration.md#host-and-database-jobs)).

Run both exporters as services of your init system, listening on loopback. If they are not
services yet, these are the `ExecStart=` lines of their systemd units (binaries in
`/usr/local/bin`; the downloads and their sha256 are on the [toolchain page](toolchain.md)); use
the path of the merged config if you merged the modules:

```ini
# json_exporter.service
ExecStart=/usr/local/bin/json_exporter --config.file=/etc/json_exporter/config.yml --web.listen-address=127.0.0.1:7979
# blackbox_exporter.service
ExecStart=/usr/local/bin/blackbox_exporter --config.file=/etc/blackbox_exporter/blackbox.yml --web.listen-address=127.0.0.1:9115
```

Restart an exporter that was already running, so that it loads the new modules. Then check the
Prometheus config and reload Prometheus:

```bash
promtool check config /etc/prometheus/prometheus.yml
sudo systemctl reload prometheus
```

The two optional jobs are installed the same way and added to `scrape_config_files`: the admin
hostname probe (`prometheus/scrape/tunnel.yml`, set its target first) and the version list for
`FXServerBuildBehindRecommended` (`prometheus/scrape/versions.yml`, needs outbound HTTPS):

```bash
sudo install -D -m 0644 prometheus/scrape/versions.yml /etc/prometheus/scrape/versions.yml
```

## Dashboards

The dashboard "Game server overview" needs Grafana with a Prometheus data source that holds the
pack's series. It picks Grafana's default Prometheus data source; switch it with the Data source
selector at the top. Only if Grafana has no data source for this Prometheus yet, install the
pack's one first and set its `url` to your Prometheus, for example `http://127.0.0.1:9090`
([configuration](configuration.md#dashboard-grafana)). On the Grafana host, from the clone (paths
of the Grafana packages; adapt them for another setup):

```bash
sudo install -D -m 0644 grafana/provisioning/datasources/gameserver-observability.yml /etc/grafana/provisioning/datasources/gameserver-observability.yml
sudoedit /etc/grafana/provisioning/datasources/gameserver-observability.yml   # url: your Prometheus
```

Then install the dashboard and restart Grafana. Copy only `grafana/dashboards/*.json`, not the
`shareable/` folder:

```bash
sudo install -D -m 0644 grafana/provisioning/dashboards/gameserver-observability.yml /etc/grafana/provisioning/dashboards/gameserver-observability.yml
sudo install -D -m 0644 -t /var/lib/grafana/dashboards/gameserver-observability grafana/dashboards/*.json
sudo systemctl restart grafana-server
```

Without access to Grafana's files, import the copy without variables instead: Dashboards → New →
Import, upload `grafana/dashboards/shareable/game-server-overview.json` and choose the Prometheus
data source. It shows every game server at once. Do not import it into the folder of the
provisioned dashboard, which has the same title.

The commands above were run on 2026-10-21 as root in a `grafana/grafana:13.2.4` container (without
`sudo`, with the container's start instead of `systemctl`, the data source file unchanged and
Prometheus reachable as `prometheus:9090`): Grafana created the folder "Game server" with the
dashboard and the data source "Game server metrics", the dashboard opened with that data source
and the Game server selector on All (`game-01`), and every panel showed data from the fake server
and the exporters. The import of the shareable copy was run through Grafana's import API.

## Verify the release download

Every release has a `SHA256SUMS` file and a build provenance attestation (the attestation only
for releases made while the repository is public):

```bash
sha256sum -c SHA256SUMS
gh attestation verify gameserver-observability-X.Y.Z.tar.gz --repo luminare-dev/gameserver-observability
```

## Check that it works

In Prometheus (Status → Targets) the jobs `fxserver_perf`, `fxserver_json` and
`fxserver_blackbox` are up, and these queries return one series per game server (three for
the probe):

```promql
fxserver_clients
fxserver_tick_time_seconds_count{thread="svMain"}
probe_success{job="fxserver_blackbox"}
```

`probe_success{module="http_401_expected"}` must be 1: it is 0 when `/perf/` answers without
credentials. Status → Rules lists the groups `fxserver-tick-time`, `fxserver-alerts`,
`fxserver-build-alerts`, `host-alerts` and `mariadb-alerts` with every rule `OK`, and within a
minute or two this query returns three series per game server (`svMain`, `svNetwork`, `svSync`):

```promql
server_thread:fxserver_tick_time_seconds:p95_1m
```

With the version list job, `fxserver_recommended_build` returns the current Recommended build.
Status → Alerts shows what is pending or firing. [Troubleshooting](troubleshooting.md) covers the
usual errors.

In Grafana, Dashboards → Game server → Game server overview shows your game servers in the Game
server selector, Status `Up` and the player count. Panels of rows whose exporter you do not
scrape (host, MariaDB, tunnel, admin hostname) show "No data".

## Check the repository

```bash
bash scripts/test.sh                    # unit tests, including the fake server and the pack check
python3 scripts/check_pack.py           # configs parse, privacy rules, and promtool when on the PATH
bash scripts/check_promtool.sh          # rule checks and rule tests (needs promtool)
python3 scripts/smoke_exporters.py      # end to end (needs prometheus, json_exporter, blackbox_exporter)
python3 scripts/lint_dashboards.py      # dashboards and their shareable copies, and promtool when on the PATH
```

`scripts/test.sh` ends with a summary like this one, from a machine without gitleaks,
markdownlint-cli2 and promtool (the tests that need them are skipped):

```text
Ran 254 tests in 9.082s

OK (skipped=13)
```

`python3 scripts/check_pack.py` with promtool on the `PATH` prints:

```text
check_pack: 0 finding(s) in 5 parsed file(s); promtool: 3 file(s) passed promtool check config
```

`python3 scripts/lint_dashboards.py` with promtool on the `PATH` prints:

```text
lint_dashboards: 0 finding(s) in 2 file(s), 75 queries; promtool: 75 queries passed promtool check rules
```

`python3 scripts/smoke_exporters.py --bin-dir bin` (binaries as on the [toolchain page](toolchain.md))
prints one line per check and ends with:

```text
smoke_exporters: all checks passed (187 s)
```

## Uninstall

Remove the `scrape_config_files` entries and reload Prometheus. Stop the exporters, or, if they
serve other modules too, delete this pack's modules from their configs and restart them. Then
delete the files this pack installed, the clone and the virtual environment of `scripts/test.sh`:

```bash
sudo rm -f /etc/prometheus/scrape/fxserver.yml /etc/prometheus/secrets/fxserver_perf
sudo rm -f /etc/prometheus/rules/{fxserver.recording,fxserver.alerts,build.alerts,host.alerts,mariadb.alerts}.yml
rm -rf gameserver-observability "${XDG_CACHE_HOME:-$HOME/.cache}/gameserver-observability"
```

Only where they apply: the optional jobs, if you installed them, and the exporter configs, if
[Install](#install) created them (keep them if the modules were merged into existing configs):

```bash
sudo rm -f /etc/prometheus/scrape/tunnel.yml /etc/prometheus/scrape/versions.yml
sudo rm -f /etc/json_exporter/config.yml /etc/blackbox_exporter/blackbox.yml
```

Directories that are empty afterwards (`/etc/prometheus/secrets`, `/etc/prometheus/rules`,
`/etc/prometheus/scrape`, `/etc/json_exporter`, `/etc/blackbox_exporter`) can be removed with
`sudo rmdir`.

For the dashboard, remove the provisioning file together with the dashboard files and restart
Grafana; it then deletes the dashboard (with only the dashboard files gone, it would keep it).
The empty folder "Game server" stays until you delete it in Grafana:

```bash
sudo rm -f /etc/grafana/provisioning/dashboards/gameserver-observability.yml
sudo rm -rf /var/lib/grafana/dashboards/gameserver-observability
sudo systemctl restart grafana-server
```

A provisioned data source cannot be deleted in Grafana, and it stays when its file is removed. If
you installed the pack's one, replace its file with one that deletes it, restart Grafana, then
remove the file:

```bash
printf 'apiVersion: 1\ndeleteDatasources:\n  - name: Game server metrics\n    orgId: 1\n' |
  sudo tee /etc/grafana/provisioning/datasources/gameserver-observability.yml
sudo systemctl restart grafana-server
sudo rm /etc/grafana/provisioning/datasources/gameserver-observability.yml
```

These steps were run on 2026-10-21 in the same container: after the first restart the dashboard
was gone and the folder was left; after the second the data source was gone.
