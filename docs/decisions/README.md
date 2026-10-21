# Architecture decisions

Accepted decisions govern implementation. Documentation reflects the existing
architecture; new frameworks/providers/database classes/hosted runtime/DMS or
model-controlled tools require an approved ADR and Andrew's approval.

| ADR | Decision |
| --- | --- |
| [001](ADR-001-application-topology.md) | Python modular-monolith application topology |
| [002](ADR-002-runtime-boundary.md) | Runtime boundary |
| [003](ADR-003-model-provider.md) | Provider contract and fixture-first path |
| [004](ADR-004-retrieval.md) | Authorization-scoped retrieval |
| [005](ADR-005-permissions.md) | Permission states and fail-closed behavior |
| [006](ADR-006-evaluation.md) | Versioned evaluation and critical gate |
| [007](ADR-007-provenance.md) | Minimum application-owned provenance |
| [008](ADR-008-preview-deployment.md) | Local preview/deployment scope |
| [009](ADR-009-independent-review.md) | Dedicated Codex and non-author human review |
| [010](ADR-010-untrusted-content.md) | Untrusted text cannot redefine authority |

[Decision log](decision-log.md) records dated refinements. Model/provider aliases
and tooling versions in historical decisions retain their historical context;
current configuration and release-status evidence determine the current scope.
