# Code review controls

## Required sequence

1. Author completes issue-scoped implementation and `make ci`.
2. Author records required preview evidence.
3. Dedicated Codex `/review` runs with the configured independent review model.
4. Critical and High findings are resolved before human review.
5. One non-author human approves the change.
6. Required CODEOWNER approvals are present for high-risk paths.
7. Andrew makes the final merge and release decision.
8. Acceptance and preview evidence are reviewed before Linear is marked Done.

## High-risk paths

Security/data policies, architecture and ADRs, CI/workflows, Codex configuration,
bootstrap and secret scanning, dependency/lock files, licenses, permission/domain
contracts, providers, retrieval/storage adapters, and Docker configuration are
high risk.

## CODEOWNERS identities

`@tsintsiruk` and `@adaora-orakwue` are the verified GitHub handles for Andrew
and Adaora. CODEOWNERS is final for the current P0 repository structure.

High-risk changes require the applicable CODEOWNER review controls and at least
one non-author human approval. Andrew retains final merge and release authority.

## Findings

- Critical: blocks merge and release.
- High: blocks merge and release.
- Medium/Low: resolve or document an explicit disposition before release.

Automated evaluation is evidence, not human approval. A green merge check is
necessary but not sufficient for issue completion or release.
