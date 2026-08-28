# ADR-009: Independent review

- Status: Accepted
- Decision owner: Andrew

## Decision

Every change receives a dedicated Codex `/review` before one non-author human
approval. Critical and High findings block merge. Andrew retains final merge and
release authority.

## Consequences

CODEOWNERS protects high-risk paths. Merge does not automatically satisfy issue
acceptance or mark the issue Done.
