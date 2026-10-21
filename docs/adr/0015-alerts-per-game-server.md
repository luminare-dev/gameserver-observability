# 0015. Alerts per game server

- **Status:** accepted
- **Date:** 2026-10-21

## Context

The alerts go to people who run one or a few game servers. Every series of the pack carries
`server`, a short name the operator sets per game server. `instance` can hold a host address or
an admin hostname ([ADR 0013](0013-probed-target-in-the-instance-label.md)), and alert texts end
up in chat channels and tickets. An alert also needs a severity that routing can use and a link
to what to do.

## Considered options

1. Every alert aggregates `by (server)` (plus the one label that says where, such as `thread`,
   `job` or `mountpoint`), carries only the fixed label `severity` (`critical` or `warning`), and
   has the annotations `summary`, `description` and `runbook_url`.
2. Keep all labels of the source series, as many rule sets do.
3. Add a team or service label for routing.

## Decision

Chosen option 1, because an alert then names the game server in words the operator chose, never
an address, and two targets of one server (for example both probes) report as one alert.
`critical` means act now: the game server or its database is down for players, or the admin
interface is open to anyone. `warning` means act within the day. Each `runbook_url` points to the
alert's own section of `docs/runbook.md` on the main branch, with the same five rows everywhere
(meaning, impact, diagnosis, mitigation, fix). Routing labels are left to the operator's
Alertmanager, because the pack cannot know its teams.

## Consequences

- Good: `tests/test_rules.py` enforces the shape: the labels and annotations, no `instance` and no
  per-player label in any grouping or text, a runbook section for every alert and none without
  one, and a firing and a quiet promtool case for every alert in a test that loads its file.
- Bad: jobs the pack does not ship (node_exporter, mysqld_exporter) must carry the `server` label
  too, or their alerts fire without naming a server; the configuration page shows how. Links to the
  runbook on `main` show the newest text, which can differ from an older release's rules.
