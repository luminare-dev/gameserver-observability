"""Tests for the demo stack (demo/docker-compose.yml) and its smoke test (scripts/smoke_demo.py).

The CI job demo-smoke starts the stack and checks it through the APIs. These tests check without
Docker what that run cannot see, or would only see by failing late:

- every image is pinned by digest, at the versions CI tests and docs/toolchain.md lists;
- only Prometheus, the owner of the one network namespace, publishes ports, and only on
  127.0.0.1; the exporters listen on 127.0.0.1 inside it;
- the pack's files are mounted unchanged at the paths of docs/install.md, the demo's main
  Prometheus config (prometheus/prometheus.demo.yml) is the one of the installation guide, and
  both the simulated server and Prometheus read the same /perf/ password;
- every dashboard of grafana/dashboards/ is mounted where the provisioning file looks for it;
- Grafana has no account and lets visitors in as viewers only;
- the smoke test expects the targets, probes and dashboard of the repository's files, and the
  CI job runs it;
- every picture under docs/media/ that a Markdown file shows is labelled as synthetic data.

The YAML tests need PyYAML (requirements-test.txt); scripts/test.sh installs it, and a bare
`python3 -m unittest` without it skips them.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # scripts/test.sh installs it
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo"
sys.path.insert(0, str(ROOT / "scripts"))

import lint_dashboards  # noqa: E402
import smoke_demo  # noqa: E402
import smoke_exporters  # noqa: E402

NEEDS_YAML = unittest.skipIf(yaml is None, "PyYAML is not installed (bash scripts/test.sh installs it)")
OWNER = "prometheus"  # the service that owns the network namespace and publishes the ports
IMAGE_RE = re.compile(r"^(?P<name>[a-z0-9][a-z0-9./-]*):(?P<tag>[\w.-]+)@sha256:[0-9a-f]{64}$")
LABEL = "synthetic data from the bundled simulated server"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def mounts(service: dict) -> dict[str, Path]:
    """Container path -> source path (resolved from demo/) of a service's bind mounts."""
    out: dict[str, Path] = {}
    for volume in service.get("volumes", []):
        if isinstance(volume, str):
            source, target = volume.split(":")[:2]
        else:
            source, target = volume["source"], volume["target"]
        out[target] = (DEMO / source).resolve()
    return out


def flag(service: dict, name: str) -> str | None:
    """The value of a --name=value argument in a service's command."""
    values = [arg.split("=", 1)[1] for arg in service.get("command", []) if arg.startswith(f"--{name}=")]
    return values[0] if len(values) == 1 else None


@NEEDS_YAML
class DemoComposeTest(unittest.TestCase):
    def setUp(self):
        self.compose = load_yaml(DEMO / "docker-compose.yml")
        self.services = self.compose["services"]
        self.ci_env = load_yaml(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]["exporters"]["env"]

    def test_every_image_is_pinned_by_digest_and_listed_on_the_toolchain_page(self):
        toolchain = (ROOT / "docs" / "toolchain.md").read_text(encoding="utf-8")
        for name, service in self.services.items():
            with self.subTest(service=name):
                self.assertRegex(service["image"], IMAGE_RE)
                self.assertNotIn("build", service)
                self.assertIn(f"`{service['image']}`", toolchain)

    def test_images_are_the_versions_ci_tests(self):
        matches = [IMAGE_RE.match(service["image"]) for service in self.services.values()]
        tags = {match["name"]: match["tag"] for match in matches}
        self.assertEqual(tags["prom/prometheus"], f"v{self.ci_env['PROMETHEUS_VERSION']}")
        self.assertEqual(tags["quay.io/prometheuscommunity/json-exporter"], f"v{self.ci_env['JSON_EXPORTER_VERSION']}")
        self.assertEqual(tags["prom/blackbox-exporter"], f"v{self.ci_env['BLACKBOX_EXPORTER_VERSION']}")
        self.assertEqual(tags["grafana/grafana"], lint_dashboards.GRAFANA_VERSION)
        self.assertRegex(tags["python"], r"^3\.(1[0-9])-slim$")  # the fake server needs Python 3.10 or newer

    def test_only_the_namespace_owner_publishes_ports_and_only_on_loopback(self):
        variables = []
        for name, service in self.services.items():
            with self.subTest(service=name):
                if name == OWNER:
                    self.assertNotIn("network_mode", service)
                    for port in service["ports"]:
                        match = re.fullmatch(r"127\.0\.0\.1:\$\{(\w+):-(\d+)\}:(\d+)", port)
                        self.assertIsNotNone(match, port)
                        self.assertEqual(match[2], match[3], "the default host port is the container port")
                        variables.append(match[1])
                else:
                    self.assertEqual(service.get("network_mode"), f"service:{OWNER}")
                    self.assertNotIn("ports", service)
        self.assertEqual(sorted(variables), sorted(smoke_demo.PORT_VARIABLES))
        self.assertNotIn("networks", self.compose)

    def test_exporters_listen_on_loopback_where_the_scrape_jobs_expect_them(self):
        scrape = (ROOT / "prometheus" / "scrape" / "fxserver.yml").read_text(encoding="utf-8")
        for name, port in (("json-exporter", 7979), ("blackbox-exporter", 9115)):
            with self.subTest(service=name):
                self.assertEqual(flag(self.services[name], "web.listen-address"), f"127.0.0.1:{port}")
                self.assertIn(f"replacement: 127.0.0.1:{port}", scrape)

    def test_the_packs_files_are_mounted_at_the_install_paths(self):
        expected = {
            OWNER: {
                "/etc/prometheus/prometheus.yml": ROOT / "prometheus" / "prometheus.demo.yml",
                "/etc/prometheus/scrape/fxserver.yml": ROOT / "prometheus" / "scrape" / "fxserver.yml",
                "/etc/prometheus/rules": ROOT / "rules",
            },
            "json-exporter": {"/etc/json_exporter/config.yml": ROOT / "json_exporter" / "config.yml"},
            "blackbox-exporter": {"/etc/blackbox_exporter/blackbox.yml": ROOT / "blackbox" / "blackbox.yml"},
            "fxserver": {"/opt/fake-fxserver/fake_fxserver.py": ROOT / "demo" / "fake-fxserver" / "fake_fxserver.py"},
        }
        for name, files in expected.items():
            with self.subTest(service=name):
                self.assertEqual(mounts(self.services[name]), {k: v.resolve() for k, v in files.items()})
        install = (ROOT / "docs" / "install.md").read_text(encoding="utf-8")
        for target in ("/etc/prometheus/scrape/fxserver.yml", "/etc/prometheus/rules", "/etc/json_exporter/config.yml",
                       "/etc/blackbox_exporter/blackbox.yml"):
            with self.subTest(path=target):
                self.assertIn(target, install)
        self.assertEqual(flag(self.services["json-exporter"], "config.file"), "/etc/json_exporter/config.yml")
        self.assertEqual(flag(self.services["blackbox-exporter"], "config.file"), "/etc/blackbox_exporter/blackbox.yml")
        self.assertEqual(flag(self.services[OWNER], "config.file"), "/etc/prometheus/prometheus.yml")
        for service in self.services.values():
            for target in mounts(service):
                self.assertTrue(mounts(service)[target].exists(), target)

    def test_the_main_prometheus_config_is_the_one_of_the_installation_guide(self):
        main = load_yaml(ROOT / "prometheus" / "prometheus.demo.yml")
        self.assertEqual(main, {"scrape_config_files": ["/etc/prometheus/scrape/fxserver.yml"],
                                "rule_files": ["/etc/prometheus/rules/*.yml"]})
        install = (ROOT / "docs" / "install.md").read_text(encoding="utf-8")
        self.assertIn("scrape_config_files:\n  - /etc/prometheus/scrape/fxserver.yml\nrule_files:\n"
                      "  - /etc/prometheus/rules/*.yml\n", install)

    def test_the_simulated_server_and_prometheus_share_the_perf_password(self):
        scrape = load_yaml(ROOT / "prometheus" / "scrape" / "fxserver.yml")
        perf = next(j for j in scrape["scrape_configs"] if j["job_name"] == "fxserver_perf")
        self.assertIn("perf_password", self.compose["configs"])
        targets = {}
        for name in (OWNER, "fxserver"):
            configs = self.services[name]["configs"]
            self.assertEqual([c["source"] for c in configs], ["perf_password"])
            targets[name] = configs[0]["target"]
        self.assertEqual(targets[OWNER], perf["basic_auth"]["password_file"])
        self.assertEqual(flag(self.services["fxserver"], "perf-password-file"), targets["fxserver"])
        self.assertEqual(flag(self.services["fxserver"], "perf-user"), perf["basic_auth"]["username"])

    def test_every_dashboard_is_mounted_where_the_provider_reads(self):
        provider = load_yaml(ROOT / "grafana" / "provisioning" / "dashboards" / "gameserver-observability.yml")
        folder = provider["providers"][0]["options"]["path"]
        grafana = mounts(self.services["grafana"])
        dashboards = {t: s for t, s in grafana.items() if t.endswith(".json")}
        expected = {f"{folder}/{p.name}": p.resolve()
                    for p in (ROOT / "grafana" / "dashboards").glob("*.json")}  # not shareable/
        self.assertEqual(dashboards, expected)
        for kind in ("datasources", "dashboards"):
            name = f"/etc/grafana/provisioning/{kind}/gameserver-observability.yml"
            self.assertEqual(grafana[name], (ROOT / "grafana" / "provisioning" / kind / "gameserver-observability.yml"))
        home = self.services["grafana"]["environment"]["GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH"]
        self.assertIn(home, dashboards)

    def test_grafana_has_no_account_and_only_viewers(self):
        env = self.services["grafana"]["environment"]
        self.assertEqual(env["GF_SECURITY_DISABLE_INITIAL_ADMIN_CREATION"], "true")
        self.assertEqual(env["GF_AUTH_ANONYMOUS_ENABLED"], "true")
        self.assertEqual(env["GF_AUTH_ANONYMOUS_ORG_ROLE"], "Viewer")
        self.assertEqual(env["GF_AUTH_DISABLE_LOGIN_FORM"], "true")
        self.assertEqual(env["GF_AUTH_BASIC_ENABLED"], "false")
        self.assertNotIn("GF_SECURITY_ADMIN_PASSWORD", env)

    def test_containers_without_their_own_user_run_as_nobody(self):
        # The Prometheus, json_exporter and Grafana images set a user of their own.
        for name in ("fxserver", "blackbox-exporter"):
            with self.subTest(service=name):
                self.assertEqual(self.services[name].get("user"), "65534:65534")


@NEEDS_YAML
class SmokeDemoTest(unittest.TestCase):
    def test_it_expects_every_target_and_probe_of_the_scrape_config(self):
        targets = smoke_demo.expected_targets()
        self.assertEqual(set(targets), {"fxserver_perf", "fxserver_json", "fxserver_blackbox"})
        self.assertEqual(sum(targets.values()), smoke_exporters.DEFAULT_JOB_TARGETS)
        blackbox = load_yaml(ROOT / "blackbox" / "blackbox.yml")["modules"]
        self.assertEqual(smoke_demo.probe_modules(), {"tcp_connect", "http_fxserver_info", "http_401_expected"})
        self.assertLessEqual(smoke_demo.probe_modules(), set(blackbox))

    def test_it_expects_the_dashboard_and_data_source_of_the_repository(self):
        expect = smoke_demo.grafana_expectations()
        self.assertEqual(expect["uid"], "gso-game-server-overview")
        self.assertEqual(expect["title"], "Game server overview")
        self.assertEqual(expect["folder"], "Game server")
        self.assertEqual(expect["datasource"], "gso-prometheus")
        self.assertGreater(expect["panels"], 0)
        self.assertEqual(smoke_demo.rule_files(), {p.name for p in (ROOT / "rules").glob("*.y*ml")})

    def test_the_ci_job_runs_it(self):
        job = load_yaml(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]["demo-smoke"]
        self.assertEqual(job["runs-on"], "ubuntu-24.04")
        self.assertEqual(job["permissions"], {"contents": "read"})
        self.assertLessEqual(job["timeout-minutes"], 20)
        self.assertIn("python3 scripts/smoke_demo.py", [step.get("run") for step in job["steps"]])


class DemoMediaTest(unittest.TestCase):
    def test_every_shown_picture_of_the_demo_is_labelled_as_synthetic(self):
        media = sorted(p.name for p in (ROOT / "docs" / "media").glob("*") if p.suffix in (".png", ".gif"))
        self.assertIn("dashboard.png", media)
        shown: set[str] = set()
        for md in [ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]:
            text = md.read_text(encoding="utf-8")
            for alt, target in re.findall(r"!\[([^\]]*)\]\(([^)\s]*media/[^)\s]+)\)", text):
                with self.subTest(file=md.relative_to(ROOT).as_posix(), image=target):
                    self.assertIn(LABEL, alt.lower())
                    self.assertTrue((md.parent / target).resolve().is_file(), target)
                    shown.add(Path(target).name)
        self.assertEqual(shown, set(media), "every picture in docs/media/ is shown, and labelled, somewhere")


if __name__ == "__main__":
    unittest.main()
