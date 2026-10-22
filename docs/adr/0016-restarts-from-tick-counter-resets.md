# 0016. Restarts from tick counter resets

- **Status:** accepted
- **Date:** 2026-10-21

## Context

The alert asked for is "0 players 30 minutes after a restart window": players who were online
before a restart and did not come back point to a server that is missing from the server list
or cannot be joined. The pack collects from outside the server process, so there is no restart
event. The status endpoints have no start time. The tick count of `svMain` on `/perf/` is a
counter that starts at 0 with the process. Many servers restart on a schedule, often at night,
when nobody plays.

## Considered options

1. A restart is a reset of `fxserver_tick_time_seconds_count{thread="svMain"}`; fire when there
   was a reset 30 to 60 minutes ago, no player since then for 30 minutes, and players in the 30
   minutes before that.
2. A restart is a gap in `up` of the `/perf/` job.
3. Fire when there are 0 players for 30 minutes at any time.

## Decision

Chosen option 1, because the counter reset marks the process start itself, also when txAdmin
restarts the server within one scrape interval, and it needs no extra data. The condition on the
players before the restart keeps a night restart of an empty server quiet. The alert has no
`for`: the windows in the expression already make it wait 30 minutes. It ends an hour after the
restart or when a player joins, because it reports a restart that players did not come back from,
not an empty server. Option 2 misses quick restarts and fires on scrape problems. Option 3 fires
every quiet night.

## Consequences

- Good: `tests/rules/noplayers.test.yml` covers a busy server that stays empty, the 30 minutes
  counted from the restart, a server that emptied before its restart, players who come back,
  players who leave again, an empty server without a restart and a server that is down after its
  restart.
- Bad: a server that restarts while its players leave anyway (a restart at the end of an event)
  fires once; the runbook says to move the restart or silence the alert for that time. A restart
  is missed if `/perf/` was not scraped around it.
