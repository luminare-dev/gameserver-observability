# 0018. Dashboard with a shareable copy

- **Status:** accepted
- **Date:** 2026-10-21

## Context

The dashboard has to work in two ways. Provisioned from files on the operator's own Grafana, it
should let them pick the data source and the game servers. Imported somewhere else, for example
from a dashboard catalogue later, it must not carry anything of the place it came from: no data
source uid, no selected server name, no host address (ADR 0013). A dashboard with variables keeps
the values it was saved with, and a stored data source uid breaks the import on every other
Grafana. The rows the plan asks for are tick time, players, the game server's resources, host,
MariaDB and tunnel; the resource list of the game server is not collected (ADR 0009, one series
per resource would break the cardinality budget).

## Considered options

1. One dashboard with a data source variable and a `server` variable, plus a copy without
   variables that a script makes from it and the dashboard check compares on every pull request.
2. One dashboard with variables only, shared with Grafana's own export.
3. Two dashboards edited by hand.

## Decision

Chosen option 1, because the copy then never drifts from the dashboard and needs no Grafana to
be made. `grafana/dashboards/game-server-overview.json` has the variable `datasource` (no stored
selection, so Grafana picks the viewer's default Prometheus data source) and `server` (several
servers, stored as All). `python3 scripts/lint_dashboards.py --fix` writes
`grafana/dashboards/shareable/game-server-overview.json` from it: every panel names the import
input `${DS_PROMETHEUS}`, the matchers on `$server` are dropped so that the copy shows every
server, and it gets its own uid (`-shared`), so that importing it next to the provisioned one
never replaces it. Option 2 keeps the variables and their stored values in the export, and its
result depends on the Grafana that exports it. Option 3 would drift. The dashboard has no
resources row; its host row shows the machine's CPU, memory, disk and network instead. The
optional data source file names its data source "Game server metrics" (uid `gso-prometheus`),
not "Prometheus" and not the default, so that it never replaces or takes over a data source the
operator already has.

## Consequences

- Good: on 2026-10-21 Grafana 13.2.4 provisioned the dashboard from these files alone, and every
  query of both files returned data from the fake server and the exporters; the copy imported with
  one data source input and no variable left.
- Bad: the copy cannot filter one game server. A variable may only be used as a label matcher of
  the form `label=~"$server"`; the generator refuses anything else. After every change of the
  dashboard the copy has to be written again (the check fails until it is).
