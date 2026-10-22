# 0017. Build age and the Recommended build

- **Status:** accepted
- **Date:** 2026-10-21

## Context

The alerts asked for are "build older than 8 weeks" and "behind the Recommended build". The game
server does not say when its build was made or released: `info.json` has the build number in the
version string, which a label cannot compare with a number. The `fxserver` role of the
`luminare.gameserver` collection writes two textfile metrics for node_exporter: the build number
that runs, and the time its `current` link was switched. The platform publishes the current
Recommended build in a public version list, which json_exporter can read. Its support policy
(a Recommended build is supported until 6 weeks after the next one, builds older than 3 months
cannot be joined from the server list) makes both alerts worth having.

## Considered options

1. Age from the switch time (`fxserver_artifact_installed_timestamp_seconds`), and the Recommended
   build from the version list through an optional json_exporter job, compared with
   `fxserver_artifact_build`.
2. The build date of each build, looked up in the version list.
3. A list of build numbers and dates kept in this repository.

## Decision

Chosen option 1, because both inputs exist today and are numbers PromQL can compare. The switch
time is a lower bound of the build's age: a build that was already old when it was switched on
fires later. "Behind" means older than every Recommended build of the last 14 days
(`min_over_time` of the version list), so a new Recommended build gets two weeks before the alert
fires, and an outage of the version list does not end the alert. Option 2 is not possible: the
list has support dates but no release dates. Option 3 would go stale between releases of this
pack.

## Consequences

- Good: both alerts are tested over 17 simulated days (`tests/rules/build.test.yml`), including
  an update, a newer build than the Recommended one and an outage of the version list. The version
  list module was checked against the real list on 2026-10-21.
- Bad: both alerts need the textfile metrics, so they work out of the box only with the
  collection (or a script that writes the same file). The version list job adds an outbound
  request from the Prometheus host, every 4 minutes; no alert watches that job, so a broken list
  stays unnoticed until someone looks at `up{job="fxserver_versions"}`. `FXServerArtifactOld` also
  fires when the build that runs is still the current Recommended build; the runbook says to
  silence it then.
