# Publishing checklist

One gate before a repository goes public and before any release is announced. Part A sets up a
new repository from this template, part B is the gate itself, part C covers each release and
part D the upkeep. Copy part B into the pull request or issue that makes the repository public,
tick every box, and note the date. A box that cannot be ticked stops the publication.

Facts and links in this file were checked on 2026-10-06 (A7 and B17 on 2026-10-07).

## A. Set up a new repository from the template

- [ ] **A1 Create it.** In [luminare-dev](https://github.com/luminare-dev): **Use this template**,
      visibility **private** until part B passes. The name follows B4. Untick *Template
      repository* in Settings → General if it was copied (only `oss-template` is a template; the
      release workflow skips template repositories).
- [ ] **A2 Fill the README.** Delete the template-only note (with its two marker comments), fill
      every placeholder from [PLACEHOLDERS.md](PLACEHOLDERS.md) and resolve every
      `<!-- template: … -->` hint. Keep the section order: it is the order the project page on
      luminare.tech expects (problem, install, decisions, results, links), and the header block
      between `header:begin` and `header:end` is dropped there.
- [ ] **A3 Brand files.** In brand-repos, add the repository to `repos.yaml` (slug, title,
      one-line description, `variant: studio`, licence), run `build_repos.py`, then copy
      `out/<slug>/studio/*` to `docs/brand/` and `out/<slug>/NOTICE` to `NOTICE`. Fill the
      `AUTHOR_NAME` and `YEAR` placeholders in `NOTICE`. Check with
      `python3 scripts/set_byline.py verify --expect studio`. **Ansible collections** (their
      README is also shown on galaxy.ansible.com): replace the README's whole header block (from
      the `header:begin` to the `header:end` comment) with `out/<slug>/README-snippet.md`, whose
      image links are absolute `raw.githubusercontent.com` URLs (Galaxy drops `<picture>` and
      keeps a relative `<img src>` unchanged, so `docs/brand/…` breaks there), and add
      `docs/brand` to `build_ignore` in `galaxy.yml`, so the brand files, which the licence does
      not cover, stay out of the collection artifact. Check the header on Galaxy after the
      first import.
- [ ] **A4 Licence.** Follow [licenses/CHOOSING.md](licenses/CHOOSING.md): `LICENSE`, the README's
      licence line, then remove the unused texts in `licenses/`. Always copy `LICENSE` fresh from
      `licenses/` with the year of first publication, even when MIT is kept: the template's own
      `LICENSE` carries the template's year.
- [ ] **A5 Release files.** Keep `CHANGELOG.md` (seed with the "Origin" entry),
      `.release-please-manifest.json` (`{}`), `version.txt` (`0.0.0`) and
      `release-please-config.json` (`initial-version` `0.1.0`) as they are.
- [ ] **A6 Tests.** Replace or extend `tests/` with the project's own tests and set the test
      command in `ci.yml` and `release.yml` (input `test-command`) if it is not
      `python3 -m unittest discover -s tests -v`.
- [ ] **A7 Settings.** Work through section 3 of the organization's
      [SETTINGS.md](https://github.com/luminare-dev/.github/blob/main/SETTINGS.md), with these
      values for this template's workflows:
  - required status checks: `ci / lint-test`, `secrets / gitleaks`, `pr / pr-title` (GitHub
    Actions) and `DCO` (DCO app). Reusable workflows report as `<caller job> / <called job>`;
    import the ruleset only after each check has run once on a pull request.
  - Settings → Actions → General: *Allow GitHub Actions to create and approve pull requests* on
    (release-please opens the release pull request with `GITHUB_TOKEN`).
  - Allowed actions (organization or repository): actions created by GitHub (`actions/*`,
    `github/*`) plus only the third-party actions these workflows use, each pinned by SHA:
    `DavidAnson/markdownlint-cli2-action`, `googleapis/release-please-action` and
    `ossf/scorecard-action`.
  - Settings → General → Releases: immutable releases on. The release workflow creates a draft,
    attaches every file and publishes last, so it works with immutable releases.
- [ ] **A8 Local run.** All commands in part E pass.

## B. The gate

- [ ] **B1 Licence and NOTICE.** `LICENSE` holds one SPDX licence and GitHub shows it in the
      sidebar. `NOTICE` excludes the names, logos and `docs/brand/` from the licence and keeps the
      font's OFL. Vendored code is listed in `THIRD_PARTY_NOTICES.md`.
- [ ] **B2 No secrets in any commit.** `gitleaks git --redact --config .gitleaks.toml .` reports
      0 findings over the **full** history, and the `secrets / gitleaks` check is green. For any
      finding: **rotate first** (revoke the key or token, issue a new one), then remove it from
      history or publish with a fresh history. A secret that was ever pushed counts as leaked.
      Game-server license keys (`cfxk_…`) are also scanned for by the platform on public
      repositories.
- [ ] **B3 No personal or internal data.** No player data (names, identifiers, IPs) in code,
      fixtures, metrics labels, logs or screenshots: counts only. No internal IP addresses, tenant
      or subscription IDs, account numbers or hostnames. Hostnames must be public names on the
      studio's hostname registry or reserved examples (`example.com`, `.example`, `.invalid`,
      `.test`); example IPs come from `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24` and
      `2001:db8::/32`. Helpful searches:
      `git grep -nE '\b([0-9]{1,3}\.){3}[0-9]{1,3}\b'` (IPv4),
      `git grep -nEi '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'` (GUIDs, tenant
      IDs) and a look at every image in the repository. No FXServer artifacts, game files or
      Rockstar assets in the repository or in release archives; link to the official downloads
      instead.
- [ ] **B4 Names.** Repository name, Galaxy namespace and collection name, package names, a
      GitHub Action name and grafana.com dashboard titles carry no platform or vendor mark:
      never FiveM, Cfx, CitizenFX, RedM, txAdmin, GTA, Rockstar, Take-Two or an FX… coinage, and
      no Proxmox, Windows, Microsoft, Prometheus, Grafana or similar as the name. "… for
      FiveM/RedM servers (FXServer)" belongs in the description and topics only. Galaxy
      collection names and versions and grafana.com titles are **permanent**: decide them once.
      The Galaxy namespace is `luminare` (fallback `luminare_dev` if Galaxy does not grant it).
      The name check in `scripts/forbidden_words.py` is green; a registry convention such as
      `ansible-collection-<name>` needs an `@name` line in `.forbidden-words-allow`.
- [ ] **B5 Byline.** The studio byline "a Luminare Development open-source project" with the link
      to `https://luminare.tech/open-source/<slug>/` is active, under the header and in the
      licence section, and `python3 scripts/set_byline.py verify --expect studio` passes. The
      header renders in GitHub's light and dark theme. (The personal byline is the one-command
      fallback: `python3 scripts/set_byline.py personal`, then the brand swap it prints.)
- [ ] **B6 Wording check green in publish mode.** `python3 scripts/forbidden_words.py` (without
      `--template-mode`) reports 0 findings: no offer, price, funding or store wording in English <!-- rule-text -->
      or German, no unfilled placeholder, no template hint, no private e-mail address. Review every
      entry in `.forbidden-words-allow` and every line that ends with a `rule-text` comment (both
      are counted in the summary line). Also run it once with the maintainer's private term list:
      `--extra-terms <private list outside the repository>`. The commit history is public too:
      `git log --all --format='%an <%ae>%n%cn <%ce>%n%B' | python3 scripts/forbidden_words.py --stdin --extra-terms <private list>`
      reports 0 findings for every commit message and author line; otherwise reword those
      commits before the first push, or publish with a fresh history.
- [ ] **B7 Sponsorships off, no funding file.** Settings → General → Features: *Sponsorships* <!-- rule-text -->
      unticked. No `FUNDING.yml` anywhere; the check fails on one, and the organization's <!-- rule-text -->
      `.github` repository has none either.
- [ ] **B8 Social preview.** `docs/brand/social-preview-1280x640.png` (studio variant from
      brand-repos, 1280×640, under 1 MB) uploaded under Settings → General → Social preview.
      Never game screenshots, Rockstar or GTA art, or logos of other projects.
- [ ] **B9 Description and topics.** One factual sentence as the description; the website field
      points to the project page. Descriptive topics (for example `ansible`, `ansible-collection`,
      `molecule`, `prometheus`, `grafana-dashboard`, `fxserver`, `fivem`). FXServer projects keep
      the "Not affiliated" section in the README.
- [ ] **B10 Release notes are factual.** Release notes come from the pull request titles (the
      `pr / pr-title` check runs the wording check on each title). Read the release body before
      announcing it: what changed and why, nothing else.
- [ ] **B11 Records.** The repository is listed in `repos.json` in the private `oss-metrics`
      repository with `planned: false` (planned repositories are already there with
      `planned: true`; add any other), is covered by `METRICS_TOKEN` (when the token uses "Only
      select repositories", add it to the selection; oss-metrics README, "Setup"), and gets its
      first snapshot within 14 days. It is also added to the maintainer's private artefact list
      (name, licence, URL, date it became public).
- [ ] **B12 No unfilled placeholders.** Covered by B6; double-check `NOTICE`, `LICENSE` and the
      ADR dates.
- [ ] **B13 Allowlist exceptions are narrow.** A project that must show a currency sign or link
      its own free app or extension listing (calculators, mobile apps, browser extensions) gets
      one reviewed line per exception in `.forbidden-words-allow`: scoped to its data or UI files,
      or to the one listing domain it really uses (`apps.apple.com`, `play.google.com`, <!-- rule-text -->
      `f-droid.org`, `chromewebstore.google.com`, `microsoftedge.microsoft.com`), always with a <!-- rule-text -->
      reason. A funding file can never be allowlisted. <!-- rule-text -->
- [ ] **B14 Security settings.** Private vulnerability reporting, secret scanning with push
      protection and Dependabot alerts are on; the ruleset from A7 is active; *Sponsorships* is <!-- rule-text -->
      still off.
- [ ] **B15 Logged-out view.** Open the repository in a private browser window: README, header,
      licence, release and links work, and nothing private shows.
- [ ] **B16 Forum release post (FXServer projects, optional).** Only within the Cfx.re forum's
      [release rules](https://forum.cfx.re/t/releases-rules-and-faq/240725) (version of
      2024-11-04, read 2026-10-06):
  - the repository is public with its FOSS licence and a GitHub release to download (the forum
    asks for a public git repository or a forum upload; never a registration, Discord join or
    licence token to get or run it);
  - links only of the allowed kinds: GitHub, documentation, support site, Discord (support only,
    never for delivery), video platforms such as YouTube, dependencies; no other social media
    and nothing outside that list, in particular no donation or sponsor links; <!-- rule-text -->
  - the "free" tag and topic tags, a complete description written by hand (the forum rejects
    pasted language-model output), a demo video or screenshots (first image uploaded to the
    forum), resource monitor numbers or a profiler screenshot;
  - code quality: no `GetPlayerPed(-1)`, no `__resource.lua`, not a single file under 50 lines;
  - at most one release topic per 48 hours; the account has trust level 1;
  - the title follows the pattern `<name> for FiveM`, and the post carries the not-affiliated line.
- [ ] **B17 Link targets are live.** The project page `https://luminare.tech/open-source/<slug>/`
      (byline, README links and the website field from B9) answers with HTTP 200, and the
      organization's `luminare-dev/.github` repository is public, so the README's contributing,
      conduct, security and support links work. Until both hold, publication waits.

## C. Every release

- [ ] Merge pull requests with Conventional Commit titles only; release-please keeps a release
      pull request (`chore(main): release X.Y.Z`) up to date.
- [ ] Before merging the release pull request, **close and reopen it** once: pull requests opened
      with `GITHUB_TOKEN` do not start workflows, so the required checks would never report.
- [ ] Before merging the release pull request, the commit history check from B6 (with the
      private term list) still reports 0 findings.
- [ ] After the merge, the `release` workflow creates the draft release and the tag, builds
      `<slug>-X.Y.Z.tar.gz` with `SHA256SUMS`, attests the archive and publishes the release.
      Verify it from outside with the commands below this list.
- [ ] Registry uploads follow their own rules: Galaxy versions can never be changed or deleted
      (test the tarball first, stay below 1.0.0 until the interface is stable); a grafana.com
      dashboard names its licence in the description.
- [ ] Announce a release once per venue, only after part B holds for that version, with the
      promotion templates and each venue's own rules.

```bash
gh release download vX.Y.Z -R luminare-dev/<slug>
sha256sum -c SHA256SUMS
gh attestation verify <slug>-X.Y.Z.tar.gz -R luminare-dev/<slug>
```

## D. Upkeep

- **Weekly:** notifications, triage (first reply within 7 days), Dependabot pull requests, red CI.
- **Monthly:** the Actions tab (GitHub disables scheduled workflows in public repositories after
  60 days without activity; the weekly Scorecard run is one); bump the pinned gitleaks and
  actionlint downloads by hand (version and sha256 inputs in `reusable-gitleaks.yml` and
  `reusable-ci.yml`, sha256 from the vendor's checksums file); check that the tools in
  `requirements-dev.txt` are current.
- **Quarterly:** licence and NOTICE review, Scorecard results, archive repositories that are no
  longer maintained (with a note in the README).

## E. Local commands

The same checks as CI. Python 3.10 or later; the tools from `requirements-dev.txt` in a virtual
environment; `gitleaks`, `actionlint` and `markdownlint-cli2` on the `PATH`.

```bash
python3 scripts/forbidden_words.py                    # publish mode (template mode: --template-mode)
git log --all --format='%an <%ae>%n%cn <%ce>%n%B' | python3 scripts/forbidden_words.py --stdin
python3 scripts/set_byline.py verify --expect studio
python3 scripts/check_workflows.py --list
python3 -m unittest discover -s tests -v
gitleaks git --redact --config .gitleaks.toml .
yamllint --strict .
markdownlint-cli2 "**/*.md"
actionlint
zizmor --offline .github/workflows
```
