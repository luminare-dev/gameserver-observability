# 0023. No Alertmanager in 0.1

- **Status:** accepted
- **Date:** 2026-10-22

## Context

The rules in `rules/` decide when something is wrong; telling a person (mail, chat, a pager) is
Alertmanager's job. Most Prometheus setups already run an Alertmanager with routes and receivers
of their own, and every receiver needs an address, a webhook URL or a token that differs per user
and is a secret. The pack also has a demo stack, where it is tempting to show a notification.

## Considered options

1. Ship rules only. Every alert carries the labels `server` and `severity` and a `runbook_url`, so
   an existing Alertmanager can route it; the alerts are visible in Prometheus (Status → Alerts,
   the `ALERTS` series) and on the dashboard.
2. Ship an Alertmanager configuration and add Alertmanager to the demo stack, with a receiver
   that sends nowhere or to a local webhook.
3. Grafana-managed alerts instead of Prometheus rules.

## Decision

Chosen option 1 for 0.1, because routing depends on the user's own receivers, which this
repository cannot know and must not hold. A shipped configuration would be either a receiver
that does nothing or a placeholder for a secret, and adding Alertmanager to the demo stack would
show Alertmanager, not the pack. [Configuration](../configuration.md#send-the-alerts-to-alertmanager)
shows the two settings that connect the rules to an Alertmanager and a route by `severity`,
both checked with promtool and amtool. Option 3 ties the alerts to Grafana: promtool cannot test
Grafana-managed rules, and the rules could no longer be evaluated by Prometheus alone.

## Consequences

- Good: the rule files drop into any Prometheus with or without Alertmanager, and no receiver
  settings or secrets are in the repository.
- Good: every alert is tested with promtool in CI (a firing and a quiet case).
- Bad: nobody is notified until the alerts are routed in your Alertmanager; the demo stack shows
  pending and firing alerts on the dashboard and in Prometheus, but sends no notification.
