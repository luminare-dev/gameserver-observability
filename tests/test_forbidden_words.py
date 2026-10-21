"""Tests for scripts/forbidden_words.py (standard library unittest)."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import forbidden_words as fw  # noqa: E402


# Test addresses are built at run time, so the e-mail check still covers this file (an
# allowlist entry here would also let a real address through).
AT = "@"
PRIVATE_ADDRESS = "someone.private" + AT + "gmail.com"


def temp_dir(prefix: str = "fw-test-") -> Path:
    """A temporary folder that is removed when the tests of this module are done."""
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    unittest.addModuleCleanup(shutil.rmtree, tmp, ignore_errors=True)
    return tmp


def make_repo(files: dict[str, str | bytes], allow: str | None = None) -> Path:
    """A throw-away folder (not a git repository, so the folder walk is used)."""
    tmp = temp_dir()
    for rel, content in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
    if allow is not None:
        (tmp / fw.ALLOW_FILE).write_text(allow, encoding="utf-8")
    return tmp


def run(root: Path, **kw) -> fw.Report:
    kw.setdefault("repo_name", "clean-name")
    with mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": ""}):
        return fw.run(root, **kw)


def hits(text: str) -> list[str]:
    return fw.check_string(text)


class AcceptanceTest(unittest.TestCase):
    """Acceptance test of the template: the check fails on a test sentence."""

    def test_fails_on_a_test_sentence(self):
        sentence = "Buy the pro version now, prices from 5 € - coming soon, sponsor us or donate!"
        rule_ids = {e.split("[", 1)[1].split("]", 1)[0] for e in hits(sentence)}
        self.assertTrue({"buy", "pro-version", "price", "currency", "coming-soon", "sponsor", "donate"} <= rule_ids,
                        rule_ids)

    def test_stdin_mode_exit_codes(self):
        script = str(ROOT / "scripts" / "forbidden_words.py")
        bad = subprocess.run([sys.executable, script, "--stdin"], input="Hire me for your next project",
                             capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1, bad.stdout)
        good = subprocess.run([sys.executable, script, "--stdin"], input="Idempotent roles, tested with Molecule.",
                              capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stdout)

    def test_german_test_sentence(self):
        sentence = "Jetzt kaufen: Preis auf Anfrage, demnächst bald verfügbar, Spenden willkommen."
        self.assertGreaterEqual(len(hits(sentence)), 4)


class WordingRulesTest(unittest.TestCase):
    def assertHit(self, text: str, rule_id: str):
        found = [e for e in hits(text) if f"[{rule_id}]" in e]
        self.assertTrue(found, f"{rule_id!r} not found in {text!r}: {hits(text)}")

    def assertClean(self, text: str):
        self.assertEqual(hits(text), [], text)

    def test_english_terms(self):
        cases = {
            "price": "See the price list", "currency": "only 9 EUR", "hire": "We are hiring",
            "buy": "purchase a licence", "sell": "we sell add-ons", "invoice": "an invoice follows",
            "pro-version": "the Pro-Version has more", "paid-tier": "a paid plan exists",
            "commercial-licence": "commercial license available", "paid-support": "priority support",
            "services": "our services", "custom-work": "custom integrations on request",
            "quote": "request a quote", "availability": "available for projects",
            "coming-soon": "launching soon", "waitlist": "join the wait-list", "sponsor": "sponsored",
            "donate": "donations welcome", "funding": "funding", "affiliate-ads": "affiliate link",
            "shop-store": "visit our webshop", "special-offer": "limited time", "crypto": "bitcoin",
        }
        for rule_id, text in cases.items():
            with self.subTest(rule_id=rule_id):
                self.assertHit(text, rule_id)

    def test_german_terms(self):
        cases = {
            "de-price": "Preise ab", "de-buy": "jetzt kaufen", "de-donate": "spenden Sie",
            "de-coming-soon": "bald verfügbar", "de-offer": "unser Angebot", "de-commission": "beauftragen Sie mich",
            "de-services": "Dienstleistungen", "de-ads": "Werbung",
        }
        for rule_id, text in cases.items():
            with self.subTest(rule_id=rule_id):
                self.assertHit(text, rule_id)

    def test_german_compounds_and_phrasings(self):
        cases = [
            ("de-donate", "Spendenkonto"), ("de-donate", "Spendenaktion"), ("de-donate", "Spendenseite"),
            ("de-donate", "Spendenlink"), ("de-donate", "Unterstützen Sie uns"),
            ("de-price", "Einführungspreis"), ("de-price", "Sonderpreis"), ("de-price", "Festpreis"),
            ("de-price", "Kaufpreis"), ("de-price", "Preismodell"), ("de-price", "Preisvorteil"),
            ("de-price", "Abonnement"), ("de-shop", "Produktlinie"), ("de-shop", "Store-Seite"),
            ("de-ads", "Partnerprogramm"), ("de-buy", "Bezahlversion"), ("de-buy", "kauf jetzt"),
        ]
        for rule_id, text in cases:
            with self.subTest(text=text):
                self.assertHit(text, rule_id)

    def test_funding_and_offer_gaps(self):
        cases = [
            ("funding", "crowdfunding"), ("funding-platform", "Kickstarter"), ("funding-platform", "Indiegogo"),
            ("funding-platform", "steadyhq.com/x"), ("funding-platform", "flattr.com"),
            ("funding-platform", "donorbox.org"), ("funding-platform", "checkout.stripe.com/x"),
            ("funding-platform", "revolut.me/x"), ("donate", "support us"),
            ("commercial-licence", "licensing options available"), ("paid-support", "Enterprise support"),
        ]
        for rule_id, text in cases:
            with self.subTest(text=text):
                self.assertHit(text, rule_id)

    def test_phrases_broken_across_lines(self):
        for rule_id, text in (("pro-version", "the pro\nversion"), ("coming-soon", "coming\n  soon"),
                              ("availability", "available for\nprojects"), ("de-commission", "Preis auf\nAnfrage")):
            with self.subTest(text=text):
                self.assertHit(text, rule_id)
        found = hits("line one\nthe pro\nversion")
        self.assertEqual(len(found), 1, found)
        self.assertIn("<stdin>:2:5: [pro-version]", found[0])  # reported once, on the line it starts

    def test_unicode_and_entity_evasions(self):
        cases = [
            ("mixed-script", "pr\u0456ce list"),          # Cyrillic i
            ("price", "pri\u200bce list"),                # zero-width space
            ("price", "\uff50\uff52\uff49\uff43\uff45"),  # full-width letters
            ("pro-version", "pro\u2011version"),          # non-breaking hyphen
            ("currency", "&#8364; 5"), ("currency", "&#x20AC; 5"), ("currency", "5EUR"),
            ("product-path", "https://luminare.tech/store"), ("product-path", "https://luminare.tech/products/"),
            ("product-path", "https://luminare.tech/services/"),
        ]
        for rule_id, text in cases:
            with self.subTest(text=text):
                self.assertHit(text, rule_id)

    def test_domains_and_hosts(self):
        self.assertHit("https://example.tebex.io/package/1", "store-domain")
        self.assertHit("https://ko-fi.com/someone", "funding-platform")
        self.assertHit("https://github.com/sponsors/someone", "funding-platform")
        self.assertHit("https://patreon.com/x", "funding-platform")
        self.assertHit("https://play.google.com/store/apps/details?id=x", "store-domain")
        self.assertHit("docs live on scripts.example.tech", "product-host")
        self.assertHit("store.example-studio.com", "product-host")
        self.assertClean("store.example.com and https://example.com/products")  # reserved example domains

    def test_case_insensitive(self):
        self.assertHit("PRO VERSION", "pro-version")
        self.assertHit("Coming Soon", "coming-soon")

    def test_word_boundaries_and_tuned_false_positives(self):
        for text in (
            "a key-value store keeps the token",       # bare "store"
            "the HTTP client retries",                  # "client"
            "Ansible bietet Module für alles",          # "bietet"
            "Daten nie preisgeben",                     # "preisgeben" vs "Preis"
            "Grafana Cloud free tier",                  # "free tier"
            "set sv_licenseKey from the vault",         # licence key wording
            "Not affiliated with or endorsed by Cfx.re, Rockstar Games or Take-Two.",
            "Watch the repository to subscribe to releases",
            "the systemd service restarts",
            "das nehmen wir in Kauf",                   # idiom
            "decommission the old host",                # "commission" inside a word
            "open a pull request",                      # "request"
            "workshop notes",                           # "shop" inside a word
            "a buyer persona",                          # "buy" inside a word
            "die Preisgabe von Daten",                  # "Preisgabe" vs "Preis"
            "the job stays suspended",                  # "spende" inside an English word
            "120 µs latency, Δt = 5 s",                 # Greek letters that look unlike Latin ones
            "Grüße, naïve café",                        # accented Latin letters
            "support us-east-1 and eu-west-1",          # a region name, not "support us"
            "curl 'https://x.example/?a=1&notify=1'",   # an entity without ";" stays as it is
        ):
            with self.subTest(text=text):
                self.assertClean(text)


class RepositoryScanTest(unittest.TestCase):
    def test_clean_repository(self):
        root = make_repo({"README.md": "# clean-name\n\nIdempotent roles.\n"})
        report = run(root)
        self.assertEqual(report.errors, [])

    def test_finding_with_location(self):
        root = make_repo({"docs/a.md": "line one\nbuy now\n"})
        report = run(root)
        self.assertEqual(len(report.errors), 1)
        self.assertIn("docs/a.md:2:1: [buy]", report.errors[0])

    def test_rule_text_marker_exempts_the_line(self):
        root = make_repo({"RULES.md": "- never write coming soon <!-- rule-text -->\n"})
        report = run(root)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.rule_text_lines, 1)

    def test_rule_text_marker_as_yaml_comment(self):
        root = make_repo({"ci.yml": "- name: Forbidden words, funding file  # rule-text\n"})
        report = run(root)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.rule_text_lines, 1)

    def test_rule_text_only_as_end_of_line_comment(self):
        for line in ("Buy the pro version now rule-text",                       # the word in prose
                     "[shop](https://example.tebex.io) see /docs/rule-text.md",  # in a path
                     "prices: https://x.example/rule-texts",                     # in a URL
                     "<!-- rule-text --> buy now",                               # not at the end
                     "buy now #rule-text-ish"):
            with self.subTest(line=line):
                report = run(make_repo({"a.md": line + "\n"}))
                self.assertTrue(report.errors, line)
                self.assertEqual(report.rule_text_lines, 0)

    def test_rule_text_does_not_excuse_private_terms(self):
        root = make_repo({"a.md": "Jane Example wrote this <!-- rule-text -->\n"})
        extra = temp_dir() / "private.txt"
        extra.write_text("text jane\\s+example\n", encoding="utf-8")
        self.assertEqual(len(run(root, extra_terms=extra).errors), 1)

    def test_file_paths_are_checked(self):
        root = make_repo({"docs/pricing.md": "ok\n", "docs/donate.md": "ok\n", "docs/install.md": "ok\n"})
        errors = run(root).errors
        self.assertEqual(len(errors), 2, errors)
        self.assertTrue(any(e.startswith("docs/pricing.md: [price]") for e in errors), errors)
        self.assertTrue(any(e.startswith("docs/donate.md: [donate]") for e in errors), errors)

    def test_binary_files_are_skipped(self):
        root = make_repo({"img.png": b"\x89PNG\0buy now", "data.bin": b"\0\0buy now"})
        self.assertEqual(run(root).errors, [])

    def test_funding_file_fails_and_cannot_be_allowlisted(self):
        root = make_repo({".github/FUNDING.yml": "github: [someone]\n"})
        self.assertTrue(any("funding file" in e for e in run(root).errors))
        root2 = make_repo({"x.md": "ok\n"}, allow=".github/FUNDING.yml | * | trying to excuse the file anyway\n")
        with self.assertRaises(fw.ConfigError):
            run(root2)

    def test_funding_yaml_variant_any_case(self):
        root = make_repo({"docs/Funding.YAML": "x\n"})
        self.assertTrue(any("funding file" in e for e in run(root).errors))


class AllowlistTest(unittest.TestCase):
    def test_entry_by_rule_id(self):
        root = make_repo({"src/data/rates.json": '{"currency": "€"}\n'},
                         allow="src/data/* | currency | calculator data needs the currency sign\n")
        report = run(root)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.allowed, 1)

    def test_entry_by_matched_text_is_narrow(self):
        root = make_repo({"README.md": "Get it on https://play.google.com/store/apps/details?id=x\n"
                                       "or https://apps.apple.com/app/id1\n"},
                         allow="README.md | play.google.com | the free app's own store page\n")
        report = run(root)
        self.assertEqual(len(report.errors), 1)
        self.assertIn("apps.apple.com", report.errors[0])

    def test_entry_scoped_to_path(self):
        root = make_repo({"src/data/x.json": "€\n", "README.md": "€\n"},
                         allow="src/data/* | € | calculator data only\n")
        report = run(root)
        self.assertEqual(len(report.errors), 1)
        self.assertIn("README.md", report.errors[0])

    def test_reason_is_required(self):
        root = make_repo({"a.md": "x\n"}, allow="a.md | buy |\n")
        with self.assertRaises(fw.ConfigError):
            run(root)
        root2 = make_repo({"a.md": "x\n"}, allow="a.md | buy | short\n")
        with self.assertRaises(fw.ConfigError):
            run(root2)

    def test_unused_entry_warns(self):
        root = make_repo({"a.md": "fine\n"}, allow="a.md | buy | an entry nobody needs any more\n")
        report = run(root)
        self.assertEqual(report.errors, [])
        self.assertTrue(any("matched nothing" in w for w in report.warnings))

    def test_star_does_not_excuse_addresses_or_private_terms(self):
        root = make_repo({"tests/test_x.py": f"ADDRESS = '{PRIVATE_ADDRESS}'  # Jane Example\n"},
                         allow="tests/test_x.py | * | test sentences that must trigger the rules\n"
                               "tests/test_x.py | extra-1 | trying to excuse a private term anyway\n")
        extra = temp_dir() / "private.txt"
        extra.write_text("text jane\\s+example\n", encoding="utf-8")
        errors = run(root, extra_terms=extra).errors
        self.assertEqual(len(errors), 2, errors)
        self.assertTrue(any("[email]" in e for e in errors), errors)
        self.assertTrue(any("[extra-1]" in e for e in errors), errors)

    def test_name_pseudo_path(self):
        root = make_repo({"README.md": "x\n"}, allow="@name | ansible | registry naming convention for collections\n")
        report = run(root, repo_name="ansible-collection-infra_edge")
        self.assertEqual(report.errors, [])


class NameCheckTest(unittest.TestCase):
    def names_errors(self, **kw) -> list[str]:
        files = kw.pop("files", {"README.md": "x\n"})
        root = make_repo(files)
        return [e for e in run(root, **kw).errors if e.startswith("@name")]

    def test_platform_marks_in_repo_name(self):
        for name in ("fivem-tools", "FiveM_Admin", "five-m-kit", "cfx-helper", "my-txadmin-backup", "redm-scripts",
                     "gta-utils", "rockstar-stats", "fxinstaller", "fx-tools", "citizenfx-ci"):
            with self.subTest(name=name):
                self.assertTrue(self.names_errors(repo_name=name), name)

    def test_vendor_marks_in_repo_name(self):
        for name in ("proxmox-backup-checker", "windows-wifi-heatmap", "grafana-pack", "prometheus-rules"):
            with self.subTest(name=name):
                self.assertTrue(self.names_errors(repo_name=name), name)

    def test_neutral_names_pass(self):
        for name in ("gameserver-observability", "infra-edge-lab", "lua-resource-kit", "oss-template",
                     "effects-lab", "netfx-free", "redmond-notes", "readme-tools"):
            with self.subTest(name=name):
                self.assertEqual(self.names_errors(repo_name=name), [], name)

    def test_galaxy_and_package_names(self):
        files = {"galaxy.yml": "namespace: luminare\nname: fivem_server\nversion: 0.1.0\n",
                 "package.json": '{"name": "txadmin-helper"}\n', "README.md": "x\n"}
        errors = self.names_errors(repo_name="neutral", files=files)
        self.assertEqual(len(errors), 2, errors)

    def test_readme_title_and_dashboard_title(self):
        files = {"README.md": "<!-- header:begin -->\n# ignored FiveM header\n<!-- header:end -->\n# Cfx Monitor\n",
                 "dashboards/main-dashboard.json": '{"title": "Grafana FXServer board", "panels": []}\n'}
        errors = self.names_errors(repo_name="neutral", files=files)
        self.assertEqual(len(errors), 3, errors)  # Cfx in the title; Grafana and FX... in the dashboard

    def test_placeholder_title_is_skipped(self):
        files = {"README.md": "# {{PROJECT_TITLE}}\n"}
        root = make_repo(files)
        report = run(root, repo_name="neutral", template_mode=True)
        self.assertEqual([e for e in report.errors if e.startswith("@name")], [])


class PlaceholderTest(unittest.TestCase):
    def test_unfilled_placeholder_fails_in_publish_mode(self):
        root = make_repo({"README.md": "# {{PROJECT_TITLE}}\n", "PLACEHOLDERS.md": "{{PROJECT_TITLE}}\n"})
        self.assertTrue(any("unfilled placeholder" in e for e in run(root).errors))

    def test_template_mode_allows_listed_placeholders_only(self):
        root = make_repo({"README.md": "{{SLUG}} {{OTHER}}\n", "PLACEHOLDERS.md": "| `{{SLUG}}` | x |\n"})
        errors = run(root, template_mode=True).errors
        self.assertEqual(len(errors), 1)
        self.assertIn("OTHER", errors[0])

    def test_github_expressions_and_jinja_are_not_placeholders(self):
        root = make_repo({"ci.yml": "token: ${{ secrets.GITHUB_TOKEN }}\nx: ${{ FOO }}\n",
                          "role.j2": "{{ ansible_host }}\n"})
        self.assertEqual(run(root).errors, [])

    def test_template_hints_fail_in_publish_mode(self):
        root = make_repo({"README.md": "<!-- template: fill me -->\n<!-- template-only:begin -->\nx\n"})
        errors = run(root).errors
        self.assertEqual(len(errors), 2, errors)
        self.assertEqual(run(root, template_mode=True).errors, [])

    def test_placeholder_allowlist(self):
        root = make_repo({"docs/howto.md": "write {{AUTHOR_NAME}} into NOTICE\n"},
                         allow="docs/howto.md | placeholder | documents the placeholder syntax\n")
        self.assertEqual(run(root).errors, [])


class EmailTest(unittest.TestCase):
    def test_private_address_fails(self):
        root = make_repo({"docs/a.md": f"Write to {PRIVATE_ADDRESS} for help\n"})
        errors = run(root).errors
        self.assertEqual(len(errors), 1)
        self.assertIn("[email]", errors[0])

    def test_role_noreply_and_example_addresses_pass(self):
        root = make_repo({"docs/a.md": "security@luminare.tech, oss@luminare.tech, conduct@luminare.tech, "
                                       "76869048+someone@users.noreply.github.com, you@example.com, "
                                       "test@example.invalid, git clone git@github.com:o/r.git, "
                                       "actions/checkout@v7 and pkg@1.2.3\n"
                                       f"Co-Authored-By: A Tool <noreply{AT}vendor.example-tool.com>\n"})
        self.assertEqual(run(root).errors, [])

    def test_email_allowlist(self):
        root = make_repo({"a.md": f"upstream maintainer: maintainer{AT}upstream.org\n"},
                         allow="a.md | email | the upstream project's published contact address\n")
        self.assertEqual(run(root).errors, [])


class ExtraTermsTest(unittest.TestCase):
    def test_private_extra_terms(self):
        root = make_repo({"a.md": "Contact Jane Example at the office\n"})
        extra = temp_dir() / "private.txt"
        extra.write_text("# private list\ntext jane\\s+example\nname secret-codename\n", encoding="utf-8")
        report = run(root, extra_terms=extra, repo_name="secret-codename-tool")
        self.assertEqual(len(report.errors), 2, report.errors)

    def test_bad_extra_line(self):
        extra = temp_dir() / "private.txt"
        extra.write_text("jane\n", encoding="utf-8")
        with self.assertRaises(fw.ConfigError):
            fw.load_extra_terms(extra)


class CliTest(unittest.TestCase):
    def test_list_rules(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(fw.main(["--list-rules"]), 0)
        self.assertIn("pro-version", buf.getvalue())
        self.assertIn("fx-coinage", buf.getvalue())

    def test_github_annotations(self):
        root = make_repo({"a.md": "buy\n"})
        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": ""}):
            code = fw.main(["--root", str(root), "--repo-name", "x", "--format", "github"])
        self.assertEqual(code, 1)
        self.assertIn("::error file=a.md,line=1,col=1::", buf.getvalue())

    def test_config_error_exit_code(self):
        root = make_repo({"a.md": "x\n"}, allow="broken line without separators\n")
        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch("sys.stderr", new=io.StringIO()):
            self.assertEqual(fw.main(["--root", str(root), "--repo-name", "x"]), 2)

    def test_this_repository_is_clean_in_template_mode(self):
        """The template itself passes its own check (the CI step in template mode)."""
        with mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "luminare-dev/oss-template"}):
            report = fw.run(ROOT, template_mode=True)
        self.assertEqual(report.errors, [])


if __name__ == "__main__":
    unittest.main()
