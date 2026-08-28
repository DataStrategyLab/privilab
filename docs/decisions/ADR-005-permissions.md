# ADR-005: Permissions

- Status: Accepted
- Decision owner: Andrew

## Decision

PriviLAB permission states are `ALLOW`, `CONDITIONAL`, `BLOCK`, and `UNKNOWN`.
They are distinct from Legal AI Readiness G1/G2/G3. Missing material context,
`BLOCK`, `UNKNOWN`, and unresolved `CONDITIONAL` outcomes fail closed.

## Consequences

Permission logic is deterministic and application-controlled, not model-based.
DSL-105 does not implement the vocabulary as runtime product behavior.
