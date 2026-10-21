# 0003. Secret scanning with the gitleaks binary

- **Status:** accepted
- **Date:** 2026-10-06

## Context

Every commit of a public repository stays readable forever, so the whole history is scanned on
every pull request and push. Game-server license keys are also scanned for by the platform on
public repositories. The repositories live in an organization account.

## Considered options

1. `gitleaks/gitleaks-action`.
2. The gitleaks binary, downloaded and checked against a pinned sha256.
3. Only GitHub secret scanning with push protection.

## Decision

Option 2, in addition to GitHub's push protection. The action needs a licence key secret for
repositories owned by an organization, secrets are not available to fork pull requests, and the
action sends the repository name and owner to a licence-key service. The binary (MIT) needs no
secret, scans the full history (`fetch-depth: 0`) and runs the same way locally. `.gitleaks.toml`
extends the default rules with game-server license keys, `sv_licenseKey` and `TXHOST_API_TOKEN`
values, and Discord webhook URLs.

## Consequences

- Good: the same check for every contributor, locally and in CI, with no secret.
- Good: custom rules for secrets the default rules do not know.
- Bad: the version and sha256 are bumped by hand.
