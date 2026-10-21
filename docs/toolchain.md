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
| Prometheus (server) | 3.15.0 | `.github/workflows/ci.yml`, job `exporters`, `env:` (the same tarball as promtool) | `prometheus-3.15.0.linux-amd64.tar.gz`, `2a542df32eac02ee17b9d844fb2aa1de00dafa5476579ba8a3ba862e9d572ea0` |
| json_exporter | 0.8.0 | `.github/workflows/ci.yml`, job `exporters`, `env:` | `json_exporter-0.8.0.linux-amd64.tar.gz`, `bd25fe58f62cec131b2ecbe859358990bb07f0266439ddcdef501fdd182a4fe1` |
| blackbox_exporter | 0.29.0 | `.github/workflows/ci.yml`, job `exporters`, `env:` | `blackbox_exporter-0.29.0.linux-amd64.tar.gz`, `5512929259bb6164f68ebe20ce433ec43b8609e3a79c95324f5020e931488fb4` |

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

The json_exporter and blackbox_exporter sha256 values are the lines for the `linux-amd64`
tarballs in each release's `sha256sums.txt`
(<https://github.com/prometheus-community/json_exporter/releases/download/v0.8.0/sha256sums.txt>,
<https://github.com/prometheus/blackbox_exporter/releases/download/v0.29.0/sha256sums.txt>); both
downloads were checked against them with `sha256sum -c` on 2026-10-21, and they were the latest
releases that day. For `scripts/smoke_exporters.py` put the three binaries into one folder and
pass it with `--bin-dir`, or put them on the `PATH`:

```bash
mkdir -p bin
curl -fsSLO https://github.com/prometheus-community/json_exporter/releases/download/v0.8.0/json_exporter-0.8.0.linux-amd64.tar.gz
echo "bd25fe58f62cec131b2ecbe859358990bb07f0266439ddcdef501fdd182a4fe1  json_exporter-0.8.0.linux-amd64.tar.gz" | sha256sum -c -
tar -xzf json_exporter-0.8.0.linux-amd64.tar.gz -C bin --strip-components=1 json_exporter-0.8.0.linux-amd64/json_exporter
curl -fsSLO https://github.com/prometheus/blackbox_exporter/releases/download/v0.29.0/blackbox_exporter-0.29.0.linux-amd64.tar.gz
echo "5512929259bb6164f68ebe20ce433ec43b8609e3a79c95324f5020e931488fb4  blackbox_exporter-0.29.0.linux-amd64.tar.gz" | sha256sum -c -
tar -xzf blackbox_exporter-0.29.0.linux-amd64.tar.gz -C bin --strip-components=1 blackbox_exporter-0.29.0.linux-amd64/blackbox_exporter
tar -xzf prometheus-3.15.0.linux-amd64.tar.gz -C bin --strip-components=1 prometheus-3.15.0.linux-amd64/prometheus
python3 scripts/smoke_exporters.py --bin-dir bin
```

## Container images

The [demo stack](demo.md) (`demo/docker-compose.yml`) and its CI job `demo-smoke` pull these
images, each pinned by the digest of its multi-platform index. Each digest is the one
`docker pull` gave for the tag on 2026-10-21, and each image was pulled again by that digest:

| Image | Version | Pinned as |
|---|---|---|
| Prometheus | 3.15.0 | `prom/prometheus:v3.15.0@sha256:efd719c99d83b060d9daefdcf00360461adf279f45ef5391f8d111892118753e` |
| json_exporter | 0.8.0 | `quay.io/prometheuscommunity/json-exporter:v0.8.0@sha256:3aad20d41a0b31dfaaf7ab1a091440e92a82a61ef68b76750eac0ad50a983652` |
| blackbox_exporter | 0.29.0 | `prom/blackbox-exporter:v0.29.0@sha256:9613f2884689b6fad9f1939f6a3b0388c93a022cfaededb19545b329b5c83dea` |
| Grafana (OSS) | 13.2.4 | `grafana/grafana:13.2.4@sha256:dbbc38ea21103cefb50396340cd88afec779c7e070b0a7bf5a75b4ce46651d3f` |
| Python, for the simulated server | 3.13.16 | `python:3.13-slim@sha256:cf50a4f6ac4f026458b08d5222023d700ac806410dff5e9ca8728fa44f2b850f` |

The versions are those of the binaries above and of the Grafana the dashboards are checked with
(`GRAFANA_VERSION` in `scripts/lint_dashboards.py`); `tests/test_demo.py` fails when they differ
and when an image is not in this table. Bump an image together with its binary: read the digest
with `docker buildx imagetools inspect <image>:<tag>`, change the tag and the digest in
`demo/docker-compose.yml` and here, and run `python3 scripts/smoke_demo.py`. The Dependabot entry
for the demo ignores version updates, so that it proposes only a new digest under the same tag
(`.github/dependabot.yml`; this entry has not run yet).

## Checked locally, not in CI

The dashboard check of 2026-10-21 (README, Results) ran the dashboard on a real Grafana with the
exporters whose series its host, MariaDB and tunnel rows read. CI does not download these; the
dashboard check in CI (`scripts/lint_dashboards.py`) needs only Python and promtool. The
pictures in `docs/media/` were taken from the demo stack with headless Chromium from the image
below, driven by Playwright for Python 1.64.0 and labelled with Pillow 13.0.0, both installed
with pip into a throwaway virtual environment, without Playwright's own browser download
([demo](demo.md#pictures)). The downloads were checked against the checksums named below:

| Tool | Version | File or image, sha256 |
|---|---|---|
| Grafana | 13.2.4 | image `grafana/grafana:13.2.4@sha256:dbbc38ea21103cefb50396340cd88afec779c7e070b0a7bf5a75b4ce46651d3f` |
| node_exporter | 1.12.1 | `node_exporter-1.12.1.linux-amd64.tar.gz`, `b51d8a76aa2a9156a55d501aca6276fae09e262259a5e4e831d2c2222f084e63` (the release's `sha256sums.txt`) |
| mysqld_exporter | 0.20.0 | `mysqld_exporter-0.20.0.linux-amd64.tar.gz`, `5773496e9962ca3817b3599fe4d74f218c95c1295eb2a742462df8e035fe51bd` (the release's `sha256sums.txt`) |
| cloudflared | 2026.10.2 | `cloudflared-linux-amd64`, `35fbdd2beb378436c7da377d7358cea8e33f9c94a6705d1d8036bf9b0d6d8005` (the checksum in the release notes) |
| MariaDB | 11.8.9 | image `mariadb:11.8@sha256:f16d7a344413e519dff518f27bdb221388f84b0d274c97c4fb5f2cb0dc1b34fa` |
| Chromium (headless shell) | 156.0.8078.48 | image `chromedp/headless-shell@sha256:3da74b0945e4f80f00f0310bcda9f76cee283539ebd200a053a7bebf3de89423` |

`scripts/lint_dashboards.py` records the Grafana version and its dashboard schema version (42)
in `GRAFANA_VERSION` and `SCHEMA_VERSION`; a dashboard saved by a newer Grafana fails the check
until it has been tried on that version and both values are updated.

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
  cooldown (`.github/dependabot.yml`). For the demo images it is set to open them only for a new
  digest under the same tag.
- promtool, Prometheus, json_exporter, blackbox_exporter, gitleaks and actionlint: once a month,
  read the latest release and its checksums file, change the version and sha256 together, and
  update the table above. `tests/test_pack_repo.py` fails when the promtool or exporter pins in
  `ci.yml` and this page disagree, when the `exporters` job uses another Prometheus than the
  `promtool` job, and when the gitleaks pin in `scripts/test.sh`, the defaults in
  `reusable-gitleaks.yml` and this page disagree. After bumping an exporter, run
  `scripts/smoke_exporters.py` and check the [metrics reference](metrics.md) against its output;
  after bumping Prometheus and promtool, run `bash scripts/check_promtool.sh` as well. Bump the
  demo image of the same tool in the same change ([container images](#container-images)).
- The `python:3.12-slim` digest above: before recompiling `requirements-test.txt` by hand, read
  the current digest with `docker buildx imagetools inspect python:3.12-slim` and update the
  command and its date (Dependabot recompiles the file in its own environment).
