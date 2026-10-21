# Runbook

One section per alert or failure. The pack's alert rules are not in the repository yet. This page
covers a scrape target of the pack that is down, and failures of the repository's own automation.

## Failure: a target of the pack is down

| | |
|---|---|
| **Meaning** | `up{job=~"fxserver_.*"}` is 0 for a target: Prometheus could not scrape `/perf/` (`fxserver_perf`), or json_exporter or blackbox_exporter answered with an error or not at all (`fxserver_json`, `fxserver_blackbox`). |
| **Impact** | The series of that target stop: tick times, the player count, the version or the probe results are missing for that game server until it is fixed. |
| **Diagnosis** | Prometheus → Status → Targets shows the target's last error. `server returned HTTP status 401 Unauthorized` on `fxserver_perf`: the password file and the server's `sv_prometheusBasicAuth*` values differ. `503` on `fxserver_json`: json_exporter could not fetch the JSON, see its log (`Failed to fetch JSON response`). `sample limit exceeded`: the target served more series than its `sample_limit`. `connection refused`: the exporter or the game server is not running, or the address in the scrape job is wrong. [Troubleshooting](troubleshooting.md) has each case. |
| **Mitigation** | If the game server itself is down, that is the incident; the probes `tcp_connect` and `http_fxserver_info` show it too. Otherwise the server is unaffected: only its monitoring is missing. |
| **Fix** | Correct the password file, the exporter service or the scrape job, check a changed copy of the configs with `python3 scripts/check_pack.py --allow-any-address` ([configuration](configuration.md)), and reload Prometheus. |

## Failure: the probe `http_401_expected` fails

| | |
|---|---|
| **Meaning** | `probe_success{module="http_401_expected"}` is 0: `/perf/` did not refuse a request without credentials with `401`. |
| **Impact** | When `/perf/` answers `200`, anyone who reaches the game port can read the server's tick times. |
| **Diagnosis** | `probe_http_status_code{module="http_401_expected"}`: `200` means no user and no password are set on the server; `0` means the probe got no answer (then `tcp_connect` usually fails as well). |
| **Mitigation** | Set the credentials soon; until then the exposure is limited to tick times, because `/perf/` holds no player data. Do not close TCP 30120 for it: players need that port to join. |
| **Fix** | Set `sv_prometheusBasicAuthUser` and `sv_prometheusBasicAuthPassword` in the server's secrets ([configuration](configuration.md#game-server)), write the same password into the Prometheus password file and restart the server. |

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
| **Meaning** | The promtool download did not match its pinned sha256, or `scripts/check_promtool.sh` reported invalid rules, a failing rule test, or rule files while `tests/rules/` has no rule test at all. (A rule file that no rule test names in `rule_files` fails `RuleCoverageTest` in `ci / lint-test` instead.) |
| **Impact** | The pull request should not be merged; rules that do not load or are untested would ship in the next release. |
| **Diagnosis** | Read the job log: `sha256sum` errors point to the download, `promtool check rules` and `promtool test rules` print the file, rule and expected versus actual alerts. Reproduce with `bash scripts/check_promtool.sh` and promtool 3.15.0. |
| **Mitigation** | Fix the rule or its test in the same pull request. |
| **Fix** | For checksum errors, take the version and the sha256 from the same Prometheus release ([toolchain](toolchain.md)). |

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
| **Meaning** | A download did not match its pinned sha256, or `scripts/smoke_exporters.py` reported a failed check: an exporter rejected its config, a target was not up, a metric, label or value was not as documented, a probe failed, or the fake server received a `players.json` request. |
| **Impact** | The pull request should not be merged: the configs would not deliver the documented metrics. |
| **Diagnosis** | The job log lists every check with `ok` or `FAIL` and ends with the last lines of each process's log. Reproduce with the binaries from the [toolchain page](toolchain.md) and `python3 scripts/smoke_exporters.py --bin-dir bin`; the ports 30120, 7979 and 9115 must be free. |
| **Mitigation** | Fix the config, the fake server or the expectation in the same pull request. |
| **Fix** | When a change of names or labels is intended, update `docs/metrics.md` and `EXPECTED_METRICS` in the script together; `tests/test_pack_repo.py` checks that both match the configs. For checksum errors, take the version and the sha256 from the same release ([toolchain](toolchain.md)). |
