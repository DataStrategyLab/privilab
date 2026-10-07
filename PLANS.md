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


## DSL-154 prospect-demo qualification plan

Governing issue: DSL-154 / P1-01. Start from exact candidate
`f19f5542105661614c225691c3df780264de8262`. DSL-153 and the P0 implementation
chain are complete; no architecture change, new dependency, provider, framework,
storage class, runtime MCP, or hosted deployment is authorized. ADR-003 through
ADR-010 remain controlling.

1. Inventory the current candidate and prior Gate 5 evidence before changing any
   qualification artifact. Preserve the DSL-120 historical package as historical
   evidence; Andrew's 2026-10-05 INTERNAL DEMO READY disposition is recorded in
   Linear and must not be retroactively rewritten into the old repository manifest.
2. Create a versioned AI Release Candidate Manifest binding source SHA, artifact
   or image identity, runtime, dependency state, provider/model configuration,
   prompt/agent configuration, task/corpus/rubric/evaluator identities, permission
   configuration, tools/MCP status, feature flags, and evidence/build provenance.
3. Refresh the exact post-DSL-153 engineering evidence required by DSL-154:
   bootstrap, `make ci`, `git diff --check`, golden eval, preview, package/build,
   permission/isolation/adversarial cases, provenance/history reconstruction, and
   repeat-run stability. Run container checks when the approved environment permits
   Docker access; otherwise preserve the limitation and hand off the exact check.
4. Capture bounded software-supply-chain and open-source evidence without adding
   new runtime frameworks: SBOM where supported, dependency/version/license state,
   relevant advisory findings supplied through an approved current-source step,
   container/base-image identity, and build provenance/attestation where available.
5. Keep fresh external fact checking outside the network-disabled Codex sandbox.
   Codex inventories every mutable vendor/model/framework/license/security claim
   and records what needs current-source verification; an approved external research
   step supplies source/date/result evidence for later consistency checking.
6. Preserve protected-holdout separation. Do not create, alter, or optimize holdout
   content merely to pass qualification. Record either separately approved holdout
   evidence or Andrew's explicit no-holdout condition/deferral.
7. Treat substantive legal/domain review, proposition-level legal-source approval,
   human visual/demo rehearsal, backup-media acceptance, durable Drive promotion,
   non-author review, and final Gate 5 authority as human/system-of-record handoffs.
   Codex may prepare evidence but may not manufacture those approvals.
8. If qualification discovers a material product defect, preserve the failing
   evidence and recommend the smallest bounded corrective issue/PR. Do not expand
   DSL-154 into product implementation. A material correction creates a new
   candidate identity and invalidates only affected evidence.
9. Freeze DSL-154 tooling in commit T, then qualify from a fresh local checkout
   of exact T with no copied virtualenv/database/evidence. Approved local tool,
   interpreter, and dependency caches are permitted; label this environment
   FRESH_CHECKOUT_CACHE_BACKED, not independent network retrieval. Keep the
   product candidate, execution checkout, dependency identity, and limitation
   separate. Historical docs/product/evidence/gate5/ is read-only throughout.
10. Commit the engineering package as H and verify it from a fresh checkout.
    Finish the author session with a clean tree and READY FOR INDEPENDENT CODEX
    REVIEW or NOT READY FOR INDEPENDENT CODEX REVIEW. Do not launch review here.
    Prepare a separate configured GPT-6 Astra reviewer to inspect final H against
    f19f5542105661614c225691c3df780264de8262, including unchanged candidate
    behavior and all DSL-154 tooling/tests/evidence/claims/handoff logic.
11. Recommend DSL-154 In Review only when engineering evidence and independent AI
    review are complete. Prospect-demo release still requires required substantive
    review, holdout disposition, claims/current-fact verification, human rehearsal,
    durable release record, non-author/CODEOWNER review as applicable, and Andrew's
    explicit Gate 5 decision.

Use public, synthetic, anonymized, properly redacted, or properly licensed content
only. Do not retain unnecessary prompt, answer, retrieved-source, secret, client,
matter, OCG, privileged, work-product, or sensitive security content in evidence.
A green test suite, successful rehearsal, or automated evaluator result is evidence,
not release authority.
