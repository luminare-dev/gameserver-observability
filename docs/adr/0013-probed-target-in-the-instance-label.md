# 0013. Probed target in the instance label

- **Status:** accepted
- **Date:** 2026-10-21

## Context

The jobs `fxserver_json`, `fxserver_blackbox` and `fxserver_tunnel` scrape json_exporter and
blackbox_exporter, which fetch the real target per scrape. Without a relabel rule, `instance`
would be the exporter's address (`127.0.0.1:7979`) for every target. A fixed alias per job (for
example `game-01-json`) would keep every probed URL and address out of the labels, which matters
because dashboards made from this data get shared. Every series already carries the `server`
label, a short name chosen per game server, and `module`, which says which probe or endpoint made
it.

## Considered options

1. Copy the probed target (`__param_target`) into `instance`, as the blackbox_exporter and
   json_exporter examples do.
2. A fixed alias per job.
3. An alias built from `server` and `module`.

## Decision

Chosen option 1, because when a probe fails, `up == 0` and the probe series then name the URL or
port that failed, without a look into the scrape config. Option 2 hides that, and option 3 only
repeats two labels that every series already has. The shipped targets are loopback addresses and
`example.com`; the address of a real server or admin hostname appears in `instance` only in the
operator's own Prometheus. Shared views must not show it: rules, alerts and dashboards built on
this data group by `server` and `module`, never by `instance`.

## Consequences

- Good: a failing target is named in the series itself.
- Bad: `instance` holds a host address or a hostname. The later dashboard step must keep it out
  of shared views (no `instance` in panels, legends, variables or tables), its lint must fail on
  any query or legend that uses `instance`, and the share copy must not contain it.
