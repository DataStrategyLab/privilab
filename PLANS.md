# Execution plans

Substantial changes must have an issue-scoped plan before implementation. A plan
records the governing issue, acceptance criteria, architecture decisions,
dependencies, verification stages, preview evidence, license/data impact,
review findings, and remaining blockers.

## DSL-105 bootstrap plan

DSL-105 establishes the approved repository skeleton and makes `make ci` the
canonical local, Codex, and GitHub Actions contract. Product behavior belonging
to DSL-106 and later issues is represented only by explicit placeholders.

Completion requires bootstrap evidence, offline `make ci`, localhost preview,
local-container verification where Docker is available, dedicated Codex review,
one non-author human approval, Andrew's final decision, and an explicit Linear
state update. Merge alone is not completion.
