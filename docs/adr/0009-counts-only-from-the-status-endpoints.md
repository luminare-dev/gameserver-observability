# 0009. Counts only, from the status endpoints

- **Status:** accepted
- **Date:** 2026-10-21

## Context

The pack needs the player count and a few facts about the server (slots, version, OneSync). The
game server serves them as JSON on the game port: `dynamic.json` has the number of connected
clients and the slots, `info.json` the version string and the server variables, and
`players.json` one entry per player, which holds names and identifiers when the request carries
the players token. Whatever reaches Prometheus is kept for weeks and shown on dashboards that
people share, so data about single players must never get there, also not by a mistake in a
later change.

## Considered options

1. Read the count from `dynamic.json` `clients` with json_exporter; never request `players.json`.
2. Count the entries of `players.json` (json_exporter cannot count array entries, so this needs a
   small exporter of its own).
3. A resource inside the game server that exports metrics itself.

## Decision

Chosen option 1, because `dynamic.json` already has the count and needs no per-player data at
all, and json_exporter is a maintained exporter that runs outside the server process. Option 2
would fetch player data only to throw it away, and option 3 would run code inside the server
that it is supposed to watch. The rule is enforced, not only documented: `scripts/check_pack.py`
fails when any scrape config or exporter module names `players.json` or adds a label such as
`name`, `player`, `identifier`, `license`, `ip`, `endpoint`, `ping` or `id`, and
`scripts/smoke_exporters.py` checks in CI that the fake server never receives a `players.json`
request and that no such label arrives in Prometheus. The modules read four fields and nothing
else ([metrics reference](../metrics.md)).

## Consequences

- Good: no player data can reach Prometheus through this pack, and a change that would add some
  fails CI.
- Good: one series for the count instead of one per player keeps the
  [cardinality budget](../cardinality.md) small.
- Bad: if `dynamic.json` is ever unavailable while `players.json` works, there is no player count;
  the `up` series of the job shows it.
