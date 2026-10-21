#!/usr/bin/env bash
# The repository's test command. CI (ci.yml) and the release build (release.yml) pass it as the
# reusable workflows' test-command input, so a pull request, the release tag and a local run all
# run the same checks.
#
# It creates a virtual environment outside the repository, installs the hash-pinned
# requirements-test.txt (binary wheels only) and runs the unit tests in tests/. In CI (CI=true)
# it first installs the sha256-pinned gitleaks binary, so that the secret-rule tests run there
# instead of being skipped; locally they run when gitleaks is on the PATH.
#
#   bash scripts/test.sh
#
# TEST_VENV  where the virtual environment goes. Default in CI:
#            $RUNNER_TEMP/gameserver-observability-test-venv; elsewhere:
#            ${XDG_CACHE_HOME:-$HOME/.cache}/gameserver-observability/test-venv.
#            An existing directory is reused only if it belongs to the current user; a
#            virtual environment there without a working pip is created again.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Keep equal to the defaults in .github/workflows/reusable-gitleaks.yml and docs/toolchain.md
# (tests/test_pack_repo.py compares them; bumped by hand, monthly).
GITLEAKS_VERSION=8.30.1
GITLEAKS_SHA256=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb

if [ -n "${RUNNER_TEMP:-}" ]; then
  default_venv="$RUNNER_TEMP/gameserver-observability-test-venv"
else
  default_venv="${XDG_CACHE_HOME:-${HOME:?set HOME or TEST_VENV}/.cache}/gameserver-observability/test-venv"
fi
venv="${TEST_VENV:-$default_venv}"

# Never run a Python that another user put there.
if [ -e "$venv" ] && [ ! -O "$venv" ]; then
  echo "error: $venv exists but does not belong to $(id -un); remove it or set TEST_VENV" >&2
  exit 1
fi
# Create the environment, or create it again when it has no working pip: when an earlier
# `python3 -m venv` stopped half-way (for example without ensurepip), bin/python exists but pip
# does not. Only a folder with a pyvenv.cfg, that is a virtual environment, is cleared.
if ! "$venv/bin/python" -m pip --version >/dev/null 2>&1; then
  if [ -f "$venv/pyvenv.cfg" ]; then
    echo "$venv has no working pip; creating it again" >&2
    python3 -m venv --clear "$venv"
  else
    mkdir -p "$(dirname "$venv")"
    python3 -m venv "$venv"
  fi
fi
"$venv/bin/python" -m pip install --quiet --disable-pip-version-check \
  --require-hashes --only-binary=:all: -r requirements-test.txt

if [ "${CI:-}" = "true" ]; then
  tools="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/gameserver-observability-tools.XXXXXX")"
  release="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}"
  curl -fsSL -o "$tools/gitleaks.tar.gz" "$release/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"
  echo "${GITLEAKS_SHA256}  $tools/gitleaks.tar.gz" | sha256sum -c -
  tar -xzf "$tools/gitleaks.tar.gz" -C "$tools" gitleaks
  export PATH="$tools:$PATH"
  gitleaks version
fi

# Strict: tests that need a package from requirements-test.txt (and, in CI, gitleaks) fail
# instead of skipping.
PACK_TESTS_STRICT=1 "$venv/bin/python" -m unittest discover -s tests -v
