# 0002. Pin every action and downloaded tool

- **Status:** accepted
- **Date:** 2026-10-06

## Context

Workflows run third-party code with access to the repository token. A tag such as `@v4` can be
moved to different code at any time, and a release download can be replaced. GitHub's security
guidance calls a full commit SHA the only way to use an action as an immutable release.

## Considered options

1. Tags (`@v4`), updated by hand.
2. Full commit SHAs with a `# vX.Y.Z` comment, kept current by Dependabot.
3. Vendoring the actions into the repository.

## Decision

Option 2. Every `uses:` of a remote action or reusable workflow is a 40-character commit SHA with
a version comment; `scripts/check_workflows.py` fails CI otherwise. Dependabot updates the pins
weekly with a 7-day cooldown. Tools that are downloaded in CI (gitleaks, actionlint) are pinned by
version and sha256 from the vendor's checksums file; Python tools are installed with
`pip --require-hashes`. Workflows start from `permissions: {}`, each job asks only for what it
needs, checkouts do not keep credentials, `pull_request_target` is never used and no secret is
passed to fork pull requests.

## Consequences

- Good: a moved tag or replaced download cannot change what CI runs.
- Good: the organization can turn on "Require actions to be pinned to a full-length commit SHA".
- Bad: Dependabot pull requests need review, and the downloaded tools need a manual monthly bump.
