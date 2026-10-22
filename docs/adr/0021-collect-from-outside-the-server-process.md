# 0021. Collect from outside the server process

- **Status:** accepted
- **Date:** 2026-10-22

## Context

Metrics about a game server can come from two places. A resource (a script package) inside the
server can gather what the scripting runtime sees and serve it on an HTTP path of the game port.
Or a monitoring host can read what the server itself already serves on the game port: the
tick-time histogram on `/perf/`, the counts and slots in `dynamic.json`, the version in
`info.json`. The alerts this pack is for (slow ticks, a server that is down, no players after a
restart, an old build, disk and database) need the tick time, the player count, the build and
whether the port answers. Whatever watches the server should not depend on the thing it watches:
a resource runs in the same process, its work counts towards the tick time it reports, and it is
gone when the process is.

## Considered options

1. Outside the process: Prometheus scrapes `/perf/` itself, json_exporter and blackbox_exporter on
   the monitoring host fetch the JSON endpoints and probe the port.
2. A resource inside the game server that serves its own metrics endpoint.
3. Both: the outside scrape, plus an optional resource for what only the inside can see.

## Decision

Chosen option 1, because the server already serves everything the alerts need: `/perf/` is
FXServer's own histogram of every thread's tick time, and `dynamic.json` has the player count
without any player data ([ADR 0009](0009-counts-only-from-the-status-endpoints.md)). Nothing of
this pack runs in the game server; it only needs the two `/perf/` credentials set
(`sv_prometheusBasicAuthUser`, `sv_prometheusBasicAuthPassword`). The configs read only the game
port, so they do not depend on whether the server is started directly or by txAdmin, or on its
framework and resources. A server
that is down or does not answer on its port is reported by the probes, which need nothing from
the server's scripting runtime (`FXServerDown`). Option 2 sees more, but it puts code into the
process it watches and has to be installed and updated with the server's resources. Option 3
would add a second component to build, test and secure, and nothing the 0.1 alerts need comes
from it.

## Consequences

- Good: nothing to install into, or to keep compatible with, the game server; operators review
  configuration files only.
- Good: the probes report a stopped or hanging port independently of the server's own work, and
  the tick times are measured by the server, not by a script that competes with the scripts it
  measures.
- Bad: only what the server publishes can be collected: no entity counts, no per-resource
  timings, no connection outcomes, no events of your own resources. Projects that run inside the
  server can show those ("Why not a similar project?" in the README).
- Bad: the pack depends on the endpoints of the server version: their fields, the `/perf/` access
  rule, `sv_requestParanoia` and the rate limits. They were read in the server's source code and
  are tested against a fake server, not yet against a running one (README, Limitations).
