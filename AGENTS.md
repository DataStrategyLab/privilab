# Repository instructions

These instructions apply to the entire repository.

## Governing authority

Follow the approved Gate 1 PRD, Gate 2 architecture, Gate 3 execution system,
accepted ADRs, and the active Linear issue. Architecture changes require a new
ADR and Andrew's approval.

## Required workflow

1. Work from one Ready Linear issue on an isolated branch/worktree.
2. Keep changes inside the issue scope.
3. Run `make ci`; do not substitute a different verification sequence.
4. Run the issue's preview command when preview validation is required.
5. Run a dedicated Codex `/review` before non-author human review.
6. Resolve all Critical and High findings before merge.
7. Obtain one non-author human approval and Andrew's final merge/release
   decision. Merge does not automatically mean the Linear issue is Done.

## Code Review Rules

Read and follow [.github/CODE_REVIEW.md](.github/CODE_REVIEW.md) for pull-request
reviews, including requests made with `@codex review`. Apply the checks relevant
to the change and preserve the required human approval workflow above.

## Hard boundaries

- Use public, synthetic, anonymized, redacted, or properly licensed content
  only.
- Never add client/matter data, privileged or work-product content, identifiable
  OCGs/engagement terms, restricted legal-database content, credentials, or
  sensitive security findings.
- Do not introduce another framework, runtime provider, database class, hosted
  runtime, DMS integration, autonomous-agent framework, model-controlled tool,
  or runtime MCP without an approved ADR.
- Authorization filtering must occur before source content enters model context.
- Permission states are `ALLOW`, `CONDITIONAL`, `BLOCK`, and `UNKNOWN`; they are
  distinct from Legal AI Readiness G1/G2/G3.
- Critical evaluation and unresolved permissions fail closed.
- Human review remains separate from automated evaluation.

## Linear MCP exception

Linear MCP is approved only as a user-level Codex engineering and
project-management integration. It is not a PriviLAB runtime dependency. Do not
add Linear MCP configuration to this repository or expose client/DMS data or
deployment credentials through it.

## Generated state

Keep `.venv/`, `.tools/`, `.local/`, build products, caches, coverage output,
SQLite files, and local environment files untracked. Do not edit `uv.lock`
manually.
