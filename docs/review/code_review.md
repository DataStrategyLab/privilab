# Code review controls

## Requesting a Codex review

Comment `@codex review` on the pull request. The root
[AGENTS.md](../../AGENTS.md) directs Codex to the shared
[pull request review guide](../../.github/CODE_REVIEW.md), which defines review
scope, evidence standards, actionable feedback, and private security reporting.
Maintainers coordinate the configured dedicated review and retain the required
human approval sequence below. A GitHub review request does not configure or
prove which model executed it; record the actual available review evidence.

## Required sequence

1. Author completes issue-scoped implementation and `make ci`.
2. Author records required preview evidence.
3. Dedicated Codex `/review` runs with the configured independent review model.
4. Critical and High findings are resolved before human review.
5. One non-author human approves the change.
6. Required CODEOWNER approvals are present for high-risk paths.
7. Andrew makes the final merge and release decision.
8. Acceptance and preview evidence are reviewed before issue completion is
   recorded. Public contributors use the public issue/PR; maintainers separately
   reconcile any private Linear state. Private-system access is not required.

## High-risk paths

Security/data policies, architecture and ADRs, CI/workflows, Codex configuration,
bootstrap and secret scanning, dependency/lock files, licenses, permission/domain
contracts, providers, retrieval/storage adapters, and Docker configuration are
high risk.

## CODEOWNERS identities

`@tsintsiruk` and `@NaveenGali11` are the GitHub handles for Andrew and Naveen.
All 19 existing CODEOWNERS patterns name both active owners.
CODEOWNERS is final for these active patterns and identities.
GitHub uses the PR base branch's CODEOWNERS until a change merges. Adding a PR
author as an owner does not make their self-review a non-author approval.

High-risk changes require the applicable CODEOWNER review controls and at least
one non-author human approval. Andrew retains final merge and release authority.

Historical review contributions remain credited in
[Contributors and acknowledgments](../../CONTRIBUTORS.md). A change in active
ownership does not change the attribution, version, or scope of earlier reviews.

## Findings

- Critical: blocks merge and release.
- High: blocks merge and release.
- Medium/Low: resolve or document an explicit disposition before release.

Automated evaluation is evidence, not human approval. A green merge check is
necessary but not sufficient for issue completion or release.
