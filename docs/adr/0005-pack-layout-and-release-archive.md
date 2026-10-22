# 0005. Plain files in a fixed layout, released as the source archive

- **Status:** accepted
- **Date:** 2026-10-21

## Context

The pack is configuration, not a program: Prometheus scrape configs, json_exporter and
blackbox_exporter modules, recording and alerting rules with their tests, dashboards with their
provisioning files, and a demo stack. Users copy these files into their own monitoring setup or
vendor them into their own automation, so the release has to be easy to unpack and inspect, and
the files have to be at stable paths that the docs, the tests and such automation can name.

## Considered options

1. Plain files in fixed top-level folders; the release is the template's `git archive` of the tag.
2. A generated bundle (for example one archive per component, or a mixin that renders the files).
3. Container images with the configs baked in.

## Decision

Chosen option: "plain files in fixed folders, released as the source archive", because every file
can be read, diffed and reviewed as it is, and the template's release workflow already builds,
checksums and attests a `git archive` of the tag. The folders are:

| Folder | Content |
|---|---|
| `prometheus/` | scrape config snippets and the demo stack's full Prometheus config |
| `json_exporter/` | json_exporter modules for the server's JSON endpoints |
| `blackbox/` | blackbox_exporter probe modules |
| `rules/` | recording and alerting rules |
| `tests/rules/` | promtool unit tests for the rules |
| `grafana/` | dashboards and provisioning files |
| `demo/` | the demo stack with the fake game server |
| `docs/` | reference, runbook and decision records |

The release asset is `gameserver-observability-X.Y.Z.tar.gz` (input `archive-name` in
`release.yml`) with `SHA256SUMS`. No `export-ignore` attribute is used, so the archive holds every
tracked file; `tests/test_pack_repo.py` fails if an attribute would drop a file or one of these
folders.

## Consequences

- Good: one release asset, verifiable with `sha256sum -c` and (once the repository is public)
  `gh attestation verify`; no build step to trust.
- Good: automation (for example an Ansible role) can vendor the files from a tag at known paths.
- Bad: the archive also contains CI files, scripts and tests that a user does not need; they are
  small and documented in the README.
