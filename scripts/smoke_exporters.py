#!/usr/bin/env python3
"""End-to-end check of the scrape config, exporter modules and rules against the fake game server.

Starts, all on 127.0.0.1: the fake server (demo/fake-fxserver/fake_fxserver.py) on 30120 with
/perf/ behind basic auth, a synthetic version list (served by this script on a free port),
json_exporter on 7979 with json_exporter/config.yml, blackbox_exporter on 9115 with
blackbox/blackbox.yml, and Prometheus on a free port. Prometheus loads
prometheus/scrape/fxserver.yml and prometheus/scrape/versions.yml through scrape_config_files,
as the installation guide does, and every rule file in rules/. Three things are changed in
temporary copies: the /perf/ password file path, and the version list's URL and its 4-minute
interval (15 s here, so that the run does not wait minutes for the first scrape). Then it
checks through the Prometheus API that:

- every target is up, and both exporters accept their configuration (--config.check);
- the tick-time histogram arrives as fxserver_tick_time_seconds_* with a thread label for
  svMain, svNetwork and svSync, and no series keeps the server's name label;
- exactly the documented fxserver_* metrics exist, with the fake's values and the version list's
  Recommended build, and nothing else from /perf/ gets through;
- no series has a label outside the expected set, and no label name a player could be tied to;
- the blackbox probes succeed (TCP, info.json, /perf/ refused without credentials);
- players.json was never requested (the fake counts requests per path);
- every rule file is loaded and every rule evaluates without an error; the recorded tick-time
  series exist per server and thread with plausible values, and no alert is active while the
  fake server is healthy;
- a tick-time spike (the fake's load knob) makes FXServerTickTimeHigh pending for the server and
  svMain, and nothing else;
- a stopped fake server makes FXServerDown pending for the server, while FXServerTargetDown stays
  quiet (the failing scrapes of a server that is down are not a monitoring problem).

The CI job "exporters" runs it with the pinned binaries on the PATH. Locally, put prometheus,
json_exporter and blackbox_exporter on the PATH (or pass --bin-dir) and make sure the ports
30120, 7979 and 9115 are free:

  python3 scripts/smoke_exporters.py [--bin-dir DIR] [--timeout 120]

Exit code 0 when every check passes, 1 when one fails, 2 when the run could not start.
Python 3.10 or newer, standard library only.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRAPE_CONFIG = ROOT / "prometheus" / "scrape" / "fxserver.yml"
VERSIONS_CONFIG = ROOT / "prometheus" / "scrape" / "versions.yml"
RULES_DIR = ROOT / "rules"
JSON_EXPORTER_CONFIG = ROOT / "json_exporter" / "config.yml"
BLACKBOX_CONFIG = ROOT / "blackbox" / "blackbox.yml"
FAKE_SERVER = ROOT / "demo" / "fake-fxserver" / "fake_fxserver.py"
PASSWORD_FILE = "/etc/prometheus/secrets/fxserver_perf"
FIXED_PORTS = {"fake game server": 30120, "json_exporter": 7979, "blackbox_exporter": 9115}
VERSIONS_URL = "https://changelogs-live.fivem.net/api/changelog/versions/linux/server"
VERSIONS_PATH = "/api/changelog/versions/linux/server"
VERSIONS_INTERVAL = "4m"
JOBS = ("fxserver_perf", "fxserver_json", "fxserver_blackbox", "fxserver_versions")
DEFAULT_JOB_TARGETS = 6  # the targets of prometheus/scrape/fxserver.yml
EXPECTED_TARGETS = DEFAULT_JOB_TARGETS + 1  # and the version list
THREADS = {"svMain", "svNetwork", "svSync"}
BUCKETS_PER_THREAD = 15  # 14 bounds and +Inf
EXPECTED_METRICS = {
    "fxserver_tick_time_seconds_bucket", "fxserver_tick_time_seconds_sum", "fxserver_tick_time_seconds_count",
    "fxserver_clients", "fxserver_max_clients", "fxserver_info", "fxserver_onesync_enabled",
    "fxserver_recommended_build",
}
ALLOWED_LABELS = {"__name__", "job", "instance", "server", "module", "thread", "le", "version", "build", "phase"}
PLAYER_LABELS = {"name", "player", "players", "identifier", "identifiers", "license", "ip", "endpoint", "ping", "id"}
FAKE_CLIENTS = 3
FAKE_MAX_CLIENTS = 32
FAKE_BUILD = "35245"
FAKE_RECOMMENDED_BUILD = "35300"
SERVER = "game-01"
SPIKE_TICK_MS = 90  # svMain mean tick time for the spike; most ticks then take longer than 50 ms
HEALTHY_MAIN_P95 = 0.05  # the threshold of FXServerTickTimeHigh
MAIN_TICKS_PER_SECOND = (15, 25)  # svMain ticks every 50 ms while its ticks are short


class Failure(Exception):
    pass


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def port_in_use(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def find_binary(name: str, bin_dir: str | None) -> str:
    if bin_dir:
        path = Path(bin_dir) / name
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        raise Failure(f"{name} not found in {bin_dir}")
    found = shutil.which(name)
    if not found:
        raise Failure(f"{name} is not on the PATH (or pass --bin-dir)")
    return found


def http_json(url: str, data: bytes | None = None) -> object:
    with urllib.request.urlopen(url, data=data, timeout=10) as resp:  # noqa: S310 (loopback URLs only)
        return json.load(resp)


class Prometheus:
    def __init__(self, port: int):
        self.base = f"http://127.0.0.1:{port}"

    def api(self, path: str, **params: str) -> object:
        url = f"{self.base}/api/v1/{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        doc = http_json(url)
        if doc.get("status") != "success":
            raise Failure(f"Prometheus API {path}: {doc}")
        return doc["data"]

    def query(self, expr: str) -> list[dict]:
        data = self.api("query", query=expr)
        return data["result"]

    def ready(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base}/-/ready", timeout=2) as resp:  # noqa: S310
                return resp.status == 200
        except (OSError, urllib.error.URLError):
            return False


class Run:
    def __init__(self, bins: dict[str, str], timeout: float, work: Path):
        self.bins = bins
        self.timeout = timeout
        self.work = work
        self.procs: list[tuple[str, subprocess.Popen, Path]] = []
        self.failures: list[str] = []

    def start(self, label: str, argv: list[str], env: dict[str, str] | None = None) -> subprocess.Popen:
        log = self.work / f"{label}.log"
        with open(log, "wb") as fh:
            proc = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT, cwd=self.work,
                                    env={**os.environ, **(env or {})})
        self.procs.append((label, proc, log))
        return proc

    def stop(self, show_logs: bool) -> None:
        for label, proc, log in reversed(self.procs):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            if show_logs:
                text = log.read_text(encoding="utf-8", errors="replace")
                tail = "\n".join(text.splitlines()[-25:])
                print(f"--- last lines of the {label} log ---\n{tail}", file=sys.stderr)

    def check(self, ok: bool, message: str) -> None:
        print(f"{'ok  ' if ok else 'FAIL'} {message}")
        if not ok:
            self.failures.append(message)

    def assert_running(self, stopped: tuple[str, ...] = ()) -> None:
        """Every process still runs, except those in stopped (stopped on purpose)."""
        for label, proc, _ in self.procs:
            if label not in stopped and proc.poll() is not None:
                raise Failure(f"{label} exited with code {proc.returncode}")

    def wait_until(self, what: str, probe, stopped: tuple[str, ...] = ()):
        """Call probe() every 2 seconds until it returns something true; return that value."""
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            self.assert_running(stopped)
            result = probe()
            if result:
                return result
            time.sleep(2)
        raise Failure(f"{what}: not reached within {self.timeout:g} seconds")


def config_checks(run: Run) -> None:
    for name, config in (("json_exporter", JSON_EXPORTER_CONFIG), ("blackbox_exporter", BLACKBOX_CONFIG)):
        result = subprocess.run([run.bins[name], "--config.check", f"--config.file={config}"],
                                capture_output=True, text=True)
        run.check(result.returncode == 0, f"{name} --config.check accepts {config.relative_to(ROOT)}")
        if result.returncode != 0:
            print(result.stdout + result.stderr, file=sys.stderr)


def replace_once(text: str, pattern: str, replacement: str, source: Path) -> str:
    new_text, count = re.subn(pattern, lambda m: m.group(1) + replacement, text, flags=re.M)
    if count != 1:
        raise Failure(f"expected one match of {pattern!r} in {source.relative_to(ROOT)}")
    return new_text


def prometheus_config(work: Path, password_file: Path, versions_port: int) -> Path:
    """The main config: both scrape files, with the temporary password file instead of the
    documented path and the local version list instead of the real one, and every rule file."""
    scrape = replace_once(SCRAPE_CONFIG.read_text(encoding="utf-8"),
                          rf"^(\s*password_file: ){re.escape(PASSWORD_FILE)}$", str(password_file), SCRAPE_CONFIG)
    versions = VERSIONS_CONFIG.read_text(encoding="utf-8")
    versions = replace_once(versions, rf'^(\s*- targets: \["){re.escape(VERSIONS_URL)}(?="\]$)',
                            f"http://127.0.0.1:{versions_port}{VERSIONS_PATH}", VERSIONS_CONFIG)
    versions = replace_once(versions, rf"^(\s*scrape_interval: ){VERSIONS_INTERVAL}$", "15s", VERSIONS_CONFIG)
    files = []
    for name, text in (("fxserver.yml", scrape), ("versions.yml", versions)):
        path = work / name
        path.write_text(text, encoding="utf-8")
        files.append(path)
    main = {"scrape_config_files": [str(p) for p in files], "rule_files": [str(RULES_DIR / "*.yml")]}
    out = work / "prometheus.yml"
    out.write_text(json.dumps(main, indent=2) + "\n", encoding="utf-8")  # JSON is valid YAML
    return out


def rule_counts() -> dict[str, int]:
    """Rule files in rules/ and the number of rules in each (lines that start an alert or record)."""
    return {p.name: len(re.findall(r"^\s*- (?:alert|record):", p.read_text(encoding="utf-8"), re.M))
            for p in sorted(RULES_DIR.glob("*.yml"))}


class VersionList:
    """A synthetic version list on 127.0.0.1: the one field the module reads, plus one it ignores."""

    def __init__(self):
        body = json.dumps({"recommended": FAKE_RECOMMENDED_BUILD, "latest": "35400"}).encode()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 (name given by BaseHTTPRequestHandler)
                found = urllib.parse.urlsplit(self.path).path == VERSIONS_PATH
                self.send_response(200 if found else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body) if found else 0))
                self.end_headers()
                if found:
                    self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A002
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def wait_for_targets(run: Run, prom: Prometheus) -> list[dict]:
    deadline = time.monotonic() + run.timeout
    while time.monotonic() < deadline:
        run.assert_running()
        if prom.ready():
            targets = prom.api("targets", state="active")["activeTargets"]
            scraped = [t for t in targets if t.get("health") in ("up", "down")]
            if len(targets) == EXPECTED_TARGETS and len(scraped) == EXPECTED_TARGETS:
                return targets
        time.sleep(2)
    raise Failure(f"not every target was scraped within {run.timeout:g} seconds")


def series_checks(run: Run, prom: Prometheus, fake_port: int) -> None:
    jobs = "|".join(JOBS)
    selector = f'{{job=~"{jobs}"}}'

    names = set(prom.api("label/__name__/values", **{"match[]": selector}))
    fxserver_names = {n for n in names if n.startswith("fxserver_")}
    run.check(fxserver_names == EXPECTED_METRICS,
              f"fxserver_* metrics are exactly the documented ones: {sorted(fxserver_names)}")
    leaked = sorted(n for n in names if n.startswith(("tickTime", "fake_")))
    run.check(not leaked, f"nothing else from /perf/ is kept (found: {leaked or 'none'})")

    labels = set(prom.api("labels", **{"match[]": selector}))
    run.check(labels <= ALLOWED_LABELS, f"labels are only {sorted(ALLOWED_LABELS & labels)} "
                                        f"(unexpected: {sorted(labels - ALLOWED_LABELS) or 'none'})")
    run.check(not labels & PLAYER_LABELS, f"no player label names (found: {sorted(labels & PLAYER_LABELS) or 'none'})")

    threads = {r["metric"].get("thread") for r in prom.query("count by (thread) (fxserver_tick_time_seconds_count)")}
    run.check(threads == THREADS, f"tick-time histogram has threads {sorted(t for t in threads if t)}")
    buckets = {r["metric"]["thread"]: int(r["value"][1])
               for r in prom.query("count by (thread) (fxserver_tick_time_seconds_bucket)")}
    run.check(buckets == {t: BUCKETS_PER_THREAD for t in THREADS},
              f"{BUCKETS_PER_THREAD} buckets per thread: {dict(sorted(buckets.items()))}")
    named = prom.query(f'count({{job=~"{jobs}", name!=""}})')
    run.check(not named, "no series keeps the server's name label")
    ticks = prom.query('fxserver_tick_time_seconds_count{thread="svMain"}')
    run.check(len(ticks) == 1 and float(ticks[0]["value"][1]) > 0, "svMain tick count is above 0")

    def value(expr: str) -> list[tuple[dict, float]]:
        return [(r["metric"], float(r["value"][1])) for r in prom.query(expr)]

    run.check([v for _, v in value("fxserver_clients")] == [FAKE_CLIENTS], f"fxserver_clients is {FAKE_CLIENTS}")
    run.check([v for _, v in value("fxserver_max_clients")] == [FAKE_MAX_CLIENTS],
              f"fxserver_max_clients is {FAKE_MAX_CLIENTS}")
    info = value("fxserver_info")
    run.check(len(info) == 1 and info[0][1] == 1 and info[0][0].get("build") == FAKE_BUILD,
              f"fxserver_info is 1 with build {FAKE_BUILD} ({info[0][0].get('version') if info else 'missing'})")
    run.check([v for _, v in value("fxserver_onesync_enabled")] == [1], "fxserver_onesync_enabled is 1")
    recommended = value("fxserver_recommended_build")
    run.check([v for _, v in recommended] == [float(FAKE_RECOMMENDED_BUILD)]
              and "server" not in (recommended[0][0] if recommended else {}),
              f"fxserver_recommended_build is {FAKE_RECOMMENDED_BUILD} from the version list, without a server label")

    probes = {m.get("module"): v for m, v in value('probe_success{job="fxserver_blackbox"}')}
    for module in ("tcp_connect", "http_fxserver_info", "http_401_expected"):
        run.check(probes.get(module) == 1, f"blackbox probe {module} succeeds")
    up = value(f'up{{job=~"{jobs}"}}')
    run.check(len(up) == EXPECTED_TARGETS and all(v == 1 for _, v in up), f"all {EXPECTED_TARGETS} targets are up")

    per_target = sorted((m["job"], m.get("module", "-"), int(v))
                        for m, v in value(f"scrape_samples_post_metric_relabeling{selector}"))
    for job, module, samples in per_target:
        print(f"     samples per scrape {job:<18} {module:<19} {samples}")
    print(f"     samples per scrape, all {len(per_target)} targets: {sum(n for _, _, n in per_target)}")

    state = http_json(f"http://127.0.0.1:{fake_port}/fake/state")
    requests = state["requests"]
    run.check(requests["/players.json"] == 0, "players.json was never requested")
    run.check(requests["/perf/"] > 0 and state["perf_refused"] > 0,
              f"/perf/ was scraped ({requests['/perf/']} requests) and refused without credentials "
              f"({state['perf_refused']} refused)")


ALERT_GROUP = "fxserver-alerts"
RECORDED = ("server_thread:fxserver_tick_time_seconds:p95_1m", "server_thread:fxserver_tick_time_seconds:p99_1m",
            "server_thread:fxserver_tick_time_seconds:mean1m", "server_thread:fxserver_tick_time_seconds_count:rate1m")


def alert_summary(alerts: list[dict]) -> str:
    return ", ".join(sorted(f"{a['labels'].get('alertname')} {a['state']}" for a in alerts)) or "none"


def alerts_named(prom: Prometheus, name: str) -> list[dict] | None:
    """All active alerts, if one of them is the named alert; else None."""
    alerts = prom.api("alerts")["alerts"]
    return alerts if any(a["labels"].get("alertname") == name for a in alerts) else None


def rule_checks(run: Run, prom: Prometheus, fake: subprocess.Popen, fake_port: int) -> None:
    groups = prom.api("rules")["groups"]
    loaded: dict[str, int] = {}
    for group in groups:
        loaded[Path(group["file"]).name] = loaded.get(Path(group["file"]).name, 0) + len(group["rules"])
    expected = rule_counts()
    run.check(loaded == expected, f"every rule file in rules/ is loaded with all its rules: {loaded}")

    # The recorded p95 needs two /perf/ scrapes within a minute and one evaluation; after that,
    # wait until every group has been evaluated again, so that every rule has seen the data.
    run.wait_until("the recorded p95 for every thread", lambda: len(prom.query(RECORDED[0])) == len(THREADS))
    marks = {g["name"]: g["lastEvaluation"] for g in prom.api("rules")["groups"]}
    run.wait_until("an evaluation of every rule group after that",
                   lambda: all(g["lastEvaluation"] != marks[g["name"]] for g in prom.api("rules")["groups"]))
    groups = prom.api("rules")["groups"]
    errors = [f"{r['name']}: {r.get('lastError')}" for g in groups for r in g["rules"] if r.get("health") != "ok"]
    run.check(not errors, f"every rule evaluates without an error ({'; '.join(errors) or 'all ok'})")

    for name in RECORDED:
        rows = prom.query(name)
        run.check({r["metric"].get("thread") for r in rows} == THREADS and len(rows) == len(THREADS)
                  and all(set(r["metric"]) == {"__name__", "server", "thread"} and r["metric"]["server"] == SERVER
                          for r in rows),
                  f"{name} has one series per thread, with only the labels server and thread")

    def main_thread(name: str) -> float:
        rows = prom.query(f'{name}{{thread="svMain"}}')
        return float(rows[0]["value"][1]) if rows else float("nan")

    p95, p99, rate = main_thread(RECORDED[0]), main_thread(RECORDED[1]), main_thread(RECORDED[3])
    run.check(0 < p95 <= p99 <= HEALTHY_MAIN_P95,
              f"svMain p95 {p95:.4f} s and p99 {p99:.4f} s of the healthy fake server, at most {HEALTHY_MAIN_P95} s")
    low, high = MAIN_TICKS_PER_SECOND
    run.check(low <= rate <= high, f"svMain ticks {rate:.1f} times per second (expected {low} to {high})")
    alerts = prom.api("alerts")["alerts"]
    run.check(not alerts, f"no alert is pending or firing while the fake server is healthy ({alert_summary(alerts)})")

    # A tick-time spike: FXServerTickTimeHigh goes pending (it fires only after 5 minutes).
    started = time.monotonic()
    http_json(f"http://127.0.0.1:{fake_port}/fake/control", json.dumps({"main_tick_ms": SPIKE_TICK_MS}).encode())
    alerts = run.wait_until("FXServerTickTimeHigh after the spike", lambda: alerts_named(prom, "FXServerTickTimeHigh"))
    expected_labels = {"alertname": "FXServerTickTimeHigh", "server": SERVER, "thread": "svMain", "severity": "warning"}
    run.check(len(alerts) == 1 and alerts[0]["labels"] == expected_labels and alerts[0]["state"] == "pending",
              f"a {SPIKE_TICK_MS} ms svMain spike makes FXServerTickTimeHigh pending for {SERVER} and svMain "
              f"after {time.monotonic() - started:.0f} s, and nothing else ({alert_summary(alerts)})")

    # The game server stops: FXServerDown goes pending. Once it is, wait for one more evaluation
    # of the group, so that FXServerTargetDown has seen the failed probes too.
    started = time.monotonic()
    fake.terminate()
    fake.wait(timeout=10)
    stopped = ("fake-fxserver",)
    run.wait_until("FXServerDown after the fake server stopped", lambda: alerts_named(prom, "FXServerDown"), stopped)
    seconds = time.monotonic() - started
    mark = next(g["lastEvaluation"] for g in prom.api("rules")["groups"] if g["name"] == ALERT_GROUP)
    run.wait_until(f"the next evaluation of {ALERT_GROUP}",
                   lambda: any(g["name"] == ALERT_GROUP and g["lastEvaluation"] != mark
                               for g in prom.api("rules")["groups"]), stopped)
    alerts = prom.api("alerts")["alerts"]
    down = [a for a in alerts if a["labels"].get("alertname") == "FXServerDown"]
    run.check(len(down) == 1 and down[0]["labels"] == {"alertname": "FXServerDown", "server": SERVER,
                                                       "severity": "critical"},
              f"the stopped fake server makes FXServerDown pending for {SERVER} after {seconds:.0f} s")
    run.check(not any(a["labels"].get("alertname") == "FXServerTargetDown" for a in alerts),
              f"FXServerTargetDown stays quiet while the server is down ({alert_summary(alerts)})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bin-dir", help="folder with prometheus, json_exporter and blackbox_exporter")
    parser.add_argument("--timeout", type=float, default=120, help="seconds to wait for the first scrapes")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)  # keep the order of results and logs in CI output

    try:
        bins = {name: find_binary(name, args.bin_dir) for name in ("prometheus", "json_exporter", "blackbox_exporter")}
        busy = [f"{label} ({port})" for label, port in FIXED_PORTS.items() if port_in_use(port)]
        if busy:
            raise Failure(f"port(s) in use on 127.0.0.1: {', '.join(busy)}")
    except Failure as exc:
        print(f"smoke_exporters: {exc}", file=sys.stderr)
        return 2

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="gso-smoke-") as tmp:
        work = Path(tmp)
        run = Run(bins, args.timeout, work)
        versions = VersionList()
        try:
            config_checks(run)
            password = secrets.token_urlsafe(24)
            password_file = work / "fxserver_perf"
            password_file.write_text(password + "\n", encoding="utf-8")
            password_file.chmod(0o600)
            prom_port = free_port()
            fake = run.start("fake-fxserver", [sys.executable, str(FAKE_SERVER), "--port", "30120", "--quiet",
                                        "--clients", str(FAKE_CLIENTS), "--max-clients", str(FAKE_MAX_CLIENTS),
                                        "--build", FAKE_BUILD, "--perf-user", "prometheus",
                                        "--perf-password-file", str(password_file)])
            run.start("json_exporter", [bins["json_exporter"], f"--config.file={JSON_EXPORTER_CONFIG}",
                                        "--web.listen-address=127.0.0.1:7979"])
            run.start("blackbox_exporter", [bins["blackbox_exporter"], f"--config.file={BLACKBOX_CONFIG}",
                                            "--web.listen-address=127.0.0.1:9115"])
            config = prometheus_config(work, password_file, versions.port)
            run.start("prometheus", [bins["prometheus"], f"--config.file={config}",
                                     f"--storage.tsdb.path={work / 'data'}",
                                     f"--web.listen-address=127.0.0.1:{prom_port}"])
            prom = Prometheus(prom_port)
            targets = wait_for_targets(run, prom)
            for t in sorted(targets, key=lambda t: (t["labels"]["job"], t["labels"].get("module", ""))):
                labels = t["labels"]
                print(f"     target {labels['job']:<18} {labels.get('module', '-'):<19} {t['health']:<5} "
                      f"{t.get('lastError') or ''}")
            series_checks(run, prom, 30120)
            rule_checks(run, prom, fake, 30120)
        except (Failure, OSError, KeyError, ValueError, StopIteration, subprocess.TimeoutExpired) as exc:
            run.failures.append(str(exc) or type(exc).__name__)
            print(f"FAIL {exc or type(exc).__name__}")
        finally:
            run.stop(show_logs=bool(run.failures))
            versions.close()
    seconds = time.monotonic() - started
    if run.failures:
        print(f"smoke_exporters: {len(run.failures)} check(s) failed ({seconds:.0f} s)")
        return 1
    print(f"smoke_exporters: all checks passed ({seconds:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
