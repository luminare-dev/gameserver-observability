# 0004. Draft releases with checksums and build provenance

- **Status:** accepted
- **Date:** 2026-10-06

## Context

Releases should be reproducible from a tag, verifiable by anyone, and must not change after
publication. Version numbers and the changelog come from Conventional Commit titles.

## Considered options

1. Tags and releases by hand.
2. release-please, with the release published directly and files attached afterwards.
3. release-please creating a draft release with its tag, files attached, then published.

## Decision

Option 3. release-please (`release-type: simple`, `draft` with `force-tag-creation`) keeps a
release pull request open and, when it is merged, creates the tag and a draft release. The same
workflow run tests the tag, builds a `git archive` source tarball, writes `SHA256SUMS`, creates a
SLSA build provenance attestation with `actions/attest` (the successor of
`actions/attest-build-provenance`), attaches the files and publishes the release. Everything stays
in one run because a tag created with `GITHUB_TOKEN` does not start other workflows.

## Consequences

- Good: works with immutable releases; a published release never changes.
- Good: `sha256sum -c SHA256SUMS` and `gh attestation verify` prove where an archive came from.
- Bad: the release pull request has to be closed and reopened once so that the required checks run
  on it.
