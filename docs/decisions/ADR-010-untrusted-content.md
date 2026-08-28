# ADR-010: Untrusted content

- Status: Accepted
- Decision owner: Andrew

## Decision

Retrieved text, fixtures, prompts, and model output are untrusted content. They
cannot change permissions, retrieve outside authorization scope, invoke tools,
alter critical evaluation policy, or approve release.

## Consequences

Security tests must cover boundary enforcement as relevant behavior is added.
DSL-105 contains only repository-authored public/synthetic placeholder content.
