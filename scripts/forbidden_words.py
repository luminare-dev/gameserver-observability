#!/usr/bin/env python3
"""Pre-publication checks for a public repository (Python standard library only).

Five checks, all run by default:

1. Wording: offer, price, funding, store and "coming soon" wording in English and German, plus
   funding-platform and store domains. Case-insensitive and word-boundary aware. The rules run
   over the whole file, so a phrase broken across a line wrap still matches, and over every file
   path. Each line is normalised first (HTML entities, NFKC, invisible characters, Unicode
   dashes), and a word that mixes Latin with Cyrillic or Greek look-alike letters is reported.
2. Funding file: a FUNDING.yml / FUNDING.yaml anywhere fails, and no allowlist entry can excuse it.
3. Names: platform and vendor marks in the repository name, galaxy.yml namespace/name, package
   names, an Action name, Grafana dashboard titles and the README title.
4. Placeholders: an unfilled {{NAME}} placeholder, a leftover "<!-- template:" hint or a
   leftover template-only block fails.
5. E-mail addresses: only the role addresses, GitHub noreply addresses and reserved example
   domains may appear (no private address in a public file).
   With --template-mode (the template repository itself) placeholders are allowed, but each one
   must be listed in PLACEHOLDERS.md.

Exceptions:
* `.forbidden-words-allow` in the repository root, one entry per line:
      <path glob> | <rule id, matched text or *> | <reason>
  The pseudo-path "@name" covers the name check. Every entry needs a reason, and unused entries
  are reported. Scope an entry to data or UI files, or to the one domain a project links to.
  The term "*" never covers the e-mail rule (name "email" explicitly), and terms from the
  private list (--extra-terms) can never be excused.
* A line that quotes the rules themselves can end with the comment <!-- rule-text --> (Markdown,
  HTML) or # rule-text (YAML, shell, Python). Only that comment at the very end of the line
  counts. It exempts that line from the wording check only (not from the private terms). Every
  use is counted in the summary, so a reviewer sees how many exist.

Exit codes: 0 clean, 1 findings, 2 usage or configuration error.

Usage:
  python3 scripts/forbidden_words.py [--template-mode] [--repo-name NAME] [PATH ...]
  echo "Buy the pro version" | python3 scripts/forbidden_words.py --stdin
  git log --all --format='%an <%ae>%n%cn <%ce>%n%B' | python3 scripts/forbidden_words.py --stdin
  python3 scripts/forbidden_words.py --list-rules
"""

from __future__ import annotations

import argparse
import bisect
import configparser
import fnmatch
import html
import json
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - the CI runner has 3.12
    tomllib = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parent.parent
ALLOW_FILE = ".forbidden-words-allow"
MARKER = "rule-text"
# Only an HTML or "#" comment at the very end of the line counts, never the word in prose or a URL.
MARKER_RE = re.compile(r"(?:<!--\s*rule-text\s*-->|(?<!\S)#\s*rule-text)\s*$")
EXTRA_PREFIX = "extra-"  # rule ids of the private term list
NAME_PSEUDO_PATH = "@name"
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".cache", "dist", ".tox"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".tgz",
                   ".woff", ".woff2", ".ttf", ".otf", ".mp4", ".webm", ".cast"}


@dataclass(frozen=True)
class Rule:
    rule_id: str
    label: str
    regex: re.Pattern
    accept: Callable[[str], bool] | None = None  # optional second test on the matched text


def _rules(spec: list[tuple[str, str, str]]) -> list[Rule]:
    return [Rule(rid, label, re.compile(rx, re.IGNORECASE | re.MULTILINE)) for rid, label, rx in spec]


S = r"[\s-]+"  # one or more spaces or hyphens between the words of a phrase

# --------------------------------------------------------------------------------------------
# Wording rules: the publishing rules in PUBLISHING.md (part B). Public project text describes
# what the code does; it carries no price, offer, funding, store or "coming soon" wording.
#
# Tuning notes (false positives found in infra docs, kept out on purpose):
# * bare "store" (key-value store, store a token), "offer"/"bietet" ("Ansible bietet ..."),
#   "service" (systemd service), "client" (HTTP client), "subscribe" (watch notifications),
#   "free tier" (Grafana Cloud Free), "licence key" (FXServer needs a server key), "billing",
#   "Anfrage" (HTTP request), "Anzeige" (display), "Aktion" (GitHub Actions), "erwerben"
#   (Kenntnisse erwerben), "bestellen" (ordering a server for yourself), "Kauf" ("in Kauf
#   nehmen"), "Leistung" (performance), "selbstständig" (runs on its own), "SLA".
# * "affiliated" stays allowed: the not-affiliated line is mandatory for FXServer projects;
#   only "affiliate(s)" in the marketing sense is matched.
# * "preisgeben"/"Preisgabe" (to disclose) are excluded from the German price rule, and
#   "suspended" from the German donation rule (it contains "spende").
# * Phrases are matched with spaces, hyphens or line breaks between the words ("pro-version").
# * Store and product hosts or paths on the reserved example domains (example.com/.org/.net) are
#   not reported.
# * Known matches kept on purpose (a project that really needs one gets a reviewed entry in
#   .forbidden-words-allow, scoped to its data or UI files): "commission a server" (the
#   availability rule), "EUR/USD" (an exchange-rate exporter), "spot price", "sponsored by the
#   protocol", "Angebot von <hoster>", "Werbung blocken", "Preisgeld".
# --------------------------------------------------------------------------------------------
TEXT_RULES = _rules([
    # English: money and selling
    ("price", "price wording", r"\bpric(?:e|es|ed|ing|elists?)\b"),
    ("currency", "currency sign or code",
     r"€|£|\bEUR\b|\bUSD\b|\beuros?\b|\d\s*(?:EUR|USD)\b|\b(?:EUR|USD)\s*\d"),
    ("hire", "hire wording", r"\bhir(?:e|es|ed|ing)\b"),
    ("buy", "buy or purchase wording", r"\bbuy(?:s|ing)?\b|\bpurchas(?:e|es|ed|ing)\b"),
    ("sell", "selling wording", r"\bsell(?:s|ing)?\b|\bfor" + S + r"sale\b|\bon" + S + r"sale\b"),
    ("invoice", "invoice wording", r"\binvoic(?:e|es|ed|ing)\b"),
    ("pro-version", "paid edition wording",
     r"\bpro" + S + r"(?:version|edition|tier|plan|features?)\b|\bpremium\b"
     r"|\b(?:lite|free)" + S + r"(?:version|edition)\b|\bupgrade" + S + r"to" + S + r"pro\b"),
    ("paid-tier", "paid tier wording",
     r"\bpaid" + S + r"(?:tiers?|plans?|versions?|editions?|support|add-?ons?|features?|licen[cs]es?)\b"
     r"|\benterprise" + S + r"(?:edition|version|tier|plan|licen[cs]e)\b|\bfree" + S + r"trial\b"),
    ("commercial-licence", "commercial or dual licence offer",
     r"\bcommercial" + S + r"licen[cs]e\b|\bdual" + S + r"licen[cs](?:e|ed|ing)\b|\blicensing" + S + r"options\b"),
    ("paid-support", "paid support wording",
     r"\b(?:paid|commercial|priority|premium|enterprise)" + S + r"support\b"
     r"|\bsupport" + S + r"(?:contracts?|plans?|packages?)\b"),
    ("services", "services wording",
     r"\b(?:our|my)" + S + r"services\b|\bservices" + S + r"(?:offered|available)\b"
     r"|\bprofessional" + S + r"services\b|\b(?:setup|installation|install|consulting)" + S + r"services?\b"
     r"|\bconsultancy\b"),
    ("custom-work", "custom work on request",
     r"\bcustom" + S + r"(?:integrations?|development|work|setups?|installs?|installations?)\b"
     r"|\b(?:up)?on" + S + r"request\b"),
    ("quote", "quote wording", r"\b(?:request|get|ask" + S + r"for|free|custom)" + S + r"(?:a" + S + r")?quotes?\b"),
    ("availability", "availability for work",
     r"\bavailable" + S + r"for" + S + r"(?:new" + S + r")?(?:projects?|hire|freelance|work|contracts?|commissions?|clients?)\b"
     r"|\bopen" + S + r"for" + S + r"(?:work|projects?|commissions?|business|clients?)\b|\bfreelanc\w*"
     r"|\bcommissions?\b|\bdm" + S + r"(?:me|us)\b|\bcontact" + S + r"(?:me|us)" + S + r"for\b"),
    ("coming-soon", "announcement of something not yet available",
     r"\bcoming" + S + r"soon\b|\b(?:launching|available)" + S + r"soon\b|\bsoon" + S + r"available\b"
     r"|\bstay" + S + r"tuned\b|\bearly" + S + r"access\b|\bpre-?orders?\b"),
    ("waitlist", "waitlist or newsletter",
     r"\bwait(?:ing)?[\s-]?lists?\b|\bnewsletters?\b|\bsign" + S + r"up" + S + r"for" + S + r"updates\b"),
    ("sponsor", "sponsor wording", r"\bsponsor\w*|\bgesponsert\b"),
    ("donate", "donation wording",
     r"\bdonat\w*|\btip[\s-]?jars?\b|\b(?:buy|get)" + S + r"me" + S + r"a" + S + r"coffee\b"
     r"|\bsupport" + S + r"(?:the|this|my)" + S + r"(?:project|work)\b|\bsupport" + S + r"(?:us|me)\b(?!-)"),
    ("funding", "funding wording", r"\b\w*funding\b|\bfund" + S + r"(?:this|the)" + S + r"project\b"),
    ("affiliate-ads", "affiliate, referral or ad wording",
     r"\baffiliates?\b|\breferral" + S + r"(?:links?|codes?)\b|\bpromo" + S + r"codes?\b|\bcoupons?\b"
     r"|\bdiscount\w*|\badvertisements?\b|\bad-?supported\b"),
    ("shop-store", "shop, store page or product line",
     r"\b(?:web|online|app)[\s-]?(?:shop|store)s?\b|\bshops?\b|\bstore" + S + r"(?:pages?|links?)\b"
     r"|\bstorefronts?\b|\bproduct" + S + r"lines?\b"),
    ("special-offer", "limited or special offer", r"\b(?:special|limited)" + S + r"(?:offers?|time)\b"),
    ("crypto", "crypto payment address",
     r"\bbitcoin\b|\bethereum\b|\bbtc" + S + r"address\b|\bcrypto" + S + r"(?:address|wallet)\b|\bwallet" + S + r"address\b"),
    # German equivalents (posts are German first).
    ("de-price", "Preis- oder Honorarwortlaut",
     r"\b\w*?preis(?!g[ae]b)\w*|\bkostenpflichtig\w*|\bentgelt\w*|\bhonorar\w*"
     r"|\bstundensatz\w*|\btagessatz\w*|\bpauschale\b|\bgebühr(?:en)?\b|\babo(?:nnement\w*)?\b"),
    ("de-buy", "Kauf- oder Verkaufswortlaut",
     r"\b(?:kaufen|kauft|kaufe|gekauft)\b|\bverkauf(?:en|t|e)?\b|\bvollversion\b|\bkauf\s+jetzt\b"
     r"|\bbezahl(?:version|variante)\w*"),
    ("de-donate", "Spenden- oder Trinkgeldwortlaut",
     r"\b\w*?(?<!su)spende\w*|\bspendier\w*|\btrinkgeld\w*"
     r"|\bunterstütz\w*\s+(?:sie\s+)?(?:uns|mich|das\s+projekt)\b"),
    ("de-coming-soon", "Ankündigung (demnächst, bald verfügbar, Warteliste)",
     r"\bdemnächst\b|\bbald" + S + r"(?:verfügbar|erhältlich|da|online)\b|\bin" + S + r"kürze\b"
     r"|\bwarteliste\w*|\bvorbestell\w*|\bvorverkauf\w*"),
    ("de-offer", "Angebotswortlaut",
     r"\bangebot(?:e|en|s)?\b|\bsonderangebot\w*|\b(?:ich|wir)" + S + r"bieten?\b|\bbieten?" + S + r"(?:ich|wir)\b"
     r"|\brabatt\w*|\bgutschein\w*|\bkommerzielle" + S + r"lizenz\b"),
    ("de-commission", "Auftragswortlaut",
     r"\bbeauftrag\w*|\bauftr(?:a|ä)g(?:e|en)?\b|\bauftragsarbeit\w*|\bkostenvoranschl(?:a|ä)g\w*|\bauf" + S + r"anfrage\b"),
    ("de-services", "Dienstleistungs- oder Verfügbarkeitswortlaut",
     r"\bdienstleist\w*|\bfreiberuf\w*|\bfür" + S + r"(?:neue" + S + r")?projekte" + S + r"(?:frei|verfügbar)\b"
     r"|\b(?:meine|unsere)" + S + r"(?:dienste|leistungen)\b"),
    ("de-ads", "Werbe- oder Partnerlinkwortlaut",
     r"\bwerbung\b|\bwerbe(?:link|partner)\w*|\bpartnerlinks?\b|\bprovisionslinks?\b|\bpartnerprogramm\w*"),
    ("de-shop", "Store-Seiten- oder Produktlinienwortlaut", r"\bprodukt[\s-]?linie\w*|\bstore[\s-]?seite\w*"),
    # Domains and hosts.
    ("funding-platform", "funding or donation platform",
     r"patreon|\bko-?fi\b|buymeacoffee|paypal|open[\s-]?collective|liberapay|github\.com/sponsors"
     r"|polar\.sh|thanks\.dev|tidelift|issuehunt|bountysource|gitcoin|kickstarter|indiegogo|steadyhq|flattr"
     r"|donorbox|(?:checkout|donate|buy)\.stripe\.com|revolut\.me"),
    ("store-domain", "store or marketplace domain",
     r"tebex|gumroad|lemonsqueezy|payhip|\bitch\.io\b|etsy\.com|shopify|apps\.apple\.com|play\.google\.com"
     r"|f-droid\.org|chromewebstore\.google\.com|microsoftedge\.microsoft\.com|addons\.mozilla\.org"
     r"|store\.steampowered\.com"),
    ("product-host", "store or product-line hostname",
     r"\b(?:store|shop|scripts)\.(?!example\.(?:com|net|org)\b)"
     r"(?:primary_domain|[a-z0-9-]+\.(?:tech|com|net|org|io|at|de|eu|dev|app|gg|shop|store))\b"),
    ("product-path", "store, product or pricing page on a website",
     # (play.google.com/store is the store-domain rule's, so one allowlist entry covers a listing)
     r"(?<![a-z0-9.-])(?![a-z0-9.-]*\b(?:example\.(?:com|net|org)|play\.google\.com)/)[a-z0-9.-]+\.[a-z]{2,}"
     r"/(?:store|shop|products?|services|pricing|preise|checkout)\b"),
])

# Look-alike letters (homoglyph evasion such as a Cyrillic "i" in "price"). Greek letters that
# do not look like Latin ones (µ in "µs", Δ in "Δt") are not reported.
_GREEK_LOOKALIKES = set("\u0391\u0392\u0395\u0396\u0397\u0399\u039a\u039c\u039d\u039f\u03a1\u03a4\u03a5\u03a7"  # capitals
                        "\u03b1\u03b5\u03b9\u03ba\u03bd\u03bf\u03c1\u03c5\u03c7")  # small letters


def _mixes_scripts(word: str) -> bool:
    latin = other = False
    for ch in word:
        if not ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        if name.startswith("LATIN"):
            latin = True
        elif name.startswith("CYRILLIC") or (name.startswith("GREEK") and ch in _GREEK_LOOKALIKES):
            other = True
    return latin and other


TEXT_RULES.append(Rule("mixed-script", "word mixes Latin with Cyrillic or Greek look-alike letters",
                       re.compile(r"\w*[^\x00-\x7f\W]\w*"), _mixes_scripts))

# --------------------------------------------------------------------------------------------
# Name rules (PUBLISHING.md B4): platform and vendor marks stay out of every name. Platform
# names belong in descriptions and topics ("... for FiveM/RedM servers (FXServer)"). Registry
# conventions such as "ansible-collection-<name>" or "terraform-provider-<name>" are
# descriptive use and need an "@name" allowlist entry.
# --------------------------------------------------------------------------------------------
_L, _R = r"(?<![a-z0-9])", r"(?![a-z0-9])"
_SEP = r"[\s._-]*"
NAME_RULES = _rules([
    ("fivem", "FiveM", r"fivem|five" + _SEP + r"m" + _R),
    ("cfx", "Cfx", r"cfx"),
    ("citizenfx", "CitizenFX", r"citizen" + _SEP + r"fx"),
    ("redm", "RedM", _L + r"redm" + _R),
    ("txadmin", "txAdmin", r"tx" + _SEP + r"admin"),
    ("gta", "GTA", _L + r"gta"),
    ("rockstar", "Rockstar", r"rock" + _SEP + r"star"),
    ("take-two", "Take-Two", r"take" + _SEP + r"two"),
    ("fx-coinage", "FX... coinage", _L + r"fx"),
    ("apple", "Apple", _L + r"apple"), ("iphone", "iPhone", _L + r"iphone"),
    ("android", "Android", _L + r"android"), ("google-play", "Google Play", _L + r"google" + _SEP + r"play"),
    ("chrome", "Chrome", _L + r"chrome"), ("gemini", "Gemini", _L + r"gemini"),
    ("wi-fi", "Wi-Fi", _L + r"wi" + _SEP + r"fi" + _R), ("prometheus", "Prometheus", _L + r"prometheus"),
    ("alertmanager", "Alertmanager", _L + r"alert" + _SEP + r"manager"), ("proxmox", "Proxmox", _L + r"proxmox"),
    ("pve", "PVE", _L + r"pve" + _R), ("windows", "Windows", _L + r"windows"),
    ("microsoft", "Microsoft", _L + r"microsoft"), ("intune", "Intune", _L + r"intune"),
    ("entra", "Entra", _L + r"entra" + _R), ("powershell", "PowerShell", _L + r"power" + _SEP + r"shell"),
    ("azure", "Azure", _L + r"azure"), ("discord", "Discord", _L + r"discord"),
    ("steam", "Steam", _L + r"steam" + _R), ("minecraft", "Minecraft", _L + r"minecraft"),
    ("netbox", "NetBox", _L + r"net" + _SEP + r"box"), ("terraform", "Terraform", _L + r"terraform"),
    ("opentofu", "OpenTofu", _L + r"open" + _SEP + r"tofu"), ("grafana", "Grafana", _L + r"grafana"),
    ("tebex", "Tebex", r"tebex"), ("cloudflare", "Cloudflare", _L + r"cloudflare"),
    ("hetzner", "Hetzner", _L + r"hetzner"), ("docker", "Docker", _L + r"docker"),
    ("ansible", "Ansible", _L + r"ansible"),
])

PLACEHOLDER_RE = re.compile(r"(?<!\$)\{\{\s*([A-Z][A-Z0-9_]*)\s*\}\}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
ALLOWED_EMAILS = {"oss@luminare.tech", "conduct@luminare.tech", "security@luminare.tech", "git@github.com"}
ALLOWED_EMAIL_SUFFIXES = ("@users.noreply.github.com", "@example.com", "@example.org", "@example.net", ".example",
                          ".invalid", ".test")
ALLOWED_EMAIL_PREFIXES = ("noreply@", "no-reply@")  # no-reply senders are nobody's mailbox (commit trailers)
TEMPLATE_HINT_RE = re.compile(r"<!--\s*template(?::|-only:begin)", re.IGNORECASE)
FUNDING_RE = re.compile(r"funding\.ya?ml", re.IGNORECASE)


@dataclass
class AllowEntry:
    line_no: int
    glob: str
    term: str
    reason: str
    used: int = 0

    def matches(self, rel_path: str, rule: Rule, text: str) -> bool:
        if not fnmatch.fnmatchcase(rel_path, self.glob):
            return False
        t = self.term.casefold()
        if t == "*":  # "*" never covers e-mail addresses: an entry has to name "email"
            return rule.rule_id != "email"
        return t == rule.rule_id.casefold() or t == rule.label.casefold() or t == text.casefold()


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    allowed: int = 0
    rule_text_lines: int = 0
    files_scanned: int = 0
    gh_annotations: list[str] = field(default_factory=list)

    def error(self, msg: str, path: str | None = None, line: int | None = None, col: int | None = None) -> None:
        self.errors.append(msg)
        if path and not path.startswith("@") and path != "<stdin>":
            loc = f"file={path}" + (f",line={line}" if line else "") + (f",col={col}" if col else "")
            self.gh_annotations.append(f"::error {loc}::{msg}")


class ConfigError(Exception):
    pass


# --------------------------------------------------------------------------------------------
def load_allowlist(root: Path) -> list[AllowEntry]:
    path = root / ALLOW_FILE
    entries: list[AllowEntry] = []
    if not path.exists():
        return entries
    for no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3 or not all(parts):
            raise ConfigError(f"{ALLOW_FILE}:{no}: expected '<path glob> | <term> | <reason>'")
        glob, term, reason = parts
        if len(reason) < 10:
            raise ConfigError(f"{ALLOW_FILE}:{no}: the reason is too short to review ({reason!r})")
        if FUNDING_RE.search(glob):
            raise ConfigError(f"{ALLOW_FILE}:{no}: a funding file can never be allowlisted")
        entries.append(AllowEntry(no, glob, term, reason))
    return entries


def load_extra_terms(path: Path) -> tuple[list[Rule], list[Rule]]:
    """Private term list kept outside the repository (for example personal data that must never
    appear). Lines: 'text <regex>' or 'name <regex>'; '#' starts a comment line."""
    text_rules: list[Rule] = []
    name_rules: list[Rule] = []
    for no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        kind, _, rx = line.partition(" ")
        if kind not in ("text", "name") or not rx.strip():
            raise ConfigError(f"{path}:{no}: expected 'text <regex>' or 'name <regex>'")
        try:
            compiled = re.compile(rx.strip(), re.IGNORECASE | re.MULTILINE)
        except re.error as exc:
            raise ConfigError(f"{path}:{no}: bad regex: {exc}") from exc
        rule = Rule(f"{EXTRA_PREFIX}{no}", "term from the private extra list", compiled)
        (text_rules if kind == "text" else name_rules).append(rule)
    return text_rules, name_rules


def list_files(root: Path, only: list[str] | None = None) -> list[str]:
    files: list[str] = []
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                             capture_output=True, check=True)
        files = [f for f in out.stdout.decode("utf-8").split("\0") if f]
        files = [f for f in files if (root / f).is_file()]
    except (OSError, subprocess.CalledProcessError):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                files.append(Path(dirpath, name).relative_to(root).as_posix())
    files = sorted(set(f for f in files if not any(part in SKIP_DIRS for part in Path(f).parts)))
    if only:
        prefixes = [Path(p).as_posix().rstrip("/") for p in only]
        files = [f for f in files if any(f == p or f.startswith(p + "/") for p in prefixes)]
    return files


def is_text(path: Path) -> bool:
    if path.suffix.lower() in BINARY_SUFFIXES:
        return False
    try:
        with path.open("rb") as fh:
            return b"\0" not in fh.read(8192)
    except OSError:
        return False


_ENTITY_RE = re.compile(r"&(?:#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});")
_LINE_BREAKS_RE = re.compile(r"[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]")
# Invisible characters are removed; Unicode hyphens and dashes and the minus sign become "-".
_NORMALISE = {**dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\u00ad\ufeff")),
              **{cp: "-" for cp in (*range(0x2010, 0x2016), 0x2212)}}


def normalise(line: str) -> str:
    """The text a reader sees: HTML entities decoded (only complete ones with ";"), NFKC
    (full-width letters, ligatures, no-break spaces), invisible characters removed, dashes
    unified. The result never contains a line break, so line numbers stay valid."""
    line = _ENTITY_RE.sub(lambda m: html.unescape(m.group(0)), line)
    line = unicodedata.normalize("NFKC", line).translate(_NORMALISE)
    return _LINE_BREAKS_RE.sub(" ", line)


def scan_text(rel: str, text: str, rules: list[Rule], allow: list[AllowEntry], report: Report) -> None:
    raw_lines = text.splitlines()
    found: list[tuple[int, int, str]] = []
    for no, line in enumerate(raw_lines, start=1):
        for m in EMAIL_RE.finditer(line):
            addr = m.group(0).lower()
            if addr in ALLOWED_EMAILS or addr.endswith(ALLOWED_EMAIL_SUFFIXES) or addr.startswith(ALLOWED_EMAIL_PREFIXES):
                continue
            if _allowed(allow, rel, EMAIL_RULE, m.group(0), report):
                continue
            found.append((no, m.start() + 1, f"[email] e-mail address that is not a role or example "
                                             f"address: {m.group(0)!r}"))
    marked = [bool(MARKER_RE.search(line)) for line in raw_lines]
    report.rule_text_lines += sum(marked)
    # The wording rules run over the whole (normalised) text, so a phrase broken across a line
    # wrap matches too; each match is mapped back to the line it starts on.
    lines = [normalise(line) for line in raw_lines]
    joined = "\n".join(lines)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line) + 1)
    for rule in rules:
        for m in rule.regex.finditer(joined):
            if not m.group(0) or (rule.accept and not rule.accept(m.group(0))):
                continue
            first = bisect.bisect_right(starts, m.start()) - 1
            last = bisect.bisect_right(starts, m.end() - 1) - 1
            if not rule.rule_id.startswith(EXTRA_PREFIX) and all(marked[first:last + 1]):
                continue  # a rule-text line (never for the private terms)
            if _allowed(allow, rel, rule, m.group(0), report):
                continue
            found.append((first + 1, m.start() - starts[first] + 1,
                          f"[{rule.rule_id}] {rule.label}: {m.group(0)!r}"))
    for no, col, msg in sorted(found):
        report.error(f"{rel}:{no}:{col}: {msg}", rel, no, col)


def scan_path(rel: str, rules: list[Rule], allow: list[AllowEntry], report: Report) -> None:
    """The wording rules on a file path (docs/pricing.md is as public as its content)."""
    for rule in rules:
        for m in rule.regex.finditer(normalise(rel)):
            if not m.group(0) or (rule.accept and not rule.accept(m.group(0))):
                continue
            if _allowed(allow, rel, rule, m.group(0), report):
                continue
            report.error(f"{rel}: [{rule.rule_id}] {rule.label} in the file path: {m.group(0)!r}", rel)


PLACEHOLDER_RULE = Rule("placeholder", "unfilled placeholder", PLACEHOLDER_RE)
EMAIL_RULE = Rule("email", "e-mail address", EMAIL_RE)
TEMPLATE_HINT_RULE = Rule("template-hint", "template hint or template-only block", TEMPLATE_HINT_RE)


def _allowed(allow: list[AllowEntry], rel: str, rule: Rule, text: str, report: Report) -> bool:
    if rule.rule_id.startswith(EXTRA_PREFIX):
        return False  # private terms (personal data) can never be excused
    hit = next((a for a in allow if a.matches(rel, rule, text)), None)
    if hit:
        hit.used += 1
        report.allowed += 1
    return hit is not None


def scan_placeholders(rel: str, text: str, template_mode: bool, listed: set[str], allow: list[AllowEntry],
                      report: Report) -> None:
    if Path(rel).name == "PLACEHOLDERS.md":
        return
    for no, line in enumerate(text.splitlines(), start=1):
        for m in PLACEHOLDER_RE.finditer(line):
            name = m.group(1)
            if _allowed(allow, rel, PLACEHOLDER_RULE, m.group(0), report):
                continue
            if template_mode and name in listed:
                continue
            if not template_mode:
                report.error(f"{rel}:{no}: unfilled placeholder {m.group(0)}", rel, no, m.start() + 1)
            else:
                report.error(f"{rel}:{no}: placeholder {m.group(0)} is not listed in PLACEHOLDERS.md",
                             rel, no, m.start() + 1)
        if not template_mode and (m := TEMPLATE_HINT_RE.search(line)):
            if _allowed(allow, rel, TEMPLATE_HINT_RULE, m.group(0), report):
                continue
            report.error(f"{rel}:{no}: template hint or template-only block left in (delete it once the "
                         "section is filled)", rel, no)


# --------------------------------------------------------------------------------------------
def _first(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, re.MULTILINE)
    return m.group(1).strip().strip("'\"") if m else None


def repo_name_candidates(root: Path, explicit: str | None) -> list[tuple[str, str]]:
    if explicit:
        return [("repository name", explicit)]
    env = os.environ.get("GITHUB_REPOSITORY")
    if env and "/" in env:
        owner, name = env.split("/", 1)
        return [("repository owner", owner), ("repository name", name)]
    try:
        url = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                             capture_output=True, text=True, check=True).stdout.strip()
        m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", url)
        if m:
            return [("repository owner", m.group(1)), ("repository name", m.group(2))]
    except (OSError, subprocess.CalledProcessError):
        pass
    return [("repository name (directory)", root.name)]


def name_candidates(root: Path, files: list[str], explicit_repo: str | None) -> list[tuple[str, str]]:
    names = repo_name_candidates(root, explicit_repo)

    def read(rel: str) -> str | None:
        p = root / rel
        return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else None

    if (t := read("galaxy.yml")) is not None:
        for key in ("namespace", "name"):
            if v := _first(rf"^{key}:\s*(\S+)", t):
                names.append((f"galaxy.yml {key}", v))
    if (t := read("package.json")) is not None:
        try:
            if v := json.loads(t).get("name"):
                names.append(("package.json name", v))
        except json.JSONDecodeError:
            pass
    for rel, table in (("pyproject.toml", "project"), ("Cargo.toml", "package")):
        if (t := read(rel)) is not None and tomllib is not None:
            try:
                if v := tomllib.loads(t).get(table, {}).get("name"):
                    names.append((f"{rel} name", v))
            except tomllib.TOMLDecodeError:
                pass
    if (t := read("setup.cfg")) is not None:
        cp = configparser.ConfigParser()
        try:
            cp.read_string(t)
            if cp.has_option("metadata", "name"):
                names.append(("setup.cfg name", cp.get("metadata", "name")))
        except configparser.Error:
            pass
    if (t := read("go.mod")) is not None and (v := _first(r"^module\s+(\S+)", t)):
        names.append(("go.mod module", v.rsplit("/", 1)[-1]))
    for rel in ("action.yml", "action.yaml", "Chart.yaml"):
        if (t := read(rel)) is not None and (v := _first(r"^name:\s*(.+?)\s*$", t)):
            names.append((f"{rel} name", v))
    if (t := read("README.md")) is not None:
        body = re.sub(r"<!--\s*header:begin.*?header:end\s*-->", "", t, flags=re.DOTALL)
        if (v := _first(r"^#\s+(.+?)\s*#*\s*$", body)) and not PLACEHOLDER_RE.fullmatch(v):
            names.append(("README title", v))
    for rel in files:
        if rel.endswith(".json") and "dashboard" in rel.lower():
            try:
                data = json.loads((root / rel).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and "panels" in data and isinstance(data.get("title"), str):
                names.append((f"{rel} dashboard title", data["title"]))
    return names


def check_names(names: list[tuple[str, str]], rules: list[Rule], allow: list[AllowEntry], report: Report) -> None:
    for source, value in names:
        norm = value.casefold()
        for rule in rules:
            m = rule.regex.search(norm)
            if not m:
                continue
            if _allowed(allow, NAME_PSEUDO_PATH, rule, m.group(0), report):
                continue
            report.error(f"{NAME_PSEUDO_PATH}: {source} {value!r} contains the mark {rule.label!r}; "
                         "platform names belong in the description and topics", NAME_PSEUDO_PATH)


# --------------------------------------------------------------------------------------------
def run(root: Path, *, template_mode: bool = False, repo_name: str | None = None, only: list[str] | None = None,
        extra_terms: Path | None = None, check_names_too: bool = True) -> Report:
    report = Report()
    allow = load_allowlist(root)
    text_rules, name_rules = list(TEXT_RULES), list(NAME_RULES)
    if extra_terms:
        extra_text, extra_name = load_extra_terms(extra_terms)
        text_rules += extra_text
        name_rules += extra_name
    files = list_files(root, only)
    for rel in files:
        if FUNDING_RE.fullmatch(Path(rel).name):
            report.error(f"{rel}: a funding file must not exist (it adds a Sponsor button)", rel)
        else:
            scan_path(rel, text_rules, allow, report)
    listed: set[str] = set()
    if (root / "PLACEHOLDERS.md").is_file():
        listed = set(PLACEHOLDER_RE.findall((root / "PLACEHOLDERS.md").read_text(encoding="utf-8")))
    for rel in files:
        path = root / rel
        if rel == ALLOW_FILE or not is_text(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            report.warnings.append(f"{rel}: not UTF-8, skipped")
            continue
        report.files_scanned += 1
        scan_text(rel, text, text_rules, allow, report)
        scan_placeholders(rel, text, template_mode, listed, allow, report)
    if check_names_too:
        check_names(name_candidates(root, files, repo_name), name_rules, allow, report)
    for entry in allow:
        if entry.used == 0:
            report.warnings.append(f"{ALLOW_FILE}:{entry.line_no}: entry '{entry.glob} | {entry.term}' matched nothing; "
                                   "remove it if it is stale")
    return report


def check_string(text: str, extra_terms: Path | None = None) -> list[str]:
    """Wording check on a single string (PR titles, release notes, post drafts)."""
    report = Report()
    rules = list(TEXT_RULES)
    if extra_terms:
        rules += load_extra_terms(extra_terms)[0]
    scan_text("<stdin>", text, rules, [], report)
    return report.errors


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("paths", nargs="*", help="limit the scan to these files or folders (relative to --root)")
    p.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this script's repository)")
    p.add_argument("--template-mode", action="store_true",
                   help="allow {{PLACEHOLDERS}} listed in PLACEHOLDERS.md (only for the template repository)")
    p.add_argument("--repo-name", help="repository name for the name check (default: GITHUB_REPOSITORY, "
                                       "the origin remote, or the folder name)")
    p.add_argument("--extra-terms", type=Path, help="private term list outside the repository ('text <regex>' / "
                                                     "'name <regex>' per line)")
    p.add_argument("--stdin", action="store_true", help="check text from standard input (wording rules only)")
    p.add_argument("--format", choices=("text", "github"), default="text",
                   help="'github' also prints workflow annotations")
    p.add_argument("--list-rules", action="store_true", help="print the rules and exit")
    args = p.parse_args(argv)

    if args.list_rules:
        for rule in TEXT_RULES:
            print(f"text  {rule.rule_id:20} {rule.label}")
        for rule in NAME_RULES:
            print(f"name  {rule.rule_id:20} {rule.label}")
        return 0
    try:
        if args.stdin:
            errors = check_string(sys.stdin.read(), args.extra_terms)
            for e in errors:
                print(f"error: {e}")
            print(f"{len(errors)} finding(s)")
            return 1 if errors else 0
        report = run(args.root.resolve(), template_mode=args.template_mode, repo_name=args.repo_name,
                     only=args.paths or None, extra_terms=args.extra_terms)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    for w in report.warnings:
        print(f"warning: {w}")
    for e in report.errors:
        print(f"error: {e}")
    if args.format == "github":
        for a in report.gh_annotations:
            print(a)
    mode = "template mode" if args.template_mode else "publish mode"
    print(f"{len(report.errors)} finding(s), {len(report.warnings)} warning(s); {report.files_scanned} files, "
          f"{report.allowed} allowlisted match(es), {report.rule_text_lines} rule-text line(s); {mode}")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
