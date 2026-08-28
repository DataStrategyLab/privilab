# ADR-006: Evaluation

- Status: Accepted
- Decision owner: Andrew

## Decision

Evaluation is explicit, versioned, and deterministic for critical release
criteria. Critical evaluation failures fail closed. Human review is a separate
control and is not replaced by automated evaluation.

## Consequences

DSL-105 reports the fixture smoke eval as `NOT APPLICABLE / SKIPPED`; no behavior
harness exists and no passing product-eval evidence is claimed.
