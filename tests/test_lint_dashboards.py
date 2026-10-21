"""Tests for scripts/lint_dashboards.py, the check of the Grafana dashboards.

The repository's dashboards must pass every check. Each other test copies the dashboard and the
metrics reference into a temporary folder, breaks one thing and expects the check that guards it
to report it, so a check that stops working fails here. Standard library only; the promtool test
runs when promtool is on the PATH (the promtool job runs the whole check with promtool as well).
"""

from __future__ import annotations

import copy
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import lint_dashboards as ld  # noqa: E402

DASHBOARD = "grafana/dashboards/game-server-overview.json"
SHAREABLE = "grafana/dashboards/shareable/game-server-overview.json"


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def panels(doc: dict) -> list[dict]:
    return ld.all_panels(doc["panels"])


def panel(doc: dict, title: str) -> dict:
    return next(p for p in panels(doc) if p.get("title") == title)


class TempRepo:
    """A folder with the metrics reference and one dashboard, plus its shareable copy."""

    def __init__(self, test: unittest.TestCase):
        self.root = Path(tempfile.mkdtemp(prefix="gso-dash-"))
        test.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / "docs").mkdir()
        shutil.copy(ROOT / "docs" / "metrics.md", self.root / "docs" / "metrics.md")
        (self.root / ld.SHAREABLE_DIR).mkdir(parents=True)

    def write(self, doc: dict, shareable: dict | None = None, name: str = "game-server-overview.json",
              make_copy: bool = True) -> None:
        (self.root / ld.DASHBOARD_DIR / name).write_text(ld.render(doc), encoding="utf-8")
        if make_copy:
            shared = shareable if shareable is not None else ld.make_shareable(doc)
            (self.root / ld.SHAREABLE_DIR / name).write_text(ld.render(shared), encoding="utf-8")

    def lint(self) -> list[ld.Finding]:
        linter = ld.DashboardLinter(self.root)
        with mock.patch.object(ld.shutil, "which", return_value=None):
            linter.run(require_promtool=False)
        return linter.findings


class LintTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo(self)
        self.doc = load(DASHBOARD)

    def findings(self, doc: dict | None = None, **write) -> list[ld.Finding]:
        self.repo.write(self.doc if doc is None else doc, **write)
        return self.repo.lint()

    def assertFinds(self, check: str, text: str, findings: list[ld.Finding] | None = None) -> None:
        findings = self.findings() if findings is None else findings
        hits = [f for f in findings if f.check == check and text in f.message]
        self.assertTrue(hits, f"no [{check}] finding with {text!r} in:\n" + "\n".join(map(str, findings)))


class RepositoryDashboardsTest(unittest.TestCase):
    def test_the_dashboards_pass_every_check(self):
        linter = ld.DashboardLinter(ROOT)
        with mock.patch.object(ld.shutil, "which", return_value=None):  # promtool: see PromtoolTest
            linter.run()
        self.assertEqual([str(f) for f in linter.findings], [])
        self.assertEqual(sorted(linter.files), [DASHBOARD, SHAREABLE])

    def test_the_dashboard_has_the_rows_of_the_plan(self):
        doc = load(DASHBOARD)
        self.assertEqual(doc["title"], "Game server overview")
        rows = [p["title"] for p in doc["panels"] if p["type"] == "row"]
        self.assertEqual(rows, ["Overview", "Tick time", "Players", "Host", "MariaDB", "Probes and tunnel"])
        heatmap = panel(doc, "Main thread tick time")
        self.assertEqual(heatmap["type"], "heatmap")
        self.assertIn("fxserver_tick_time_seconds_bucket", heatmap["targets"][0]["expr"])
        percentiles = " ".join(t["expr"] for t in panel(doc, "Tick time p95 and p99")["targets"])
        self.assertIn(":p95_1m", percentiles)
        self.assertIn(":p99_1m", percentiles)

    def test_the_variables_are_a_data_source_and_the_game_server(self):
        variables = {v["name"]: v for v in ld.template_variables(load(DASHBOARD))}
        self.assertEqual(sorted(variables), ["datasource", "server"])
        self.assertEqual(variables["datasource"]["type"], "datasource")
        self.assertEqual(variables["server"]["query"]["query"], 'label_values(up{job="fxserver_perf"}, server)')

    def test_the_shareable_copy_has_no_variables_and_one_input(self):
        shared = load(SHAREABLE)
        text = json.dumps(shared)
        self.assertEqual(shared["templating"], {"list": []})
        self.assertNotIn("$server", text)
        self.assertNotIn("${datasource}", text)
        self.assertEqual([i["name"] for i in shared["__inputs"]], ["DS_PROMETHEUS"])
        self.assertEqual(shared["uid"], load(DASHBOARD)["uid"] + "-shared")
        self.assertEqual(shared["title"], load(DASHBOARD)["title"])
        for p in panels(shared):
            if p["type"] != "row":
                with self.subTest(panel=p["title"]):
                    self.assertEqual(p["datasource"], {"type": "prometheus", "uid": "${DS_PROMETHEUS}"})

    def test_fix_changes_nothing_in_the_repository_files(self):
        repo = TempRepo(self)
        shutil.copy(ROOT / DASHBOARD, repo.root / DASHBOARD)
        shutil.copy(ROOT / SHAREABLE, repo.root / SHAREABLE)
        self.assertEqual(ld.DashboardLinter(repo.root).fix(), [])
        self.assertEqual((repo.root / SHAREABLE).read_bytes(), (ROOT / SHAREABLE).read_bytes())


class FormatAndNamesTest(LintTestCase):
    def test_other_indentation_is_reported_and_fix_rewrites_it(self):
        self.repo.write(self.doc)
        path = self.repo.root / DASHBOARD
        path.write_text(json.dumps(self.doc, indent=4), encoding="utf-8")
        self.assertFinds("parse", "repository's format", self.repo.lint())
        self.assertEqual(ld.DashboardLinter(self.repo.root).fix(), [DASHBOARD])
        self.assertEqual(self.repo.lint(), [])

    def test_invalid_json_is_reported(self):
        self.repo.write(self.doc)
        (self.repo.root / DASHBOARD).write_text("{", encoding="utf-8")
        self.assertFinds("parse", "not valid JSON", self.repo.lint())

    def test_schema_of_another_grafana_and_a_stored_id_are_reported(self):
        self.doc["schemaVersion"] = 41
        self.doc["id"] = 7
        findings = self.findings()
        self.assertFinds("parse", "schemaVersion 41", findings)
        self.assertFinds("parse", '"id" must be null', findings)

    def test_platform_and_vendor_marks_in_titles_are_reported(self):
        self.doc["title"] = "FXServer overview"
        panel(self.doc, "CPU")["title"] = "Grafana host CPU"
        findings = self.findings()
        self.assertFinds("names", "dashboard title 'FXServer overview'", findings)
        self.assertFinds("names", "'Grafana host CPU'", findings)


class DatasourceAndVariablesTest(LintTestCase):
    def test_a_hard_coded_data_source_uid_is_reported(self):
        panel(self.doc, "Players")["datasource"] = {"type": "prometheus", "uid": "P1809F7CD0C75ACF3"}
        self.assertFinds("datasource", "panel 3 ('Players')")

    def test_a_query_with_its_own_data_source_is_reported(self):
        panel(self.doc, "Players")["targets"][0]["datasource"] = {"type": "prometheus", "uid": "abc"}
        self.assertFinds("datasource", "query A")

    def test_a_stored_data_source_selection_is_reported(self):
        variable = ld.template_variables(self.doc)[0]
        variable["current"] = {"text": "Prometheus", "value": "P1809F7CD0C75ACF3"}
        self.assertFinds("datasource", "variable datasource: current and options must be empty")

    def test_a_selected_game_server_is_reported(self):
        variable = ld.template_variables(self.doc)[1]
        variable["current"] = {"text": "game-01", "value": "game-01"}
        self.assertFinds("variables", "keep no selected value but All")

    def test_an_unknown_variable_is_reported(self):
        target = panel(self.doc, "Players")["targets"][0]
        target["expr"] = target["expr"].replace("$server", "$host")
        self.assertFinds("variables", "$host is not a variable of this dashboard")

    def test_another_variable_type_is_reported(self):
        self.doc["templating"]["list"].append({"name": "site", "type": "custom", "query": "a,b"})
        self.assertFinds("variables", "type 'custom'")

    def test_a_variable_on_a_player_label_is_reported(self):
        variable = ld.template_variables(self.doc)[1]
        variable["query"]["query"] = 'label_values(up{job="fxserver_perf"}, license)'
        self.assertFinds("labels", "label 'license' could identify a player")

    def test_the_shareable_copy_must_not_keep_variables(self):
        shared = ld.make_shareable(self.doc)
        shared["templating"] = copy.deepcopy(self.doc["templating"])
        self.assertFinds("variables", "a shareable copy has no template variables", self.findings(shareable=shared))


class QueryTest(LintTestCase):
    def set_expr(self, title: str, expr: str, legend: str | None = None) -> None:
        target = panel(self.doc, title)["targets"][0]
        target["expr"] = expr
        if legend is not None:
            target["legendFormat"] = legend

    def test_an_undocumented_metric_is_reported(self):
        self.set_expr("Players", 'sum by (server) (fxserver_players_online{server=~"$server"})')
        self.assertFinds("metrics", "metric 'fxserver_players_online' is not in docs/metrics.md")

    def test_a_player_label_is_reported_in_matchers_groupings_and_legends(self):
        self.set_expr("Players", 'sum by (server, name) (fxserver_clients{server=~"$server"})', "{{name}}")
        findings = self.findings()
        self.assertFinds("labels", "label 'name' could identify a player", findings)
        self.assertFinds("labels", "the legend shows label 'name'", findings)
        self.set_expr("Players", 'sum by (server) (fxserver_clients{server=~"$server", endpoint!=""})', "{{server}}")
        self.assertFinds("labels", "label 'endpoint' could identify a player")

    def test_an_unaggregated_selector_is_reported(self):
        for expr in ('fxserver_clients{server=~"$server"}',
                     'topk(1, fxserver_clients{server=~"$server"})',
                     'sum without (module) (fxserver_clients{server=~"$server"})'):
            with self.subTest(expr=expr):
                self.set_expr("Players", expr)
                self.assertFinds("aggregation", "fxserver_clients is not aggregated")

    def test_the_instance_label_is_reported_anywhere(self):
        self.set_expr("Players", 'sum by (server) (fxserver_clients{server=~"$server"})', "{{instance}}")
        self.assertFinds("labels", "uses 'instance'")
        self.setUp()
        panel(self.doc, "Players")["description"] = "Clients per instance"
        self.assertFinds("labels", "uses 'instance'")

    def test_addresses_and_foreign_links_are_reported(self):
        panel(self.doc, "Players")["description"] = "Scraped from 192.0.2.10, see https://example.com/help"
        findings = self.findings()
        self.assertFinds("links", "IP address 192.0.2.10", findings)
        self.assertFinds("links", "link https://example.com/help does not point to this repository", findings)

    def test_a_query_that_cannot_be_read_is_reported(self):
        self.set_expr("Players", 'sum by (server) (fxserver_clients{server=~"$server"}')
        self.assertFinds("parse", "a '(' is not closed")

    def test_a_selector_on_the_metric_name_is_reported(self):
        self.set_expr("Players", 'sum by (server) ({__name__="fxserver_clients", server=~"$server"})')
        self.assertFinds("parse", "matches __name__")


class PanelTest(LintTestCase):
    def test_duplicate_ids_missing_descriptions_and_legends_are_reported(self):
        players, slots = panel(self.doc, "Players"), panel(self.doc, "Slots in use")
        slots["id"] = players["id"]
        del players["description"]
        players["targets"][0]["legendFormat"] = "__auto"
        findings = self.findings()
        self.assertFinds("panels", "id must be a number used by no other panel", findings)
        self.assertFinds("panels", "needs a description", findings)
        self.assertFinds("panels", "set a legend", findings)

    def test_overlapping_and_out_of_grid_panels_are_reported(self):
        panel(self.doc, "Players")["gridPos"] = {"h": 4, "w": 3, "x": 1, "y": 1}
        panel(self.doc, "Firing alerts")["gridPos"] = {"h": 4, "w": 4, "x": 21, "y": 1}
        findings = self.findings()
        self.assertFinds("panels", "panel 3: overlaps panel 2", findings)
        self.assertFinds("panels", "outside the 24-column grid", findings)

    def test_a_panel_without_queries_is_reported(self):
        panel(self.doc, "Players")["targets"] = []
        self.assertFinds("panels", "has no queries")


class ShareableCopyTest(LintTestCase):
    def test_a_missing_copy_is_reported(self):
        self.assertFinds("shareable", "missing or not the copy", self.findings(make_copy=False))

    def test_an_outdated_copy_is_reported(self):
        old = ld.make_shareable(self.doc)
        panel(self.doc, "Players")["description"] = "Connected clients, a count."
        self.assertFinds("shareable", "missing or not the copy", self.findings(shareable=old))

    def test_a_copy_without_its_dashboard_is_reported(self):
        self.repo.write(self.doc)
        (self.repo.root / ld.SHAREABLE_DIR / "old.json").write_text(
            ld.render(ld.make_shareable(self.doc) | {"uid": "old-shared"}), encoding="utf-8")
        self.assertFinds("shareable", "no dashboard grafana/dashboards/old.json", self.repo.lint())

    def test_a_variable_outside_a_matcher_cannot_be_shared(self):
        target = panel(self.doc, "Players")["targets"][0]
        target["expr"] = 'sum by (server) (fxserver_clients) * on (server) group_left label_replace(' \
                         'vector(1), "server", "$server", "", "")'
        self.assertFinds("shareable", "$server is used outside a label matcher", self.findings(make_copy=False))

    def test_fix_writes_the_copy(self):
        self.repo.write(self.doc, make_copy=False)
        self.assertEqual(ld.DashboardLinter(self.repo.root).fix(), [SHAREABLE])
        self.assertEqual(self.repo.lint(), [])
        self.assertEqual(ld.DashboardLinter(self.repo.root).fix(), [])

    def test_drop_variable_matchers(self):
        cases = {
            'sum(x{server=~"$server", job="a"})': 'sum(x{job="a"})',
            'sum(x{server=~"${server}"}) / sum(y{job="a", server="$server"})': 'sum(x) / sum(y{job="a"})',
            'sum(rate(x{server=~"$server"}[$__rate_interval]))': "sum(rate(x[$__rate_interval]))",
            'sum(x{server!~"$server"})': None,  # a negative matcher is not a selection: cannot be dropped
        }
        for expr, expected in cases.items():
            with self.subTest(expr=expr):
                if expected is None:
                    with self.assertRaises(ld.ShareableError):
                        ld.drop_variable_matchers(expr, ["server"])
                else:
                    self.assertEqual(ld.drop_variable_matchers(expr, ["server"]), expected)


class AnalyseTest(unittest.TestCase):
    def test_metrics_labels_and_aggregation(self):
        query = ld.analyse('sum by (server) (rate(a_total{x="1", y=~"$v"}[5m] offset 1h)) / on (server) '
                           'group_left max by (server, le) (b) > bool 0.5')
        self.assertEqual(query.metrics, ["a_total", "b"])
        self.assertEqual(sorted(set(query.labels)), ["le", "server", "x", "y"])
        self.assertEqual(query.problems, [])

    def test_clause_first_and_nested_functions(self):
        query = ld.analyse("histogram_quantile(0.95, sum by (le) (increase(h_bucket[1m:15s])))"
                           " and on () max(c{a='{x}'})")
        self.assertEqual(query.metrics, ["h_bucket", "c"])
        self.assertEqual(query.problems, [])
        self.assertEqual(ld.analyse("max without () (sum by (s) (d))").problems, [])

    def test_label_arguments_of_label_replace(self):
        query = ld.analyse('label_replace(sum by (src) (e), "dst", "$1", "src", "(.*)")')
        self.assertIn("dst", query.labels)
        self.assertEqual(query.metrics, ["e"])

    def test_keywords_numbers_and_functions_are_not_metrics(self):
        query = ld.analyse("time() - max(f) or vector(0) unless count(g) == 1e3 and inf > nan")
        self.assertEqual(query.metrics, ["f", "g"])

    def test_problems(self):
        self.assertTrue(any("not aggregated" in p for p in ld.analyse("h").problems))
        self.assertTrue(any("not aggregated" in p for p in ld.analyse("bottomk(2, h)").problems))
        with self.assertRaises(ld.PromQLError):
            ld.analyse("sum(h))")
        with self.assertRaises(ld.PromQLError):
            ld.analyse('sum(h{a=~"x})')

    def test_substitute_uses_sample_values(self):
        self.assertEqual(ld.substitute('sum(rate(x{s=~"$server"}[$__rate_interval])) $__range ${server:raw} $other',
                                       {"server"}),
                         'sum(rate(x{s=~"game-01"}[1m])) 1h game-01 $other')


class MetricsReferenceTest(unittest.TestCase):
    def test_only_the_first_column_of_metric_and_series_tables_counts(self):
        repo = TempRepo(self)
        (repo.root / "docs" / "metrics.md").write_text(
            "# Metrics\n\n| Metric | Type |\n|---|---|\n| `a_total`, `b` | `not_this` |\n\n"
            "| Option | Default |\n|---|---|\n| `not_an_option_metric` | x |\n\n"
            "| Series | Meaning |\n|---|---|\n| `level:c:rate1m` | y |\n", encoding="utf-8")
        self.assertEqual(ld.documented_metrics(repo.root), {"a_total", "b", "level:c:rate1m"})

    def test_the_repository_reference_lists_the_dashboard_series(self):
        documented = ld.documented_metrics(ROOT)
        for name in ("fxserver_clients", "ALERTS", "node_cpu_seconds_total", "mysql_global_status_queries",
                     "cloudflared_tunnel_ha_connections", "server_thread:fxserver_tick_time_seconds:p95_1m"):
            with self.subTest(metric=name):
                self.assertIn(name, documented)


@unittest.skipUnless(shutil.which("promtool"), "promtool is not on the PATH (the promtool job runs this check)")
class PromtoolTest(unittest.TestCase):
    def test_every_repository_query_parses(self):
        linter = ld.DashboardLinter(ROOT)
        result = linter.run(require_promtool=True)
        self.assertEqual([str(f) for f in linter.findings], [])
        self.assertIn("passed promtool check rules", result)

    def test_a_query_promtool_rejects_is_reported(self):
        repo = TempRepo(self)
        doc = load(DASHBOARD)
        panel(doc, "Players")["targets"][0]["expr"] = 'sum by (server) (rate(fxserver_clients{server=~"$server"}))'
        repo.write(doc)
        linter = ld.DashboardLinter(repo.root)
        self.assertEqual(linter.run(require_promtool=True), "failed")
        self.assertTrue(any(f.check == "promtool" and "panel 3 ('Players') query A" in f.message
                            for f in linter.findings), linter.findings)


class CommandLineTest(unittest.TestCase):
    def run_main(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(ld.shutil, "which", return_value=None):
            code = ld.main(list(args))
        return code, out.getvalue()

    def test_exit_codes(self):
        repo = TempRepo(self)
        doc = load(DASHBOARD)
        repo.write(doc)
        code, out = self.run_main("--root", str(repo.root))
        self.assertEqual(code, 0, out)
        self.assertIn("lint_dashboards: 0 finding(s) in 2 file(s)", out)
        code, out = self.run_main("--root", str(repo.root), "--require-promtool")
        self.assertEqual(code, 1)
        self.assertIn("promtool is not on the PATH", out)
        doc["title"] = "Grafana overview"
        repo.write(doc)
        self.assertEqual(self.run_main("--root", str(repo.root))[0], 1)
        with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(self.run_main("--root", str(repo.root / "missing"))[0], 2)

    def test_no_dashboard_is_a_finding(self):
        repo = TempRepo(self)
        code, out = self.run_main("--root", str(repo.root))
        self.assertEqual(code, 1)
        self.assertIn("no dashboard found", out)


if __name__ == "__main__":
    unittest.main()
