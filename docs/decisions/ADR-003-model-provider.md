# ADR-003: Model provider

- Status: Accepted
- Decision owner: Andrew

## Decision

Model execution will be isolated behind a provider contract.
FixtureModelProvider must be implemented and accepted first. OpenAIProvider and
live GPT work remain blocked until P0-10 is accepted.

## Consequences

DSL-105 adds no model SDK, model credentials, provider code, or live eval.
Additional providers require an ADR and approval.
