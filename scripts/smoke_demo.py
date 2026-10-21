#!/usr/bin/env python3
"""Smoke test of the demo stack (demo/docker-compose.yml): start it, check it, remove it.

Starts the stack with `docker compose up` under its own project name, with Grafana, Prometheus
and the simulated game server published on free ports of 127.0.0.1, and checks through their
HTTP APIs that:

- every target of prometheus/scrape/fxserver.yml is up and every blackbox probe succeeds, so
  /perf/ refuses requests without the password and the scrape with the password works;
- Prometheus has the simulated server's player count, and players.json was never requested;
- every rule file in rules/ is loaded, every rule is evaluated without an error, and no alert is
  pending or firing while the simulated server is healthy;
- Grafana provisioned the dashboard of grafana/dashboards/ from the repository's files alone, in
  the folder of the provisioning file and read-only, finds it by its title, and answers a query
  through the data source of the provisioning file with the same player count;
- Grafana has no account: a sign-in as admin is refused.

Then `docker compose down --volumes` removes the containers, the network and the volumes, also
when a check fails (after printing the last log lines of every service). The CI job "demo-smoke"
runs it on a GitHub ubuntu-24.04 runner; locally it needs Docker with the Compose plugin:

  python3 scripts/smoke_demo.py [--project-name NAME] [--timeout 180]

The project name must not belong to a running stack: the script refuses to start then, so that
it never removes containers it did not create. Exit code 0 when every check passes, 1 when one
fails, 2 when the run could not start. Python 3.10 or newer, standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:  # also when run with python3 -I
    sys.path.insert(0, str(SCRIPTS))

from check_pack import load_yaml  # noqa: E402

COMPOSE_FILE = ROOT / "demo" / "docker-compose.yml"
SCRAPE_CONFIG = ROOT / "prometheus" / "scrape" / "fxserver.yml"
RULES_DIR = ROOT / "rules"
DASHBOARD = ROOT / "grafana" / "dashboards" / "game-server-overview.json"
DASHBOARD_PROVIDER = ROOT / "grafana" / "provisioning" / "dashboards" / "gameserver-observability.yml"
DATASOURCE = ROOT / "grafana" / "provisioning" / "datasources" / "gameserver-observability.yml"
DEFAULT_PROJECT = "gameserver-observability-demo-smoke"
# The host ports the compose file publishes, set through these variables (docs/demo.md).
PORT_VARIABLES = ("GSO_DEMO_GRAFANA_PORT", "GSO_DEMO_PROMETHEUS_PORT", "GSO_DEMO_GAME_PORT")


class Failure(Exception):
    pass


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def http(url: str, data: bytes | None = None, timeout: float = 10) -> tuple[int, object]:
    """Status and parsed JSON body (None when the body is not JSON) of a request to a local URL."""
    headers = {"Content-Type": "application/json"} if data is not None else {}
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310 (127.0.0.1 only)
            status, body = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, body = exc.code, exc.read()
    try:
        return status, json.loads(body)
    except ValueError:
        return status, None


def expected_targets() -> dict[str, int]:
    """Targets per job of the pack's scrape config, which the demo mounts unchanged."""
    jobs = load_yaml(SCRAPE_CONFIG.read_text(encoding="utf-8"))["scrape_configs"]
    return {job["job_name"]: sum(len(group["targets"]) for group in job["static_configs"]) for job in jobs}


def probe_modules() -> set[str]:
    jobs = load_yaml(SCRAPE_CONFIG.read_text(encoding="utf-8"))["scrape_configs"]
    return {group["labels"]["module"] for job in jobs if job["job_name"] == "fxserver_blackbox"
            for group in job["static_configs"]}


def rule_files() -> set[str]:
    return {p.name for p in RULES_DIR.glob("*.yml")}


def grafana_expectations() -> dict[str, object]:
    """Title, uid and panel count of the dashboard, its folder and the data source uid."""
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    provider = load_yaml(DASHBOARD_PROVIDER.read_text(encoding="utf-8"))["providers"][0]
    datasource = load_yaml(DATASOURCE.read_text(encoding="utf-8"))["datasources"][0]
    return {"title": dashboard["title"], "uid": dashboard["uid"], "panels": len(dashboard["panels"]),
            "folder": provider["folder"], "datasource": datasource["uid"]}


class Stack:
    def __init__(self, project: str, timeout: float):
        self.project = project
        self.timeout = timeout
        self.ports = {name: free_port() for name in PORT_VARIABLES}
        self.env = {**os.environ, **{name: str(port) for name, port in self.ports.items()}}
        self.grafana = f"http://127.0.0.1:{self.ports['GSO_DEMO_GRAFANA_PORT']}"
        self.prometheus = f"http://127.0.0.1:{self.ports['GSO_DEMO_PROMETHEUS_PORT']}"
        self.game = f"http://127.0.0.1:{self.ports['GSO_DEMO_GAME_PORT']}"
        self.failures: list[str] = []

    def compose(self, *args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
        argv = ["docker", "compose", "--project-name", self.project, "--file", str(COMPOSE_FILE), *args]
        result = subprocess.run(argv, env=self.env, text=True, capture_output=capture)
        if check and result.returncode != 0:
            raise Failure(f"{' '.join(argv[2:])} failed with exit code {result.returncode}"
                          + (f": {result.stderr.strip()}" if capture else ""))
        return result

    def check(self, ok: bool, message: str) -> None:
        print(f"{'ok  ' if ok else 'FAIL'} {message}")
        if not ok:
            self.failures.append(message)

    def wait_until(self, what: str, probe):
        """Call probe() every 2 seconds until it returns something true; return that value.

        Errors count as "not yet" (a service that is still starting refuses connections or
        answers 503); the last one is reported when the time is up.
        """
        deadline = time.monotonic() + self.timeout
        last_error = ""
        while time.monotonic() < deadline:
            try:
                result = probe()
                if result:
                    return result
            except (Failure, OSError, KeyError, ValueError, TypeError, AttributeError) as exc:
                last_error = f" (last error: {exc})"
            time.sleep(2)
        raise Failure(f"{what}: not reached within {self.timeout:g} seconds{last_error}")

    def prom(self, path: str, **params: str) -> object:
        url = f"{self.prometheus}/api/v1/{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        status, doc = http(url)
        if status != 200 or not isinstance(doc, dict) or doc.get("status") != "success":
            raise Failure(f"Prometheus API {path}: HTTP {status} {doc}")
        return doc["data"]

    def query(self, expr: str) -> list[tuple[dict, float]]:
        return [(r["metric"], float(r["value"][1])) for r in self.prom("query", query=expr)["result"]]


def prometheus_checks(stack: Stack) -> int:
    """The checks in Prometheus; returns the player count it holds."""
    expected = expected_targets()

    def all_up() -> list[dict] | None:
        # A probe can fail once while the simulated server is still starting, so wait until every
        # target's last scrape succeeded.
        targets = stack.prom("targets", state="active")["activeTargets"]
        healthy = len(targets) == sum(expected.values()) and all(t["health"] == "up" for t in targets)
        return targets if healthy else None

    targets = stack.wait_until("every target up", all_up)
    per_job: dict[str, int] = {}
    for t in sorted(targets, key=lambda t: (t["labels"]["job"], t["labels"].get("module", ""))):
        per_job[t["labels"]["job"]] = per_job.get(t["labels"]["job"], 0) + 1
        print(f"     target {t['labels']['job']:<18} {t['labels'].get('module', '-'):<19} {t['health']}")
    stack.check(per_job == expected, f"all {sum(expected.values())} targets of {SCRAPE_CONFIG.relative_to(ROOT)} "
                                     f"are up: {per_job}")

    probes = {m.get("module"): v for m, v in stack.query('probe_success{job="fxserver_blackbox"}')}
    stack.check(probes == {module: 1.0 for module in probe_modules()},
                f"every blackbox probe succeeds, /perf/ without the password included: {probes}")

    status, state = http(f"{stack.game}/fake/state")
    if status != 200 or not isinstance(state, dict):
        raise Failure(f"the simulated server's /fake/state answered HTTP {status}")
    clients = [v for _, v in stack.query("fxserver_clients")]
    stack.check(clients == [float(state["clients"])],
                f"fxserver_clients is the simulated server's {state['clients']} players ({clients})")
    stack.check(state["requests"]["/players.json"] == 0, "players.json was never requested")
    stack.check(state["requests"]["/perf/"] > state["perf_refused"] > 0,
                f"/perf/ was scraped with the password and refused without it "
                f"({state['requests']['/perf/']} requests, {state['perf_refused']} refused)")

    def evaluated() -> list[dict] | None:
        groups = stack.prom("rules")["groups"]
        rules = [r for g in groups for r in g["rules"]]
        return groups if rules and all(r["health"] != "unknown" for r in rules) else None

    groups = stack.wait_until("an evaluation of every rule", evaluated)
    loaded = {Path(g["file"]).name for g in groups}
    stack.check(loaded == rule_files(), f"every rule file in rules/ is loaded: {sorted(loaded)}")
    errors = [f"{r['name']}: {r.get('lastError')}" for g in groups for r in g["rules"] if r["health"] != "ok"]
    rules = sum(len(g["rules"]) for g in groups)
    stack.check(not errors, f"all {rules} rules are evaluated without an error ({'; '.join(errors) or 'all ok'})")
    # A probe that failed during the start can make an alert pending; it must clear again.
    try:
        stack.wait_until("no alert pending or firing", lambda: not stack.prom("alerts")["alerts"])
        active = []
    except Failure:
        active = sorted(f"{a['labels'].get('alertname')} {a['state']}" for a in stack.prom("alerts")["alerts"])
    stack.check(not active, f"no alert is pending or firing while the simulated server is healthy "
                            f"({', '.join(active) or 'none'})")
    return state["clients"]


def grafana_checks(stack: Stack, clients: int) -> None:
    expect = grafana_expectations()
    stack.wait_until("Grafana's health check", lambda: http(f"{stack.grafana}/api/health")[1].get("database") == "ok")

    def provisioned() -> dict | None:
        status, doc = http(f"{stack.grafana}/api/dashboards/uid/{expect['uid']}")
        return doc if status == 200 else None

    doc = stack.wait_until(f"the dashboard {expect['uid']}", provisioned)
    meta, dashboard = doc["meta"], doc["dashboard"]
    stack.check(dashboard.get("title") == expect["title"] and len(dashboard.get("panels", [])) == expect["panels"],
                f"the dashboard \"{expect['title']}\" with its {expect['panels']} panels is provisioned "
                f"from {DASHBOARD.relative_to(ROOT)}")
    stack.check(meta.get("provisioned") is True and meta.get("folderTitle") == expect["folder"]
                and meta.get("canSave") is False and meta.get("canEdit") is False,
                f"it is in the folder \"{expect['folder']}\" and read-only (provisioned "
                f"{meta.get('provisioned')}, folder {meta.get('folderTitle')!r}, can save {meta.get('canSave')})")

    query = urllib.parse.urlencode({"query": expect["title"], "type": "dash-db"})
    status, found = http(f"{stack.grafana}/api/search?{query}")
    uids = [d.get("uid") for d in found] if status == 200 and isinstance(found, list) else []
    stack.check(expect["uid"] in uids, f"Grafana's search finds it by its title ({uids})")

    body = {"queries": [{"refId": "A", "datasource": {"uid": expect["datasource"]}, "expr": "fxserver_clients",
                         "instant": True}], "from": "now-5m", "to": "now"}
    status, result = http(f"{stack.grafana}/api/ds/query", json.dumps(body).encode())
    try:
        values = [v for frame in result["results"]["A"]["frames"] for v in frame["data"]["values"][1]]
    except (KeyError, IndexError, TypeError):
        values = []
    stack.check(status == 200 and values == [clients],
                f"a query through the data source {expect['datasource']} returns the {clients} players "
                f"(HTTP {status}, {values})")

    login = json.dumps({"user": "admin", "password": "admin"}).encode()
    status, _ = http(f"{stack.grafana}/login", login)
    stack.check(status in (400, 401, 403), f"signing in as admin is refused (HTTP {status}): Grafana has no account")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-name", default=DEFAULT_PROJECT, help=f"Compose project (default {DEFAULT_PROJECT})")
    parser.add_argument("--timeout", type=float, default=180, help="seconds to wait for each step")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)  # keep the order of results and logs in CI output

    stack = Stack(args.project_name, args.timeout)
    try:
        if not shutil.which("docker"):
            raise Failure("docker is not on the PATH")
        version = stack.compose("version", "--short", capture=True).stdout.strip()
        existing = stack.compose("ps", "--all", "--quiet", capture=True).stdout.split()
        if existing:
            raise Failure(f"the Compose project {args.project_name} already has {len(existing)} container(s); "
                          "remove them or pass another --project-name")
    except (Failure, OSError) as exc:
        print(f"smoke_demo: {exc}", file=sys.stderr)
        return 2

    print(f"     Docker Compose {version}, project {args.project_name}, "
          + ", ".join(f"{name}={port}" for name, port in stack.ports.items()))
    started = time.monotonic()
    try:
        stack.compose("up", "--detach", "--quiet-pull")
        clients = prometheus_checks(stack)
        grafana_checks(stack, clients)
    except (Failure, OSError, KeyError, ValueError, TypeError, AttributeError) as exc:
        stack.failures.append(str(exc) or type(exc).__name__)
        print(f"FAIL {exc or type(exc).__name__}")
    finally:
        if stack.failures:
            stack.compose("logs", "--no-color", "--tail", "40", check=False)
        down = stack.compose("down", "--volumes", "--remove-orphans", "--timeout", "20", check=False)
        if down.returncode != 0:
            stack.failures.append(f"docker compose down failed with exit code {down.returncode}")
    seconds = time.monotonic() - started
    if stack.failures:
        print(f"smoke_demo: {len(stack.failures)} check(s) failed ({seconds:.0f} s)")
        return 1
    print(f"smoke_demo: all checks passed, stack removed ({seconds:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
