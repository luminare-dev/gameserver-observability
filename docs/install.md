# Installation

<!-- template: the full installation path. The README quickstart is the short version of this page.
     Every command must work on a clean machine; say which one you tested on and when. -->

## Requirements

| Requirement | Version | Notes |
|---|---|---|
| {{COMPONENT}} | {{SUPPORTED_RANGE}} | |

## Install

```bash
{{QUICKSTART_COMMANDS}}
```

## Verify the release download

Every release has a `SHA256SUMS` file and a build provenance attestation:

```bash
sha256sum -c SHA256SUMS
gh attestation verify <archive>.tar.gz --repo luminare-dev/{{SLUG}}
```

## Check that it works

<!-- template: one command and the output that proves the installation works. -->

## Uninstall

<!-- template: how to remove everything the installation created. -->
