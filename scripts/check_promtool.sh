#!/usr/bin/env bash
# Checks the pack's Prometheus rule files with promtool. The CI job "promtool" (ci.yml) runs it
# with promtool from the official Prometheus release tarball, pinned by version and sha256
# (docs/toolchain.md); run it locally the same way with that promtool on the PATH.
#
#   bash scripts/check_promtool.sh
#
#   rules/*.yml, rules/*.yaml   promtool check rules with every lint check, lint findings fatal
#                               (syntax, PromQL, templates, duplicate rules)
#   tests/rules/*.test.yml      promtool test rules (unit tests with input series and expected
#   (and *.test.yaml)           alerts, annotations and recorded values)
#
# The check fails when rules/ has rule files but tests/rules/ has no rule test at all. What
# promtool cannot see is checked by the unit tests in ci / lint-test (scripts/test.sh):
# RuleCoverageTest in tests/test_pack_repo.py (every rule file is named in the rule_files of a
# rule test) and tests/test_rules.py (every alert has a firing and a quiet case, labels,
# annotations, a runbook section, and so on).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
shopt -s nullglob

promtool --version | head -n 1

rules=(rules/*.yml rules/*.yaml)
tests=(tests/rules/*.test.yml tests/rules/*.test.yaml)

if [ "${#rules[@]}" -eq 0 ]; then
  echo "rules/: no rule files to check"
else
  promtool check rules --lint=all --lint-fatal "${rules[@]}"
fi

if [ "${#tests[@]}" -eq 0 ]; then
  if [ "${#rules[@]}" -gt 0 ]; then
    echo "error: rules/ has rule files, but tests/rules/ has no rule test (*.test.yml or *.test.yaml)" >&2
    exit 1
  fi
  echo "tests/rules/: no rule tests to run"
else
  promtool test rules "${tests[@]}"
fi
