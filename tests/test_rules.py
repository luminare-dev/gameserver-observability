"""Tests for the pack's Prometheus rules (rules/*.yml), their promtool tests and their runbook.

promtool checks that the rules load and that each case in tests/rules/ holds
(scripts/check_promtool.sh, CI job "promtool"). These tests check what promtool cannot see:

- Every alert has the label severity (critical or warning) and no other fixed label, and the
  annotations summary, description and runbook_url. The runbook URL points to the alert's own
  section of docs/runbook.md on the main branch; that section has the rows Meaning, Impact,
  Diagnosis, Mitigation and Fix, and no section describes an alert that does not exist.
- Every alert has a promtool case where it fires and one where it must stay quiet, both in a
  test that loads the alert's rule file. promtool passes a case for a misspelled alert name or
  for a rule file that is not loaded without testing anything, so both are checked here.
- Every recorded series has a promql_expr_test in a test that loads its rule file.
- Alerts name the game server: every firing case expects the server label, and no rule groups
  by, matches on or prints the instance label or a label tied to a player.
- Every metric a rule reads and every recorded series is in docs/metrics.md, every alert is in
  the threshold table of docs/configuration.md and in the README's alert table, and every link to a runbook section resolves.

The tests need PyYAML (requirements-test.txt). scripts/test.sh installs it and sets
PACK_TESTS_STRICT=1; without PyYAML a bare unittest run skips them.
"""

from __future__ import annotations

import glob
import os
import re
import sys
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # scripts/test.sh installs it; see the module docstring
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_pack  # noqa: E402

RULE_FILE_GLOBS = ("rules/*.yml", "rules/*.yaml")  # the same globs as scripts/check_promtool.sh
RULE_TEST_GLOBS = ("tests/rules/*.test.yml", "tests/rules/*.test.yaml")
RUNBOOK = ROOT / "docs" / "runbook.md"
RUNBOOK_URL = "https://github.com/luminare-dev/gameserver-observability/blob/main/docs/runbook.md"
SEVERITIES = {"critical", "warning"}
ANNOTATIONS = {"summary", "description", "runbook_url"}
RUNBOOK_ROWS = ("Meaning", "Impact", "Diagnosis", "Mitigation", "Fix")
ALERT_HEADING = "Alert: "
PROMQL_WORDS = {"and", "or", "unless", "bool", "by", "without", "on", "ignoring", "group_left", "group_right",
                "offset", "inf", "nan"}
GROUPING_RE = re.compile(r"\b(by|without|on|ignoring|group_left|group_right)\s*\(([^)]*)\)")
NEEDS_YAML = unittest.skipIf(yaml is None, "PyYAML is not installed (bash scripts/test.sh installs it)")


def paths(patterns: tuple[str, ...]) -> list[Path]:
    return sorted({p for pattern in patterns for p in ROOT.glob(pattern)})


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def all_rules() -> list[tuple[Path, str, dict]]:
    """(rule file, group name, rule) for every rule in rules/."""
    return [(path, group["name"], rule) for path in paths(RULE_FILE_GLOBS)
            for group in load(path).get("groups") or [] for rule in group.get("rules") or []]


def alert_rules() -> list[tuple[Path, dict]]:
    return [(path, rule) for path, _, rule in all_rules() if "alert" in rule]


def recording_rules() -> list[tuple[Path, dict]]:
    return [(path, rule) for path, _, rule in all_rules() if "record" in rule]


def rule_tests() -> list[tuple[Path, set[Path], dict]]:
    """(test file, rule files it loads, test group) for every promtool test group.

    Like promtool, each rule_files entry is taken relative to the test file's folder, and globs
    in it are expanded.
    """
    out = []
    for path in paths(RULE_TEST_GLOBS):
        doc = load(path)
        loaded: set[Path] = set()
        for entry in doc.get("rule_files") or []:
            loaded.update(Path(p).resolve() for p in glob.glob(os.path.join(path.parent, str(entry))))
        out.extend((path, loaded, group) for group in doc.get("tests") or [])
    return out


def metric_names(expr: str) -> set[str]:
    """The metric names a PromQL expression selects (not functions, keywords or label names)."""
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '""', expr)  # string literals
    text = re.sub(r"\{[^}]*\}", " ", text)  # label matchers
    text = re.sub(r"\[[^\]]*\]", " ", text)  # ranges and subqueries
    text = GROUPING_RE.sub(" ", text)  # label lists of by, on, group_left, ...
    text = re.sub(r"\boffset\s+-?\w+", " ", text)
    names = set()
    for match in re.finditer(r"[A-Za-z_:][A-Za-z0-9_:]*", text):
        name = match.group(0)
        before = text[match.start() - 1] if match.start() else " "
        if before.isdigit() or before == ".":  # the exponent of a number such as 1e3
            continue
        if text[match.end():].lstrip().startswith("(") or name.lower() in PROMQL_WORDS:
            continue
        names.add(name)
    return names


def grouping_labels(expr: str) -> set[str]:
    return {label.strip() for _, labels in GROUPING_RE.findall(expr) for label in labels.split(",") if label.strip()}


def github_anchor(heading: str) -> str:
    """The fragment GitHub gives a Markdown heading: lower case, punctuation dropped, spaces to -."""
    text = re.sub(r"[`*_]{2,}|`", "", heading.strip()).lower()
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def markdown_sections(path: Path) -> dict[str, str]:
    """Level-2 headings of a Markdown file and the text up to the next one."""
    parts = re.split(r"^## (.+)$", path.read_text(encoding="utf-8"), flags=re.M)
    return {parts[i].strip(): parts[i + 1] for i in range(1, len(parts), 2)}


def anchors(path: Path) -> set[str]:
    text = re.sub(r"^```.*?^```", "", path.read_text(encoding="utf-8"), flags=re.M | re.S)
    return {github_anchor(m.group(1)) for m in re.finditer(r"^#{1,6} (.+)$", text, re.M)}


class HelperTest(unittest.TestCase):
    """The helpers above must read PromQL and headings correctly, or the checks below mean little."""

    def test_metric_names(self):
        expr = ('(max by (server) (max_over_time(fxserver_clients[30m] offset 30m)) > 0) and on (server) '
                'sum by (server) (rate(mysql_global_status_slow_queries{job="a b"}[5m])) * 60 > 1e3 '
                'unless on (server) histogram_quantile(0.95, sum by (le) (rate(x_bucket[1m]))) '
                'and time() - up{job=~"fxserver_.*"} > 56 * 86400')
        self.assertEqual(metric_names(expr), {"fxserver_clients", "mysql_global_status_slow_queries", "x_bucket",
                                              "up"})
        self.assertEqual(metric_names("server_thread:fxserver_tick_time_seconds:p95_1m{thread=\"svMain\"} > 0.05"),
                         {"server_thread:fxserver_tick_time_seconds:p95_1m"})

    def test_grouping_labels(self):
        expr = "min by (server, job) (up) == 0 unless on(server) x and ignoring (instance) y * group_left (a) z"
        self.assertEqual(grouping_labels(expr), {"server", "job", "instance", "a"})

    def test_github_anchor(self):
        self.assertEqual(github_anchor("Alert: FXServerDown"), "alert-fxserverdown")
        self.assertEqual(github_anchor("Failure: the `promtool` job fails"), "failure-the-promtool-job-fails")
        self.assertEqual(github_anchor("Host and database jobs"), "host-and-database-jobs")


@NEEDS_YAML
class AlertRuleShapeTest(unittest.TestCase):
    def test_there_are_rules(self):
        self.assertGreaterEqual(len(alert_rules()), 6)
        self.assertGreater(len(recording_rules()), 0)

    def test_every_alert_has_a_severity_and_the_three_annotations(self):
        for path, rule in alert_rules():
            with self.subTest(alert=rule["alert"], file=path.name):
                self.assertEqual(set(rule.get("labels") or {}), {"severity"})
                self.assertIn(rule["labels"]["severity"], SEVERITIES)
                self.assertEqual(set(rule.get("annotations") or {}), ANNOTATIONS)
                self.assertNotIn("\n", rule["annotations"]["summary"])
                self.assertIn("{{ $labels.server }}", rule["annotations"]["summary"])

    def test_rule_and_group_names_are_unique(self):
        groups = [group for _, group, _ in all_rules()]
        names = [rule.get("alert") or rule.get("record") for _, _, rule in all_rules()]
        self.assertEqual(len(set(groups)), len({(p, g) for p, g, _ in all_rules()}), "a group name repeats")
        self.assertEqual(len(names), len(set(names)), "a rule name repeats")

    def test_no_rule_uses_the_instance_label_or_a_player_label(self):
        for path, _, rule in all_rules():
            name = rule.get("alert") or rule.get("record")
            with self.subTest(rule=name, file=path.name):
                for label in grouping_labels(rule["expr"]):
                    self.assertNotEqual(label, "instance")
                    self.assertIsNone(check_pack.PLAYER_LABEL_RE.fullmatch(label), label)
                for label in rule.get("labels") or {}:
                    self.assertIsNone(check_pack.PLAYER_LABEL_RE.fullmatch(label), label)
                for text in (rule.get("annotations") or {}).values():
                    for label in re.findall(r"\$labels\.(\w+)", text):
                        self.assertNotEqual(label, "instance")
                        self.assertIsNone(check_pack.PLAYER_LABEL_RE.fullmatch(label), label)
                self.assertNotIn("players.json", rule["expr"])

    def test_recorded_names_start_with_the_labels_they_keep(self):
        """level:metric:operations, where the level names the labels the result keeps (le is used up)."""
        for _, rule in recording_rules():
            with self.subTest(record=rule["record"]):
                level = rule["record"].split(":")[0]
                self.assertEqual(set(level.split("_")), grouping_labels(rule["expr"]) - {"le"})
                self.assertIn("server", level.split("_"))


@NEEDS_YAML
class RunbookTest(unittest.TestCase):
    def setUp(self):
        self.sections = markdown_sections(RUNBOOK)

    def test_every_runbook_url_points_to_the_alerts_section(self):
        for _, rule in alert_rules():
            name = rule["alert"]
            with self.subTest(alert=name):
                heading = ALERT_HEADING + name
                self.assertIn(heading, sorted(self.sections))
                self.assertEqual(rule["annotations"]["runbook_url"], f"{RUNBOOK_URL}#{github_anchor(heading)}")

    def test_every_alert_section_has_the_five_rows(self):
        for heading, body in self.sections.items():
            if not heading.startswith(ALERT_HEADING):
                continue
            with self.subTest(section=heading):
                rows = re.findall(r"^\| \*\*(\w+)\*\* \| \S", body, re.M)
                self.assertEqual(tuple(rows), RUNBOOK_ROWS)

    def test_no_alert_section_without_an_alert(self):
        alerts = {rule["alert"] for _, rule in alert_rules()}
        documented = {h.removeprefix(ALERT_HEADING) for h in self.sections if h.startswith(ALERT_HEADING)}
        self.assertEqual(documented, alerts)

    def test_every_link_to_a_runbook_section_resolves(self):
        targets = anchors(RUNBOOK)
        for path in [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]:
            for fragment in re.findall(r"runbook\.md#([\w-]+)", path.read_text(encoding="utf-8")):
                with self.subTest(file=path.relative_to(ROOT).as_posix(), fragment=fragment):
                    self.assertIn(fragment, targets)


@NEEDS_YAML
class RuleTestCoverageTest(unittest.TestCase):
    def setUp(self):
        self.tests = rule_tests()

    def cases(self, name: str, rule_file: Path) -> list[list]:
        """The exp_alerts of every case for this alert in a test that loads its rule file."""
        return [case.get("exp_alerts") or [] for _, loaded, group in self.tests if rule_file.resolve() in loaded
                for case in group.get("alert_rule_test") or [] if case.get("alertname") == name]

    def test_every_alert_fires_in_one_case_and_stays_quiet_in_another(self):
        for path, rule in alert_rules():
            with self.subTest(alert=rule["alert"]):
                cases = self.cases(rule["alert"], path)
                self.assertTrue(any(cases), "no case where the alert fires")
                self.assertTrue(any(not c for c in cases), "no case where the alert must stay quiet")

    def test_every_alertname_in_the_tests_is_an_alert_of_a_loaded_file(self):
        alerts = {rule["alert"]: path.resolve() for path, rule in alert_rules()}
        for test_file, loaded, group in self.tests:
            for case in group.get("alert_rule_test") or []:
                with self.subTest(file=test_file.name, test=group.get("name"), alertname=case.get("alertname")):
                    self.assertIn(case.get("alertname"), alerts)
                    self.assertIn(alerts[case["alertname"]], loaded)

    def test_every_firing_case_expects_the_server_and_the_severity(self):
        severity = {rule["alert"]: rule["labels"]["severity"] for _, rule in alert_rules()}
        for test_file, _, group in self.tests:
            for case in group.get("alert_rule_test") or []:
                for expected in case.get("exp_alerts") or []:
                    labels = expected.get("exp_labels") or {}
                    with self.subTest(file=test_file.name, test=group.get("name"), alertname=case["alertname"]):
                        self.assertTrue(labels.get("server"))
                        self.assertEqual(labels.get("severity"), severity[case["alertname"]])
                        self.assertNotIn("instance", labels)
                        self.assertEqual(set(expected.get("exp_annotations") or {}), ANNOTATIONS)

    def test_every_recorded_series_has_an_expression_test(self):
        for path, rule in recording_rules():
            pattern = re.compile(rf"(?<![\w:]){re.escape(rule['record'])}(?![\w:])")
            with self.subTest(record=rule["record"]):
                self.assertTrue(any(pattern.search(case.get("expr", "")) for _, loaded, group in self.tests
                                    if path.resolve() in loaded for case in group.get("promql_expr_test") or []))


@NEEDS_YAML
class RuleDocsTest(unittest.TestCase):
    def test_every_metric_the_rules_read_and_every_recorded_series_is_documented(self):
        doc = (ROOT / "docs" / "metrics.md").read_text(encoding="utf-8")
        names = {name for _, _, rule in all_rules() for name in metric_names(rule["expr"])}
        names |= {rule["record"] for _, rule in recording_rules()}
        self.assertIn("fxserver_tick_time_seconds_bucket", names)
        for name in sorted(names):
            with self.subTest(metric=name):
                self.assertIn(f"`{name}`", doc)

    def test_every_alert_is_in_the_threshold_table(self):
        section = markdown_sections(ROOT / "docs" / "configuration.md")["Rules (`rules/`)"]
        for _, rule in alert_rules():
            with self.subTest(alert=rule["alert"]):
                self.assertRegex(section, rf"(?m)^\| `{rule['alert']}` \|")

    def test_the_readme_lists_every_alert(self):
        section = markdown_sections(ROOT / "README.md")["How it works"]
        for _, rule in alert_rules():
            with self.subTest(alert=rule["alert"]):
                self.assertRegex(section, rf"(?m)^\| [^|]*`{rule['alert']}`[^|]*\|")


if __name__ == "__main__":
    unittest.main()
