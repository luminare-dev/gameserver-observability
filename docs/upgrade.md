# Upgrading

Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Before 1.0.0 a minor
release may contain breaking changes; they are listed under "BREAKING CHANGES" in the
[changelog](../CHANGELOG.md). For this pack, breaking means a change you have to follow in your
own setup: a renamed or removed metric, label, alert, rule file, exporter module or dashboard
variable, which your own queries, Alertmanager routes, silences or dashboards may use.

## General steps

1. Read the changelog entries between your version and the new one, the "BREAKING CHANGES" first.
2. Back up your copies: `/etc/prometheus/scrape/fxserver.yml` (it holds your targets and `server`
   labels), the exporter configs, and any copy of the dashboard you changed in Grafana.
3. Get the new release: download it and verify it as shown in
   [Installation](install.md#verify-the-release-download), or check out its tag in your clone
   (`git fetch --tags && git checkout vX.Y.Z`).
4. Compare the shipped files with your copies, and take the changes into them:

   ```bash
   diff -u /etc/prometheus/scrape/fxserver.yml prometheus/scrape/fxserver.yml
   diff -u /etc/json_exporter/config.yml json_exporter/config.yml
   diff -u /etc/blackbox_exporter/blackbox.yml blackbox/blackbox.yml
   ```

   Keep your targets and `server` labels in the scrape file. The `/perf/` password file stays as
   it is: the install command creates it only where none exists. Install the rule files again
   with the command of [Install](install.md#install), and delete a rule file from
   `/etc/prometheus/rules/` that the new release no longer has. Restart an exporter whose config
   changed.
5. Check the config and reload Prometheus:

   ```bash
   promtool check config /etc/prometheus/prometheus.yml
   sudo systemctl reload prometheus
   ```

6. Copy the dashboard files again with the commands of [Dashboards](install.md#dashboards) and
   restart Grafana; the provisioning file also makes Grafana read the folder again every 60
   seconds.
7. Run the checks of [Check that it works](install.md#check-that-it-works).

## Prometheus, the exporters and Grafana

The pack is tested with the versions under "Supported versions" in the README; the repository's
CI downloads exactly those ([toolchain](toolchain.md)). After you upgrade Prometheus,
json_exporter, blackbox_exporter or Grafana on your side, run the checks of
[Check that it works](install.md#check-that-it-works) again. The json_exporter modules have the
format of 0.8.0, and the dashboard has schema 42, the latest of Grafana 13.2.4; other versions
have not been tried.

## The game server

A new FXServer build may change the endpoints the pack reads. The source code of the endpoints was
the same in builds 35245 and 37692 (README, Results), and nothing has been tried on a running
server yet. After switching to a build outside that range, check in Prometheus that:

- `up{job=~"fxserver_.*"}` is 1 for every target; a scrape that keeps failing raises
  `FXServerTargetDown`;
- `fxserver_info` has the new build number in its `build` label (if the label is missing, the
  version string has another shape: [metrics reference](metrics.md#job-fxserver_json-infojson-and-dynamicjson-through-json_exporter));
- `probe_success{module="http_401_expected"}` is still 1, so `/perf/` still refuses requests
  without credentials.

With the `luminare.gameserver` collection, the build metrics (`fxserver_artifact_build` and the
time of the switch) change when the `fxserver` role switches the build, so `FXServerArtifactOld`
ends with the update.

## Version notes

No release so far needs manual steps. A release that does gets its own section here.
