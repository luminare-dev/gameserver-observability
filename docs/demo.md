# Demo stack

`demo/docker-compose.yml` runs the pack against the bundled simulated server
(`demo/fake-fxserver/fake_fxserver.py`): the scrape jobs, the exporter modules, the rules and the
dashboard, with Prometheus, json_exporter, blackbox_exporter and Grafana in containers on your
machine. Everything it shows is **synthetic data from the bundled simulated server**: there is no
game server and there are no players. Use it to look at the dashboard and the alerts before you
install anything, or to try a change of the pack.

![Dashboard "Game server overview" during a tick-time spike, synthetic data from the bundled simulated server](media/dashboard.png)

*Synthetic data from the bundled simulated server: the dashboard of the demo stack while the
simulated server's main thread ticks slowly and `FXServerTickTimeHigh` fires.*

## Requirements

Docker Engine with the Compose plugin, and about 2.6 GB of disk for the five images.

## Start and stop

```bash
git clone https://github.com/luminare-dev/gameserver-observability.git && cd gameserver-observability
docker compose -f demo/docker-compose.yml up -d
```

Then open <http://127.0.0.1:3000/>: Grafana shows "Game server overview" as its home page, without
a sign-in. Prometheus is at <http://127.0.0.1:9090/> (Status → Targets, Alerts). The rules need
about a minute for the first recorded values, so the tick-time panels fill after that.

```bash
docker compose -f demo/docker-compose.yml down -v   # removes the containers, the network and the data
```

If a port is taken, choose others for the host side; the stack itself does not change:

```bash
GSO_DEMO_GRAFANA_PORT=13000 GSO_DEMO_PROMETHEUS_PORT=19090 GSO_DEMO_GAME_PORT=40130 \
  docker compose -f demo/docker-compose.yml up -d
```

## What runs

| Service | Image (pinned by digest) | What it does | Listens on |
|---|---|---|---|
| `prometheus` | `prom/prometheus:v3.15.0` | The pack's scrape jobs (`prometheus/scrape/fxserver.yml`) and rules (`rules/*.yml`); `prometheus/prometheus.demo.yml` is the main config of the [installation guide](install.md#install) | 9090, published on `127.0.0.1` |
| `fxserver` | `python:3.13-slim` | The simulated server: 3 of 32 players, `/perf/` behind basic auth, a load knob | 30120, published on `127.0.0.1` |
| `json-exporter` | `quay.io/prometheuscommunity/json-exporter:v0.8.0` | The modules of `json_exporter/config.yml` | `127.0.0.1:7979`, inside the stack only |
| `blackbox-exporter` | `prom/blackbox-exporter:v0.29.0` | The modules of `blackbox/blackbox.yml` | `127.0.0.1:9115`, inside the stack only |
| `grafana` | `grafana/grafana:13.2.4` | The provisioning files and the dashboard of `grafana/` | 3000, published on `127.0.0.1` |

The services share one network namespace, so the pack's files are mounted from the repository as
they are, at the paths of the installation guide: inside the stack, `127.0.0.1` means the same as
on a single host. The simulated
server and Prometheus share the demo's `/perf/` password `synthetic-demo-only`, which guards
synthetic data only; never use it for a real server.

Grafana has no account at all: every visitor is a viewer, nobody can sign in, and nothing can be
changed in it. Its usage reports, update checks, news feed and plugin preinstalls are switched
off, and the stack leaves out the optional version list job, which would fetch the platform's
version list from the internet.

Some panels stay empty, because the demo has nothing that feeds them: the rows Host and MariaDB
and the panels of the admin hostname and the tunnel need node_exporter, mysqld_exporter,
cloudflared and an admin hostname, and Build age needs the textfile metrics of the
`luminare.gameserver` collection's `fxserver` role ([metrics reference](metrics.md)).

## Simulate a load spike

The simulated server has a load knob on `/fake/control` (only on `127.0.0.1`, see
`demo/fake-fxserver/fake_fxserver.py` for every field):

```bash
curl -X POST -d '{"clients": 20}' http://127.0.0.1:30120/fake/control                         # 20 players (0 to 32)
curl -X POST -d '{"main_tick_ms": 90, "for_seconds": 600}' http://127.0.0.1:30120/fake/control # slow ticks for 10 minutes
curl -X POST -d '{"restart": true}' http://127.0.0.1:30120/fake/control                       # tick counters from zero
```

With slow ticks, the `svMain` p95 and p99 rise above 100 ms within a minute, ticks per second
drop from about 20 to about 11, most ticks land in the heatmap's buckets from 50 to 150 ms, and
`FXServerTickTimeHigh` becomes pending; it fires 5 minutes later and is gone about 80 seconds
after the spike ends. `docker compose -f demo/docker-compose.yml stop fxserver` stops the
simulated server: `FXServerDown` becomes pending within a minute and fires 2 minutes later;
`docker compose -f demo/docker-compose.yml start fxserver` brings it back with new counters (and 3
players again), and the Restarts panel counts the restart.

## Smoke test

```bash
python3 scripts/smoke_demo.py
```

It starts the stack under its own project name with free ports, checks targets, probes, rules
and the dashboard through the APIs of Prometheus and Grafana, and removes the stack again, also
when a check fails. CI runs it in the `demo-smoke` job.
