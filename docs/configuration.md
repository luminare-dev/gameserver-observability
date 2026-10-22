# Configuration

The pack's own options (scrape targets, exporter modules, rule thresholds, dashboard variables) are
added with those files; none of them is in the repository yet. These are the settings that exist
today, all of them for the repository's checks:

| Option | Type | Default | Description |
|---|---|---|---|
| `TEST_VENV` (environment, `scripts/test.sh`) | path | in CI `$RUNNER_TEMP/gameserver-observability-test-venv`, elsewhere `${XDG_CACHE_HOME:-~/.cache}/gameserver-observability/test-venv` | Where the test script keeps its virtual environment. It is reused if it exists and belongs to the current user (otherwise the script stops with an error), and created again if it has no working pip; the requirements are installed again on every run. |
| `test-command` (input in `ci.yml` and `release.yml`) | string | `bash scripts/test.sh` | The test command for `ci / lint-test` and for the release build on the tag. Both files must use the same value (a unit test checks it). |
| `archive-name` (input in `release.yml`) | string | `gameserver-observability` | Name of the release asset `<name>-X.Y.Z.tar.gz`. |
| `PROMTOOL_VERSION`, `PROMTOOL_SHA256` (`env:` of the `promtool` job in `ci.yml`) | string | `3.15.0`, the sha256 of its linux-amd64 tarball | The promtool download. Change both together and update [toolchain.md](toolchain.md); a unit test compares them. |
| `GITLEAKS_VERSION`, `GITLEAKS_SHA256` (variables in `scripts/test.sh`) | string | `8.30.1`, the sha256 of its linux-x64 tarball | The gitleaks download that `scripts/test.sh` makes in CI (`CI=true`), so the secret-rule tests run there. Keep them equal to the defaults in `reusable-gitleaks.yml` and to [toolchain.md](toolchain.md); a unit test compares them. |

## Secrets

Secrets never go into this repository, an issue or a log. Pass them through environment variables
or a secret store. CI scans every commit with gitleaks; a leaked secret is rotated first and
removed from history second.

The repository needs no secret today: CI and the release use only the workflow's own
`GITHUB_TOKEN`. Never commit a server license key (`sv_licenseKey`, `cfxk_…`), a txAdmin token or a
password. Where an example needs a license key, write `CHANGE_ME_LICENSE_KEY`, and never start a
placeholder with `cfxk_`. Any `cfxk_` value with 20 or more key characters after the prefix fails
the secret scan, wherever it stands in a line; the only exception is a placeholder made of `x` and
`_` characters. Shorter values such as `cfxk_REPLACE_ME` are not reported, but they still look
like keys, so do not use them either
([ADR 0008](adr/0008-extra-secret-rule-for-any-cfxk-token.md)).
