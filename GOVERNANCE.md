# Project governance

PriviLAB is maintained by Data Strategy Lab as a Developer Preview reference
implementation. This document explains the existing contribution and decision
process; it does not create new approval powers or change the project license.

## Responsibilities

| Role | Responsibility |
| --- | --- |
| Contributors | Propose bounded changes, explain their behavior, provide verification evidence, and contribute only material they have the right to share. |
| Maintainers and code owners | Triage proposals, review changes within their expertise, protect repository boundaries, and document unresolved concerns. |
| Creator and Lead Architect | Andrew Tsintsiruk (`@tsintsiruk`) makes final architecture, merge, and release decisions under the existing review requirements. |

[CODEOWNERS](.github/CODEOWNERS) identifies the applicable review owners:
`@tsintsiruk` and `@NaveenGali11`. Ownership does not replace
non-author review, establish availability for every request, or allow an author
to approve their own change. GitHub evaluates CODEOWNERS from the PR's base branch
until a change merges. See the [review controls](docs/review/code_review.md).

[Contributor acknowledgments](CONTRIBUTORS.md) recognize current and historical
contributions separately from active review responsibilities.

## Proposals and decisions

Start with a non-sensitive [GitHub issue](https://github.com/DataStrategyLab/privilab/issues)
describing the problem, intended behavior, scope, and observable acceptance
criteria. Public contributors do not need access to private Linear; maintainers
coordinate the accepted engineering scope. Small documentation corrections can
use the bounded process described in [Contributing](CONTRIBUTING.md).

Use issue and PR discussion to explain evidence, alternatives, and trade-offs.
Architecture changes require an accepted architecture decision record and the
Lead Architect's approval before implementation. Existing
[ADRs](docs/decisions/README.md) and [repository instructions](AGENTS.md) govern
implementation boundaries. A roadmap item or review comment alone does not
authorize a new architecture or expanded deployment scope.

Maintainers should explain requested changes or rejection with concrete reasons.
Contributors may ask for clarification or offer new evidence in the same thread.
Keep discussion respectful and follow the [Code of Conduct](CODE_OF_CONDUCT.md).
Use its private reporting process for conduct concerns, and
[SECURITY.md](SECURITY.md) for sensitive security matters.

## Review and release

Follow the [contribution workflow](CONTRIBUTING.md) and
[pull request review guide](.github/CODE_REVIEW.md). The existing process requires
canonical `make ci` verification, any required preview evidence, dedicated Codex
review, one non-author human approval, and applicable CODEOWNER approvals.
Critical and High findings block merge; other findings need an explicit
disposition. Automated checks and reviews are evidence, not human approval.

Reviewers disclose relevant authorship or conflicts and distinguish what they
independently checked from reported results. Approval applies to the reviewed
revision and scope; changes require updated review evidence as appropriate.
Code ownership does not waive these requirements, including for work authored
by the Lead Architect.

Final merge, publication, and release decisions remain with Andrew Tsintsiruk.
A merged PR does not automatically establish issue acceptance, authorize a
release, or qualify an artifact for production or prospect use. The
[release-status document](docs/release-status.md) records the applicable boundaries.
Document the actual decision and released revision without treating a planned
date or a passing test as publication approval.

## Policy changes and contribution rights

Propose changes to governance, ownership, or review rules through a scoped PR
with the same verification and non-author review requirements. Changes must be
consistent with accepted decisions or include the required decision update.

[LICENSE](LICENSE), [NOTICE](NOTICE), the [license guide](licenses/README.md),
and [contribution terms](CONTRIBUTING.md#contribution-rights) govern reuse and
submission rights. This document adds no CLA, copyright transfer, or trademark
permission. For usage questions and support limits, see [SUPPORT.md](SUPPORT.md).
