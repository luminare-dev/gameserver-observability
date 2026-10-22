# 0006. promtool from the official release tarball

- **Status:** accepted
- **Date:** 2026-10-21

## Context

Rules are only useful when they are checked and tested: `promtool check rules` catches syntax and
PromQL errors, `promtool test rules` runs unit tests with input series and expected alerts. CI
needs promtool in a known version. The organization allows only GitHub-owned actions plus three
named third-party actions, and every downloaded tool must be pinned
([ADR 0002](0002-pin-actions-and-downloaded-tools.md)).

## Considered options

1. The official tarball `prometheus-<version>.linux-amd64.tar.gz` from the Prometheus GitHub
   release, checked against the release's `sha256sums.txt`.
2. The `prom/prometheus` container image, pinned by digest, run with `--entrypoint promtool`.
3. A third-party setup action from the Marketplace.

## Decision

Chosen option: "official tarball", because it is the same download as for a binary install of the
Prometheus server, needs no container runtime, and works the same way locally and in CI. The CI
job `promtool` downloads version 3.15.0, checks the pinned sha256 with `sha256sum -c`, extracts
only `promtool` and runs `scripts/check_promtool.sh`. The script checks `rules/*.yml` (and
`*.yaml`), runs `tests/rules/*.test.yml`, and fails when rule files exist without any rule test;
a unit test in `ci / lint-test` checks that every rule file is named in the `rule_files` of a rule
test. Option 3 is not on the allow-list; option 2 needs a Docker pull for a single binary.

## Consequences

- Good: a replaced release asset fails the job; the version is visible in the workflow and in
  [docs/toolchain.md](../toolchain.md), and a test keeps the two equal.
- Bad: Dependabot does not see the pin; it is bumped by hand with the other downloaded tools.
- Bad: the `promtool` job is not one of the four required checks yet; it is added to the ruleset
  once it has run on a pull request.
