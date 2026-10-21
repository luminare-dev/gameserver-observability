# Probe log

What a running game server with a license key serves on the endpoints this pack reads, checked by
hand. Everything the pack collects was read in the FXServer source code of build 35245 and is
tested against the fake server ([metrics reference](metrics.md#how-far-each-metric-is-verified));
this page holds the commands for the check on a real server and the tables for its results.

**Status: not run yet.** The check needs a game server with a license key, and none has been used
for this project yet (README, Limitations). The result tables stay empty until then. Where a
result differs from what the source code says, the pull request that fills this page also changes
the configs, rules, fake server and docs that rely on it.

## Before you start

- Use a test server that no player joins. One step turns the `/perf/` credentials off for a
  minute, and a request that the request paranoia refuses makes the server block the address it
  came from.
- Run the steps of [`/perf/`](#perf-with-and-without-credentials) and of
  [fields and the version string](#fields-and-the-version-string) on the Prometheus host: it has
  the password file, and its address is the one the pack scrapes from. Run the steps of
  [request paranoia and rate limits](#request-paranoia-and-rate-limits) from a second machine
  that reaches the game port, so that a block or a rate limit does not hit the scrapes. Run the
  [txAdmin step](#txadmin-hoststatus) on the game server itself.
- Write down status codes, header names, metric names, label names, field names, types and
  counts. Never write a password, a token, a license key, an address, a host name, the server's
  project name or anything about a player into this page.
- Do not request `players.json`: the pack never reads it, and the probe does not need it.

## Setup

| | Result |
|---|---|
| Date | not run yet |
| Build (`server` field of `info.json`) | not run yet |
| txAdmin version | not run yet |
| `sv_requestParanoia` before the probe | not run yet |
| OneSync (`onesync`) | not run yet |

On each machine, work in a folder only you can read, and set `SERVER` to the address and game
port that Prometheus scrapes (here an example from the documentation range):

```bash
mkdir -m 0700 probe && cd probe
SERVER=192.0.2.10:30120
```

On the Prometheus host, write the `/perf/` credentials into a curl config file only you can read,
so that the password never appears on a command line. `prometheus` is the user of the shipped
scrape job; use the value of your `sv_prometheusBasicAuthUser`. A password with `"` or `\` needs a
backslash before each of them in this file.

```bash
( umask 077 && printf 'user = "prometheus:%s"\n' "$(sudo cat /etc/prometheus/secrets/fxserver_perf)" > perf.curlrc )
```

## `/perf/` with and without credentials

On the Prometheus host:

```bash
# 1. Without credentials
curl -sS -D - "http://$SERVER/perf/"; echo
# 2. With a wrong password: type anything but the password when curl asks for one
curl -sS -o /dev/null -w '%{http_code}\n' --user prometheus "http://$SERVER/perf/"
# 3. With the credentials: status, content type, metric names, threads, bucket bounds, label names
curl -sS -K perf.curlrc -D perf.headers -o perf.txt -w '%{http_code}\n' "http://$SERVER/perf/"
grep -i '^content-type' perf.headers
grep -v '^#' perf.txt | sed 's/[{ ].*//' | sort | uniq -c
grep '^tickTime_count' perf.txt | grep -o 'name="[^"]*"'
grep '^tickTime_bucket' perf.txt | grep 'name="svMain"' | grep -o 'le="[^"]*"'
grep -v '^#' perf.txt | grep -o '{[^}]*}' | grep -o '[a-zA-Z_][a-zA-Z0-9_]*=' | sort -u
# 4. Ten requests with the credentials, at once
for i in $(seq 10); do curl -sS -K perf.curlrc -o /dev/null -w '%{http_code} ' "http://$SERVER/perf/"; done; echo
```

Step 5 opens `/perf/` for about a minute. In the server console, empty both credentials:

```text
set sv_prometheusBasicAuthUser ""
set sv_prometheusBasicAuthPassword ""
```

Then, on the Prometheus host, send ten requests without credentials (`000` means that the server
closed the connection):

```bash
for i in $(seq 10); do curl -sS -o /dev/null -w '%{http_code} ' "http://$SERVER/perf/"; done; echo
```

Look at `probe_success{module="http_401_expected"}` and the alert `FXServerPerfEndpointExposed`
in Prometheus, set both credentials again in the console, and repeat step 1.

| Step | Expected by the source of build 35245 | Result |
|---|---|---|
| 1. Without credentials | `401`, body `Unauthorized.` | not run yet |
| 2. Wrong password | `401` | not run yet |
| 3. Status and content type | `200`, `text/plain` | not run yet |
| 3. Metric names | `tickTime_bucket`, `tickTime_sum`, `tickTime_count`; whether others follow is not known (the scrape job drops them) | not run yet |
| 3. Threads (`name`) | `svMain`, `svNetwork`, `svSync` | not run yet |
| 3. Bucket bounds (`le`) | the 14 bounds from 0.001 to 0.25 seconds of the [metrics reference](metrics.md#job-fxserver_perf-perf-on-the-game-port), and `+Inf` | not run yet |
| 3. Label names | `name`, `le` | not run yet |
| 4. Ten requests with the credentials | ten times `200`: requests with the credentials have no rate limit | not run yet |
| 5. The emptied credentials apply without a restart | yes: the server builds its check again when either variable changes | not run yet |
| 5. Ten requests without credentials | `200` for about the first five, then `429` with the body `Rate limit exceeded.` (2 requests per second, burst 5, per address) | not run yet |
| 5. Probe and alert | `probe_success` 0 for `http_401_expected`, `FXServerPerfEndpointExposed` pending | not run yet |
| 1 again, with the credentials set back | `401` | not run yet |

## Fields and the version string

On the Prometheus host, the requests json_exporter makes, without extra headers. The scripts
print field names, types and counts, never the host name or the project name:

```bash
curl -sS "http://$SERVER/info.json" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print("server:", d.get("server"))
print("fields:", sorted(d))
print("vars.onesync_enabled:", repr(d.get("vars", {}).get("onesync_enabled")))
print("resources:", len(d.get("resources", [])))'
curl -sS "http://$SERVER/dynamic.json" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print("fields:", sorted(d))
print("clients:", repr(d.get("clients")), "sv_maxclients:", repr(d.get("sv_maxclients")))'
```

Then, in Prometheus, read the labels `version` and `build` of `fxserver_info` for this server.

| Check | Expected by the source of build 35245 | Result |
|---|---|---|
| `server` | `FXServer-master v1.0.0.35245 linux`, the text in the build's server library | not run yet |
| `build` label of `fxserver_info` | `35245` | not run yet |
| Fields of `info.json` | `enforceSteamAuth`, `enhancedHostSupport`, `requestSteamTicket`, `resources`, `server`, `vars`, `version`, and `icon` with a server icon | not run yet |
| `vars.onesync_enabled` | the string `"true"` or `"false"` | not run yet |
| Fields of `dynamic.json` | `clients`, `gametype`, `hostname`, `iv`, `mapname`, `sv_maxclients` | not run yet |
| `clients`, `sv_maxclients` | a number; a string such as `"32"` | not run yet |

## Request paranoia and rate limits

From the second machine. For each level, set it in the server console (`sv_requestParanoia 0`,
then 1, 2 and 3) and run a, then b with the header the table names for that level; after a
request that the server refused, run c before the next level:

```bash
# a. Plain requests, as json_exporter sends them
for path in info.json dynamic.json; do curl -sS -o /dev/null -w "$path %{http_code}\n" "http://$SERVER/$path"; done
# b. One request with an extra header: 'Via: 1.1 probe' or 'Upgrade-Insecure-Requests: 1'
HEADER='Via: 1.1 probe'
curl -sS -o reply.txt -w '%{http_code}\n' -H "$HEADER" "http://$SERVER/info.json"; head -c 20 reply.txt; echo
# c. How long the address stays blocked: a plain request every 10 seconds, for at most 15 minutes
start=$(date +%s)
for i in $(seq 90); do
  code=$(curl -sS -m 5 -o /dev/null -w '%{http_code}' "http://$SERVER/dynamic.json" 2>/dev/null)
  [ "$code" = 200 ] && break
  sleep 10
done
echo "answer $code after $(( $(date +%s) - start )) s"
```

If the address is still blocked when c ends, write that down and use another machine for the next
level.

| Level | Request | Expected by the source of build 35245 | Result |
|---|---|---|---|
| 0 | a | `200` for both | not run yet |
| 0 | b with `Via` | `200` | not run yet |
| 0 | b with `Upgrade-Insecure-Requests` | `200` | not run yet |
| 1 | a | `200` for both | not run yet |
| 1 | b with `Upgrade-Insecure-Requests` | `200` | not run yet |
| 1 | b with `Via` | `403`, body `Nope.`, the address is blocked | not run yet |
| 2 | a | `200` for both | not run yet |
| 2 | b with `Upgrade-Insecure-Requests` | `403`, body `Nope.`, the address is blocked | not run yet |
| 3 | a | `200` for both | not run yet |
| 3 | b with `Via` | `403`, body `Nope.`, then the connection is closed; the address is blocked | not run yet |
| 1 to 3 | c: how long the block lasts | not known | not run yet |

Then, at the level the server runs with, the rate limits (`000` means that the server closed the
connection):

```bash
for path in info.json dynamic.json; do
  printf '%s: ' "$path"
  for i in $(seq 15); do curl -sS -o /dev/null -w '%{http_code} ' "http://$SERVER/$path" 2>/dev/null; done
  echo
done
```

| Endpoint | Expected by the source of build 35245 | Result |
|---|---|---|
| `info.json`, 15 requests at once | `200` for about the first ten, then `429` with the body `Rate limit exceeded.` (4 requests per second, burst 10, per address), or `000` while the limit closes connections | not run yet |
| `dynamic.json`, 15 requests at once | 15 times `200`: no rate limit | not run yet |

## txAdmin `/host/status`

On the game server. The `txadmin` role of the `luminare.gameserver` collection writes the token to
`/etc/fxserver/txadmin.env` as `TXHOST_API_TOKEN`; this writes it into a header file only you can
read, so that it never appears on a command line or in a URL:

```bash
( umask 077 && sudo sed -n 's/^TXHOST_API_TOKEN=/x-txadmin-envtoken: /p' /etc/fxserver/txadmin.env > txadmin.header )
# Without the token
curl -sS -w '\n%{http_code}\n' http://127.0.0.1:40120/host/status
# With the token in the header
curl -sS -H @txadmin.header -o host-status.json -w '%{http_code}\n' http://127.0.0.1:40120/host/status
# Field paths and types only, no values
python3 - host-status.json <<'EOF'
import json, sys

def walk(value, path):
    if isinstance(value, dict):
        for key, item in value.items():
            walk(item, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        print(f"{path}: list of {len(value)}")
        if value:
            walk(value[0], f"{path}[0]")
    else:
        print(f"{path}: {type(value).__name__}")

walk(json.load(open(sys.argv[1], encoding="utf-8")), "")
EOF
```

Read the field paths before you copy them here: a path made from a name (of a player, a resource
or a host) does not belong on this page.

| Check | Expected by the source of txAdmin 8.1.1 | Result |
|---|---|---|
| Without the token | `200`, a JSON object with `"error": "token missing"` | not run yet |
| With the token | `200`, a JSON object | not run yet |
| Field paths and types | not known: this is what the probe is for | not run yet |

## Clean up

Set `sv_requestParanoia` back to the level from [Setup](#setup), check that both `/perf/`
credentials are set (step 1 answers `401`), and on each machine remove the folder with the
password and token files:

```bash
cd .. && rm -rf probe
```

## After the probe

- Fill in the tables and [Setup](#setup), and change **Status** to the date of the run.
- Where a result differs from the expected value, change the scrape job, module or probe, the
  fake server (`demo/fake-fxserver/fake_fxserver.py`) and its tests, and the docs in the same pull
  request.
- Update the **Verified** column of the [metrics reference](metrics.md) for the rows the probe
  checked, and the README's Limitations.
- A json_exporter module for `/host/status` is a change of its own, once its fields are known
  ([not collected](metrics.md#not-collected)).
