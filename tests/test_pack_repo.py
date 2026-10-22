"""Tests for this repository's own setup (the template's tests cover the shared scripts).

- The release archive (scripts/package_release.py, a `git archive` of the tag) is the pack
  tarball: it must hold every tracked file, and no git attribute may drop the pack's folders.
- Dependabot: every ecosystem uses a Conventional Commit prefix with `include: scope` and the
  `dependencies` label (the PR-title check rejects anything else), and every requirements file,
  Dockerfile and Compose file is covered by an ecosystem.
- Python requirements are pinned by version and sha256.
- CI and the release build run the same test command; the promtool, Prometheus, exporter and
  gitleaks pins match docs/toolchain.md and the secret-scan workflow; the promtool job runs the
  pack check and the dashboard check, and the exporters job the end-to-end run.
- Every metric the scrape configs and the json_exporter modules produce, and every job and probe
  module of every scrape file, is in docs/metrics.md; scripts/smoke_exporters.py expects exactly
  those metrics and runs every scrape file except the optional tunnel probe.
- docs/cardinality.md: the sample limits, target counts and recorded series in its tables are
  those of the scrape configs and the recording rules, and its sums add up.
- The scrape job's build rule finds the build number in both likely shapes of the version string.
- promtool: every rule file is named in the rule_files of at least one rule test.
- gitleaks: the license-key rules (the same as in the luminare.gameserver collection) find keys
  of any layout, also right after a word character; documentation placeholders stay clean.

The YAML tests need PyYAML (requirements-test.txt). scripts/test.sh installs it and sets
PACK_TESTS_STRICT=1, so CI and the release build fail instead of skipping them; a bare
`python3 -m unittest discover -s tests` without PyYAML skips them. The archive tests need git.
The gitleaks tests need the gitleaks binary: scripts/test.sh installs the pinned version in CI,
elsewhere they run when gitleaks is on the PATH.
"""

from __future__ import annotations

import glob
import json
import os
import re
import secrets
import shutil
import string
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # scripts/test.sh installs it; see the module docstring
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_pack  # noqa: E402
import package_release as pr  # noqa: E402
import smoke_exporters  # noqa: E402

# Where the pack's files live (docs/adr/0005-pack-layout-and-release-archive.md). Sample paths,
# so an export-ignore attribute is caught even before the first file of a folder exists.
PACK_PATHS = [
    "prometheus/scrape/fxserver.yml",
    "prometheus/prometheus.demo.yml",
    "json_exporter/config.yml",
    "blackbox/blackbox.yml",
    "rules/fxserver.alerts.yml",
    "tests/rules/tick.test.yml",
    "grafana/dashboards/game-server-overview.json",
    "grafana/dashboards/shareable/game-server-overview.json",
    "grafana/provisioning/dashboards/gameserver-observability.yml",
    "grafana/provisioning/datasources/gameserver-observability.yml",
    "demo/docker-compose.yml",
    "docs/metrics.md",
]
CONVENTIONAL_PREFIXES = {"build", "ci", "chore", "test"}
SCRAPE_FILES = ("prometheus/scrape/fxserver.yml", "prometheus/scrape/tunnel.yml", "prometheus/scrape/versions.yml")
RULE_FILE_GLOBS = ("rules/*.yml", "rules/*.yaml")  # the same globs as scripts/check_promtool.sh
RULE_TEST_GLOBS = ("tests/rules/*.test.yml", "tests/rules/*.test.yaml")
ANY_SHAPE_RULE = "cfx-license-key-any-shape"
KEY_PREFIX = "cfx" + "k_"  # split so that no line of this file starts a key
KEY_CHARS = string.ascii_letters + string.digits
IN_GIT_CHECKOUT = (ROOT / ".git").exists() and shutil.which("git") is not None
NEEDS_YAML = unittest.skipIf(yaml is None, "PyYAML is not installed (bash scripts/test.sh installs it)")


def temp_dir(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    unittest.addModuleCleanup(shutil.rmtree, tmp, ignore_errors=True)
    return tmp


def git(*args: str, stdin: str | None = None) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], input=stdin, check=True, capture_output=True,
                          text=True).stdout


def load_yaml(rel: str) -> dict:
    return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))


def tracked_files() -> list[str]:
    if IN_GIT_CHECKOUT:
        return [p for p in git("ls-files", "-z").split("\0") if p]
    return [p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()]


def rand(n: int) -> str:
    return "".join(secrets.choice(KEY_CHARS) for _ in range(n))


def rule_files_without_test(root: Path) -> list[str]:
    """Rule files that no promtool rule test names in its rule_files.

    Like promtool, each rule_files entry is taken relative to the test file's folder, and globs
    in it are expanded.
    """
    base = root.resolve()
    rule_files = {p.resolve() for pattern in RULE_FILE_GLOBS for p in base.glob(pattern)}
    named: set[Path] = set()
    for pattern in RULE_TEST_GLOBS:
        for test_file in base.glob(pattern):
            doc = yaml.safe_load(test_file.read_text(encoding="utf-8")) or {}
            for entry in doc.get("rule_files") or []:
                named.update(Path(p).resolve() for p in glob.glob(os.path.join(test_file.parent, str(entry))))
    return sorted(p.relative_to(base).as_posix() for p in rule_files - named)


@unittest.skipUnless(IN_GIT_CHECKOUT, "needs a git checkout")
class ReleaseArchiveTest(unittest.TestCase):
    def test_no_attribute_drops_files_from_the_archive(self):
        paths = sorted(set(tracked_files()) | set(PACK_PATHS))
        out = git("check-attr", "--stdin", "-z", "export-ignore", "export-subst", stdin="\0".join(paths) + "\0")
        fields = out.split("\0")
        set_attrs = [(fields[i], fields[i + 1], fields[i + 2]) for i in range(0, len(fields) - 2, 3)
                     if fields[i + 2] != "unspecified"]
        self.assertEqual(set_attrs, [])

    def test_archive_of_head_holds_every_tracked_file(self):
        out = temp_dir("gso-archive-")
        archive = pr.build(ROOT, "HEAD", "gameserver-observability", "0.0.0", out)[0]
        prefix = "gameserver-observability-0.0.0/"
        with tarfile.open(archive) as tar:
            members = {m.name.removeprefix(prefix) for m in tar.getmembers() if not m.isdir()}
        expected = {p for p in git("ls-tree", "-r", "-z", "--name-only", "HEAD").split("\0") if p}
        self.assertEqual(members, expected)
        for must in ("LICENSE", "NOTICE", "README.md", "CHANGELOG.md"):
            self.assertIn(must, members)


class TestEnvironmentTest(unittest.TestCase):
    def test_strict_runs_have_pyyaml(self):
        """scripts/test.sh sets PACK_TESTS_STRICT=1: there, a missing PyYAML is an error, not a skip."""
        if os.environ.get("PACK_TESTS_STRICT") == "1":
            self.assertIsNotNone(yaml, "PyYAML is missing although PACK_TESTS_STRICT=1")

    def test_ci_runs_have_gitleaks(self):
        """In CI scripts/test.sh installs gitleaks, so the secret-rule tests cannot be skipped there."""
        if os.environ.get("PACK_TESTS_STRICT") == "1" and os.environ.get("CI") == "true":
            self.assertIsNotNone(shutil.which("gitleaks"), "gitleaks is missing although CI=true")


@NEEDS_YAML
class DependabotTest(unittest.TestCase):
    def setUp(self):
        self.updates = load_yaml(".github/dependabot.yml")["updates"]

    @staticmethod
    def directories(update: dict) -> list[str]:
        return [d.strip("/") for d in update.get("directories") or [update["directory"]]]

    def test_titles_pass_the_pr_title_check(self):
        for u in self.updates:
            with self.subTest(ecosystem=u["package-ecosystem"], directories=self.directories(u)):
                self.assertIn(u["commit-message"]["prefix"], CONVENTIONAL_PREFIXES)
                self.assertEqual(u["commit-message"].get("include"), "scope")
                self.assertEqual(u["labels"], ["dependencies"])

    def covered(self, ecosystems: set[str], directory: str) -> bool:
        return any(u["package-ecosystem"] in ecosystems and directory in self.directories(u) for u in self.updates)

    def test_every_manifest_is_covered(self):
        self.assertTrue(self.covered({"github-actions"}, ""))
        for rel in tracked_files():
            path = Path(rel)
            directory = "" if path.parent == Path(".") else path.parent.as_posix()
            if re.fullmatch(r"requirements.*\.(txt|in)", path.name):
                ecosystems = {"pip"}
            elif path.name.startswith("Dockerfile"):
                ecosystems = {"docker"}
            elif re.fullmatch(r"(docker-)?compose(\.[\w-]+)?\.ya?ml", path.name):
                ecosystems = {"docker-compose"}
            else:
                continue
            with self.subTest(file=rel):
                self.assertTrue(self.covered(ecosystems, directory), f"no {ecosystems} entry for /{directory}")


class RequirementsTest(unittest.TestCase):
    def requirements(self, rel: str) -> list[str]:
        text = (ROOT / rel).read_text(encoding="utf-8").replace("\\\n", " ")
        return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]

    def test_every_requirement_is_pinned_by_hash(self):
        for rel in ("requirements-dev.txt", "requirements-test.txt"):
            reqs = self.requirements(rel)
            self.assertTrue(reqs, rel)
            for req in reqs:
                with self.subTest(file=rel, requirement=req.split()[0]):
                    self.assertRegex(req, r"^[A-Za-z0-9._-]+==[0-9][^ ]* ")
                    self.assertRegex(req, r"--hash=sha256:[0-9a-f]{64}")

    def test_test_requirements_are_compiled_for_the_runner_python(self):
        header = (ROOT / "requirements-test.txt").read_text(encoding="utf-8")
        self.assertIn("autogenerated by pip-compile with Python 3.12", header)
        self.assertIn("pip-compile --generate-hashes", header)
        # docs/toolchain.md sets CUSTOM_COMPILE_COMMAND to the command it runs, so a recompile keeps
        # this header line byte for byte.
        toolchain = (ROOT / "docs" / "toolchain.md").read_text(encoding="utf-8")
        documented = re.search(r"^cmd='(pip-compile [^']+)'$", toolchain, re.M)
        self.assertIsNotNone(documented, "the compile command (cmd='pip-compile …') is not in docs/toolchain.md")
        self.assertIn(f"\n#    {documented.group(1)}\n", header)


@NEEDS_YAML
class WorkflowInputsTest(unittest.TestCase):
    def test_ci_and_release_run_the_same_test_command(self):
        ci = load_yaml(".github/workflows/ci.yml")["jobs"]["ci"]["with"]["test-command"]
        release = load_yaml(".github/workflows/release.yml")["jobs"]["release"]["with"]["test-command"]
        self.assertEqual(ci, "bash scripts/test.sh")
        self.assertEqual(release, ci)

    def test_promtool_pin_matches_the_toolchain_page(self):
        env = load_yaml(".github/workflows/ci.yml")["jobs"]["promtool"]["env"]
        version, sha256 = env["PROMTOOL_VERSION"], env["PROMTOOL_SHA256"]
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        self.assertRegex(sha256, r"^[0-9a-f]{64}$")
        toolchain = (ROOT / "docs" / "toolchain.md").read_text(encoding="utf-8")
        self.assertIn(f"prometheus-{version}.linux-amd64.tar.gz", toolchain)
        self.assertIn(sha256, toolchain)

    def test_promtool_job_checks_the_pack_configs_and_the_dashboards(self):
        runs = [step.get("run", "") for step in load_yaml(".github/workflows/ci.yml")["jobs"]["promtool"]["steps"]]
        self.assertIn("python3 scripts/check_pack.py --require-promtool", runs)
        self.assertIn("python3 scripts/lint_dashboards.py --require-promtool", runs)

    def test_exporter_pins_match_the_toolchain_page_and_the_promtool_job(self):
        jobs = load_yaml(".github/workflows/ci.yml")["jobs"]
        env = jobs["exporters"]["env"]
        self.assertEqual((env["PROMETHEUS_VERSION"], env["PROMETHEUS_SHA256"]),
                         (jobs["promtool"]["env"]["PROMTOOL_VERSION"], jobs["promtool"]["env"]["PROMTOOL_SHA256"]))
        toolchain = (ROOT / "docs" / "toolchain.md").read_text(encoding="utf-8")
        for name, prefix in (("prometheus", "PROMETHEUS"), ("json_exporter", "JSON_EXPORTER"),
                             ("blackbox_exporter", "BLACKBOX_EXPORTER")):
            version, sha256 = str(env[f"{prefix}_VERSION"]), env[f"{prefix}_SHA256"]
            with self.subTest(tool=name):
                self.assertRegex(version, r"^\d+\.\d+\.\d+$")
                self.assertRegex(sha256, r"^[0-9a-f]{64}$")
                self.assertIn(f"{name}-{version}.linux-amd64.tar.gz", toolchain)
                self.assertIn(sha256, toolchain)
        runs = [step.get("run", "") for step in jobs["exporters"]["steps"]]
        self.assertIn("python3 scripts/smoke_exporters.py", runs)

    def test_gitleaks_pin_matches_the_secret_scan_and_the_toolchain_page(self):
        script = (ROOT / "scripts" / "test.sh").read_text(encoding="utf-8")
        version = re.search(r"^GITLEAKS_VERSION=(\d+\.\d+\.\d+)$", script, re.M)
        sha256 = re.search(r"^GITLEAKS_SHA256=([0-9a-f]{64})$", script, re.M)
        self.assertIsNotNone(version, "GITLEAKS_VERSION not found in scripts/test.sh")
        self.assertIsNotNone(sha256, "GITLEAKS_SHA256 not found in scripts/test.sh")
        workflow = load_yaml(".github/workflows/reusable-gitleaks.yml")
        inputs = workflow.get("on", workflow.get(True))["workflow_call"]["inputs"]  # YAML 1.1 reads "on" as true
        self.assertEqual(str(inputs["gitleaks-version"]["default"]), version.group(1))
        self.assertEqual(str(inputs["gitleaks-sha256"]["default"]), sha256.group(1))
        toolchain = (ROOT / "docs" / "toolchain.md").read_text(encoding="utf-8")
        self.assertIn(f"gitleaks_{version.group(1)}_linux_x64.tar.gz", toolchain)
        self.assertIn(sha256.group(1), toolchain)


def exported_metrics() -> set[str]:
    """The fxserver_* metric names the pack's configs produce, read with the pack check's reader."""
    names: set[str] = set()
    scrape = check_pack.load_yaml((ROOT / "prometheus" / "scrape" / "fxserver.yml").read_text(encoding="utf-8"))
    for job in scrape["scrape_configs"]:
        for rule in job.get("metric_relabel_configs") or []:
            if rule.get("target_label") == "__name__":
                alternatives = re.fullmatch(r"\w+_\(([\w|]+)\)", rule["regex"]).group(1).split("|")
                names |= {rule["replacement"].replace("$1", alt) for alt in alternatives}
    modules = check_pack.load_yaml((ROOT / "json_exporter" / "config.yml").read_text(encoding="utf-8"))["modules"]
    checker = check_pack.PackChecker(ROOT)
    for module in modules.values():
        for metric in module["metrics"]:
            names |= set(checker.json_metric_names(metric))
    return names


class PackDocsTest(unittest.TestCase):
    def setUp(self):
        self.metrics_doc = (ROOT / "docs" / "metrics.md").read_text(encoding="utf-8")

    def test_every_exported_metric_is_documented(self):
        names = exported_metrics()
        self.assertEqual(len(names), 8, names)
        for name in sorted(names):
            with self.subTest(metric=name):
                self.assertIn(f"`{name}`", self.metrics_doc)

    def test_every_job_and_probe_module_is_documented(self):
        for rel in SCRAPE_FILES:
            for job in check_pack.load_yaml((ROOT / rel).read_text(encoding="utf-8"))["scrape_configs"]:
                with self.subTest(job=job["job_name"]):
                    self.assertIn(f"`{job['job_name']}`", self.metrics_doc)
        blackbox = check_pack.load_yaml((ROOT / "blackbox" / "blackbox.yml").read_text(encoding="utf-8"))
        for module in blackbox["modules"]:
            with self.subTest(module=module):
                self.assertIn(f"`{module}`", self.metrics_doc)

    def test_every_scrape_file_is_documented(self):
        on_disk = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "prometheus" / "scrape").glob("*.y*ml"))
        self.assertEqual(on_disk, sorted(SCRAPE_FILES))

    def test_the_end_to_end_run_expects_exactly_these_metrics(self):
        self.assertEqual(smoke_exporters.EXPECTED_METRICS, exported_metrics())

    def test_the_end_to_end_run_uses_every_scrape_file_but_the_tunnel_probe(self):
        used = {smoke_exporters.SCRAPE_CONFIG, smoke_exporters.VERSIONS_CONFIG}
        self.assertEqual(sorted(p.relative_to(ROOT).as_posix() for p in used),
                         sorted(set(SCRAPE_FILES) - {"prometheus/scrape/tunnel.yml"}))
        self.assertEqual(smoke_exporters.EXPECTED_TARGETS,
                         sum(targets_of(job) for p in used for job in scrape_jobs(p.relative_to(ROOT).as_posix())))


PROMETHEUS_SERIES_PER_TARGET = 5  # up, scrape_duration_seconds, scrape_samples_*, scrape_series_added


# Recorded series, each one per server and thread (rules/fxserver.recording.yml).
RECORDED_PER_THREAD = (
    "server_thread:fxserver_tick_time_seconds:p95_1m",
    "server_thread:fxserver_tick_time_seconds:p99_1m",
    "server_thread:fxserver_tick_time_seconds:mean1m",
    "server_thread:fxserver_tick_time_seconds_count:rate1m",
)


def scrape_jobs(rel: str) -> list[dict]:
    return check_pack.load_yaml((ROOT / rel).read_text(encoding="utf-8"))["scrape_configs"]


def targets_of(job: dict) -> int:
    return sum(len(group["targets"]) for group in job["static_configs"])


def series_limit(rel: str) -> int:
    """Upper bound of the series of one scrape file: per target its sample_limit plus Prometheus' own."""
    return sum(targets_of(job) * (job["sample_limit"] + PROMETHEUS_SERIES_PER_TARGET) for job in scrape_jobs(rel))


def markdown_table(text: str, heading: str) -> list[list[str]]:
    """The body rows of the first table after a heading, as lists of stripped cells."""
    section = text.split(f"\n{heading}\n", 1)[1].split("\n## ", 1)[0]
    rows = [line.strip().strip("|").split("|") for line in section.splitlines() if line.startswith("|")]
    return [[cell.strip() for cell in row] for row in rows[2:]]


def number(text: str) -> int:
    return int(re.search(r"\d[\d,]*", text).group(0).replace(",", ""))


class CardinalityDocTest(unittest.TestCase):
    def setUp(self):
        self.doc = (ROOT / "docs" / "cardinality.md").read_text(encoding="utf-8")
        self.jobs = {job["job_name"]: job for job in scrape_jobs("prometheus/scrape/fxserver.yml")}

    def test_the_measured_table_matches_the_scrape_config(self):
        rows = markdown_table(self.doc, "## Measured: the pack's jobs")
        total = rows.pop()
        targets_per_job: dict[str, int] = {}
        for job_cell, samples, own, limit in rows:
            job = self.jobs[re.match(r"`(\w+)`", job_cell).group(1)]
            targets_per_job[job["job_name"]] = targets_per_job.get(job["job_name"], 0) + 1
            with self.subTest(row=job_cell):
                self.assertEqual(number(limit), job["sample_limit"])
                self.assertEqual(number(own), PROMETHEUS_SERIES_PER_TARGET)
                self.assertLessEqual(number(samples), job["sample_limit"])
        self.assertEqual(targets_per_job, {name: targets_of(job) for name, job in self.jobs.items()})
        self.assertEqual(number(total[0]), smoke_exporters.DEFAULT_JOB_TARGETS)
        self.assertEqual(number(total[1]), sum(number(row[1]) for row in rows))
        self.assertEqual(number(total[2]), PROMETHEUS_SERIES_PER_TARGET * len(rows))
        self.assertIn(f"costs **{number(total[1]) + number(total[2])} series**", self.doc)

    def test_the_budget_table_uses_the_sample_limits_and_adds_up(self):
        rows = {row[0]: row[1] for row in markdown_table(self.doc, "## The whole budget per server")}
        default_jobs = series_limit("prometheus/scrape/fxserver.yml")
        tunnel = series_limit("prometheus/scrape/tunnel.yml")
        versions = series_limit("prometheus/scrape/versions.yml")
        recorded = len(RECORDED_PER_THREAD) * len(smoke_exporters.THREADS)
        self.assertIn(f"at most {default_jobs} by the sample limits", rows["This pack, default jobs"])
        self.assertEqual(rows["This pack, tunnel probe"], f"at most {tunnel}")
        self.assertEqual(rows["This pack, version list"], f"at most {versions}, once per Prometheus")
        self.assertEqual(number(rows["This pack, recording rules"]), recorded)
        reserves = sum(number(series) for part, series in rows.items() if part.startswith("Reserve:"))
        total = default_jobs + tunnel + versions + recorded + reserves
        self.assertEqual(rows["**Total**"], f"**at most {total:,}**")
        self.assertLessEqual(total, 2000)
        measured = number(rows["This pack, default jobs"])
        free = 2000 - measured - recorded - reserves
        text = " ".join(self.doc.split())
        self.assertIn(f"limit of {default_jobs}, and without the optional jobs, {free:,} of the 2,000", text)
        self.assertIn(f"({free - tunnel - versions:,} with the tunnel probe and the version list at their limits)",
                      text)

    def test_the_recording_rules_are_the_ones_counted(self):
        text = (ROOT / "rules" / "fxserver.recording.yml").read_text(encoding="utf-8")
        recorded = set(re.findall(r"^\s*- record: (\S+)$", text, re.M))
        self.assertEqual(recorded, set(RECORDED_PER_THREAD))
        self.assertEqual(set(smoke_exporters.RECORDED), set(RECORDED_PER_THREAD))


class BuildLabelTest(unittest.TestCase):
    def test_the_build_rule_reads_both_version_shapes(self):
        job = {j["job_name"]: j for j in scrape_jobs("prometheus/scrape/fxserver.yml")}["fxserver_json"]
        rule = next(r for r in job["metric_relabel_configs"] if r.get("target_label") == "build")
        self.assertEqual(rule["source_labels"], ["__name__", "version"])
        self.assertEqual(rule["replacement"], "$1")
        for version in ("FXServer-master SERVER v1.0.0.35245 linux", "FXServer-master v1.0.0.35245 linux"):
            with self.subTest(version=version):
                # Prometheus anchors the regex and joins the source labels with ";".
                match = re.fullmatch(rule["regex"], f"fxserver_info;{version}")
                self.assertIsNotNone(match)
                self.assertEqual(match.group(1), "35245")
        self.assertIsNone(re.fullmatch(rule["regex"], "fxserver_info;FXServer-master linux"))


@NEEDS_YAML
class RuleCoverageTest(unittest.TestCase):
    def test_every_rule_file_is_named_in_a_rule_test(self):
        self.assertEqual(rule_files_without_test(ROOT), [])

    def test_a_rule_file_without_a_rule_test_is_reported(self):
        root = temp_dir("gso-rules-")
        (root / "rules").mkdir()
        (root / "tests" / "rules").mkdir(parents=True)
        for name in ("a.yml", "b.yml", "c.yaml"):
            (root / "rules" / name).write_text("groups: []\n", encoding="utf-8")
        (root / "tests" / "rules" / "a.test.yml").write_text(
            "rule_files: [../../rules/a.yml]\ntests: []\n", encoding="utf-8")
        self.assertEqual(rule_files_without_test(root), ["rules/b.yml", "rules/c.yaml"])
        (root / "tests" / "rules" / "rest.test.yaml").write_text(
            "rule_files:\n  - ../../rules/*.yml\n  - ../../rules/c.yaml\ntests: []\n", encoding="utf-8")
        self.assertEqual(rule_files_without_test(root), [])


@unittest.skipUnless(shutil.which("gitleaks"), "gitleaks is not on the PATH")
class CfxKeyRuleTest(unittest.TestCase):
    """Every key-shaped value is built at run time, so no key-shaped string is ever committed."""

    def scan(self, folder: Path) -> list[str]:
        report = temp_dir("gso-gl-report-") / "report.json"  # never written into the scanned folder
        subprocess.run(["gitleaks", "dir", "--no-banner", "--redact", "--exit-code", "0",
                        "--config", str(ROOT / ".gitleaks.toml"), "--report-format", "json",
                        "--report-path", str(report), str(folder)],
                       check=True, capture_output=True, text=True)
        return [f["RuleID"] for f in json.loads(report.read_text(encoding="utf-8") or "[]")]

    def rules_for(self, filename: str, content: str) -> set[str]:
        folder = temp_dir("gso-gl-key-")
        (folder / filename).write_text(content, encoding="utf-8")
        return set(self.scan(folder))

    def test_key_without_inner_underscore_is_found(self):
        """The template's two-part rule cannot see this one; the any-shape rule must."""
        key = KEY_PREFIX + rand(32)
        self.assertIn(ANY_SHAPE_RULE, self.rules_for("secrets.cfg", f'sv_licenseKey "{key}"\n'))
        self.assertIn(ANY_SHAPE_RULE, self.rules_for("notes.txt", f"license key: {key}\n"))

    def test_usual_shape_is_found_by_both_rules(self):
        found = self.rules_for("host_vars.yml", f"fxserver_license_key: {KEY_PREFIX}{rand(20)}_{rand(6)}\n")
        self.assertTrue({"cfx-server-key", ANY_SHAPE_RULE} <= found, found)

    def test_key_in_an_environment_file_is_found(self):
        found = self.rules_for("txadmin.env", f"TXHOST_DEFAULT_CFXKEY={KEY_PREFIX}{rand(24)}\n")
        self.assertIn(ANY_SHAPE_RULE, found)

    def test_key_right_after_a_word_character_is_found(self):
        """`_` and letters are word characters, so a rule that starts with a word boundary misses these."""
        for before in ("KEY_", "LICENSE_KEY_", "x", "9"):
            with self.subTest(before=before):
                self.assertIn(ANY_SHAPE_RULE, self.rules_for("notes.txt", f"{before}{KEY_PREFIX}{rand(30)}\n"))

    def test_documented_placeholders_stay_clean(self):
        content = (
            'sv_licenseKey "CHANGE_ME_LICENSE_KEY"\n'
            "fxserver_license_key: CHANGE_ME_LICENSE_KEY\n"
            'sv_licenseKey "{{ fxserver_license_key }}"\n'
            f"sv_licenseKey {KEY_PREFIX}{'x' * 24}\n"
            f"sv_licenseKey {KEY_PREFIX}{'x' * 12}_{'x' * 6}\n"
            f"# a key looks like {KEY_PREFIX}{'x' * 24}\n"
        )
        self.assertEqual(self.rules_for("server.cfg.example", content), set())

    def test_this_file_stays_clean(self):
        folder = temp_dir("gso-gl-self-")
        shutil.copy(Path(__file__), folder / Path(__file__).name)
        self.assertEqual(self.scan(folder), [])


if __name__ == "__main__":
    unittest.main()
