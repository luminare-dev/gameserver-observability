#!/usr/bin/env python3
"""Checks the Grafana dashboards, and writes their shareable copies.

Files: grafana/dashboards/*.json, the dashboards that Grafana provisions from this repository
(with a data source variable), and grafana/dashboards/shareable/*.json, one copy of each without
template variables, for importing and sharing.

  python3 scripts/lint_dashboards.py [--root DIR] [--require-promtool] [--fix]

Checks:
  parse        every file is a JSON object in the repository's format (two-space indentation,
               final newline) with a uid, a title, panels, "id": null and the classic schema in
               the version of the Grafana the dashboards are checked with (schemaVersion 42,
               the latest of Grafana 13.2.4)
  names        the dashboard title and every row and panel title pass the name check of
               scripts/forbidden_words.py: no platform or vendor mark
  datasource   no hard-coded data source: every panel, query, variable and annotation names the
               data source variable ${datasource} (shareable copies: the import input
               ${DS_PROMETHEUS}), and the data source variable selects none of its own
  variables    only a data source variable and query variables; every $variable in a query is
               one of them or one of Grafana's interval and range variables; a query variable
               keeps no selected value but "All"; shareable copies have no template variable
               and declare their one input
  metrics      every metric a query, variable or annotation reads is listed in docs/metrics.md
               (the first column of its Metric and Series tables)
  aggregation  every series selector is inside an aggregation (sum, max, count, ... without a
               clause or with by (...)), so a panel shows only the labels its query chose
  labels       no label a query matches or groups by, and none a legend shows, could identify
               a player (the names check_pack.py rejects); no text anywhere uses the label
               instance, which holds host addresses
  panels       every panel has a unique id, a title, a place on the 24-column grid that overlaps
               no other panel and, except rows, a description; every query has a unique refId,
               an expression and, unless it is a table query, a legend of its own
  links        no IP address, and links only to this repository
  shareable    every dashboard has a shareable copy, equal to the one --fix writes, and every
               shareable copy has its dashboard
  promtool     promtool check rules parses every query, with the variables replaced by sample
               values, when promtool is on the PATH (--require-promtool: fail when it is not)

--fix writes every dashboard in the repository's format and writes the shareable copies, then
checks them. Exit codes: 0 no findings, 1 findings, 2 usage error. Python 3.10 or newer,
standard library only.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:  # also when run with python3 -I
    sys.path.insert(0, str(SCRIPTS))

from check_pack import IPV4_RE, PLAYER_LABEL_RE  # noqa: E402
from forbidden_words import NAME_RULES  # noqa: E402

DEFAULT_ROOT = SCRIPTS.parent
DASHBOARD_DIR = "grafana/dashboards"
SHAREABLE_DIR = "grafana/dashboards/shareable"
METRICS_DOC = "docs/metrics.md"
METRIC_TABLE_HEADERS = {"Metric", "Series"}

DATASOURCE_TYPE = "prometheus"
SHARE_INPUT = "DS_PROMETHEUS"
SHARE_DATASOURCE = "${" + SHARE_INPUT + "}"
SHARE_UID_SUFFIX = "-shared"
BUILTIN_DATASOURCE = {"type": "grafana", "uid": "-- Grafana --"}  # Grafana's built-in annotations
GRAFANA_VERSION = "13.2.4"  # the Grafana the dashboards are checked with (docs/install.md)
SCHEMA_VERSION = 42  # the latest dashboard schema of that Grafana; a newer one may not load in it
PANEL_NAMES = {"stat": "Stat", "timeseries": "Time series", "heatmap": "Heatmap", "table": "Table",
               "gauge": "Gauge", "bargauge": "Bar gauge", "text": "Text"}
GRID_COLUMNS = 24
UID_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")

# Grafana's own variables a query may use, with the sample values for promtool. A query variable
# is replaced by SAMPLE_VALUE.
BUILTIN_VARIABLES = {"__rate_interval": "1m", "__interval": "1m", "__range": "1h"}
SAMPLE_VALUE = "game-01"
VARIABLE_RE = re.compile(r"\$\{([A-Za-z_]\w*)(?::\w+)?\}|\$([A-Za-z_]\w*)")
LEGEND_LABEL_RE = re.compile(r"\{\{\s*([A-Za-z_]\w*)\s*\}\}")
INSTANCE_RE = re.compile(r"\binstance\b")
URL_RE = re.compile(r"https?://[^\s\"'<>)]+")
ALLOWED_URL_PREFIX = "https://github.com/luminare-dev/gameserver-observability/"
LABEL_VALUES_RE = re.compile(r"\s*label_values\(\s*(?:(?P<expr>.*\S)\s*,\s*)?(?P<label>[A-Za-z_]\w*)\s*\)\s*", re.S)

# --------------------------------------------------------------------------------------------
# PromQL: just enough to find the metrics, the labels and whether each selector is aggregated
# --------------------------------------------------------------------------------------------

# Aggregations whose result has only the labels of their by clause (or none). topk, bottomk,
# limitk and limit_ratio keep every label of the series they pick, so they do not count.
AGGREGATIONS = {"sum", "min", "max", "avg", "group", "stddev", "stdvar", "count", "count_values", "quantile"}
LABEL_KEEPING_AGGREGATIONS = {"topk", "bottomk", "limitk", "limit_ratio"}
GROUPING_KEYWORDS = {"by", "without", "on", "ignoring", "group_left", "group_right"}
KEYWORDS = GROUPING_KEYWORDS | {"bool", "and", "or", "unless", "offset", "atan2", "inf", "nan"}
LABEL_ARGUMENT_FUNCTIONS = {"label_replace", "label_join", "count_values"}

_STRING = r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`[^`]*`'
_TOKEN_RE = re.compile(rf"""
    (?P<ws>\s+)
  | (?P<string>{_STRING})
  | (?P<var>\$\{{[A-Za-z_]\w*(?::\w+)?\}}|\$[A-Za-z_]\w*)
  | (?P<braces>\{{(?:[^{{}}"'`]|{_STRING})*\}})
  | (?P<brackets>\[[^\[\]]*\])
  | (?P<duration>(?:[0-9]+(?:ms|[smhdwy]))+(?![\w:]))
  | (?P<number>0[xX][0-9a-fA-F]+|(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?)
  | (?P<ident>[A-Za-z_:][\w:]*)
  | (?P<op>==|!=|>=|<=|=~|!~|[-+*/%^<>=(),@])
""", re.X)
_MATCHER_RE = re.compile(rf"\s*(([A-Za-z_]\w*)\s*(=~|!~|!=|=)\s*({_STRING}))\s*(?:,|$)")


class PromQLError(ValueError):
    pass


@dataclass
class Token:
    kind: str
    text: str
    start: int
    end: int


@dataclass
class Query:
    metrics: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def tokenize(expr: str) -> list[Token]:
    tokens, pos = [], 0
    while pos < len(expr):
        match = _TOKEN_RE.match(expr, pos)
        if match is None:
            raise PromQLError(f"cannot read the query from {expr[pos:pos + 20]!r}")
        if match.lastgroup != "ws":
            tokens.append(Token(match.lastgroup, match.group(), match.start(), match.end()))
        pos = match.end()
    return tokens


@dataclass
class Matcher:
    label: str
    operator: str
    value: str  # with its quotes
    text: str


def matchers(braces: str) -> list[Matcher]:
    """The matchers of a {...} block."""
    body, found, pos = braces[1:-1], [], 0
    while body[pos:].strip():
        match = _MATCHER_RE.match(body, pos)
        if match is None:
            raise PromQLError(f"cannot read the label matchers {braces!r}")
        found.append(Matcher(match.group(2), match.group(3), match.group(4), match.group(1)))
        pos = match.end()
    return found


def analyse(expr: str) -> Query:
    """The metrics, label names and problems of one PromQL expression."""
    query = Query()
    tokens = tokenize(expr)
    pairs: dict[int, int] = {}
    stack: list[int] = []
    for i, token in enumerate(tokens):
        if token.kind == "op" and token.text == "(":
            stack.append(i)
        elif token.kind == "op" and token.text == ")":
            if not stack:
                raise PromQLError("a ')' has no '('")
            pairs[stack.pop()] = i
    if stack:
        raise PromQLError("a '(' is not closed")
    opens_of = {close: open_ for open_, close in pairs.items()}

    def word(i: int) -> str | None:
        return tokens[i].text.lower() if 0 <= i < len(tokens) and tokens[i].kind == "ident" else None

    def labels_in(open_: int) -> list[str]:
        return [t.text for t in tokens[open_ + 1:pairs[open_]] if t.kind == "ident"]

    def clause_after(close: int) -> tuple[str, list[str]] | None:
        if word(close + 1) in ("by", "without") and close + 2 in pairs:
            return word(close + 1), labels_in(close + 2)
        return None

    # What each pair of parentheses is: a label list, the body of an aggregation (with its
    # clause), the arguments of a function, or plain parentheses.
    kinds: dict[int, tuple] = {}
    for open_ in sorted(pairs):
        before = word(open_ - 1)
        if before in GROUPING_KEYWORDS:
            kinds[open_] = ("labels", before)
        elif before in AGGREGATIONS:
            kinds[open_] = ("aggregation", clause_after(pairs[open_]))
        elif before is not None:
            kinds[open_] = ("function", before)
        elif open_ - 1 in opens_of and kinds.get(opens_of[open_ - 1], ("",))[0] == "labels":
            label_list = opens_of[open_ - 1]  # sum by (labels) (body)
            keyword = kinds[label_list][1]
            if keyword in ("by", "without") and word(label_list - 2) in AGGREGATIONS:
                kinds[open_] = ("aggregation", (keyword, labels_in(label_list)))
            else:
                kinds[open_] = ("plain", None)
        else:
            kinds[open_] = ("plain", None)

    def enclosing(i: int) -> list[int]:
        return [open_ for open_, close in pairs.items() if open_ < i < close]

    for i, token in enumerate(tokens):
        around = enclosing(i)
        if any(kinds[o][0] == "labels" for o in around):
            if token.kind == "ident":
                query.labels.append(token.text)
            continue
        if token.kind == "string" and any(kinds[o][0] == "function" and kinds[o][1] in LABEL_ARGUMENT_FUNCTIONS
                                          for o in around):
            text = token.text[1:-1]
            if re.fullmatch(r"[A-Za-z_]\w*", text):
                query.labels.append(text)
        if token.kind == "braces":
            found = matchers(token.text)
            query.labels.extend(m.label for m in found)
            if "__name__" in (m.label for m in found):
                query.problems.append("matches __name__; name the metric instead")
            if word(i - 1) is None or word(i - 1) in KEYWORDS:
                query.problems.append(f"the selector {token.text} names no metric")
            continue
        if token.kind != "ident" or token.text.lower() in KEYWORDS:
            continue
        following = tokens[i + 1] if i + 1 < len(tokens) else None
        if following is not None and following.kind == "op" and following.text == "(":
            continue  # a function or an aggregation
        if token.text.lower() in AGGREGATIONS | LABEL_KEEPING_AGGREGATIONS and word(i + 1) in ("by", "without"):
            continue  # an aggregation with its clause first: sum by (labels) (...)
        query.metrics.append(token.text)
        clauses = [kinds[o][1] for o in around if kinds[o][0] == "aggregation"]
        if not any(clause is None or clause[0] == "by" for clause in clauses):
            how = "with by (...) instead of without" if clauses else "in sum, max, count or another aggregation"
            query.problems.append(f"{token.text} is not aggregated; wrap it {how}, so that the panel "
                                  "shows only the labels the query chooses")
    return query


def variables_in(text: str) -> list[str]:
    return [a or b for a, b in VARIABLE_RE.findall(text)]


def substitute(expr: str, query_variables: set[str]) -> str:
    """The query with sample values for its variables, as Grafana would send it."""
    def value(match: re.Match) -> str:
        name = match.group(1) or match.group(2)
        if name in BUILTIN_VARIABLES:
            return BUILTIN_VARIABLES[name]
        return SAMPLE_VALUE if name in query_variables else match.group(0)
    return VARIABLE_RE.sub(value, expr)


# --------------------------------------------------------------------------------------------
# Dashboards
# --------------------------------------------------------------------------------------------

def render(doc: object) -> str:
    """The repository's format of a dashboard file."""
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def all_panels(panels: list) -> list[dict]:
    """Every panel, including the panels inside collapsed rows."""
    found = []
    for panel in panels if isinstance(panels, list) else []:
        if isinstance(panel, dict):
            found.append(panel)
            found.extend(all_panels(panel.get("panels") or []))
    return found


def strings(value: object, where: str = ""):
    """(location, text) of every string value and every mapping key."""
    if isinstance(value, str):
        yield where, value
    elif isinstance(value, dict):
        for key, item in value.items():
            loc = f"{where}.{key}" if where else str(key)
            yield loc, str(key)
            yield from strings(item, loc)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from strings(item, f"{where}[{index}]")


def template_variables(doc: dict) -> list[dict]:
    templating = doc.get("templating") if isinstance(doc.get("templating"), dict) else {}
    found = templating.get("list") or []
    return [v for v in found if isinstance(v, dict)] if isinstance(found, list) else []


def datasource_references(doc: dict) -> set[str]:
    """How queries refer to the dashboard's data source variable: ${name} and $name."""
    names = [v.get("name") for v in template_variables(doc) if v.get("type") == "datasource"]
    return {ref for name in names if isinstance(name, str) for ref in ("${" + name + "}", "$" + name)}


class ShareableError(ValueError):
    pass


def drop_variable_matchers(expr: str, names: list[str]) -> str:
    """The query without its label matchers on the given variables, e.g. server=~"$server"."""
    def is_variable(matcher: Matcher) -> bool:
        match = VARIABLE_RE.fullmatch(matcher.value[1:-1])
        return matcher.operator in ("=", "=~") and match is not None and (match.group(1) or match.group(2)) in names
    parts, last = [], 0
    for token in tokenize(expr):
        if token.kind == "braces":
            kept = [m.text for m in matchers(token.text) if not is_variable(m)]
            parts += [expr[last:token.start], "{" + ", ".join(kept) + "}" if kept else ""]
            last = token.end
    expr = "".join(parts) + expr[last:]
    left = [n for n in variables_in(expr) if n in names]
    if left:
        raise ShareableError(f"${left[0]} is used outside a label matcher of the form label=~\"${left[0]}\", "
                             f"so the shareable copy cannot drop it: {expr!r}")
    return expr


def make_shareable(doc: dict) -> dict:
    """The variable-free copy of a dashboard: the data source becomes the import input
    ${DS_PROMETHEUS}, the matchers on query variables are dropped, so the copy shows every game
    server, and the copy gets its own uid, so that importing it never replaces the dashboard."""
    shared = copy.deepcopy(doc)
    references = datasource_references(doc)
    query_variables = [v["name"] for v in template_variables(doc)
                       if v.get("type") != "datasource" and isinstance(v.get("name"), str)]
    def fix(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "datasource" and isinstance(value, dict) and value.get("uid") in references:
                    node[key] = {"type": value.get("type"), "uid": SHARE_DATASOURCE}
                elif key == "expr" and isinstance(value, str):
                    node[key] = drop_variable_matchers(value, query_variables)
                else:
                    fix(value)
        elif isinstance(node, list):
            for item in node:
                fix(item)

    fix(shared)
    shared["id"] = None
    shared["uid"] = f"{doc.get('uid')}{SHARE_UID_SUFFIX}"
    shared["templating"] = {"list": []}
    panel_types = []
    for panel in all_panels(doc.get("panels") or []):
        if panel.get("type") not in (None, "row") and panel["type"] not in panel_types:
            panel_types.append(panel["type"])
    requires = [{"type": "grafana", "id": "grafana", "name": "Grafana", "version": GRAFANA_VERSION},
                {"type": "datasource", "id": DATASOURCE_TYPE, "name": "Prometheus", "version": "1.0.0"}]
    requires += [{"type": "panel", "id": t, "name": PANEL_NAMES.get(t, t), "version": ""} for t in sorted(panel_types)]
    inputs = [{"name": SHARE_INPUT, "label": "Prometheus", "description": "Data source with the pack's metrics",
               "type": "datasource", "pluginId": DATASOURCE_TYPE, "pluginName": "Prometheus"}]
    return {"__inputs": inputs, "__elements": {}, "__requires": requires, **shared}


def documented_metrics(root: Path) -> set[str]:
    """The metric names in the first column of the Metric and Series tables of docs/metrics.md."""
    names: set[str] = set()
    header = None
    for line in (root / METRICS_DOC).read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            header = None
            continue
        first = line.strip().strip("|").split("|")[0].strip()
        if header is None:
            header = first
        elif header in METRIC_TABLE_HEADERS and not set(first) <= set("-: "):
            names.update(re.findall(r"`([A-Za-z_:][A-Za-z0-9_:]*)`", first))
    return names


@dataclass(frozen=True)
class Finding:
    path: str
    check: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: [{self.check}] {self.message}"


class DashboardLinter:
    def __init__(self, root: Path):
        self.root = root
        self.findings: list[Finding] = []
        self.files: dict[str, dict] = {}
        self.queries: list[tuple[str, str, str, set[str]]] = []  # (file, where, expr, query variables)
        self.metrics = documented_metrics(root) if (root / METRICS_DOC).is_file() else set()

    def add(self, path: str, check: str, message: str) -> None:
        self.findings.append(Finding(path, check, message))

    # -- files ----------------------------------------------------------------------------
    def dashboard_files(self) -> tuple[list[Path], list[Path]]:
        def glob(folder: str) -> list[Path]:
            return sorted(p for p in (self.root / folder).glob("*.json") if p.is_file())
        return glob(DASHBOARD_DIR), glob(SHAREABLE_DIR)

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def load(self, path: Path) -> dict | None:
        rel = self.rel(path)
        try:
            text = path.read_text(encoding="utf-8")
            doc = json.loads(text)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            self.add(rel, "parse", f"not valid JSON: {exc}")
            return None
        if not isinstance(doc, dict):
            self.add(rel, "parse", "the file must hold a JSON object")
            return None
        if text != render(doc):
            self.add(rel, "parse", "not in the repository's format (two-space indentation, final newline); "
                                   "run python3 scripts/lint_dashboards.py --fix")
        self.files[rel] = doc
        return doc

    # -- one dashboard ----------------------------------------------------------------------
    def check_dashboard(self, rel: str, doc: dict, shareable: bool) -> None:
        for key, kind in (("uid", str), ("title", str), ("panels", list), ("schemaVersion", int)):
            if not isinstance(doc.get(key), kind) or (kind is str and not doc[key].strip()):
                self.add(rel, "parse", f"{key} is missing or not a {kind.__name__}")
        if isinstance(doc.get("schemaVersion"), int) and doc["schemaVersion"] != SCHEMA_VERSION:
            self.add(rel, "parse", f"schemaVersion {doc['schemaVersion']}: the dashboards are checked with Grafana "
                                   f"{GRAFANA_VERSION}, whose schema is {SCHEMA_VERSION}")
        if doc.get("id") is not None:
            self.add(rel, "parse", '"id" must be null: Grafana gives provisioned and imported dashboards their own')
        if isinstance(doc.get("uid"), str) and not UID_RE.fullmatch(doc["uid"]):
            self.add(rel, "parse", f"uid {doc['uid']!r} must be 1 to 40 letters, digits, '-' or '_'")
        panels = all_panels(doc.get("panels") or [])
        self.check_names(rel, doc, panels)
        self.check_variables(rel, doc, shareable)
        self.check_panels(rel, doc, panels, shareable)
        self.check_annotations(rel, doc, shareable)
        self.check_text(rel, doc)

    def check_names(self, rel: str, doc: dict, panels: list[dict]) -> None:
        titles = [("dashboard title", doc.get("title"))]
        titles += [(f"panel {p.get('id')} title", p.get("title")) for p in panels]
        for where, title in titles:
            if not isinstance(title, str):
                continue
            for rule in NAME_RULES:
                if rule.regex.search(title.casefold()):
                    self.add(rel, "names", f"{where} {title!r} contains the mark {rule.label!r}; "
                                           "platform names belong in descriptions")

    def datasource_ok(self, value: object, shareable: bool, references: set[str]) -> bool:
        if not isinstance(value, dict) or value.get("type") != DATASOURCE_TYPE or set(value) != {"type", "uid"}:
            return False
        return value["uid"] == SHARE_DATASOURCE if shareable else value["uid"] in references

    def expected_datasource(self, shareable: bool) -> str:
        return f'{{"type": "{DATASOURCE_TYPE}", "uid": "{SHARE_DATASOURCE if shareable else "${datasource}"}"}}'

    def check_variables(self, rel: str, doc: dict, shareable: bool) -> None:
        variables = template_variables(doc)
        if shareable:
            if variables:
                self.add(rel, "variables", "a shareable copy has no template variables")
            inputs = doc.get("__inputs")
            if not (isinstance(inputs, list) and len(inputs) == 1 and isinstance(inputs[0], dict)
                    and inputs[0].get("name") == SHARE_INPUT and inputs[0].get("type") == "datasource"
                    and inputs[0].get("pluginId") == DATASOURCE_TYPE):
                self.add(rel, "variables", f"__inputs must declare exactly one data source input, {SHARE_INPUT}")
            return
        kinds = [v.get("type") for v in variables]
        if kinds.count("datasource") != 1:
            self.add(rel, "variables", "needs exactly one data source variable (type datasource)")
        references = datasource_references(doc)
        names = set()
        for variable in variables:
            name, kind = variable.get("name"), variable.get("type")
            where = f"variable {name}"
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_]\w*", name) or name in names:
                self.add(rel, "variables", f"{where}: the name is missing, invalid or used twice")
            names.add(name)
            current = variable.get("current")
            if kind == "datasource":
                if variable.get("query") != DATASOURCE_TYPE:
                    self.add(rel, "variables", f'{where}: query must be "{DATASOURCE_TYPE}"')
                if current not in (None, {}) or variable.get("options") not in (None, []):
                    self.add(rel, "datasource", f"{where}: current and options must be empty, so that Grafana "
                                                "selects the viewer's data source instead of a stored uid")
            elif kind == "query":
                if not self.datasource_ok(variable.get("datasource"), False, references):
                    self.add(rel, "datasource", f"{where}: datasource must be {self.expected_datasource(False)}")
                query = variable.get("query")
                expr = query.get("query") if isinstance(query, dict) else query
                self.check_variable_query(rel, where, expr)
                selected = current.get("value") if isinstance(current, dict) else None
                if current not in (None, {}) and selected not in ("$__all", ["$__all"]):
                    self.add(rel, "variables", f"{where}: keep no selected value but All (it would show one of "
                                               "your servers to everyone who opens the file)")
                if variable.get("options") not in (None, []):
                    self.add(rel, "variables", f"{where}: options must be empty; Grafana reads them from the data")
            else:
                self.add(rel, "variables", f"{where}: type {kind!r}; only datasource and query variables are used")

    def check_variable_query(self, rel: str, where: str, expr: object) -> None:
        match = LABEL_VALUES_RE.fullmatch(expr) if isinstance(expr, str) else None
        if match is None:
            self.add(rel, "variables", f"{where}: the query must be label_values(<selector>, <label>)")
            return
        label = match.group("label")
        if PLAYER_LABEL_RE.fullmatch(label):
            self.add(rel, "labels", f"{where}: label {label!r} could identify a player")
        if match.group("expr"):
            self.check_expr(rel, where, match.group("expr"), aggregated=False)

    def check_panels(self, rel: str, doc: dict, panels: list[dict], shareable: bool) -> None:
        references = datasource_references(doc)
        query_variables = {v.get("name") for v in template_variables(doc) if v.get("type") == "query"}
        ids: set[object] = set()
        for panel in panels:
            pid, kind = panel.get("id"), panel.get("type")
            where = f"panel {pid} ({panel.get('title')!r})"
            if not isinstance(pid, int) or pid in ids:
                self.add(rel, "panels", f"{where}: id must be a number used by no other panel")
            ids.add(pid)
            if not isinstance(panel.get("title"), str) or not panel["title"].strip():
                self.add(rel, "panels", f"{where}: needs a title")
            if kind != "row" and (not isinstance(panel.get("description"), str) or not panel["description"].strip()):
                self.add(rel, "panels", f"{where}: needs a description that says what it shows and where from")
            targets = panel.get("targets")
            if kind == "row":
                continue
            if not isinstance(targets, list) or not targets:
                self.add(rel, "panels", f"{where}: has no queries")
                continue
            if not self.datasource_ok(panel.get("datasource"), shareable, references):
                self.add(rel, "datasource", f"{where}: datasource must be {self.expected_datasource(shareable)}")
            refs: set[object] = set()
            for target in targets:
                if not isinstance(target, dict):
                    self.add(rel, "panels", f"{where}: a query is not an object")
                    continue
                ref = target.get("refId")
                twhere = f"{where} query {ref}"
                if not isinstance(ref, str) or ref in refs:
                    self.add(rel, "panels", f"{twhere}: refId must be set and unique in the panel")
                refs.add(ref)
                if "datasource" in target and not self.datasource_ok(target["datasource"], shareable, references):
                    self.add(rel, "datasource", f"{twhere}: datasource must be {self.expected_datasource(shareable)}")
                expr = target.get("expr")
                if not isinstance(expr, str) or not expr.strip():
                    self.add(rel, "panels", f"{twhere}: has no expression")
                    continue
                legend = target.get("legendFormat")
                if target.get("format") != "table" and (not isinstance(legend, str) or legend in ("", "__auto")):
                    self.add(rel, "panels", f"{twhere}: set a legend (legendFormat); Grafana's own legend shows "
                                            "every label of the series")
                for label in LEGEND_LABEL_RE.findall(legend if isinstance(legend, str) else ""):
                    if PLAYER_LABEL_RE.fullmatch(label):
                        self.add(rel, "labels", f"{twhere}: the legend shows label {label!r}, which could "
                                                "identify a player")
                self.check_expr(rel, twhere, expr, query_variables=query_variables, shareable=shareable)
        self.check_grid(rel, doc.get("panels") or [])

    def check_grid(self, rel: str, panels: list) -> None:
        placed: list[tuple[int, int, int, int, object]] = []
        for panel in [p for p in panels if isinstance(p, dict)]:
            grid = panel.get("gridPos")
            where = f"panel {panel.get('id')}"
            if not isinstance(grid, dict) or not all(isinstance(grid.get(k), int) for k in "hwxy"):
                self.add(rel, "panels", f"{where}: gridPos needs h, w, x and y")
                continue
            x, y, w, h = grid["x"], grid["y"], grid["w"], grid["h"]
            if x < 0 or y < 0 or w < 1 or h < 1 or x + w > GRID_COLUMNS:
                self.add(rel, "panels", f"{where}: gridPos {grid} is outside the {GRID_COLUMNS}-column grid")
                continue
            for ox, oy, ow, oh, other in placed:
                if x < ox + ow and ox < x + w and y < oy + oh and oy < y + h:
                    self.add(rel, "panels", f"{where}: overlaps panel {other}")
            placed.append((x, y, w, h, panel.get("id")))
            if panel.get("type") == "row" and panel.get("panels"):
                self.check_grid(rel, panel["panels"])

    def check_annotations(self, rel: str, doc: dict, shareable: bool) -> None:
        annotations = doc.get("annotations") if isinstance(doc.get("annotations"), dict) else {}
        references = datasource_references(doc)
        query_variables = {v.get("name") for v in template_variables(doc) if v.get("type") == "query"}
        for annotation in annotations.get("list") or []:
            where = f"annotation {annotation.get('name')!r}" if isinstance(annotation, dict) else "annotation"
            if not isinstance(annotation, dict):
                self.add(rel, "parse", f"{where} is not an object")
                continue
            if annotation.get("builtIn") == 1 and annotation.get("datasource") == BUILTIN_DATASOURCE:
                continue
            if not self.datasource_ok(annotation.get("datasource"), shareable, references):
                self.add(rel, "datasource", f"{where}: datasource must be {self.expected_datasource(shareable)}")
            expr = annotation.get("expr")
            if not isinstance(expr, str) or not expr.strip():
                self.add(rel, "panels", f"{where}: has no expression")
                continue
            for key in ("titleFormat", "textFormat"):
                for label in LEGEND_LABEL_RE.findall(str(annotation.get(key) or "")):
                    if PLAYER_LABEL_RE.fullmatch(label):
                        self.add(rel, "labels", f"{where}: {key} shows label {label!r}, which could identify a player")
            for label in str(annotation.get("tagKeys") or "").split(","):
                if label.strip() and PLAYER_LABEL_RE.fullmatch(label.strip()):
                    self.add(rel, "labels", f"{where}: tagKeys shows label {label.strip()!r}, which could "
                                            "identify a player")
            self.check_expr(rel, where, expr, query_variables=query_variables, shareable=shareable)

    def check_expr(self, rel: str, where: str, expr: str, query_variables: set | None = None,
                   shareable: bool = False, aggregated: bool = True) -> None:
        query_variables = query_variables or set()
        allowed = set(BUILTIN_VARIABLES) | (set() if shareable else query_variables)
        for name in variables_in(expr):
            if name not in allowed:
                self.add(rel, "variables", f"{where}: ${name} is not a variable of this dashboard")
        try:
            query = analyse(expr)
        except PromQLError as exc:
            self.add(rel, "parse", f"{where}: {exc}")
            return
        for metric in query.metrics:
            if metric not in self.metrics:
                self.add(rel, "metrics", f"{where}: metric {metric!r} is not in {METRICS_DOC}")
        for label in query.labels:
            if PLAYER_LABEL_RE.fullmatch(label):
                self.add(rel, "labels", f"{where}: label {label!r} could identify a player")
        for problem in query.problems:
            if aggregated or "not aggregated" not in problem:
                self.add(rel, "aggregation" if "not aggregated" in problem else "parse", f"{where}: {problem}")
        self.queries.append((rel, where, expr, set(query_variables)))

    def check_text(self, rel: str, doc: dict) -> None:
        for where, text in strings(doc):
            if INSTANCE_RE.search(text):
                self.add(rel, "labels", f"{where}: uses 'instance', which holds host addresses; group by server "
                                        "and module instead")
            for match in IPV4_RE.finditer(text):
                self.add(rel, "links", f"{where}: IP address {match.group(1)}")
            for url in URL_RE.findall(text):
                if not url.startswith(ALLOWED_URL_PREFIX):
                    self.add(rel, "links", f"{where}: link {url} does not point to this repository")

    # -- shareable copies --------------------------------------------------------------------
    def check_shareable(self, dashboards: dict[str, dict], shareables: list[Path]) -> None:
        expected = {f"{SHAREABLE_DIR}/{Path(rel).name}": rel for rel in dashboards}
        for path in shareables:
            if self.rel(path) not in expected:
                self.add(self.rel(path), "shareable", f"no dashboard {DASHBOARD_DIR}/{path.name} to be made from")
        uids: dict[str, str] = {}
        for share_rel, rel in expected.items():
            doc = dashboards[rel]
            for uid in (doc.get("uid"), f"{doc.get('uid')}{SHARE_UID_SUFFIX}"):
                if isinstance(uid, str) and uid in uids:
                    self.add(rel, "parse", f"uid {uid!r} is also used by {uids[uid]}")
                uids[str(uid)] = rel
            try:
                wanted = render(make_shareable(doc))
            except (ShareableError, PromQLError) as exc:
                self.add(rel, "shareable", str(exc))
                continue
            path = self.root / share_rel
            if not path.is_file() or path.read_text(encoding="utf-8") != wanted:
                self.add(share_rel, "shareable", f"missing or not the copy of {rel}; "
                                                 "run python3 scripts/lint_dashboards.py --fix")

    def fix(self) -> list[str]:
        """Write every dashboard in the repository's format and its shareable copy."""
        written = []
        dashboards, _ = self.dashboard_files()
        for path in dashboards:
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                text = render(doc)
                shared = render(make_shareable(doc)) if isinstance(doc, dict) else None
            except (ValueError, ShareableError) as exc:
                self.add(self.rel(path), "parse", f"not fixed: {exc}")
                continue
            for target, content in ((path, text), (self.root / SHAREABLE_DIR / path.name, shared)):
                if content is None:
                    continue
                if not target.is_file() or target.read_text(encoding="utf-8") != content:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
                    written.append(self.rel(target))
        return written

    # -- promtool ---------------------------------------------------------------------------
    def run_promtool(self, required: bool) -> str:
        promtool = shutil.which("promtool")
        if promtool is None:
            if required:
                self.add("promtool", "promtool", "promtool is not on the PATH")
                return "missing"
            return "skipped (promtool is not on the PATH)"
        if not self.queries:
            return "no queries"
        rules, names = [], {}
        for index, (rel, where, expr, query_variables) in enumerate(self.queries, start=1):
            record = f"dashboard_check:query_{index}"
            names[record] = f"{rel}: {where}"
            rules.append({"record": record, "expr": substitute(expr, query_variables)})
        with tempfile.TemporaryDirectory(prefix="lint-dashboards-") as tmp:
            path = Path(tmp) / "queries.yml"  # JSON is valid YAML
            path.write_text(json.dumps({"groups": [{"name": "dashboard-queries", "rules": rules}]}, indent=2),
                            encoding="utf-8")
            result = subprocess.run([promtool, "check", "rules", str(path)], capture_output=True, text=True)
        if result.returncode != 0:
            output = (result.stdout + result.stderr).strip()
            failing = [names[n] for n in sorted(set(re.findall(r"dashboard_check:query_\d+", output)), key=len)]
            self.add("promtool", "promtool", "promtool check rules failed for "
                                             f"{'; '.join(failing) or 'the queries'}: {output.replace(chr(10), ' | ')}")
            return "failed"
        return f"{len(self.queries)} quer{'y' if len(self.queries) == 1 else 'ies'} passed promtool check rules"

    # -- all --------------------------------------------------------------------------------
    def run(self, require_promtool: bool = False) -> str:
        if not (self.root / METRICS_DOC).is_file():
            self.add(METRICS_DOC, "metrics", "the metrics reference is missing")
        dashboard_paths, shareable_paths = self.dashboard_files()
        if not dashboard_paths:
            self.add(DASHBOARD_DIR, "parse", "no dashboard found")
        dashboards: dict[str, dict] = {}
        for paths, shareable in ((dashboard_paths, False), (shareable_paths, True)):
            for path in paths:
                doc = self.load(path)
                if doc is None:
                    continue
                rel = self.rel(path)
                if not shareable:
                    dashboards[rel] = doc
                try:
                    self.check_dashboard(rel, doc, shareable)
                except (AttributeError, TypeError, KeyError) as exc:  # a value of an unexpected type
                    self.add(rel, "parse", f"unexpected structure ({exc})")
        self.check_shareable(dashboards, shareable_paths)
        return self.run_promtool(require_promtool)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the Grafana dashboards and their shareable copies.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="repository root (default: this checkout)")
    parser.add_argument("--require-promtool", action="store_true",
                        help="fail when promtool is not on the PATH instead of skipping that check")
    parser.add_argument("--fix", action="store_true",
                        help="write the dashboards in the repository's format and their shareable copies first")
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        print(f"lint_dashboards: {args.root} is not a folder", file=sys.stderr)
        return 2
    root = args.root.resolve()
    if args.fix:
        fixer = DashboardLinter(root)
        for rel in fixer.fix():
            print(f"wrote {rel}")
        for finding in fixer.findings:
            print(finding)
    linter = DashboardLinter(root)
    promtool = linter.run(require_promtool=args.require_promtool)
    for finding in linter.findings:
        print(finding)
    print(f"lint_dashboards: {len(linter.findings)} finding(s) in {len(linter.files)} file(s), "
          f"{len(linter.queries)} queries; promtool: {promtool}")
    return 1 if linter.findings else 0


if __name__ == "__main__":
    sys.exit(main())
