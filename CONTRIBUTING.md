# Contributing

PriviLAB changes follow the Gate 3 issue-to-release workflow.

## Before implementation

- Confirm the Linear issue is Ready or In Progress and defines scope,
  acceptance criteria, tests, security/data constraints, and preview needs.
- Read `AGENTS.md`, the relevant ADRs, and current repository instructions.
- Stop for approval before any architecture drift or unapproved dependency.

## Verification and review

- Bootstrap with `./scripts/bootstrap.sh` and verify with `make ci`.
- Never make live evals or paid/model calls part of `make ci`.
- Run a dedicated Codex `/review`; `.codex/config.toml` selects the independent
  review model.
- Critical and High findings block merge.
- Obtain one non-author human approval. High-risk paths additionally require a
  CODEOWNER review once all verified CODEOWNER identities are present.
- Andrew has final merge and release authority.
- A merged PR still requires acceptance, preview, and Linear completion evidence
  before the issue is Done.

## Pull requests

Keep PRs linked to one issue and include verification output, preview evidence,
data/license changes, limitations, and review findings. Do not include secrets
or client data in code, fixtures, screenshots, logs, or PR text.
