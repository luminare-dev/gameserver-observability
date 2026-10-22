# Runbook

One section per alert or failure. The pack's alert rules are not in the repository yet; what runs
today is the repository's own automation, so this page covers its failures.

## Failure: the release build fails on the tag

| | |
|---|---|
| **Meaning** | The release workflow created the tag `vX.Y.Z` and a draft release, but the `build` job failed: `bash scripts/test.sh` on the tag, or packing the archive. |
| **Impact** | The draft release has no files and stays unpublished; users see no new release. |
| **Diagnosis** | Open the failed run under Actions → release, job `build`. Run `git checkout vX.Y.Z && bash scripts/test.sh` locally to reproduce. |
| **Mitigation** | Nothing is published, so nothing has to be withdrawn. If the failure was transient (a download or PyPI timeout), use **Re-run failed jobs** on the run; the jobs check out the same tag again. |
| **Fix** | Fix the cause in a pull request. The version in `.release-please-manifest.json` already moved to X.Y.Z, so the fix is released under the next version number. Delete the unpublished draft release and its tag, so the broken version does not linger. |

## Failure: the release pull request shows no checks

| | |
|---|---|
| **Meaning** | release-please opened or updated its pull request with `GITHUB_TOKEN`, and changes made with that token do not start other workflows. |
| **Impact** | The required checks never report, so the pull request cannot be merged. |
| **Diagnosis** | The pull request `chore(main): release X.Y.Z` lists no runs of `ci` or `pr`. |
| **Mitigation** | Close the pull request and reopen it once; that starts the checks. |
| **Fix** | None needed; this is how `GITHUB_TOKEN` works ([ADR 0004](adr/0004-draft-releases-with-checksums-and-provenance.md)). |

## Failure: the `promtool` job fails

| | |
|---|---|
| **Meaning** | The promtool download did not match its pinned sha256, or `scripts/check_promtool.sh` reported invalid rules, a failing rule test, or rule files while `tests/rules/` has no rule test at all. (A rule file that no rule test names in `rule_files` fails `RuleCoverageTest` in `ci / lint-test` instead.) |
| **Impact** | The pull request should not be merged; rules that do not load or are untested would ship in the next release. |
| **Diagnosis** | Read the job log: `sha256sum` errors point to the download, `promtool check rules` and `promtool test rules` print the file, rule and expected versus actual alerts. Reproduce with `bash scripts/check_promtool.sh` and promtool 3.15.0. |
| **Mitigation** | Fix the rule or its test in the same pull request. |
| **Fix** | For checksum errors, take the version and the sha256 from the same Prometheus release ([toolchain](toolchain.md)). |
