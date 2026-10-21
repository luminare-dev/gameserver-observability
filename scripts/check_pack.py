#!/usr/bin/env python3
"""Checks the pack's collection configs: they parse, and they keep to the privacy rules.

Files: prometheus/**/*.yml (scrape configs, and the demo stack's main config, which includes them
by scrape_config_files), json_exporter/*.yml and blackbox/*.yml.

  python3 scripts/check_pack.py [--root DIR] [--require-promtool] [--allow-any-address]

Checks:
  parse        every file is valid YAML (of the subset below) with the expected top-level shape;
               json_exporter keys are checked against its schema (json_exporter itself ignores
               unknown keys, so a typo would silently drop a metric)
  players      no value anywhere names players.json: player counts come from dynamic.json
  labels       no label that a scrape job, relabel rule or exporter module adds has a per-player
               name (name, player, identifier, license, ip, endpoint, ping, id, ...); labelmap
               and honor_labels are not used, because they pass on labels nobody reviewed
  perf         a job that scrapes /perf/ keeps only listed metric names and drops the server's
               name label, which an earlier rule copies to thread
  secrets      passwords, tokens and credentials only through *_file settings, never inline;
               in every header map (headers of json_exporter and blackbox modules, http_headers
               of Prometheus jobs and of the exporters' HTTP clients) no inline secrets and no
               inline value for a header named like a credential (Authorization, cookie, token)
  addresses    IP addresses only from loopback or the documentation ranges, so that no real
               address gets into the repository (--allow-any-address: skip this check, for a
               copy of the configs that holds the addresses of your servers)
  modules      every module a scrape job asks json_exporter (port 7979) or blackbox_exporter
               (port 9115) for exists in that exporter's config; job names are unique
  promtool     "promtool check config" accepts every Prometheus file, when promtool is on the
               PATH (--require-promtool: fail when it is not)

Exit codes: 0 no findings, 1 findings, 2 usage error. Python 3.10 or newer, standard library
only, so it runs before anything is installed. That is why it brings its own reader for the YAML
subset the configs use: block mappings and sequences, flow sequences and mappings on one line,
plain and quoted scalars, comments. Anything else (anchors, tags, block scalars, multi-line flow
collections, YAML 1.1 values such as yes/no or 0755) is reported as a parse finding instead of
being guessed at; the unit tests compare the reader with PyYAML on every config file.
"""

from __future__ import annotations

import argparse
import fnmatch
import ipaddress
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
JSON_EXPORTER_PORT = "7979"
BLACKBOX_PORT = "9115"

# Label names that would tie a series to a player (exact names, case-insensitive).
PLAYER_LABEL_RE = re.compile(
    r"(?i)(names?|player(s|_?(name|id|ids))?|identifiers?|license\d*|steam(id)?|discord|xbl|live|fivem|"
    r"ip|ip_?address|address|endpoint|ping|id|guid|hwid|tokens?|nick(name)?)"
)
SECRET_KEYS = {"password", "bearer_token", "credentials", "client_secret", "secret", "token"}
SECRET_HEADER_RE = re.compile(r"(?i).*(authorization|token|secret|password|api.?key|cookie).*")
ALLOWED_NETWORKS = [ipaddress.ip_network(n) for n in
                    ("127.0.0.0/8", "::1/128", "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")]
IPV4_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
METRIC_NAME_RE = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]*")
LABEL_NAME_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")

JSON_MODULE_KEYS = {"headers", "metrics", "http_client_config", "body", "valid_status_codes"}
JSON_METRIC_KEYS = {"name", "path", "labels", "type", "valuetype", "epochtimestamp", "help", "values",
                    "allow_missing_key"}
PROMETHEUS_TOP_KEYS = {"global", "scrape_configs", "scrape_config_files", "rule_files", "alerting",
                       "remote_write", "remote_read", "storage", "tracing", "runtime", "otlp"}
BLACKBOX_PROBERS = {"http", "tcp", "icmp", "dns", "grpc", "websocket", "unix"}


# --------------------------------------------------------------------------------------------
# YAML subset reader
# --------------------------------------------------------------------------------------------

class YamlError(ValueError):
    def __init__(self, line: int, message: str):
        super().__init__(f"line {line}: {message}")
        self.line = line


@dataclass
class _Line:
    number: int
    indent: int
    text: str  # without indentation and comment


_PLAIN_START_FORBIDDEN = set("[]{},#&*!|>'\"%@`")
_UNEXPECTED_INDENT = "unexpected indentation (values that continue on the next line are not supported)"
_YAML11_BOOL_RE = re.compile(r"(?i)(y|n|yes|no|on|off)")
_INT_RE = re.compile(r"[-+]?(0|[1-9][0-9]*)")
_FLOAT_RE = re.compile(r"[-+]?[0-9]+\.[0-9]*|\.[0-9]+")
# Plain scalars that PyYAML would turn into something else than a string or a decimal number.
_AMBIGUOUS_RE = re.compile(
    r"[-+]?0[0-9_]+|[-+]?0[box][0-9a-fA-F_]+|[-+]?[0-9][0-9_]*(:[0-5]?[0-9])+(\.[0-9_]*)?|"
    r"[-+]?[0-9][0-9_]*_[0-9_]*(\.[0-9_]*)?|[-+]?([0-9][0-9_]*)?\.[0-9_]+[eE][-+]?[0-9]+|"
    r"[-+]?[0-9]+(\.[0-9]*)?[eE][-+]?[0-9]+|[-+]\.[0-9]+|[-+]?\.(inf|Inf|INF)|\.(nan|NaN|NAN)|"
    r"[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}([Tt ].*)?|<<|="
)


def _strip_comment(raw: str, number: int) -> str:
    """The line without its comment; quotes are respected, a '#' starts a comment after a blank."""
    quote = None
    i = 0
    while i < len(raw):
        ch = raw[i]
        if quote == "'":
            if ch == "'":
                if i + 1 < len(raw) and raw[i + 1] == "'":
                    i += 1
                else:
                    quote = None
        elif quote == '"':
            if ch == "\\":
                i += 1
            elif ch == '"':
                quote = None
        elif ch in "'\"" and (i == 0 or raw[i - 1] in " \t[{,:-"):
            quote = ch
        elif ch == "#" and (i == 0 or raw[i - 1] in " \t"):
            return raw[:i].rstrip()
        i += 1
    if quote is not None:
        raise YamlError(number, "quoted scalar is not closed on this line")
    return raw.rstrip()


def _scan_lines(text: str) -> list[_Line]:
    lines = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw[: len(raw) - len(raw.lstrip(" \t"))]:
            raise YamlError(number, "tab in indentation")
        content = _strip_comment(raw, number)
        stripped = content.lstrip(" ")
        if not stripped:
            continue
        if stripped in ("---", "...") or stripped.startswith(("--- ", "%")):
            if lines or stripped != "---":
                raise YamlError(number, "document markers and directives are not supported")
            continue
        lines.append(_Line(number, len(content) - len(stripped), stripped))
    return lines


def _resolve_plain(token: str, number: int) -> object:
    if token in ("", "~", "null", "Null", "NULL"):
        return None
    if token in ("true", "True", "TRUE"):
        return True
    if token in ("false", "False", "FALSE"):
        return False
    if _YAML11_BOOL_RE.fullmatch(token):
        raise YamlError(number, f"'{token}' is a boolean in YAML 1.1; write true/false or quote it")
    if _INT_RE.fullmatch(token):
        return int(token)
    if _FLOAT_RE.fullmatch(token):
        return float(token)
    if _AMBIGUOUS_RE.fullmatch(token):
        raise YamlError(number, f"'{token}' is not a plain string in YAML; quote it")
    return token


_ESCAPES = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r",
            "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\x85", "_": "\xa0"}


class _Inline:
    """Parser for one line's value: quoted and plain scalars, flow sequences and mappings."""

    def __init__(self, text: str, number: int):
        self.text = text
        self.pos = 0
        self.number = number

    def error(self, message: str) -> YamlError:
        return YamlError(self.number, message)

    def skip_spaces(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos] == " ":
            self.pos += 1

    def parse_document_value(self) -> object:
        value = self.parse_value(flow=False)
        self.skip_spaces()
        if self.pos != len(self.text):
            raise self.error(f"unexpected text after the value: {self.text[self.pos:]!r}")
        return value

    def parse_value(self, flow: bool) -> object:
        self.skip_spaces()
        if self.pos >= len(self.text):
            return None
        ch = self.text[self.pos]
        if ch == "[":
            return self.parse_flow_sequence()
        if ch == "{":
            return self.parse_flow_mapping()
        if ch == '"':
            return self.parse_double()
        if ch == "'":
            return self.parse_single()
        return self.parse_plain(flow)

    def parse_double(self) -> str:
        self.pos += 1
        out = []
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch == '"':
                self.pos += 1
                return "".join(out)
            if ch == "\\":
                self.pos += 1
                esc = self.text[self.pos: self.pos + 1]
                if esc in _ESCAPES:
                    out.append(_ESCAPES[esc])
                    self.pos += 1
                elif esc in ("x", "u", "U"):
                    width = {"x": 2, "u": 4, "U": 8}[esc]
                    digits = self.text[self.pos + 1: self.pos + 1 + width]
                    if len(digits) != width or not re.fullmatch(r"[0-9a-fA-F]+", digits):
                        raise self.error(f"bad \\{esc} escape")
                    out.append(chr(int(digits, 16)))
                    self.pos += 1 + width
                else:
                    raise self.error(f"unknown escape \\{esc}")
                continue
            out.append(ch)
            self.pos += 1
        raise self.error("double-quoted scalar is not closed")

    def parse_single(self) -> str:
        self.pos += 1
        out = []
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch == "'":
                if self.text[self.pos + 1: self.pos + 2] == "'":
                    out.append("'")
                    self.pos += 2
                    continue
                self.pos += 1
                return "".join(out)
            out.append(ch)
            self.pos += 1
        raise self.error("single-quoted scalar is not closed")

    def parse_plain(self, flow: bool) -> object:
        start = self.pos
        ch = self.text[start]
        nxt = self.text[start + 1: start + 2]
        if ch in _PLAIN_START_FORBIDDEN or (ch in "-?:" and nxt in ("", " ")):
            raise self.error(f"unsupported or unexpected YAML here: {self.text[start:]!r}")
        stops = ",[]{}" if flow else ""
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch in stops:
                break
            if ch == ":" and (flow or self.text[self.pos + 1: self.pos + 2] in ("", " ")):
                if flow:
                    raise self.error("':' inside a plain scalar in a flow collection; quote the value")
                raise self.error("mapping value where a scalar was expected; quote the value")
            if ch == "#" and self.text[self.pos - 1] == " ":
                break
            self.pos += 1
        token = self.text[start:self.pos].rstrip(" ")
        return _resolve_plain(token, self.number)

    def expect(self, ch: str) -> None:
        self.skip_spaces()
        if self.text[self.pos: self.pos + 1] != ch:
            raise self.error(f"expected '{ch}' (flow collections must close on the same line)")
        self.pos += 1

    def parse_flow_sequence(self) -> list:
        self.pos += 1
        items: list = []
        self.skip_spaces()
        if self.text[self.pos: self.pos + 1] == "]":
            self.pos += 1
            return items
        while True:
            items.append(self.parse_value(flow=True))
            self.skip_spaces()
            if self.text[self.pos: self.pos + 1] == ",":
                self.pos += 1
                continue
            self.expect("]")
            return items

    def parse_flow_mapping(self) -> dict:
        self.pos += 1
        out: dict = {}
        self.skip_spaces()
        if self.text[self.pos: self.pos + 1] == "}":
            self.pos += 1
            return out
        while True:
            self.skip_spaces()
            key = self.parse_flow_key()
            if key in out:
                raise self.error(f"duplicate key {key!r}")
            self.skip_spaces()
            out[key] = self.parse_value(flow=True)
            self.skip_spaces()
            if self.text[self.pos: self.pos + 1] == ",":
                self.pos += 1
                continue
            self.expect("}")
            return out

    def parse_flow_key(self) -> object:
        if self.text[self.pos: self.pos + 1] in ("'", '"'):
            key = self.parse_single() if self.text[self.pos] == "'" else self.parse_double()
        else:
            start = self.pos
            while self.pos < len(self.text) and self.text[self.pos] not in ":,[]{}":
                self.pos += 1
            key = _resolve_plain(self.text[start:self.pos].strip(" "), self.number)
        if self.text[self.pos: self.pos + 1] != ":" or self.text[self.pos + 1: self.pos + 2] not in (" ", ",", "}"):
            raise self.error("expected ': ' after a key in a flow mapping")
        self.pos += 1
        return key


def _split_key(line: _Line) -> tuple[object, str] | None:
    """(key, rest) when the line is a block mapping entry, else None."""
    text = line.text
    if text[0] in "'\"":
        inline = _Inline(text, line.number)
        key = inline.parse_single() if text[0] == "'" else inline.parse_double()
        rest = text[inline.pos:]
        if rest == ":" or rest.startswith(": "):
            return key, rest[1:].strip(" ")
        return None
    if text[0] in _PLAIN_START_FORBIDDEN or text.startswith(("- ", "? ")) or text in ("-", "?"):
        return None
    match = re.search(r":( |$)", text)
    if not match:
        return None
    key_text = text[: match.start()].rstrip(" ")
    if not key_text:
        return None
    return _resolve_plain(key_text, line.number), text[match.end():].strip(" ")


class _Block:
    def __init__(self, lines: list[_Line]):
        self.lines = lines
        self.i = 0

    def parse(self) -> object:
        if not self.lines:
            return None
        value = self.parse_node(self.lines[0].indent)
        if self.i != len(self.lines):
            line = self.lines[self.i]
            raise YamlError(line.number, _UNEXPECTED_INDENT)
        return value

    def parse_node(self, indent: int) -> object:
        line = self.lines[self.i]
        if line.text == "-" or line.text.startswith("- "):
            return self.parse_sequence(indent)
        if _split_key(line) is not None:
            return self.parse_mapping(indent)
        self.i += 1
        if line.text[:1] in "|>":
            raise YamlError(line.number, "block scalars (| and >) are not supported")
        return _Inline(line.text, line.number).parse_document_value()

    def parse_inline_or_nested(self, rest: str, line: _Line, parent_indent: int, allow_same_indent_seq: bool):
        if rest:
            if rest[0] in "|>&*!":
                raise YamlError(line.number, f"'{rest[0]}' (block scalars, anchors, aliases, tags) is not supported")
            return _Inline(rest, line.number).parse_document_value()
        if self.i < len(self.lines):
            nxt = self.lines[self.i]
            if nxt.indent > parent_indent:
                return self.parse_node(nxt.indent)
            if allow_same_indent_seq and nxt.indent == parent_indent and (nxt.text == "-" or nxt.text.startswith("- ")):
                return self.parse_sequence(parent_indent)
        return None

    def parse_mapping(self, indent: int) -> dict:
        out: dict = {}
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if line.indent < indent:
                break
            if line.indent > indent:
                raise YamlError(line.number, _UNEXPECTED_INDENT)
            split = _split_key(line)
            if split is None:
                raise YamlError(line.number, "expected 'key: value'")
            key, rest = split
            if isinstance(key, (dict, list)):
                raise YamlError(line.number, "complex keys are not supported")
            if key in out:
                raise YamlError(line.number, f"duplicate key {key!r}")
            self.i += 1
            out[key] = self.parse_inline_or_nested(rest, line, indent, allow_same_indent_seq=True)
        return out

    def parse_sequence(self, indent: int) -> list:
        items: list = []
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if line.indent < indent:
                break
            if line.indent > indent:
                raise YamlError(line.number, _UNEXPECTED_INDENT)
            if not (line.text == "-" or line.text.startswith("- ")):
                break
            rest = line.text[1:].lstrip(" ")
            if not rest:
                self.i += 1
                items.append(self.parse_inline_or_nested("", line, indent, allow_same_indent_seq=False))
                continue
            column = indent + (len(line.text) - len(rest))
            # The item's text becomes a line of its own at its real column: a nested mapping or
            # sequence continues on the following lines at that column.
            self.lines[self.i] = _Line(line.number, column, rest)
            items.append(self.parse_node(column))
        return items


def load_yaml(text: str) -> object:
    """Load the YAML subset described in the module docstring; raises YamlError."""
    return _Block(_scan_lines(text)).parse()


# --------------------------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Finding:
    path: str
    check: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: [{self.check}] {self.message}"


def walk(value: object, where: str = ""):
    """Yield (location, key, value) for every scalar and every mapping key."""
    if isinstance(value, dict):
        for key, item in value.items():
            loc = f"{where}.{key}" if where else str(key)
            yield loc, key, item
            yield from walk(item, loc)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk(item, f"{where}[{index}]")


def as_list(value: object) -> list:
    """The value if it is a list, else an empty list (the shape check reports other types)."""
    return value if isinstance(value, list) else []


def strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


class PackChecker:
    def __init__(self, root: Path, allow_any_address: bool = False):
        self.root = root
        self.allow_any_address = allow_any_address
        self.findings: list[Finding] = []
        self.files: dict[str, object] = {}

    def add(self, path: str, check: str, message: str) -> None:
        self.findings.append(Finding(path, check, message))

    # -- files ----------------------------------------------------------------------------
    def config_files(self) -> dict[str, list[Path]]:
        def glob(pattern: str) -> list[Path]:
            return sorted(p for p in self.root.glob(pattern) if p.is_file())
        return {
            "prometheus": glob("prometheus/**/*.yml") + glob("prometheus/**/*.yaml"),
            "json_exporter": glob("json_exporter/*.yml") + glob("json_exporter/*.yaml"),
            "blackbox": glob("blackbox/*.yml") + glob("blackbox/*.yaml"),
        }

    def load(self, path: Path) -> object | None:
        rel = path.relative_to(self.root).as_posix()
        try:
            doc = load_yaml(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, YamlError) as exc:
            self.add(rel, "parse", str(exc))
            return None
        if not isinstance(doc, dict):
            self.add(rel, "parse", "the file must hold a mapping")
            return None
        self.files[rel] = doc
        return doc

    # -- shared checks ----------------------------------------------------------------------
    def check_common(self, rel: str, doc: object) -> None:
        for text in strings(doc):
            if "players.json" in text.lower():
                self.add(rel, "players", f"names players.json ({text!r}); count players with dynamic.json")
            for match in IPV4_RE.finditer(text):
                self.check_address(rel, match.group(1))
            for token in re.findall(r"\[([0-9a-fA-F:]+)\]", text):
                self.check_address(rel, token)
        for loc, key, value in walk(doc):
            if isinstance(key, str) and key.lower() in SECRET_KEYS and value not in (None, ""):
                self.add(rel, "secrets", f"{loc} is set inline; use the matching *_file setting")
            if key in ("headers", "http_headers") and isinstance(value, dict):
                self.check_headers(rel, loc, value)

    def check_headers(self, rel: str, loc: str, headers: dict) -> None:
        """A header map: name -> value (json_exporter, blackbox http), or name -> values/secrets/files
        (http_headers of an HTTP client, blackbox websocket headers)."""
        for header, spec in headers.items():
            where = f"{loc}.{header}"
            if isinstance(spec, dict):
                if spec.get("secrets") not in (None, "", []):
                    self.add(rel, "secrets", f"{where}: secrets are set inline; read them from files")
                if spec.get("values") not in (None, "", []) and SECRET_HEADER_RE.fullmatch(str(header)):
                    self.add(rel, "secrets", f"{where}: header {header!r} has an inline value; read it from files")
            elif spec not in (None, "") and SECRET_HEADER_RE.fullmatch(str(header)):
                self.add(rel, "secrets", f"{where}: header {header!r} would put a secret into the config; "
                                         "write it at deploy time, never into the repository")

    def check_address(self, rel: str, text: str) -> None:
        if self.allow_any_address:
            return
        try:
            address = ipaddress.ip_address(text)
        except ValueError:
            return
        if not any(address in net for net in ALLOWED_NETWORKS):
            self.add(rel, "addresses", f"{address} is not loopback or a documentation address")

    def check_label_name(self, rel: str, where: str, name: object) -> None:
        if not isinstance(name, str) or not LABEL_NAME_RE.fullmatch(name):
            self.add(rel, "labels", f"{where}: {name!r} is not a valid label name")
        elif PLAYER_LABEL_RE.fullmatch(name):
            self.add(rel, "labels", f"{where}: label {name!r} could identify a player")

    # -- Prometheus -------------------------------------------------------------------------
    def check_prometheus(self, rel: str, doc: dict, jobs_seen: dict[str, str],
                         modules_wanted: list[tuple[str, str, str, str]]) -> None:
        for key in doc:
            if key not in PROMETHEUS_TOP_KEYS:
                self.add(rel, "parse", f"unknown top-level key {key!r}")
        includes = doc.get("scrape_config_files")
        if includes is not None:
            self.check_includes(rel, includes)
        scrape_configs = doc.get("scrape_configs")
        if scrape_configs is None and includes is not None:
            return  # a main config that only includes scrape files
        if not isinstance(scrape_configs, list) or not scrape_configs:
            self.add(rel, "parse", "scrape_configs must be a non-empty list")
            return
        for index, job in enumerate(scrape_configs):
            if not isinstance(job, dict) or not isinstance(job.get("job_name"), str):
                self.add(rel, "parse", f"scrape_configs[{index}] needs a job_name")
                continue
            name = job["job_name"]
            if name in jobs_seen:
                self.add(rel, "modules", f"job {name!r} is also defined in {jobs_seen[name]}")
            jobs_seen[name] = rel
            self.check_job(rel, name, job, modules_wanted)

    def check_includes(self, rel: str, includes: object) -> None:
        """scrape_config_files of a main config: the installed paths of this pack's scrape files."""
        if not isinstance(includes, list) or not includes or not all(isinstance(i, str) for i in includes):
            self.add(rel, "parse", "scrape_config_files must be a non-empty list of paths")
            return
        scrape_files = sorted(p.name for p in (self.root / "prometheus" / "scrape").glob("*.y*ml"))
        for entry in includes:
            if not fnmatch.filter(scrape_files, entry.rpartition("/")[2]):
                self.add(rel, "parse", f"scrape_config_files: {entry!r} names no file of prometheus/scrape/")

    def check_job(self, rel: str, name: str, job: dict, modules_wanted: list[tuple[str, str, str, str]]) -> None:
        where = f"job {name}"
        if job.get("honor_labels") is True:
            self.add(rel, "labels", f"{where}: honor_labels passes the target's own labels on unchecked")
        static_modules: list[str] = []
        for group in as_list(job.get("static_configs")):
            labels = group.get("labels") if isinstance(group, dict) else None
            for label, value in (labels if isinstance(labels, dict) else {}).items():
                self.check_label_name(rel, f"{where} static label", label)
                if label in ("module", "__param_module"):
                    static_modules.append(str(value))
        for kind in ("relabel_configs", "metric_relabel_configs"):
            for rule in as_list(job.get(kind)):
                if not isinstance(rule, dict):
                    continue
                action = rule.get("action", "replace")
                if action == "labelmap":
                    self.add(rel, "labels", f"{where} {kind}: labelmap copies labels nobody reviewed")
                target = rule.get("target_label")
                if target is not None and not str(target).startswith("__"):
                    self.check_label_name(rel, f"{where} {kind} target_label", target)
        if str(job.get("metrics_path", "/metrics")).startswith("/perf"):
            self.check_perf_job(rel, where, job)
        address = self.rewritten_address(job)
        params = job.get("params") if isinstance(job.get("params"), dict) else {}
        modules = [str(m) for m in as_list(params.get("module"))] + static_modules
        exporter = {JSON_EXPORTER_PORT: "json_exporter", BLACKBOX_PORT: "blackbox"}.get(address.rpartition(":")[2])
        if exporter:
            if not modules:
                self.add(rel, "modules", f"{where}: sends no module to {exporter}")
            for module in modules:
                modules_wanted.append((rel, where, exporter, module))

    @staticmethod
    def rewritten_address(job: dict) -> str:
        address = ""
        for rule in as_list(job.get("relabel_configs")):
            if isinstance(rule, dict) and rule.get("target_label") == "__address__" and "replacement" in rule:
                address = str(rule["replacement"])
        return address

    def check_perf_job(self, rel: str, where: str, job: dict) -> None:
        auth = job.get("basic_auth")
        if not isinstance(auth, dict) or not auth.get("password_file"):
            self.add(rel, "secrets", f"{where}: /perf/ needs basic_auth with a password_file")
        rules = [r for r in as_list(job.get("metric_relabel_configs")) if isinstance(r, dict)]
        keeps_names = any(r.get("action") == "keep" and r.get("source_labels") == ["__name__"] for r in rules)
        if not keeps_names:
            self.add(rel, "perf", f"{where}: needs a keep rule on __name__ so unknown /perf/ metrics are dropped")

        def matches(pattern: object, text: str) -> bool:
            try:
                return re.fullmatch(str(pattern), text) is not None
            except re.error:
                return False
        def removes_name(rule: dict) -> bool:
            if rule.get("action") == "labeldrop":
                return matches(rule.get("regex", "(.*)"), "name")
            if rule.get("action") == "labelkeep":
                return not matches(rule.get("regex", "(.*)"), "name")
            return False
        # Rules run in order: a copy after the rule that removes name finds no name to copy.
        removals = [i for i, r in enumerate(rules) if removes_name(r)]
        copies = [i for i, r in enumerate(rules)
                  if r.get("source_labels") == ["name"] and r.get("target_label") == "thread"]
        if not removals:
            self.add(rel, "perf", f"{where}: the server's name label must be dropped (labeldrop name)")
        if not copies:
            self.add(rel, "perf", f"{where}: copy the name label to thread before dropping it")
        elif removals and copies[0] > removals[0]:
            self.add(rel, "perf", f"{where}: the copy of name to thread must come before the rule that drops name")

    # -- json_exporter ----------------------------------------------------------------------
    def json_metric_names(self, metric: dict) -> list[str]:
        if metric.get("type", "value") == "object":
            return [f"{metric.get('name')}_{key}" for key in (metric.get("values") or {})]
        return [str(metric.get("name"))]

    def check_json_exporter(self, rel: str, doc: dict) -> set[str]:
        modules = doc.get("modules")
        if set(doc) != {"modules"} or not isinstance(modules, dict) or not modules:
            self.add(rel, "parse", "json_exporter config needs exactly one top-level key, modules, with modules in it")
            return set()
        for module_name, module in modules.items():
            where = f"module {module_name}"
            if not isinstance(module, dict):
                self.add(rel, "parse", f"{where} must be a mapping")
                continue
            for key in sorted(set(module) - JSON_MODULE_KEYS):
                self.add(rel, "parse", f"{where}: unknown key {key!r} (json_exporter would ignore it)")
            metrics = module.get("metrics")
            if not isinstance(metrics, list) or not metrics:
                self.add(rel, "parse", f"{where}: metrics must be a non-empty list")
                continue
            for metric in metrics:
                self.check_json_metric(rel, where, metric)
        return set(modules)

    def check_json_metric(self, rel: str, where: str, metric: object) -> None:
        if not isinstance(metric, dict) or not isinstance(metric.get("name"), str):
            self.add(rel, "parse", f"{where}: every metric needs a name")
            return
        where = f"{where} metric {metric['name']}"
        for key in sorted(set(metric) - JSON_METRIC_KEYS):
            self.add(rel, "parse", f"{where}: unknown key {key!r} (json_exporter would ignore it)")
        kind = metric.get("type", "value")
        if kind not in ("value", "object"):
            self.add(rel, "parse", f"{where}: type must be value or object")
        if metric.get("valuetype", "untyped") not in ("gauge", "counter", "untyped"):
            self.add(rel, "parse", f"{where}: valuetype must be gauge, counter or untyped")
        if not isinstance(metric.get("path"), str) or not metric["path"].strip():
            self.add(rel, "parse", f"{where}: path is missing")
        if kind == "object" and not isinstance(metric.get("values"), dict):
            self.add(rel, "parse", f"{where}: an object metric needs values")
        for name in self.json_metric_names(metric):
            if not METRIC_NAME_RE.fullmatch(name):
                self.add(rel, "parse", f"{where}: {name!r} is not a valid metric name")
        labels = metric.get("labels") or {}
        if not isinstance(labels, dict):
            self.add(rel, "parse", f"{where}: labels must be a mapping")
            return
        for label in labels:
            self.check_label_name(rel, f"{where} label", label)

    # -- blackbox ---------------------------------------------------------------------------
    def check_blackbox(self, rel: str, doc: dict) -> set[str]:
        modules = doc.get("modules")
        if set(doc) != {"modules"} or not isinstance(modules, dict) or not modules:
            self.add(rel, "parse", "blackbox config needs exactly one top-level key, modules, with modules in it")
            return set()
        for module_name, module in modules.items():
            if not isinstance(module, dict) or module.get("prober") not in BLACKBOX_PROBERS:
                self.add(rel, "parse", f"module {module_name}: prober must be one of {sorted(BLACKBOX_PROBERS)}")
                continue
            tcp = module.get("tcp") if isinstance(module.get("tcp"), dict) else {}
            for step in as_list(tcp.get("query_response")):
                for label in as_list(step.get("labels")) if isinstance(step, dict) else []:
                    if isinstance(label, dict):
                        self.check_label_name(rel, f"module {module_name} query_response label", label.get("name"))
        return set(modules)

    # -- promtool ---------------------------------------------------------------------------
    def run_promtool(self, paths: list[Path], required: bool) -> str:
        promtool = shutil.which("promtool")
        if promtool is None:
            if required:
                self.add("promtool", "promtool", "promtool is not on the PATH")
                return "missing"
            return "skipped (promtool is not on the PATH)"
        if not paths:
            return "no Prometheus files"
        result = subprocess.run([promtool, "check", "config", "--lint=all", "--lint-fatal",
                                 *[str(p) for p in paths]], capture_output=True, text=True)
        if result.returncode != 0:
            output = (result.stdout + result.stderr).strip().replace("\n", " | ")
            self.add("promtool", "promtool", f"promtool check config failed: {output}")
            return "failed"
        return f"{len(paths)} file(s) passed promtool check config"

    # -- all --------------------------------------------------------------------------------
    def run(self, require_promtool: bool = False) -> str:
        groups = self.config_files()
        jobs_seen: dict[str, str] = {}
        modules_wanted: list[tuple[str, str, str, str]] = []
        available = {"json_exporter": set(), "blackbox": set()}
        if not groups["prometheus"]:
            self.add("prometheus", "parse", "no scrape config found")
        for kind, paths in groups.items():
            for path in paths:
                doc = self.load(path)
                if doc is None:
                    continue
                rel = path.relative_to(self.root).as_posix()
                self.check_common(rel, doc)
                try:
                    if kind == "prometheus":
                        self.check_prometheus(rel, doc, jobs_seen, modules_wanted)
                    elif kind == "json_exporter":
                        available["json_exporter"] |= self.check_json_exporter(rel, doc)
                    else:
                        available["blackbox"] |= self.check_blackbox(rel, doc)
                except (AttributeError, TypeError) as exc:  # a value of an unexpected type
                    self.add(rel, "parse", f"unexpected structure ({exc})")
        for rel, where, exporter, module in modules_wanted:
            if module not in available[exporter]:
                self.add(rel, "modules", f"{where}: module {module!r} is not in the {exporter} config")
        return self.run_promtool([p for p in groups["prometheus"]], require_promtool)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the pack's scrape and exporter configs.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="repository root (default: this checkout)")
    parser.add_argument("--require-promtool", action="store_true",
                        help="fail when promtool is not on the PATH instead of skipping that check")
    parser.add_argument("--allow-any-address", action="store_true",
                        help="accept any IP address, for a copy of the configs with the addresses of your servers")
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        print(f"check_pack: {args.root} is not a folder", file=sys.stderr)
        return 2
    checker = PackChecker(args.root.resolve(), allow_any_address=args.allow_any_address)
    promtool = checker.run(require_promtool=args.require_promtool)
    for finding in checker.findings:
        print(finding)
    print(f"check_pack: {len(checker.findings)} finding(s) in {len(checker.files)} parsed file(s); "
          f"promtool: {promtool}")
    return 1 if checker.findings else 0


if __name__ == "__main__":
    sys.exit(main())
