"""Tests for the fake game server (demo/fake-fxserver/fake_fxserver.py).

The simulation tests use an injected clock, so they move time forward without sleeping. The HTTP
tests start the server on a free port of 127.0.0.1 in a thread. Standard library only.
"""

from __future__ import annotations

import base64
import contextlib
import http.client
import importlib.util
import io
import json
import math
import os
import re
import secrets
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
FAKE_PATH = ROOT / "demo" / "fake-fxserver" / "fake_fxserver.py"


def load_fake():
    spec = importlib.util.spec_from_file_location("fake_fxserver", FAKE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up while the class is built
    spec.loader.exec_module(module)
    return module


fake = load_fake()

SAMPLE_RE = re.compile(r'^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(\{(?P<labels>[^}]*)\})? (?P<value>\S+)$')
LABEL_RE = re.compile(r'(?P<key>[a-zA-Z_][a-zA-Z0-9_]*)="(?P<value>[^"\\]*)"')


class FakeClock:
    def __init__(self) -> None:
        self.now = 5000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def parse_exposition(text: str) -> dict[tuple[str, tuple[tuple[str, str], ...]], float]:
    """Parse the Prometheus text format strictly enough to catch malformed lines."""
    samples = {}
    for line in text.splitlines():
        if line.startswith("# HELP ") or line.startswith("# TYPE "):
            continue
        match = SAMPLE_RE.match(line)
        if not match:
            raise AssertionError(f"not a valid sample line: {line!r}")
        labels_text = match.group("labels") or ""
        labels = tuple(sorted((m.group("key"), m.group("value")) for m in LABEL_RE.finditer(labels_text)))
        rebuilt = ",".join(f'{k}="{v}"' for k, v in sorted(labels))
        if labels_text and sorted(labels_text.split(",")) != sorted(rebuilt.split(",")):
            raise AssertionError(f"bad labels in {line!r}")
        samples[(match.group("name"), labels)] = float(match.group("value"))
    return samples


def histogram(samples: dict, thread: str) -> tuple[list[tuple[float, float]], float, float]:
    buckets = sorted((float(dict(labels)["le"]), value) for (name, labels), value in samples.items()
                     if name == "tickTime_bucket" and dict(labels)["name"] == thread)
    count = samples[("tickTime_count", (("name", thread),))]
    total = samples[("tickTime_sum", (("name", thread),))]
    return buckets, count, total


def share_above(samples: dict, thread: str, bound: float) -> float:
    buckets, count, _ = histogram(samples, thread)
    at_or_below = next(value for le, value in buckets if le == bound)
    return (count - at_or_below) / count


class TickSimulationTest(unittest.TestCase):
    def make(self, main_tick_ms: float = 4.0, seed: int = 7) -> tuple[object, FakeClock]:
        clock = FakeClock()
        return fake.TickSimulation(main_tick_ms, seed, clock), clock

    def test_threads_tick_at_their_timer_rate(self):
        sim, clock = self.make()
        clock.advance(10)
        samples = parse_exposition(sim.exposition())
        counts = {t: histogram(samples, t)[1] for t in fake.THREAD_INTERVAL_MS}
        # One tick at time 0, then one per interval: 20, 100 and 125 per second.
        self.assertEqual(counts, {"svMain": 201, "svNetwork": 1001, "svSync": 1251})

    def test_histogram_is_cumulative_and_ends_with_the_count(self):
        sim, clock = self.make()
        clock.advance(30)
        samples = parse_exposition(sim.exposition())
        for thread in fake.THREAD_INTERVAL_MS:
            buckets, count, total = histogram(samples, thread)
            with self.subTest(thread=thread):
                self.assertEqual([le for le, _ in buckets], [*fake.BUCKETS, math.inf])
                values = [v for _, v in buckets]
                self.assertEqual(values, sorted(values))
                self.assertEqual(values[-1], count)
                # The server measures in whole milliseconds, so the sum is a multiple of 0.001.
                self.assertAlmostEqual(total * 1000, round(total * 1000), places=6)

    def test_exposition_uses_the_server_names_and_one_extra_metric(self):
        sim, clock = self.make()
        clock.advance(1)
        text = sim.exposition()
        self.assertIn("# HELP tickTime Time spent on server ticks\n# TYPE tickTime histogram\n", text)
        names = {name for name, _ in parse_exposition(text)}
        self.assertEqual(names, {"tickTime_bucket", "tickTime_sum", "tickTime_count", "fake_unlisted_metric"})
        self.assertIn('tickTime_bucket{name="svMain",le="+Inf"}', text)
        self.assertIn('tickTime_bucket{name="svSync",le="0.07"}', text)

    def test_default_load_stays_fast(self):
        sim, clock = self.make()
        clock.advance(60)
        samples = parse_exposition(sim.exposition())
        self.assertEqual(share_above(samples, "svMain", 0.008), 0.0)

    def test_load_knob_slows_svmain_only(self):
        sim, clock = self.make()
        clock.advance(10)
        before = parse_exposition(sim.exposition())
        sim.set_main_tick_ms(90, None)
        clock.advance(60)
        after = parse_exposition(sim.exposition())
        main_new = histogram(after, "svMain")[1] - histogram(before, "svMain")[1]
        slow_new = (main_new - (next(v for le, v in histogram(after, "svMain")[0] if le == 0.05)
                                - next(v for le, v in histogram(before, "svMain")[0] if le == 0.05)))
        self.assertGreater(slow_new / main_new, 0.6)  # most ticks now take more than 50 ms
        # Ticks longer than the 50 ms interval also make the thread tick less often.
        self.assertLess(main_new, 60 * 20 * 0.7)
        for thread in ("svNetwork", "svSync"):
            with self.subTest(thread=thread):
                self.assertEqual(share_above(after, thread, 0.008), 0.0)

    def test_temporary_spike_returns_to_the_previous_load(self):
        sim, clock = self.make()
        sim.set_main_tick_ms(120, for_seconds=30)
        self.assertEqual(sim.current_main_tick_ms(), 120)
        self.assertEqual(sim.spike_seconds_left(), 30)
        clock.advance(31)
        self.assertEqual(sim.current_main_tick_ms(), 4.0)
        self.assertEqual(sim.spike_seconds_left(), 0)
        sim.advance()
        samples = parse_exposition(sim.exposition())
        self.assertGreater(share_above(samples, "svMain", 0.05), 0.5)  # the spike is in the history
        count_after_spike = histogram(samples, "svMain")[1]
        clock.advance(60)
        later = parse_exposition(sim.exposition())
        new = histogram(later, "svMain")[1] - count_after_spike
        self.assertEqual(new, 60 * 20)  # back at full rate

    def test_restart_resets_the_counters(self):
        sim, clock = self.make()
        clock.advance(20)
        sim.advance()
        sim.restart()
        samples = parse_exposition(sim.exposition())
        self.assertEqual({t: histogram(samples, t)[1] for t in fake.THREAD_INTERVAL_MS},
                         {"svMain": 0, "svNetwork": 0, "svSync": 0})
        clock.advance(1)
        samples = parse_exposition(sim.exposition())
        self.assertEqual(histogram(samples, "svMain")[1], 20)

    def test_long_pause_is_capped(self):
        sim, clock = self.make()
        clock.advance(7200)
        samples = parse_exposition(sim.exposition())
        self.assertEqual(histogram(samples, "svMain")[1], fake.MAX_STEP_SECONDS * 20 + 1)

    def test_same_seed_gives_the_same_ticks(self):
        first, clock1 = self.make(seed=42)
        second, clock2 = self.make(seed=42)
        clock1.advance(15)
        clock2.advance(15)
        self.assertEqual(first.exposition(), second.exposition())

    def test_tick_time_limits(self):
        for bad in (-1, fake.MAX_TICK_MS + 1, "5", True, None):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                fake.check_tick_ms(bad)
        self.assertEqual(fake.check_tick_ms(0), 0.0)


class Server:
    """The fake server on a free loopback port, for one test."""

    def __init__(self, test: unittest.TestCase, **config):
        self.clock = FakeClock()
        self.state = fake.FakeServerState(fake.FakeConfig(seed=1, **config), clock=self.clock)
        self.httpd = fake.make_server(self.state, "127.0.0.1", 0, quiet=True)
        self.port = self.httpd.server_address[1]
        thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        test.addCleanup(self.close, thread)

    def close(self, thread: threading.Thread) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        thread.join(5)

    def request(self, method: str, path: str, body: bytes | None = None,
                headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
        finally:
            conn.close()

    def get_json(self, path: str) -> object:
        status, headers, body = self.request("GET", path)
        assert status == 200, (status, body)
        assert headers["content-type"] == "application/json"
        return json.loads(body)

    def control(self, data: object) -> tuple[int, dict]:
        status, _, body = self.request("POST", "/fake/control", json.dumps(data).encode(),
                                       {"Content-Type": "application/json"})
        return status, json.loads(body)


def basic(user: str, password: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


class EndpointTest(unittest.TestCase):
    def test_info_json(self):
        server = Server(self, build=35245, max_clients=48)
        info = server.get_json("/info.json")
        self.assertEqual(info["server"], "FXServer-master v1.0.0.35245 linux")
        self.assertIs(info["enhancedHostSupport"], True)
        self.assertEqual(info["resources"][0], "hardcap")
        self.assertEqual(info["vars"]["sv_maxClients"], "48")
        self.assertEqual(info["vars"]["onesync_enabled"], "true")
        self.assertTrue(all(isinstance(v, str) for v in info["vars"].values()))
        self.assertIsInstance(info["version"], int)
        self.assertNotIn("sv_hostname", info["vars"])  # the server leaves it out of vars

    def test_dynamic_json(self):
        server = Server(self, clients=5, max_clients=48)
        dynamic = server.get_json("/dynamic.json")
        self.assertEqual(dynamic["clients"], 5)
        self.assertEqual(dynamic["sv_maxclients"], "48")  # a string, as the server sends it
        self.assertEqual(set(dynamic), {"clients", "gametype", "hostname", "iv", "mapname", "sv_maxclients"})

    def test_players_json_is_anonymous_and_counted(self):
        server = Server(self, clients=4)
        players = server.get_json("/players.json")
        self.assertEqual(len(players), 4)
        for player in players:
            self.assertEqual(player, {"endpoint": "127.0.0.1", "id": 0, "identifiers": [], "name": "Player", "ping": 0})
        self.assertEqual(server.state.state()["requests"]["/players.json"], 1)

    def test_perf_needs_the_exact_credentials(self):
        password = secrets.token_urlsafe(16)
        server = Server(self, perf_user="prometheus", perf_password=password)
        for headers in ({}, basic("prometheus", "wrong"), basic("other", password),
                        {"Authorization": "Bearer " + password}):
            with self.subTest(headers=sorted(headers)):
                status, resp_headers, body = server.request("GET", "/perf/", headers=headers)
                self.assertEqual((status, body), (401, b"Unauthorized."))
                self.assertNotIn("www-authenticate", resp_headers)  # the server sends no challenge
        status, headers, body = server.request("GET", "/perf/", headers=basic("prometheus", password))
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "text/plain")
        self.assertIn(b"tickTime_count", body)
        self.assertEqual(server.request("GET", "/perf", headers=basic("prometheus", password))[0], 200)
        state = server.state.state()
        self.assertEqual((state["requests"]["/perf/"], state["perf_refused"], state["perf_auth"]), (6, 4, True))

    def test_perf_is_open_without_user_and_password(self):
        server = Server(self)
        status, _, body = server.request("GET", "/perf/")
        self.assertEqual(status, 200)
        parse_exposition(body.decode())

    def test_a_user_without_password_still_needs_credentials(self):
        server = Server(self, perf_user="prometheus")
        self.assertEqual(server.request("GET", "/perf/")[0], 401)
        self.assertEqual(server.request("GET", "/perf/", headers=basic("prometheus", ""))[0], 200)

    def test_request_paranoia(self):
        cases = [  # (level, header, refused)
            (0, {"Via": "1.1 proxy"}, False),
            (1, {"Via": "1.1 proxy"}, True),
            (1, {"Upgrade-Insecure-Requests": "1"}, False),
            (2, {"Upgrade-Insecure-Requests": "1"}, True),
            (3, {}, False),
        ]
        for level, headers, refused in cases:
            server = Server(self, request_paranoia=level)
            for path in ("/info.json", "/dynamic.json", "/players.json"):
                with self.subTest(level=level, headers=sorted(headers), path=path):
                    status, _, body = server.request("GET", path, headers=headers)
                    if refused:
                        self.assertEqual((status, body), (403, b"Nope."))
                    else:
                        self.assertEqual(status, 200)

    def test_head_and_unknown_paths(self):
        server = Server(self)
        status, headers, body = server.request("HEAD", "/dynamic.json")
        self.assertEqual((status, body), (200, b""))
        self.assertGreater(int(headers["content-length"]), 0)
        self.assertEqual(server.request("GET", "/nothing-here")[0], 404)
        self.assertEqual(server.request("POST", "/info.json", b"{}")[0], 404)
        self.assertEqual(server.state.state()["requests"]["other"], 1)


class ControlTest(unittest.TestCase):
    def test_load_knob_and_clients(self):
        server = Server(self, clients=3)
        status, state = server.control({"main_tick_ms": 90, "for_seconds": 120})
        self.assertEqual(status, 200)
        self.assertEqual((state["main_tick_ms"], state["spike_seconds_left"]), (90.0, 120.0))
        server.clock.advance(121)
        self.assertEqual(server.get_json("/fake/state")["main_tick_ms"], 4.0)
        status, state = server.control({"main_tick_ms": 75})
        self.assertEqual((status, state["main_tick_ms"], state["spike_seconds_left"]), (200, 75.0, 0.0))
        status, state = server.control({"clients": 0})
        self.assertEqual((status, state["clients"]), (200, 0))
        self.assertEqual(server.get_json("/dynamic.json")["clients"], 0)
        self.assertEqual(server.get_json("/players.json"), [])

    def test_restart(self):
        server = Server(self)
        server.clock.advance(10)
        status, _ = server.control({"restart": True})
        self.assertEqual(status, 200)
        samples = parse_exposition(server.request("GET", "/perf/")[2].decode())
        self.assertEqual(histogram(samples, "svMain")[1], 0)

    def test_bad_requests_change_nothing(self):
        server = Server(self, clients=3, max_clients=32)
        for body in ({}, [], {"clients": 33}, {"clients": -1}, {"clients": True}, {"clients": 2.5},
                     {"main_tick_ms": "fast"}, {"main_tick_ms": -5}, {"for_seconds": 10},
                     {"main_tick_ms": 90, "for_seconds": 0}, {"restart": "yes"}, {"players": 1},
                     {"clients": 2, "main_tick_ms": "x"}):
            with self.subTest(body=body):
                status, reply = server.control(body)
                self.assertEqual(status, 400)
                self.assertIn("error", reply)
        state = server.get_json("/fake/state")
        self.assertEqual((state["clients"], state["main_tick_ms"]), (3, 4.0))
        status, _, body = server.request("POST", "/fake/control", b"not json")
        self.assertEqual(status, 400)
        status, _, body = server.request("POST", "/fake/control", b"")
        self.assertEqual(status, 400)

    def test_control_can_be_turned_off(self):
        server = Server(self, control=False)
        self.assertEqual(server.request("GET", "/fake/state")[0], 404)
        self.assertEqual(server.request("POST", "/fake/control", b'{"clients": 0}')[0], 404)
        self.assertEqual(server.state.clients, 3)


class CommandLineTest(unittest.TestCase):
    def test_settings_from_the_environment_and_the_password_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            pw_file = Path(tmp) / "pw"
            pw_file.write_text("from-file\n", encoding="utf-8")
            env = {"FAKE_PORT": "31999", "FAKE_CLIENTS": "7", "FAKE_MAX_CLIENTS": "64", "FAKE_BUILD": "40000",
                   "FAKE_MAIN_TICK_MS": "80", "FAKE_REQUEST_PARANOIA": "2", "FAKE_SEED": "3",
                   "FAKE_PERF_USER": "prom", "FAKE_PERF_PASSWORD": "from-env"}
            with mock.patch.dict(os.environ, env):
                args = fake.parse_args([])
                config = fake.config_from_args(args)
                self.assertEqual((args.port, config.clients, config.max_clients, config.build),
                                 (31999, 7, 64, 40000))
                self.assertEqual((config.main_tick_ms, config.request_paranoia, config.seed), (80.0, 2, 3))
                self.assertEqual((config.perf_user, config.perf_password), ("prom", "from-env"))
                config = fake.config_from_args(fake.parse_args(["--perf-password-file", str(pw_file)]))
                self.assertEqual(config.perf_password, "from-file")
        self.assertIsNone(fake.config_from_args(fake.parse_args(["--seed", "-1"])).seed)
        self.assertFalse(fake.config_from_args(fake.parse_args(["--no-control"])).control)

    def test_invalid_settings_exit_with_2(self):
        for argv in (["--clients", "40", "--max-clients", "32"], ["--max-clients", "0"],
                     ["--main-tick-ms", "-1"], ["--perf-password-file", "/nonexistent/pw"]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(fake.main(argv), 2)
                self.assertIn("fake-fxserver:", err.getvalue())

    def test_the_password_is_not_a_command_line_option(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            fake.parse_args(["--perf-password", "x"])


if __name__ == "__main__":
    unittest.main()
