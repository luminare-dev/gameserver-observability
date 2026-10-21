"""Tests for scripts/check_pack.py: the YAML subset reader and the pack's config checks.

The checker runs on copies of the repository's config files in a temporary folder, each test
changing one thing that must be reported. The comparison with PyYAML needs PyYAML
(requirements-test.txt); scripts/test.sh installs it and sets PACK_TESTS_STRICT=1, so it cannot
be skipped there. The promtool tests run when promtool is on the PATH.
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_pack as cp  # noqa: E402

try:
    import yaml
except ImportError:  # scripts/test.sh installs it
    yaml = None

CONFIG_DIRS = ("prometheus", "json_exporter", "blackbox")
SCRAPE = "prometheus/scrape/fxserver.yml"
TUNNEL = "prometheus/scrape/tunnel.yml"
JSON_CONFIG = "json_exporter/config.yml"
BLACKBOX = "blackbox/blackbox.yml"


def config_files() -> list[Path]:
    return sorted(p for d in CONFIG_DIRS for p in (ROOT / d).rglob("*") if p.suffix in (".yml", ".yaml"))


class ReaderTest(unittest.TestCase):
    def test_block_and_flow_collections(self):
        text = (
            "# comment\n"
            "a: 1\n"
            "b:\n"
            "  - x\n"
            "  - key: value  # trailing comment\n"
            "    other: [1, 'two', \"three\", {k: v}]\n"
            "  -\n"
            "    - nested\n"
            "c:\n"
            "- indentless\n"
            "d: {}\n"
            "e: []\n"
            "f:\n"
            "g: 'it''s'\n"
            "h: \"tab\\tquote\\\"\"\n"
            "i: a#b\n"
            "j: http://127.0.0.1:30120/info.json\n"
            "k: '{ .clients }'\n"
            "'quoted key': 2.5\n"
        )
        self.assertEqual(cp.load_yaml(text), {
            "a": 1,
            "b": ["x", {"key": "value", "other": [1, "two", "three", {"k": "v"}]}, ["nested"]],
            "c": ["indentless"],
            "d": {}, "e": [], "f": None,
            "g": "it's", "h": 'tab\tquote"', "i": "a#b",
            "j": "http://127.0.0.1:30120/info.json",
            "k": "{ .clients }",
            "quoted key": 2.5,
        })

    def test_scalar_types(self):
        cases = {"true": True, "False": False, "null": None, "~": None, "0": 0, "-7": -7, "+3": 3,
                 "1.5": 1.5, "1.": 1.0, ".5": 0.5, "15s": "15s", "1.0.0": "1.0.0", "v1": "v1", "2xx": "2xx"}
        for token, expected in cases.items():
            with self.subTest(token=token):
                value = cp.load_yaml(f"v: {token}\n")["v"]
                self.assertEqual(value, expected)
                self.assertIs(type(value), type(expected))

    def test_unsupported_or_ambiguous_yaml_is_refused(self):
        cases = {
            "yes/no booleans": "a: yes\n",
            "on as key": "on: push\n",
            "octal-looking number": "a: 0755\n",
            "sexagesimal number": "a: 1:30\n",
            "date": "a: 2026-10-21\n",
            "exponent without a dot": "a: 1e3\n",
            "exponent float": "a: 1.5e3\n",
            "one-letter boolean key": "y: 1\n",
            "value ending in a colon": "a: ends with colon:\n",
            "signed dot float": "a: -.5\n",
            "infinity": "a: .inf\n",
            "anchor": "a: &x 1\n",
            "alias": "a: *x\n",
            "tag": "a: !!str 1\n",
            "block scalar": "a: |\n  text\n",
            "folded scalar": "a: >\n  text\n",
            "multi-line plain scalar": "a: one\n  two\n",
            "multi-line flow sequence": "a: [1,\n  2]\n",
            "unclosed quote": "a: 'open\n",
            "colon in a flow plain scalar": "a: [127.0.0.1:30120]\n",
            "colon-space in a value": "a: b: c\n",
            "duplicate key": "a: 1\na: 2\n",
            "duplicate flow key": "a: {b: 1, b: 2}\n",
            "tab indentation": "a:\n\t- 1\n",
            "second document": "a: 1\n---\nb: 2\n",
            "directive": "%YAML 1.1\na: 1\n",
            "complex key": "? a\n: 1\n",
            "bad escape": 'a: "\\q"\n',
            "merge key": "<<: 1\n",
        }
        for label, text in cases.items():
            with self.subTest(label), self.assertRaisesRegex(cp.YamlError, r"^line \d+: "):
                cp.load_yaml(text)

    def test_error_names_the_line(self):
        with self.assertRaises(cp.YamlError) as ctx:
            cp.load_yaml("a: 1\nb:\n  c: yes\n")
        self.assertEqual(ctx.exception.line, 3)

    def test_leading_document_marker_and_empty_input(self):
        self.assertEqual(cp.load_yaml("---\na: 1\n"), {"a": 1})
        self.assertIsNone(cp.load_yaml("# only a comment\n\n"))


@unittest.skipIf(yaml is None and os.environ.get("PACK_TESTS_STRICT") != "1", "PyYAML is not installed")
class ReaderMatchesPyYamlTest(unittest.TestCase):
    def test_every_config_file_reads_like_pyyaml(self):
        self.assertIsNotNone(yaml, "PyYAML is missing although PACK_TESTS_STRICT=1")
        files = config_files()
        self.assertGreaterEqual(len(files), 4)
        for path in files:
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.relative_to(ROOT).as_posix()):
                mine, ref = cp.load_yaml(text), yaml.safe_load(text)
                self.assertEqual(mine, ref)
                self.assertEqual(repr(mine), repr(ref))  # same types too (1 vs 1.0 vs True)

    def test_supported_samples_read_like_pyyaml(self):
        samples = [
            "a: [1, 2.5, 'x', \"y\", {b: c}, []]\n",
            "- a: 1\n  b:\n    - c\n    - d: e\n- f\n",
            "x:\n- 1\n- 2\nz: 3\n",
            "s: 'single ''quoted'' # not a comment'\nt: \"\\u00e9\\x41\"\n",
            "u: plain with spaces and #hash\nv: 'ends with colon:'\n",
            "w: 127.0.0.1:7979\nz: '[not a list]'\n",
        ]
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(repr(cp.load_yaml(text)), repr(yaml.safe_load(text)))


class CheckerTest(unittest.TestCase):
    """Run the checker on a copy of the repository's configs, changed by each test."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="gso-check-pack-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for name in CONFIG_DIRS:
            shutil.copytree(ROOT / name, self.root / name)
        # No promtool for the checker tests unless a test asks for it.
        patcher = mock.patch.object(cp.shutil, "which", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def edit(self, rel: str, old: str, new: str) -> None:
        path = self.root / rel
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text, f"test fixture out of date: {old!r} not in {rel}")
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def findings(self, require_promtool: bool = False) -> list[cp.Finding]:
        checker = cp.PackChecker(self.root)
        checker.run(require_promtool=require_promtool)
        return checker.findings

    def assert_finding(self, check: str, text: str) -> None:
        found = self.findings()
        self.assertTrue(any(f.check == check and text in f.message for f in found),
                        f"no [{check}] finding containing {text!r}; got: {[str(f) for f in found]}")

    def test_the_copies_are_clean(self):
        self.assertEqual(self.findings(), [])

    def test_players_json_target(self):
        self.edit(SCRAPE, "http://127.0.0.1:30120/dynamic.json", "http://127.0.0.1:30120/players.json")
        self.assert_finding("players", "players.json")

    def test_players_json_in_an_exporter_module(self):
        self.edit(JSON_CONFIG, "help: Connected clients (dynamic.json clients)", "help: Clients (from /PLAYERS.JSON)")
        self.assert_finding("players", "players.json")

    def test_player_label_in_a_static_config(self):
        self.edit(SCRAPE, "          server: game-01\n          module: fxserver_dynamic",
                  "          server: game-01\n          player_name: x\n          module: fxserver_dynamic")
        self.assert_finding("labels", "'player_name' could identify a player")

    def test_player_label_from_a_relabel_rule(self):
        self.edit(SCRAPE, "target_label: thread", "target_label: identifier")
        self.assert_finding("labels", "'identifier' could identify a player")

    def test_player_label_in_a_json_exporter_metric(self):
        self.edit(JSON_CONFIG, "          version: '{ .server }'",
                  "          version: '{ .server }'\n          ip: '{ .x }'")
        self.assert_finding("labels", "'ip' could identify a player")

    def test_player_label_in_a_blackbox_query_response(self):
        self.edit(BLACKBOX, "  tcp_connect:\n    prober: tcp\n",
                  "  tcp_connect:\n    prober: tcp\n    tcp:\n      query_response:\n"
                  "        - expect: '^(.*)$'\n          labels:\n"
                  "            - name: license\n              value: '$1'\n")
        self.assert_finding("labels", "'license' could identify a player")

    def test_labelmap_and_honor_labels(self):
        self.edit(SCRAPE, "      - regex: name\n        action: labeldrop\n",
                  "      - regex: name\n        action: labeldrop\n      - regex: (.+)\n        action: labelmap\n")
        self.edit(SCRAPE, "    scrape_interval: 15s\n", "    scrape_interval: 15s\n    honor_labels: true\n")
        found = [str(f) for f in self.findings()]
        self.assertTrue(any("labelmap" in f for f in found), found)
        self.assertTrue(any("honor_labels" in f for f in found), found)

    def test_perf_job_must_drop_the_name_label(self):
        self.edit(SCRAPE, "      - regex: name\n        action: labeldrop\n", "")
        self.assert_finding("perf", "name label must be dropped")

    def test_perf_job_must_keep_only_listed_metrics(self):
        self.edit(SCRAPE, "        regex: tickTime_(bucket|sum|count)\n        action: keep\n",
                  "        regex: tickTime_(bucket|sum|count)\n        action: drop\n")
        self.assert_finding("perf", "keep rule on __name__")

    def test_perf_job_must_copy_name_to_thread(self):
        self.edit(SCRAPE, "      - source_labels: [name]\n        target_label: thread\n", "")
        self.assert_finding("perf", "copy the name label to thread")

    def test_perf_job_must_copy_name_before_dropping_it(self):
        copy = "      - source_labels: [name]\n        target_label: thread\n"
        drop = "      - regex: name\n        action: labeldrop\n"
        self.edit(SCRAPE, copy + drop, drop + copy)
        self.assert_finding("perf", "must come before the rule that drops name")

    def test_perf_job_must_copy_name_before_a_labelkeep_without_it(self):
        copy = "      - source_labels: [name]\n        target_label: thread\n"
        keep = "      - regex: __name__|job|instance|server|thread|le\n        action: labelkeep\n"
        self.edit(SCRAPE, "      - regex: name\n        action: labeldrop\n", keep)
        self.assertEqual([str(f) for f in self.findings() if f.check == "perf"], [])
        self.edit(SCRAPE, copy + keep, keep + copy)
        self.assert_finding("perf", "must come before the rule that drops name")

    def test_perf_job_needs_a_password_file(self):
        self.edit(SCRAPE, "      password_file: /etc/prometheus/secrets/fxserver_perf",
                  "      password: inline-value")
        found = [str(f) for f in self.findings()]
        self.assertTrue(any("[secrets]" in f and "inline" in f for f in found), found)
        self.assertTrue(any("[secrets]" in f and "password_file" in f for f in found), found)

    def test_secret_header_in_json_exporter(self):
        self.edit(JSON_CONFIG, "  fxserver_dynamic:\n",
                  "  fxserver_dynamic:\n    headers:\n      x-txadmin-envtoken: abc\n")
        self.assert_finding("secrets", "x-txadmin-envtoken")

    def test_secret_header_in_a_blackbox_module(self):
        self.edit(BLACKBOX, "      valid_status_codes: [401]\n",
                  "      valid_status_codes: [401]\n      headers:\n        Authorization: Basic abc\n")
        self.assert_finding("secrets", "modules.http_401_expected.http.headers.Authorization")

    def test_secret_header_in_a_prometheus_job(self):
        self.edit(SCRAPE, "    sample_limit: 100\n",
                  "    sample_limit: 100\n    http_headers:\n      X-Api-Key:\n        values: [abc]\n"
                  "      X-Trace:\n        secrets: [abc]\n")
        found = [str(f) for f in self.findings()]
        self.assertTrue(any("[secrets]" in f and "'X-Api-Key' has an inline value" in f for f in found), found)
        self.assertTrue(any("[secrets]" in f and "X-Trace: secrets are set inline" in f for f in found), found)

    def test_headers_from_files_and_plain_headers_are_fine(self):
        self.edit(SCRAPE, "    sample_limit: 100\n",
                  "    sample_limit: 100\n    http_headers:\n      X-Api-Key:\n"
                  "        files: [/etc/prometheus/secrets/api_key]\n      X-Scraper:\n        values: [prometheus]\n")
        self.edit(BLACKBOX, "      valid_status_codes: [401]\n",
                  "      valid_status_codes: [401]\n      headers:\n        Accept: text/plain\n")
        self.assertEqual(self.findings(), [])

    def test_private_and_wildcard_addresses_unless_any_address_is_allowed(self):
        # Built at run time: the repository holds no private address literal (only loopback and the
        # documentation ranges), but the check must still report one.
        private = ".".join(("172", "16", "0", "1"))
        self.edit(SCRAPE, 'targets: ["127.0.0.1:30120"]', f'targets: ["{private}:30120"]')
        self.edit(SCRAPE, "replacement: 127.0.0.1:9115", "replacement: 0.0.0.0:9115")
        found = [str(f) for f in self.findings()]
        self.assertTrue(any(f"{private} is not loopback" in f for f in found), found)
        self.assertTrue(any("0.0.0.0" in f for f in found), found)
        # A copy with the addresses of real servers: --allow-any-address skips only this check.
        checker = cp.PackChecker(self.root, allow_any_address=True)
        checker.run()
        self.assertEqual(checker.findings, [])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cp.main(["--root", str(self.root), "--allow-any-address"]), 0, out.getvalue())
            self.assertEqual(cp.main(["--root", str(self.root)]), 1, out.getvalue())

    def test_documentation_addresses_are_fine(self):
        self.edit(SCRAPE, 'targets: ["127.0.0.1:30120"]', 'targets: ["192.0.2.10:30120"]')
        self.assertEqual(self.findings(), [])

    def test_unknown_json_exporter_keys(self):
        self.edit(JSON_CONFIG, "        path: '{ .clients }'\n        valuetype: gauge",
                  "        path: '{ .clients }'\n        valueType: gauge")
        self.assert_finding("parse", "unknown key 'valueType'")

    def test_object_metric_needs_values(self):
        self.edit(JSON_CONFIG, "        values:\n          info: 1\n", "")
        self.assert_finding("parse", "an object metric needs values")

    def test_missing_modules(self):
        self.edit(SCRAPE, "module: fxserver_info", "module: fxserver_infos")
        self.edit(SCRAPE, "module: tcp_connect", "module: tcp")
        found = [str(f) for f in self.findings()]
        self.assertTrue(any("'fxserver_infos' is not in the json_exporter config" in f for f in found), found)
        self.assertTrue(any("'tcp' is not in the blackbox config" in f for f in found), found)

    def test_duplicate_job_names_across_files(self):
        self.edit(TUNNEL, "job_name: fxserver_tunnel", "job_name: fxserver_blackbox")
        self.assert_finding("modules", "also defined in prometheus/scrape/fxserver.yml")

    def test_invalid_yaml_is_reported_with_its_line(self):
        self.edit(BLACKBOX, "    prober: tcp\n", "    prober: tcp\n    insecure: yes\n")
        found = [str(f) for f in self.findings()]
        self.assertTrue(any(f.startswith("blackbox/blackbox.yml: [parse] line ") for f in found), found)

    def test_wrong_top_level_shapes(self):
        (self.root / "json_exporter" / "extra.yml").write_text("- a\n", encoding="utf-8")
        (self.root / "blackbox" / "blackbox.yml").write_text("modules:\n  x:\n    prober: smtp\n", encoding="utf-8")
        (self.root / "prometheus" / "scrape" / "empty.yml").write_text("global: {}\n", encoding="utf-8")
        found = [str(f) for f in self.findings()]
        self.assertTrue(any("json_exporter/extra.yml: [parse] the file must hold a mapping" in f for f in found), found)
        self.assertTrue(any("prober must be one of" in f for f in found), found)
        self.assertTrue(any("empty.yml: [parse] scrape_configs must be a non-empty list" in f for f in found), found)

    def test_odd_shapes_are_findings_not_crashes(self):
        (self.root / "prometheus" / "scrape" / "odd.yml").write_text(
            "scrape_configs:\n  - job_name: odd\n    static_configs: {a: 1}\n    params: [x]\n"
            "    relabel_configs: 5\n  - job_name: odd2\n    static_configs:\n      - labels: [x]\n"
            "    metric_relabel_configs: [1, {action: labelmap}]\n", encoding="utf-8")
        (self.root / "json_exporter" / "config.yml").write_text(
            "modules:\n  m:\n    headers: [x]\n    metrics:\n      - name: a\n        path: '{ .a }'\n"
            "        labels: [x]\n      - 5\n", encoding="utf-8")
        (self.root / "blackbox" / "blackbox.yml").write_text(
            "modules:\n  tcp_connect:\n    prober: tcp\n    tcp: [x]\n  http_fxserver_info:\n    prober: http\n"
            "  http_401_expected:\n    prober: http\n  http_access_protected:\n    prober: http\n", encoding="utf-8")
        found = [str(f) for f in self.findings()]
        self.assertTrue(any("labelmap" in f for f in found), found)
        self.assertTrue(any("labels must be a mapping" in f for f in found), found)
        self.assertTrue(any("every metric needs a name" in f for f in found), found)

    def test_promtool_required_but_missing(self):
        found = self.findings(require_promtool=True)
        self.assertEqual([(f.check, f.message) for f in found], [("promtool", "promtool is not on the PATH")])


@unittest.skipUnless(shutil.which("promtool"), "promtool is not on the PATH")
class PromtoolTest(unittest.TestCase):
    def test_promtool_accepts_the_repository_and_rejects_a_broken_copy(self):
        checker = cp.PackChecker(ROOT)
        self.assertIn("passed promtool check config", checker.run(require_promtool=True))
        self.assertEqual(checker.findings, [])
        with tempfile.TemporaryDirectory(prefix="gso-check-pack-") as tmp:
            for name in CONFIG_DIRS:
                shutil.copytree(ROOT / name, Path(tmp) / name)
            path = Path(tmp) / SCRAPE
            path.write_text(path.read_text(encoding="utf-8").replace("scrape_interval: 15s", "scrape_interval: 15"),
                            encoding="utf-8")
            checker = cp.PackChecker(Path(tmp))
            self.assertEqual(checker.run(require_promtool=True), "failed")
            self.assertEqual([f.check for f in checker.findings], ["promtool"])


class CommandLineTest(unittest.TestCase):
    def run_main(self, argv: list[str]) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch.object(cp.shutil, "which", return_value=None), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(out):
            code = cp.main(argv)
        return code, out.getvalue()

    def test_repository_is_clean(self):
        code, out = self.run_main([])
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"check_pack: 0 finding\(s\) in \d+ parsed file\(s\); promtool: skipped")

    def test_findings_exit_with_1_and_a_missing_root_with_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self.run_main(["--root", tmp])
            self.assertEqual(code, 1)
            self.assertIn("prometheus: [parse] no scrape config found", out)
            code, _ = self.run_main(["--root", str(Path(tmp) / "missing")])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
