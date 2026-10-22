#!/usr/bin/env python3
"""A fake game server for tests and demos: synthetic data on the HTTP endpoints FXServer serves.

It answers the paths that the pack's scrape config, json_exporter and blackbox_exporter use, in
the shapes and with the access rules of FXServer build 35245 as read in its source code
(docs/metrics.md has the details and links). Every value is synthetic: there are no players, no
names, no identifiers and no addresses other than 127.0.0.1. It is not a game server and must
never be reachable by players.

Endpoints (port 30120 by default, bound to 127.0.0.1 unless --bind says otherwise):

  GET /info.json       server version, ServerInfo variables, started resources
  GET /dynamic.json    hostname, client count, sv_maxclients
  GET /players.json    one anonymous entry per client, as the server serves it without a token;
                       here so that tests can prove the pack never requests it (see /fake/state)
  GET /perf/           the tickTime histogram (threads svMain, svNetwork and svSync) in the
                       Prometheus text format, with Content-Type "text/plain". When a user or a
                       password is set, every request without the exact Basic credentials gets
                       401 "Unauthorized."; with neither set the endpoint is open, as on the
                       real server.

Not modelled: the rate limits, blocking the sending address after a paranoia refusal (and
closing the socket at level 3), the server icon and the players token (sv_playersToken).

Fake-only control endpoints (off with --no-control):

  GET  /fake/state     current settings and the number of requests per path
  POST /fake/control   JSON object with any of:
                         "main_tick_ms": mean svMain tick time in milliseconds (the load knob;
                                         a spike is 70 or more, the default is 4)
                         "for_seconds":  with main_tick_ms, return to the previous value after
                                         this many seconds (a temporary spike)
                         "clients":      connected clients, 0 to max clients
                         "restart":      true resets the histograms, like a server restart

Settings come from the command line or, for each option, from an environment variable
(FAKE_PORT, FAKE_BIND, FAKE_BUILD, FAKE_CLIENTS, FAKE_MAX_CLIENTS, FAKE_MAIN_TICK_MS,
FAKE_REQUEST_PARANOIA, FAKE_SEED, FAKE_PERF_USER). The /perf/ password is read from
FAKE_PERF_PASSWORD or from the file named by --perf-password-file or FAKE_PERF_PASSWORD_FILE,
never from the command line.

  python3 demo/fake-fxserver/fake_fxserver.py --perf-user prometheus --perf-password-file pw.txt

Python 3.10 or newer, standard library only.
"""

from __future__ import annotations

import argparse
import base64
import hmac
import json
import math
import os
import random
import sys
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import urlsplit

# The three threads that observe tickTime, with their timer interval in whole milliseconds
# (GameServer.cpp, build 35245: 1000 / 20, 1000 / 100 and 1000 / 120 in integer arithmetic).
THREAD_INTERVAL_MS = {"svMain": 50, "svNetwork": 10, "svSync": 8}
# Mean tick time in milliseconds for the threads the load knob does not move (synthetic values).
DEFAULT_TICK_MS = {"svMain": 4.0, "svNetwork": 0.6, "svSync": 1.2}
# Bucket upper bounds of tickTime in seconds (GameServer.cpp, build 35245), +Inf is added.
BUCKETS = (0.001, 0.002, 0.004, 0.006, 0.008, 0.010, 0.015, 0.020, 0.030, 0.050, 0.070, 0.100, 0.150, 0.250)
BUCKETS_MS = tuple(round(bound * 1000) for bound in BUCKETS)
# The histogram never simulates more than this many seconds per update: after a longer pause
# without requests the counters continue as if the server had been paused.
MAX_STEP_SECONDS = 600
MAX_TICK_MS = 10_000.0
DEFAULT_RESOURCES = ("hardcap", "mapmanager", "spawnmanager", "sessionmanager", "basic-gamemode")
COUNTED_PATHS = ("/info.json", "/dynamic.json", "/players.json", "/perf/", "/fake/state", "/fake/control")
PARANOIA_REPLY = b"Nope."


def format_bound(bound: float) -> str:
    return "+Inf" if math.isinf(bound) else repr(bound)


@dataclass
class ThreadHistogram:
    """Cumulative tickTime histogram of one thread, advanced in simulated milliseconds."""

    interval_ms: int
    next_tick_ms: int = 0  # simulated time of the next tick
    counts: list[int] = field(default_factory=lambda: [0] * (len(BUCKETS) + 1))  # per bucket, not cumulative
    total: int = 0
    sum_ms: int = 0

    def observe(self, measured_ms: int) -> None:
        index = next((i for i, bound in enumerate(BUCKETS_MS) if measured_ms <= bound), len(BUCKETS_MS))
        self.counts[index] += 1
        self.total += 1
        self.sum_ms += measured_ms

    def cumulative(self) -> list[int]:
        out, running = [], 0
        for count in self.counts:
            running += count
            out.append(running)
        return out


class TickSimulation:
    """Synthetic tick times for svMain, svNetwork and svSync.

    Each tick takes a random time around the thread's mean (uniform between half and one and a
    half times the mean) and is recorded in whole milliseconds, as the server measures it. A
    thread ticks once per timer interval, or right after the previous tick when that took longer
    than the interval. Simulated time is counted in whole milliseconds from the start; the clock
    (seconds) is injectable, so tests can move time forward without sleeping.
    """

    def __init__(self, main_tick_ms: float, seed: int | None, clock: Callable[[], float]):
        self._clock = clock
        self._rng = random.Random(seed)
        self._lock = threading.Lock()
        self._start = clock()
        self._done_until_ms = 0
        self.base_main_tick_ms = check_tick_ms(main_tick_ms)
        self._spike: tuple[float, int] | None = None  # (main_tick_ms, end in simulated ms)
        self.histograms = {name: ThreadHistogram(interval) for name, interval in THREAD_INTERVAL_MS.items()}

    def now_ms(self) -> int:
        return math.floor((self._clock() - self._start) * 1000)

    def mean_ms(self, thread: str, at_ms: int) -> float:
        if thread != "svMain":
            return DEFAULT_TICK_MS[thread]
        if self._spike is not None and at_ms < self._spike[1]:
            return self._spike[0]
        return self.base_main_tick_ms

    def advance(self) -> None:
        with self._lock:
            now = self.now_ms()
            start = max(self._done_until_ms, now - MAX_STEP_SECONDS * 1000)
            for name, hist in self.histograms.items():
                hist.next_tick_ms = max(hist.next_tick_ms, start)
                while hist.next_tick_ms <= now:
                    duration_ms = self.mean_ms(name, hist.next_tick_ms) * self._rng.uniform(0.5, 1.5)
                    measured_ms = math.floor(duration_ms + self._rng.random())  # whole milliseconds
                    hist.observe(measured_ms)
                    hist.next_tick_ms += max(hist.interval_ms, measured_ms)
            self._done_until_ms = now
            if self._spike is not None and now >= self._spike[1]:
                self._spike = None

    def set_main_tick_ms(self, value: float, for_seconds: float | None) -> None:
        self.advance()
        value = check_tick_ms(value)
        with self._lock:
            if for_seconds is None:
                self.base_main_tick_ms = value
                self._spike = None
            else:
                self._spike = (value, self.now_ms() + round(for_seconds * 1000))

    def current_main_tick_ms(self) -> float:
        with self._lock:
            return self.mean_ms("svMain", self.now_ms())

    def spike_seconds_left(self) -> float:
        with self._lock:
            if self._spike is None:
                return 0.0
            return max(0, self._spike[1] - self.now_ms()) / 1000

    def restart(self) -> None:
        """Start from zero, like a restarted server: the first ticks come one interval later."""
        with self._lock:
            now = self.now_ms()
            self.histograms = {name: ThreadHistogram(interval, next_tick_ms=now + interval)
                               for name, interval in THREAD_INTERVAL_MS.items()}
            self._done_until_ms = now

    def exposition(self) -> str:
        """The histogram in the Prometheus text format, in the order the server writes it."""
        self.advance()
        with self._lock:
            lines = ["# HELP tickTime Time spent on server ticks", "# TYPE tickTime histogram"]
            for name, hist in self.histograms.items():
                label = f'name="{name}"'
                lines.append(f"tickTime_count{{{label}}} {hist.total}")
                lines.append(f"tickTime_sum{{{label}}} {hist.sum_ms / 1000:.3f}")
                for bound, count in zip((*BUCKETS, math.inf), hist.cumulative()):
                    lines.append(f'tickTime_bucket{{{label},le="{format_bound(bound)}"}} {count}')
        # Fake-only: stands in for any other metric a server version may add. The scrape config
        # keeps only tickTime, so this one must never reach Prometheus.
        lines += ["# HELP fake_unlisted_metric Not a server metric; the scrape config must drop it",
                  "# TYPE fake_unlisted_metric gauge", 'fake_unlisted_metric{name="extra"} 1']
        return "\n".join(lines) + "\n"


def check_tick_ms(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= MAX_TICK_MS:
        raise ValueError(f"main_tick_ms must be a number from 0 to {MAX_TICK_MS:g}")
    return float(value)


@dataclass
class FakeConfig:
    build: int = 35245
    clients: int = 3
    max_clients: int = 32
    main_tick_ms: float = DEFAULT_TICK_MS["svMain"]
    perf_user: str = ""
    perf_password: str = ""
    request_paranoia: int = 0
    seed: int | None = None
    control: bool = True
    resources: tuple[str, ...] = DEFAULT_RESOURCES


class FakeServerState:
    """Everything the endpoints serve; shared by the request threads."""

    def __init__(self, config: FakeConfig, clock: Callable[[], float] = time.monotonic):
        if not 1 <= config.max_clients <= 2048:
            raise ValueError("max clients must be from 1 to 2048")
        if not 0 <= config.clients <= config.max_clients:
            raise ValueError("clients must be from 0 to max clients")
        self.config = config
        self.clients = config.clients
        self.ticks = TickSimulation(config.main_tick_ms, config.seed, clock)
        self.requests = {path: 0 for path in (*COUNTED_PATHS, "other")}
        self.perf_refused = 0
        self._lock = threading.Lock()
        if config.perf_user or config.perf_password:
            token = base64.b64encode(f"{config.perf_user}:{config.perf_password}".encode()).decode()
            self._perf_auth: bytes | None = f"Basic {token}".encode()
        else:
            self._perf_auth = None

    @property
    def perf_auth_required(self) -> bool:
        return self._perf_auth is not None

    def count(self, path: str) -> None:
        with self._lock:
            self.requests[path if path in self.requests else "other"] += 1

    def perf_allowed(self, authorization: str | None) -> bool:
        if self._perf_auth is None:
            return True
        allowed = authorization is not None and hmac.compare_digest(authorization.encode(), self._perf_auth)
        if not allowed:
            with self._lock:
                self.perf_refused += 1
        return allowed

    def server_string(self) -> str:
        # The Linux build script writes "<branch> <CI build number> linux" for master and release
        # builds ("<branch> SERVER v1.0.0.<date> linux" only for feature branches), and the build
        # 35245 artifact holds "FXServer-master v1.0.0.35245 linux". Not yet seen on a running
        # server; see docs/metrics.md.
        return f"FXServer-master v1.0.0.{self.config.build} linux"

    def info(self) -> dict:
        variables = {
            "gamename": "gta5",
            "locale": "en-US",
            "onesync_enabled": "true",
            "sv_maxClients": str(self.config.max_clients),
            "sv_projectDesc": "Synthetic data for tests",
            "sv_projectName": "Fake test server",
        }
        return {
            "enhancedHostSupport": True,
            "enforceSteamAuth": False,
            "requestSteamTicket": "unset",
            "resources": list(self.config.resources),
            "server": self.server_string(),
            "vars": variables,
            "version": 1048576 + self.config.build,  # the real value is a hash of this document
        }

    def dynamic(self) -> dict:
        return {
            "clients": self.clients,
            "gametype": "",
            "hostname": "Fake test server",
            "iv": str(1048576 + self.config.build),
            "mapname": "",
            "sv_maxclients": str(self.config.max_clients),
        }

    def players(self) -> list[dict]:
        # What the server serves without the players token: no name, no identifiers, no address.
        anonymous = {"endpoint": "127.0.0.1", "id": 0, "identifiers": [], "name": "Player", "ping": 0}
        return [dict(anonymous) for _ in range(self.clients)]

    def state(self) -> dict:
        with self._lock:
            requests = dict(self.requests)
            perf_refused = self.perf_refused
        return {
            "build": self.config.build,
            "clients": self.clients,
            "max_clients": self.config.max_clients,
            "main_tick_ms": self.ticks.current_main_tick_ms(),
            "spike_seconds_left": round(self.ticks.spike_seconds_left(), 3),
            "perf_auth": self.perf_auth_required,
            "perf_refused": perf_refused,
            "request_paranoia": self.config.request_paranoia,
            "requests": requests,
        }

    def control(self, body: object) -> dict:
        if not isinstance(body, dict) or not body:
            raise ValueError("send a JSON object with main_tick_ms, for_seconds, clients or restart")
        unknown = sorted(set(body) - {"main_tick_ms", "for_seconds", "clients", "restart"})
        if unknown:
            raise ValueError(f"unknown field(s): {', '.join(unknown)}")
        for_seconds = body.get("for_seconds")
        if for_seconds is not None:
            if "main_tick_ms" not in body:
                raise ValueError("for_seconds needs main_tick_ms")
            if (isinstance(for_seconds, bool) or not isinstance(for_seconds, (int, float))
                    or not 0 < for_seconds <= 86400):
                raise ValueError("for_seconds must be a number above 0 and at most 86400")
        clients = body.get("clients")
        if clients is not None and (isinstance(clients, bool) or not isinstance(clients, int)
                                    or not 0 <= clients <= self.config.max_clients):
            raise ValueError(f"clients must be a whole number from 0 to {self.config.max_clients}")
        restart = body.get("restart", False)
        if not isinstance(restart, bool):
            raise ValueError("restart must be true or false")
        if "main_tick_ms" in body:
            check_tick_ms(body["main_tick_ms"])
        # Everything is valid: apply it.
        if restart:
            self.ticks.restart()
        if "main_tick_ms" in body:
            self.ticks.set_main_tick_ms(body["main_tick_ms"], for_seconds)
        if clients is not None:
            self.clients = clients
        return self.state()


class FakeHandler(BaseHTTPRequestHandler):
    server_version = "FakeFXServer"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    state: FakeServerState  # set by make_server
    quiet = False

    def log_message(self, format: str, *args) -> None:  # noqa: A002 (signature of the base class)
        if not self.quiet:
            sys.stderr.write(f"fake-fxserver: {self.address_string()} {format % args}\n")

    def reply(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def reply_json(self, status: int, data: object) -> None:
        self.reply(status, json.dumps(data, separators=(",", ":")).encode(), "application/json")

    def path_only(self) -> str:
        path = urlsplit(self.path).path
        if path == "/perf" or path.startswith("/perf/"):
            return "/perf/"
        return path

    def paranoid_refusal(self) -> bool:
        """sv_requestParanoia: 1 refuses requests through a proxy (Via header), 2 also browsers."""
        level = self.state.config.request_paranoia
        if (level >= 1 and self.headers.get("Via")) or (level >= 2 and self.headers.get("Upgrade-Insecure-Requests")):
            self.reply(HTTPStatus.FORBIDDEN, PARANOIA_REPLY, "text/plain")
            return True
        return False

    def do_GET(self) -> None:  # noqa: N802 (name given by BaseHTTPRequestHandler)
        path = self.path_only()
        state = self.state
        state.count(path)
        if path in ("/info.json", "/dynamic.json", "/players.json"):
            if self.paranoid_refusal():
                return
            data = {"/info.json": state.info, "/dynamic.json": state.dynamic, "/players.json": state.players}[path]()
            self.reply_json(HTTPStatus.OK, data)
        elif path == "/perf/":
            if not state.perf_allowed(self.headers.get("Authorization")):
                self.reply(HTTPStatus.UNAUTHORIZED, b"Unauthorized.", "text/plain")
                return
            self.reply(HTTPStatus.OK, state.ticks.exposition().encode(), "text/plain")
        elif path == "/fake/state" and state.config.control:
            self.reply_json(HTTPStatus.OK, state.state())
        else:
            self.reply(HTTPStatus.NOT_FOUND, b"Not found.", "text/plain")

    do_HEAD = do_GET

    def do_POST(self) -> None:  # noqa: N802
        path = self.path_only()
        self.state.count(path)
        if path != "/fake/control" or not self.state.config.control:
            self.reply(HTTPStatus.NOT_FOUND, b"Not found.", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 < length <= 4096:
            self.reply_json(HTTPStatus.BAD_REQUEST, {"error": "send a JSON body of at most 4096 bytes"})
            return
        try:
            body = json.loads(self.rfile.read(length))
            self.reply_json(HTTPStatus.OK, self.state.control(body))
        except (ValueError, UnicodeDecodeError) as exc:
            self.reply_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})


def make_server(state: FakeServerState, bind: str = "127.0.0.1", port: int = 30120,
                quiet: bool = False) -> ThreadingHTTPServer:
    handler = type("BoundFakeHandler", (FakeHandler,), {"state": state, "quiet": quiet})
    server = ThreadingHTTPServer((bind, port), handler)
    server.daemon_threads = True
    return server


def env_default(name: str, default: str) -> str:
    return os.environ.get(name, default)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fake game server with synthetic data, for tests and demos.",
                                     allow_abbrev=False)
    parser.add_argument("--bind", default=env_default("FAKE_BIND", "127.0.0.1"), help="address to listen on")
    parser.add_argument("--port", type=int, default=int(env_default("FAKE_PORT", "30120")))
    parser.add_argument("--build", type=int, default=int(env_default("FAKE_BUILD", "35245")),
                        help="build number in the version string")
    parser.add_argument("--clients", type=int, default=int(env_default("FAKE_CLIENTS", "3")))
    parser.add_argument("--max-clients", type=int, default=int(env_default("FAKE_MAX_CLIENTS", "32")))
    parser.add_argument("--main-tick-ms", type=float, default=float(env_default("FAKE_MAIN_TICK_MS", "4")),
                        help="mean svMain tick time in milliseconds (the load knob)")
    parser.add_argument("--request-paranoia", type=int, choices=range(4),
                        default=int(env_default("FAKE_REQUEST_PARANOIA", "0")), help="like sv_requestParanoia")
    parser.add_argument("--seed", type=int, default=int(env_default("FAKE_SEED", "-1")),
                        help="random seed for repeatable tick times (-1: random)")
    parser.add_argument("--perf-user", default=env_default("FAKE_PERF_USER", ""),
                        help="user for /perf/ (like sv_prometheusBasicAuthUser)")
    parser.add_argument("--perf-password-file", default=env_default("FAKE_PERF_PASSWORD_FILE", ""),
                        help="file with the /perf/ password; FAKE_PERF_PASSWORD is used when not set")
    parser.add_argument("--no-control", action="store_true", help="turn off /fake/state and /fake/control")
    parser.add_argument("--quiet", action="store_true", help="do not log requests")
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> FakeConfig:
    if args.perf_password_file:
        with open(args.perf_password_file, encoding="utf-8") as fh:
            password = fh.read().rstrip("\r\n")
    else:
        password = os.environ.get("FAKE_PERF_PASSWORD", "")
    return FakeConfig(build=args.build, clients=args.clients, max_clients=args.max_clients,
                      main_tick_ms=args.main_tick_ms, perf_user=args.perf_user, perf_password=password,
                      request_paranoia=args.request_paranoia, seed=None if args.seed < 0 else args.seed,
                      control=not args.no_control)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        state = FakeServerState(config_from_args(args))
    except (OSError, ValueError) as exc:
        print(f"fake-fxserver: {exc}", file=sys.stderr)
        return 2
    server = make_server(state, args.bind, args.port, args.quiet)
    host, port = server.server_address[:2]
    auth = "with basic auth" if state.perf_auth_required else "open (no user or password set)"
    print(f"fake-fxserver: synthetic data on http://{host}:{port} (build {args.build}); /perf/ {auth}",
          file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
