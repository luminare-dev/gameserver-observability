# Installation

The pack's configs, rules and dashboards are not in the repository yet, so there is nothing to
install on a monitoring host today. This page covers what works now: getting the repository,
running its checks, and verifying a release download once releases exist. The commands were run
on Linux (x86-64) on 2026-10-21.

## Requirements

| Requirement | Version | Notes |
|---|---|---|
| git | any recent | to clone the repository |
| Python | 3.10 or newer, with the `venv` module | `scripts/test.sh` creates a virtual environment; on Debian and Ubuntu install `python3-venv` |
| Network access to PyPI | | `scripts/test.sh` installs `requirements-test.txt` (hash-pinned, binary wheels only) |
| promtool | 3.15.0 | optional, for `scripts/check_promtool.sh`; from the official Prometheus tarball ([toolchain](toolchain.md)) |
| gitleaks | 8.30.1 | optional locally; with gitleaks on the `PATH` the tests also check the secret-scan rules. In CI, `scripts/test.sh` installs this version itself |

## Install

```bash
git clone https://github.com/luminare-dev/gameserver-observability.git
cd gameserver-observability
bash scripts/test.sh
```

To run the rule checks as the CI job `promtool` does, install promtool as shown on the
[toolchain page](toolchain.md), put it on the `PATH` and run:

```bash
bash scripts/check_promtool.sh
```

## Verify the release download

Every release has a `SHA256SUMS` file and a build provenance attestation (the attestation only
for releases made while the repository is public):

```bash
sha256sum -c SHA256SUMS
gh attestation verify gameserver-observability-X.Y.Z.tar.gz --repo luminare-dev/gameserver-observability
```

## Check that it works

`bash scripts/test.sh` ends with a summary like this one, from a machine without gitleaks and
markdownlint-cli2 (the tests that need them are skipped; the number of tests grows with the pack):

```text
Ran 116 tests in 1.812s

OK (skipped=10)
```

`bash scripts/check_promtool.sh` prints the promtool version and, while `rules/` is empty:

```text
promtool, version 3.15.0 (branch: HEAD, revision: 5241a27fe3c6983549fccc32f6e65917408c63cd)
rules/: no rule files to check
tests/rules/: no rule tests to run
```

## Uninstall

Delete the clone and the test environment. `scripts/test.sh` keeps its virtual environment in
`$TEST_VENV`, by default `~/.cache/gameserver-observability/test-venv` (under `$XDG_CACHE_HOME`
instead of `~/.cache` when that is set):

```bash
rm -rf gameserver-observability "${XDG_CACHE_HOME:-$HOME/.cache}/gameserver-observability"
```
