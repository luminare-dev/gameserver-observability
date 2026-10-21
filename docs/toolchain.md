# Toolchain and pins

Every tool that CI downloads or installs is pinned: actions by commit SHA (Dependabot keeps them
current), binaries by version and sha256, Python packages by version and sha256
([ADR 0002](adr/0002-pin-actions-and-downloaded-tools.md)). This page lists the pins this
repository adds to the template's and how to bump them. Values checked on 2026-10-21.

## Downloaded binaries

| Tool | Version | Where it is pinned | File and sha256 |
|---|---|---|---|
| promtool (Prometheus) | 3.15.0 | `.github/workflows/ci.yml`, job `promtool`, `env:` | `prometheus-3.15.0.linux-amd64.tar.gz`, `2a542df32eac02ee17b9d844fb2aa1de00dafa5476579ba8a3ba862e9d572ea0` |
| gitleaks | 8.30.1 | `.github/workflows/reusable-gitleaks.yml` (template, `secrets / gitleaks`) and `scripts/test.sh` (`GITLEAKS_VERSION`, `GITLEAKS_SHA256`, used in CI for the secret-rule tests) | `gitleaks_8.30.1_linux_x64.tar.gz`, `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb` |
| actionlint | 1.7.12 | `.github/workflows/reusable-ci.yml` (template) | `actionlint_1.7.12_linux_amd64.tar.gz`, `8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8` |

The promtool sha256 is the line for `prometheus-3.15.0.linux-amd64.tar.gz` in the release's
`sha256sums.txt`
(<https://github.com/prometheus/prometheus/releases/download/v3.15.0/sha256sums.txt>); the
download was checked against it with `sha256sum -c` on 2026-10-21. promtool comes from the same
tarball as the Prometheus server ([ADR 0006](adr/0006-promtool-from-the-official-release-tarball.md)).

Local install (the same steps as the CI job):

```bash
curl -fsSLO https://github.com/prometheus/prometheus/releases/download/v3.15.0/prometheus-3.15.0.linux-amd64.tar.gz
echo "2a542df32eac02ee17b9d844fb2aa1de00dafa5476579ba8a3ba862e9d572ea0  prometheus-3.15.0.linux-amd64.tar.gz" | sha256sum -c -
tar -xzf prometheus-3.15.0.linux-amd64.tar.gz --strip-components=1 prometheus-3.15.0.linux-amd64/promtool
./promtool --version
```

## Python packages

| File | Used by | How it is installed |
|---|---|---|
| `requirements-dev.txt` | yamllint and zizmor in `ci / lint-test` (template) | `pip install --require-hashes --only-binary=:all:` in the job's virtual environment |
| `requirements-test.txt` (compiled from `requirements-test.in`) | the unit tests (`scripts/test.sh`): PyYAML 6.0.3 | the same flags, in a separate virtual environment that `scripts/test.sh` creates ([ADR 0007](adr/0007-one-test-script-with-hash-pinned-requirements.md)) |

`requirements-test.txt` is compiled with Python 3.12, the Python of the GitHub `ubuntu-24.04`
runner, and pip-tools 7.5.2. The compile runs in the `python:3.12-slim` image (Python 3.12.15),
pinned by the digest it had on 2026-10-21, because the machine has no Python 3.12:

```bash
cmd='pip-compile --generate-hashes --strip-extras --output-file=requirements-test.txt requirements-test.in'
docker run --rm -v "$PWD":/w -w /w -e CUSTOM_COMPILE_COMMAND="$cmd" \
  python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 \
  sh -c "pip install --quiet pip-tools==7.5.2 && $cmd"
```

`CUSTOM_COMPILE_COMMAND` makes the file's header show the command that ran. Without it,
pip-tools 7.5.2 writes the options in its own order and adds a `--no-index` that was not given,
and that header command fails when run as written. Running the command above on 2026-10-21, with
and without an existing `requirements-test.txt`, gave the committed file byte for byte.

pip-tools itself is installed by version only, not by hash: the compile step is a helper, and
what is trusted is its output, the hash-pinned `requirements-test.txt` that is reviewed in the pull
request and installed with `--require-hashes`.

## Bumping

- Actions and Python packages: Dependabot opens grouped pull requests every Monday after a 7-day
  cooldown (`.github/dependabot.yml`).
- promtool, gitleaks and actionlint: once a month, read the latest release and its checksums file,
  change the version and sha256 together, and update the table above.
  `tests/test_pack_repo.py` fails when the promtool pin in `ci.yml` and this page disagree, and
  when the gitleaks pin in `scripts/test.sh`, the defaults in `reusable-gitleaks.yml` and this
  page disagree.
- The `python:3.12-slim` digest above: before recompiling `requirements-test.txt` by hand, read
  the current digest with `docker buildx imagetools inspect python:3.12-slim` and update the
  command and its date (Dependabot recompiles the file in its own environment).
