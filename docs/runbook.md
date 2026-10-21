# Runbook

One section per alert of the pack's rules (`rules/`), then one per failure of the repository's
own automation. The `runbook_url` of every alert links to its section here. Each section answers
the same five questions: what fired (Meaning), what it does to players and admins (Impact), how to
find the cause (Diagnosis), how to limit the damage now (Mitigation) and how to remove the cause
(Fix).

Severity `critical` means act now: the game server or its database is down for players, or the
admin interface is open to anyone. `warning` means act within the day: the server is slow, at
risk, or partly unmonitored ([ADR 0015](adr/0015-alerts-per-game-server.md)). The queries use `game-01` for the `server`
label; use the value of the alert. The commands assume a game server set up like the
`luminare.gameserver` collection sets it up (service `fxserver.service`, files under
`/opt/fxserver`); adapt them to your setup. Thresholds and how to change them:
[configuration](configuration.md#rules-rules).

Facts about the platform below come from its support articles:
[server list](https://support.cfx.re/hc/en-us/articles/8855785066012) (registration, required
variables, up to 8 minutes to appear) and
[build support](https://support.cfx.re/hc/en-us/articles/12242287993500) (support windows, builds
older than 3 months).

## Alert: FXServerDown

| | |
|---|---|
| **Meaning** | For 2 minutes the game port of the server has refused TCP connections (probe `tcp_connect`), or `info.json` has not answered with `200` (probe `http_fxserver_info`). Severity critical. |
| **Impact** | Players cannot join, and connected players have lost the server. The server's other series stop too, so the other alerts for it stay quiet until it is back. |
| **Diagnosis** | `probe_success{job="fxserver_blackbox", server="game-01"}` shows which probe fails. `tcp_connect` 0: no process listens on the port; `systemctl status fxserver` and `journalctl -u fxserver -n 200` show why it stopped (a crash, a missing or rejected license key, the port in use, a failed update). `tcp_connect` 1 but `http_fxserver_info` 0: the process runs but does not answer; `probe_http_status_code{module="http_fxserver_info"}` 0 means a timeout (the server hangs, often in a resource), `403` that the server refused the request ([request paranoia](metrics.md#request-paranoia-and-rate-limits)). Check the host as well: memory (`journalctl -k \| grep -i "out of memory"`) and disk ([HostDiskAlmostFull](#alert-hostdiskalmostfull)). |
| **Mitigation** | Restart the server (`sudo systemctl restart fxserver`, or from txAdmin). If it broke right after an update, switch back to the previous build (with the collection: set `fxserver_build` to it and run the playbook) and restart. A planned restart that takes longer than 2 minutes also fires this alert: silence it in Alertmanager for planned maintenance. |
| **Fix** | Remove the cause from the log: renew the license key, correct the configuration, free the port, give the host more memory, or fix the resource that hangs the server. |

## Alert: FXServerTargetDown

| | |
|---|---|
| **Meaning** | For 10 minutes Prometheus has not been able to scrape at least one target of the job in the alert (`up` is 0), while the probes do not report the server as down. Severity warning. |
| **Impact** | The game server may be fine, but the series of that target are missing, and the alerts that read them stay quiet: `fxserver_perf` feeds [FXServerTickTimeHigh](#alert-fxserverticktimehigh) and [FXServerNoPlayersAfterRestart](#alert-fxservernoplayersafterrestart); `fxserver_json` the player count; `fxserver_blackbox` [FXServerDown](#alert-fxserverdown) and [FXServerPerfEndpointExposed](#alert-fxserverperfendpointexposed); `fxserver_tunnel` the admin hostname alerts. The version list job (`fxserver_versions`) has no `server` label and is not part of this alert: check `up{job="fxserver_versions"}` there. |
| **Diagnosis** | Prometheus → Status → Targets shows the target's last error. `server returned HTTP status 401 Unauthorized` on `fxserver_perf`: the password file and the server's `sv_prometheusBasicAuth*` values differ. `503` on `fxserver_json`: json_exporter could not fetch the JSON, see its log (`Failed to fetch JSON response`); a `403 Nope.` comes from request paranoia when a proxy sits between json_exporter and the server, a `429` from the server's rate limit. `connection refused` on an exporter job: json_exporter or blackbox_exporter is not running (`systemctl status json_exporter blackbox_exporter`). `sample limit exceeded`: the target served more series than its `sample_limit` ([cardinality budget](cardinality.md)). [Troubleshooting](troubleshooting.md) has each case. |
| **Mitigation** | Start the exporter that stopped. Until the target is back, watch the server through txAdmin or its console. |
| **Fix** | Correct the password file, the exporter service or the scrape job, check a changed copy of the configs with `python3 scripts/check_pack.py --allow-any-address` ([configuration](configuration.md)), and reload Prometheus. |

## Alert: FXServerTickTimeHigh

| | |
|---|---|
| **Meaning** | For 5 minutes more than 5 % of the server's main-thread ticks (`svMain`) have taken longer than 50 ms, its timer interval: the 95th percentile over each minute stayed above 50 ms. Severity warning. |
| **Impact** | The server falls behind its 20 ticks per second: scripts, events and synchronisation run late, and players notice lag, rubber-banding and delayed actions. |
| **Diagnosis** | `server_thread:fxserver_tick_time_seconds:p95_1m{server="game-01"}` shows when it started and whether other threads are slow too; `server_thread:fxserver_tick_time_seconds_count:rate1m{thread="svMain"}` drops below 20 while ticks are slow. Compare the start with resource updates, restarts and the player count (`fxserver_clients`). Record a profile with the server console's `profiler` command to see which resource takes the time; txAdmin's performance chart reads the same `/perf/` histogram. Check the host: CPU usage and steal (`rate(node_cpu_seconds_total{mode="steal"}[5m])` with node_exporter), memory and swap, and slow database queries ([MariaDBSlowQueries](#alert-mariadbslowqueries)). |
| **Mitigation** | Stop or restart the resource that the profile names (`stop <resource>` or `restart <resource>` in the console), or roll back its last update. If the host is short of CPU, move other workloads off it. |
| **Fix** | Fix the resource: work that runs every tick without a wait, large loops, or code that waits on the database inside a tick. If no resource stands out and the CPU is saturated, the host is too small for the player count. |

## Alert: FXServerNoPlayersAfterRestart

| | |
|---|---|
| **Meaning** | The server restarted 30 to 60 minutes ago (its `svMain` tick counter started at 0 again), has had no player in the last 30 minutes, and had players in the 30 minutes before. The alert clears an hour after the restart or when a player joins. Severity warning. |
| **Impact** | Players who were online before the restart did not come back: they may not find the server in the server list, or may not be able to join it. |
| **Diagnosis** | Look for the server in the server list of the game client; after a restart it can take up to 8 minutes to appear. Check the server's log since the restart (`journalctl -u fxserver --since "-1h"`) for errors about the license key or the server list. Check that `sv_projectName` and `sv_projectDesc` are set (the list requires both), that `sv_lan` is not `true` (a LAN-only server is not listed), and that `sv_master1` is not set to an empty value (the server then stays listed, but the server browser disables its connect button). Check the build: builds older than 3 months cannot be joined from the server list ([FXServerArtifactOld](#alert-fxserverartifactold), [FXServerBuildBehindRecommended](#alert-fxserverbuildbehindrecommended)). Try to join directly with `connect <address>:30120` in the client console; if that fails too, check that the game port is open for TCP and UDP from outside (the pack's probes run from the Prometheus host and do not test UDP). |
| **Mitigation** | Tell the community the direct connect address. If the server did not register in the list, restart it once more. |
| **Fix** | Correct the server variables, update the build, or open the game port, depending on the cause. If restarts are scheduled at a time when players leave anyway, this alert can fire without a problem: move the restart or silence the alert for that time. |

## Alert: FXServerPerfEndpointExposed

| | |
|---|---|
| **Meaning** | For 5 minutes `/perf/` has answered a request without credentials with `2xx` instead of `401` (probe `http_401_expected`, `probe_http_status_code`). Severity warning. |
| **Impact** | Anyone who reaches the game port can read the server's tick times. `/perf/` holds no player data, and unauthenticated requests are rate-limited by the server. |
| **Diagnosis** | `probe_http_status_code{module="http_401_expected", server="game-01"}` is `200`: neither `sv_prometheusBasicAuthUser` nor `sv_prometheusBasicAuthPassword` is set on the running server, for example after a configuration change or because `secrets.cfg` is no longer executed from `server.cfg`. |
| **Mitigation** | Set the credentials soon. Do not close TCP 30120 for it: players need that port to join. |
| **Fix** | Set `sv_prometheusBasicAuthUser` and `sv_prometheusBasicAuthPassword` in the server's secrets ([configuration](configuration.md#game-server)), write the same password into the Prometheus password file and restart the server. |

## Alert: FXServerAdminHostnameUnprotected

| | |
|---|---|
| **Meaning** | For 5 minutes the admin hostname (job `fxserver_tunnel`, for example the txAdmin web interface published through a tunnel) has answered a request without a login with `2xx`, instead of a redirect to the access proxy's login page or a refusal. Severity critical. |
| **Impact** | The admin interface is reachable from the internet without the access proxy; its own login is the only protection left. |
| **Diagnosis** | `curl -sI https://<hostname>/` from outside the network answers `200` with the admin page. Check the access application and its policy for the hostname at the tunnel provider (deleted, disabled, or covering another path), and the tunnel's ingress rules (the hostname may point to the admin interface without the access layer). |
| **Mitigation** | Take the hostname off the tunnel (remove its ingress rule or stop the tunnel connector) until the protection is back. Admins can reach the interface through an SSH port forward to `127.0.0.1:40120` meanwhile. |
| **Fix** | Restore the access application and its policy, then check that a request without a login gets `302`, `303` or `403` again (the alert clears). Review the admin interface's log for logins during the exposure. |

## Alert: FXServerAdminHostnameProbeFailing

| | |
|---|---|
| **Meaning** | For 10 minutes the admin hostname has not answered over HTTPS with a redirect to the login page or a refusal (`302`, `303` or `403`), and it has not answered `2xx` either: no answer, a TLS or DNS error, plain HTTP, or another status such as `502`. Severity warning. |
| **Impact** | Admins cannot reach the admin interface through the hostname. Players are not affected. |
| **Diagnosis** | `probe_http_status_code{job="fxserver_tunnel", server="game-01"}`: `0` means no connection (DNS, network, timeout), `5xx` that the tunnel or the access proxy cannot reach the admin interface. On the Prometheus host, `curl 'http://127.0.0.1:9115/probe?module=http_access_protected&target=https://<hostname>/&debug=true'` shows every step of the probe, including the TLS details. Check the tunnel connector's service and log on the game server host, and whether the admin interface listens on its port. |
| **Mitigation** | Use an SSH port forward to `127.0.0.1:40120` to reach the admin interface. |
| **Fix** | Restart or repair the tunnel connector, correct the DNS record or the certificate, or start the admin interface again. |

## Alert: FXServerArtifactOld

| | |
|---|---|
| **Meaning** | The active server build was switched on more than 8 weeks (56 days) ago, read from the textfile metric `fxserver_artifact_installed_timestamp_seconds` on the host. The switch time is a lower bound of the build's age: a build that was already old when it was switched on is older than the alert says. Severity warning. |
| **Impact** | None yet. A Recommended build loses support 6 weeks after the next one is released, and unsupported builds older than 3 months cannot be joined from the server list. |
| **Diagnosis** | The running build is the `build` label of `fxserver_info{server="game-01"}` (and `fxserver_artifact_build` on the host). The current Recommended build is `fxserver_recommended_build` (with the job `fxserver_versions`) or `recommended` in the platform's version list, `https://changelogs-live.fivem.net/api/changelog/versions/linux/server`; its `support_policy` holds the date each build's support ends. The current Recommended build stays supported, so if it is the one that runs, the alert only says that it was switched on long ago. |
| **Mitigation** | Nothing urgent; plan the update before the build loses support. |
| **Fix** | Update to the current Recommended build (with the collection: set `fxserver_build`, `fxserver_artifact_url` and `fxserver_artifact_sha256`, see its upgrade guide). The alert clears when the new build is switched on. If the build that runs is still the current Recommended build, there is nothing newer to switch to: silence the alert until the next Recommended build is out. |

## Alert: FXServerBuildBehindRecommended

| | |
|---|---|
| **Meaning** | The build the server runs (`fxserver_artifact_build`, a textfile metric on the host) is older than every Recommended build that the platform's version list named in the last 14 days (`fxserver_recommended_build`, job `fxserver_versions`): a newer Recommended build has been out for 14 days, or for as long as the version list has been read if that is shorter. Severity warning. |
| **Impact** | None yet. A Recommended build loses support 6 weeks after the next one is released, and builds older than 3 months cannot be joined from the server list. |
| **Diagnosis** | `fxserver_artifact_build{server="game-01"}` is the build that runs, `fxserver_recommended_build` the Recommended build the version list names now; `min_over_time(fxserver_recommended_build[14d])` is the value the alert compares with. The list itself: `curl -fsS https://changelogs-live.fivem.net/api/changelog/versions/linux/server` (`recommended`, `recommended_download`, and the date each build's support ends in `support_policy`). If `fxserver_recommended_build` is empty, the job cannot read the list: check `up{job="fxserver_versions"}` and the json_exporter log ([troubleshooting](troubleshooting.md#fxserver_recommended_build-is-empty)). |
| **Mitigation** | Nothing urgent; plan the update before the build's support ends. Try the new build on a test server first. |
| **Fix** | Update to the Recommended build (with the collection: set `fxserver_build`, `fxserver_artifact_url` and `fxserver_artifact_sha256` together, see its upgrade guide). The alert clears once the textfile metric shows the new build. If you stay on an older build on purpose, silence the alert until you update. |

## Alert: HostDiskAlmostFull

| | |
|---|---|
| **Meaning** | For 10 minutes less than 15 % of a writable filesystem on the game server's host has been available to processes that do not run as root (node_exporter, `node_filesystem_avail_bytes`). Severity warning. |
| **Impact** | None yet. When it is full, the game server cannot write logs or save data, the database stops writing, and backups and build updates fail. |
| **Diagnosis** | `df -h <mountpoint>` and `sudo du -xh --max-depth=2 <mountpoint> \| sort -h \| tail -n 20`. Usual growth on a game server host: old builds in `/opt/fxserver/artifacts`, local backups in `/var/backups/fxserver`, txAdmin's logs under `/opt/fxserver/txData`, the journal (`journalctl --disk-usage`), the database in `/var/lib/mysql`, and Prometheus' data if it runs on the same host. |
| **Mitigation** | Free space: `sudo journalctl --vacuum-size=500M`, delete backups that are also stored off the host, delete builds that are neither the current nor the previous one. |
| **Fix** | Set retention where the growth comes from (journald `SystemMaxUse`, the number of kept backups and builds, txAdmin's log retention, old rows in the database), or give the host a larger disk. |

## Alert: MariaDBDown

| | |
|---|---|
| **Meaning** | For 2 minutes mysqld_exporter has not been able to connect to the database or to query it (`mysql_up` is 0). Severity critical. |
| **Impact** | Resources that keep their data in the database cannot load or save it: players may lose progress, and joining can fail. |
| **Diagnosis** | `systemctl status mariadb` and `journalctl -u mariadb -n 100`. Common causes: a full disk ([HostDiskAlmostFull](#alert-hostdiskalmostfull)), the kernel's out-of-memory killer (`journalctl -k \| grep -i "out of memory"`), a crashed table after a power loss. If MariaDB runs, the exporter's own login may fail: its log then says `Access denied`. |
| **Mitigation** | Start MariaDB again (`sudo systemctl restart mariadb`). Restart the game server's resources that use the database once it is back, or the whole server if they do not reconnect. |
| **Fix** | Remove the cause from the log: free disk space, give the host more memory or lower `innodb_buffer_pool_size`, repair the table, or correct the exporter's credentials. |

## Alert: MariaDBSlowQueries

| | |
|---|---|
| **Meaning** | For 10 minutes the database has run more than one slow query a minute, averaged over 5 minutes (`mysql_global_status_slow_queries`). A query is slow when it runs longer than `long_query_time` (10 s by default). Severity warning. |
| **Impact** | Resources that wait for these queries respond late; if they wait inside a tick, the server lags ([FXServerTickTimeHigh](#alert-fxserverticktimehigh)). |
| **Diagnosis** | `SHOW FULL PROCESSLIST;` shows the queries running now. Turn on the slow query log (`SET GLOBAL slow_query_log = ON;`), find its file with `SHOW VARIABLES LIKE 'slow_query_log_file';` and summarise it with `mysqldumpslow`. `EXPLAIN` a slow query: a full table scan points to a missing index; `SHOW ENGINE INNODB STATUS\G` shows lock waits. |
| **Mitigation** | End a runaway query (`KILL <id>;`), or stop the resource that sends it. |
| **Fix** | Add the missing index, delete old rows from tables that only grow (logs, history), or give the buffer pool more memory. If `long_query_time` was lowered on purpose, raise the alert's threshold to match ([configuration](configuration.md#rules-rules)). |

## Failure: the release build fails on the tag

| | |
|---|---|
| **Meaning** | The release workflow created the tag `vX.Y.Z` and a draft release, but the `build` job failed: `bash scripts/test.sh` on the tag, or packing the archive. |
| **Impact** | The draft release has no files and stays unpublished; users see no new release. |
| **Diagnosis** | Open the failed run under Actions → release, job `build`. Run `git checkout vX.Y.Z && bash scripts/test.sh` locally to reproduce. |
| **Mitigation** | Nothing is published, so nothing has to be withdrawn. If the failure was transient (a download or PyPI timeout), use **Re-run failed jobs** on the run; the jobs check out the same tag again. |
| **Fix** | Fix the cause in a pull request. The version in `.release-please-manifest.json` already moved to X.Y.Z, so the fix is released under the next version number. Delete the unpublished draft release and its tag, so the broken version does not linger. |

## Failure: the release pull request shows no checks

| | |
|---|---|
| **Meaning** | release-please opened or updated its pull request with `GITHUB_TOKEN`, and changes made with that token do not start other workflows. |
| **Impact** | The required checks never report, so the pull request cannot be merged. |
| **Diagnosis** | The pull request `chore(main): release X.Y.Z` lists no runs of `ci` or `pr`. |
| **Mitigation** | Close the pull request and reopen it once; that starts the checks. |
| **Fix** | None needed; this is how `GITHUB_TOKEN` works ([ADR 0004](adr/0004-draft-releases-with-checksums-and-provenance.md)). |

## Failure: the `promtool` job fails

| | |
|---|---|
| **Meaning** | The promtool download did not match its pinned sha256, or `scripts/check_promtool.sh` reported invalid rules (`promtool check rules` with all lint checks, lint findings fatal), a failing rule test, or rule files while `tests/rules/` has no rule test at all. (A rule file that no rule test names in `rule_files`, an alert without a firing and a quiet case, or a missing runbook section fails `tests/test_pack_repo.py` or `tests/test_rules.py` in `ci / lint-test` instead.) |
| **Impact** | The pull request should not be merged; rules that do not load or are untested would ship in the next release. |
| **Diagnosis** | Read the job log: `sha256sum` errors point to the download, `promtool check rules` and `promtool test rules` print the file, rule and expected versus actual alerts or values. Reproduce with `bash scripts/check_promtool.sh` and promtool 3.15.0. |
| **Mitigation** | Fix the rule or its test in the same pull request. |
| **Fix** | For checksum errors, take the version and the sha256 from the same Prometheus release ([toolchain](toolchain.md)). When a rule changes on purpose, change its expected alerts and annotations in `tests/rules/` and its section in this runbook with it. |

## Failure: the pack check fails

| | |
|---|---|
| **Meaning** | `python3 scripts/check_pack.py` found a problem in `prometheus/`, `json_exporter/` or `blackbox/`: a file does not parse, a config names `players.json`, adds a label tied to a player, sets a password or a secret header inline, uses an address outside loopback and the documentation ranges, or asks an exporter for a module it does not have; or `promtool check config` failed. The unit tests run it in `ci / lint-test`, the `promtool` job runs it with `--require-promtool`. |
| **Impact** | The pull request must not be merged: the change would ship a broken config or one that collects data about players. |
| **Diagnosis** | Each finding names the file, the check and the cause, for example `prometheus/scrape/fxserver.yml: [labels] job fxserver_perf static label: label 'player' could identify a player`. Reproduce with `python3 scripts/check_pack.py` (with promtool 3.15.0 on the `PATH` for the promtool part). |
| **Mitigation** | Fix the config in the same pull request. |
| **Fix** | Follow the message; [metrics reference](metrics.md#not-collected) lists what the pack never collects and why. A parse finding about unsupported YAML means: write the value the way the other configs do (quoted strings, `true`/`false`, one-line flow lists) ([ADR 0011](adr/0011-pack-check-in-standard-library-python.md)). An `[addresses]` finding in a copy with the addresses of your servers is expected: check that copy with `--allow-any-address`; in this repository, use loopback or the documentation ranges. |

## Failure: the `exporters` job fails

| | |
|---|---|
| **Meaning** | A download did not match its pinned sha256, or `scripts/smoke_exporters.py` reported a failed check: an exporter rejected its config, a target was not up, a metric, label or value was not as documented, a probe failed, the fake server received a `players.json` request, a rule file was not loaded or a rule did not evaluate, or the rules did not react as expected to the healthy server, to the tick-time spike or to the stopped server. |
| **Impact** | The pull request should not be merged: the configs would not deliver the documented metrics, or the rules would not work on them. |
| **Diagnosis** | The job log lists every check with `ok` or `FAIL` and ends with the last lines of each process's log. Reproduce with the binaries from the [toolchain page](toolchain.md) and `python3 scripts/smoke_exporters.py --bin-dir bin`; the ports 30120, 7979 and 9115 must be free. |
| **Mitigation** | Fix the config, the rule, the fake server or the expectation in the same pull request. |
| **Fix** | When a change of names or labels is intended, update `docs/metrics.md` and `EXPECTED_METRICS` in the script together; `tests/test_pack_repo.py` checks that both match the configs. When a rule changes on purpose, change the script's expectations with it (`RECORDED`, the alert labels in `rule_checks`). For checksum errors, take the version and the sha256 from the same release ([toolchain](toolchain.md)). |
