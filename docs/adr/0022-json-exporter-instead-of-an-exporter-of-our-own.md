# 0022. json_exporter instead of an exporter of our own

- **Status:** accepted
- **Date:** 2026-10-22

## Context

`dynamic.json` and `info.json` are JSON documents, and Prometheus reads only its own text
formats. Something has to turn four fields into metrics: the player count, the slots, the version
string and the OneSync flag, and, for the build alert, the Recommended build from the platform's
public version list. That component runs on the monitoring host, fetches URLs on the game port,
and has to be installed, updated and secured by every user of the pack.

## Considered options

1. prometheus-community's json_exporter (0.8.0) with modules in `json_exporter/config.yml`.
2. A small exporter of our own (Python or Go) that fetches the endpoints and serves metrics.
3. A script on a timer that writes the values into a file for node_exporter's textfile collector.

## Decision

Chosen option 1, because the four fields are plain values that json_exporter's JSONPath reads
directly, so the pack stays configuration ([ADR 0005](0005-pack-layout-and-release-archive.md)).
json_exporter is a project of the prometheus-community organisation, released with a checksums
file for each release, and runs as an ordinary service; setups that already run it only add
three modules. The
same exporter reads the version list (`fxserver_versions`). It fetches per scrape, so a value is
as fresh as the scrape. Option 2 would give full control (for example a numeric build metric
instead of a `build` label), but it is code to write, package, sign, release and keep secure for
a job that configuration does. Option 3 serves values as old as the last timer run and needs a
script with network access on the game or monitoring host.

## Consequences

- Good: no program of this project runs on the monitoring host; users update json_exporter like
  any other exporter ([toolchain](../toolchain.md) has the download and its sha256).
- Good: the CI job `exporters` runs the pinned json_exporter release with the shipped modules
  against the fake server, so a wrong path or name fails CI
  ([ADR 0012](0012-test-the-configs-against-a-fake-server.md)).
- Bad: json_exporter fetches any URL that whoever reaches it asks for, so it must listen on
  loopback or a private address ([configuration](../configuration.md#json_exporter-modules-json_exporterconfigyml)).
- Bad: JSONPath cannot count or parse, so the build number is a label of `fxserver_info` that the
  scrape job cuts out of the version string, and the build alerts read the number from the
  `fxserver` role's textfile metrics instead
  ([ADR 0017](0017-build-age-and-the-recommended-build.md)). json_exporter ignores keys it does not
  know, so `scripts/check_pack.py` reports unknown keys in the modules.
