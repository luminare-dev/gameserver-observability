# 0001. Record architecture decisions

- **Status:** accepted
- **Date:** 2026-10-06

## Context

Decisions about this project (tools, structure, interfaces, trade-offs) need to stay
understandable for reviewers, contributors and the maintainer months later, without reading the
whole history.

## Considered options

1. Architecture Decision Records in the repository, one Markdown file per decision.
2. A wiki page.
3. Decisions only in issues and pull requests.

## Decision

Chosen option: ADRs in `docs/adr/`, in the MADR-lite format of
[0000-template.md](0000-template.md), because they are versioned with the code, reviewed in the
same pull requests and published with the documentation.

## Consequences

- Good: every significant decision has a short, dated record with the options that were rejected.
- Good: the README's "Design decisions" section links the important ones.
- Bad: writing an ADR takes about 10 minutes; small, reversible choices do not need one.
