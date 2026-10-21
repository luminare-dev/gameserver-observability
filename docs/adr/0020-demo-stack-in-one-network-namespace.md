# 0020. Demo stack in one network namespace

- **Status:** accepted
- **Date:** 2026-10-21

## Context

The pack needs something to show without a game server: a stack that runs the scrape jobs,
exporter modules, rules and dashboard against the simulated server, that CI can start, and that
screenshots can be taken of. The pack's files are written for one host: the scrape jobs reach the
game server and the exporters on `127.0.0.1`, and the optional data source file names
`prometheus:9090`. A stack that needed copies of these files with other addresses would show,
and test, something other than what is installed. The demo also must not publish anything beyond
the machine it runs on, and it must not need a password that someone could reuse.

## Considered options

1. Compose services that share the network namespace of the Prometheus service, the pack's files
   mounted unchanged, and only Prometheus, Grafana and the simulated server published on
   `127.0.0.1`.
2. Compose services on their own network with a demo copy of the scrape config that uses the
   service names as targets.
3. Host networking for every service.

## Decision

Chosen option 1. Inside one namespace `127.0.0.1` means the same thing as on a single host, so the
scrape file, the exporter configs, the rules, the provisioning files and the dashboard are
mounted from the repository as they are, at the paths of the [installation guide](../install.md).
The main config, `prometheus/prometheus.demo.yml` (the place
[ADR 0005](0005-pack-layout-and-release-archive.md) gives it), is the one of that guide.
Prometheus owns the namespace because it is what everything else talks to, and because the
simulated server can then be stopped and started alone (to watch `FXServerDown`). Option 2 needs
a second scrape config that can drift from the shipped one and puts service names into the
`instance` labels; option 3 puts the exporters and the simulated server's control endpoint on the
host's network.

Grafana runs without any account (`disable_initial_admin_creation`), with anonymous viewers and
no sign-in, so there is no default password; the dashboard is its home page. The simulated server
runs from the pinned `python:3.13-slim` image with the script mounted, so there is no image to
build. Every image is pinned by digest at the versions CI tests with the pinned binaries;
`tests/test_demo.py` checks the pins, the mounts and the published ports, and the CI job
`demo-smoke` (`scripts/smoke_demo.py`) starts the stack, checks it through the APIs and removes it.

## Consequences

- Good: the demo, its smoke test and the screenshots use the files that users install, byte for
  byte, and the `instance` labels show loopback addresses only.
- Good: nothing is published beyond `127.0.0.1` of the Docker host. Grafana's usage reports,
  update checks, news feed and plugin preinstalls are switched off, and the version list job,
  which would fetch the platform's list from the internet, is left out.
- Bad: the other containers live in the Prometheus container's namespace. When only that
  container is recreated (`docker compose up -d --force-recreate prometheus`), they are cut off
  until `docker compose up -d` recreates them too (tried on 2026-10-22). A second copy of the
  stack needs other host ports (`GSO_DEMO_*_PORT`).
- Bad: the image versions are bumped by hand together with the binary pins; Dependabot is set to
  propose only new digests under the same tag.
