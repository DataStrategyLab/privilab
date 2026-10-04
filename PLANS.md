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

## DSL-120 Gate 5 evidence plan

Governing issue: DSL-120 (Ready, confirmed through approved Linear integration).
Use the prepared branch/worktree at 8d4bad1833431452bd6e99d2c238f5aa51cebbf5.
No pull, new checkout, runtime change, new dependency, or ADR is planned.

1. Add an offline, metadata-only collector and focused regression tests. Exercise
   the six governed cases, separate synthetic decisions, approval denial,
   persistence-invariant history/reopen checks, and an independent safe rerun.
2. Prepare consolidated Gate 5 scripts, claims/limitations, correction-loop
   evidence, backup/human rehearsal checklists, and pending human decision fields.
3. Freeze evidence tooling in a local commit. Record that execution commit as
   evidence_tooling_head_sha, independently of tested_candidate_sha. Keep
   evidence_commit_sha null until an external record binds the final package.
4. Run bootstrap --ci, make ci, diff checking, localhost preview, and collector
   capture using fresh ignored .local/gate5 paths. Export only sanitized summaries.
   Container evidence is supplemental and conditional on approved socket access.
5. Run dedicated configured GPT-6 Astra Codex review; resolve Critical/High and
   explicitly disposition Medium/Low findings. Rerun affected verification.
6. Hand off A–J evidence and recommend In Review only when engineering and AI
   review gates are complete. Human approvals and Andrew's Gate 5 decision remain
   separate; never infer Done from technical completion.

Acceptance follows the issue's complete scenario, minimum-provenance, claims,
review, and release checklist. ADR-004 through ADR-010 remain unchanged. Public
and repository-authored synthetic content only; preserve existing approved asset
hash/license evidence. Substantive review remains DRAFT and prospect eligibility
false; holdout disposition, current-source claims verification, human visual
acceptance, durable Drive promotion, and final release authority remain pending.
A material product change resets the tested candidate; evidence-only recording
and collector tests do not change product behavior. Findings and remaining
blockers will be recorded in docs/product/evidence/gate5/README.md.
