# Troubleshooting

## `The virtual environment was not created successfully because ensurepip is not available`

**Cause:** `scripts/test.sh` creates a virtual environment, and Debian and Ubuntu ship the `venv`
module's pip bootstrap in a separate package.

**Fix:** install it (the package name follows the Python version, for example `python3.12-venv`)
and run the script again. The failed run left an environment without pip behind; the script
notices that and creates the environment again (`… has no working pip; creating it again`).

```bash
sudo apt-get install python3-venv
bash scripts/test.sh
```

## `error: … exists but does not belong to …; remove it or set TEST_VENV`

**Cause:** the folder for the test environment (`$TEST_VENV`, see
[configuration](configuration.md)) already exists and belongs to another user. `scripts/test.sh`
refuses to run a Python that someone else could have put there.

**Fix:** check what the folder is, then delete it, or point `TEST_VENV` to a folder of your own,
for example `TEST_VENV="$HOME/.cache/gso-test-venv" bash scripts/test.sh`.

## `ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE`

**Cause:** pip downloaded a file whose sha256 is not listed in `requirements-test.txt`. That
happens when a proxy or mirror serves different files, or when the file was edited by hand.

**Fix:** install from PyPI directly. If `requirements-test.in` changed, compile the file again as
shown on the [toolchain page](toolchain.md) instead of editing hashes by hand.

## `sha256sum: WARNING: 1 computed checksum did NOT match`

**Cause:** the downloaded promtool tarball is not the file the pin expects: the download broke, or
the version and the sha256 were changed separately.

**Fix:** download again; when bumping promtool, take the version and the sha256 from the same
release's `sha256sums.txt` and change both in `ci.yml` and [toolchain.md](toolchain.md).

## `promtool: command not found`

**Cause:** `scripts/check_promtool.sh` expects promtool on the `PATH`.

**Fix:** install it as shown on the [toolchain page](toolchain.md) and add its folder to the
`PATH`, for example `PATH="$PWD:$PATH" bash scripts/check_promtool.sh`.

## Still stuck?

Search the [issues](https://github.com/luminare-dev/gameserver-observability/issues), then ask in
the repository's [Discussions](https://github.com/luminare-dev/gameserver-observability/discussions).
Never post secrets, keys, IP addresses, hostnames or player data; redact logs before you paste
them.
