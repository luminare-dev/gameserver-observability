# 0008. Extra secret rule for any cfxk_ token

- **Status:** accepted
- **Date:** 2026-10-21

## Context

A game server's license key starts with `cfxk_`, and the platform scans public repositories for
leaked keys. The template's `.gitleaks.toml` has two rules for them: one finds keys of the usual
two-part shape (`cfxk_<letters and digits>_<letters and digits>`) that start at a word boundary,
in any file; the other finds literal values on `sv_licenseKey` lines. A key that does not have the
two-part shape is therefore found only on an `sv_licenseKey` line, and outside such a line a key
right after a word character (for example `LICENSE_KEY_cfxk_…`) is not found at all. This
repository's docs and examples need one placeholder that never looks like a key.

## Considered options

1. Keep the template's `.gitleaks.toml` byte for byte.
2. Add the rules of the `luminare.gameserver` collection: one rule for any `cfxk_` value of key
   length, and an allowlist entry for `CHANGE_ME_…` placeholders on `sv_licenseKey` lines.
3. Rely on GitHub secret scanning and push protection only.

## Decision

Chosen option 2, with the rules copied unchanged from the `luminare.gameserver` collection. The
rule `cfx-license-key-any-shape` matches `cfxk_[A-Za-z0-9_]{20,}` without word boundaries, so it
also fires when the key follows a letter, a digit or `_`, and it allows only the placeholder made
of `x` and `_` characters. The `sv_licenseKey` rule also allows lines with `changeme` or a
`CHANGE_ME_…` value. A `cfxk_` value with fewer than 20 characters after the prefix, such as
`cfxk_REPLACE_ME`, is reported by no rule, so examples never start a placeholder with `cfxk_` and
use `CHANGE_ME_LICENSE_KEY`. The default rules stay on (`[extend] useDefault = true`).
`CfxKeyRuleTest` in `tests/test_pack_repo.py` builds random keys at run time and checks that the
rules find them, also right after a word character, and that placeholders stay clean.
`scripts/test.sh` installs the pinned gitleaks binary in CI, so these tests run in
`ci / lint-test` and in the release build instead of being skipped.

## Consequences

- Good: a key of 20 or more characters in any layout fails `secrets / gitleaks` before it reaches
  a public commit, and the pack and the collection report the same values.
- Bad: the file differs from the template's, so template updates to it are merged by hand, and a
  rule change is made in both repositories.
- Bad: a short made-up `cfxk_` word is not caught; examples avoid the prefix instead.
