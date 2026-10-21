# Configuration

<!-- template: every option, with type, default and an example. Generate this table from the
     source (role defaults, schema, CLI help) when the project allows it, so it cannot drift. -->

| Option | Type | Default | Description |
|---|---|---|---|
| `example_option` | string | `""` | What it changes. |

## Secrets

Secrets never go into this repository, an issue or a log. Pass them through environment variables
or a secret store. CI scans every commit with gitleaks; a leaked secret is rotated first and
removed from history second.

<!-- template: name each secret the project needs and where it is read from. -->
