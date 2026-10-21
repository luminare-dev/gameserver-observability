# Placeholders

Every value in double curly braces is a placeholder. In this template repository CI runs the
wording check in template mode, which accepts the placeholders listed below and nothing else. In
a repository created from the template, CI fails on every placeholder that is still open, so the
list doubles as the fill-in checklist (about 20 minutes for the README).

## Filled in every new repository

| Placeholder | Where | Fill with |
|---|---|---|
| `{{SLUG}}` | `README.md` (badges, links, byline), `docs/install.md` | The repository name, which is also the project page slug: `https://luminare.tech/open-source/<slug>/`. Lower case, hyphens, no platform names. |
| `{{PROJECT_TITLE}}` | `README.md` (title, header alt text, diagram) | The display name. Neutral: no FiveM, Cfx, RedM, txAdmin, GTA, Rockstar, FX… coinage, and no vendor mark such as Proxmox, Windows, Prometheus or Grafana. |
| `{{ONE_LINE_PURPOSE}}` | `README.md` | One sentence: what it does and for whom. "… for FiveM/RedM servers (FXServer)" is allowed here, never in the name. |
| `{{PROBLEM_STATEMENT}}` | `README.md` (Why) | 2–4 sentences on the problem and what the project shows. |
| `{{QUICKSTART_COMMANDS}}` | `README.md` (Quickstart), `docs/install.md` | At most five commands, tested on a clean machine. |
| `{{TARGET_SYSTEM}}` | `README.md` (diagram) | What the project acts on, for example "Ubuntu 24.04 host". |
| `{{COMPONENT}}`, `{{TESTED_VERSION}}`, `{{SUPPORTED_RANGE}}` | `README.md` (Supported versions); `{{COMPONENT}}` and `{{SUPPORTED_RANGE}}` also in `docs/install.md` | One row per runtime or dependency that matters. |
| `{{LIMITATION}}` | `README.md` (Limitations) | One bullet per limitation. |
| `{{RESULT}}`, `{{VALUE}}`, `{{METHOD}}` | `README.md` (Results) | Measured numbers with method and date. |
| `{{SPDX_ID}}` | `README.md` (Licence) | The SPDX id of the chosen licence (`Apache-2.0`, `MIT`), see [licenses/CHOOSING.md](licenses/CHOOSING.md). |
| `{{AUTHOR_NAME}}` | the inactive personal byline in `README.md`; `LICENSE` and `NOTICE` of a new repository (copied from `licenses/` and brand-repos) | The copyright holder, a natural person: the full legal name, in the same form in every repository. This template's own `LICENSE` and `NOTICE` already carry it, because the template is published itself. |
| `{{YEAR}}` | `LICENSE` and `NOTICE` of a new repository (copied from `licenses/` and brand-repos) | The year of first publication. `LICENSE` is always copied fresh from `licenses/`, even when MIT is kept: the template's own `LICENSE` carries the template's year, and no check notices a wrong year. |
| `{{VERSION}}` | `docs/upgrade.md` | The version an upgrade note applies to. |

## Values to check, not placeholders

| Value | Where | Why |
|---|---|---|
| `ci / lint-test`, `secrets / gitleaks`, `pr / pr-title`, `DCO` | the repository ruleset (required status checks) | Reusable workflows report as `<caller job> / <called job>`. A required check that never reports blocks every merge. |
| `luminare-dev` | `README.md` badges and links | The organization that holds the repository. |
| `oss-template` in `docs/brand/` | header SVGs and social preview | Replace with the files generated for the new slug by brand-repos (PUBLISHING.md, A3). |
| `release-please-config.json` → `initial-version` | first release | `0.1.0`; stay below 1.0.0 until the public interface is stable. |
| `version.txt` | release-please | Starts at `0.0.0`; release-please updates it. |
